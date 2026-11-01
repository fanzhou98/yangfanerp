"""期初应收收款：独立于订单，按客户冲减期初余额，并进入资金流水。"""
import json, secrets
import resources_costs as rc
import erp_access


def save(c, b, role, now, audit):
    erp_access.require_role(role, 'finance.receipt')
    action = b.get('action') or 'create'
    if action == 'void':
        rid = rc.text(b.get('id'), '收款编号', 40)
        row = c.execute('SELECT payload FROM receipts WHERE id=?', (rid,)).fetchone()
        if not row:
            raise ValueError('期初收款不存在')
        old = json.loads(row[0])
        if old.get('order_id') or old.get('kind') != 'opening':
            raise ValueError('该流水不是期初应收收款')
        rc.open_period(c, str(old.get('received_date') or '')[:10])
        if old.get('voided'):
            raise ValueError('该期初收款已冲销')
        reason = rc.text(b.get('reason'), '冲销原因', 200)
        voided = {**old, 'voided': True, 'void_reason': reason, 'voided_at': now,
                  'voided_by': role, 'version': int(old.get('version', 0)) + 1}
        c.execute('UPDATE receipts SET payload=? WHERE id=?', (rc.dump(voided), rid))
        audit(c, role, '冲销期初应收收款', rid, old, voided)
        return voided
    if action != 'create':
        raise ValueError('期初收款操作无效')
    cid = rc.text(b.get('customer_id'), '客户', 40)
    row = c.execute('SELECT id,name,opening_cents,opening_date FROM customers WHERE id=?', (cid,)).fetchone()
    if not row:
        raise ValueError('客户不存在')
    customer = {'id': row['id'], 'name': row['name'], 'opening_cents': row['opening_cents'], 'opening_date': row['opening_date'] or ''}
    opening = int(customer.get('opening_cents') or 0)
    if opening <= 0:
        raise ValueError('该客户没有期初应收')
    amount = rc.cents(b.get('amount'), '收款金额', True)
    discount = rc.cents(b.get('discount', '0'), '折扣')
    rounding = rc.cents(b.get('rounding', '0'), '抹零')
    total = amount + discount + rounding
    if total <= 0:
        raise ValueError('到账、折扣和抹零合计必须大于0')
    received_date = rc.day(b.get('received_date'))
    today = now[:10]
    rc.open_period(c, received_date)
    if received_date > today:
        raise ValueError('到账日期不能晚于今天')
    if received_date < (customer.get('opening_date') or ''):
        raise ValueError('到账日期不能早于该客户期初日期')
    paid = rc.opening_receipts_paid(c, today).get(cid, 0)
    remaining = opening - paid
    if total > remaining:
        raise ValueError('到账、折扣和抹零合计不能超过该客户期初应收未收余额')
    if (discount or rounding) and not str(b.get('note', '')).strip():
        raise ValueError('有折扣或抹零时请填写原因或凭据备注')
    receipt = {
        'id': 'OR-' + secrets.token_hex(5).upper(), 'order_id': '', 'kind': 'opening',
        'customer_id': cid, 'customer_name': customer.get('name', ''),
        'amount_cents': amount, 'discount_cents': discount, 'rounding_cents': rounding,
        'account_id': rc.fund_account(c, b), 'received_date': received_date,
        'method': rc.text(b.get('method'), '收款方式', 40),
        'note': rc.text(b.get('note', ''), '收款备注', 500, False),
        'at': now, 'role': role, 'version': 1,
    }
    c.execute('INSERT INTO receipts(id,payload) VALUES(?,?)', (receipt['id'], rc.dump(receipt)))
    audit(c, role, '登记期初应收收款', receipt['id'], None, receipt)
    return receipt
