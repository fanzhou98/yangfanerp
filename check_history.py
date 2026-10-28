"""Saved pre/post-dispatch evidence, evaluated only against each saved source snapshot.
Live source-change checks remain in inventory_reconciliation.report, never inferred here.
"""
import json
from datetime import datetime,date
from zoneinfo import ZoneInfo
from decimal import Decimal
import resources_costs as rc
from inventory_query import register
from finance_query import _text

STATES={'matched':'保存时已对平','variance':'保存时有差异','negative':'保存时应剩为负','missing':'保存时实盘待补','unconfirmed':'保存时完整性待确认','unit':'保存时单位不一致','source_missing':'原实发快照未列'}
PRODUCT_FIELDS=('product_id','unit','pre_qty','post_qty','post_in_qty','post_out_qty','movement_note','post_source','closing_version')
SOURCE_FIELDS=('order_id','customer_id','customer_name','product_id','unit','actual_qty','ordered_qty')

def dec(v):return None if v in (None,'') else Decimal(str(v))
def arithmetic(a,b,sign=1):return None if dec(a) is None or dec(b) is None else rc.ds(dec(a)+sign*dec(b))

def source_sql(start,end,all_dates,product_id='',status='',search='',versions='latest'):
    where=["json_extract(t.payload,'$.kind')='inventory-check'"];args=[]
    if not all_dates:where.extend(["json_extract(t.payload,'$.business_date')>=?","json_extract(t.payload,'$.business_date')<=?"]);args.extend([start,end])
    base='SELECT t.id,t.payload FROM trade_records t WHERE '+' AND '.join(where)
    revision="SELECT id,payload record,1 is_latest FROM base"
    if versions=='all':revision+=" UNION ALL SELECT b.id,h.value,0 FROM base b,json_each(b.payload,'$.history') h"
    sql="""WITH base AS ("""+base+"""), revisions AS ("""+revision+"""), items AS (
      SELECT r.id,json_extract(record,'$.business_date') business_date,json_extract(record,'$.version') version,is_latest,
      json_extract(record,'$.handler') handler,json_extract(record,'$.note') note,json_extract(record,'$.updated_at') updated_at,
      COALESCE(json_extract(record,'$.sources_checked'),0) sources_checked,
      json_type(record,'$.source_snapshot')='array' snapshot_available,
      json_extract(p.value,'$.product_id') product_id,COALESCE(m.name,json_extract(p.value,'$.product_id')) product_name,
      json_extract(p.value,'$.unit') unit,NULLIF(json_extract(p.value,'$.pre_qty'),'') pre_qty,NULLIF(json_extract(p.value,'$.post_qty'),'') post_qty,
      COALESCE(NULLIF(json_extract(p.value,'$.post_in_qty'),''),'0') post_in_qty,COALESCE(NULLIF(json_extract(p.value,'$.post_out_qty'),''),'0') post_out_qty,
      json_extract(p.value,'$.movement_note') movement_note,COALESCE(json_extract(p.value,'$.post_source'),'manual') post_source,
      json_extract(p.value,'$.closing_version') closing_version,
      json_extract(p.value,'$.unit') IS NOT NULL AND json_extract(p.value,'$.unit')!='' AND NOT EXISTS(SELECT 1 FROM json_each(record,'$.source_snapshot') l WHERE json_extract(l.value,'$.product_id')=json_extract(p.value,'$.product_id') AND COALESCE(json_extract(l.value,'$.unit'),'')!=json_extract(p.value,'$.unit')) same_unit,
      COALESCE((SELECT history_decimal_sum(COALESCE(NULLIF(json_extract(l.value,'$.actual_qty'),''),'0')) FROM json_each(record,'$.source_snapshot') l WHERE json_extract(l.value,'$.product_id')=json_extract(p.value,'$.product_id')),'0') source_qty
      FROM revisions r,json_each(record,'$.products') p LEFT JOIN products m ON m.id=json_extract(p.value,'$.product_id')
    ), expected AS (SELECT *,CASE WHEN snapshot_available AND same_unit THEN source_qty END shipped_qty,
      CASE WHEN snapshot_available AND same_unit AND pre_qty IS NOT NULL THEN check_history_sub(check_history_add(check_history_sub(pre_qty,source_qty),post_in_qty),post_out_qty) END expected_qty FROM items
    ), differences AS (SELECT *,CASE WHEN sources_checked AND post_qty IS NOT NULL THEN check_history_sub(post_qty,expected_qty) END difference_qty FROM expected),
    projection AS (SELECT *,CASE WHEN NOT COALESCE(snapshot_available,0) THEN 'source_missing' WHEN NOT same_unit THEN 'unit' WHEN pre_qty IS NULL OR post_qty IS NULL THEN 'missing' WHEN NOT sources_checked THEN 'unconfirmed' WHEN check_history_negative(expected_qty) THEN 'negative' WHEN check_history_zero(difference_qty) THEN 'matched' ELSE 'variance' END status FROM differences)
    SELECT * FROM projection"""
    filters=[]
    if product_id:filters.append('product_id=?');args.append(product_id)
    if status:filters.append('status=?');args.append(status)
    if search:
        filters.append("instr(lower(COALESCE(product_name,'')||' '||product_id||' '||COALESCE(handler,'')||' '||COALESCE(note,'')||' '||COALESCE(movement_note,'')||' '||business_date),lower(?))>0");args.append(search)
    if filters:sql+=' WHERE '+' AND '.join(filters)
    return sql,args

