"""Product operating estimates. No tax/COGS close -> never net profit.
Actual bean pools and FIFO valuations are shared with production / material reports.
Unknown weights or unallocated cost pools remain visible, never become zero costs.
"""
import calendar
from decimal import Decimal
from datetime import date
import resources_costs as rc
import production_management as pm
import production_daily as daily
import material_allocation as ma
import finished_goods
import trade

WAGE_CATEGORIES=('wages-production','wages-delivery','wages-management')


def line_kg(c,line,product):
    value,_=pm.sales_line_kg(line,'reviewed')
    return value


def month(c,year_month):
    rc.day(year_month+'-01');end=year_month+'-'+str(calendar.monthrange(int(year_month[:4]),int(year_month[5:7]))[1])
    products={p['id']:dict(p) for p in c.execute('SELECT * FROM products')}
    orders=[o for o in rc.rows(c,'orders') if o.get('state')=='reviewed' and o['business_date'].startswith(year_month)]
    revenue={};kg={};missing=set();count={};adjustments={}
    for o in orders:
        weights={}
        for l in o.get('lines',[]):
            pid=l['product_id'];value=int(l.get('amount_cents') or 0);revenue[pid]=revenue.get(pid,0)+value;weights[pid]=weights.get(pid,Decimal(0))+max(value,0)
            weight=line_kg(c,l,products.get(pid))
            if weight is None:missing.add(pid)
            else:kg[pid]=kg.get(pid,Decimal(0))+weight
            count[pid]=count.get(pid,0)+1
        for pid,value in ma.split(sum(o.get(k,0) for k in ('discount_cents','rounding_cents')),weights).items():adjustments[pid]=adjustments.get(pid,0)+value
    for r in rc.rows(c,'sales_returns'):
        if r.get('voided') or not r.get('finance') or r['finance']['state']!='posted':continue
        if r.get('order_id') not in {o['id'] for o in orders}:continue
        pid=r['product_id'];adjustments[pid]=adjustments.get(pid,0)+r['finance']['amount_cents']
    _,ledger=rc.material_ledger(c,end);entries=[e for e in ledger if e['business_date'].startswith(year_month) and e['kind'] in ('consume','return','loss')]
    allocation=ma.month_report(c,year_month);bean_qty=sum((Decimal(p['issued_kg']) for p in allocation['pools']),Decimal(0));bean_cost=allocation['total_cents'];bean_kg={};soy={}
    for r in allocation['allocations']:
        pid=r['product_id'];bean_kg[pid]=bean_kg.get(pid,Decimal(0))+Decimal(r['allocated_kg']);soy[pid]=soy.get(pid,0)+r['cost_cents']
    unpriced_materials=[e for e in entries if Decimal(e.get('uncosted_out_qty') or '0')>0]
    soy_loss=sum(e['cost_cents'] for e in entries if e['material_id']=='RM-SOY' and e['kind']=='loss')
    direct={};shared_materials=soy_loss
    for e in entries:
        if e['material_id']=='RM-SOY':continue
        value=e['cost_cents']*(-1 if e['kind']=='return' else 1);pid=e.get('product_id')
        if pid in products:direct[pid]=direct.get(pid,0)+value
        else:shared_materials+=value
    goods=finished_goods.stock_cost(c,year_month+'-01',end);goods_cost={r['product_id']:r['sales_cost_cents'] for r in goods}
    expenses=rc.period_expenses(c,year_month)
    wages=sum(e['amount_cents'] for e in expenses if e['category'] in WAGE_CATEGORIES and not e.get('product_id'))
    transport_basis=__import__('transport_closure').cost_basis(c,year_month);transport=transport_basis['amount_cents']
    other=sum(e['amount_cents'] for e in expenses if not e.get('product_id') and e['category'] not in WAGE_CATEGORIES+('transport',))
    dedicated={}
    for e in expenses:
        if e.get('product_id') in products and e['category']!='transport':dedicated[e['product_id']]=dedicated.get(e['product_id'],0)+e['amount_cents']
    byproduct=sum(r['amount_cents'] for r in rc.rows(c,'byproduct_sales') if not r.get('voided') and r['business_date'].startswith(year_month))
    # Do not allocate any weighted pool when a required denominator is incomplete.
    weight_alloc=ma.split(wages+transport,kg) if not missing else {}
    bean_pool=other+shared_materials-byproduct
    bean_alloc=ma.split(bean_pool,bean_kg) if not allocation['unallocated_cents'] else {}
    gaps=[{'field':'成品存货成本结转与税费未完整归集，不能认定净利润','owner':'会计','target':'production'}]
    gaps.extend(transport_basis['gaps'])
    if any(e.get('is_estimate') for e in expenses):gaps.append({'field':'本月含暂估成本，账单到后仍需核销补差','owner':'会计','target':'expenses'})
    if allocation['unallocated_cents']:gaps.append({'field':'大豆成本尚有 '+str(allocation['unallocated_cents'])+' 分未分摊；须补上豆、浆缸或入库计价','owner':'厂长 / 会计','target':'production'})
    if unpriced_materials:gaps.append({'field':'部分领用 / 报损批次成本未完整计价','owner':'会计','target':'materials'})
    if missing:gaps.append({'field':'部分实发缺少公斤依据，工资及运费不能按重量完整分摊','owner':'库管 / 会计','target':'weighing'})
    if not any(p['month']==year_month and p['state']=='closed' for p in rc.rows(c,'resource_periods')):gaps.append({'field':'成本月份未结账，费用可能未录全','owner':'会计','target':'expenses'})
    rows=[]
    for pid in sorted(set(revenue)|set(soy)|set(direct)|set(dedicated)|set(goods_cost)):
        if pid not in products:continue
        product=products[pid];q=kg.get(pid,Decimal(0));income=revenue.get(pid,0)-adjustments.get(pid,0);beans=bean_kg.get(pid,Decimal(0));soy_cost=soy.get(pid,0);direct_cost=soy_cost+direct.get(pid,0)+goods_cost.get(pid,0);indirect=dedicated.get(pid,0)+weight_alloc.get(pid,0)+bean_alloc.get(pid,0)
        reasons=['实际配送运费依据尚未齐全'] if transport_basis['gaps'] else []
        if any(not e.get('product_id') or e.get('product_id')==pid for e in unpriced_materials):reasons.append('材料批次计价不完整')
        if pid in missing:reasons.append('实发公斤依据缺失')
        if allocation['unallocated_cents'] and daily.uses_slurry(daily.main_material(c,product)):reasons.append('来源大豆成本待核对')
        if missing and wages+transport:reasons.append('工资 / 运费重量分摊待核对')
        if bean_pool and (allocation['unallocated_cents'] or not bean_kg):reasons.append('共用成本折豆分摊待核对')
        if any(r['product_id']==pid and Decimal(r.get('unvalued_qty') or '0') for r in goods):reasons.append('外购成品期初成本待补')
        net=income-direct_cost-indirect if not reasons else None
        rows.append({'product_id':pid,'product_name':product['name'],'unit':product['unit'],'orders':count.get(pid,0),'qty_kg':None if pid in missing else rc.ds(q),'revenue_cents':income,'gross_sales_cents':revenue.get(pid,0),'reductions_cents':adjustments.get(pid,0),'soy_kg':rc.ds(beans),'soy_cost_cents':soy_cost,'direct_material_cents':direct.get(pid,0),'purchased_cents':goods_cost.get(pid,0),'direct_cents':direct_cost,'gross_cents':income-direct_cost,'indirect_cents':indirect,'net_cents':net,'missing_data':reasons,
            'gross_margin':rc.ds(Decimal(income-direct_cost)/income) if income else None,'net_margin':rc.ds(Decimal(net)/income) if net is not None and income else None,'break_even_price':rc.ds(Decimal(direct_cost+indirect)/q) if q and pid not in missing and not reasons else None})
    rows.sort(key=lambda r:(r['net_cents'] is None,-(r['net_cents'] or 0),r['product_name']))
    total={'qty_kg':None if missing else rc.ds(sum(kg.values(),Decimal(0))),'revenue_cents':sum(r['revenue_cents'] for r in rows),'direct_cents':sum(r['direct_cents'] for r in rows),'gross_cents':sum(r['gross_cents'] for r in rows),'indirect_cents':sum(r['indirect_cents'] for r in rows),'net_cents':None if any(r['net_cents'] is None for r in rows) else sum(r['net_cents'] for r in rows),'soy_kg':rc.ds(bean_qty),'soy_cost_cents':bean_cost}
    import reporting
    return {'month':year_month,'rows':rows,'total':total,'gaps':gaps,'report_context':reporting.context('产品经营测算',year_month+'-01',end,'已复核发货 / 原单归属退货 / FIFO材料耗用 / 实际供浆分摊 / 外购实发成本 / 期间费用 / 配送趟次','采用本次读取时的已复核状态，跨期退货按原单归属。生产耗用与发货可能跨期，尚未完整进行成品成本结转及税费核算。'),
        'costs':{'bean_qty_kg':rc.ds(bean_qty),'bean_cost_cents':bean_cost,'unallocated_bean_cents':allocation['unallocated_cents'],'wages_cents':wages,'transport_cents':transport,'other_expenses_cents':other,'shared_materials_cents':shared_materials,'soy_loss_cents':soy_loss,'byproduct_cents':byproduct,'weight_pool_cents':wages+transport,'bean_pool_cents':bean_pool},
        'basis':'收入为已复核发货减原单归属已复核退货及折让；大豆采用实际供浆分摊和批次领用成本；辅料按归属、外购按实发成本。工资及运费按完整实发公斤分摊，共用期间费用和材料（含大豆报损）扣豆渣收入后按实际分摊用豆量分摊；专属费用直接归属。缺项保留待核对；费用与生产耗用不等于已完成销售成本结转，差额为经营测算。'}


