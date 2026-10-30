import erp_access
"""Customer statement snapshot; no mutation or automatic receipt confirmation."""
import json
import trade

def snapshot(c,cid,day,generated_at):
    customer=c.execute('SELECT id,name,route,legal_name,phone,opening_cents,opening_date FROM customers WHERE id=?',(cid,)).fetchone()
    if not customer:raise ValueError('客户不存在，请重新选择')
    orders=[o for r in c.execute('SELECT payload FROM orders') if (o:=json.loads(r[0]))['customer_id']==cid]
    def bill(o):
        credit=o.get('return_credit_cents',0);remaining=max(0,o['total_cents']-o['paid_cents']-credit-o.get('discount_cents',0)-o.get('rounding_cents',0))
        return {'id':o['id'],'business_date':o['business_date'],'version':o['version'],'state':o['state'],'total_cents':o['total_cents'],'paid_cents':o['paid_cents'],'credit_cents':credit,'discount_cents':o.get('discount_cents',0),'rounding_cents':o.get('rounding_cents',0),'remaining_cents':remaining,'settled_at':(o.get('settlement') or {}).get('at'),'reviewed_at':(o.get('review') or {}).get('at'),'lines':[{'product_name':l['product_name'],'product_id':l['product_id'],'actual_qty':l['actual_qty'],'unit':l['unit'],'billing_unit':l.get('billing_unit','公斤' if l['unit']=='筐' else '包'),'bill_qty':l['bill_qty'],'price':l['price'],'amount_cents':l['amount_cents'],'settlement_mode':l.get('settlement_mode','')} for l in o['lines']]}
    current=[bill(o) for o in orders if o['business_date']==day and o['state'] in ('ready','reviewed')]
    current.sort(key=lambda o:o['id'])
    history=[bill(o) for o in orders if o['business_date']<day and o['state']=='reviewed' and o['total_cents']>o['paid_cents']+o.get('return_credit_cents',0)+o.get('discount_cents',0)+o.get('rounding_cents',0)]
    history.sort(key=lambda o:(o['business_date'],o['id']))
    old_pending=[bill(o) for o in orders if o['business_date']<day and o['state']=='ready']
    pending=[o for o in current if o['state']=='ready'];posted=[o for o in current if o['state']=='reviewed']
    totals={'current_sales_cents':sum(o['total_cents'] for o in posted),'current_paid_cents':sum(o['paid_cents'] for o in posted),'current_credit_cents':sum(o['credit_cents'] for o in posted),'current_remaining_cents':sum(o['remaining_cents'] for o in posted),'history_remaining_cents':sum(o['remaining_cents'] for o in history),'pending_cents':sum(o['total_cents'] for o in pending),'historical_pending_cents':sum(o['total_cents'] for o in old_pending)}
    totals['current_discount_cents']=sum(o['discount_cents'] for o in posted)
    totals['current_rounding_cents']=sum(o['rounding_cents'] for o in posted)
    opening_cents=int(customer['opening_cents'] or 0);opening_day=(customer['opening_date'] or '')
    opening=None
    if opening_cents>0 and (not opening_day or opening_day<=day):
        opening={'business_date':opening_day or '日期未登记','amount_cents':opening_cents,'remaining_cents':opening_cents}
    totals['opening_cents']=opening_cents if opening else 0
    totals['payable_cents']=totals['current_remaining_cents']+totals['history_remaining_cents']+totals['opening_cents']
    returns=[]
    for row in c.execute('SELECT payload FROM sales_returns'):
        r=json.loads(row[0]);f=r.get('finance')
        if r['customer_id']!=cid or r.get('voided') or r['received_date']>day:continue
        returns.append({'id':r['id'],'received_date':r['received_date'],'product_name':r['product_name'],'net_kg':r['net_kg'],'account_qty':f.get('account_qty') if f else None,'billing_unit':f.get('billing_unit') if f else '公斤','price':f.get('original_price') if f else None,'amount_cents':f.get('amount_cents') if f else None,'state':f.get('state') if f else 'unaccounted'})
    result={'customer':dict(customer),'business_date':day,'generated_at':generated_at,'opening':opening,'balance_basis':'应付合计为期初应收（期初日期不晚于所选日期）加上所选日期及以前账单的当前未收金额，截至图片生成时','current':current,'history':history,'historical_pending':old_pending,'returns':returns,'totals':totals,'unsettled_count':sum(o['business_date']==day and o['state'] not in ('ready','reviewed') for o in orders)}
    for result_key,meta_key in [('issuer_profile','statement_supplier'),('buyer_profile','statement_buyer_'+cid)]:
        row=c.execute('SELECT value FROM meta WHERE key=?',(meta_key,)).fetchone();result[result_key]=json.loads(row[0]) if row else {}
    result['company']=__import__('company').current(c)
    if result['company']['version'] or not result['issuer_profile']:result['issuer_profile']={**result['issuer_profile'],'name':result['company']['name'],'phone':result['company']['phone']}
    result['crates']=trade.customer_crates(c,cid,day)
    result['delivery_feedback']=[r for r in trade.records(c,'feedback') if r['customer_id']==cid and r['business_date']<=day]
    result['source_fingerprint']=fingerprint(result)
    return result


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def fingerprint(value):
    import hashlib
    return hashlib.sha256(canonical({k:v for k,v in value.items() if k not in ('generated_at','issuer_profile','buyer_profile','source_fingerprint')}).encode()).hexdigest()