def history(c,*,start='',end='',all_dates=False,product_id='',status='',search='',versions='latest',page=1,page_size=50):
    start=_text(start,'开始日期',10);end=_text(end,'结束日期',10)
    if all_dates:
        if start or end:raise ValueError('全部日期不能同时指定起止日期')
    else:
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date();start=start or today.replace(day=1).isoformat();end=end or today.isoformat();rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('查询范围最多3652天')
    product_id=_text(product_id,'产品');status=_text(status,'状态');search=_text(search,'搜索');versions=_text(versions,'版本范围')
    if status and status not in STATES:raise ValueError('状态无效')
    if versions not in ('latest','all'):raise ValueError('版本范围无效')
    try:page=int(page);page_size=int(page_size)
    except (ValueError,TypeError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页须为1至200条')
    register(c);c.create_function('check_history_add',2,arithmetic,deterministic=True);c.create_function('check_history_sub',2,lambda a,b:arithmetic(a,b,-1),deterministic=True);c.create_function('check_history_negative',1,lambda a:int(dec(a) is not None and dec(a)<0),deterministic=True);c.create_function('check_history_zero',1,lambda a:int(dec(a) is not None and dec(a)==0),deterministic=True)
    sql,args=source_sql(start,end,all_dates,product_id,status,search,versions)
    total,days,revisions=c.execute("SELECT COUNT(*),COUNT(DISTINCT business_date),COUNT(DISTINCT business_date||'/'||version) FROM ("+sql+')',args).fetchone();pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    cursor=c.execute('SELECT * FROM ('+sql+') ORDER BY business_date DESC,version DESC,product_id,unit LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size]);names=[d[0] for d in cursor.description];rows=[dict(zip(names,r)) for r in cursor]
    for r in rows:r.pop('source_qty',None);r['status_label']=STATES[r['status']]
    fields=','.join("SUM(status='%s') %s_count"%(k,k) for k in STATES)
    cursor=c.execute('SELECT product_id,product_name,unit,COUNT(*) count,'+fields+' FROM ('+sql+') GROUP BY product_id,product_name,unit ORDER BY product_id,unit',args);names=[d[0] for d in cursor.description];summary=[dict(zip(names,r)) for r in cursor]
    return {'start':start,'end':end,'all':all_dates,'versions':versions,'total':total,'days':days,'revisions':revisions,'page':page,'pages':pages,'page_size':page_size,'rows':rows,'summary':summary,'basis':'按核对业务日期查询已保存依据，每行一个产品的一个保存版本。差异仅按该版保存的实发快照计算，不表示当前已对平；当前实发及日结来源是否变化，请进入单日核对页核验。产品名称来自当前档案，单位来自原记录；未登记的日期和产品不在此表。完整汇总只统计记录项数，不累加库存余额、实发或跨版本数量。'}

def record(c,day,version):
    day=_text(day,'业务日期',10);rc.day(day)
    try:version=int(version)
    except (ValueError,TypeError):raise ValueError('版本号无效')
    if not 1<=version<=1000000:raise ValueError('版本号无效')
    row=c.execute("SELECT payload FROM trade_records WHERE id=? AND json_extract(payload,'$.kind')='inventory-check' AND json_extract(payload,'$.business_date')=?",('IC-'+day,day)).fetchone()
    if not row:raise LookupError('核对记录不存在')
    root=json.loads(row[0]);value=next((v for v in [root,*root.get('history',[])] if v.get('version')==version),None)
    if value is None:raise LookupError('此核对版本不存在')
    result={k:value.get(k) for k in ('business_date','version','handler','note','updated_at','sources_checked')};result['is_latest']=version==root.get('version');result['snapshot_available']=isinstance(value.get('source_snapshot'),list)
    result['products']=[{k:p.get(k) for k in PRODUCT_FIELDS} for p in value.get('products',[])]
    result['source_snapshot']=[{k:l.get(k) for k in SOURCE_FIELDS} for l in (value.get('source_snapshot') or [])];return result
