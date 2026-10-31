"""白干熏制登记：只登记投入的白干（框），不登记黄干产出。

口径：
- 熏制只取白干（框），按投入件数扣减来源库存；
- 净重优先用毛重扣皮重（皮重取产品台账每件皮重，白干（框）为 1 公斤/件），
  未填毛重时按单件净重（平均重量/标准重量）估算；
- 折豆 = 净重 ÷ 白干最后一天的出品率（往回找最近有白干产出的那一天），
  页面上标出取用的是哪一天；找不到则要求手工填出品率；
- 折豆计入当日黄干的用豆量（由生产日报读取），黄干产量仍由盘库与发货推算。
"""
import json
import secrets
import time
from decimal import Decimal, ROUND_HALF_UP

import resources_costs as rc

SOURCES = ('白干', '白干(框)', '白干（框）')
TARGETS = ('黄干', '黄干(框)', '黄干（框）')


def _rows(c, table, where='', args=()):
    return [json.loads(r[0]) for r in c.execute('SELECT payload FROM ' + table + (' WHERE ' + where if where else '') + ' ORDER BY rowid', args)]


def records(c):
    return _rows(c, 'curing_records')


def _products(c):
    return {r['id']: dict(r) for r in c.execute('SELECT * FROM products')}


def _is_source(name):
    text = str(name or '').replace('（', '(').replace('）', ')')
    return '白干' in text or '白豆干' in text


def _is_target(name):
    text = str(name or '').replace('（', '(').replace('）', ')')
    return '黄干' in text or '熏' in text


def products(c, kind='source'):
    out = []
    for p in c.execute('SELECT id,name,unit,tare,standard_kg FROM products ORDER BY id'):
        ok = _is_source(p['name']) if kind == 'source' else _is_target(p['name'])
        if ok:
            out.append({'id': p['id'], 'name': p['name'], 'unit': p['unit'], 'tare': p['tare'], 'standard_kg': p['standard_kg'] or ''})
    return out


def kg_per_unit(c, product):
    """单件净重（公斤）：平均重量表 > 标准重量 > 皮重，最后回落到 0（由页面提示填写）。"""
    if product['unit'] == '公斤':
        return Decimal('1')
    averages = {}
    row = c.execute("SELECT value FROM meta WHERE key='product_average_weights'").fetchone()
    if row:
        try:
            averages = json.loads(row[0]) or {}
        except Exception:
            averages = {}
    import production_management
    fallback = None
    try:
        fallback = production_management.product_average(c, product)
    except Exception:
        fallback = None
    for raw in (averages.get(product['id']), product.get('standard_kg'), fallback):
        raw = str(raw or '').strip()
        if not raw:
            continue
        try:
            value = Decimal(raw)
            if value > 0:
                return value
        except Exception:
            continue
    raise ValueError('%s 未设置单件净重（平均重量或标准重量），请先在生产参数中维护后再登记熏制' % product['name'])


def _family_ids(c, product_id):
    names = {r['id']: str(r['name']).replace('（', '(').replace('）', ')') for r in c.execute('SELECT id,name FROM products')}
    base = names.get(product_id, '')
    stem = '白干' if base.startswith('白干') else base
    return {pid for pid, name in names.items() if name.startswith(stem)}


def last_yield(c, day, product_id):
    """白干最后一天的出品率：在 day（含）之前找最近一天有该产品产出与用豆的记录。"""
    rows = [r for r in c.execute("SELECT id,payload FROM factory_daily ORDER BY id").fetchall()]
    best = None
    for rid, raw in rows:
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        when = rec.get('business_date') or ''
        if not when or when > day or rec.get('voided'):
            continue
        family = None
        for out in rec.get('outputs') or []:
            if out.get('product_id') != product_id:
                if family is None:
                    family = _family_ids(c, product_id)
                if out.get('product_id') not in family:
                    continue
            dry = Decimal(str(out.get('allocated_dry_kg') or '0'))
            net = Decimal(str(out.get('net_kg') or '0'))
            if dry > 0 and net > 0:
                if best is None or when > best['business_date']:
                    best = {'business_date': when, 'yield': (net / dry).quantize(Decimal('0.001')), 'dry_kg': str(dry), 'net_kg': str(net)}
    return best


