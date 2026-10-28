"""Read-only SQL histories; operational projections and settlement writers stay intact."""
import json
from datetime import date,datetime
from zoneinfo import ZoneInfo
import resources_costs as rc
from finance_query import _text
from inventory_query import register

MODULES={'trips':{'delivery.dispatch','finance.costs','finance.expense-payables'},'feedback':{'delivery.weighing','finance.settlement'},'movements':{'asset.crates','asset.register'},'requests':{'asset.crates'},'documents':{'finance.costs','finance.expense-payables'}}
SOURCES={'trips':('trade_records','trip','business_date'),'feedback':('trade_records','feedback','feedback_date'),'movements':('asset_records','movement','business_date'),'requests':('driver_return_requests',None,'business_date'),'documents':('trade_records','transport-document','business_date')}
STATES={'trips':('active','voided','unsettled','settled'),'feedback':('pending','resolved'),'movements':('active','voided','return','receipt','scrap','unattributed'),'requests':('pending','confirmed','withdraw_pending','rejected','withdrawn'),'documents':('active','voided')}
COMMON=('id','kind','version','business_date','updated_at','handler','note')
FIELDS={'trips':('execution_state','provider_id','closure_version','trip_id','trip_name','vehicle_id','vehicle_name','driver_ids','driver','partner','area','plan_version','voided','void_reason'), 'feedback':('order_id','customer_id','customer_name','product_id','product_name','unit','actual_qty','received_qty','difference_qty','feedback_date','state','resolution','resolved_at','source_order_version'), 'movements':('movement','asset_id','asset_name','qty','batch_id','driver_id','driver','vehicle_id','vehicle_name','trip','source_date','source_trip_id','source_vehicle_id','source_vehicle_name','order_id','customer_id','customer_name','voided','void_reason'), 'requests':('state','driver_id','driver','vehicle_id','vehicle_name','trip','source_date','source_trip_id','source_vehicle_id','source_vehicle_name','submitted_at','confirmed_batch_id','reviewed_at','reviewer','review_note','withdraw_reason'), 'documents':('voided','void_reason','provider_id','month','partner','trip_count','operator_name','expense_id')}
LINE_FIELDS=('asset_id','asset_name','qty','order_id','customer_id','customer_name')
BASIS={'trips':'日期为配送业务日；实发确认后即计入待结算，状态以是否结算或作废为准，不再区分待出车、配送中或完成。作废记录保留但不计有效汇总；费用仅授权财务可见。', 'feedback':'日期为客户反馈日期，原配送日期另列；数量取登记反馈时原实发与客户实收快照，不随当前订单改写。按产品及原单位分别汇总，反馈不直接改变库存或应收。', 'movements':'日期为实物流水业务日；只汇总有效回筐、新增及报损，不含司机待确认填报，不将流水当作库存余额。按原框型编号分别列示，父框与属性流水各计一次，不额外叠加父框汇总；未关联客户的历史回筐不冲减客户欠筐。', 'requests':'日期为填报回筐业务日，原配送日期与提交/复核时间另列。仅列已提交的填报当前状态，草稿和已删除草稿不公开。填报数量不代表实物入账；确认后以关联批次的有效实物流水为准，不与回筐流水相加。', 'documents':'日期为结算所属月的月末业务日，月份另列。金额取出具时归档快照，已撤销记录保留但不计有效汇总；不按当前区域价格重算；应付与付款仍在原费用流程核对。'}

def check_kind(kind):
    if kind not in SOURCES:raise ValueError('历史类型无效')

