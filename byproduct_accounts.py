"""Customer identities and immutable, customer-facing byproduct statements."""
import calendar
import csv
import hashlib
import io
import json
import re
import secrets
from decimal import Decimal

import erp_access
import resources_costs as rc
import statements


def valid_month(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}',value):raise ValueError('结算月份无效')
    rc.day(value+'-01');return value


def customer(c,cid):
    row=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone()
    if not row:raise ValueError('请选择已登记的豆渣客户')
    return dict(row)


def sale_customer(c,cid):
    value=customer(c,cid)
    if value['business_kind'] not in ('byproduct','both'):raise ValueError('该客户未启用豆渣业务，请先在客户档案中调整业务类型')
    return value


def legacy_customer(c,name,now,audit):
    """Compatibility for the old admin setting; never merge with a sales namesake."""
    name=rc.text(name,'固定买家',100)
    matches=c.execute("SELECT * FROM customers WHERE name=? AND business_kind='byproduct'",(name,)).fetchall()
    if len(matches)==1:return dict(matches[0])
    numbers=[int(r[0][1:]) for r in c.execute('SELECT id FROM customers') if re.fullmatch(r'C[0-9]+',r[0])]
    cid='C'+str(max(numbers,default=0)+1).zfill(3)
    c.execute("INSERT INTO customers(id,name,route,note,delivery_method,legal_name,business_kind) VALUES(?,?,?,'','pickup',?,'byproduct')",(cid,name,'豆渣自取',name))
    value=customer(c,cid);audit(c,'管理员','建立豆渣客户档案',cid,None,value)
    return value


def receivables(c):
    clients={r['id']:dict(r) for r in c.execute('SELECT * FROM customers')}
    result=[]
    for value in rc.rows(c,'byproduct_sales'):
        if value.get('voided'):continue
        r=rc.byproduct_business_record(value);client=clients.get(r.get('customer_id'),{})
        result.append({**r,'customer_name':client.get('name') or r['buyer'],
                       'outstanding_cents':max(0,r['amount_cents']-r['received_cents'])})
    return result


def summary(c,month):
    """Bounded initialization payload: month totals per customer plus all-time outstanding."""
    valid_month(month)
    amount="COALESCE(CAST(json_extract(payload,'$.amount_cents') AS INTEGER),0)"
    received="COALESCE(CAST(json_extract(payload,'$.received_cents') AS INTEGER),0)"
    qty=("COALESCE(CAST(ROUND(CAST(COALESCE(json_extract(payload,'$.qty'),0) AS REAL)*1000) AS INTEGER),0)"
         "*CASE WHEN COALESCE(json_extract(payload,'$.unit'),'公斤')='吨' THEN 1000 ELSE 1 END")
    active="COALESCE(json_extract(payload,'$.voided'),0)=0"
    clients={r['id']:dict(r) for r in c.execute('SELECT id,name,business_kind FROM customers')}
    monthly={}
    for cid,sales,paid,milli in c.execute(
            "SELECT COALESCE(json_extract(payload,'$.customer_id'),''),COALESCE(SUM("+amount+"),0),COALESCE(SUM("+received+"),0),COALESCE(SUM("+qty+"),0) "
            "FROM byproduct_sales WHERE "+active+" AND substr(json_extract(payload,'$.business_date'),1,7)=? GROUP BY 1",(month,)):
        monthly[cid]=(sales,paid,milli)
    debts={cid:owed for cid,owed in c.execute(
        "SELECT COALESCE(json_extract(payload,'$.customer_id'),''),COALESCE(SUM("+amount+"-"+received+"),0) "
        "FROM byproduct_sales WHERE "+active+" AND "+amount+">"+received+" GROUP BY 1")}
    customers=[]
    for cid,client in clients.items():
        if client['business_kind'] not in ('byproduct','both'):continue
        sales,paid,milli=monthly.get(cid,(0,0,0))
        customers.append({'customer_id':cid,'name':client['name'],'business_kind':client['business_kind'],
                          'month_cents':sales,'month_received_cents':paid,'month_qty_kg':str(Decimal(milli)/1000),
                          'outstanding_cents':max(0,debts.get(cid,0))})
    customers.sort(key=lambda r:(r['name'],r['customer_id']))
    total=c.execute("SELECT COUNT(*) FROM byproduct_sales WHERE "+active+" AND "+amount+">"+received).fetchone()[0]
    limit=500
    outstanding=[]
    for (payload,) in c.execute("SELECT payload FROM byproduct_sales WHERE "+active+" AND "+amount+">"+received+" "
                                 "ORDER BY json_extract(payload,'$.business_date'),id LIMIT ?",(limit,)):
        value=rc.byproduct_business_record(json.loads(payload));client=clients.get(value.get('customer_id'),{})
        outstanding.append({'id':value['id'],'business_date':value['business_date'],'customer_id':value.get('customer_id',''),
                            'customer_name':client.get('name') or value['buyer'],'buyer':value['buyer'],
                            'amount_cents':value['amount_cents'],'received_cents':value['received_cents'],
                            'outstanding_cents':max(0,value['amount_cents']-value['received_cents']),'version':value.get('version',1)})
    return {'month':month,'customers':customers,
            'month_cents':sum(v[0] for v in monthly.values()),'month_received_cents':sum(v[1] for v in monthly.values()),
            'month_qty_kg':str(Decimal(sum(v[2] for v in monthly.values()))/1000),
            'outstanding_cents':sum(max(0,v) for v in debts.values()),
            'outstanding':outstanding,'outstanding_total':total,'limit':limit}


