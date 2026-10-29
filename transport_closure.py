"""Transport operations, provider quotes and reversible unpaid settlements.
All writes share the caller transaction. Legacy records remain unchanged.
"""
import calendar,copy,hashlib,json,secrets
from decimal import Decimal
import erp_access as access,expense_parties as parties,resources_costs as rc

PERMISSIONS={'transport-sync':'delivery.schedule','transport-provider':'delivery.schedule','transport-provider-status':'delivery.schedule','transport-quote':'costs.write','transport-quote-delete':'costs.write','transport-task':'costs.write','transport-task-void':'costs.write','transport-price':'costs.write','transport-reopen':'costs.write'}
QUOTE_KEY='transport_provider_quotes_v1'
TASK_TYPES={'delivery':'配送','crate':'收框','tofu':'冻豆腐','other':'其他临时'}
TASK_KINDS=tuple(TASK_TYPES)

def providers(c):
    fields=('id','name','phone','note','active','version','updated_at')
    return [{k:p.get(k,'') for k in fields} for p in parties.catalog(c) if p['kind']=='logistics']

def regions(c):
    rows=c.execute("SELECT region FROM customers WHERE TRIM(COALESCE(region,''))<>'' UNION SELECT city FROM delivery_markets WHERE TRIM(COALESCE(city,''))<>''").fetchall()
    return sorted({str(r[0]).strip() for r in rows if str(r[0]).strip()})
def provider(c,pid,active=True):
    p=next((p for p in parties.catalog(c) if p['id']==pid and p['kind']=='logistics' and (p['active'] or not active)),None)
    if not p:raise ValueError('请选择有效配送服务商，须使用运输服务收款方档案')
    return p

def quotes(c):
    r=c.execute('SELECT value FROM meta WHERE key=?',(QUOTE_KEY,)).fetchone();return json.loads(r[0]) if r else []
def quote(c,pid,area,day,vehicle='',task='delivery'):
    rows=[q for q in quotes(c) if q['provider_id']==pid and q['area']==area and q['effective_date']<=day and q.get('task','delivery')==task and q.get('mode','trip')=='trip']
    exact=[q for q in rows if q.get('vehicle','')==vehicle] or [q for q in rows if not q.get('vehicle')]
    return max(exact,key=lambda q:q['effective_date']) if exact else None

def contract(c,pid,area,day):
    rows=[q for q in quotes(c) if q['provider_id']==pid and q['area']==area and q['effective_date']<=day and q.get('mode')=='monthly']
    return max(rows,key=lambda q:q['effective_date']) if rows else None

def month_last(month):return month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:]))[1])

def monthly_charges(c,month,pid=''):
    last=month_last(month);latest={}
    for q in quotes(c):
        if q.get('mode')!='monthly' or q.get('effective_date','')>last:continue
        if pid and q['provider_id']!=pid:continue
        key=(q['provider_id'],q['area']);cur=latest.get(key)
        if not cur or q['effective_date']>=cur['effective_date']:latest[key]=q
    return [{'id':q['id'],'kind':'transport-contract','provider_id':q['provider_id'],'partner':q.get('provider_name',''),'area':q['area'],'business_date':last,'month':month,'task':'delivery','mode':'monthly','amount_cents':q.get('amount_cents',0)} for q in latest.values()]

def tasks(c,month,pid=''):
    import trade
    return [t for t in trade.records(c,'transport-task') if not t.get('voided') and t['business_date'].startswith(month) and (not pid or t.get('provider_id')==pid)]

def order_market(plan,o,customers,market_names):
    mid=(plan.get('order_markets') or {}).get(o['id'])
    if mid:return mid
    customer=customers.get(o.get('customer_id'),{})
    return customer.get('market_id') or market_names.get(customer.get('route') or o.get('route',''),'')

