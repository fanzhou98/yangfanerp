"""Decision report contracts. All business aggregation uses cents / Decimal here.
Renderers may scale geometry and format values, but must not calculate balances.
"""
import calendar
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import resources_costs as rc
import sales_query


def context(title,start,end,source,basis):
    rc.day(start);rc.day(end)
    return {'version':1,'title':title,'start':start,'end':end,'generated_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'source':source,'basis':basis}


def sales(c,start,end,region='',*,all_dates=False):
    start,end=sales_query.resolve(c,start,end,all_dates)
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    customers={r['id']:dict(r) for r in c.execute('SELECT * FROM customers')}
    all_orders={r['id']:r for r in sales_query.orders(c,start,end,region=region)}
    belongs=lambda cid:not region or (customers.get(cid,{}).get('region') or '未设置地区')==region
    orders=list(all_orders.values())
    reviewed=[o for o in orders if o.get('state')=='reviewed'];returns=[r for r in rc.rows(c,'sales_returns') if not r.get('voided') and belongs(r['customer_id'])]
    posted=lambda r:r.get('finance',{}).get('state')=='posted' if r.get('finance') else False
    received=[r for r in returns if start<=r['received_date']<=end]
    # Receipt-date and original-order attribution intentionally remain separate.
    attributed=[r for r in returns if r.get('order_id') in {o['id'] for o in reviewed}]
    gross=sum(o.get('total_cents',0) for o in reviewed)
    returned=sum(r['finance']['amount_cents'] for r in received if posted(r))
    original_returns=sum(r['finance']['amount_cents'] for r in attributed if posted(r))
    adjustments=sum(o.get('discount_cents',0)+o.get('rounding_cents',0) for o in reviewed)
    trend=[]
    for offset in range((last-first).days+1):
        day=(first+timedelta(days=offset)).isoformat();day_orders=[o for o in orders if o['business_date']==day];done=[o for o in day_orders if o.get('state')=='reviewed']
        trend.append({'label':day,'value':sum(o.get('total_cents',0) for o in done) if done else None,'state':'已复核' if done else '待复核' if day_orders else '无单据','n':len(done),'pending':len(day_orders)-len(done)})
    # Long windows aggregate to real calendar months; no interpolation of missing days.
    grain='日'
    if len(trend)>92:
        grouped={}
        for point in trend:
            row=grouped.setdefault(point['label'][:7],{'label':point['label'][:7],'value':None,'n':0,'missing_days':0})
            if point['value'] is None:row['missing_days']+=1
            else:row['value']=(row['value'] or 0)+point['value'];row['n']+=point['n']
        trend=list(grouped.values());grain='月（仅已复核日，缺项见表）'
    ranks={}
    for o in reviewed:
        cid=o['customer_id'];customer=customers.get(cid,{})
        row=ranks.setdefault(cid,{'key':cid,'label':o.get('customer_name') or customer.get('name',cid),'sub':' / '.join(filter(None,[customer.get('region'),customer.get('route')])),'value':0,'orders':0,'products':{}})
        row['value']+=o.get('total_cents',0);row['orders']+=1
        for line in o['lines']:
            key=(line['product_id'],line['unit']);product=row['products'].setdefault(key,{'product_name':line['product_name'],'unit':line['unit'],'qty':Decimal(0),'sales_cents':0})
            product['qty']+=Decimal(line.get('actual_qty') or '0');product['sales_cents']+=line.get('amount_cents',0)
    rank=[]
    for row in sorted(ranks.values(),key=lambda r:(-r['value'],r['key'])):
        rank.append({**row,'share_pct':rc.ds(Decimal(row['value'])*100/gross) if gross else '0','products':[{**p,'qty':rc.ds(p['qty'])} for p in row['products'].values()]})
    product={}
    for o in reviewed:
        for l in o['lines']:
            key=(l['product_id'],l['unit']);r=product.setdefault(key,{'product_name':l['product_name'],'unit':l['unit'],'qty':Decimal(0),'sales_cents':0})
            r['qty']+=Decimal(l.get('actual_qty') or '0');r['sales_cents']+=l.get('amount_cents',0)
    gaps=[]
    pending=len(orders)-len(reviewed)
    if pending:gaps.append({'field':str(pending)+' 笔发货单尚未复核，金额未计入','owner':'会计 / 出纳','target':'settlements'})
    unconfirmed=sum(not posted(r) for r in received)
    if unconfirmed:gaps.append({'field':str(unconfirmed)+' 笔退货待核定 / 复核，净额尚不完整','owner':'会计 / 出纳','target':'returns'})
    for r in received:
        oid=r.get('order_id')
        if oid and oid not in all_orders:
            row=c.execute('SELECT payload FROM orders WHERE id=?',(oid,)).fetchone()
            if row:all_orders[oid]=json.loads(row[0])
    return {**context('发货与退货',start,end,'订单 / 客户退货台账','发货口径，不代表门店动销。净额按原单归属；收货日退货另列，不能与本期发货直接混扣。折让单列；应收余额为当前状态。'),
        'gross_cents':gross if reviewed else None,'received_return_cents':returned if received else None,'original_return_cents':original_returns if reviewed else None,
        'adjustment_cents':adjustments,'reductions_cents':original_returns+adjustments if reviewed else None,'net_cents':gross-original_returns-adjustments if reviewed else None,'pending_orders':pending,'reviewed_orders':len(reviewed),'unconfirmed_returns':unconfirmed,
        'trend_summary':{'reviewed_orders':len(reviewed),'pending_orders':pending,'missing_days':sum(p.get('state')!='已复核' for p in trend) if grain=='日' else sum(p['missing_days'] for p in trend)},'products':[{**r,'qty':rc.ds(r['qty'])} for r in sorted(product.values(),key=lambda r:(-r['sales_cents'],r['product_name']))],
        'returns':[{'id':r['id'],'received_date':r['received_date'],'original_date':all_orders.get(r.get('order_id'),{}).get('business_date'), 'customer_name':customers.get(r['customer_id'],{}).get('name',r['customer_id']),'product_name':r.get('product_name',''),'qty':r.get('qty'),'unit':r.get('unit'),'amount_cents':r['finance']['amount_cents'] if posted(r) else None,'state':'已复核' if posted(r) else '待核定 / 复核'} for r in sorted(received,key=lambda r:(r['received_date'],r['id']))],
        'charts':[{'kind':'trend','title':'已复核发货金额如何变化？','unit':'元','type':'cents','grain':grain,'points':trend,'note':'少于 3 天有已复核数据时只显示数值条，不画趋势；无单据 / 仅待复核日期不当作 0。按公历统计，未作农历节日对齐。'},
                  {'kind':'rank','drilldown':'customer','title':'哪些客户贡献最多已复核发货金额？','unit':'元','type':'cents','points':rank[:10],'all_points':rank,'note':'按金额降序；主图前10名，完整数据见表。未建立渠道字段，不按客户名称猜测渠道。'}],'gaps':gaps}


def production_month(c,month):
    rc.day(month+'-01');plans=[p for p in rc.rows(c,'warehouse_plans') if p['business_date'].startswith(month)]
    batches=[b for b in rc.rows(c,'processing_batches') if not b.get('voided') and b['business_date'].startswith(month)]
    orders=[o for o in rc.rows(c,'orders') if o['business_date'].startswith(month)]
    end=month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:7]))[1]);_,entries=rc.material_ledger(c,end)
    beans=sum((Decimal(e['qty'])*(1 if e['kind']=='consume' else -1) for e in entries if e['material_id']=='RM-SOY' and e['business_date'].startswith(month) and e['kind'] in ('consume','return')),Decimal(0))
    result=[]
    for p in c.execute('SELECT * FROM products'):
        stock=[r for plan in plans for r in plan.get('stock',[]) if r['product_id']==p['id']]
        normal=sum((Decimal(r.get('produced_qty') or '0') for r in stock),Decimal(0))
        incoming=sum((Decimal(r.get('qty') or '0') for b in batches for r in b.get('outputs',[]) if r['product_id']==p['id']),Decimal(0))
        used=sum((Decimal(b.get('input_kg') or '0') for b in batches if b.get('product_id')==p['id']),Decimal(0))
        sent=sum((Decimal(l.get('actual_qty') or '0') for o in orders for l in o['lines'] if l['product_id']==p['id']),Decimal(0))
        loss=sum((Decimal(r.get('loss_qty') or '0') for r in stock),Decimal(0))
        result.append({'product_name':p['name'],'unit':p['unit'],'normal_qty':rc.ds(normal) if plans else None,'processing_qty':rc.ds(incoming) if batches else None,'input_qty':rc.ds(used) if batches else None,'shipped_qty':rc.ds(sent) if orders else None,'loss_qty':rc.ds(loss) if plans else None})
    return {**context('生产月报',month+'-01',end,'库存生产登记 / 转加工批次 / 实发单 / 材料台账','普通生产按库管登记，含转加工时分列。筐、包、袋按产品单位分别查看，不跨单位求和；无登记留待补。上豆为实际领用减退料。'), 'rows':result,'bean_kg':rc.ds(beans) if any(e['business_date'].startswith(month) and e['material_id']=='RM-SOY' and e['kind']=='consume' for e in entries) else None,'registered_days':len({p['business_date'] for p in plans}),'open_days':len({p['business_date'] for p in plans}-{r['business_date'] for r in rc.rows(c,'stock_closings') if r.get('state')=='closed'})}