def source_sql(kind,start='',end='',all_dates=False,*,status='',search='',driver_id='',vehicle_id='',customer_id='',asset_id='',partner=''):
    check_kind(kind);table,record_kind,field=SOURCES[kind];when="json_extract(t.payload,'$."+field+"')";conditions=[];args=[]
    if record_kind:conditions.append("json_extract(t.payload,'$.kind')=?");args.append(record_kind)
    if kind=='requests':conditions.append("json_extract(t.payload,'$.state') IN ('pending','confirmed','withdraw_pending','rejected','withdrawn')")
    if not all_dates:conditions += [when+'>=?',when+'<=?'];args += [start,end]
    for key,value in [('vehicle_id',vehicle_id),('partner',partner),('customer_id',customer_id),('asset_id',asset_id)]:
        if value:
            if kind=='requests' and key in ('customer_id','asset_id'):
                conditions.append("EXISTS(SELECT 1 FROM json_each(t.payload,'$.lines') l WHERE json_extract(l.value,'$."+key+"')=?)")
            else:conditions.append("json_extract(t.payload,'$."+key+"')=?")
            args.append(value)
    if driver_id:
        if kind=='trips':conditions.append("(json_extract(t.payload,'$.driver_id')=? OR EXISTS(SELECT 1 FROM json_each(t.payload,'$.driver_ids') d WHERE d.value=?))");args += [driver_id,driver_id]
        else:conditions.append("json_extract(t.payload,'$.driver_id')=?");args.append(driver_id)
    void="COALESCE(json_extract(t.payload,'$.voided'),0)";state="json_extract(t.payload,'$.state')"
    if status:
        if status in ('active','voided'):conditions.append(void+('=0' if status=='active' else '!=0'))
        elif kind=='trips':conditions += [void+'=0',"COALESCE(json_extract(t.payload,'$.document_id'),'')"+("=''" if status=='unsettled' else "!=''")]
        elif kind=='movements':
            conditions.append(void+'=0')
            if status=='unattributed':conditions += ["json_extract(t.payload,'$.movement')='return'","COALESCE(json_extract(t.payload,'$.customer_id'),'')=''"]
            else:conditions.append("json_extract(t.payload,'$.movement')=?");args.append(status)
        else:conditions.append(state+'=?');args.append(status)
    if search:
        # Literal contains search over safe fields only; hidden financial state is not searchable.
        keys=['id','note',*FIELDS[kind]]
        keys=[k for k in keys if k not in ('driver_ids','expense_id')]
        expression="||' '||".join("COALESCE(CAST(json_extract(t.payload,'$."+k+"') AS TEXT),'')" for k in keys)
        conditions.append('instr(lower('+expression+'),lower(?))>0');args.append(search)
    return 'SELECT t.id,t.payload,'+when+' query_date FROM '+table+' t WHERE '+(' AND '.join(conditions) or '1'),args

def safe_record(kind,r,financial=False):
    value={k:r[k] for k in (*COMMON,*FIELDS[kind]) if k in r}
    value['query_date']=r.get(SOURCES[kind][2],'')
    if kind in ('trips','movements'):value.setdefault('voided',False)
    if financial and kind in ('trips','documents'):
        for k in ('amount_cents','document_id'):
            if k in r:value[k]=r[k]
    if kind=='requests':value['lines']=[{k:l[k] for k in LINE_FIELDS if k in l} for l in r.get('lines',[])]
    if kind=='documents':value['lines']=[safe_record('trips',l,True) for l in r.get('lines',[])]
    return value

def detail(c,kind,key,*,financial=False):
    check_kind(kind)
    if kind=='documents' and not financial:raise ValueError('需要财务查看权限')
    key=_text(key,'原单编号',100);sql,args=source_sql(kind,all_dates=True)
    row=c.execute('SELECT payload FROM ('+sql+') WHERE id=?',[*args,key]).fetchone()
    return {'kind':kind,'record':safe_record(kind,json.loads(row[0]),financial),'basis':BASIS[kind]} if row else None