def own_orders(c,plan,tid):
    import trade
    assigned={a['market_id']:a.get('trip_id') for a in plan.get('assignments',[])}
    customers={r['id']:dict(r) for r in c.execute('SELECT id,market_id,route FROM customers')}
    market_names={r['name']:r['id'] for r in c.execute('SELECT id,name FROM delivery_markets')}
    return [json.loads(r[0]) for r in c.execute("SELECT payload FROM orders WHERE json_extract(payload,'$.business_date')=?",(plan['business_date'],)) if (lambda o:o.get('delivery_method')!='pickup' and assigned.get(order_market(plan,o,customers,market_names))==tid and any(Decimal(l.get('actual_qty') or '0')>0 for l in o['lines']))(json.loads(r[0]))]

def unplanned(c,day):
    if not c.execute('SELECT 1 FROM dispatch_plans WHERE business_date=?',(day,)).fetchone():return []
    plan=plan_for(c,day)
    assigned={a['market_id']:a.get('trip_id') for a in plan.get('assignments',[]) if a.get('trip_id')}
    customers={r['id']:dict(r) for r in c.execute('SELECT id,market_id,route FROM customers')}
    market_names={r['name']:r['id'] for r in c.execute('SELECT id,name FROM delivery_markets')}
    missing=[]
    for (payload,) in c.execute("SELECT payload FROM orders WHERE json_extract(payload,'$.business_date')=?",(day,)):
        o=json.loads(payload)
        if o.get('delivery_method')=='pickup' or not any(Decimal(l.get('actual_qty') or '0')>0 for l in o['lines']):continue
        if assigned.get(order_market(plan,o,customers,market_names)) not in {t['id'] for t in plan['trips']}:missing.append(o['id'])
    return missing

def source(c,plan,tid):
    rows=own_orders(c,plan,tid)
    return sorted([{'order_id':o['id'],'customer_id':o['customer_id'],'lines':sorted([{'product_id':l['product_id'],'actual_qty':l['actual_qty']} for l in o['lines'] if Decimal(l['actual_qty'])>0],key=lambda l:l['product_id'])} for o in rows],key=lambda o:o['order_id'])

def stamp(value):return hashlib.sha256(rc.dump(value).encode()).hexdigest()
def plan_for(c,day):
    row=c.execute('SELECT payload FROM dispatch_plans WHERE business_date=?',(day,)).fetchone();return json.loads(row[0]) if row else {'business_date':day,'trips':[]}
def put(c,r):c.execute('UPDATE trade_records SET payload=? WHERE id=?',(rc.dump(r),r['id']))
def trip_snapshot(t):return {k:t.get(k) for k in ('id','name','vehicle_id','driver_ids','driver','provider_id','period')}

def guard_dispatch(c,before,after):
    import trade
    for r in trade.records(c,'trip'):
        if r['business_date']!=after['business_date'] or r.get('voided') or not r.get('document_id'):continue
        old=next((t for t in (before or {}).get('trips',[]) if t['id']==r['trip_id']),None);new=next((t for t in after['trips'] if t['id']==r['trip_id']),None)
        old_stops=[a for a in (before or {}).get('assignments',[]) if a.get('trip_id')==r['trip_id']];new_stops=[a for a in after['assignments'] if a.get('trip_id')==r['trip_id']]
        if trip_snapshot(old or {})!=trip_snapshot(new or {}) or old_stops!=new_stops or r.get('source_snapshot') is not None and r['source_snapshot']!=source(c,after,r['trip_id']):raise ValueError('此趟已结算，须先撤销运输结算后再改派')