def consumed(c, when, product_id):
    """当日已登记熏制投入的件数与公斤，用于库存扣减。"""
    qty = Decimal('0')
    kg = Decimal('0')
    for rec in records(c):
        if rec.get('voided') or rec.get('business_date') != when or rec.get('source_product_id') != product_id:
            continue
        qty += Decimal(str(rec.get('qty') or '0'))
        kg += Decimal(str(rec.get('net_kg') or '0'))
    return qty, kg


def beans_for(c, when, product_id):
    """当日计入某产品（黄干）的熏制折豆量（公斤）。"""
    total = Decimal('0')
    for rec in records(c):
        if rec.get('voided') or rec.get('business_date') != when or rec.get('target_product_id') != product_id:
            continue
        total += Decimal(str(rec.get('beans_kg') or '0'))
    return total


def _text(value, label, limit=200):
    return rc.text(value, label, limit)


def material_cost_total(c, month=None):
    """未作废熏制登记的材料成本合计（分）；未计价笔数单列，不按 0 元混入。"""
    total = 0
    priced = 0
    unpriced = 0
    for rec in records(c):
        if rec.get('voided'):
            continue
        when = str(rec.get('business_date') or '')
        if month and not when.startswith(month):
            continue
        cents = rec.get('material_cost_cents')
        if cents in (None, ''):
            unpriced += 1
        else:
            total += int(cents)
            priced += 1
    return {'material_cost_cents': total, 'priced_records': priced, 'unpriced_records': unpriced}


