"""Daily management P&L: cash receipts, material use, utilities, labour and overhead.

The page is a management view, not the accounting close. Amounts are computed from
the same ledgers as the monthly reports and keep the basis visible in every row.
"""
from datetime import date, datetime
import calendar
from decimal import Decimal, ROUND_HALF_UP
import json
import re

import erp_access
import finished_goods
import owner_analysis
import payroll
import resources_costs as rc

CONFIG_KEY = 'daily_cost_config'
ITEMS = ('water', 'electricity', 'steam', 'auxiliary', 'labor', 'other')
ENERGY_ITEMS = ('water', 'electricity', 'steam')
LABELS = {'water': '水费', 'electricity': '电费', 'steam': '蒸汽费', 'auxiliary': '辅料估算', 'labor': '人工成本', 'other': '其他间接费用'}
UNITS = {'water': '吨', 'electricity': '度', 'steam': '吨', 'auxiliary': '公斤豆', 'labor': '人', 'other': ''}
DEFAULTS = {
    'water_price_cents': 450,
    'electricity_price_cents': 80,
    'steam_price_cents': 25000,
    'custom_items': [],
    'auxiliary_base_soy_kg': 10000,
    'auxiliary_base_amount_cents': 200000,
    'labor_daily_rate_cents': 20000,
    'version': 0,
}


def _config(c):
    value = dict(DEFAULTS)
    row = c.execute('SELECT value FROM meta WHERE key=?', (CONFIG_KEY,)).fetchone()
    if row:
        try:
            saved = json.loads(row[0])
        except Exception:
            saved = {}
        if isinstance(saved, dict):
            value.update({k: saved[k] for k in DEFAULTS if k in saved})
    return value


def _normalize_custom(items):
    result = []
    if not isinstance(items, list):
        return result
    seen = set()
    for raw in items[:30]:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get('key') or '').strip()
        label = str(raw.get('label') or '').strip()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', key) or not label or key in seen:
            continue
        mode = raw.get('mode') if raw.get('mode') in ('meter', 'manual') else 'manual'
        category = raw.get('category') if raw.get('category') in ('energy', 'other') else 'other'
        try:
            price = int(raw.get('price_cents') or 0)
        except Exception:
            price = 0
        result.append({
            'key': key,
            'label': label[:30],
            'mode': mode,
            'unit': str(raw.get('unit') or '')[:12],
            'price_cents': max(0, price),
            'category': category,
            'active': bool(raw.get('active', True)),
        })
        seen.add(key)
    return result


def _all_custom_items(cfg):
    return _normalize_custom(cfg.get('custom_items'))


def _custom_items(cfg):
    return [item for item in _all_custom_items(cfg) if item.get('active')]


def _energy_defs(cfg, include_inactive=False):
    defs = [
        {'key': 'water', 'label': LABELS['water'], 'unit': UNITS['water'], 'mode': 'meter', 'price_cents': int(cfg['water_price_cents']), 'category': 'energy'},
        {'key': 'electricity', 'label': LABELS['electricity'], 'unit': UNITS['electricity'], 'mode': 'meter', 'price_cents': int(cfg['electricity_price_cents']), 'category': 'energy'},
        {'key': 'steam', 'label': LABELS['steam'], 'unit': UNITS['steam'], 'mode': 'meter', 'price_cents': int(cfg['steam_price_cents']), 'category': 'energy'},
    ]
    defs.extend(dict(item) for item in _all_custom_items(cfg) if item.get('category') == 'energy' and (include_inactive or item.get('active')))
    return defs


def config_view(c):
    cfg = _config(c)
    return {
        'water_price_cents': cfg['water_price_cents'],
        'electricity_price_cents': cfg['electricity_price_cents'],
        'steam_price_cents': cfg['steam_price_cents'],
        'custom_items': [dict(x) for x in cfg.get('custom_items', [])],
        'auxiliary_base_soy_kg': cfg['auxiliary_base_soy_kg'],
        'auxiliary_base_amount_cents': cfg['auxiliary_base_amount_cents'],
        'labor_daily_rate_cents': cfg['labor_daily_rate_cents'],
        'version': cfg['version'],
    }


def _yuan(cents):
    return float(Decimal(int(cents or 0)) / 100)


