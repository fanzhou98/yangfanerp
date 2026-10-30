"""Q03 purchase order history: SQL filters/totals/pages, complete selected-order details."""
from datetime import datetime,date
from decimal import Decimal
from zoneinfo import ZoneInfo
import purchasing
import resources_costs as rc
from finance_query import _text

STATUSES=('草稿','待入库','部分入库','全部入库','已关闭余量','已取消')
DATE="json_extract(o.payload,'$.business_date')"
SUPPLIER="json_extract(o.payload,'$.supplier_id')"


class DecimalSum:
    def __init__(self):self.value=Decimal(0)
    def step(self,value):self.value+=Decimal(str(value or 0))
    def finalize(self):return str(self.value)


def _register(c):
    c.create_aggregate('purchase_decimal_sum',1,DecimalSum)
    c.create_function('purchase_decimal_eq',2,lambda a,b:int(Decimal(str(a or 0))==Decimal(str(b or 0))),deterministic=True)


def sql_scope(*,start,end,all_dates,supplier_id,search,status):
    terms=[];params=[]
    if not all_dates:terms.extend([DATE+'>=?',DATE+'<=?']);params.extend([start,end])
    if supplier_id:terms.append(SUPPLIER+'=?');params.append(supplier_id)
    if search:
        terms.append("(instr(lower(o.id||' '||COALESCE(json_extract(o.payload,'$.supplier_name'),'')||' '||COALESCE(json_extract(o.payload,'$.note'),'')),lower(?))>0 OR EXISTS(SELECT 1 FROM json_each(o.payload,'$.lines') sl WHERE instr(lower(COALESCE(json_extract(sl.value,'$.material_name'),'')),lower(?))>0))")
        params.extend([search,search])
    where=' AND '.join(terms) or '1'
    # Unary + removes the outer TEXT affinity without changing its value; this
    # lets SQLite use the JSON expression index for correlated receipt lookups.
    query=f"""WITH base AS (SELECT o.id,o.payload,{DATE} business_date,
      CASE json_extract(o.payload,'$.state') WHEN 'draft' THEN '草稿' WHEN 'cancelled' THEN '已取消' WHEN 'closed' THEN '已关闭余量'
      ELSE CASE WHEN NOT EXISTS(SELECT 1 FROM json_each(o.payload,'$.lines') l WHERE NOT purchase_decimal_eq(json_extract(l.value,'$.qty'),
        (SELECT purchase_decimal_sum(json_extract(rl.value,'$.qty')) FROM purchase_receipts r,json_each(r.payload,'$.lines') rl
         WHERE json_extract(r.payload,'$.order_id')=+o.id AND json_extract(rl.value,'$.line_id')=json_extract(l.value,'$.id')))) THEN '全部入库'
      WHEN EXISTS(SELECT 1 FROM purchase_receipts r WHERE json_extract(r.payload,'$.order_id')=+o.id) THEN '部分入库' ELSE '待入库' END END status
      FROM purchase_orders o WHERE {where})
      SELECT * FROM base"""
    if status=='待验收':query+=" WHERE status IN ('待入库','部分入库')"
    elif status:query+=' WHERE status=?';params.append(status)
    return query,params