def sales(c,cid):
    """Active sales for one customer, used only by the legacy customer statement dialog."""
    customer(c,cid)
    result=[]
    for (payload,) in c.execute("SELECT payload FROM byproduct_sales WHERE json_extract(payload,'$.customer_id')=? "
                                 "ORDER BY json_extract(payload,'$.business_date'),id",(cid,)):
        value=rc.byproduct_business_record(json.loads(payload))
        if not value.get('voided'):result.append(value)
    return result


def snapshot(c,cid,month,generated_at):
    valid_month(month);client=customer(c,cid)
    end=month+'-%02d'%calendar.monthrange(int(month[:4]),int(month[5:]))[1]
    rows=sorted((r for r in receivables(c) if r.get('customer_id')==cid and r['business_date']<=end),key=lambda r:(r['business_date'],r['id']))
    current=[r for r in rows if r['business_date'].startswith(month)]
    history=[r for r in rows if r['business_date'][:7]<month and r['outstanding_cents']>0]
    def bill(r):
        return {k:r[k] for k in ('id','business_date','qty','unit','price','amount_cents','received_cents','outstanding_cents')}
    details=[]
    for r in current:
        daily=r.get('daily_rows') or []
        valid_daily=bool(daily) and sum((Decimal(d['qty']) for d in daily),Decimal(0))==Decimal(r['qty']) and sum(d['amount_cents'] for d in daily)==r['amount_cents']
        if valid_daily:
            details.extend({'date':d['date'],'product_name':'豆渣','sale_id':r['id'],'qty':d['qty'],'unit':r['unit'],'price':r['price'],'amount_cents':d['amount_cents']} for d in daily)
        else:details.append({'date':r['business_date'],'product_name':'豆渣','sale_id':r['id'],'qty':r['qty'],'unit':r['unit'],'price':r['price'],'amount_cents':r['amount_cents']})
    details.sort(key=lambda d:(d['date'],d['sale_id']))
    indexed={}
    for r in details:indexed.setdefault(r['date'],[]).append({**r,'status':'已入账'})
    details=[]
    for day in range(1,int(end[-2:])+1):
        when=month+'-%02d'%day
        details.extend(indexed.get(when) or [{'date':when,'product_name':'豆渣','sale_id':'','qty':None,'unit':'公斤','price':None,'amount_cents':0,'status':'无已入账记录'}])
    totals={'current_sales_cents':sum(r['amount_cents'] for r in current),'current_paid_cents':sum(r['received_cents'] for r in current),
            'current_remaining_cents':sum(r['outstanding_cents'] for r in current),'history_remaining_cents':sum(r['outstanding_cents'] for r in history)}
    totals['payable_cents']=totals['current_remaining_cents']+totals['history_remaining_cents']
    issuer=c.execute("SELECT value FROM meta WHERE key='statement_supplier'").fetchone()
    value={'kind':'byproduct','month':month,'period_start':month+'-01','period_end':end,'business_date':end,'generated_at':generated_at,
           'customer':{k:client[k] for k in ('id','name','legal_name','phone','route')},
           'details':details,'current':[bill(r) for r in current],'history':[bill(r) for r in history],
           'totals':totals,'source_sale_ids':[r['id'] for r in current+history],
           'source_versions':{r['id']:r['version'] for r in current+history},
           'balance_basis':'仅含豆渣已入账货款；本月账款及此前未清账款的当前余额，金额截至本单生成时。',
           'issuer_profile':json.loads(issuer[0]) if issuer else {}}
    value['company']=__import__('company').current(c)
    if value['company']['version'] or not value['issuer_profile']:value['issuer_profile']={**value['issuer_profile'],'name':value['company']['name'],'phone':value['company']['phone']}
    value['source_fingerprint']=statements.fingerprint(value)
    return value


