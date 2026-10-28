"""Scoped live finished-stock projection for business days without their own closing.
Canonical inventory arithmetic remains shared. Quarantine needs the full selected
return prefix; filtering dates or pages must not cut off prior returns/disposals.
"""
import json,bisect
from collections import defaultdict
from datetime import date,datetime,timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import inventory as inv,resources_costs as rc,order_corrections as corrections
from inventory_query import register
from finance_query import _text

MOVEMENTS=('production_qty','purchased_qty','return_restock_qty','processing_output_qty','processing_input_qty','loss_qty','shipped_qty')
STATES=('unregistered','opening','draft','reserved','negative','locked','registered')

def days_sql(start,end,all_dates):
    params=[];parts=[]
    sources=[('warehouse_plans','business_date','1'),('orders',"json_extract(payload,'$.business_date')",'1'),('processing_batches',"json_extract(payload,'$.business_date')","COALESCE(json_extract(payload,'$.voided'),0)=0"),('finished_goods_records',"json_extract(payload,'$.business_date')","json_extract(payload,'$.kind')='receipt' AND COALESCE(json_extract(payload,'$.voided'),0)=0"),('sales_returns',"json_extract(payload,'$.received_date')","COALESCE(json_extract(payload,'$.voided'),0)=0 AND COALESCE(json_extract(payload,'$.receipt_mode'),'physical')='physical'"),('stock_closings','business_date',"json_extract(payload,'$.state')='reopened'"),('trade_records',"json_extract(payload,'$.business_date')","json_extract(payload,'$.kind')='inventory-check'")]
    for table,field,condition in sources:
        if not all_dates:condition+=' AND '+field+'>=? AND '+field+'<=?';params.extend([start,end])
        parts.append('SELECT '+field+' business_date FROM '+table+' WHERE '+condition)
    condition="COALESCE(json_extract(r.payload,'$.voided'),0)=0 AND COALESCE(json_extract(d.value,'$.voided'),0)=0"
    if not all_dates:condition+=" AND json_extract(d.value,'$.business_date')>=? AND json_extract(d.value,'$.business_date')<=?";params.extend([start,end])
    parts.append("SELECT json_extract(d.value,'$.business_date') business_date FROM sales_returns r,json_each(r.payload,'$.disposals') d WHERE "+condition)
    return 'WITH days AS ('+' UNION '.join(parts)+") SELECT business_date FROM days WHERE business_date IS NOT NULL AND NOT EXISTS(SELECT 1 FROM stock_closings s WHERE s.business_date=+days.business_date AND json_extract(s.payload,'$.state')='closed') ORDER BY business_date",params

def read_days(c,table,field,days,condition='1'):
    return [json.loads(r[0]) for r in c.execute('SELECT payload FROM '+table+' WHERE '+field+' IN (SELECT value FROM json_each(?)) AND '+condition+' ORDER BY rowid',(rc.dump(days),))]

def projections(c,days,products):
    if not days or not products:return []
    orders=read_days(c,'orders',"json_extract(payload,'$.business_date')",days)
    batches=read_days(c,'processing_batches',"json_extract(payload,'$.business_date')",days,"COALESCE(json_extract(payload,'$.voided'),0)=0")
    receipts=read_days(c,'finished_goods_records',"json_extract(payload,'$.business_date')",days,"json_extract(payload,'$.kind')='receipt' AND COALESCE(json_extract(payload,'$.voided'),0)=0")
    plans={r['business_date']:r for r in read_days(c,'warehouse_plans','business_date',days)}
    amendments=read_days(c,'order_corrections',"json_extract(payload,'$.business_date')",days,"json_extract(payload,'$.kind')='shipment'")
    previous_days=[(date.fromisoformat(d)-timedelta(days=1)).isoformat() for d in days]
    previous={r['business_date']:r for r in read_days(c,'stock_closings','business_date',previous_days,"json_extract(payload,'$.state')='closed'")}
    locks=[r[0] for r in c.execute("SELECT business_date FROM stock_closings WHERE business_date>=? AND json_extract(payload,'$.state')='closed' ORDER BY business_date",(days[0],))]
    # All disposals in each selected return remain available to remaining_return.
    ids=[p['id'] for p in products]
    returns=[json.loads(r[0]) for r in c.execute("SELECT payload FROM sales_returns WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 AND json_extract(payload,'$.product_id') IN (SELECT value FROM json_each(?)) AND (json_extract(payload,'$.received_date')<=? OR EXISTS(SELECT 1 FROM json_each(payload,'$.disposals') d WHERE json_extract(d.value,'$.business_date') IN (SELECT value FROM json_each(?)))) ORDER BY rowid",(rc.dump(ids),days[-1],rc.dump(days)))]
    by_day={}
    for table,values in [('orders',orders),('processing',batches),('receipts',receipts),('amendments',amendments)]:
        grouped=defaultdict(list)
        for r in values:grouped[r['business_date']].append(r)
        by_day[table]=grouped
    result=[]
    for day,prior_day in zip(days,previous_days):
        plan=corrections.effective_plan(c,plans.get(day,{}),_amendments=by_day['amendments'][day]);purchased=defaultdict(Decimal);restocked=defaultdict(Decimal)
        for r in by_day['receipts'][day]:
            for line in r['lines']:purchased[line['product_id']]+=Decimal(line['qty'])
        for r in returns:
            for d in r.get('disposals',[]):
                if not d.get('voided') and d['kind']=='restock' and d['business_date']==day:restocked[r['product_id']]+=Decimal(d['stock_qty'])
        sources={'plan':plan,'previous_closing':previous.get(prior_day),'orders':by_day['orders'][day],'returns':[r for r in returns if r.get('receipt_mode','physical')=='physical' and r['received_date']<=day],'processing':by_day['processing'][day],'purchased':purchased,'restocked':restocked,'closing':None}
        snap=inv.stock(c,day,products,_sources=sources);stock_ids={r['product_id'] for r in plan.get('stock',[])};position=bisect.bisect_left(locks,day);locked=locks[position] if position<len(locks) else ''
        for p in snap['products']:
            if p['product_id'] not in stock_ids:
                p['production_qty']=None;p['loss_qty']=None
            result.append({**p,'business_date':day,'plan_saved':bool(plan),'stock_registered':p['product_id'] in stock_ids,'plan_version':plan.get('version'),'allocation_state':snap['allocation_state'],'previous_closing_date':prior_day if previous.get(prior_day) else '', 'opening_source_date':plan.get('opening_source_date',''),'lock_date':locked})
    return result