def history(c,*,kind='trips',start='',end='',all_dates=False,status='',search='',driver_id='',vehicle_id='',customer_id='',asset_id='',partner='',page=1,page_size=50,financial=False):
    check_kind(kind);start=_text(start,'开始日期',10);end=_text(end,'结束日期',10)
    if all_dates:
        if start or end:raise ValueError('全部日期不能同时指定起止日期')
    else:
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date();start=start or today.replace(day=1).isoformat();end=end or today.isoformat();rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('查询范围最多3652天')
    values={k:_text(v,k,100) for k,v in [('status',status),('search',search),('driver_id',driver_id),('vehicle_id',vehicle_id),('customer_id',customer_id),('asset_id',asset_id),('partner',partner)]};status=values['status']
    if status and status not in STATES[kind]:raise ValueError('状态无效')
    supported={'trips':{'driver_id','vehicle_id','partner'},'feedback':{'customer_id'},'movements':{'driver_id','vehicle_id','customer_id','asset_id'},'requests':{'driver_id','vehicle_id'},'documents':{'partner'}}[kind]
    if any(v for k,v in values.items() if k not in supported|{'status','search'}):raise ValueError('该类型不支持此筛选')
    if kind=='documents' and not financial:raise ValueError('需要财务查看权限')
    if kind=='trips' and status in ('settled','unsettled') and not financial:raise ValueError('需要财务状态查看权限')
    try:page=int(page);page_size=int(page_size)
    except (ValueError,TypeError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('分页参数无效')
    register(c);sql,args=source_sql(kind,start,end,all_dates,**values)
    total=c.execute('SELECT COUNT(*) FROM ('+sql+')',args).fetchone()[0];pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    raw=[json.loads(r[0]) for r in c.execute('SELECT payload FROM ('+sql+') ORDER BY query_date DESC,id DESC LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size])]
    # List rows omit archive lines; the complete original is fetched by ID on demand.
    rows=[]
    for r in raw:
        value=safe_record(kind,r,financial);value.pop('lines',None);rows.append(value)
    base='WITH selected AS ('+sql+') '
    def qty_sum(expression,name):
        return 'CASE WHEN COUNT('+expression+')=0 THEN NULL ELSE history_decimal_sum('+expression+') END '+name+',SUM('+expression+' IS NULL) '+name+'_missing'
    if kind=='feedback':
        expr="SELECT json_extract(payload,'$.product_id') product_id,json_extract(payload,'$.product_name') product_name,json_extract(payload,'$.unit') unit,COUNT(*) count,"+','.join(qty_sum("json_extract(payload,'$."+k+"')",k) for k in ('actual_qty','received_qty','difference_qty'))+" FROM selected GROUP BY product_id,product_name,unit ORDER BY product_id,unit,product_name"
    elif kind=='movements':
        expr="SELECT json_extract(payload,'$.asset_id') asset_id,json_extract(payload,'$.asset_name') asset_name,json_extract(payload,'$.movement') movement,COUNT(*) count,"+qty_sum("json_extract(payload,'$.qty')",'qty')+" FROM selected WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 GROUP BY asset_id,asset_name,movement ORDER BY asset_id,movement,asset_name"
    elif kind=='requests':
        expr="SELECT json_extract(s.payload,'$.state') state,json_extract(l.value,'$.asset_id') asset_id,json_extract(l.value,'$.asset_name') asset_name,COUNT(DISTINCT s.id) count,"+qty_sum("json_extract(l.value,'$.qty')",'qty')+" FROM selected s,json_each(s.payload,'$.lines') l GROUP BY state,asset_id,asset_name ORDER BY state,asset_id,asset_name"
    else:
        expr="SELECT json_extract(payload,'$.partner') partner,COUNT(*) count"
        if kind=='documents':expr+=",SUM(json_extract(payload,'$.trip_count')) trip_count"
        if financial:expr+=",SUM(json_extract(payload,'$.amount_cents')) amount_cents,SUM(json_extract(payload,'$.amount_cents') IS NULL) amount_missing"
        expr+=" FROM selected"+(" WHERE COALESCE(json_extract(payload,'$.voided'),0)=0" if kind in ('trips','documents') else '')+" GROUP BY partner ORDER BY partner"
    cursor=c.execute(base+expr,args);names=[r[0] for r in cursor.description];summary=[dict(zip(names,r)) for r in cursor]
    return {'kind':kind,'start':start,'end':end,'all':all_dates,'financial':financial,'total':total,'page':page,'pages':pages,'page_size':page_size,'rows':rows,'summary':summary,'basis':BASIS[kind]}
