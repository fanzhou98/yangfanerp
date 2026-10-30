"""Product operating estimates. No tax/COGS close -> never net profit.
Actual bean pools and FIFO valuations are shared with production / material reports.
Unknown weights or unallocated cost pools remain visible, never become zero costs.
"""
import calendar
from decimal import Decimal, ROUND_HALF_UP
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
    amort=ma.amortized_shares(c,year_month)
    amortized_ids={item['entry_id'] for item in rc.amortizations(c)}
    entries=[e for e in entries if e['id'] not in amortized_ids]
    entries,workshop_adjust,workshop=__import__('material_consumption').cost_entries(c,year_month,entries)
    workshop_ratios=workshop_adjust
    amortized_by_product={};amort_shared=0
    for item in amort:
        pids=[pid for pid in item['product_ids'] if pid in products]
        if not pids:amort_shared+=item['month_cents']
        else:
            for pid,cents in item['allocations'].items():
                if pid in products:amortized_by_product[pid]=amortized_by_product.get(pid,0)+cents
    allocation=ma.month_report(c,year_month);bean_qty=sum((Decimal(p['issued_kg']) for p in allocation['pools']),Decimal(0));bean_cost=allocation['total_cents'];bean_kg={};soy={}
    for r in allocation['allocations']:
        pid=r['product_id'];bean_kg[pid]=bean_kg.get(pid,Decimal(0))+Decimal(r['allocated_kg']);soy[pid]=soy.get(pid,0)+r['cost_cents']
    scoped=ma.scope_allocations(c,year_month,entries,ma._day_bean(allocation))
    scoped_by_product={}
    for detail in scoped.values():
        for pid,value in detail['allocations'].items():
            scoped_by_product[pid]=scoped_by_product.get(pid,0)+value
    equal_scoped=any(d['basis']=='coverage-equal' for d in scoped.values())
    pending_material=sum(max(0,d['amount_cents']-sum(d['allocations'].values())) for d in scoped.values())
    pending_material_products={pid for d in scoped.values() if d['amount_cents']!=sum(d['allocations'].values()) for pid in d['product_ids']}
    material_issues=__import__('material_consumption').closing_issues(c,year_month,workshop)
    unpriced_materials=[e for e in entries if Decimal(e.get('uncosted_out_qty') or '0')>0]
    soy_loss=sum(e['cost_cents'] for e in entries if e['material_id']=='RM-SOY' and e['kind']=='loss')
    direct={};shared_materials=soy_loss+amort_shared
    for e in entries:
        if e['material_id']=='RM-SOY':continue
        if len(e.get('product_ids') or [])>=2:continue
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
    gaps.extend({'field':reason,'owner':'厂长 / 会计','target':'workshop'} for reason in material_issues)
    for item in scoped.values():
        if item['basis']=='packaging-pending':gaps.append({'field':item['material_name']+' 包装规格或生产数量不全，成本保留待分配','owner':'厂长 / 会计','target':'workshop'})
    if any(e.get('is_estimate') for e in expenses):gaps.append({'field':'本月含暂估成本，账单到后仍需核销补差','owner':'会计','target':'expenses'})
    if allocation['unallocated_cents']:gaps.append({'field':'大豆成本尚有 '+str(allocation['unallocated_cents'])+' 分未分摊；须补上豆、浆缸或入库计价','owner':'厂长 / 会计','target':'production'})
    if unpriced_materials:gaps.append({'field':'部分领用 / 报损批次成本未完整计价','owner':'会计','target':'materials'})
    if equal_scoped:gaps.append({'field':'有辅料领用缺少覆盖期用豆依据，已按承担产品均分，请核对供浆登记','owner':'厂长 / 会计','target':'production'})
    if any(item['basis']=='amortization-equal' for item in amort):gaps.append({'field':'有分期耗材缺少当月用豆依据，已按承担产品均分，请核对供浆登记','owner':'厂长 / 会计','target':'production'})
    if workshop_ratios:
        gaps.append({'field':'车间余料已按盘点结转实耗，未盘点物料仍按领用全额计入','owner':'厂长 / 会计','target':'production'})
        for w in workshop['rows']:
            if w['counted'] and w['prior_missing']:gaps.append({'field':w['material_name']+' 首月车间余料按 0 起算，请补上月盘点','owner':'厂长','target':'production'})
            if w['counted'] and w['over_issue']:gaps.append({'field':w['material_name']+' 盘点数量大于期初加领用，请复核','owner':'厂长','target':'production'})
    if missing:gaps.append({'field':'部分实发缺少公斤依据，工资及运费不能按重量完整分摊','owner':'库管 / 会计','target':'weighing'})
    if not any(p['month']==year_month and p['state']=='closed' for p in rc.rows(c,'resource_periods')):gaps.append({'field':'成本月份未结账，费用可能未录全','owner':'会计','target':'expenses'})
    procs=[b for b in rc.rows(c,'processing_batches') if not b.get('voided') and str(b.get('business_date') or '')[:7]==year_month]
    proc_pids={b.get('product_id') for b in procs}|{o.get('product_id') for b in procs for o in (b.get('outputs') or [])}
    rows=[]
    for pid in sorted(set(revenue)|set(soy)|set(direct)|set(dedicated)|set(goods_cost)|set(scoped_by_product)|set(amortized_by_product)|{x for x in proc_pids if x in products}):
        if pid not in products:continue
        product=products[pid];q=kg.get(pid,Decimal(0));income=revenue.get(pid,0)-adjustments.get(pid,0);beans=bean_kg.get(pid,Decimal(0));soy_cost=soy.get(pid,0);scoped_cost=scoped_by_product.get(pid,0);amortized_cost=amortized_by_product.get(pid,0);direct_cost=soy_cost+direct.get(pid,0)+scoped_cost+amortized_cost+goods_cost.get(pid,0);indirect=dedicated.get(pid,0)+weight_alloc.get(pid,0)+bean_alloc.get(pid,0)
        reasons=['实际配送运费依据尚未齐全'] if transport_basis['gaps'] else []
        if pid in pending_material_products:reasons.append('材料成本待分配')
        if material_issues:reasons.append('车间余料盘点或包材成本待核对')
        if any(not e.get('product_id') or e.get('product_id')==pid for e in unpriced_materials):reasons.append('材料批次计价不完整')
        if pid in missing:reasons.append('实发公斤依据缺失')
        if allocation['unallocated_cents'] and daily.uses_slurry(daily.main_material(c,product)):reasons.append('来源大豆成本待核对')
        if missing and wages+transport:reasons.append('工资 / 运费重量分摊待核对')
        if bean_pool and (allocation['unallocated_cents'] or not bean_kg):reasons.append('共用成本折豆分摊待核对')
        if any(r['product_id']==pid and Decimal(r.get('unvalued_qty') or '0') for r in goods):reasons.append('外购成品期初成本待补')
        net=income-direct_cost-indirect if not reasons else None
        rows.append({'product_id':pid,'product_name':product['name'],'unit':product['unit'],'orders':count.get(pid,0),'qty_kg':None if pid in missing else rc.ds(q),'revenue_cents':income,'gross_sales_cents':revenue.get(pid,0),'reductions_cents':adjustments.get(pid,0),'soy_kg':rc.ds(beans),'soy_cost_cents':soy_cost,'direct_material_cents':direct.get(pid,0),'scope_material_cents':scoped_cost,'amortized_cents':amortized_cost,'purchased_cents':goods_cost.get(pid,0),'direct_cents':direct_cost,'gross_cents':income-direct_cost,'indirect_cents':indirect,'net_cents':net,'missing_data':reasons,
            'gross_margin':rc.ds(Decimal(income-direct_cost)/income) if income else None,'net_margin':rc.ds(Decimal(net)/income) if net is not None and income else None,'break_even_price':rc.ds(Decimal(direct_cost+indirect)/q) if q and pid not in missing and not reasons else None})
    transfer_in={};transfer_out={};transfers=[]
    by_pid={r['product_id']:r for r in rows};groups={};edges={};indegree={}
    for batch in sorted(procs,key=lambda b:(b['business_date'],b['id'])):
        src=batch.get('product_id');input_kg=Decimal(str(batch.get('input_kg') or 0))
        weights={o['product_id']:Decimal(str(o.get('net_kg') or o.get('qty') or 0)) for o in batch.get('outputs',[]) if o.get('product_id') in products and Decimal(str(o.get('net_kg') or o.get('qty') or 0))>0}
        if input_kg<=0 or not weights:continue
        groups.setdefault(src,[]).append((batch,input_kg,weights));indegree.setdefault(src,0)
        for target in weights:
            indegree.setdefault(target,0)
            if target not in edges.setdefault(src,set()):
                edges[src].add(target);indegree[target]+=1
    ready=sorted(pid for pid,n in indegree.items() if not n);ordered=[]
    while ready:
        src=ready.pop(0);ordered.append(src)
        for target in sorted(edges.get(src,set())):
            indegree[target]-=1
            if not indegree[target]:ready.append(target);ready.sort()
    blocked=set(indegree)-set(ordered)
    def block(pid,reason):
        blocked.add(pid)
        if pid in by_pid:
            if reason not in by_pid[pid]['missing_data']:by_pid[pid]['missing_data'].append(reason)
            by_pid[pid]['net_cents']=None
    if blocked:
        gaps.append({'field':'转加工依赖存在环路或依赖环路，成本待核对','owner':'会计 / 厂长','target':'production'})
        for pid in list(blocked):block(pid,'转加工依赖环路，成本待核对')
    for src in ordered:
        batches=groups.get(src,[])
        if not batches:continue
        row=by_pid.get(src)
        if src in blocked or not row or row['qty_kg'] is None or src in pending_material_products or material_issues:
            gaps.append({'field':'转加工批次缺少来源产品结算公斤或材料成本，不能结转','owner':'会计 / 厂长','target':'production'})
            for target in edges.get(src,set()):block(target,'转加工来源材料成本待核对')
            continue
        qty=Decimal(str(row['qty_kg']));material=int(row['soy_cost_cents'])+int(row['direct_material_cents'])+int(row['scope_material_cents'])+int(row['amortized_cents'])+transfer_in.get(src,0)
        if material<0:
            for target in edges.get(src,set()):block(target,'转加工来源材料成本异常')
            continue
        pool_weights={'retained':max(qty,Decimal(0))}
        pool_weights.update({'batch:'+batch['id']:input_kg for batch,input_kg,_ in batches})
        denom=sum(pool_weights.values(),Decimal(0));amounts=ma.split(material,pool_weights)
        for batch,input_kg,weights in batches:
            amount=amounts.get('batch:'+batch['id'],0)
            if not amount:continue
            transfer_out[src]=transfer_out.get(src,0)+amount
            shares=ma.split(amount,weights)
            for pid,share in shares.items():transfer_in[pid]=transfer_in.get(pid,0)+share
            transfers.append({'batch_id':batch['id'],'business_date':batch['business_date'],'source_product_id':src,'source_product_name':products.get(src,{}).get('name',src),'input_kg':rc.ds(input_kg),'unit_material_cents':rc.ds((Decimal(material)/denom).quantize(Decimal('0.01'))),'amount_cents':amount,'targets':[{'product_id':pid,'product_name':products[pid]['name'],'cents':value} for pid,value in shares.items()]})
    for row in rows:
        pid=row['product_id'];inn=transfer_in.get(pid,0);out=transfer_out.get(pid,0)
        row['transfer_in_cents']=inn;row['transfer_out_cents']=out
        if not inn and not out:continue
        row['direct_cents']=row['direct_cents']+inn-out;row['gross_cents']=row['revenue_cents']-row['direct_cents']
        q=Decimal(row['qty_kg']) if row['qty_kg'] else Decimal(0)
        row['net_cents']=None if row['missing_data'] else row['revenue_cents']-row['direct_cents']-row['indirect_cents']
        row['gross_margin']=rc.ds(Decimal(row['gross_cents'])/row['revenue_cents']) if row['revenue_cents'] else None
        row['net_margin']=rc.ds(Decimal(row['net_cents'])/row['revenue_cents']) if row['net_cents'] is not None and row['revenue_cents'] else None
        row['break_even_price']=rc.ds(Decimal(row['direct_cents']+row['indirect_cents'])/q) if q>0 and not row['missing_data'] else None
    if transfers:gaps.append({'field':'转加工材料成本按来源产品当月材料单位成本结转，来源结算公斤口径须复核','owner':'会计','target':'production'})
    rows.sort(key=lambda r:(r['net_cents'] is None,-(r['net_cents'] or 0),r['product_name']))
    total={'qty_kg':None if missing else rc.ds(sum(kg.values(),Decimal(0))),'revenue_cents':sum(r['revenue_cents'] for r in rows),'direct_cents':sum(r['direct_cents'] for r in rows),'gross_cents':sum(r['gross_cents'] for r in rows),'indirect_cents':sum(r['indirect_cents'] for r in rows),'net_cents':None if any(r['net_cents'] is None for r in rows) else sum(r['net_cents'] for r in rows),'soy_kg':rc.ds(bean_qty),'soy_cost_cents':bean_cost}
    import reporting
    return {'month':year_month,'rows':rows,'total':total,'gaps':gaps,'report_context':reporting.context('产品经营测算',year_month+'-01',end,'已复核发货 / 原单归属退货 / FIFO材料耗用 / 实际供浆分摊 / 外购实发成本 / 期间费用 / 配送趟次','采用本次读取时的已复核状态，跨期退货按原单归属。生产耗用与发货可能跨期，尚未完整进行成品成本结转及税费核算。'),
        'costs':{'pending_material_cents':pending_material,'material_closing_issues':material_issues,'bean_qty_kg':rc.ds(bean_qty),'bean_cost_cents':bean_cost,'unallocated_bean_cents':allocation['unallocated_cents'],'wages_cents':wages,'transport_cents':transport,'other_expenses_cents':other,'shared_materials_cents':shared_materials,'scope_materials_cents':sum(scoped_by_product.values()),'workshop_adjust_cents':sum(workshop_adjust.values()),'transfer_cents':sum(transfer_in.values()),'amortized_cents':sum(amortized_by_product.values())+amort_shared,'soy_loss_cents':soy_loss,'byproduct_cents':byproduct,'weight_pool_cents':wages+transport,'bean_pool_cents':bean_pool},
        'material_allocations':list(scoped.values())+amort,
        'transfers':transfers,'workshop':workshop,
        'basis':'收入为已复核发货减原单归属已复核退货及折让；大豆采用实际供浆分摊和批次领用成本；辅料按归属，多产品领用按覆盖期实际用豆量分摊；外购按实发成本。工资及运费按完整实发公斤分摊，共用期间费用和材料（含大豆报损）扣豆渣收入后按实际分摊用豆量分摊；专属费用直接归属。缺项保留待核对；费用与生产耗用不等于已完成销售成本结转，差额为经营测算。'}


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
    report['total']['net_cents']=None if costs.get('pending_material_cents') or costs.get('material_closing_issues') or allocation['pending_items'] or any(r['net_cents'] is None for r in report['rows']) else sum(r['net_cents'] for r in report['rows'])
    report['total']['qty_kg']=None if any(r['qty_kg'] is None for r in report['rows']) else rc.ds(sum((Decimal(r['qty_kg']) for r in report['rows']),Decimal(0)))
    report['gaps']=[g for g in report['gaps'] if '工资及运费不能按重量' not in g['field']]
    if allocation['pending_items']:report['gaps'].append({'field':'共用费用存在待分摊金额，见逐笔分摊依据','owner':'会计 / 出纳','target':'expenses'})
    report['basis']='结算公斤加权分摊：本期已复核自产结算公斤 × 产品加工强度系数；每笔费用只在指定承担产品内分摊。外购成品不参与；混合来源未区分、待复核或缺公斤时列待分摊。标准重量仅用于偏差预警。大豆直接成本仍按实际供浆归属；自产成品成本结转尚未完整，结果为经营测算。'
    def _margin(part,whole):
        if part is None or not whole:return None
        return rc.ds(Decimal(part)/Decimal(whole))
    statement={
        'revenue_cents':report['total']['revenue_cents'],
        'direct_cents':report['total']['direct_cents'],
        'gross_cents':report['total']['gross_cents'],
        'period_cents':report['total']['indirect_cents'],
        'profit_cents':report['total']['net_cents'],
        'gross_margin':_margin(report['total']['gross_cents'],report['total']['revenue_cents']),
        'profit_margin':_margin(report['total']['net_cents'],report['total']['revenue_cents']),
        'byproduct_cents':report['costs']['byproduct_cents'],
        'unallocated_cents':allocation['unallocated_cents']+costs.get('pending_material_cents',0),
        'pending_material_cents':costs.get('pending_material_cents',0),
        'pending_expense_cents':(allocation['amount_cents']-allocation['allocated_cents']),
        'basis':'管理口径，非税务报表：税费与折旧用费用登记的手工估算值计入期间费用，不单独计提；收入、成本、费用均精确到分；缺项未归集时净利润留空，不用估算值凑数。'
    }
    report['statement']=statement
    report['report_context']['basis']=report['basis']
    return report