legacy_month=month

def month(c,year_month):
    import cost_allocation as ca
    period=next((r for r in rc.rows(c,'resource_periods') if r['month']==year_month),None)
    if period and period['state']=='closed' and period.get('report_snapshot'):
        import copy
        return copy.deepcopy(period['report_snapshot'])
    report=legacy_month(c,year_month)
    reused={r['product_id'] for r in rc.rows(c,'sales_returns') if not r.get('voided') for d in r.get('disposals',[]) if not d.get('voided') and d['kind']=='restock' and d['business_date'].startswith(year_month)}
    reused.update(o['product_id'] for batch in rc.rows(c,'processing_batches') if not batch.get('voided') and batch.get('origin')=='customer_return' and batch['business_date'].startswith(year_month) for o in batch.get('outputs',[]))
    if reused:
        report['gaps'].append({'field':'退货回可发及转加工的原批存货成本待核对，不能据此确认产品利润','owner':'会计','target':'returns'})
        for row in report['rows']:
            if row['product_id'] in reused:row['missing_data'].append('退货来源批次成本待核对')

    if period and period['state']=='closed' and period.get('allocation_rule')!=ca.RULE:
        report['allocation_version']='legacy-closed';return report
    expenses=[e for e in rc.period_expenses(c,year_month) if e['category']!='transport']
    costs=report['costs']
    extra=[{'id':'actual-trips','label':'实际配送趟次','amount_cents':costs['transport_cents']},
           {'id':'shared-materials','label':'共用材料与报损','amount_cents':costs['shared_materials_cents']},
           {'id':'byproduct-credit','label':'豆渣收入抵减','amount_cents':-costs['byproduct_cents']}]
    allocation=ca.allocate(c,year_month+'-01',report['report_context']['end'],expenses,[e for e in extra if e['amount_cents']])
    report['allocation']={k:v for k,v in allocation.items() if k not in ('basis','allocations')}
    report['allocation_version']=ca.RULE
    obsolete=('实发公斤依据缺失','工资 / 运费重量分摊待核对','共用成本折豆分摊待核对')
    for row in report['rows']:
        pid=row['product_id'];b=allocation['basis'][pid]
        row['qty_kg']=None if b['missing'] or b['pending'] else rc.ds(b['kg'])
        row['self_settled_kg']=None if b['mixed'] or b['missing'] or b['pending'] else rc.ds(b['self_kg'])
        row['processing_intensity']=rc.ds(ca.factor(c,pid,year_month))
        row['allocation_weight']=rc.ds(b['self_kg']*ca.factor(c,pid,year_month)) if not b['excluded'] and row['self_settled_kg'] is not None else None
        reasons=[r for r in row['missing_data'] if r not in obsolete]
        if b['missing'] or b['pending']:reasons.append('结算公斤或复核状态待核对')
        affected=[d for d in allocation['details'] if d['unallocated_cents'] and pid in d['product_ids']]
        if affected:reasons.append('共用费用待分摊：'+'；'.join(dict.fromkeys(r for d in affected for r in d['reasons'])))
        row['missing_data']=reasons;row['indirect_cents']=allocation['allocations'].get(pid,0)
        row['net_cents']=row['revenue_cents']-row['direct_cents']-row['indirect_cents'] if not reasons else None
        q=Decimal(row['qty_kg']) if row['qty_kg'] is not None else Decimal(0)
        row['net_margin']=rc.ds(Decimal(row['net_cents'])/row['revenue_cents']) if row['net_cents'] is not None and row['revenue_cents'] else None
        row['break_even_price']=rc.ds(Decimal(row['direct_cents']+row['indirect_cents'])/q) if q>0 and not reasons else None
    report['total']['indirect_cents']=allocation['allocated_cents']
    report['total']['net_cents']=None if allocation['pending_items'] or any(r['net_cents'] is None for r in report['rows']) else sum(r['net_cents'] for r in report['rows'])
    report['total']['qty_kg']=None if any(r['qty_kg'] is None for r in report['rows']) else rc.ds(sum((Decimal(r['qty_kg']) for r in report['rows']),Decimal(0)))
    report['gaps']=[g for g in report['gaps'] if '工资及运费不能按重量' not in g['field']]
    if allocation['pending_items']:report['gaps'].append({'field':'共用费用存在待分摊金额，见逐笔分摊依据','owner':'会计 / 出纳','target':'expenses'})
    report['basis']='结算公斤加权分摊：本期已复核自产结算公斤 × 产品加工强度系数；每笔费用只在指定承担产品内分摊。外购成品不参与；混合来源未区分、待复核或缺公斤时列待分摊。标准重量仅用于偏差预警。大豆直接成本仍按实际供浆归属；自产成品成本结转尚未完整，结果为经营测算。'
    report['report_context']['basis']=report['basis']
    return report