def wechat_text(s):
    money=lambda n:format(Decimal(n)/100,'.2f')
    p=s['parties'];t=s['totals']
    lines=[p['seller_name'],*__import__('company').text_lines(s.get('company')),'豆渣结算单','结算期间：'+s['period_start']+' 至 '+s['period_end'],'出具日期：'+s['generated_at'][:10],'客户：'+p['buyer_name'],'单号：'+s['document_id'],
           '本月货款：'+money(t['current_sales_cents'])+'元','本月账款已收：'+money(t['current_paid_cents'])+'元',
           '历史未收：'+money(t['history_remaining_cents'])+'元','尚欠合计：'+money(t['payable_cents'])+'元',
           '金额截至本单生成时，请核对明细。无误请针对本条回复“无误”；有差异请告知。']
    return '\n'.join(lines)


def issue(c,b,role,now,audit):
    erp_access.require_role(role,'finance.statement-issue')
    key=rc.text(b.get('request_key'),'出具请求编号',80);cid=rc.text(b.get('customer_id'),'客户编号',40)
    month=valid_month(b.get('month'));operator=c.execute('SELECT * FROM operator_users WHERE id=? AND active=1',(b.get('operator_user_id'),)).fetchone()
    if not operator or b.get('operator_version')!=operator['version']:raise ValueError('请重新选择有效经办人并核对版本')
    seller=rc.text(b.get('seller_name'),'供货方正式名称',120);phone=rc.text(b.get('seller_phone',''),'供货方电话',40,False)
    buyer=rc.text(b.get('buyer_name'),'客户结算名称',120);note=rc.text(b.get('note',''),'结算单备注',500,False)
    if b.get('identity_checked') is not True:raise ValueError('请先核对客户、月份和金额后勾选出具确认')
    request={k:b.get(k) for k in ('customer_id','month','seller_name','seller_phone','buyer_name','operator_user_id','operator_version','note','source_fingerprint')}
    prior=c.execute('SELECT id FROM byproduct_statements WHERE request_key=?',(key,)).fetchone()
    if prior:
        doc=get_document(c,prior[0])
        if doc.get('issue_request')!=request:raise ValueError('出具请求已使用，请重新读取后出具')
        return doc
    identity=__import__('company').current(c)
    if identity['version'] and (seller!=identity['name'] or phone!=identity['phone']):raise ValueError('供货方与当前公司信息不一致，请重新读取预览后出具')
    s=snapshot(c,cid,month,now())
    if s['source_fingerprint']!=b.get('source_fingerprint'):raise ValueError('客户档案、货款或收款已有变化，请重新预览后出具')
    if not s['current'] and not s['history']:raise ValueError('所选客户和月份没有已入账豆渣账款，不能出具结算单')
    doc_id='BZ-'+month.replace('-','')+'-'+secrets.token_hex(5).upper()
    s.update(document_id=doc_id,document_state='待客户确认',document_template_version='byproduct-1',
             parties={'seller_name':seller,'seller_phone':phone,'buyer_name':buyer,'operator':operator['name']},
             note=note,issue_request=request,issued_by=role)
    s.pop('issuer_profile',None);s['wechat_text']=wechat_text(s)
    raw=statements.canonical(s);digest=hashlib.sha256(raw.encode()).hexdigest()
    c.execute('INSERT INTO byproduct_statements VALUES(?,?,?,?,?,?)',(doc_id,key,cid,month,raw,digest))
    c.execute("INSERT INTO meta VALUES('statement_supplier',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(statements.canonical({'name':seller,'phone':phone,'operator':operator['name']}),))
    audit(c,role,'出具豆渣结算单（待客户确认）',doc_id,None,{'customer_id':cid,'month':month,'payable_cents':s['totals']['payable_cents'],'content_hash':digest})
    return {**s,'content_hash':digest}


def get_document(c,doc_id):
    row=c.execute('SELECT payload,content_hash FROM byproduct_statements WHERE id=?',(doc_id,)).fetchone()
    if not row:raise ValueError('豆渣结算单不存在')
    if hashlib.sha256(row[0].encode()).hexdigest()!=row[1]:raise ValueError('豆渣归档单据内容校验不一致')
    s={**json.loads(row[0]),'content_hash':row[1]}
    for rid in s['source_sale_ids']:
        sale=c.execute('SELECT payload FROM byproduct_sales WHERE id=?',(rid,)).fetchone()
        record=json.loads(sale[0]) if sale else {}
        if not sale or record.get('voided') or record.get('last_void_version',0)>s['source_versions'].get(rid,0):
            s.update(voided=True,void_info={'reason':'来源豆渣收入已作废，请重新出具结算单','voided_at':''},wechat_text='来源收入已作废，请以重新出具的结算单为准。')
            break
    return s


def documents(c,cid):
    return [{'id':r[0],'month':r[1],'issued_at':(s:=get_document(c,r[0]))['generated_at'],'voided':s.get('voided',False)} for r in c.execute('SELECT id,month FROM byproduct_statements WHERE customer_id=? ORDER BY rowid DESC',(cid,))]


def statement_csv(s):
    def safe(v):
        text=str(v);return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    money=lambda n:format(Decimal(n)/100,'.2f')
    output=io.StringIO();w=csv.writer(output)
    w.writerow(['豆渣结算单',safe(s['document_id'])]);w.writerow(['结算开始日期',s['period_start'],'结算结束日期',s['period_end']]);w.writerow(['出具日期',s['generated_at'][:10]])
    w.writerow(['供货方',safe(s['parties']['seller_name']),'客户',safe(s['parties']['buyer_name'])])
    w.writerow(['日期','产品名称','收入单号','数量','单位','单价（元）','金额（元）','说明'])
    for r in s['details']:w.writerow([r['date'],r['product_name'],safe(r['sale_id']),r['qty'] if r['qty'] is not None else '—',r['unit'],r['price'] if r['price'] is not None else '—',money(r['amount_cents']),r['status']])
    w.writerow(['历史未收明细']);w.writerow(['日期','收入单号','原额（元）','已收（元）','未收（元）'])
    for r in s['history']:w.writerow([r['business_date'],safe(r['id']),money(r['amount_cents']),money(r['received_cents']),money(r['outstanding_cents'])])
    for label,key in [('本月货款','current_sales_cents'),('本月账款已收','current_paid_cents'),('本月未收','current_remaining_cents'),('历史未收','history_remaining_cents'),('尚欠合计','payable_cents')]:w.writerow([label,money(s['totals'][key])])
    w.writerow([s['balance_basis']]);w.writerow(['生成时间',s['generated_at']]);w.writerow(['状态','已作废，不得用于结算' if s.get('voided') else '待客户确认'])
    return ('\ufeff'+output.getvalue()).encode()
