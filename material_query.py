"""SQL history pages over original material facts and their complete FIFO valuation.

FIFO remains the canonical Python engine, restricted only by material and end
cutoff. Neither the start date nor warehouse filter may truncate that chain.
No derived/business tables are written by these reads.
"""
import json
from datetime import date,datetime
from zoneinfo import ZoneInfo
import resources_costs as rc
from finance_query import _text
from inventory_query import register

REUSABLE=('P-LARGE','P-MEDIUM','P-SMOKED','P-KONJAC','P-LONG')
KINDS=('opening','receipt','consume','return','loss','count','transfer','gain')
WHEN="json_extract(e.payload,'$.business_date')"
MID="json_extract(e.payload,'$.material_id')"
WAREHOUSE="COALESCE(NULLIF(json_extract(e.payload,'$.warehouse_id'),''),CASE WHEN json_extract(e.payload,'$.material_id')='RM-SOY' THEN 'WH-UNASSIGNED' ELSE 'WH-COMMON' END)"

def source_sql(start,end,all_dates,material_id='',category='',warehouse_id='',entry_kind='',status='',search=''):
    where=[];args=[]
    if not all_dates:where.extend([WHEN+'>=?',WHEN+'<=?']);args.extend([start,end])
    for field,value in [(MID,material_id),('i.category',category),("json_extract(e.payload,'$.kind')",entry_kind)]:
        if value:where.append(field+'=?');args.append(value)
    if warehouse_id:where.append('('+WAREHOUSE+"=? OR json_extract(e.payload,'$.target_warehouse_id')=?)");args.extend([warehouse_id,warehouse_id])
    if status:where.append("COALESCE(json_extract(e.payload,'$.voided'),0)="+('1' if status=='voided' else '0'))
    if search:
        where.append("instr(lower(e.id||' '||COALESCE(i.name,'')||' '||COALESCE(json_extract(e.payload,'$.material_name'),'')||' '||COALESCE(json_extract(e.payload,'$.handler'),'')||' '||COALESCE(json_extract(e.payload,'$.reference'),'')||' '||COALESCE(json_extract(e.payload,'$.partner'),'')||' '||COALESCE(json_extract(e.payload,'$.note'),'')),lower(?))>0");args.append(search)
    sql='SELECT e.id,e.payload,'+WHEN+' business_date,'+MID+" material_id,COALESCE(json_extract(e.payload,'$.sequence'),0) sequence,COALESCE(json_extract(e.payload,'$.voided'),0) voided FROM material_entries e JOIN material_items i ON i.id="+MID+' WHERE '+(' AND '.join(where) or '1')
    return sql,args