def save(c, body, user, audit, now):
    action = str(body.get('action') or 'save')
    ident = str(body.get('id') or '')
    existing = next((r for r in records(c) if r['id'] == ident), None) if ident else None
    if action in ('void', 'delete'):
        if not existing:
            raise ValueError('没有找到这条熏制登记')
        if existing.get('voided'):
            raise ValueError('这条熏制登记已作废')
        updated = dict(existing, voided=True, voided_by=user, voided_at=now, version=existing['version'] + 1)
        c.execute('UPDATE curing_records SET payload=?,version=? WHERE id=?', (json.dumps(updated, ensure_ascii=False), updated['version'], ident))
        audit(c, user, '作废熏制登记', '熏制登记', existing, updated)
        return {'record': updated}

    prods = _products(c)
    when = rc.day(body.get('business_date'))
    import inventory
    inventory.open_day(c, when)
    rc.open_period(c, when)
    source_id = str(body.get('source_product_id') or '')
    source = prods.get(source_id)
    if not source or not _is_source(source['name']):
        raise ValueError('来源必须是白干或白干（框）')
    target = next((p for p in prods.values() if _is_target(p['name'])), None)
    if not target:
        raise ValueError('没有找到黄干产品，无法折算用豆')
    raw = body.get('pieces')
    if raw in (None, ''):
        raw = body.get('qty')
    qty = rc.qty(raw, '投入件数' if source['unit'] != '公斤' else '投入公斤')
    if qty <= 0:
        raise ValueError('投入件数必须大于 0')
    gross_raw = str(body.get('gross_kg') or '').strip()
    gross = rc.qty(gross_raw, '毛重') if gross_raw else Decimal('0')
    per_unit = kg_per_unit(c, source)
    tare = Decimal('0')
    if source['unit'] != '公斤':
        try:
            tare = Decimal(str(source.get('tare') or '0'))
        except Exception:
            tare = Decimal('0')
    tare_total = (qty * tare).quantize(Decimal('0.001'))
    weight_source = '单件净重'
    if source['unit'] == '公斤':
        net_kg = qty
        weight_source = '公斤'
    elif gross > 0:
        net_kg = (gross - tare_total).quantize(Decimal('0.001'))
        if net_kg <= 0:
            raise ValueError('毛重 %s 公斤小于皮重合计 %s 公斤（%s 公斤/件），请核对后再登记' % (rc.ds(gross), rc.ds(tare_total), rc.ds(tare)))
        weight_source = '毛重扣皮重'
    else:
        net_kg = (qty * per_unit).quantize(Decimal('0.001'))
    rate = Decimal(str(body.get('yield_rate') or '0'))
    yield_day = ''
    if rate <= 0:
        picked = last_yield(c, when, source_id)
        if not picked:
            raise ValueError('没有找到白干的历史出品率，请手工填写出品率')
        rate = picked['yield']
        yield_day = picked['business_date']
    beans = (net_kg / rate).quantize(Decimal('0.001'))
    note = _text(body.get('note'), '备注', 200) if body.get('note') else ''

    stock = next((row for row in inventory.stock(c, when, [dict(r) for r in c.execute('SELECT * FROM products WHERE id=?', (source_id,))])['products']), None)
    available = Decimal('0') if not stock or stock.get('free_qty') in (None, '') else Decimal(str(stock['free_qty']))
    same_day_qty, _ = consumed(c, when, source_id)
    if existing:
        same_day_qty -= Decimal(str(existing.get('qty') or '0'))
    unit_qty = qty if source['unit'] != '公斤' else (qty / per_unit if per_unit else qty)
    if available < same_day_qty + unit_qty:
        raise ValueError('%s 可用库存不足：可扣 %s %s，本次需扣 %s %s' % (source['name'], rc.ds(available), source['unit'], rc.ds(unit_qty), source['unit']))

    source_unit_cost = None
    material_cost_cents = None
    cost_status = '未计价'
    try:
        import inventory_valuation
        priced = inventory_valuation.unit_cost(c, when, source_id)
    except Exception:
        priced = None
    if priced and priced.get('unit_cost') not in (None, ''):
        price = Decimal(str(priced['unit_cost']))
        material_cost_cents = int((qty * price).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        source_unit_cost = rc.ds(price)
        cost_status = '已计价'

    record = {
        'id': existing['id'] if existing else 'CURE-' + secrets.token_hex(6).upper(),
        'business_date': when,
        'source_product_id': source_id,
        'source_product_name': source['name'],
        'source_unit': source['unit'],
        'qty': rc.ds(qty),
        'unit_kg': rc.ds(per_unit),
        'tare_kg': rc.ds(tare),
        'tare_total_kg': rc.ds(tare_total),
        'gross_kg': rc.ds(gross) if gross > 0 else '',
        'weight_source': weight_source,
        'net_kg': rc.ds(net_kg),
        'target_product_id': target['id'],
        'target_product_name': target['name'],
        'yield_rate': rc.ds(rate),
        'yield_source_date': yield_day or _text(body.get('yield_source_date'), '出品率日期', 10) if body.get('yield_source_date') else yield_day,
        'beans_kg': rc.ds(beans),
        'source_unit_cost': source_unit_cost,
        'material_cost_cents': material_cost_cents,
        'cost_status': cost_status,
        'cost_basis': '投入量×白干结存单价',
        'note': note,
        'created_by': (existing or {}).get('created_by') or user,
        'created_at': (existing or {}).get('created_at') or now,
        'updated_at': now,
        'version': (existing or {}).get('version', 0) + 1,
        'voided': False,
    }
    if existing:
        c.execute('UPDATE curing_records SET payload=?,version=? WHERE id=?', (json.dumps(record, ensure_ascii=False), record['version'], record['id']))
    else:
        c.execute('INSERT INTO curing_records(id,business_date,payload,version) VALUES(?,?,?,?)', (record['id'], when, json.dumps(record, ensure_ascii=False), record['version']))
    audit(c, user, '登记熏制投入' if not existing else '修改熏制登记', '熏制登记', existing, record)
    return {'record': record}