def sync(c,day,role,now,audit):
    import trade
    plan=plan_for(c,day);existing={r['trip_id']:r for r in trade.records(c,'trip') if r['business_date']==day};changed=[];current={t['id'] for t in plan.get('trips',[])}
    def retire(old,reason):
        if not old or old.get('voided') or old.get('document_id') or not old.get('auto_from_dispatch') or not old.get('closure_version'):return
        r={**old,'voided':True,'execution_state':'cancelled','state_note':reason,'void_reason':reason,'version':old.get('version',0)+1,'updated_at':now()}
        put(c,r);audit(c,role,'同步作废无实发配送',r['id'],old,r);changed.append(r)
    for t in plan.get('trips',[]):
        snap=source(c,plan,t['id']);old=existing.get(t['id'])
        if not snap:retire(old,'排车已无对应实发，自动作废');continue
        if old and old.get('document_id'):continue
        rc.open_period(c,day)
        area=trade.trip_area(c,plan,t['id']);pid=t.get('provider_id','');p=provider(c,pid,False) if pid else None;task=t.get('task') if t.get('task') in TASK_KINDS and t.get('task')!='delivery' else 'delivery';q=quote(c,pid,area,day,t.get('vehicle',''),task) if pid else None;mc=contract(c,pid,area,day) if pid and task=='delivery' else None
        r={**(old or {}),'voided':False,'void_reason':'','state_note':'','id':(old or {}).get('id','TR-AUTO-'+hashlib.sha256((day+'|'+t['id']).encode()).hexdigest()[:20]),'kind':'trip','closure_version':1,'business_date':day,'trip_id':t['id'],'trip_name':t['name'],'vehicle_id':t.get('vehicle_id',''),'vehicle_name':t.get('vehicle_name',''),'driver':t.get('driver',''),'driver_ids':t.get('driver_ids',[]),'provider_id':pid,'partner':p['name'] if p else '', 'area':area,'execution_state':'confirmed','source_snapshot':snap,'source_order_ids':[o['order_id'] for o in snap],'plan_version':plan.get('version'),'auto_from_dispatch':True,'note':'确认实发生成配送记录','handler':role}
        preserve=old and old.get('price_manual') and old.get('provider_id')==pid and old.get('area')==area
        if not preserve:
            if q:r.update(amount_cents=q['amount_cents'],quote_snapshot=q,covered_by_monthly='',pricing_pending=not bool(p))
            elif mc:r.update(amount_cents=0,quote_snapshot=mc,covered_by_monthly=mc['id'],pricing_pending=not bool(p))
            else:r.update(amount_cents=None,quote_snapshot=None,covered_by_monthly='',pricing_pending=True)
            r['price_manual']=False
        else:r['pricing_pending']=not bool(p and r.get('amount_cents'))
        if old and all(old.get(k)==v for k,v in r.items()):continue
        r.update(version=(old or {}).get('version',0)+1,updated_at=now())
        if old:put(c,r)
        else:c.execute('INSERT INTO trade_records VALUES(?,?)',(r['id'],rc.dump(r)))
        audit(c,role,'同步实发配送与服务商报价',r['id'],old,r);changed.append(r)
    for tid,old in existing.items():
        if tid not in current:retire(old,'此趟已从排车删除，自动作废')
    return changed

def unpriced(r):return r.get('pricing_pending') or r.get('amount_cents') is None or not r.get('partner')
def ready(r):return not unpriced(r)