def issue(c,body,role,now,audit):
    import hashlib,secrets
    from datetime import date
    erp_access.require_role(role,'finance.statement-issue')
    def text(key,maximum=120,required=True):
        value=body.get(key,'')
        if not isinstance(value,str) or len(value)>maximum or required and not value.strip():raise ValueError('请核对并填写'+{'seller_name':'供货方正式名称','buyer_name':'购货方正式名称或姓名','request_key':'出具请求编号'}.get(key,key))
        return value.strip()
    key=text('request_key',80);cid=text('customer_id',40);day=text('business_date',10)
    customer=c.execute('SELECT name,legal_name FROM customers WHERE id=?',(cid,)).fetchone()
    if not customer:raise ValueError('客户不存在')
    if not body.get('buyer_name'):body={**body,'buyer_name':customer['legal_name'] or customer['name']}
    operator_id=body.get('operator_user_id')
    operator_row=None
    if operator_id:
        operator_row=c.execute('SELECT * FROM operator_users WHERE id=? AND active=1',(operator_id,)).fetchone()
        if not operator_row:raise ValueError('所选经办人不存在或已停用，请重新选择')
        if 'operator_version' in body and body['operator_version']!=operator_row['version']:raise ValueError('经办人资料已修改，请重新读取后核对')
        body={**body,'operator':operator_row['name']}
    if date.fromisoformat(day).isoformat()!=day:raise ValueError('业务日期无效')
    seller=text('seller_name');buyer=text('buyer_name');phone=text('seller_phone',40,False)
    operator=text('operator',80);note=text('note',500,False)
    if body.get('identity_checked') is not True:raise ValueError('请核对双方主体和账款范围后勾选出具确认')
    request={'customer_id':cid,'business_date':day,'seller_name':seller,'buyer_name':buyer,'seller_phone':phone,'operator':operator,'operator_user_id':operator_id,'note':note,'source_fingerprint':body.get('source_fingerprint')}
    prior=c.execute('SELECT * FROM statement_documents WHERE request_key=?',(key,)).fetchone()
    if prior:
        value=get_document(c,prior['id'])
        if value.get('issue_request')!=request:raise ValueError('出具请求已使用，请重新预览后出具')
        return value
    identity=__import__('company').current(c)
    if identity['version'] and (seller!=identity['name'] or phone!=identity['phone']):raise ValueError('供货方与当前公司信息不一致，请重新读取预览后出具')
    s=snapshot(c,cid,day,now())
    if body.get('source_fingerprint')!=fingerprint(s):raise ValueError('账单、收款或退货数据已有变化，请重新读取预览后核对出具')
    if not s['current'] and not s['history'] and not s['historical_pending']:raise ValueError('当前没有可出具的已算票账款，请先完成会计算票')
    duplicate=[]
    for document_id,payload in c.execute("SELECT id,payload FROM statement_documents WHERE customer_id=? AND business_date=? AND json_extract(payload,'$.issue_request.source_fingerprint')=?",(cid,day,request['source_fingerprint'])).fetchall():
        old_request=json.loads(payload).get('issue_request') or {}
        if old_request.get('seller_name')==seller and old_request.get('seller_phone')==phone:duplicate.append(document_id)
    if duplicate:raise ValueError('该客户在本业务日、同一数据版本已出具对账单 '+duplicate[0]+'；请勿重复签发，确需重出请先更正数据后重新预览')
    doc_id='DZ-'+day.replace('-','')+'-'+secrets.token_hex(5).upper()
    epoch=c.execute("SELECT value FROM meta WHERE key='business_data_epoch'").fetchone()
    s.update(document_id=doc_id,source_data_epoch=epoch[0] if epoch else '0',document_state='待客户确认',issue_request=request,parties={'seller_name':seller,'seller_phone':phone,'buyer_name':buyer,'operator':operator,'operator_user_id':operator_id,'operator_version':operator_row['version'] if operator_row else None},note=note,issued_by=role)
    s['document_template_version']='0.20'
    s['confirmation_terms']={
        'feedback':'请核对账款，无误请回复“对”；有异议请于收到后 3 日内提出。',
        'no_silence':'逾期未提出异议的，视为确认本单金额。',
        'scope':'仅含已复核账款；金额截至本单生成时。',
        'retention':'请保留原始对账消息及客户回复。'}
    s['wechat_text']=wechat_text(s)
    # Profiles prefill later drafts; the issued version retains its own immutable copy.
    s.pop('issuer_profile',None);s.pop('buyer_profile',None)
    raw=canonical(s);digest=hashlib.sha256(raw.encode()).hexdigest()
    c.execute('INSERT INTO statement_documents VALUES(?,?,?,?,?,?,?)',(doc_id,key,cid,day,s['generated_at'],raw,digest))
    for profile_key,value in [('statement_supplier',{'name':seller,'phone':phone,'operator':operator}),('statement_buyer_'+cid,{'name':buyer})]:
        c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(profile_key,canonical(value)))
    audit(c,role,'出具货款对账确认单（待客户确认）',doc_id,None,{'customer_id':cid,'business_date':day,'payable_cents':s['totals']['payable_cents'],'content_hash':digest})
    return {**s,'content_hash':digest}