def production_day(c,day):
    """Charts for the production daily page; no sales, cost or cash data."""
    import production_management as fm
    import owner_analysis
    rc.day(day)
    current=fm.daily_report(c,day)
    previous_dates=sorted({r['business_date'] for t in ('factory_daily','warehouse_plans') for r in rc.rows(c,t) if r['business_date']<day},reverse=True)
    previous_day=previous_dates[0] if previous_dates else None
    previous=fm.daily_report(c,previous_day) if previous_day else None
    products=[]
    for p in current['products']:
        prev=next((r for r in (previous or {}).get('products',[]) if r['product_id']==p['product_id']),{})
        a,b=p.get('settlement_yield'),prev.get('settlement_yield')
        comparable=a is not None and b is not None and Decimal(b)>0 and not p.get('settlement_pending') and not prev.get('settlement_pending') and p.get('main_material')==prev.get('main_material') and current.get('production_config')==(previous or {}).get('production_config') and all(current['settings'].get(k)==(previous or {}).get('settings',{}).get(k) for k in ('large_slurry_kg','small_slurry_kg','skin_slurry_kg','large_slurry_crates','small_slurry_crates','skin_slurry_crates'))
        delta=(Decimal(a)/Decimal(b)-1)*100 if comparable else None
        products.append({**p,'previous_yield':b,'change_pct':rc.ds(delta) if delta is not None else None,'change_alert':delta is not None and abs(delta)>Decimal(current['settings']['evidence_alert_pct'])})
    yields=yield_comparison(products,current['settings']['evidence_alert_pct'])
    charts=[];gaps=[]
    if yields['comparable_count']:charts.append(yields)
    else:gaps.append({'field':'无上次同口径生产记录，无法比较出品率','owner':'厂长','target':'production-report'})
    return {**context('生产日报图表',day,day,'生产登记 / 材料领用 / 实发与盘库','只展示生产与质量；不含成本、销售、应收或利润。出品率采用已复核结算公斤与同日归属干豆；跨日库存须另行核对。'),
            'business_date':day,'previous_day':previous_day,
            'charts':charts,'gaps':gaps,
            'comparable_products':sum(1 for p in products if p.get('previous_yield') is not None and p.get('settlement_yield') is not None)}