def save(c,kind,b,role,now,audit):
    import trade
    if kind not in PERMISSIONS:raise ValueError('不支持的配送操作')
    access.require_role(role,PERMISSIONS[kind]);key=rc.text(b.get('request_key'),'提交编号',100);finger=stamp({'operation':kind,'body':{k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}})
    previous=c.execute('SELECT payload FROM trade_submissions WHERE request_key=?',(key,)).fetchone()
    if previous:
        r=json.loads(previous[0])
        if r.get('fingerprint')!=finger:raise ValueError('提交编号已使用，请重新打开')
        return r
    old=None
    if kind=='transport-sync':
        day=rc.day(b.get('business_date'));changed=sync(c,day,role,now,audit);r={'id':'SYNC-'+key,'kind':'transport-sync','business_date':day,'changed_count':len(changed)}
    elif kind=='transport-provider':
        value=parties.save(c,{**b,'kind':'logistics'},role,now,audit,permission='delivery.schedule');r={'id':value['id'],'kind':'provider','name':value['name'],'phone':value.get('phone',''),'active':value['active'],'version':value['version']}
    elif kind=='transport-provider-status':
        old=provider(c,b.get('id'),False)
        if type(b.get('version')) is not int or old['version']!=b.get('version'):raise ValueError('服务商档案已变化，请刷新')
        value=parties.save(c,{**old,'active':b.get('active') is True,'request_key':key},role,now,audit,permission='delivery.schedule');r={'id':value['id'],'kind':'provider','name':value['name'],'active':value['active'],'version':value['version']}
    elif kind=='transport-quote':
        p=provider(c,b.get('provider_id'));area=rc.text(b.get('area'),'配送区域',20);day=rc.day(b.get('effective_date'));mode=b.get('mode') if b.get('mode') in ('trip','monthly') else 'trip';task=b.get('task') if b.get('task') in TASK_KINDS else 'delivery';vehicle=rc.text(b.get('vehicle',''),'车辆类型',30,False);values=quotes(c);old=next((q for q in values if (q['provider_id'],q['area'],q['effective_date'],q.get('mode','trip'),q.get('task','delivery'),q.get('vehicle',''))==(p['id'],area,day,mode,task,vehicle)),None)
        if type(b.get('version')) is not int or b['version']!=(old or {}).get('version',0):raise ValueError('报价已变化，请刷新后核对')
        if area not in regions(c) and not (old and area==old.get('area')):raise ValueError('配送区域须从客户地区列表中选择')
        r={'id':(old or {}).get('id','TQ-'+secrets.token_hex(8)),'provider_id':p['id'],'provider_name':p['name'],'area':area,'effective_date':day,'mode':mode,'task':task,'vehicle':vehicle,'amount_cents':rc.cents(b.get('rate'),positive=True),'version':(old or {}).get('version',0)+1,'updated_at':now()}
        values=[q for q in values if q['id']!=r['id']]+[r];c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(QUOTE_KEY,rc.dump(values)));audit(c,role,'维护配送服务商区域报价',r['id'],old,r)
    elif kind=='transport-quote-delete':
        values=quotes(c);old=next((q for q in values if q['id']==b.get('id')),None)
        if not old or (type(b.get('version')) is not int or old.get('version')!=b.get('version')):raise ValueError('报价已变化，请刷新')
        values=[q for q in values if q['id']!=old['id']];c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(QUOTE_KEY,rc.dump(values)));audit(c,role,'删除配送服务商区域报价',old['id'],old,{'deleted':True});r={'id':old['id'],'kind':'quote','deleted':True}
    elif kind=='transport-task':
        import trade
        p=provider(c,b.get('provider_id'));day=rc.day(b.get('business_date'));task=b.get('task') if b.get('task') in TASK_TYPES and b.get('task')!='delivery' else 'other';amount=rc.cents(b.get('rate'),positive=True);note=rc.text(b.get('note',''),'说明',300,False)
        rc.open_period(c,day)
        r={'id':'TT-'+secrets.token_hex(8),'kind':'transport-task','business_date':day,'provider_id':p['id'],'partner':p['name'],'task':task,'task_label':TASK_TYPES[task],'amount_cents':amount,'note':note,'voided':False,'version':1,'updated_at':now(),'handler':role}
        c.execute('INSERT INTO trade_records VALUES(?,?)',(r['id'],rc.dump(r)));audit(c,role,'登记临时运输任务',r['id'],None,r)
    elif kind=='transport-task-void':
        import trade
        old=next((t for t in trade.records(c,'transport-task') if t['id']==b.get('id')),None)
        if not old or old.get('voided') or old.get('document_id') or (type(b.get('version')) is not int or old['version']!=b.get('version')):raise ValueError('临时任务已变化或已结算，请刷新')
        reason=rc.text(b.get('note'),'作废原因',300);r={**old,'voided':True,'void_reason':reason,'version':old['version']+1,'updated_at':now(),'handler':role};put(c,r);audit(c,role,'作废临时运输任务',r['id'],old,r)
    elif kind=='transport-reopen':
        old=next((d for d in trade.records(c,'transport-document') if d['id']==b.get('id')),None)
        if not old or old.get('voided') or (type(b.get('version')) is not int or old['version']!=b.get('version')):raise ValueError('结算单已变化，请刷新')
        reason=rc.text(b.get('note'),'撤销结算原因',500);expense=next((e for e in rc.expense_projection(c) if e['id']==old['expense_id']),None)
        if not expense or expense.get('voided') or (type(b.get('expense_version')) is not int or b.get('expense_version')!=expense['version']):raise ValueError('应付状态已变化，请刷新后核对')
        if expense['paid_cents']:raise ValueError('已有付款，不能撤销结算；须保留付款凭据，另行办理差额或退款核查')
        rc.open_period(c,old['business_date']);rc.expense_open_periods(c,expense)
        original=json.loads(c.execute('SELECT payload FROM indirect_expenses WHERE id=?',(expense['id'],)).fetchone()[0]);updated={**original,'voided':True,'void_reason':reason,'voided_at':now(),'version':expense['version']+1,'review_reset_version':expense['version']+1};c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(rc.dump(updated),expense['id']));audit(c,role,'撤销未付款运输应付',expense['id'],original,updated)
        for t in trade.records(c,'trip')+trade.records(c,'transport-task'):
            if t.get('document_id')==old['id']:
                value={**t,'version':t['version']+1,'updated_at':now(),'previous_document_ids':t.get('previous_document_ids',[])+[old['id']]};value.pop('document_id',None);put(c,value)
        r={**old,'voided':True,'void_reason':reason,'version':old['version']+1,'updated_at':now()};put(c,r);audit(c,role,'撤销运输结算并释放原趟次',r['id'],old,r)
    else:
        old=next((r for r in trade.records(c,'trip') if r['id']==b.get('id')),None)
        if not old or (type(b.get('version')) is not int or old['version']!=b.get('version')) or old.get('document_id'):raise ValueError('趟次已变化或已结算，请先核对结算单')
        if old.get('voided'):raise ValueError('已取消趟次不能计费')
        rc.open_period(c,old['business_date']);r=copy.deepcopy(old);reason=rc.text(b.get('note'),'操作依据',500)
        p=provider(c,b.get('provider_id'));rate=rc.cents(b.get('rate'),positive=True)
        r.update(provider_id=p['id'],partner=p['name'],amount_cents=rate,pricing_pending=False,price_manual=True,price_note=reason,provider_snapshot={k:p[k] for k in ('id','name','kind','phone','version')})
        r.update(version=old['version']+1,updated_at=now(),handler=role,change_history=old.get('change_history',[])+[{'version':old['version'],'execution_state':old.get('execution_state'),'provider_id':old.get('provider_id'),'amount_cents':old.get('amount_cents'),'note':reason,'at':now(),'handler':role}]);put(c,r);audit(c,role,'配送运费更正',r['id'],old,r)
    r={**r,'fingerprint':finger};c.execute('INSERT INTO trade_submissions VALUES(?,?)',(key,rc.dump(r)));return r

