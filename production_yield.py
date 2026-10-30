"""生产日出品率 FIFO 台账。

结算公斤默认只反映“当天复核的发货”，若当天发出的货包含昨日结转，结算均重会被结转货
稀释。这里按生产日排出一条先进先出队列：每天先扣减结转框数（用其生产日登记的约当
单框重量），剩余自有发货的结算公斤才用于计算当天生产框数的约当产出重量。

队列只依赖订单、生产日报、盘库结存与领料流水；不额外落库，按月份缓存并在源数据
变化（哈希变化）时重算。跨月结转通过逐月传递队列实现，月结快照不重写历史。
"""
import hashlib
import json
from decimal import Decimal

import resources_costs as rc

RULE = 'production-day-fifo-v1'
_CACHE = {}
_TABLES = ('orders', 'factory_daily', 'stock_closings', 'material_entries', 'factory_scrap')


def _path(c):
    try:
        return c.execute('PRAGMA database_list').fetchone()[2] or ''
    except Exception:
        return ''


def _first_month(c):
    months = set()
    for table in _TABLES:
        try:
            row = c.execute("SELECT MIN(substr(json_extract(payload,'$.business_date'),1,7)) FROM " + table).fetchone()
        except Exception:
            continue
        if row and row[0]:
            months.add(row[0])
    return min(months) if months else None


def _next_month(month):
    y, m = int(month[:4]), int(month[5:7])
    return f'{y + (m == 12):04d}-{1 if m == 12 else m + 1:02d}'


def _month_hash(c, month):
    h = hashlib.sha256(month.encode())
    lo, hi = month + '-01', _next_month(month) + '-01'
    for table in _TABLES:
        try:
            rows = c.execute("SELECT id,payload FROM " + table + " WHERE json_extract(payload,'$.business_date')>=? AND json_extract(payload,'$.business_date')<? ORDER BY id", (lo, hi)).fetchall()
        except Exception:
            rows = []
        for row in rows:
            h.update(str(row[0]).encode())
            h.update(row[1].encode())
    return h.hexdigest()


def _settled_kg(line):
    if line.get('billing_unit') == '公斤' and line.get('bill_qty') not in ('', None):
        try:
            q = Decimal(line['bill_qty'])
        except Exception:
            return None
        return q if q.is_finite() and q >= 0 else None
    return None


def _shipments(c, month):
    result = {}
    for o in rc.rows(c, 'orders'):
        if o.get('business_date', '')[:7] != month:
            continue
        for line in o.get('lines', []):
            qty = Decimal(line.get('actual_qty') or '0')
            if qty <= 0:
                continue
            key = (o['business_date'], line['product_id'])
            item = result.setdefault(key, {'qty': Decimal(0), 'kg': Decimal(0), 'missing': False, 'pending': False})
            if o.get('state') != 'reviewed':
                item['pending'] = True
                continue
            item['qty'] += qty
            kg = _settled_kg(line)
            if kg is None:
                item['missing'] = True
            else:
                item['kg'] += kg
    return result


def _active_days(c, month):
    days = set()
    lo, hi = month + '-01', _next_month(month) + '-01'
    for table in ('orders', 'factory_daily', 'stock_closings'):
        try:
            for row in c.execute("SELECT DISTINCT json_extract(payload,'$.business_date') FROM " + table + " WHERE json_extract(payload,'$.business_date')>=? AND json_extract(payload,'$.business_date')<?", (lo, hi)):
                if row[0]:
                    days.add(row[0])
        except Exception:
            continue
    return sorted(days)


def _consume(queue, qty, w_last):
    """Consume qty crates FIFO; return (consumed crates, consumed kg, kg fully known)."""
    consumed = Decimal(0)
    kg = Decimal(0)
    known = True
    while qty > 0 and queue:
        day, have, weight = queue[0]
        use = min(qty, have)
        if weight is None:
            weight = w_last
        if weight is None:
            known = False
        else:
            kg += use * weight
        consumed += use
        qty -= use
        if use >= have:
            queue.pop(0)
        else:
            queue[0] = (day, have - use, queue[0][2])
    return consumed, kg, known


