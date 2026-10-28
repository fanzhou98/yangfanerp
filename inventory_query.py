"""Read-only return/processing history; global stock and costing retain full ledgers."""
import json
from datetime import date,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import resources_costs as rc
from finance_query import _text

RETURN_STATES=('active','account','review','posted','physical','processing','credit','closed','voided')
PROCESS_STATES=('active','pending','completed','voided')
class DecimalSum:
    def __init__(self):self.value=Decimal(0)
    def step(self,v):self.value+=Decimal(str(v or 0))
    def finalize(self):return rc.ds(self.value)

def register(c):
    c.create_aggregate('history_decimal_sum',1,DecimalSum)
    c.create_function('history_sub',2,lambda a,b:rc.ds(Decimal(str(a or 0))-Decimal(str(b or 0))),deterministic=True)
    c.create_function('history_positive',1,lambda a:int(Decimal(str(a or 0))>0),deterministic=True)


def query_sql(kind,start,end,all_dates,product_id='',customer_id='',status='',search='',origin=''):
    table,field=('sales_returns','received_date') if kind=='returns' else ('processing_batches','business_date')
    when="json_extract(t.payload,'$."+field+"')";where=[];params=[]
    if not all_dates:where.extend([when+'>=?',when+'<=?']);params.extend([start,end])
    if product_id:
        term="json_extract(t.payload,'$.product_id')=?";params.append(product_id)
        if kind=='processing':term="("+term+" OR EXISTS(SELECT 1 FROM json_each(t.payload,'$.outputs') o WHERE json_extract(o.value,'$.product_id')=?))";params.append(product_id)
        where.append(term)
    if customer_id:where.append("json_extract(t.payload,'$.customer_id')=?");params.append(customer_id)
    if origin:where.append("COALESCE(json_extract(t.payload,'$.origin'),'internal')=?");params.append(origin)
    if search:
        where.append("(instr(lower(t.id||' '||COALESCE(json_extract(t.payload,'$.customer_name'),'')||' '||COALESCE(json_extract(t.payload,'$.product_name'),'')||' '||COALESCE(json_extract(t.payload,'$.product_id'),'')||' '||COALESCE(json_extract(t.payload,'$.order_id'),'')||' '||COALESCE(json_extract(t.payload,'$.source_return_id'),'')||' '||COALESCE(json_extract(t.payload,'$.source_note'),'')||' '||COALESCE(json_extract(t.payload,'$.reason'),'')||' '||COALESCE(json_extract(t.payload,'$.handler'),'')||' '||COALESCE(json_extract(t.payload,'$.note'),'')||' '||COALESCE((SELECT name FROM products WHERE id=json_extract(t.payload,'$.product_id')),'')),lower(?))>0 OR EXISTS(SELECT 1 FROM json_each(t.payload,'$.outputs') o WHERE instr(lower(COALESCE(json_extract(o.value,'$.product_name'),'')),lower(?))>0))")
        params.extend([search,search])
    base=f"SELECT t.id,t.payload,{when} business_date,COALESCE(json_extract(t.payload,'$.voided'),0) voided FROM {table} t WHERE {' AND '.join(where) or '1'}"
    if kind=='returns':
        sql="""WITH base AS ("""+base+"""),calc AS (SELECT *,
          CASE WHEN json_extract(payload,'$.receipt_mode')='merchant_disposed' THEN '0' ELSE history_sub(json_extract(payload,'$.qty'),(SELECT history_decimal_sum(json_extract(d.value,'$.qty')) FROM json_each(base.payload,'$.disposals') d WHERE COALESCE(json_extract(d.value,'$.voided'),0)=0)) END left_qty,
          CASE WHEN json_extract(payload,'$.receipt_mode')='merchant_disposed' THEN '0' ELSE history_sub(json_extract(payload,'$.net_kg'),(SELECT history_decimal_sum(json_extract(d.value,'$.net_kg')) FROM json_each(base.payload,'$.disposals') d WHERE COALESCE(json_extract(d.value,'$.voided'),0)=0)) END left_kg,
          EXISTS(SELECT 1 FROM json_each(base.payload,'$.disposals') d WHERE COALESCE(json_extract(d.value,'$.voided'),0)=0 AND json_extract(d.value,'$.kind')='reprocess' AND COALESCE(json_extract(d.value,'$.processing_completed'),0)=0) pending_process,
          CASE WHEN json_extract(payload,'$.finance.state')='posted' THEN COALESCE(json_extract(payload,'$.finance.amount_cents'),0)-COALESCE((SELECT SUM(json_extract(a.value,'$.amount_cents')) FROM json_each(base.payload,'$.finance.allocations') a),0)-COALESCE((SELECT SUM(json_extract(a.value,'$.amount_cents')) FROM json_each(base.payload,'$.finance.refunds') a),0) ELSE 0 END wallet_cents
          FROM base) SELECT * FROM calc"""
        states={'active':'voided=0','voided':'voided!=0','account':"voided=0 AND json_type(payload,'$.finance') IS NULL OR voided=0 AND json_type(payload,'$.finance')='null'",'review':"voided=0 AND json_extract(payload,'$.finance.state')='pending_review'",'posted':"voided=0 AND json_extract(payload,'$.finance.state')='posted'",'physical':'voided=0 AND (history_positive(left_qty) OR history_positive(left_kg))','processing':'voided=0 AND pending_process=1','credit':"voided=0 AND json_extract(payload,'$.finance.state')='posted' AND wallet_cents>0",'closed':"voided=0 AND NOT history_positive(left_qty) AND NOT history_positive(left_kg) AND pending_process=0 AND json_extract(payload,'$.finance.state')='posted' AND wallet_cents=0"}
    else:
        sql='WITH base AS ('+base+') SELECT * FROM base'
        states={'active':'voided=0','voided':'voided!=0','pending':"voided=0 AND json_extract(payload,'$.state')='pending'",'completed':"voided=0 AND COALESCE(json_extract(payload,'$.state'),'completed')='completed'"}
    if status:sql+=' WHERE ('+states[status]+')'
    return sql,params


