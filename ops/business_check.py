#!/usr/bin/env python3
"""Read-only consistency checks for the current business round.

This command deliberately imports no application modules, performs no migrations,
and emits counts/error codes only. Archived rounds are counted, never reconciled
against the current round. Run against a local SQLite file, not a network share.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


REQUIRED_TABLES = ('customers', 'products', 'orders', 'receipts', 'sales_returns', 'statement_documents')


def check_database(database):
    errors = Counter()
    counts = {}
    report = {'version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'scope': 'current_business_round', 'read_only': True}

    def fail(kind):
        errors[kind] += 1

    def cents(value, kind, positive=False):
        if type(value) is not int or value < 0 or positive and value == 0:
            fail(kind)
            return None
        return value

    def payloads(connection, table):
        result = []
        for row in connection.execute('SELECT id,payload FROM '+table):
            try:
                value = json.loads(row['payload'])
                if not isinstance(value, dict):
                    raise ValueError()
            except (ValueError, TypeError, RecursionError):
                fail(table+'.invalid_payload')
                continue
            if value.get('id') != row['id']:
                fail(table+'.payload_id_mismatch')
            result.append((row['id'], value))
        return result

    connection = None
    try:
        uri = Path(database).expanduser().resolve().as_uri()+'?mode=ro'
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = set(REQUIRED_TABLES)-tables
        for _ in missing:
            fail('schema.missing_required_table')
        if not missing:
            for table in REQUIRED_TABLES:
                counts[table] = connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            for table in ('archived_orders', 'trial_archives'):
                counts[table+'_excluded'] = connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] if table in tables else 0
            customers = {r[0] for r in connection.execute('SELECT id FROM customers')}
            products = {r[0] for r in connection.execute('SELECT id FROM products')}
            orders = dict(payloads(connection, 'orders'))
            receipts = payloads(connection, 'receipts')
            returns = payloads(connection, 'sales_returns')
            paid = defaultdict(int)
            discounts = defaultdict(int)
            roundings = defaultdict(int)
            credited = defaultdict(int)

            for order in orders.values():
                if order.get('customer_id') not in customers:
                    fail('orders.customer_missing')
                lines = order.get('lines')
                if not isinstance(lines, list) or not lines:
                    fail('orders.invalid_lines')
                    continue
                for line in lines:
                    if not isinstance(line, dict) or line.get('product_id') not in products:
                        fail('orders.product_missing')

            for _, receipt in receipts:
                amount = cents(receipt.get('amount_cents'), 'receipts.invalid_amount')
                oid = receipt.get('order_id')
                order = orders.get(oid) if isinstance(oid, str) else None
                if order is None:
                    fail('receipts.order_missing')
                    continue
                if receipt.get('customer_id') != order.get('customer_id'):
                    fail('receipts.customer_mismatch')
                if not receipt.get('voided') and order.get('state') != 'reviewed':
                    fail('receipts.order_not_reviewed')
                discount=cents(receipt.get('discount_cents',0),'receipts.invalid_discount')
                rounding=cents(receipt.get('rounding_cents',0),'receipts.invalid_rounding')
                if receipt.get('voided'):
                    # 冲销流水保留原记录但不计入已收；冲销理由必须留痕。
                    if not str(receipt.get('void_reason') or '').strip():fail('receipts.void_reason_missing')
                    continue
                if amount is not None:
                    paid[oid] += amount
                if discount is not None:discounts[oid]+=discount
                if rounding is not None:roundings[oid]+=rounding
                if None not in (amount,discount,rounding) and amount+discount+rounding<=0:fail('receipts.empty_reduction')

            for _, returned in returns:
                if returned.get('customer_id') not in customers:
                    fail('returns.customer_missing')
                if returned.get('product_id') not in products:
                    fail('returns.product_missing')
                finance = returned.get('finance')
                if finance is None:
                    continue
                if not isinstance(finance, dict):
                    fail('returns.invalid_finance')
                    continue
                if returned.get('voided'):
                    # 冲销抵扣后按普通流程作废是允许的：保留 reversed 财务快照，
                    # 但必须已无有效抵扣与退款；其他 voided 带财务的记录仍是错误。
                    if not (finance.get('state') == 'reversed' and not finance.get('allocations') and not finance.get('refunds')):
                        fail('returns.voided_has_finance')
                    continue
                if finance.get('state') != 'posted':
                    if finance.get('allocations') or finance.get('refunds'):
                        fail('returns.unposted_has_allocations_or_refunds')
                    continue
                amount = cents(finance.get('amount_cents'), 'returns.invalid_credit_amount')
                allocations = finance.get('allocations', [])
                refunds = finance.get('refunds', [])
                if not isinstance(allocations, list) or not isinstance(refunds, list):
                    fail('returns.invalid_allocation_or_refund_list')
                    continue
                allocated = refunded = 0
                for allocation in allocations:
                    if not isinstance(allocation, dict):
                        fail('returns.invalid_allocation')
                        continue
                    value = cents(allocation.get('amount_cents'), 'returns.invalid_allocation_amount', positive=True)
                    if value is not None:
                        allocated += value
                    oid = allocation.get('order_id')
                    order = orders.get(oid) if isinstance(oid, str) else None
                    if order is None:
                        fail('returns.allocation_order_missing')
                        continue
                    if order.get('customer_id') != returned.get('customer_id'):
                        fail('returns.allocation_customer_mismatch')
                    if order.get('state') != 'reviewed':
                        fail('returns.allocation_order_not_reviewed')
                    if value is not None:
                        credited[oid] += value
                for refund in refunds:
                    if not isinstance(refund, dict):
                        fail('returns.invalid_refund')
                        continue
                    value = cents(refund.get('amount_cents'), 'returns.invalid_refund_amount', positive=True)
                    if value is not None:
                        refunded += value
                if amount is not None:
                    # Wallet is intentionally derived, not a second stored amount.
                    # The conservation identity is amount = allocated + refunded
                    # + wallet; a negative wallet means the credit was overspent.
                    wallet = amount-allocated-refunded
                    if wallet < 0:
                        fail('returns.negative_wallet')

            for oid, order in orders.items():
                total = cents(order.get('total_cents'), 'orders.invalid_total')
                paid_amount = cents(order.get('paid_cents'), 'orders.invalid_paid_amount')
                credit = cents(order.get('return_credit_cents', 0), 'orders.invalid_return_credit')
                if paid_amount is not None and paid_amount != paid[oid]:
                    fail('orders.paid_receipts_mismatch')
                if credit is not None and credit != credited[oid]:
                    fail('orders.return_credit_allocations_mismatch')
                discount=cents(order.get('discount_cents',0),'orders.invalid_discount')
                rounding=cents(order.get('rounding_cents',0),'orders.invalid_rounding')
                if discount is not None and discount!=discounts[oid]:fail('orders.discount_receipts_mismatch')
                if rounding is not None and rounding!=roundings[oid]:fail('orders.rounding_receipts_mismatch')
                if discount is not None and rounding is not None and total is not None and paid_amount is not None and credit is not None and total-paid_amount-credit-discount-rounding < 0:
                    fail('orders.negative_receivable')

            resource_tables={'material_items','material_entries','indirect_expenses','byproduct_sales','resource_periods'}
            if resource_tables <= tables:
                from decimal import Decimal,InvalidOperation
                try:
                    materials={r['id']:dict(r) for r in connection.execute('SELECT * FROM material_items')}
                    material_quantities=defaultdict(Decimal)
                    for table in resource_tables:counts[table]=connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                    entries=[e for _,e in payloads(connection,'material_entries') if not e.get('voided')]
                    for e in sorted(entries,key=lambda e:(e['business_date'],e['sequence'])):
                        if e['material_id'] not in materials:fail('materials.item_missing');continue
                        q=Decimal(e['qty'])
                        if not q.is_finite() or q<=0:fail('materials.invalid_quantity');continue
                        if e['unit']!=materials[e['material_id']]['unit']:fail('materials.unit_mismatch')
                        if e['kind'] not in ('opening','receipt','return','gain','consume','loss','transfer'):fail('materials.invalid_kind');continue
                        cents(e.get('amount_cents'),'materials.invalid_amount')
                        key=(e['material_id'],e.get('warehouse_id') or ('WH-UNASSIGNED' if e['material_id']=='RM-SOY' else 'WH-COMMON'))
                        material_quantities[key]+=q if e['kind'] in ('opening','receipt','return','gain') else -q
                        if material_quantities[key]<0:fail('materials.negative_inventory')
                        if e['kind']=='transfer':material_quantities[(e['material_id'],e['target_warehouse_id'])]+=q
                    for _,e in payloads(connection,'indirect_expenses'):
                        if not e.get('voided'):cents(e.get('amount_cents'),'expenses.invalid_amount',positive=True)
                    metered=[]
                    for _,e in payloads(connection,'indirect_expenses'):
                        if e.get('voided') or e.get('accrual_method')!='service_days':continue
                        scope=(e.get('category'),e.get('service_account'),e.get('counterparty_id') or e.get('supplier_id') or e.get('partner',''))
                        if sum(p['amount_cents'] for p in e.get('accruals',[]))!=e.get('amount_cents'):fail('expenses.coverage_amount_mismatch')
                        if not e.get('service_account') or not e.get('service_start') or not e.get('service_end') or e['service_start']>=e['service_end']:fail('expenses.invalid_coverage');continue
                        for prior_scope,prior in metered:
                            if scope==prior_scope and max(e['service_start'],prior['service_start'])<min(e['service_end'],prior['service_end']):fail('expenses.coverage_overlap')
                        metered.append((scope,e))
                    if 'expense_estimates' in tables:
                        estimates=dict(payloads(connection,'expense_estimates'));counts['expense_estimates']=len(estimates)
                        for estimate in estimates.values():
                            cents(estimate.get('amount_cents'),'expense_estimates.invalid_amount',positive=not bool(estimate.get('close_source')))
                            if estimate.get('payment_mode')!='estimate':fail('expense_estimates.payment_not_allowed')
                            if sum(p['amount_cents'] for p in estimate.get('accruals',[]))!=estimate.get('amount_cents'):fail('expense_estimates.accrual_mismatch')
                        for _,expense in payloads(connection,'indirect_expenses'):
                            if any(key not in estimates for key in expense.get('estimate_ids',[])):fail('expense_estimates.source_missing')
                    if {'expense_reviews','expense_payments'}<=tables:
                        fees=dict(payloads(connection,'indirect_expenses'));reviews=[r for _,r in payloads(connection,'expense_reviews')];paid=defaultdict(int)
                        for table in ('expense_reviews','expense_payments'):counts[table]=connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                        for r in reviews:
                            if r.get('expense_id') not in fees or r.get('decision') not in ('approve','return'):fail('expenses.invalid_review')
                        for _,p in payloads(connection,'expense_payments'):
                            fee=fees.get(p.get('expense_id'));value=cents(p.get('amount_cents'),'expenses.invalid_payment',positive=True)
                            if not fee:fail('expenses.payment_source_missing');continue
                            if fee.get('voided') or fee['category'].startswith('wages-') or fee['category']=='depreciation':fail('expenses.payment_not_allowed')
                            approvals=[r for r in reviews if r.get('expense_id')==fee['id'] and r.get('expense_version',0)<p.get('expense_version',0)]
                            if not approvals or max(approvals,key=lambda r:r['expense_version'])['decision']!='approve':fail('expenses.payment_not_reviewed')
                            if value is not None:paid[fee['id']]+=value
                        for key,value in paid.items():
                            if value>fees[key]['amount_cents']:fail('expenses.negative_payable')
                    for _,e in payloads(connection,'byproduct_sales'):
                        if e.get('voided'):continue
                        total=cents(e.get('amount_cents'),'byproducts.invalid_amount',positive=True);paid=cents(e.get('received_cents'),'byproducts.invalid_received')
                        if total is not None and paid is not None and paid>total:fail('byproducts.negative_receivable')
                except (ValueError,TypeError,KeyError,InvalidOperation):fail('resources.invalid_ledger')

            purchase_tables={'suppliers','purchase_orders','purchase_receipts','purchase_payments'}
            if purchase_tables <= tables:
                from decimal import Decimal,InvalidOperation
                try:
                    for table in purchase_tables:counts[table]=connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                    suppliers=dict(payloads(connection,'suppliers'));pos=dict(payloads(connection,'purchase_orders'));grs=dict(payloads(connection,'purchase_receipts'));pps=dict(payloads(connection,'purchase_payments'));mts=dict(payloads(connection,'material_entries'))
                    charges=dict(payloads(connection,'purchase_charges')) if 'purchase_charges' in tables else {}
                    if 'purchase_charges' in tables:counts['purchase_charges']=len(charges)
                    payees=dict(payloads(connection,'purchase_payees')) if 'purchase_payees' in tables else {}
                    drivers={r[0]:r[1] for r in connection.execute('SELECT id,name FROM delivery_drivers')}
                    charge_allocations=defaultdict(int);charges_paid=defaultdict(int)
                    for cid,charge in charges.items():
                        cents(charge.get('amount_cents'),'purchase.charge_amount_invalid',positive=True)
                        if charge.get('billing_unit') not in ('公斤','吨') or charge.get('kind') not in ('freight','unloading'):fail('purchase.charge_pricing_invalid')
                        if int((Decimal(charge['billing_qty'])*Decimal(charge['rate'])*100).quantize(Decimal(1),rounding='ROUND_HALF_UP'))!=charge['amount_cents']:fail('purchase.charge_pricing_mismatch')
                        if charge.get('receipt_id') not in grs:fail('purchase.charge_reference_missing')
                        kind=charge.get('payee_type','supplier');pid=charge.get('payee_id','')
                        if kind=='supplier':
                            if charge.get('supplier_id') not in suppliers or (pid and pid!=charge.get('supplier_id')):fail('purchase.charge_payee_missing')
                        elif kind in ('driver','worker','other'):
                            person=payees.get(pid)
                            if not charge.get('payee_name') or charge.get('supplier_id') or not ((person and person['kind']==kind and person['name']==charge['payee_name']) or (kind=='driver' and pid.startswith('fleet:') and pid[6:] in drivers)):fail('purchase.charge_payee_missing')
                        else:fail('purchase.charge_payee_missing')
                        if sum(a['amount_cents'] for a in charge['allocations'])!=charge['amount_cents']:fail('purchase.charge_allocation_mismatch')
                        for a in charge['allocations']:
                            charge_allocations[a['material_entry_id']]+=a['amount_cents']
                            if a['material_entry_id'] not in mts:fail('purchase.charge_material_missing')
                            elif mts[a['material_entry_id']].get('purchase_receipt_id')!=charge['receipt_id']:fail('purchase.charge_receipt_mismatch')
                    received_qty=defaultdict(Decimal);received_cents=defaultdict(int);paid_cents=defaultdict(int);seen_entries=set()
                    for rid,r in grs.items():
                        o=pos.get(r.get('order_id'))
                        if not o:fail('purchase.receipt_order_missing');continue
                        if o['state']=='draft' or o['state']=='cancelled':fail('purchase.receipt_order_state')
                        if r['supplier_id']!=o['supplier_id']:fail('purchase.receipt_supplier_mismatch')
                        value=cents(r['amount_cents'],'purchase.receipt_amount_invalid',positive=True)
                        if value!=sum(l['amount_cents'] for l in r['lines']):fail('purchase.receipt_amount_mismatch')
                        received_cents[o['id']]+=value or 0
                        for l in r['lines']:
                            line=next((x for x in o['lines'] if x['id']==l['line_id']),None);entry=mts.get(l['material_entry_id']);q=Decimal(l['qty'])
                            if not q.is_finite() or q<=0:fail('purchase.receipt_quantity_invalid');continue
                            received_qty[(o['id'],l['line_id'])]+=q
                            if not line or l['material_id']!=line['material_id'] or l['unit']!=line['unit']:fail('purchase.receipt_line_mismatch')
                            if not entry or entry.get('voided') or entry.get('purchase_receipt_id')!=rid or entry.get('purchase_order_id')!=o['id'] or entry.get('material_id')!=l['material_id'] or Decimal(entry['qty'])!=q or entry['amount_cents']!=l['amount_cents']+charge_allocations[l['material_entry_id']] or entry['business_date']!=r['business_date']:fail('purchase.material_link_mismatch')
                            if l['material_entry_id'] in seen_entries:fail('purchase.material_duplicate_link')
                            seen_entries.add(l['material_entry_id'])
                    for _,pay in pps.items():
                        if pay.get('charge_id'):
                            ch=charges.get(pay['charge_id'])
                            if not ch or ch['supplier_id']!=pay['supplier_id'] or ch['order_id']!=pay['order_id']:fail('purchase.charge_payment_reference_mismatch')
                            if ch and any(pay.get(k)!=ch.get(k) for k in ('payee_type','payee_id','payee_name')):fail('purchase.charge_payment_payee_mismatch')
                            charges_paid[pay['charge_id']]+=cents(pay['amount_cents'],'purchase.charge_payment_invalid',positive=True) or 0
                            continue
                        o=pos.get(pay.get('order_id'))
                        if not o:fail('purchase.payment_order_missing');continue
                        if pay['supplier_id']!=o['supplier_id']:fail('purchase.payment_supplier_mismatch')
                        paid_cents[o['id']]+=cents(pay['amount_cents'],'purchase.payment_amount_invalid',positive=True) or 0
                    for cid,ch in charges.items():
                        if charges_paid[cid]>ch['amount_cents']:fail('purchase.charge_overpayment')
                    for oid,o in pos.items():
                        if o['supplier_id'] not in suppliers:fail('purchase.supplier_missing')
                        if o['state'] not in ('draft','confirmed','closed','cancelled'):fail('purchase.order_state_invalid')
                        if len({l['id'] for l in o['lines']})!=len(o['lines']):fail('purchase.line_duplicate')
                        total=cents(o['total_cents'],'purchase.order_amount_invalid',positive=True)
                        if total!=sum(l['amount_cents'] for l in o['lines']):fail('purchase.order_amount_mismatch')
                        if paid_cents[oid]>received_cents[oid] or received_cents[oid]>total:fail('purchase.negative_payable_or_overreceipt')
                        for l in o['lines']:
                            q=Decimal(l['qty'])
                            if not q.is_finite() or q<=0 or received_qty[(oid,l['id'])]>q:fail('purchase.order_quantity_invalid')
                            if l['material_id'] not in materials or l['unit']!=materials[l['material_id']]['unit']:fail('purchase.material_master_mismatch')
                    for mid,e in mts.items():
                        if e.get('purchase_receipt_id') and mid not in seen_entries:fail('purchase.material_orphan_link')
                except (ValueError,TypeError,KeyError,InvalidOperation):fail('purchase.invalid_ledger')

            for table in ('statement_documents','byproduct_statements'):
                if table not in tables:continue
                for row in connection.execute('SELECT payload,content_hash FROM '+table):
                    raw = row['payload']
                    if not isinstance(raw, str) or hashlib.sha256(raw.encode('utf-8')).hexdigest() != row['content_hash']:
                        fail('statements.content_hash_mismatch')
    except (sqlite3.Error, OSError, ValueError, TypeError):
        # Never echo SQL, file paths, payloads, identifiers, or exception strings.
        fail('database.read_error')
    finally:
        if connection is not None:
            connection.rollback()
            connection.close()
    report.update(ok=not errors, counts=counts, error_count=sum(errors.values()),
                  errors=[{'type': kind, 'count': count} for kind, count in sorted(errors.items())])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='只读核对当前业务轮次的引用、收款、退货抵扣及归档哈希；仅输出计数和错误类型')
    parser.add_argument('--database', required=True, type=Path, help='SQLite 数据库路径（mode=ro，不初始化、不迁移）')
    args = parser.parse_args(argv)
    report = check_database(args.database)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