def _compute_month(c, month, settings_fn, weight_fn, opening):
    import production_daily
    queue = {pid: [tuple(x) for x in items] for pid, items in opening.items()}
    w_last = {}
    for pid, items in queue.items():
        for _, _, weight in reversed(items):
            if weight is not None:
                w_last[pid] = Decimal(str(weight))
                break
    products = {r['id']: dict(r) for r in c.execute('SELECT * FROM products')}
    ships = _shipments(c, month)
    rows = {}
    for day in _active_days(c, month):
        report = production_daily.report(c, day, settings_fn(), weight_fn)
        prod = {p['product_id']: p for p in report.get('products', [])}
        touched = {pid for (d, pid) in ships if d == day}
        for pid in set(prod) | touched | set(queue):
            product = products.get(pid, {})
            p = prod.get(pid, {})
            unit = p.get('unit') or product.get('unit') or ''
            qty = Decimal(p['derived_qty']) if p.get('derived_qty') not in (None, '') else None
            bean = p.get('processing_input_kg') if p.get('processing_source_name') else p.get('bean_kg')
            bean = Decimal(bean) if bean not in (None, '') else None
            ship = ships.get((day, pid))
            Q = ship['qty'] if ship else Decimal(0)
            pending = bool(ship and ship.get('pending'))
            S = ship['kg'] if ship and not ship['missing'] else None
            if qty is None and Q <= 0 and not p:
                continue
            carry = queue.setdefault(pid, [])
            before = sum((x[1] for x in carry), Decimal(0))
            row = {'day': day, 'product_id': pid,
                   'product_name': p.get('product_name') or product.get('name') or pid,
                   'unit': unit,
                   'production_qty': rc.ds(qty) if qty is not None else None,
                   'settlement_qty': rc.ds(Q),
                   'settlement_kg': rc.ds(S) if S is not None else None,
                   'carry_before': rc.ds(before), 'carry_after': None,
                   'unit_kg': None, 'production_kg': None,
                   'bean_kg': rc.ds(bean) if bean is not None else None,
                   'yield': None, 'own_kg': None, 'status': '待盘库'}
            if unit == '公斤':
                row['production_kg'] = rc.ds(qty) if qty is not None else None
                row['own_kg'] = rc.ds(S) if S is not None else None
                row['unit_kg'] = '1'
                row['status'] = '待复核（当日发货未复核）' if pending else '结算口径' if qty is not None else '待盘库'
            else:
                consumed, value, known = _consume(carry, min(Q, before), w_last.get(pid))
                own = Q - consumed
                weight = None
                if own > 0:
                    if S is not None and known and S - value >= 0:
                        weight = (S - value) / own
                        row['status'] = '结算口径'
                    else:
                        weight = w_last.get(pid)
                        row['status'] = '估算（自有发货待复核或缺结算公斤）'
                elif qty is not None:
                    weight = w_last.get(pid)
                    if pending:
                        row['status'] = '待复核（当日发货未复核）'
                    else:
                        row['status'] = '估算（当日无自有发货）' if Q == 0 else '估算（当日发货均为结转）'
                if weight is not None:
                    w_last[pid] = weight
                    row['unit_kg'] = rc.ds(weight)
                    if qty is not None:
                        row['production_kg'] = rc.ds(qty * weight)
                    if S is not None:
                        row['own_kg'] = rc.ds(S - value)
                if qty is not None:
                    remain = qty - own
                    if remain > 0:
                        carry.append((day, remain, weight))
            row['carry_after'] = rc.ds(sum((x[1] for x in carry), Decimal(0)))
            if bean is not None and row['production_kg'] is not None and bean > 0:
                row['yield'] = rc.ds(Decimal(row['production_kg']) / bean)
            rows[(day, pid)] = row
    return rows, queue


def _month(c, month, settings_fn, weight_fn):
    path = _path(c)
    first = _first_month(c)
    if first is None or first > month:
        return {'rows': {}, 'opening': {}, 'closing': {}, 'month': month}
    opening = {}
    chain = hashlib.sha256(b'').hexdigest()
    m = first
    while m <= month:
        digest = _month_hash(c, m)
        chain = hashlib.sha256((chain + digest).encode()).hexdigest()
        cached = _CACHE.get((path, m))
        if cached and cached['hash'] == chain:
            data = cached['data']
        else:
            rows, closing = _compute_month(c, m, settings_fn, weight_fn, opening)
            data = {'rows': rows, 'opening': opening, 'closing': closing, 'month': m}
            _CACHE[(path, m)] = {'hash': chain, 'data': data}
        opening = data['closing']
        m = _next_month(m)
    return _CACHE[(path, month)]['data']


def day(c, day, settings_fn, weight_fn):
    data = _month(c, day[:7], settings_fn, weight_fn)
    return {pid: row for (d, pid), row in data['rows'].items() if d == day}


def month_summary(c, month, settings_fn, weight_fn):
    data = _month(c, month, settings_fn, weight_fn)
    result = {}
    for (d, pid), row in data['rows'].items():
        item = result.setdefault(pid, {'production_kg': Decimal(0), 'own_kg': Decimal(0), 'bean_kg': Decimal(0),
                                       'pending_days': 0, 'days': 0, 'statuses': set()})
        if row['production_kg'] is not None:
            item['production_kg'] += Decimal(row['production_kg'])
            item['days'] += 1
        if row['own_kg'] is not None:
            item['own_kg'] += Decimal(row['own_kg'])
        if row['bean_kg'] is not None:
            item['bean_kg'] += Decimal(row['bean_kg'])
        if row['status'].startswith('估算') or row['status'].startswith('待'):
            item['pending_days'] += 1
        item['statuses'].add(row['status'])
    return {pid: {'production_kg': rc.ds(item['production_kg']), 'own_kg': rc.ds(item['own_kg']),
                  'bean_kg': rc.ds(item['bean_kg']), 'pending_days': item['pending_days'],
                  'days': item['days'], 'statuses': sorted(item['statuses'])} for pid, item in result.items()}