def history(c,*,kind='returns',start='',end='',all_dates=False,product_id='',customer_id='',status='',search='',origin='',page=1,page_size=50):
    if kind not in ('returns','processing'):raise ValueError('历史类型无效')
    start=_text(start,'开始日期',10);end=_text(end,'结束日期',10)
    if all_dates:
        if start or end:raise ValueError('全部日期不能同时指定起止日期')
    else:
        current=datetime.now(ZoneInfo('Asia/Shanghai')).date();start=start or current.replace(day=1).isoformat();end=end or current.isoformat();rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('查询范围最多3652天')
    product_id=_text(product_id,'产品');customer_id=_text(customer_id,'客户');search=_text(search,'搜索');status=_text(status,'状态');origin=_text(origin,'来源')
    if status and status not in (RETURN_STATES if kind=='returns' else PROCESS_STATES):raise ValueError('状态无效')
    if kind=='processing' and customer_id or kind=='returns' and origin:raise ValueError('该历史类型不支持此筛选')
    if origin and origin not in ('internal','customer_return'):raise ValueError('加工来源无效')
    try:page=int(page);page_size=int(page_size)
    except (ValueError,TypeError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页须为1至200条')
    register(c);sql,params=query_sql(kind,start,end,all_dates,product_id,customer_id,status,search,origin)
    counts=c.execute('SELECT COUNT(*),COALESCE(SUM(voided!=0),0) FROM ('+sql+')',params).fetchone();total=counts[0];pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    rows=[json.loads(r[0]) for r in c.execute('SELECT payload FROM ('+sql+') ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?',[*params,page_size,(page-1)*page_size])]
    summary={'count':total,'voided_count':counts[1],'active_count':total-counts[1]}
    if kind=='returns':
        summary.update(zip(('posted_cents','wallet_cents'),c.execute("SELECT COALESCE(SUM(CASE WHEN voided=0 AND json_extract(payload,'$.finance.state')='posted' THEN json_extract(payload,'$.finance.amount_cents') ELSE 0 END),0),COALESCE(SUM(CASE WHEN voided=0 THEN wallet_cents ELSE 0 END),0) FROM ("+sql+')',params).fetchone()))
        grouped="SELECT json_extract(payload,'$.product_id'),json_extract(payload,'$.unit'),history_decimal_sum(json_extract(payload,'$.qty')),history_decimal_sum(json_extract(payload,'$.net_kg')),history_decimal_sum(left_qty),history_decimal_sum(left_kg) FROM ("+sql+") WHERE voided=0 GROUP BY 1,2 ORDER BY 1,2"
        quantities=[dict(zip(('product_id','unit','qty','net_kg','remaining_qty','remaining_kg'),r)) for r in c.execute(grouped,params)]
    else:
        grouped="SELECT json_extract(payload,'$.product_id'),history_decimal_sum(json_extract(payload,'$.input_kg')) FROM ("+sql+") WHERE voided=0 GROUP BY 1 ORDER BY 1"
        quantities=[{'product_id':r[0],'input_kg':r[1]} for r in c.execute(grouped,params)]
    outputs=[]
    if kind=='processing':
        out_sql="SELECT json_extract(o.value,'$.product_id'),json_extract(o.value,'$.unit'),history_decimal_sum(json_extract(o.value,'$.qty')),history_decimal_sum(json_extract(o.value,'$.net_kg')),SUM(CASE WHEN json_extract(o.value,'$.net_kg') IS NULL OR json_extract(o.value,'$.net_kg')='' THEN 1 ELSE 0 END) FROM ("+sql+") source,json_each(source.payload,'$.outputs') o WHERE source.voided=0 GROUP BY 1,2 ORDER BY 1,2"
        outputs=[dict(zip(('product_id','unit','qty','net_kg','missing_net_kg'),r)) for r in c.execute(out_sql,params)]
    return {'outputs':outputs,'kind':kind,'rows':rows,'total':total,'pages':pages,'page':page,'page_size':page_size,'start':start,'end':end,'all_dates':bool(all_dates),'summary':summary,'quantities':quantities}


def scope(result,financial):
    if financial:return result
    def strip(v):
        if isinstance(v,dict):return {k:strip(x) for k,x in v.items() if k!='finance' and not k.endswith('_cents') and 'price' not in k}
        if isinstance(v,list):return [strip(x) for x in v]
        return v
    return strip(result)