def get_document(c,doc_id):
    import hashlib
    row=c.execute('SELECT payload,content_hash FROM statement_documents WHERE id=?',(doc_id,)).fetchone()
    if not row:raise ValueError('归档单据不存在')
    if hashlib.sha256(row['payload'].encode()).hexdigest()!=row['content_hash']:raise ValueError('归档内容校验不一致，请核对数据库备份')
    value={**json.loads(row['payload']),'content_hash':row['content_hash']}
    import order_corrections
    void=order_corrections.void_info(c,doc_id)
    if void:value.update(voided=True,void_info=void,document_state='已作废',wechat_text='本结算单已作废，原因：'+void['reason']+'。请以重新出具的结算单为准。')
    return value


def latest_status(c,cid,day,generated_at):
    import order_corrections
    for row in c.execute('SELECT id,payload FROM statement_documents WHERE customer_id=? AND business_date=? ORDER BY issued_at DESC,rowid DESC',(cid,day)):
        if order_corrections.void_info(c,row['id']):continue
        payload=json.loads(row['payload'])
        return {'document_id':row['id'],'issued_at':payload.get('generated_at',''),'stale':payload.get('source_fingerprint')!=fingerprint(snapshot(c,cid,day,generated_at))}
    return {'document_id':'','issued_at':'','stale':True}


