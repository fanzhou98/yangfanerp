"""Workshop consumption and packaging reconciliation; caller owns transactions."""
import calendar
import json
import hashlib
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import resources_costs as rc


def settings(c, mid, month=None):
    month = month or date.today().strftime('%Y-%m')
    row = c.execute("SELECT value FROM meta WHERE key='material_cost_settings'").fetchone()
    versions = (json.loads(row[0]) if row else {}).get(mid, [])
    return next((v for v in reversed(sorted(versions, key=lambda v: v['cost_from'])) if v['cost_from'] <= month),
                {'cost_mode': 'legacy', 'cost_from': '', 'bag_units': '1', 'packaging_rates': {}})


def save_settings(c, mid, body):
    if 'cost_mode' not in body:
        return
    mode = body['cost_mode']
    if mode not in ('legacy', 'issue', 'count', 'amortize'):
        raise ValueError('成本方式无效')
    month = str(body.get('cost_from') or date.today().strftime('%Y-%m'))
    rc.day(month + '-01'); rc.open_period(c, month + '-01')
    if any(p['state'] == 'closed' and p['month'] >= month for p in rc.rows(c, 'resource_periods')):
        raise ValueError('后续成本月份已结账，请先重开再修改成本方式')
    units = rc.qty(body.get('bag_units') or '1', '每库存单位折合袋数', True)
    raw = body.get('packaging_rates') or {}
    if not isinstance(raw, dict):
        raise ValueError('包装用量格式无效')
    rates = {}
    for pid, value in raw.items():
        if value in ('', None): continue
        if not c.execute('SELECT 1 FROM products WHERE id=?', (pid,)).fetchone():
            raise ValueError('包装承担产品不存在')
        rates[pid] = rc.ds(rc.qty(value, '每产品单位用袋数', True))
    if mode == 'count' and int(body.get('amortize_months') or 1) > 1:
        raise ValueError('盘点实耗与跨月摊销不能同时使用')
    if mode == 'amortize' and int(body.get('amortize_months') or 1) < 2:
        raise ValueError('跨月摊销须至少2个月')
    row = c.execute("SELECT value FROM meta WHERE key='material_cost_settings'").fetchone()
    values = json.loads(row[0]) if row else {}
    versions = [v for v in values.get(mid, []) if v['cost_from'] != month]
    versions.append({'cost_mode': mode, 'cost_from': month, 'bag_units': rc.ds(units), 'packaging_rates': rates, 'product_ids': body.get('default_product_ids') or []})
    values[mid] = sorted(versions, key=lambda v: v['cost_from'])
    c.execute("INSERT INTO meta VALUES('material_cost_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (rc.dump(values),))


def production(c, month):
    """Confirmed ordinary warehouse output plus processing output, each once."""
    totals = {}; missing = set()
    for plan in rc.rows(c, 'warehouse_plans'):
        if not plan['business_date'].startswith(month): continue
        for row in plan.get('stock', []):
            pid = row['product_id']
            if row.get('produced_qty') in ('', None): missing.add(pid)
            else: totals[pid] = totals.get(pid, Decimal(0)) + Decimal(row['produced_qty'])
    for batch in rc.rows(c, 'processing_batches'):
        if batch.get('voided') or not batch['business_date'].startswith(month): continue
        for row in batch.get('outputs', []):
            pid = row['product_id']
            totals[pid] = totals.get(pid, Decimal(0)) + Decimal(row.get('qty') or 0)
    return totals, missing


def report(c, month):
    rc.day(month + '-01')
    idx = rc.month_index(month) - 1
    previous = '%04d-%02d' % (idx // 12, idx % 12 + 1)
    prior = rc._workshop_records(c, previous); current = rc._workshop_records(c, month)
    masters = {r['id']: dict(r) for r in c.execute('SELECT * FROM material_items')}
    _, ledger = rc.material_ledger(c, month + '-%02d' % calendar.monthrange(int(month[:4]), int(month[5:]))[1])
    amortized = {r['entry_id'] for r in rc.amortizations(c)}
    issues = {}; targets = {}; sources = {}
    for e in ledger:
        if e.get('voided') or e['id'] in amortized or not e['business_date'].startswith(month) or e['kind'] not in ('consume', 'return'): continue
        mid = e['material_id']; sign = -1 if e['kind'] == 'return' else 1
        d = issues.setdefault(mid, {'qty': Decimal(0), 'cents': 0, 'entries': 0})
        d['qty'] += Decimal(e['qty']) * sign; d['cents'] += int(e.get('cost_cents') or 0) * sign; d['entries'] += 1
        targets.setdefault(mid, set()).update(e.get('product_ids') or ([e['product_id']] if e.get('product_id') else []))
        sources.setdefault(mid, []).append({k: e.get(k) for k in ('id', 'business_date', 'kind', 'qty', 'cost_cents', 'uncosted_out_qty', 'product_id', 'product_ids')})
    output, missing = production(c, month)
    result = []
    closed = any(p['month'] == month and p['state'] == 'closed' for p in rc.rows(c, 'resource_periods'))
    for mid in sorted(set(issues) | set(prior) | set(current)):
        item = masters.get(mid)
        if not item or mid == 'RM-SOY': continue
        cfg = settings(c, mid, month)
        if cfg['cost_mode'] in ('issue', 'amortize'): continue
        d = issues.get(mid, {'qty': Decimal(0), 'cents': 0, 'entries': 0})
        p = prior.get(mid) or {}; cur = current.get(mid) or {}
        opening = Decimal(str(p.get('qty_close') or 0)); opening_cents = int(p.get('closing_cents') or 0)
        available = opening + d['qty']; value = opening_cents + d['cents']
        unit = Decimal(value) / available if available > 0 else Decimal(0)
        counted = cur.get('qty_close') not in ('', None)
        closing = Decimal(cur['qty_close']) if counted else None
        # Existing saved valuations remain snapshots until explicitly recounted.
        close_cents = int(cur['closing_cents']) if counted and cur.get('closing_cents') not in ('', None) else None
        actual = value - close_cents if close_cents is not None else None
        used = available - closing if counted else None
        ids = sorted(set(cfg.get('product_ids') or []) | targets.get(mid, set()) | set(p.get('product_ids') or []))
        rates = cfg['packaging_rates']; weights = {pid: output.get(pid, Decimal(0)) * Decimal(rate) for pid, rate in rates.items()}
        complete = bool(rates) and not (set(rates) & missing) and set(rates) <= set(output)
        expected = sum(weights.values(), Decimal(0)) if complete else None
        actual_bags = used * Decimal(cfg['bag_units']) if used is not None else None
        fingerprint = hashlib.sha256(json.dumps({'prior': p, 'issues': sorted(sources.get(mid, []), key=lambda e: e['id']), 'settings': cfg, 'weights': {pid: rc.ds(weight) for pid, weight in weights.items()}, 'complete': complete}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        stale = counted and not closed and cur.get('source_fingerprint') != fingerprint
        result.append({'material_id': mid, 'material_name': item['name'], 'unit': item['unit'], **cfg,
            'qty_open': rc.ds(opening), 'qty_in': rc.ds(d['qty']), 'qty_close': rc.ds(closing) if counted else '',
            'opening_cents': opening_cents, 'issue_cents': d['cents'], 'closing_cents': close_cents if counted else '',
            'actual_cents': actual if actual is not None else '', 'unit_cents': rc.ds(unit),
            'entries': d['entries'], 'note': cur.get('note', ''), 'version': int(cur.get('version') or 0),
            'counted': counted, 'prior_missing': not p, 'over_issue': bool(counted and closing > available),
            'stale_count': stale, 'source_fingerprint': fingerprint,
            'product_ids': sorted(set(rates)) if rates else ids,
            'allocation_weights': {pid: rc.ds(weight) for pid, weight in weights.items()} if complete else {},
            'packaging_expected': rc.ds(expected) if expected is not None else None,
            'packaging_actual': rc.ds(actual_bags) if actual_bags is not None else None,
            'packaging_difference': rc.ds(actual_bags - expected) if actual_bags is not None and expected is not None else None,
            'packaging_status': '已核对产量' if complete else '包装规格或生产量待补',
            'packaging_pending': bool(rates) and (not complete or sum(weights.values(), Decimal(0)) <= 0)})
    return {'month': month, 'rows': result, 'total_issue_cents': sum(r['issue_cents'] for r in result),
            'total_actual_cents': sum(r['actual_cents'] for r in result if r['actual_cents'] != '' and not r['stale_count'] and not r['over_issue']),
            'counted': sum(r['counted'] and not r['stale_count'] and not r['over_issue'] for r in result), 'unclosed': sum(not r['counted'] or r['stale_count'] or r['over_issue'] for r in result)}


def cost_entries(c, month, entries):
    """Replace net issues with actual consumption, including opening-only months."""
    value = report(c, month); counted = {r['material_id']: r for r in value['rows'] if r['counted'] and not r['over_issue'] and not r['stale_count']}
    kept = [e for e in entries if e['material_id'] not in counted or e['kind'] not in ('consume', 'return')]
    adjustments = {}
    for mid, row in counted.items():
        ids = row['product_ids']
        kept.append({'id': 'WS-' + month + '-' + mid, 'business_date': month + '-01', 'material_id': mid,
            'material_name': row['material_name'], 'kind': 'consume', 'qty': rc.ds(Decimal(row['qty_open']) + Decimal(row['qty_in']) - Decimal(row['qty_close'])),
            'cost_cents': row['actual_cents'], 'product_ids': ids, 'product_id': ids[0] if len(ids) == 1 else '',
            'coverage_start':month+'-01','coverage_end':month+'-%02d'%calendar.monthrange(int(month[:4]),int(month[5:]))[1],
            'allocation_weights': row['allocation_weights'], 'packaging_pending': row['packaging_pending'],
            'allocation_basis': 'packaging' if row['packaging_rates'] else '', 'unit': row['unit']})
        adjustments[mid] = row['actual_cents'] - row['issue_cents']
    return kept, adjustments, value


def closing_issues(c, month, value=None):
    value = value if value is not None else report(c, month)
    errors = []
    for row in value['rows']:
        label = row['material_name']
        if row['stale_count']:
            errors.append(label + ' 领退料、计价或产量依据已变化，请重新盘点核对并保存')
        elif row['over_issue']:
            errors.append(label + ' 期末盘点超过可用余料，请核对')
        elif row['cost_mode'] == 'count' and not row['counted'] and (Decimal(row['qty_open']) or Decimal(row['qty_in'])):
            errors.append(label + ' 尚未完成月末盘点')
        elif row['counted'] and row['packaging_pending'] and row['actual_cents']:
            errors.append(label + ' 包装成本待分配，请补齐包装规格与生产量')
    return errors