def management_month(c,month):
    import finished_goods
    import trade
    sale=sales(c,month+'-01',month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:7]))[1]))
    _,entries=rc.material_ledger(c,sale['end'])
    material=sum(e['cost_cents']*(-1 if e['kind']=='return' else 1) for e in entries if e['business_date'].startswith(month) and e['kind'] in ('consume','return','loss'))
    expenses=rc.period_expenses(c,month)
    overhead=sum(e['amount_cents'] for e in expenses if e['category']!='transport')
    transport_basis=__import__('transport_closure').cost_basis(c,month);transport=transport_basis['amount_cents']
    goods=finished_goods.stock_cost(c,sale['start'],sale['end']);purchased=sum(r['sales_cost_cents'] for r in goods)
    byproduct=sum(r['amount_cents'] for r in rc.rows(c,'byproduct_sales') if not r.get('voided') and r['business_date'].startswith(month))
    cost=material+overhead+transport+purchased
    gaps=list(sale['gaps'])+transport_basis['gaps']
    if any(e.get('is_estimate') for e in expenses):gaps.append({'field':'本月成本含暂估，实际账单到后仍需核销补差','owner':'会计','target':'expenses'})
    if not any(p['month']==month and p['state']=='closed' for p in rc.rows(c,'resource_periods')):gaps.append({'field':'本月成本尚未月结，费用可能未录全','owner':'会计','target':'expenses'})
    categories={e['category'] for e in expenses}
    missing_categories=[label for key,label,*_ in rc.CATEGORIES if key in ('wages-production','wages-management','electricity','gas','water','rent','depreciation') and key not in categories]
    if missing_categories:gaps.append({'field':'费用未登记：'+'、'.join(missing_categories)+'，不能视为零成本','owner':'会计','target':'expenses'})
    gaps.extend([{'field':'成品存货成本结转与税费未完整归集，不能认定净利润','owner':'会计','target':'production'}, {'field':'无保质期及门店销售回传，不提供临期金额、动销或售罄率','owner':'基础资料 / 销售','target':'products'}])
    if any(Decimal(r.get('unvalued_qty') or '0') for r in goods):gaps.append({'field':'外购成品期初成本待补','owner':'会计','target':'payables'})
    return {**sale,'title':'月度经营判断','cost_cents':cost,'byproduct_cents':byproduct,'difference_cents':sale['net_cents']+byproduct-cost if sale['net_cents'] is not None else None,'gaps':gaps,'bridge':waterfall([('原单归属净额','净额',sale['net_cents']),('豆渣收入','豆渣',byproduct),('材料净领用','材料',-material),('外购实发成本','外购',-purchased),('配送趟次费用','运费',-transport),('非运输期间费用','费用',-overhead)],'当月已登记经营测算；首项已扣原单归属退货与折让。'+(('成本依据尚未齐全，净利润按已登记数据计算、可能偏高，补齐后需重看。') if gaps else '毛利润＝收入－材料与外购成本；净利润＝毛利润－配送趟次费用－非运输期间费用，付款不再重复计成本。'),subtotals={4:('毛利润','毛利')}),'components':[{'label':n,'value':v} for n,v in [('净材料领用',material),('外购实发成本',purchased),('实际配送趟次',transport),('非运输期间费用',overhead)]], 'cost_basis':'材料按领用＋报损－退料计价；外购按实发成本；期间费用按所属月；运输按实际趟次，月结运费凭据不重复计入。收入按原单归属净额，仍是经营测算。'}