def orders(c,*,start='',end='',all_dates=False,supplier_id='',search='',status='',page=1,page_size=50):
    start=_text(start,'开始日期',10);end=_text(end,'结束日期',10)
    if not all_dates:
        current=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        start=start or current;end=end or start;rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('采购日期范围最多3652天')
    elif start or end:raise ValueError('全部日期不能同时指定起止日期')
    supplier_id=_text(supplier_id,'供应商');search=_text(search,'搜索内容');status=_text(status,'采购状态')
    if status and status not in (*STATUSES,'待验收'):raise ValueError('采购状态无效')
    try:page=int(page);page_size=int(page_size)
    except (TypeError,ValueError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页条数须为1至200')
    _register(c)
    sql,params=sql_scope(start=start,end=end,all_dates=all_dates,supplier_id=supplier_id,search=search,status=status)
    totals=c.execute("SELECT COUNT(*),COALESCE(SUM(status='草稿'),0),COALESCE(SUM(status IN ('待入库','部分入库')),0),COALESCE(SUM(CASE WHEN status!='已取消' THEN json_extract(payload,'$.total_cents') ELSE 0 END),0) FROM ("+sql+")",params).fetchone()
    total=totals[0];pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    ids=[r[0] for r in c.execute('SELECT id FROM ('+sql+') ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?',[*params,page_size,(page-1)*page_size])]
    projected=purchasing.projection(c,order_ids=ids)
    by_id={r['id']:r for r in projected['orders']}
    return {'rows':[by_id[i] for i in ids],'total':total,'page':page,'pages':pages,'page_size':page_size,
      'start':start,'end':end,'all_dates':bool(all_dates),'summary':{'orders':total,'draft_orders':totals[1],'pending_orders':totals[2],'total_cents':totals[3]}}


def ledger_sql(kind,*,start,end,all_dates,supplier_id='',search='',status='',payment_kind='',charge_kind=''):
    table={'receipts':'purchase_receipts','payments':'purchase_payments','charges':'purchase_charges'}[kind]
    when="json_extract(t.payload,'$.business_date')";terms=[];params=[]
    if not all_dates:terms.extend([when+'>=?',when+'<=?']);params.extend([start,end])
    if supplier_id:
        # Fee/payment supplier_id can be the actual payee: always filter the source supplier.
        source="json_extract(t.payload,'$.supplier_id')" if kind=='receipts' else "json_extract(o.payload,'$.supplier_id')"
        terms.append(source+'=?');params.append(supplier_id)
    if search:
        terms.append("(instr(lower(t.id||' '||COALESCE(json_extract(t.payload,'$.order_id'),'')||' '||COALESCE(json_extract(o.payload,'$.supplier_name'),'')||' '||COALESCE(json_extract(t.payload,'$.supplier_name'),'')||' '||COALESCE(json_extract(t.payload,'$.payee_name'),'')||' '||COALESCE(json_extract(t.payload,'$.reference'),'')||' '||COALESCE(json_extract(t.payload,'$.note'),'')),lower(?))>0 OR EXISTS(SELECT 1 FROM json_each(t.payload,'$.lines') l WHERE instr(lower(COALESCE(json_extract(l.value,'$.material_name'),'')),lower(?))>0))")
        params.extend([search,search])
    if payment_kind:terms.append("COALESCE(json_extract(t.payload,'$.charge_id'),'')"+('!=' if payment_kind=='charge' else '=')+"''")
    if charge_kind:terms.append("json_extract(t.payload,'$.kind')=?");params.append(charge_kind)
    calculated="0 paid_cents,0 charges_cents"
    if kind=='receipts':calculated="0 paid_cents,COALESCE((SELECT SUM(json_extract(ch.payload,'$.amount_cents')) FROM purchase_charges ch WHERE json_extract(ch.payload,'$.receipt_id')=+t.id),0) charges_cents"
    if kind=='charges':calculated="COALESCE((SELECT SUM(json_extract(p.payload,'$.amount_cents')) FROM purchase_payments p WHERE json_extract(p.payload,'$.charge_id')=+t.id AND COALESCE(json_extract(p.payload,'$.voided'),0)=0),0) paid_cents,0 charges_cents"
    sql=f"""WITH base AS (SELECT t.id,t.payload,{when} business_date,
      COALESCE(json_extract(t.payload,'$.amount_cents'),0) amount_cents,
      json_extract(o.payload,'$.supplier_id') order_supplier_id,json_extract(o.payload,'$.supplier_name') order_supplier_name,
      {calculated} FROM {table} t LEFT JOIN purchase_orders o ON o.id=json_extract(t.payload,'$.order_id')
      WHERE {' AND '.join(terms) or '1'}) SELECT * FROM base"""
    if status:
        sql+=' WHERE '+{'unpaid':'amount_cents>paid_cents','paid':'amount_cents=paid_cents','overdue':"amount_cents>paid_cents AND json_extract(payload,'$.due_date')<?"}[status]
        if status=='overdue':params.append(datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    return sql,params


def ledger(c,*,kind='receipts',start='',end='',all_dates=False,supplier_id='',search='',status='',payment_kind='',charge_kind='',month='',page=1,page_size=50):
    if kind not in ('receipts','payments','charges','pending','payables'):raise ValueError('采购历史类型无效')
    if kind=='payables':
        if start or end or all_dates or payment_kind or charge_kind:raise ValueError('货款应付查询不支持日期范围或付款类型')
        return payables(c,month=month,supplier_id=supplier_id,search=search,status=status,page=page,page_size=page_size)
    if month:raise ValueError('月份参数仅用于货款应付')
    if kind=='pending':
        if status or payment_kind or charge_kind:raise ValueError('待验收查询不支持该筛选')
        return orders(c,start=start,end=end,all_dates=all_dates,supplier_id=supplier_id,search=search,status='待验收',page=page,page_size=page_size)
    start=_text(start,'开始日期',10);end=_text(end,'结束日期',10)
    if not all_dates:
        start=start or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat();end=end or start;rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('采购日期范围最多3652天')
    elif start or end:raise ValueError('全部日期不能同时指定起止日期')
    supplier_id=_text(supplier_id,'货源供应商');search=_text(search,'搜索内容');status=_text(status,'付款状态')
    if status and (kind!='charges' or status not in ('paid','unpaid','overdue')):raise ValueError('付款状态无效')
    if payment_kind and (kind!='payments' or payment_kind not in ('goods','charge')):raise ValueError('付款类型无效')
    if charge_kind and (kind!='charges' or charge_kind not in ('freight','unloading')):raise ValueError('费用类型无效')
    try:page=int(page);page_size=int(page_size)
    except (ValueError,TypeError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页条数须为1至200')
    _register(c)
    sql,params=ledger_sql(kind,start=start,end=end,all_dates=all_dates,supplier_id=supplier_id,search=search,status=status,payment_kind=payment_kind,charge_kind=charge_kind)
    totals=c.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents),0),COALESCE(SUM(paid_cents),0),COALESCE(SUM(charges_cents),0) FROM ("+sql+")",params).fetchone()
    total=totals[0];pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    raw=c.execute('SELECT id,payload,paid_cents,charges_cents,order_supplier_id,order_supplier_name FROM ('+sql+') ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?',[*params,page_size,(page-1)*page_size]).fetchall()
    import json
    rows=[]
    for r in raw:
        value=json.loads(r[1])
        if kind in ('payments','charges'):value.update(order_supplier_id=r[4] or '',order_supplier_name=r[5] or '')
        if kind=='charges':value.update(paid_cents=r[2],outstanding_cents=value['amount_cents']-r[2])
        if kind=='receipts':value.update(charges_cents=r[3],inventory_cost_cents=value['amount_cents']+r[3])
        rows.append(value)
    if kind=='receipts' and rows:
        ids=[r['id'] for r in rows];allocated={}
        for r in c.execute("SELECT payload FROM purchase_charges WHERE json_extract(payload,'$.receipt_id') IN ("+','.join('?' for _ in ids)+')',ids):
            for a in json.loads(r[0])['allocations']:allocated[a['material_entry_id']]=allocated.get(a['material_entry_id'],0)+a['amount_cents']
        warehouses=rc.warehouse_names(c)
        for r in rows:
            for l in r['lines']:
                l['charges_cents']=allocated.get(l['material_entry_id'],0);l['inventory_cost_cents']=l['amount_cents']+l['charges_cents']
                l['actual_unit_price']=purchasing.actual_price(l['inventory_cost_cents'],l['qty'])
                l['warehouse_name']=warehouses.get(l.get('warehouse_id'),'历史待确认库' if l['material_id']=='RM-SOY' else '公共辅料与包装库')
    summary={'count':total,'amount_cents':totals[1]}
    if kind=='receipts':summary.update(charges_cents=totals[3],inventory_cost_cents=totals[1]+totals[3])
    if kind=='charges':summary.update(paid_cents=totals[2],outstanding_cents=totals[1]-totals[2])
    return {'kind':kind,'rows':rows,'total':total,'page':page,'pages':pages,'page_size':page_size,'start':start,'end':end,'all_dates':bool(all_dates),'summary':summary}


def _month_text(value):
    value=_text(value,'采购月份',7)
    if value:
        parts=value.split('-')
        if len(parts)!=2 or len(parts[0])!=4 or len(parts[1])!=2 or not parts[0].isdigit() or not parts[1].isdigit() or not 1<=int(parts[1])<=12:
            raise ValueError('采购月份无效')
        rc.day(value+'-01')
    return value


def payables(c,*,month='',supplier_id='',search='',status='',page=1,page_size=50):
    """Goods payable list: SQL filters/totals/pages, overdue by earliest receipt due date."""
    month=_month_text(month);supplier_id=_text(supplier_id,'供应商');search=_text(search,'搜索内容');status=_text(status,'应付状态')
    if status and status not in ('未付清','已付清','已逾期'):raise ValueError('应付状态无效')
    try:page=int(page);page_size=int(page_size)
    except (TypeError,ValueError):raise ValueError('分页参数无效')
    if not 1<=page<=100000 or not 1<=page_size<=200:raise ValueError('页码须为1至100000，每页条数须为1至200')
    today=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    terms=[];params=[today]
    if month:terms.append("substr(business_date,1,7)=?");params.append(month)
    if supplier_id:terms.append('supplier_id=?');params.append(supplier_id)
    if search:
        terms.append("(instr(lower(id||' '||COALESCE(json_extract(payload,'$.supplier_name'),'')),lower(?))>0 OR EXISTS(SELECT 1 FROM json_each(payload,'$.lines') l WHERE instr(lower(COALESCE(json_extract(l.value,'$.material_name'),'')),lower(?))>0))")
        params.extend([search,search])
    sql=f"""WITH paid AS (
      SELECT json_extract(payload,'$.order_id') order_ref,SUM(CAST(json_extract(payload,'$.amount_cents') AS INTEGER)) paid
      FROM purchase_payments WHERE COALESCE(json_extract(payload,'$.charge_id'),'')='' AND COALESCE(json_extract(payload,'$.voided'),0)=0 GROUP BY order_ref),
    rec AS (
      SELECT json_extract(r.payload,'$.order_id') order_ref,json_extract(r.payload,'$.due_date') due_date,
        CAST(json_extract(r.payload,'$.amount_cents') AS INTEGER) amount,COALESCE(p.paid,0) paid,
        SUM(CAST(json_extract(r.payload,'$.amount_cents') AS INTEGER)) OVER
          (PARTITION BY json_extract(r.payload,'$.order_id') ORDER BY json_extract(r.payload,'$.due_date'),r.id) cum
      FROM purchase_receipts r LEFT JOIN paid p ON p.order_ref=json_extract(r.payload,'$.order_id')),
    base AS (
      SELECT o.id,o.payload,o.rowid rowid,{DATE} business_date,{SUPPLIER} supplier_id,
        COALESCE((SELECT SUM(amount) FROM rec WHERE order_ref=+o.id),0) received_cents,
        COALESCE((SELECT paid FROM paid WHERE order_ref=+o.id),0) paid_cents,
        COALESCE((SELECT SUM(CASE WHEN due_date<? THEN MAX(0,MIN(amount,cum-paid)) ELSE 0 END) FROM rec WHERE order_ref=+o.id),0) overdue_cents
      FROM purchase_orders o)
      SELECT id,payload,rowid,received_cents,paid_cents,received_cents-paid_cents outstanding_cents,overdue_cents
      FROM base WHERE received_cents>0"""
    if terms:sql+=' AND '+' AND '.join(terms)
    if status=='未付清':sql+=' AND outstanding_cents>0'
    elif status=='已付清':sql+=' AND outstanding_cents=0'
    elif status=='已逾期':sql+=' AND overdue_cents>0'
    totals=c.execute("SELECT COUNT(*),COALESCE(SUM(received_cents),0),COALESCE(SUM(paid_cents),0),COALESCE(SUM(outstanding_cents),0),COALESCE(SUM(overdue_cents),0) FROM ("+sql+")",params).fetchone()
    total=totals[0];pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    raw=c.execute('SELECT id,overdue_cents FROM ('+sql+') ORDER BY rowid DESC LIMIT ? OFFSET ?',[*params,page_size,(page-1)*page_size]).fetchall()
    ids=[r[0] for r in raw];overdue={r[0]:r[1] for r in raw}
    projected=purchasing.projection(c,order_ids=ids);by_id={r['id']:r for r in projected['orders']}
    rows=[]
    for i in ids:
        value=dict(by_id[i]);value['overdue_cents']=overdue.get(i,0);rows.append(value)
    return {'kind':'payables','rows':rows,'total':total,'page':page,'pages':pages,'page_size':page_size,'month':month,
      'summary':{'count':total,'received_cents':totals[1],'paid_cents':totals[2],'outstanding_cents':totals[3],'overdue_cents':totals[4]}}