def history(c,*,start='',end='',all_dates=False,product_id='',status='',search='',page=1,page_size=50):
    start=_text(start,'开始日期',10);end=_text(end,'结束日期',10)
    if all_dates:
        if start or end:raise ValueError('全部日期不能同时指定起止日期')
    else:
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date();start=start or today.replace(day=1).isoformat();end=end or today.isoformat();rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('查询范围最多3652天')
    product_id=_text(product_id,'产品');status=_text(status,'状态');search=_text(search,'搜索')
    if status and status not in STATES:raise ValueError('状态无效')
    try:page=int(page);page_size=int(page_size)
    except (ValueError,TypeError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页须为1至200条')
    sql,args=days_sql(start,end,all_dates);days=[r[0] for r in c.execute(sql,args)]
    products=[dict(r) for r in c.execute('SELECT * FROM products'+(' WHERE id=?' if product_id else '')+' ORDER BY id',([product_id] if product_id else []))]
    values=projections(c,days,products);register(c);c.create_function('open_stock_negative',1,lambda a:int(a not in (None,'') and Decimal(str(a))<0),deterministic=True)
    fields=['business_date','product_id','product_name','unit','plan_saved','stock_registered','plan_version','allocation_state','previous_closing_date','opening_source_date','lock_date',*MOVEMENTS,'opening_qty','book_qty','free_qty','quarantine_qty','quarantine_kg','counted_qty','ordered_qty','allocated_qty','reserved_qty','proposed_qty','shortage_qty','adjustment_qty','returned_qty','returned_kg','supply_qty','variance_reason']
    sql='SELECT '+','.join("json_extract(value,'$.%s') %s"%(k,k) for k in fields)+' FROM json_each(?)';args=[rc.dump(values)]
    filters=[];states={'unregistered':'stock_registered=0','opening':"opening_qty IS NULL OR opening_qty=''",'draft':"allocation_state='draft'",'reserved':"history_positive(reserved_qty)=1",'negative':'open_stock_negative(book_qty)=1 OR open_stock_negative(free_qty)=1','locked':"lock_date!=''",'registered':"stock_registered=1"}
    if status:filters.append('('+states[status]+')')
    if search:filters.append("instr(lower(product_name||' '||product_id||' '||business_date||' '||COALESCE(variance_reason,'')),lower(?))>0");args.append(search)
    sql='SELECT * FROM ('+sql+')'+(' WHERE '+' AND '.join(filters) if filters else '')
    total,day_count,unknown,unregistered=c.execute("SELECT COUNT(*),COUNT(DISTINCT business_date),COALESCE(SUM(book_qty IS NULL),0),COALESCE(SUM(stock_registered=0),0) FROM ("+sql+')',args).fetchone();pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    cursor=c.execute('SELECT * FROM ('+sql+') ORDER BY business_date DESC,product_id LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size]);names=[d[0] for d in cursor.description];rows=[dict(zip(names,r)) for r in cursor]
    totals=','.join('CASE WHEN COUNT('+k+')=0 THEN NULL ELSE history_decimal_sum('+k+') END '+k+',SUM('+k+' IS NULL) '+k+'_missing' for k in MOVEMENTS)
    cursor=c.execute("SELECT product_id,product_name,unit,COUNT(*) count,SUM(stock_registered=0) unregistered_count,"+totals+' FROM ('+sql+') GROUP BY product_id,product_name,unit ORDER BY product_id,unit',args);names=[d[0] for d in cursor.description];summary=[dict(zip(names,r)) for r in cursor]
    return {'start':start,'end':end,'all':all_dates,'total':total,'days':day_count,'unknown_rows':unknown,'unregistered_rows':unregistered,'page':page,'pages':pages,'page_size':page_size,'rows':rows,'summary':summary,'basis':'按当前已登记来源重算，仅列有库存相关业务且本日未独立日结的日期，不是保存时快照。名称及单位取当前档案；期初未确认保留待确认，未登记生产与报损不按真实0展示。汇总只累计已登记发生量，不累计多日库存或隔离余额，不代表当天业务已完整。历史退货剩余量保留此前全部有效处置，前一日实盘只用于建议开账；已保存计划仍采用原开账。后续日结已锁定的日期只读，须在原作业页核验，不能据此认定可直接日结。'}