def soy_stock(c,day):
    import owner_analysis
    stock,_,warehouses=rc.material_ledger(c,day,warehouse_details=True)
    stats=owner_analysis.soy_composition([w for w in warehouses if w['id']=='RM-SOY'])
    return {**context('黄豆库存与批次质量',day,day,'材料批次台账 / 入库检测','按所选业务日剩余库存；蛋白、水分只按已检测数量加权，未知不补零。品种、产地与播种属性独立。'), 'warehouses':[{k:w[k] for k in ('warehouse_id','warehouse_name','qty','lots')} for w in warehouses if w['id']=='RM-SOY'], 'stats':stats, 'charts':[inventory_composition(stats)], 'other_items':[{k:r[k] for k in ('id','name','unit','qty','reorder_qty','low_stock')} for r in stock if r['id']!='RM-SOY']}


def expense_charts(categories):
    points=sorted((r for r in categories if r.get('value') is not None),key=lambda r:r['value'],reverse=True)
    if len(points)<2 or points[0]['value']==points[-1]['value']:return []
    return [{'kind':'rank','title':'哪项期间费用需要重点核对？','type':'cents','unit':'元','points':points[:8],'note':'按金额前8项；其余见分类汇总。未登记费用不视为零成本。'}]

def expense_summary(c,month=''):
    if month:rc.day(month+'-01')
    projected={e['id']:e for e in rc.expense_projection(c) if not e.get('voided')}
    entries=[{**projected.get(e['id'],{}),**e} for e in rc.period_expenses(c,month)] if month else list(projected.values())
    categories=[]
    for category in __import__('cost_allocation').categories(c):
        key,label=category['id'],category['name']
        subset=[e for e in entries if e['category']==key]
        if not subset:continue
        categories.append({'label':label,'value':sum(e['amount_cents'] for e in subset)})
    charts=expense_charts(categories)
    suppliers={}
    for e in entries:
        if not e['payment_required']:continue
        sid=e.get('supplier_id') or '';key=('expense-party:'+e['counterparty_id']) if e.get('counterparty_id') else sid or 'unlinked:'+e.get('partner','')
        row=suppliers.setdefault(key,{'supplier_id':sid,'counterparty_id':e.get('counterparty_id',''),'counterparty_kind':e.get('counterparty_kind',''),'name':e.get('partner') or '费用对象待补','recognized_cents':0,'pending_cents':0,'paid_cents':0,'n':0})
        row['n']+=1;row['paid_cents']+=e['paid_cents']
        row['recognized_cents' if e['payment_state'] in ('approved','partial','paid') else 'pending_cents']+=e['outstanding_cents']
    return {
        **context('间接成本月报' if month else '费用应付来源',month+'-01' if month else min((e['business_date'] for e in entries),default=date.today().isoformat()),month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:7]))[1]) if month else date.today().isoformat(),'费用登记 / 核对 / 实付台账','按费用所属月认列，付款反映本次读取时状态。'),'month':month,'estimated_cents':sum(e['amount_cents'] for e in entries if e.get('is_estimate')),'total_cents':sum(e['amount_cents'] for e in entries),'n':len(entries),
        'wages_cents':sum(e['amount_cents'] for e in entries if e['category'].startswith('wages-')),'shared_cents':sum(e['amount_cents'] for e in entries if not e.get('product_id')),
        'charts':charts,'categories':sorted(categories,key=lambda r:-(r['value'] or 0)), 'suppliers':sorted(suppliers.values(),key=lambda r:(-r['recognized_cents'],-r['pending_cents'],r['name'])),
        'basis':'费用按覆盖月份或抄表区间归属，含尚未到单的暂估；暂估与实际到单覆盖部分不重复，金额合计精确到分；已核对费用余额纳入已确认应付，待核对和退回金额单列。付款使用实际资金账户，不重复计成本；工资从工资系统发放，折旧不产生付款。采购货款及已进入存货成本的运卸不得再次登记为间接成本。'}