def wechat_text(s):
    from decimal import Decimal
    def yuan(value):return format(Decimal(value)/100,'.2f')
    p=s.get('parties') or {};t=s['totals']
    lines=[p.get('seller_name','供货方'),*__import__('company').text_lines(s.get('company')),f"【{s['business_date']} 客户对账】",'客户：'+p.get('buyer_name',s['customer']['name']),'单号：'+s.get('document_id','未出具')]
    posted=[o for o in s['current'] if o['state']=='reviewed']
    if posted:
        lines+=['','当日明细：']
        for o in posted:
            for l in o['lines']:
                if l['amount_cents']==0:continue
                lines.append(f"{l['product_name']} {l['bill_qty']}{l['billing_unit']} × {l['price']}元 = {yuan(l['amount_cents'])}元")
    if s.get('crates',{}).get('rows'):
        lines+=['','尚欠周转筐（截至 '+s['crates']['as_of']+'）：']
        for r in s['crates']['rows']:lines.append(f"{r['asset_name']}：尚欠 {r['balance_qty']} 个（累计发出 {r['shipped_qty']}，累计回框 {r['returned_qty']}，当日回框 {r['today_returned_qty']}，期初 {r['opening_qty']}）")
    if s.get('opening'):lines+=['',f"期初应收（{s['opening']['business_date']}）：{yuan(s['opening']['amount_cents'])}元"]
    lines+=['',f"当日货款：{yuan(t['current_sales_cents'])}元",f"当日账单已收：{yuan(t['current_paid_cents'])}元",f"当日退货已抵：{yuan(t['current_credit_cents'])}元",f"当日折扣：{yuan(t.get('current_discount_cents',0))}元",f"当日抹零：{yuan(t.get('current_rounding_cents',0))}元",f"历史未收：{yuan(t['history_remaining_cents'])}元"]
    for o in s['history']:lines.append(f"  {o['business_date']} / {o['id']}：尚欠{yuan(o['remaining_cents'])}元")
    pending_cents=int(t.get('pending_cents',0));historical_pending=int(t.get('historical_pending_cents',0))
    lines+=['',f"尚欠金额：{yuan(t['payable_cents'])}元"]
    if pending_cents or historical_pending:
        # 待复核账单尚未经会计复核，不计入尚欠；需在微信里说清楚，避免客户误以为已无欠款。
        parts=[f"当日待复核 {yuan(pending_cents)}元"] if pending_cents else []
        if historical_pending:parts.append(f"历史待复核 {yuan(historical_pending)}元")
        lines.append('待复核账单：'+'，'.join(parts)+'（复核后才计入尚欠金额）')
    pending=t['pending_cents']+t['historical_pending_cents']
    if pending:lines.append(f"另有待复核{yuan(pending)}元，未计入上述欠款。")
    lines+=['金额截至本单生成时。','请核对，无误请回复“对”；有异议请于收到后 3 日内提出，逾期视为确认。']
    return '\n'.join(lines)


def batch_preview(c,day,generated_at):
    entries=[];supplier={}
    for row in c.execute('SELECT id,name,legal_name,region,route FROM customers ORDER BY region,route,id').fetchall():
        s=snapshot(c,row['id'],day,generated_at);supplier=s['issuer_profile']
        if not s['current'] and not s['history'] and not s['historical_pending'] and not s['opening']:continue
        entries.append({'customer_id':row['id'],'name':row['name'],'buyer_name':row['legal_name'] or row['name'],'region':row['region'],'market':row['route'],'source_fingerprint':s['source_fingerprint'],'current_cents':s['totals']['current_sales_cents'],'history_cents':s['totals']['history_remaining_cents'],'opening_cents':s['totals']['opening_cents'],'payable_cents':s['totals']['payable_cents'],'pending_cents':s['totals']['pending_cents']+s['totals']['historical_pending_cents']})
    return {'business_date':day,'customers':entries,'supplier':supplier}


def issue_batch(c,body,role,now,audit):
    erp_access.require_role(role,'finance.statement-issue')
    rows=body.get('items')
    if not isinstance(rows,list) or not 1<=len(rows)<=200:raise ValueError('请选择1至200位客户')
    if not all(isinstance(r,dict) and isinstance(r.get('customer_id'),str) and r['customer_id'] for r in rows):raise ValueError('客户列表无效')
    if len({r['customer_id'] for r in rows})!=len(rows):raise ValueError('客户重复，请重新选择')
    key=body.get('request_key')
    if not isinstance(key,str) or not 16<=len(key)<=40:raise ValueError('批量请求编号无效')
    supplier=c.execute("SELECT value FROM meta WHERE key='statement_supplier'").fetchone();supplier=json.loads(supplier[0]) if supplier else {}
    user_id=body.get('operator_user_id') or 'OP-CASHIER'
    docs=[]
    for row in rows:
        child={**body,'request_key':key+':'+row['customer_id'],'customer_id':row['customer_id'],'source_fingerprint':row.get('source_fingerprint'),'buyer_name':'','operator_user_id':user_id,'seller_name':body.get('seller_name') or supplier.get('name',''),'seller_phone':body.get('seller_phone',supplier.get('phone',''))}
        try:d=issue(c,child,role,now,audit)
        except ValueError as e:raise ValueError(row['customer_id']+'：'+str(e)) from e
        docs.append({'id':d['document_id'],'customer_id':d['customer']['id'],'buyer_name':d['parties']['buyer_name'],'operator':d['parties']['operator'],'payable_cents':d['totals']['payable_cents']})
    return {'documents':docs,'count':len(docs)}