def decorate_report(c,report):
    import trade
    report.update(providers=providers(c),quotes=quotes(c),regions=regions(c),tasks=tasks(c,report['month']),contracts=monthly_charges(c,report['month']));expenses={e['id']:e for e in rc.expense_projection(c)}
    for d in report['documents']:
        e=expenses.get(d['expense_id'],{});d.update(paid_cents=e.get('paid_cents',0),outstanding_cents=e.get('outstanding_cents',0),payment_status=e.get('payment_status','待核查'),expense_version=e.get('version'),can_reopen=not d.get('voided') and e.get('paid_cents')==0)
    exceptions=[];source_cache={}
    def current_source(t):
        key=(t['business_date'],t['trip_id'])
        if key not in source_cache:source_cache[key]=source(c,plan_for(c,key[0]),key[1])
        return source_cache[key]
    for (payload,) in c.execute("SELECT payload FROM orders WHERE substr(json_extract(payload,'$.business_date'),1,7)=?",(report['month'],)):
        o=json.loads(payload)
        if o.get('delivery_method')=='pickup' or not any(Decimal(l.get('actual_qty') or '0')>0 for l in o['lines']):continue
        matches=[t for t in report['trips'] if o['id'] in t.get('source_order_ids',[]) and not t.get('voided')]
        if not matches:exceptions.append({'business_date':o['business_date'],'order_id':o['id'],'customer_name':o['customer_name'],'issue':'实发尚无有效运输记录，请核对排车、同步趟次或自提方式'})
        elif any(t.get('closure_version') and t.get('source_snapshot')!=current_source(t) for t in matches):exceptions.append({'business_date':o['business_date'],'order_id':o['id'],'customer_name':o['customer_name'],'issue':'实发来源已变化，须更正趟次后结算'})
    report['exceptions']=exceptions
    return report