def waterfall(stages,note,total_label='净利润',total_short='净利',subtotals=None):
    """Cumulative cents are business data, calculated once here, never in SVG.

    subtotals maps the number of consumed stages to a subtotal (label, short) drawn from zero,
    so one chart can carry 毛利润 and 净利润 without recomputing anything in SVG.
    """
    subtotals=subtotals or {}
    title='从收入到'+total_label+'是怎么算的？'
    if any(value is None for _,_,value in stages):return {'kind':'waterfall','title':title,'type':'cents','unit':'元','points':[],'note':'收入未复核，不能形成'+total_label+'图。'+note}
    running=0;points=[]
    for index,(label,short,value) in enumerate(stages,1):
        value=int(value);start=running;running+=value
        points.append({'label':label,'short':short,'value':value,'start':start,'end':running})
        if index in subtotals:
            sub_label,sub_short=subtotals[index]
            points.append({'label':sub_label,'short':sub_short,'value':running,'start':0,'end':running,'total':True,'subtotal':True})
    points.append({'label':total_label,'short':total_short,'value':running,'start':0,'end':running,'total':True})
    return {'kind':'waterfall','title':title,'type':'cents','unit':'元','points':points,'note':note}


def inventory_composition(warehouses):
    names=[('spring','春豆','#5d9d79'),('summer','复播豆','#a9bf91'),('tianjin','天津豆','#c29c6c'),('other','其他品种','#90aeb7'),('unknown','品种待补','#cbd1cb')]
    points=[]
    for warehouse in warehouses:
        total=Decimal(warehouse['qty']);values={key:Decimal(0) for key,_,_ in names}
        for r in warehouse.get('varieties',[]):
            key={'春豆':'spring','复播豆':'summer','天津豆':'tianjin','品种待补':'unknown'}.get(r['name'],'other');values[key]+=Decimal(r['qty'])
        values['unknown']+=max(Decimal(0),total-sum(values.values()))
        points.append({'label':warehouse['warehouse_name'],'total':rc.ds(total),'values':{k:rc.ds(v) for k,v in values.items()},'percentages':{k:rc.ds(v/total*100) if total else '0' for k,v in values.items()}})
    known=sum((Decimal(row['values'][key]) for row in points for key in row['values'] if key!='unknown'),Decimal(0))
    if not known:
        return {'kind':'composition','title':'各库房的大豆品种是否匹配生产需要？','unit':'公斤','points':[],
                'empty_title':'品种未登记，暂不能构成','empty_hint':'请在生产上豆或采购验收补录采购品种；未登记不从产地或客户推断。',
                'parts':[{'key':key,'label':label,'color':color,'light':key!='spring'} for key,label,color in names],
                'note':'品种待补占全部库存；不生成100%灰条，避免看起来像已分类。'}
    return {'kind':'composition','title':'各库房的大豆品种是否匹配生产需要？','unit':'公斤','points':points,'parts':[{'key':key,'label':label,'color':color,'light':key!='spring'} for key,label,color in names],'note':'按实际采购品种及剩余公斤构成；天津豆独立分类，未登记不从产地推断。'}


def yield_comparison(products,threshold):
    points=[{'label':p['product_name'],'now':p.get('settlement_yield') if 'settlement_yield' in p else p.get('yield_kg_per_kg') if not p.get('missing_data') else None,'prev':p.get('previous_yield') if p.get('change_pct') is not None else None,'change_pct':p.get('change_pct'),'alert':p.get('change_alert',False)} for p in products if p.get('system')]
    comparable=sum(1 for p in points if p['now'] is not None and p['prev'] is not None)
    return {'kind':'dot','title':'哪些产品的结算口径出品率发生变化？','unit':'kg/kg','threshold':threshold,'points':points,'comparable_count':comparable,
            'empty_title':'本期无同期可比出品率','empty_hint':'需要上一次同口径生产记录；当前出品率与缺项见下方产品表，不画空轨道。',
            'note':'已复核结算公斤 ÷ 同日归属干豆公斤，包含保水和运输的综合结果；不是出厂物理出品率。空心点上次、实心点本次。'}
