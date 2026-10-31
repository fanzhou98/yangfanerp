"""Read-only management analysis. Preserve unknowns and state cost/time bases explicitly."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import resources_costs as rc
import production_management as fm
import trade
import production_daily as daily
import purchasing


def money(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def soy_composition(warehouses):
    result = []
    for w in warehouses:
        quantity = Decimal(w['qty'])
        crop = {k: Decimal(0) for k in ('春播', '复播', '未登记')}
        origin = {k: Decimal(0) for k in ('伊犁', '东北', '河南', '天津', '未登记')}
        for lot in w.get('lots', []):
            q = Decimal(lot['qty']); quality = lot.get('quality', {})
            crop[quality.get('sowing_type') if quality.get('sowing_type') in crop else '未登记'] += q
            origin[quality.get('origin') if quality.get('origin') in origin else '未登记'] += q
        for groups in (crop, origin):
            groups['未登记'] += max(Decimal(0), quantity - sum(groups.values()))
        analysis = daily.soybean_analysis([w])[0]
        varieties={}
        for lot in w.get('lots',[]):
            key=lot.get('quality',{}).get('soy_variety') or '品种待补';varieties[key]=varieties.get(key,Decimal(0))+Decimal(lot['qty'])
        analysis.update(varieties=[{'name':k,'qty':rc.ds(v)} for k,v in sorted(varieties.items())],protein_coverage_pct=rc.ds(Decimal(analysis['protein_known_kg'])/quantity*100) if quantity else '0',moisture_coverage_pct=rc.ds(Decimal(analysis['moisture_known_kg'])/quantity*100) if quantity else '0')
        result.append({**analysis, 'warehouse_id': w['warehouse_id'],
                       'value_cents': w['value_cents'], 'average_price': w['average_price'] if quantity else None,
                       'uncosted_qty': w['uncosted_qty'],
                       'sowing': {k: rc.ds(v) for k, v in crop.items()},
                       'origins': {k: rc.ds(v) for k, v in origin.items()}})
    return result


def people(c, day):
    groups = {r['id']: r['name'] for r in rc.rows(c, 'factory_groups')}
    employees = {r['id']: r['name'] for r in rc.rows(c, 'factory_employees')}
    schedules = [r for r in rc.rows(c, 'factory_schedules') if r['business_date'] == day]
    actual = [r for r in rc.rows(c, 'factory_attendance') if r['business_date'] == day]
    def latest(rows):
        return max(rows, key=lambda r: (r.get('updated_at', ''), r.get('version', 1)), default=None)
    schedule, attendance = latest(schedules), latest(actual)
    schedule_source='separate'
    if schedule is None and attendance and attendance.get('state')=='confirmed' and not attendance.get('source_schedule_id') and attendance.get('workflow')!='separate-v1':
        schedule=attendance;schedule_source='legacy-combined'
    planned = {e['employee_id']: e for e in (schedule or {}).get('entries', [])}
    recorded = {e['employee_id']: e for e in (attendance or {}).get('entries', [])}
    rows = []
    for eid in dict.fromkeys([*planned, *recorded]):
        p, a = planned.get(eid), recorded.get(eid)
        group = (a or p).get('group_id')
        rows.append({'group_id':group,'employee_name': (a or p).get('employee_name') or employees.get(eid, '历史员工'),
                     'group_name': groups.get(group, group or '未分组'),
                     'planned_group': groups.get((p or {}).get('group_id'), ''),
                     'planned_status': (p or {}).get('status'), 'actual_status': (a or {}).get('status') if a and a.get('entry_state',(attendance or {}).get('state'))=='confirmed' else 'draft' if a else None,
                     'planned_start': next((g.get('start_time') for g in (schedule or {}).get('groups', []) if g['group_id'] == (p or {}).get('group_id')), None),
                     'actual_start': next((g.get('start_time') for g in (attendance or {}).get('groups', []) if g['group_id'] == (a or {}).get('group_id')), None)})
    group_order={gid:i for i,gid in enumerate(groups)}
    rows.sort(key=lambda r:(group_order.get(r['group_id'],len(groups)),r['group_id'] or '',r['employee_name']))
    return {'schedule_source':schedule_source,'schedule_state': (schedule or {}).get('state', 'missing'),
            'attendance_state': (attendance or {}).get('state', 'missing'), 'rows': rows}


def accounts(c, day):
    orders = [o for o in rc.rows(c, 'orders') if o['business_date'] <= day and o.get('state') == 'reviewed']
    # No contractual customer credit term is recorded: expose aging, never invent overdue receivables.
    aging = [{'name': label, 'cents': 0} for label in ('当日', '1–7天', '8–30天', '30天以上')]
    for o in orders:
        age = (date.fromisoformat(day) - date.fromisoformat(o['business_date'])).days
        aging[0 if age == 0 else 1 if age <= 7 else 2 if age <= 30 else 3]['cents'] += fm.outstanding(o)
    p = purchasing.projection(c); payable = overdue = 0; details = []
    for order in p['orders']:
        paid = sum(x['amount_cents'] for x in p['payments'] if x['order_id'] == order['id'] and not x.get('charge_id'))
        for receipt in sorted((r for r in p['receipts'] if r['order_id'] == order['id']), key=lambda r: (r.get('due_date', r['business_date']), r['business_date'], r['id'])):
            applied = min(paid, receipt['amount_cents']); paid -= applied
            if receipt['business_date'] > day: continue
            left = receipt['amount_cents'] - applied; payable += left
            late = bool(receipt.get('due_date') and receipt['due_date'] < day)
            if late: overdue += left
            if left: details.append({'name': receipt['supplier_name'], 'due_date': receipt.get('due_date'), 'cents': left, 'overdue': late})
    for charge in p['charges']:
        if charge['business_date'] > day: continue
        left = charge['outstanding_cents']; payable += left
        late = bool(charge.get('due_date') and charge['due_date'] < day)
        if late: overdue += left
        if left: details.append({'name': charge.get('payee_name', '运卸费用'), 'due_date': charge.get('due_date'), 'cents': left, 'overdue': late})
    import finished_goods
    goods=finished_goods.projection(c,day[:7])
    for receipt in goods['receipts']:
        if receipt.get('voided') or receipt['business_date']>day:continue
        left=receipt['outstanding_cents'];payable+=left
        late=bool(receipt.get('due_date') and receipt['due_date']<day)
        if late:overdue+=left
        if left:details.append({'name':receipt['supplier_name']+'（外购成品）','due_date':receipt.get('due_date'),'cents':left,'overdue':late})
    wages=rc.rows(c,'payroll_records');undated=0
    for sheet in wages:
        if sheet.get('kind')!='sheet' or sheet.get('state')!='confirmed' or sheet['month']>day[:7]:continue
        left=sum(r.get('net_cents') or 0 for r in sheet['rows'])-sum(r['amount_cents'] for r in wages if r.get('kind')=='payment' and not r.get('voided') and r['month']==sheet['month'])
        if left>0:
            payable+=left;undated+=left;details.append({'name':sheet['month']+' 工资','due_date':None,'cents':left,'overdue':None})
    expense_pending=0
    for expense in rc.expense_projection(c):
        if expense.get('voided') or not expense['payment_required'] or expense['business_date']>day:continue
        left=expense['outstanding_cents']
        if expense['payment_state'] in ('approved','partial','paid'):
            payable+=left
            if left:details.append({'name':expense.get('partner') or '费用对象待补','due_date':None,'cents':left,'overdue':None})
        else:expense_pending+=left
    byproduct=0;byproduct_rows=[]
    for row in rc.rows(c,'byproduct_sales'):
        if row.get('voided') or row['business_date']>day:continue
        left=max(0,row['amount_cents']-row['received_cents'])
        if not left:continue
        byproduct+=left;byproduct_rows.append({'name':row['buyer'],'cents':left,'business_date':row['business_date']})
        age=(date.fromisoformat(day)-date.fromisoformat(row['business_date'])).days
        aging[0 if age==0 else 1 if age<=7 else 2 if age<=30 else 3]['cents']+=left
    return {'receivable_cents': sum(fm.outstanding(o) for o in orders)+byproduct, 'sales_receivable_cents':sum(fm.outstanding(o) for o in orders), 'byproduct_receivable_cents':byproduct,'byproduct_receivables':byproduct_rows,'expense_pending_cents':expense_pending,'undated_payable_cents':undated,'payable_cents': payable,
            'overdue_payable_cents': overdue, 'overdue_receivable_cents': None, 'aging': aging,
            'payables': details, 'receivables': fm.ar_alerts(c, day),
            'basis': '送货/入库日期截至所选日，收付款按当前余额；应付包含原料货款、外购成品、运卸、已确认未发工资和已核对未付费用；待核对费用单列，未计入已确认应付；货款按到期日优先抵付，工资无约定付款日不计逾期。应收含销售与豆渣，未登记合同账期，逾期额待核定，账龄预警不等于逾期。'}


def cost(c, day, daily_report, sales_cents):
    _, entries = rc.material_ledger(c, day)
    used = [e for e in entries if e['business_date'] == day and e['kind'] in ('consume', 'return', 'loss')]
    material = sum((-1 if e['kind'] == 'return' else 1) * e['cost_cents'] for e in used)
    unpriced = [e for e in used if e['kind'] != 'return' and (Decimal(e.get('uncosted_out_qty','0'))>0 or any(Decimal(l.get('uncosted_qty', '0')) > 0 for l in e.get('fifo_allocations', [])))]
    month = day[:7]; days = calendar.monthrange(int(day[:4]), int(day[5:7]))[1]
    expenses = rc.period_expenses(c,month)
    expense_total = sum(e['amount_cents'] for e in expenses)
    trips = [t for t in trade.records(c, 'trip') if not t.get('voided') and t['business_date'] == day]
    transport_basis=__import__('transport_closure').cost_basis(c,month,day);transport=transport_basis['amount_cents']
    non_transport = sum(e['amount_cents'] for e in expenses if e['category'] != 'transport')
    per_day = money(Decimal(non_transport) / days)
    categories = {e['category'] for e in expenses}
    missing = []
    essential = [('wages-production', '生产工资'), ('wages-management', '管理工资'), ('electricity', '生产电费'), ('gas', '燃气'), ('water', '水费'), ('rent', '租金'), ('depreciation', '折旧')]
    for key, label in essential:
        if key not in categories: missing.append({'field': month + ' ' + label, 'owner': '会计', 'target': 'expenses'})
    if unpriced: missing.append({'field': '领用批次入库金额', 'owner': '会计', 'target': 'materials'})
    if not any(e['kind'] == 'consume' for e in used): missing.append({'field': '当天原辅料领用', 'owner': '库管 / 厂长', 'target': 'materials'})
    if daily_report['record'] is None: missing.append({'field': '当天生产登记', 'owner': '厂长', 'target': 'factory'})
    if any(p.get('missing_data') for p in daily_report['products']): missing.append({'field': '成品产量与库存勾稽', 'owner': '库管 / 厂长', 'target': 'production-report'})
    period = next((r for r in rc.rows(c, 'resource_periods') if r['month'] == month), None)
    if not period or period.get('state') != 'closed': missing.append({'field': month + ' 成本月结（费用可能未录全）', 'owner': '会计', 'target': 'expenses'})
    import finished_goods
    goods=finished_goods.stock_cost(c,day,day);goods_cost=sum(r['sales_cost_cents'] for r in goods)
    if any(Decimal(r['unvalued_qty'])>0 for r in goods):missing.append({'field':'外购成品期初库存成本','owner':'会计','target':'payables'})
    byproduct = sum(r['amount_cents'] for r in rc.rows(c, 'byproduct_sales') if not r.get('voided') and r['business_date'] == day)
    missing.extend(transport_basis['gaps'])
    total = material + goods_cost + per_day + transport
    if not trips and any(o['business_date']==day for o in rc.rows(c,'orders')) and not any(e['category']=='transport' for e in expenses):
        missing.append({'field':'当天实际配送趟次与运费','owner':'会计','target':'dispatch'})
    return {'material_cents': material,'purchased_goods_cents':goods_cost, 'period_expense_cents': expense_total, 'allocated_expense_cents': per_day,
            'transport_cents': transport, 'month_days': days, 'byproduct_cents': byproduct, 'total_cents': total,
            'difference_cents': sales_cents + byproduct - total, 'missing_data': missing,
            'basis': '当日材料净领用（领用＋报损－退料）＋外购成品实发成本＋当天实际配送趟次运费＋当月非运输费用÷当月天数。运输按月结算出的应付只作会计凭据，利润测算按趟次明细计入，避免重复。工资只取费用台账。销售与当天生产可能跨日，退货抵扣、成品成本结转及税费尚未完整归集，差额仅供经营测算，不认定净利润。'}


def report(c, day):
    rc.day(day); d = date.fromisoformat(day)
    current = fm.daily_report(c, day)
    previous_dates = sorted({r['business_date'] for t in ('factory_daily', 'warehouse_plans') for r in rc.rows(c, t) if r['business_date'] < day}, reverse=True)
    previous_day = previous_dates[0] if previous_dates else None
    previous = fm.daily_report(c, previous_day) if previous_day else None
    products = []
    for p in current['products']:
        prev = next((r for r in (previous or {}).get('products', []) if r['product_id'] == p['product_id']), {})
        a, b = p.get('settlement_yield'), prev.get('settlement_yield')
        comparable = a is not None and b is not None and Decimal(b) > 0 and not p.get('settlement_pending') and not prev.get('settlement_pending') and p.get('main_material') == prev.get('main_material') and current.get('production_config')==(previous or {}).get('production_config') and all(current['settings'].get(k)==(previous or {}).get('settings',{}).get(k) for k in ('large_slurry_kg','small_slurry_kg','skin_slurry_kg','large_slurry_crates','small_slurry_crates','skin_slurry_crates'))
        delta = (Decimal(a) / Decimal(b) - 1) * 100 if comparable else None
        products.append({**p, 'previous_yield': b, 'change_pct': rc.ds(delta) if delta is not None else None,
                         'change_alert': delta is not None and abs(delta) > Decimal(current['settings']['evidence_alert_pct'])})
    sale = fm.sales_report(c, day, day)
    revenue = sum(r['sales_cents'] for r in sale['customers'])
    markets = {}
    for r in sale['customers']:
        key = (r['region'], r['market']); markets[key] = markets.get(key, 0) + r['sales_cents']
    sale['market_totals'] = [{'region': k[0], 'market': k[1], 'sales_cents': v} for k, v in markets.items()]
    costs = cost(c, day, current, revenue)
    orders = rc.rows(c, 'orders'); trend = []
    for customer in sale['customers']:
        purchased={}
        for order in orders:
            if order['business_date']!=day or order['customer_id']!=customer['customer_id']:continue
            for line in order['lines']:
                key=(line['product_name'],line['unit']);purchased[key]=purchased.get(key,Decimal(0))+Decimal(line.get('actual_qty') or '0')
        customer['purchased_products']=[{'name':k[0],'unit':k[1],'qty':rc.ds(v)} for k,v in purchased.items() if v>0]
    for offset in range(13, -1, -1):
        when = (d - timedelta(days=offset)).isoformat(); day_orders = [o for o in orders if o['business_date'] == when]
        trend.append({'date': when, 'sales_cents': sum(o.get('total_cents', 0) for o in day_orders if o.get('state') == 'reviewed'), 'pending_orders': sum(o.get('state') != 'reviewed' for o in day_orders), 'has_orders': bool(day_orders)})
    # Value production with today's reviewed sales unit price only; no price -> unknown.
    for p in products:
        sold = next((r for r in sale['products'] if r['product_id'] == p['product_id']), None)
        reviewed_qty = sum((Decimal(l.get('actual_qty') or '0') for o in orders if o['business_date'] == day and o.get('state') == 'reviewed' for l in o['lines'] if l['product_id'] == p['product_id']), Decimal(0))
        p['production_value_cents'] = money(Decimal(p['derived_qty']) * sold['sales_cents'] / reviewed_qty) if p.get('derived_qty') is not None and sold and reviewed_qty else None
    import reporting
    costs['components']=sorted([{'label':label,'value':value} for label,value in [('材料净领用',costs['material_cents']),('外购实发成本',costs['purchased_goods_cents']),('实际配送运费',costs['transport_cents']),('期间费用日摊',costs['allocated_expense_cents'])]],key=lambda r:-r['value'])
    day_sale=reporting.sales(c,day,day)
    costs['difference_cents']=day_sale['net_cents']+costs['byproduct_cents']-costs['total_cents'] if day_sale['net_cents'] is not None else None
    costs['bridge']=reporting.waterfall([('原单归属净额','净额',day_sale['net_cents']),('豆渣收入','豆渣',costs['byproduct_cents']),('材料净领用','材料',-costs['material_cents']),('外购实发成本','外购',-costs['purchased_goods_cents']),('当天配送运费','运费',-costs['transport_cents']),('期间费用日摊','费用',-costs['allocated_expense_cents'])],day+' · 仅已登记依据；收入已扣原单退货与折让。'+costs['basis']+'毛利润＝收入－材料与外购成本；净利润＝毛利润－运费与期间费用；当日依据不全时净利润偏高。',subtotals={4:('毛利润','毛利')})
    persons=people(c,day);soy=soy_composition(current['soybean_warehouses'])
    return {'day_sales':day_sale,'support_charts':[reporting.inventory_composition(soy),reporting.yield_comparison(products,current['settings']['evidence_alert_pct'])],'report_context':reporting.context('每日经营判断',day,day,'已复核订单 / 生产与盘库 / 材料批次 / 费用 / 账款','数据截至所选业务日；账款收付款按当前状态。产量及公斤为所列依据下的估算；不提供动销、临期或净利润。'), 'summary':{'reviewed_orders':sum(o['business_date']==day and o.get('state')=='reviewed' for o in orders),'pending_orders':sum(o['business_date']==day and o.get('state')!='reviewed' for o in orders),'actual_people':sum(r['actual_status'] in ('full','half','present') for r in persons['rows']),'planned_people':sum(r['planned_status'] in ('full','half','present') for r in persons['rows']),'soy_kg':rc.ds(sum((Decimal(w['qty']) for w in soy),Decimal(0)))},'business_date': day, 'previous_day': previous_day, 'products': products,
            'people': persons, 'issues': [e for e in rc.material_ledger(c,day)[1] if e['business_date']==day and e['kind'] in ('consume','return','loss')], 'systems': current['systems'],
            'sales': sale, 'sales_cents': revenue, 'trend': trend,
            'accounts': accounts(c, day), 'soy': soy, 'cost': costs,
            'yield_threshold_pct': current['settings']['evidence_alert_pct']}