def query(c,*,view='ledger',start='',end='',all_dates=False,as_of='',material_id='',category='',warehouse_id='',entry_kind='',status='',search='',page=1,page_size=50):
    if view not in ('ledger','stock'):raise ValueError('库存查询类型无效')
    start=_text(start,'开始日期',10);end=_text(end,'结束日期',10);as_of=_text(as_of,'余额截止日',10)
    current=datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if view=='stock':
        if start or end or all_dates or entry_kind:raise ValueError('余额查询只使用截止日，不使用流水起止范围/业务类型')
        as_of=as_of or current.isoformat();rc.day(as_of)
    else:
        if as_of:raise ValueError('流水查询不支持余额截止日')
        if all_dates:
            if start or end:raise ValueError('全部日期不能同时指定起止日期')
        else:
            start=start or current.replace(day=1).isoformat();end=end or current.isoformat();rc.day(start);rc.day(end)
            if start>end or (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('日期范围须正序且最多3652天')
    material_id=_text(material_id,'物料');category=_text(category,'分类');warehouse_id=_text(warehouse_id,'库房');entry_kind=_text(entry_kind,'业务类型');search=_text(search,'搜索');status=_text(status,'状态')
    allowed=('valid','voided') if view=='ledger' else ('nonzero','low','unopened','active','inactive','uncosted')
    if status and status not in allowed or entry_kind and entry_kind not in KINDS:raise ValueError('库存状态或业务类型无效')
    if category and category not in ('原料','辅料','耗材','包装','其他'):raise ValueError('物料分类无效')
    try:page=int(page);page_size=int(page_size)
    except (ValueError,TypeError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页须为1至200条')
    register(c)
    if view=='ledger':return ledger(c,start,end,all_dates,material_id,category,warehouse_id,entry_kind,status,search,page,page_size)
    return stock(c,as_of,material_id,category,warehouse_id,status,search,page,page_size)


def paging(total,page,page_size):
    pages=max(1,(total+page_size-1)//page_size);return min(page,pages),pages


def ledger(c,start,end,all_dates,material_id,category,warehouse_id,entry_kind,status,search,page,page_size):
    sql,args=source_sql(start,end,all_dates,material_id,category,warehouse_id,entry_kind,status,search)
    count=c.execute('SELECT COUNT(*),COALESCE(SUM(voided),0) FROM ('+sql+')',args).fetchone();page,pages=paging(count[0],page,page_size)
    selected=c.execute('SELECT id,payload,voided FROM ('+sql+') ORDER BY business_date DESC,sequence DESC,id DESC LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size]).fetchall()
    mids=[r[0] for r in c.execute('SELECT DISTINCT material_id FROM ('+sql+') WHERE voided=0',args)]
    _,projected=rc.material_ledger(c,until=None if all_dates else end,material_ids=mids)
    lookup={e['id']:e for e in projected};rows=[];names=rc.warehouse_names(c)
    for r in selected:
        if not r[2]:rows.append(lookup[r[0]])
        else:
            v=json.loads(r[1]);wid=rc.entry_warehouse(v)
            rows.append({**v,'warehouse_id':wid,'warehouse_name':names.get(wid,wid),'cost_cents':None,'delta_qty':'0'})
    # Bind only derived scalar values; SQL performs the full scoped aggregation.
    values=rc.dump([{'id':e['id'],'cost_cents':e['cost_cents'],'delta_qty':e['delta_qty']} for e in projected])
    sums="""WITH derived AS (SELECT json_extract(value,'$.id') id,MAX(json_extract(value,'$.cost_cents')) cost_cents,MAX(json_extract(value,'$.delta_qty')) delta_qty FROM json_each(?) GROUP BY json_extract(value,'$.id')),source AS ("""+sql+"""), scoped AS (
      SELECT s.*,d.cost_cents,d.delta_qty FROM source s LEFT JOIN derived d ON d.id=+s.id)
      SELECT material_id,json_extract(payload,'$.unit'),
      history_decimal_sum(CASE WHEN voided=0 AND json_extract(payload,'$.kind') IN ('opening','receipt','return','gain') THEN json_extract(payload,'$.qty') ELSE '0' END),
      history_decimal_sum(CASE WHEN voided=0 AND json_extract(payload,'$.kind') NOT IN ('opening','receipt','return','gain','transfer') THEN json_extract(payload,'$.qty') ELSE '0' END),
      history_decimal_sum(CASE WHEN voided=0 AND json_extract(payload,'$.kind')='transfer' THEN json_extract(payload,'$.qty') ELSE '0' END),
      history_decimal_sum(CASE WHEN voided=0 THEN COALESCE(delta_qty,'0') ELSE '0' END),
      COALESCE(SUM(CASE WHEN voided=0 THEN cost_cents ELSE 0 END),0) FROM scoped GROUP BY 1,2 ORDER BY 1,2"""
    quantities=[dict(zip(('material_id','unit','incoming_qty','outgoing_qty','transfer_qty','company_net_qty','cost_cents'),r)) for r in c.execute(sums,[values,*args])]
    return {'view':'ledger','rows':rows,'total':count[0],'page':page,'pages':pages,'page_size':page_size,'summary':{'count':count[0],'voided_count':count[1],'cost_cents':sum(q['cost_cents'] for q in quantities)},'quantities':quantities,'start':start,'end':end,'all_dates':all_dates,'valuation_note':'FIFO按匹配物料截至终日的全部库房历史计价；日期开始、库房和页码不会截断成本链；作废流水不计库存。'}


def stock(c,as_of,material_id,category,warehouse_id,status,search,page,page_size):
    where=["id NOT IN ("+','.join('?' for _ in REUSABLE)+')'];args=list(REUSABLE)
    if material_id:where.append('id=?');args.append(material_id)
    if category:where.append('category=?');args.append(category)
    mids=[r[0] for r in c.execute('SELECT id FROM material_items WHERE '+' AND '.join(where),args)]
    _,entries,balances=rc.material_ledger(c,until=as_of,warehouse_details=True,material_ids=mids)
    touched={(e['material_id'],e['warehouse_id']) for e in entries}|{(e['material_id'],e['target_warehouse_id']) for e in entries if e.get('target_warehouse_id')}
    values=rc.dump([{**{k:v for k,v in s.items() if k!='lots'},'has_entries':(s['id'],s['warehouse_id']) in touched} for s in balances])
    cond=[];params=[values]
    if warehouse_id:cond.append("json_extract(value,'$.warehouse_id')=?");params.append(warehouse_id)
    if search:cond.append("instr(lower(json_extract(value,'$.id')||' '||json_extract(value,'$.name')||' '||json_extract(value,'$.warehouse_name')),lower(?))>0");params.append(search)
    states={'nonzero':"history_positive(json_extract(value,'$.qty'))",'low':"json_extract(value,'$.low_stock')=1 AND json_extract(value,'$.has_entries')=1",'unopened':"json_extract(value,'$.has_entries')=0",'active':"json_extract(value,'$.active')=1",'inactive':"json_extract(value,'$.active')=0",'uncosted':"history_positive(json_extract(value,'$.uncosted_qty'))"}
    if status:cond.append(states[status])
    source=' FROM json_each(?) WHERE '+(' AND '.join(cond) or '1')
    total,value=c.execute("SELECT COUNT(*),COALESCE(SUM(json_extract(value,'$.value_cents')),0)"+source,params).fetchone();page,pages=paging(total,page,page_size)
    rows=[json.loads(r[0]) for r in c.execute("SELECT value"+source+" ORDER BY json_extract(value,'$.id'),json_extract(value,'$.warehouse_id') LIMIT ? OFFSET ?",[*params,page_size,(page-1)*page_size])]
    quantities=[dict(zip(('material_id','unit','qty','uncosted_qty','value_cents'),r)) for r in c.execute("SELECT json_extract(value,'$.id'),json_extract(value,'$.unit'),history_decimal_sum(json_extract(value,'$.qty')),history_decimal_sum(json_extract(value,'$.uncosted_qty')),SUM(json_extract(value,'$.value_cents'))"+source+' GROUP BY 1,2 ORDER BY 1,2',params)]
    return {'view':'stock','rows':rows,'total':total,'page':page,'pages':pages,'page_size':page_size,'summary':{'count':total,'value_cents':value},'quantities':quantities,'as_of':as_of,'valuation_note':'余额截至所选日终；FIFO按所需物料全部库房的完整历史计算，不是当前页或本月流水净额。'}


def scope(value,financial):
    def strip(v):
        if isinstance(v,dict):return {k:strip(x) for k,x in v.items() if not k.endswith('_cents') and 'price' not in k and k not in ('valuation_history','purchase_charge_history')}
        if isinstance(v,list):return [strip(x) for x in v]
        return v
    return value if financial else strip(value)