def _cents(value, label):
    try:
        number = Decimal(str(value))
    except Exception:
        raise ValueError(label + '无效')
    if not number.is_finite() or number < 0 or number > Decimal('100000000'):
        raise ValueError(label + '须为非负有效金额')
    return int((number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _qty(value, label):
    try:
        number = Decimal(str(value))
    except Exception:
        raise ValueError(label + '无效')
    if not number.is_finite() or number < 0 or number > Decimal('100000000'):
        raise ValueError(label + '须为非负有效数值')
    return number


def _records(c, day):
    rows = c.execute('SELECT * FROM daily_cost_records WHERE business_date=?', (day,)).fetchall()
    result = {r['item']: dict(r) for r in rows}
    if 'gas' in result and 'steam' not in result:
        result['steam'] = dict(result['gas'], item='steam')
    return result


def _previous_meter(c, item, day):
    if item == 'steam':
        row = c.execute("SELECT meter_end FROM daily_cost_records WHERE item IN ('steam','gas') AND business_date<? AND meter_end IS NOT NULL ORDER BY business_date DESC LIMIT 1", (day,)).fetchone()
    else:
        row = c.execute('SELECT meter_end FROM daily_cost_records WHERE item=? AND business_date<? AND meter_end IS NOT NULL ORDER BY business_date DESC LIMIT 1', (item, day)).fetchone()
    return Decimal(str(row[0])) if row and row[0] is not None else Decimal(0)


def _material_day(c, day):
    masters = {r['id']: dict(r) for r in c.execute('SELECT id,category,name FROM material_items')}
    _, entries = rc.material_ledger(c, day)
    used = [e for e in entries if e['business_date'] == day and e['kind'] in ('consume', 'return', 'loss')]
    direct = Decimal(0)
    soy = Decimal(0)
    missing = []
    for e in used:
        master = masters.get(e['material_id'], {})
        category = master.get('category', '')
        sign = -1 if e['kind'] == 'return' else 1
        if e['material_id'] == 'RM-SOY':
            soy += sign * Decimal(str(e.get('qty') or 0))
        if category in ('原料', '包装'):
            cost = int(e.get('cost_cents') or 0)
            direct += sign * Decimal(cost)
            if e['kind'] != 'return' and (Decimal(str(e.get('uncosted_out_qty') or 0)) > 0 or any(Decimal(str(l.get('uncosted_qty') or 0)) > 0 for l in e.get('fifo_allocations', []))):
                missing.append(e.get('material_name') or e['material_id'])
    return int(direct), soy, sorted(set(missing))


def _income(c, day):
    product = byproduct = opening = 0
    for r in rc.rows(c, 'receipts'):
        if r.get('voided') or r.get('received_date') != day:
            continue
        if r.get('order_id'):
            product += int(r['amount_cents'])
        else:
            opening += int(r['amount_cents'])
    for r in rc.rows(c, 'byproduct_sales'):
        if r.get('voided'):
            continue
        receipts = r.get('receipts') or []
        initial = int(r.get('received_cents') or 0) - sum(int(x.get('amount_cents') or 0) for x in receipts)
        if r.get('business_date') == day and initial:
            byproduct += initial
        for x in receipts:
            if x.get('business_date') == day:
                byproduct += int(x.get('amount_cents') or 0)
    return product, byproduct, opening


def _people(c, day, fallback_rate_cents):
    value = owner_analysis.people(c, day)
    profiles = {}
    for row in payroll.records(c):
        if row.get('kind') == 'profile' and row.get('employee_id'):
            profiles[row['employee_id']] = row
    employees = payroll.table_rows(c, 'factory_employees')
    employee_by_id = {e['id']: e for e in employees}
    management = [e for e in employees if e.get('employee_type') == 'management' and e.get('active', True)]
    days_in_month = calendar.monthrange(int(day[:4]), int(day[5:7]))[1]
    present_rows = [r for r in value['rows'] if r.get('actual_status') in ('full', 'present', 'half')]
    draft = sum(1 for r in value['rows'] if r.get('actual_status') == 'draft')
    details = []
    present_ids = set()
    equivalent_days = Decimal(0)
    for r in present_rows:
        status = r.get('actual_status')
        days = Decimal('0.5') if status == 'half' else Decimal(1)
        profile = profiles.get(r.get('employee_id'))
        is_management = employee_by_id.get(r.get('employee_id'), {}).get('employee_type') == 'management' or r.get('employee_type') == 'management'
        source = '工资档案'
        if profile:
            monthly = payroll.profile_monthly(profile)
            if is_management:
                daily = Decimal(monthly) / days_in_month
                source = '工资档案（管理固定）'
            else:
                daily = payroll.daily_cents(monthly)
            monthly_cents = monthly
        else:
            daily = Decimal(int(fallback_rate_cents))
            monthly_cents = None
            source = '兜底日薪'
        amount = int((daily * days).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        details.append({
            'employee_id': r.get('employee_id'),
            'employee_name': r.get('employee_name') or '历史员工',
            'status': status,
            'days': float(days),
            'monthly_cents': monthly_cents,
            'daily_cents': int(daily.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
            'amount_cents': amount,
            'source': source,
            'management': is_management,
        })
        present_ids.add(r.get('employee_id'))
        equivalent_days += days
    # 管理岗按月固定工资：没有考勤记录也视为正常出勤，请假/缺勤才扣减。
    extra_management = 0
    for e in management:
        if e['id'] in present_ids:
            continue
        record = next((r for r in value['rows'] if r.get('employee_id') == e['id']), {})
        status = record.get('actual_status')
        if status in ('leave', 'absent'):
            continue
        days = Decimal('0.5') if status == 'half' else Decimal(1)
        profile = profiles.get(e['id'])
        if profile:
            monthly = payroll.profile_monthly(profile)
            daily = Decimal(monthly) / days_in_month
            monthly_cents = monthly
            source = '工资档案（管理固定）'
        else:
            daily = Decimal(int(fallback_rate_cents))
            monthly_cents = None
            source = '兜底日薪'
        amount = int((daily * days).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        details.append({
            'employee_id': e['id'],
            'employee_name': e.get('name') or '管理岗',
            'status': 'half' if status == 'half' else 'full',
            'days': float(days),
            'monthly_cents': monthly_cents,
            'daily_cents': int(daily.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
            'amount_cents': amount,
            'source': source,
            'management': True,
        })
        present_ids.add(e['id'])
        equivalent_days += days
        extra_management += 1
    return len(present_rows) + extra_management, draft, value.get('attendance_state', 'missing'), details, equivalent_days


def _amount(quantity, price_cents):
    return int((quantity * Decimal(int(price_cents))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _sales_value(line, unit):
    """Value one shipped order line at the customer price when no invoice amount exists."""
    stored = int(line.get('amount_cents') or 0)
    if stored:
        return stored
    price = Decimal(str(line.get('price') or 0))
    qty = Decimal(str(line.get('actual_qty') or 0))
    if price <= 0 or qty <= 0:
        return 0
    bill = Decimal(str(line.get('bill_qty') or 0))
    if bill <= 0:
        if line.get('billing_unit') == '公斤' or (not line.get('billing_unit') and unit == '公斤'):
            standard = Decimal(str(line.get('standard_unit_kg') or 0))
            bill = qty * standard if standard > 0 else qty
        else:
            bill = qty
    return int((bill * price * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _sales_split(c, day):
    """Split today's shipped value by yesterday's carry-over, today's production, and purchased stock.

    Orders are valued at the price on the line; the warehouse plan's existing_qty is
    consumed first (same FIFO rule as the allocation page), then today's produced_qty.
    Purchased products are valued at their selling price and their FIFO purchase cost
    is deducted separately. Cash receipts remain a separate basis and are not altered.
    """
    plan = next((p for p in rc.rows(c, 'warehouse_plans') if p.get('business_date') == day), {})
    stock = {s['product_id']: s for s in (plan.get('stock') or [])}
    products = {r[0]: {'name': r[1], 'unit': r[2]} for r in c.execute('SELECT id,name,unit FROM products')}
    orders = [o for o in rc.rows(c, 'orders') if o.get('business_date') == day and o.get('state') not in ('cancelled', 'voided', 'draft')]
    detail = {}
    for order in orders:
        for line in order.get('lines') or []:
            pid = line.get('product_id')
            qty = Decimal(str(line.get('actual_qty') or 0))
            if not pid or qty <= 0:
                continue
            product = products.get(pid, {'name': line.get('product_name') or pid, 'unit': line.get('unit') or ''})
            value = _sales_value(line, product['unit'])
            s = stock.get(pid, {})
            # Purchased finished goods are not produced in-house; all shipped units are purchased stock.
            purchased = finished_goods.is_purchased(c, pid)
            if purchased:
                buckets = [('purchased', qty)]
            else:
                existing = Decimal(str(s.get('existing_qty') or 0))
                produced = Decimal(str(s.get('produced_qty') or 0))
                extra = Decimal(str(s.get('purchased') or 0))
                buckets = []
                remain = qty
                for key, available in (('carryover', existing), ('production', produced), ('purchased', extra)):
                    take = min(remain, max(Decimal(0), available))
                    if take > 0:
                        buckets.append((key, take))
                        remain -= take
                if remain > 0:
                    buckets.append(('unallocated', remain))
            row = detail.setdefault(pid, {'product_id': pid, 'product_name': product['name'], 'unit': product['unit'], 'qty': Decimal(0), 'value_cents': 0, 'carryover_cents': 0, 'production_cents': 0, 'purchased_cents': 0, 'unallocated_cents': 0})
            row['qty'] += qty
            row['value_cents'] += value
            allocated = 0
            for index, (key, take) in enumerate(buckets):
                share = value - allocated if index == len(buckets) - 1 else int((Decimal(value) * take / qty).quantize(Decimal(1), rounding=ROUND_HALF_UP))
                allocated += share
                row[{'carryover': 'carryover_cents', 'production': 'production_cents', 'purchased': 'purchased_cents', 'unallocated': 'unallocated_cents'}[key]] += share
    purchased_cost = 0
    try:
        purchased_cost = sum(int(r.get('sales_cost_cents') or 0) for r in finished_goods.stock_cost(c, day, day) if finished_goods.is_purchased(c, r['product_id']))
    except Exception:
        purchased_cost = 0
    by_product = []
    for row in detail.values():
        row['qty'] = float(row['qty'])
        row['purchased_gross_cents'] = row['purchased_cents']
        by_product.append(row)
    by_product.sort(key=lambda r: r['product_name'])
    actual = sum(r['value_cents'] for r in by_product)
    production = sum(r['production_cents'] for r in by_product)
    carryover = sum(r['carryover_cents'] for r in by_product)
    purchased = sum(r['purchased_cents'] for r in by_product)
    unallocated = sum(r['unallocated_cents'] for r in by_product)
    return {'actual_sales_cents': actual, 'production_sales_cents': production, 'carryover_sales_cents': carryover, 'purchased_sales_cents': purchased, 'unallocated_sales_cents': unallocated, 'purchased_cost_cents': purchased_cost, 'purchased_gross_cents': purchased - purchased_cost, 'by_product': by_product, 'basis': '按当日实际发货订单金额；筐装按标准净重折算公斤；昨日结转与今日生产按仓库库存 FIFO 拆分；外购按采购成本 FIFO 扣减。回款口径见上方销售回款，不与发货金额混用。'}


def _compute(c, day):
    cfg = _config(c)
    custom = _all_custom_items(cfg)
    rows = _records(c, day)
    product, byproduct, opening = _income(c, day)
    direct, soy, unpriced = _material_day(c, day)
    present, draft, attendance_state, labor_detail, labor_days = _people(c, day, cfg['labor_daily_rate_cents'])
    water = rows.get('water') or {}
    electricity = rows.get('electricity') or {}
    steam = rows.get('steam') or {}
    aux = rows.get('auxiliary') or {}
    labour = rows.get('labor') or {}
    other = rows.get('other') or {}
    base_soy = int(cfg['auxiliary_base_soy_kg'] or 10000)
    if base_soy <= 0:
        base_soy = 10000
    aux_amount = int(aux.get('amount_cents') or (soy / Decimal(base_soy) * Decimal(cfg['auxiliary_base_amount_cents'])).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if present:
        people = present
        labor_amount = sum(item['amount_cents'] for item in labor_detail)
        rate = int((Decimal(labor_amount) / labor_days).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if labor_days else 0
        fallback_people = sum(1 for item in labor_detail if item['source'] == '兜底日薪')
        management_people = sum(1 for item in labor_detail if item.get('management'))
        production_people = len(labor_detail) - management_people
        labor_basis = '管理岗固定工资 ' + str(management_people) + ' 人；生产考勤 ' + str(production_people) + ' 人 / ' + str(labor_days.normalize()) + ' 人天'
        if fallback_people:
            labor_basis += '，' + str(fallback_people) + ' 人无工资档案按 ' + str(_yuan(cfg['labor_daily_rate_cents'])) + ' 元/天兜底'
        if any(item['status'] == 'half' for item in labor_detail):
            labor_basis += '；半天按 0.5 天'
        if attendance_state != 'confirmed':
            labor_basis += '；当日生产考勤未确认，生产人工待确认'
    else:
        people = 0
        rate = 0
        labor_amount = 0
        labor_basis = '今日考勤尚未确认，人工成本暂不计算；确认考勤后自动重算'
    utility = int(water.get('amount_cents') or 0) + int(electricity.get('amount_cents') or 0) + int(steam.get('amount_cents') or 0)
    other_amount = int(other.get('amount_cents') or 0)
    revenue = product + byproduct
    split = _sales_split(c, day)
    gross = revenue - direct - aux_amount - labor_amount
    item_rows = []
    specs = [
        ('water', water, _previous_meter(c, 'water', day), cfg['water_price_cents'], '按水表差量 × 默认单价', UNITS['water']),
        ('electricity', electricity, _previous_meter(c, 'electricity', day), cfg['electricity_price_cents'], '按电表差量 × 默认单价', UNITS['electricity']),
        ('steam', steam, _previous_meter(c, 'steam', day), cfg['steam_price_cents'], '按蒸汽表差量 × 默认单价', UNITS['steam']),
    ]
    for key, row, start, price, basis, unit in specs:
        if row.get('meter_start') is not None:
            start = Decimal(str(row['meter_start']))
        end = row.get('meter_end')
        quantity = Decimal(str(row.get('quantity') if row.get('quantity') is not None else (Decimal(str(end)) - start if end is not None else 0)))
        item_rows.append({'key': key, 'label': LABELS[key], 'unit': unit, 'basis': basis, 'meter_start': float(start), 'meter_end': None if end is None else float(end), 'quantity': float(quantity), 'unit_price_cents': int(row.get('unit_price_cents') if row.get('unit_price_cents') is not None else price), 'amount_cents': int(row.get('amount_cents') or 0), 'people': None, 'note': row.get('note', ''), 'has_record': bool(row)})
    item_rows.append({'key': 'auxiliary', 'label': LABELS['auxiliary'], 'unit': UNITS['auxiliary'], 'basis': '当日净用豆量 ÷ ' + str(base_soy) + ' 公斤 × ' + str(_yuan(cfg['auxiliary_base_amount_cents'])) + ' 元基准', 'meter_start': None, 'meter_end': None, 'quantity': float(soy), 'unit_price_cents': None, 'amount_cents': aux_amount, 'people': None, 'note': aux.get('note', '')})
    item_rows.append({'key': 'labor', 'label': LABELS['labor'], 'unit': UNITS['labor'], 'basis': labor_basis, 'meter_start': None, 'meter_end': None, 'quantity': people, 'unit_price_cents': rate, 'amount_cents': labor_amount, 'people': people, 'note': labour.get('note', '')})
    custom_total = 0
    energy_custom_total = 0
    for item in custom:
        row = rows.get(item['key']) or {}
        if not item.get('active') and not row:
            continue
        if item['mode'] == 'meter':
            start = Decimal(str(row['meter_start'])) if row.get('meter_start') is not None else _previous_meter(c, item['key'], day)
            end = row.get('meter_end')
            quantity = Decimal(str(row.get('quantity') if row.get('quantity') is not None else (Decimal(str(end)) - start if end is not None else 0)))
            price = int(row.get('unit_price_cents') if row.get('unit_price_cents') is not None else item['price_cents'])
            amount = int(row.get('amount_cents') or _amount(quantity, price))
            item_rows.append({'key': item['key'], 'label': item['label'], 'unit': item['unit'] or '单位', 'basis': '按表差 × 默认单价', 'meter_start': float(start), 'meter_end': None if end is None else float(end), 'quantity': float(quantity), 'unit_price_cents': price, 'amount_cents': amount, 'people': None, 'note': row.get('note', ''), 'has_record': bool(row), 'custom': True, 'category': item['category']})
        else:
            amount = int(row.get('amount_cents') or 0)
            item_rows.append({'key': item['key'], 'label': item['label'], 'unit': item['unit'] or '', 'basis': '手工登记金额', 'meter_start': None, 'meter_end': None, 'quantity': None, 'unit_price_cents': None, 'amount_cents': amount, 'people': None, 'note': row.get('note', ''), 'has_record': bool(row), 'custom': True, 'category': item['category']})
        custom_total += amount
        if item['category'] == 'energy':
            energy_custom_total += amount
    item_rows.append({'key': 'other', 'label': LABELS['other'], 'unit': UNITS['other'], 'basis': '手工登记的其他间接费用', 'meter_start': None, 'meter_end': None, 'quantity': None, 'unit_price_cents': None, 'amount_cents': other_amount, 'people': None, 'note': other.get('note', '')})
    net = gross - utility - other_amount - custom_total
    gaps = []
    missing = [LABELS[key] for key in ENERGY_ITEMS if key not in rows]
    missing.extend(item['label'] for item in custom if item.get('active') and item['mode'] == 'meter' and item['key'] not in rows)
    missing.extend(LABELS[key] for key in ('auxiliary', 'other') if key not in rows)
    if not present:
        missing.append(LABELS['labor'])
    if missing:
        gaps.append({'field': '未登记：' + '、'.join(missing) + '，按 0 显示；不代表当日没有该项成本', 'owner': '会计'})
    if attendance_state != 'confirmed':
        gaps.append({'field': '当日生产考勤未确认，生产人工待确认；管理固定工资已按档案计入', 'owner': '厂长 / 行政'})
    if draft:
        gaps.append({'field': str(draft) + ' 人考勤仍为草稿，未计入实际出勤', 'owner': '厂长 / 行政'})
    if opening:
        gaps.append({'field': '另有期初应收收款 ' + str(_yuan(opening)) + ' 元，属于历史应收，未计入当日销售', 'owner': '出纳'})
    if unpriced:
        gaps.append({'field': '未定价材料：' + '、'.join(unpriced), 'owner': '会计'})
    if not soy:
        gaps.append({'field': '当日没有大豆净领用，辅料估算为 0', 'owner': '库管'})
    return {
        'business_date': day,
        'config': config_view(c),
        'revenue_cents': revenue,
        'sales_split': split,
        'actual_sales_cents': split['actual_sales_cents'],
        'production_sales_cents': split['production_sales_cents'],
        'carryover_sales_cents': split['carryover_sales_cents'],
        'purchased_sales_cents': split['purchased_sales_cents'],
        'purchased_cost_cents': split['purchased_cost_cents'],
        'purchased_gross_cents': split['purchased_gross_cents'],
        'product_receipts_cents': product,
        'byproduct_receipts_cents': byproduct,
        'opening_receipts_cents': opening,
        'material_cents': direct,
        'auxiliary_cents': aux_amount,
        'labor_cents': labor_amount,
        'labor_detail': labor_detail,
        'labor_days': float(labor_days),
        'utility_cents': utility,
        'custom_cents': custom_total,
        'energy_custom_cents': energy_custom_total,
        'other_cents': other_amount,
        'gross_cents': gross,
        'net_cents': net,
        'soy_kg': float(soy),
        'actual_people': present,
        'draft_people': draft,
        'attendance_state': attendance_state,
        'rows': item_rows,
        'gaps': gaps,
        'basis': '收入按当日实际到账的产品与豆渣收款；直接材料按原料与包装净领用；辅料按当日净用豆量和基准估算；人工按考勤确认人员的工资档案日薪计算（半天 0.5 天，无档案按兜底日薪）；水、电、蒸汽按表差乘默认单价；自定义项目按配置的表数或手工金额；其他为手工登记。未登记项目显示为 0 并列入缺项，不按 0 冒充已核实。',
    }

def report(c, day):
    day = rc.day(day)
    return _compute(c, day)


def _upsert(c, day, item, start, end, quantity, price, amount, people, note, now):
    c.execute('''INSERT INTO daily_cost_records(business_date,item,meter_start,meter_end,quantity,unit_price_cents,amount_cents,people,note,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(business_date,item) DO UPDATE SET meter_start=excluded.meter_start,meter_end=excluded.meter_end,quantity=excluded.quantity,
                 unit_price_cents=excluded.unit_price_cents,amount_cents=excluded.amount_cents,people=excluded.people,note=excluded.note,updated_at=excluded.updated_at''',
              (day, item, None if start is None else str(start), None if end is None else str(end), None if quantity is None else str(quantity), price, amount, people, note, now, now))


def save(c, body, role, now, audit):
    erp_access.require_role(role, 'costs.write')
    day = rc.day(body.get('business_date'))
    cfg = _config(c)
    custom = _custom_items(cfg)
    existing = _records(c, day)
    notes = {key: rc.text(body.get(key + '_note', ''), LABELS[key] + '备注', 200, False) for key in ITEMS}
    for key in ENERGY_ITEMS:
        label = LABELS[key]
        old = existing.get(key) or {}
        end_value = body.get(key + '_end')
        if end_value in (None, ''):
            if old.get('meter_end') is None:
                continue
            end = Decimal(str(old['meter_end']))
        else:
            end = _qty(end_value, label + '表数')
        start_value = body.get(key + '_start')
        if old.get('meter_start') is not None:
            start = Decimal(str(old['meter_start']))
        elif start_value not in (None, ''):
            start = _qty(start_value, label + '上次表数')
        else:
            start = _previous_meter(c, key, day)
        if end < start:
            raise ValueError(label + '当日表数不能小于上次表数')
        price = _cents(body.get(key + '_price', _yuan(cfg[key + '_price_cents'])), label + '单价')
        _upsert(c, day, key, start, end, end - start, price, _amount(end - start, price), None, notes[key], now)
    for item in custom:
        key = item['key']
        label = item['label']
        old = existing.get(key) or {}
        note = rc.text(body.get(key + '_note', ''), label + '备注', 200, False)
        if item['mode'] == 'meter':
            end_value = body.get(key + '_end')
            if end_value in (None, ''):
                if old.get('meter_end') is None:
                    continue
                end = Decimal(str(old['meter_end']))
            else:
                end = _qty(end_value, label + '表数')
            start_value = body.get(key + '_start')
            if old.get('meter_start') is not None:
                start = Decimal(str(old['meter_start']))
            elif start_value not in (None, ''):
                start = _qty(start_value, label + '上次表数')
            else:
                start = _previous_meter(c, key, day)
            if end < start:
                raise ValueError(label + '当日表数不能小于上次表数')
            price = _cents(body.get(key + '_price', _yuan(item['price_cents'])), label + '单价')
            _upsert(c, day, key, start, end, end - start, price, _amount(end - start, price), None, note, now)
        else:
            value = body.get(key + '_amount')
            if value in (None, '') and not old:
                continue
            amount = _cents(value if value not in (None, '') else _yuan(old.get('amount_cents') or 0), label + '金额')
            _upsert(c, day, key, None, None, None, None, amount, None, note, now)
    direct, soy, _ = _material_day(c, day)
    base_soy = _qty(body.get('auxiliary_base_soy_kg', cfg['auxiliary_base_soy_kg']), '辅料基准用豆量')
    if base_soy <= 0:
        raise ValueError('辅料基准用豆量须大于 0')
    base_amount = _cents(body.get('auxiliary_base_amount', _yuan(cfg['auxiliary_base_amount_cents'])), '辅料基准金额')
    aux_amount = int((soy / base_soy * Decimal(base_amount)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if soy > 0 or existing.get('auxiliary'):
        _upsert(c, day, 'auxiliary', None, None, soy, base_amount, aux_amount, None, notes['auxiliary'], now)
    present, draft, _, labor_detail, labor_days = _people(c, day, cfg['labor_daily_rate_cents'])
    people = present
    other_value = body.get('other_amount')
    other_amount = _cents(other_value, '其他间接费用') if other_value not in (None, '') else 0
    if other_value not in (None, '') or existing.get('other'):
        _upsert(c, day, 'other', None, None, None, None, other_amount, None, notes['other'], now)
    if audit:
        audit(c, role, '登记或更正每日成本', day, existing, {'soy_kg': str(soy), 'labor_people': people, 'custom_items': [x['key'] for x in custom]})
    return _compute(c, day)

def save_config(c, body, role, now, audit):
    erp_access.require_role(role, 'costs.write')
    old = _config(c)
    cfg = {
        'water_price_cents': _cents(body.get('water_price', _yuan(old['water_price_cents'])), '水价'),
        'electricity_price_cents': _cents(body.get('electricity_price', _yuan(old['electricity_price_cents'])), '电价'),
        'steam_price_cents': _cents(body.get('steam_price', _yuan(old['steam_price_cents'])), '蒸汽价'),
        'auxiliary_base_soy_kg': int(_qty(body.get('auxiliary_base_soy_kg', old['auxiliary_base_soy_kg']), '辅料基准用豆量')),
        'auxiliary_base_amount_cents': _cents(body.get('auxiliary_base_amount', _yuan(old['auxiliary_base_amount_cents'])), '辅料基准金额'),
        'labor_daily_rate_cents': _cents(body.get('labor_daily_rate', _yuan(old['labor_daily_rate_cents'])), '人工日工资'),
        'custom_items': _normalize_custom(old.get('custom_items')),
        'version': int(old.get('version') or 0) + 1,
    }
    if cfg['auxiliary_base_soy_kg'] <= 0:
        raise ValueError('辅料基准用豆量须大于 0')
    c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (CONFIG_KEY, json.dumps(cfg, ensure_ascii=False, sort_keys=True)))
    if audit:
        audit(c, role, '修改每日成本默认参数', CONFIG_KEY, old, cfg)
    return config_view(c)


def save_items(c, body, role, now, audit):
    erp_access.require_role(role, 'costs.write')
    raw = body.get('items')
    if not isinstance(raw, list) or len(raw) > 30:
        raise ValueError('成本项目须为列表且不超过 30 项')
    old = _config(c)
    old_items = _normalize_custom(old.get('custom_items'))
    old_by_key = {item['key']: item for item in old_items}
    used = set(ITEMS)
    result = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError('成本项目格式无效')
        key = str(item.get('key') or '').strip()
        if not key:
            n = index
            while 'custom-' + str(n) in used:
                n += 1
            key = 'custom-' + str(n)
        if key in used or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', key):
            raise ValueError('成本项目编码无效或重复')
        label = str(item.get('label') or '').strip()
        if not label or len(label) > 30:
            raise ValueError('成本项目名称须为 1 至 30 个字符')
        mode = item.get('mode')
        if mode not in ('meter', 'manual'):
            raise ValueError('成本项目计价方式无效')
        category = item.get('category')
        if category not in ('energy', 'other'):
            raise ValueError('成本项目类别无效')
        unit = str(item.get('unit') or '').strip()
        if len(unit) > 12:
            raise ValueError('成本项目单位过长')
        prior = old_by_key.get(key, {})
        price = _cents(item.get('price', _yuan(prior.get('price_cents') or 0)), label + '默认单价')
        result.append({'key': key, 'label': label, 'mode': mode, 'unit': unit, 'price_cents': price, 'category': category, 'active': bool(item.get('active', True))})
        used.add(key)
    cfg = dict(old)
    cfg['custom_items'] = result
    cfg['version'] = int(old.get('version') or 0) + 1
    c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (CONFIG_KEY, json.dumps(cfg, ensure_ascii=False, sort_keys=True)))
    if audit:
        audit(c, role, '维护每日成本项目', CONFIG_KEY, old_items, result)
    return config_view(c)


def _month_bounds(month):
    try:
        start = datetime.strptime(str(month), '%Y-%m').date().replace(day=1)
    except Exception:
        raise ValueError('月份格式须为 YYYY-MM')
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1)
    else:
        end = start.replace(month=start.month + 1, day=1)
    return start.isoformat(), (end.fromordinal(end.toordinal() - 1)).isoformat()


def _item_label(cfg, key):
    for item in _normalize_custom(cfg.get('custom_items')):
        if item['key'] == key:
            return item
    return {}


def _energy_item_defs(cfg, include_inactive=False):
    return _energy_defs(cfg, include_inactive)


def energy_ledger(c, month):
    start, end = _month_bounds(month)
    cfg = _config(c)
    all_defs = _energy_item_defs(cfg, True)
    active_keys = {item['key'] for item in _energy_item_defs(cfg)}
    rows = c.execute('SELECT * FROM daily_cost_records WHERE business_date BETWEEN ? AND ? ORDER BY business_date,item', (start, end)).fetchall()
    used_keys = {row['item'] for row in rows}
    defs = [item for item in all_defs if item['key'] in ('water', 'electricity', 'steam') or item['key'] in active_keys or item['key'] in used_keys]
    by_key = {item['key']: item for item in defs}
    records = {}
    for row in rows:
        item = dict(row)
        if item['item'] == 'gas':
            item['item'] = 'steam'
        records[(item['business_date'], item['item'])] = item
    days = []
    totals = {item['key']: {'quantity': 0.0, 'amount_cents': 0} for item in defs}
    day = datetime.strptime(start, '%Y-%m-%d').date()
    last = datetime.strptime(end, '%Y-%m-%d').date()
    while day <= last:
        date_text = day.isoformat()
        cells = []
        total = 0
        for item in defs:
            row = records.get((date_text, item['key']), {})
            amount = int(row.get('amount_cents') or 0)
            quantity = row.get('quantity')
            if quantity is None and item['mode'] == 'meter' and row.get('meter_end') is not None:
                quantity = float(row['meter_end']) - float(row.get('meter_start') or 0)
            cells.append({'key': item['key'], 'label': item['label'], 'unit': item['unit'], 'mode': item['mode'], 'quantity': None if quantity is None else float(quantity), 'amount_cents': amount, 'has_record': bool(row)})
            totals[item['key']]['quantity'] += float(quantity or 0)
            totals[item['key']]['amount_cents'] += amount
            total += amount
        days.append({'business_date': date_text, 'items': cells, 'total_cents': total})
        day = day.fromordinal(day.toordinal() + 1)
    settlements = []
    for row in c.execute('SELECT * FROM energy_settlements WHERE voided=0 AND period_start<=? AND period_end>=? ORDER BY period_start DESC,id DESC', (end, start)).fetchall():
        item = dict(row)
        label = by_key.get(item['item'], _item_label(cfg, item['item']))
        if item['item'] == 'steam':
            daily = c.execute("SELECT COALESCE(SUM(amount_cents),0),COALESCE(SUM(quantity),0) FROM daily_cost_records WHERE item IN ('steam','gas') AND business_date BETWEEN ? AND ?", (item['period_start'], item['period_end'])).fetchone()
        else:
            daily = c.execute('SELECT COALESCE(SUM(amount_cents),0),COALESCE(SUM(quantity),0) FROM daily_cost_records WHERE item=? AND business_date BETWEEN ? AND ?', (item['item'], item['period_start'], item['period_end'])).fetchone()
        daily_cents = int(daily[0] or 0)
        item.update({
            'item_label': label.get('label', item['item']) if isinstance(label, dict) else item['item'],
            'unit': label.get('unit', '') if isinstance(label, dict) else '',
            'daily_cents': daily_cents,
            'daily_quantity': float(daily[1] or 0),
            'difference_cents': int(item['amount_cents'] or 0) - daily_cents,
        })
        settlements.append(item)
    return {'month': start[:7], 'period_start': start, 'period_end': end, 'items': defs, 'days': days, 'totals': [dict(item, **totals.get(item['key'], {})) for item in defs], 'settlements': settlements}


def save_settlement(c, body, role, now, audit):
    erp_access.require_role(role, 'costs.write')
    start = rc.day(body.get('period_start'))
    end = rc.day(body.get('period_end'))
    if end < start:
        raise ValueError('账期结束日期不能早于开始日期')
    if (datetime.strptime(end, '%Y-%m-%d').date() - datetime.strptime(start, '%Y-%m-%d').date()).days > 366:
        raise ValueError('账期不能超过一年')
    cfg = _config(c)
    defs = {item['key']: item for item in _energy_item_defs(cfg, True)}
    item = str(body.get('item') or '')
    if item not in defs:
        raise ValueError('能源项目无效')
    quantity = None
    if body.get('quantity') not in (None, ''):
        quantity = float(_qty(body.get('quantity'), '账单用量'))
    amount = _cents(body.get('amount'), '账单金额')
    note = rc.text(body.get('note', ''), '账单备注', 200, False)
    sid = body.get('id')
    if body.get('voided'):
        if not sid:
            raise ValueError('作废账单缺少编号')
        row = c.execute('SELECT * FROM energy_settlements WHERE id=?', (sid,)).fetchone()
        if not row:
            raise ValueError('账单不存在')
        c.execute('UPDATE energy_settlements SET voided=1,updated_at=? WHERE id=?', (now, sid))
        if audit:
            audit(c, role, '作废能源结算账单', str(sid), dict(row), {'voided': 1})
        return energy_ledger(c, start[:7])
    if sid:
        row = c.execute('SELECT * FROM energy_settlements WHERE id=?', (sid,)).fetchone()
        if not row:
            raise ValueError('账单不存在')
        c.execute('UPDATE energy_settlements SET period_start=?,period_end=?,item=?,quantity=?,amount_cents=?,note=?,updated_at=? WHERE id=?', (start, end, item, quantity, amount, note, now, sid))
    else:
        c.execute('INSERT INTO energy_settlements(period_start,period_end,item,quantity,amount_cents,note,voided,created_at,updated_at) VALUES(?,?,?,?,?,?,0,?,?)', (start, end, item, quantity, amount, note, now, now))
    if audit:
        audit(c, role, '登记能源结算账单', item, None, {'period_start': start, 'period_end': end, 'amount_cents': amount})
    return energy_ledger(c, start[:7])