def operations_only(value):
    """Strict allowlist for logistics/warehouse: no fees, quote or payment details."""
    fields=('id','version','business_date','trip_id','trip_name','vehicle_id','vehicle_name','driver','driver_ids','provider_id','partner','execution_state','closure_version','voided','state_note','source_order_ids')
    return {'month':value['month'],'trips':[{k:r[k] for k in fields if k in r} for r in value['trips']],'providers':value['providers'],'exceptions':value['exceptions'],'financial':False}


def cost_basis(c,month,day=None):
    import trade
    rows=[t for t in trade.records(c,'trip') if not t.get('voided') and (t['business_date']==day if day else t['business_date'].startswith(month))]
    actual=rows;missing=[t for t in actual if unpriced(t)];gaps=[]
    if missing:gaps.append({'field':str(len(missing))+' 趟实际运费资料待补，已知小计不代表完整配送成本','owner':'会计','target':'transport-settlement'})
    extra=0
    if not day:
        extra=sum(x['amount_cents'] for x in monthly_charges(c,month))+sum(t['amount_cents'] for t in tasks(c,month))
    else:
        extra=sum(t['amount_cents'] for t in tasks(c,month) if t['business_date']==day)
    return {'amount_cents':sum(t['amount_cents'] for t in actual if t.get('amount_cents') is not None)+extra,'gaps':gaps,'actual_count':len(actual),'pending_count':0,'missing_count':len(missing)}


def order_signature(o):
    return (o.get('business_date'),o.get('customer_id'),o.get('delivery_method','delivery'),sorted((l['product_id'],rc.ds(Decimal(l['actual_qty'])) if l.get('actual_qty') not in (None,'') else '未记录') for l in o.get('lines',[]) if l.get('actual_qty') in (None,'') or Decimal(l['actual_qty'])>0))

def guard_order(c,old,new):
    if old and order_signature(old)==order_signature(new):return
    days={o['business_date'] for o in (old,new) if o};oid=new['id']
    for day in days:
        plan=plan_for(c,day)
        customer=c.execute('SELECT market_id,route FROM customers WHERE id=?',(new['customer_id'],)).fetchone()
        market=plan.get('order_markets',{}).get(oid) or (customer['market_id'] if customer else '')
        target=next((a.get('trip_id') for a in plan.get('assignments',[]) if a.get('market_id')==market),None)
        for (payload,) in c.execute("SELECT payload FROM trade_records WHERE json_extract(payload,'$.kind')='trip' AND json_extract(payload,'$.business_date')=?",(day,)):
            t=json.loads(payload)
            if t.get('voided') or not t.get('document_id'):continue
            linked=oid in t.get('source_order_ids',[])
            added=day==new['business_date'] and bool(target) and target==t.get('trip_id') and new.get('delivery_method')!='pickup' and any(Decimal(l.get('actual_qty') or '0')>0 for l in new['lines'])
            if linked or added:raise ValueError('关联配送已结算，须先撤销运输结算，再更正实发或客户日期')
