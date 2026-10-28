"""Read-only confirmed/reopened finished-stock snapshots, with shipment restatement.
Balances are never summed across days; original physical counts remain immutable.
"""
import json
from datetime import date,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import resources_costs as rc
from finance_query import _text
from inventory_query import register

MOVEMENTS=('production_qty','purchased_qty','return_restock_qty','processing_output_qty','processing_input_qty','loss_qty','shipped_qty','variance_qty')
BALANCES=('opening_qty','book_qty','counted_qty')
FIELDS=BALANCES+MOVEMENTS

def number(value):return None if value in (None,'') else Decimal(str(value))
def calculate(a,b,sign=1):return None if number(a) is None else rc.ds(number(a)+sign*(number(b) or Decimal(0)))

def source_sql(start,end,all_dates,product_id='',status='',search=''):
    where=[];args=[]
    if not all_dates:where+=['s.business_date>=?','s.business_date<=?'];args += [start,end]
    if product_id:where.append("json_extract(p.value,'$.product_id')=?");args.append(product_id)
    base="SELECT s.business_date,s.payload record,p.value product FROM stock_closings s,json_each(s.payload,'$.products') p WHERE "+(' AND '.join(where) or '1')
    fields=','.join("NULLIF(json_extract(product,'$.%s'),'') %s"%(k,k) for k in FIELDS if k not in ('book_qty','shipped_qty','variance_qty'))
    sql="""WITH base AS ("""+base+"""), changes AS (
      SELECT json_extract(a.payload,'$.stock_anchor_date') business_date,json_extract(l.value,'$.product_id') product_id,
      history_decimal_sum(json_extract(l.value,'$.delta_qty')) delta
      FROM order_corrections a,json_each(a.payload,'$.quantity_changes') l
      WHERE json_extract(a.payload,'$.kind')='shipment' AND EXISTS(SELECT 1 FROM base b WHERE b.business_date=json_extract(a.payload,'$.stock_anchor_date'))
      GROUP BY json_extract(a.payload,'$.stock_anchor_date'),json_extract(l.value,'$.product_id')
    ), projection AS (SELECT b.business_date,json_extract(record,'$.state') state,
      json_extract(product,'$.product_id') product_id,COALESCE(json_extract(product,'$.product_name'),json_extract(product,'$.product_id')) product_name,
      COALESCE(json_extract(product,'$.unit'),'未列') unit,json_extract(record,'$.version') version,
      json_extract(record,'$.closed_at') closed_at,json_extract(record,'$.role') role,json_extract(record,'$.reopen_reason') reopen_reason,
      json_extract(product,'$.variance_reason') variance_reason,"""+fields+""",
      NULLIF(json_extract(product,'$.book_qty'),'') original_book_qty,
      NULLIF(json_extract(product,'$.variance_qty'),'') original_variance_qty,
      CASE WHEN json_extract(record,'$.state')='closed' THEN COALESCE(d.delta,'0') ELSE '0' END correction_qty,
      EXISTS(SELECT 1 FROM order_corrections a WHERE json_extract(a.payload,'$.kind')='shipment' AND json_extract(a.payload,'$.stock_anchor_date')=+b.business_date) AND json_extract(record,'$.state')='closed' corrected,
      CASE WHEN json_extract(record,'$.state')='closed' THEN stock_history_sub(NULLIF(json_extract(product,'$.book_qty'),''),d.delta) ELSE NULLIF(json_extract(product,'$.book_qty'),'') END book_qty,
      CASE WHEN json_extract(record,'$.state')='closed' THEN stock_history_add(NULLIF(json_extract(product,'$.shipped_qty'),''),d.delta) ELSE NULLIF(json_extract(product,'$.shipped_qty'),'') END shipped_qty,
      CASE WHEN json_extract(record,'$.state')='closed' AND d.delta IS NOT NULL AND d.delta!='0' THEN stock_history_sub(NULLIF(json_extract(product,'$.counted_qty'),''),stock_history_sub(NULLIF(json_extract(product,'$.book_qty'),''),d.delta)) ELSE NULLIF(json_extract(product,'$.variance_qty'),'') END variance_qty
      FROM base b LEFT JOIN changes d ON d.business_date=b.business_date AND d.product_id=json_extract(product,'$.product_id'))
      SELECT * FROM projection"""
    filters=[]
    states={'closed':"state='closed'",'reopened':"state='reopened'",'variance':"state='closed' AND variance_qty IS NOT NULL AND stock_history_nonzero(variance_qty)",'corrected':'corrected=1'}
    if status:filters.append(states[status])
    if search:
        filters.append("instr(lower(business_date||' '||product_id||' '||product_name||' '||COALESCE(role,'')||' '||COALESCE(variance_reason,'')||' '||COALESCE(reopen_reason,'')),lower(?))>0");args.append(search)
    if filters:sql+=' WHERE '+' AND '.join('('+f+')' for f in filters)
    return sql,args

def history(c,*,start='',end='',all_dates=False,product_id='',status='',search='',page=1,page_size=50):
    start=_text(start,'开始日期',10);end=_text(end,'结束日期',10)
    if all_dates:
        if start or end:raise ValueError('全部日期不能同时指定起止日期')
    else:
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date();start=start or today.replace(day=1).isoformat();end=end or today.isoformat();rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('查询范围最多3652天')
    product_id=_text(product_id,'产品');status=_text(status,'状态');search=_text(search,'搜索')
    if status not in ('','closed','reopened','variance','corrected'):raise ValueError('状态无效')
    try:page=int(page);page_size=int(page_size)
    except (ValueError,TypeError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页须为1至200条')
    register(c);c.create_function('stock_history_add',2,calculate,deterministic=True);c.create_function('stock_history_sub',2,lambda a,b:calculate(a,b,-1),deterministic=True);c.create_function('stock_history_nonzero',1,lambda a:int(bool(number(a))),deterministic=True)
    sql,args=source_sql(start,end,all_dates,product_id,status,search)
    count=c.execute("SELECT COUNT(*),COUNT(DISTINCT business_date),COALESCE(SUM(state='closed'),0),COALESCE(SUM(state='reopened'),0) FROM ("+sql+')',args).fetchone()
    pages=max(1,(count[0]+page_size-1)//page_size);page=min(page,pages)
    cursor=c.execute('SELECT * FROM ('+sql+') ORDER BY business_date DESC,product_id,unit LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size]);names=[d[0] for d in cursor.description];rows=[dict(zip(names,r)) for r in cursor]
    totals=','.join("history_decimal_sum(%s) %s,SUM(%s IS NULL) %s_missing"%(k,k,k,k) for k in MOVEMENTS)
    cursor=c.execute('SELECT product_id,product_name,unit,COUNT(*) count,'+totals+" FROM ("+sql+") WHERE state='closed' GROUP BY product_id,product_name,unit ORDER BY product_id,unit,product_name",args);names=[d[0] for d in cursor.description];quantities=[dict(zip(names,r)) for r in cursor]
    return {'start':start,'end':end,'all':all_dates,'total':count[0],'days':count[1],'closed_rows':count[2],'reopened_rows':count[3],'page':page,'pages':pages,'page_size':page_size,'rows':rows,'quantities':quantities,'basis':'每行是一个产品的一日日结记录；实盘及翌日结转保持原确认值，实发更正仅重述账面、实发与差异。撤销记录仅供追溯，不计发生量汇总。汇总按产品和原单位分别统计已确认日结发生量，不累计期初、账面和实盘余额；缺失数量保持待补。未日结日期不在此表。'}
