"""Delivery evidence, reusable packaging by customer, and monthly trip settlement.

Caller owns the write transaction. Original orders and issued statements stay intact.
"""
import calendar
import hashlib
import json
import secrets
import re
from decimal import Decimal
import resources_costs as rc
import erp_access as access


def metadata(c, key, default=None):
    row=c.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else ({} if default is None else default)


def product_config(c,p):
    return metadata(c,'product_trade').get(p['id'],{})


def units(c):
    return metadata(c,'trade_units',[{'id':'筐','fractional':False},{'id':'包','fractional':False},{'id':'盒','fractional':False},{'id':'公斤','fractional':True},{'id':'件','fractional':False}])


def product_billing(c,p):
    import billing
    return product_config(c,p).get('billing_unit','公斤' if billing.enabled(c) or p['unit']=='筐' else p['unit'])


def records(c,kind=None):
    return [r for r in rc.rows(c,'trade_records') if kind is None or r['kind']==kind]


def get_order(c,oid):
    row=c.execute('SELECT payload FROM orders WHERE id=?',(oid,)).fetchone()
    if not row:raise ValueError('订单不存在，请刷新')
    return json.loads(row[0])


def crate_types(c):
    return [r for r in rc.rows(c,'asset_records') if r['kind']=='asset' and r['category']=='周转筐' and not r.get('deleted')]


def shipment(c,oid):
    return next((r for r in records(c,'shipment') if r['order_id']==oid),None)


def shipped_crates(c,o):
    explicit=shipment(c,o['id'])
    if explicit and not any('crate_lines' in l for l in o['lines']):return explicit['lines']
    mapping={r['product_id']:r['asset_id'] for r in rc.rows(c,'asset_records') if r['kind']=='mapping'}
    types={a['id']:a for a in crate_types(c)};result=[]
    for l in o['lines']:
        if 'crate_lines' in l:
            result.extend({k:v for k,v in line.items() if k!='packing_lines'} for line in l['crate_lines']);continue
        legacy=[r for r in (explicit or {}).get('lines',[]) if r['product_id']==l['product_id']]
        if legacy:result.extend(legacy);continue
        if l['unit']=='筐' and Decimal(l.get('actual_qty') or '0')>0:
            import crate_accounting
            variants=crate_accounting.variants(c,l['product_id']);parents={v['parent_id'] for v in variants}
            if not variants and l['product_id'] not in mapping:continue
            if len(variants)>1 and len(parents)>1:continue
            aid=next(iter(parents)) if len(variants)>1 else variants[0]['id'] if variants else mapping[l['product_id']]
            result.append({'product_id':l['product_id'],'asset_id':aid,'asset_name':types.get(aid,{}).get('name','未命名筐型'),'qty':int(Decimal(l['actual_qty'])),'tare':str(next((w['tare'] for w in l.get('customer',[])),'0')),'inferred':True})
    return result


def attach_crates(c,o):
    entry=shipment(c,o['id'])
    validate_shipment(c,o)
    if not entry:return
    for l in o['lines']:
        if 'crate_lines' not in l:l['crate_lines']=[r for r in entry['lines'] if r['product_id']==l['product_id']]


def validate_shipment(c,o):
    entry=shipment(c,o['id'])
    if any('crate_lines' in l for l in o['lines']):
        for l in o['lines']:
            if l.get('crate_lines') and sum(Decimal(str(r['qty'])) for r in l['crate_lines'])!=Decimal(l['actual_qty']):raise ValueError(l['product_name']+'框子属性数量与实发不一致')
        return
    if not entry:return
    if any(r['product_id'] not in {l['product_id'] for l in o['lines']} for r in entry['lines']):raise ValueError('订单产品已调整，请更新框型明细')
    for l in o['lines']:
        if l['unit']!='筐':continue
        total=sum(Decimal(str(r['qty'])) for r in entry['lines'] if r['product_id']==l['product_id'])
        if total!=Decimal(l['actual_qty']):raise ValueError(l['product_name']+'的框型数量与实发不一致，请先更新“框型与皮重”')


def customer_crates(c,cid,day):
    """As-of-date balance; unattributed historical returns never reduce a customer."""
    types={a['id']:a['name'] for a in crate_types(c)};totals={};events=[];issues=[]
    def add(a,key,qty):
        r=totals.setdefault(a,{'asset_id':a,'asset_name':types.get(a,a),'opening_qty':0,'shipped_qty':0,'returned_qty':0,'today_returned_qty':0})
        r[key]+=int(qty)
    for r in records(c,'opening'):
        if r['customer_id']==cid and r['business_date']<=day:add(r['asset_id'],'opening_qty',r['qty'])
    for o in rc.rows(c,'orders'):
        if o['customer_id']!=cid or o['business_date']>day:continue
        lines=shipped_crates(c,o)
        try:validate_shipment(c,o)
        except ValueError as e:issues.append(o['id']+' '+str(e))
        for r in lines:add(r['asset_id'],'shipped_qty',r['qty'])
        for l in o['lines']:
            if l['unit']=='筐' and Decimal(l.get('actual_qty') or '0')>0 and not any(r['product_id']==l['product_id'] for r in lines):issues.append(o['id']+' '+l['product_name']+'未登记框型')
    for r in rc.rows(c,'asset_records'):
        if r['kind']!='movement' or r.get('movement')!='return' or r.get('voided') or r.get('customer_id')!=cid or r['business_date']>day:continue
        add(r['asset_id'],'returned_qty',r['qty'])
        if r['business_date']==day:add(r['asset_id'],'today_returned_qty',r['qty'])
        events.append({k:r.get(k,'') for k in ('id','business_date','order_id','asset_id','asset_name','qty','driver','trip')})
    result=[]
    for r in totals.values():
        r['balance_qty']=r['opening_qty']+r['shipped_qty']-r['returned_qty'];result.append(r)
    return {'as_of':day,'rows':result,'returns':sorted(events,key=lambda e:(e['business_date'],e['id'])),'issues':list(dict.fromkeys(issues)),'basis':'期初欠框＋累计实发－已确认回框；未关联客户的历史回框待补录归属'}


def return_lines(c,lines,source_date='',source_trip_id='',require_order=False):
    import assets
    types={r['id']:r for r in crate_types(c) if r.get('active',True)};seen=set();out=[]
    if not isinstance(lines,list) or len(lines)>200:raise ValueError('回框明细无效')
    for l in lines:
        if not isinstance(l,dict):raise ValueError('回框明细无效')
        a=types.get(l.get('asset_id'));oid=l.get('order_id','');key=(oid,l.get('asset_id'))
        if not a or key in seen:raise ValueError('同一订单的框型无效或重复')
        seen.add(key);qty=assets.integer(l.get('qty'),'回框数量')
        if qty<=0:raise ValueError('回框数量必须大于零')
        r={'asset_id':a['id'],'asset_name':a['name'],'qty':qty}
        if require_order and not oid:raise ValueError('请按客户订单填写回框')
        if oid:
            o=get_order(c,oid)
            if source_date and o['business_date']!=source_date:raise ValueError('回框订单与原配送日期不一致')
            if source_trip_id:
                p=next((p for p in rc.rows(c,'dispatch_plans') if p['business_date']==o['business_date']),{})
                mids={a['market_id'] for a in p.get('assignments',[]) if a.get('trip_id')==source_trip_id}
                if p.get('order_markets',{}).get(oid) not in mids:raise ValueError('回框订单不属于所选趟次')
            if not any(x['asset_id']==a['id'] for x in shipped_crates(c,o)):raise ValueError('该订单未发出此框型，请先核对订单框型')
            r.update(order_id=oid,customer_id=o['customer_id'],customer_name=o['customer_name'])
        out.append(r)
    return out


def digest(value):return hashlib.sha256(rc.dump(value).encode()).hexdigest()


def projection(c,day):
    day=rc.day(day)
    return {'business_date':day,'types':crate_types(c),'shipments':records(c,'shipment'),'feedback':records(c,'feedback'),'customers':[{'customer_id':r['id'],'customer_name':r['name'],**customer_crates(c,r['id'],day)} for r in c.execute('SELECT id,name FROM customers')]}



TRANSPORT_RATES_KEY='transport_rates'
def rates(c):
    row=c.execute("SELECT value FROM meta WHERE key=?",(TRANSPORT_RATES_KEY,)).fetchone()
    cfg=json.loads(row[0]) if row else {}
    return {str(k):str(v) for k,v in (cfg.get('areas') or {}).items()}

def save_rates(c,b,role,now,audit):
    access.require_role(role,'costs.write')
    areas=b.get('areas')
    if not isinstance(areas,dict) or not areas or len(areas)>50:raise ValueError('请填写1至50个配送区域单价')
    clean={}
    for name,price in areas.items():
        label=rc.text(name,'区域名称',20);value=rc.cents(price,positive=True)
        clean[label]=str(Decimal(value)/100)
    c.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(TRANSPORT_RATES_KEY,rc.dump({'areas':clean})))
    audit(c,role,'维护运输区域单价','transport-rates',None,clean)
    return clean

def trip_area(c,plan,trip_id):
    markets={r['id']:r['city'] for r in c.execute('SELECT id,city FROM delivery_markets')}
    cities=[]
    for a in plan.get('assignments',[]):
        if a.get('trip_id')!=trip_id:continue
        city=str(markets.get(a.get('market_id')) or '').strip()
        if city and city not in cities:cities.append(city)
    return cities[0] if len(cities)==1 else ''

def ensure_dispatched_trips(c,day,role,now,audit):
    return __import__('transport_closure').sync(c,day,role,now,audit)


def transport_report(c,month):
    import transport_closure as tc
    rc.day(month+'-01')
    trips=[r for r in records(c,'trip') if r['business_date'].startswith(month)]
    docs=[r for r in records(c,'transport-document') if r['month']==month];groups={}
    for r in trips:
        if r.get('voided'):continue
        gid=r.get('provider_id') or 'legacy:'+r.get('partner','')
        g=groups.setdefault(gid,{'group_id':gid,'provider_id':r.get('provider_id',''),'partner':r.get('partner',''),'trip_count':0,'amount_cents':0,'unsettled_count':0,'unsettled_cents':0,'pending_count':0,'ready_count':0,'completed_count':0})
        g['trip_count']+=1;g['amount_cents']+=r.get('amount_cents') or 0;g['completed_count']+=1
        if not r.get('document_id'):
            g['unsettled_count']+=1;g['unsettled_cents']+=r.get('amount_cents') or 0
            if tc.ready(r):g['ready_count']+=1
            else:g['pending_count']+=1
    for gid,g in groups.items():g['source_fingerprint']=digest(sorted((r for r in trips if not r.get('voided') and (r.get('provider_id') or 'legacy:'+r.get('partner',''))==gid and not r.get('document_id')),key=lambda r:r['id']))
    return tc.decorate_report(c,{'month':month,'trips':trips,'documents':docs,'groups':list(groups.values()),'rates':rates(c)})


def save(c,kind,b,role,now,audit):
    import transport_closure as tc
    if kind in tc.PERMISSIONS:return tc.save(c,kind,b,role,now,audit)
    permission={'shipment':'weight.write','feedback':'weight.write','resolve-feedback':'finance.settle','opening':'crates.write','unit':'master.products.write','trip':'delivery.schedule','void-trip':'delivery.schedule','transport-issue':'costs.write','transport-rates':'costs.write'}.get(kind)
    if not permission:raise ValueError('未知配送管理操作')
    access.require_role(role,permission)
    key=rc.text(b.get('request_key'),'提交编号',100);finger=digest({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')})
    prior=c.execute('SELECT payload FROM trade_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        r=json.loads(prior[0])
        if r['fingerprint']!=finger:raise ValueError('提交编号已使用，请重新打开表单')
        return r
    old=None;r={};action='登记配送明细'
    if kind=='unit':
        name=rc.text(b.get('name'),'单位名称',12)
        if not re.fullmatch(r'[A-Za-z0-9\u3400-\u9fff_-]{1,12}',name):raise ValueError('单位名称请使用中文、字母或数字')
        if name in ('kg','KG','千克','框'):name='公斤' if name!='框' else '筐'
        values=units(c)
        if any(u['id']==name for u in values):raise ValueError('此单位已存在')
        values.append({'id':name,'fractional':b.get('fractional') is True});c.execute("INSERT INTO meta VALUES('trade_units',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(values),));r={'name':name}
    elif kind=='opening':
        cid=b.get('customer_id');customer=c.execute('SELECT name FROM customers WHERE id=?',(cid,)).fetchone();a=next((a for a in crate_types(c) if a['id']==b.get('asset_id')),None)
        if not customer or not a:raise ValueError('请选择客户和框型')
        import assets
        r={'customer_id':cid,'asset_id':a['id'],'asset_name':a['name'],'business_date':rc.day(b.get('business_date')),'qty':assets.integer(b.get('qty'),'期初欠框数'),'note':rc.text(b.get('note'),'登记依据',500)}
        if any(x['customer_id']==cid and x['asset_id']==a['id'] for x in records(c,'opening')):raise ValueError('此客户框型已登记期初，不能重复导入')
    elif kind in ('shipment','feedback'):
        o=get_order(c,b.get('order_id'))
        if b.get('order_version')!=o['version']:raise ValueError('订单已更新，请重新打开核对')
        r={'order_id':o['id'],'customer_id':o['customer_id'],'customer_name':o['customer_name'],'business_date':o['business_date']}
        if kind=='shipment':
            if any('crate_lines' in l for l in o['lines']):raise ValueError('本单框子已在算票表录入，请到算票表修改颜色数量并重新核对')
            import inventory,assets
            inventory.open_day(c,o['business_date'])
            if o['state'] in ('ready','reviewed'):raise ValueError('已算票订单的框型皮重已锁定，请先按原流程退回重算')
            old=shipment(c,o['id'])
            if old and b.get('version')!=old['version']:raise ValueError('框型记录已更新，请重新打开')
            lines=b.get('lines');out=[];seen=set();types={a['id']:a for a in crate_types(c) if a.get('active',True)}
            if not isinstance(lines,list) or not 1<=len(lines)<=200:raise ValueError('请填写框型数量及皮重')
            for l in lines:
                if not isinstance(l,dict):raise ValueError('框型明细格式无效')
                p=next((p for p in o['lines'] if p['product_id']==l.get('product_id') and p['unit']=='筐'),None);a=types.get(l.get('asset_id'));k=(l.get('product_id'),l.get('asset_id'))
                if not p or not a or k in seen:raise ValueError('产品或框型无效、重复')
                seen.add(k);qty=assets.integer(l.get('qty'),'发出框数')
                if qty<=0:raise ValueError('发出框数须大于零')
                tare=rc.qty(l.get('tare'),'单框皮重')
                if tare>100:raise ValueError('单框皮重不能超过100公斤')
                out.append({'product_id':p['product_id'],'asset_id':a['id'],'asset_name':a['name'],'qty':qty,'tare':rc.ds(tare)})
            r['lines']=out
            for p in o['lines']:
                if p['unit']=='筐' and sum(x['qty'] for x in out if x['product_id']==p['product_id'])!=Decimal(p['actual_qty']):raise ValueError(p['product_name']+'的各框型合计必须等于实发数量')
            if o.get('weight_confirmation'):
                o.update(weight_confirmation=None,version=o['version']+1,updated_at=now());c.execute('UPDATE orders SET payload=? WHERE id=?',(rc.dump(o),o['id']))
            action='登记订单框型与皮重'
        else:
            p=next((l for l in o['lines'] if l['product_id']==b.get('product_id')),None)
            if not p:raise ValueError('请选择订单产品')
            received=rc.qty(b.get('received_qty'),'客户反馈实收数量')
            if not next((u['fractional'] for u in units(c) if u['id']==p['unit']),False) and received!=received.to_integral_value():raise ValueError('按'+p['unit']+'反馈的实收数量须为整数')
            delta=received-Decimal(p['actual_qty'])
            r.update(product_id=p['product_id'],product_name=p['product_name'],unit=p['unit'],actual_qty=p['actual_qty'],bill_qty=p.get('bill_qty'),billing_unit=p.get('billing_unit'),received_qty=rc.ds(received),difference_qty=rc.ds(delta),feedback_date=rc.day(b.get('feedback_date')),note=rc.text(b.get('note'),'客户反馈与核对依据',500),state='pending',source_order_version=o['version'])
            if r['feedback_date']<o['business_date']:raise ValueError('反馈日期不能早于配送日期')
            if any(x['order_id']==o['id'] and x['product_id']==p['product_id'] and x['state']=='pending' for x in records(c,'feedback')):raise ValueError('此产品已有待处理反馈，请先核对原记录')
            action='登记客户漏送多送反馈'
    elif kind=='resolve-feedback':
        old=next((r for r in records(c,'feedback') if r['id']==b.get('id')),None)
        if not old or b.get('version')!=old['version'] or old['state']!='pending':raise ValueError('反馈已处理或不存在')
        r={**old,'state':'resolved','resolution':rc.text(b.get('resolution'),'处理结果及关联单号',500),'resolved_at':now()};kind='feedback';action='核对配送差异处理结果'
    elif kind=='trip':
        day=rc.day(b.get('business_date'));plan=next((p for p in rc.rows(c,'dispatch_plans') if p['business_date']==day),{});t=next((t for t in plan.get('trips',[]) if t['id']==b.get('trip_id')),None)
        if not t:raise ValueError('请先保存该日期的配送趟次')
        if not any(a.get('trip_id')==t['id'] for a in plan.get('assignments',[])):raise ValueError('该趟次没有配送点，请先核对实际配送')
        existing=next((x for x in records(c,'trip') if x['business_date']==day and x['trip_id']==t['id'] and not x.get('voided')),None)
        if existing and existing.get('closure_version'):raise ValueError('配送趟次由车辆排班和实发确认生成，不可另行登记')
        if existing:
            if not existing.get('pricing_pending') or b.get('id')!=existing['id'] or b.get('version')!=existing['version'] or existing.get('document_id'):raise ValueError('该趟已登记或已有变化，不能重复计算')
            old=existing
        rc.open_period(c,day);area=trip_area(c,plan,t['id']);table=rates(c)
        raw=str(b.get('rate') or '').strip();rate=rc.cents(raw,positive=True) if raw else None
        if rate is None:
            if not area or not table.get(area):raise ValueError('该趟未匹配到区域单价，请填写运费或先维护区域单价')
            rate=rc.cents(table[area],positive=True)
        r={**(old or {}),'business_date':day,'trip_id':t['id'],'trip_name':t['name'],'vehicle_id':t.get('vehicle_id',''),'vehicle_name':t.get('vehicle_name',''),'driver':t.get('driver',''),'driver_ids':t.get('driver_ids',[]),'partner':rc.text(b.get('partner'),'运输结算对象',100),'area':area,'amount_cents':rate,'note':rc.text(b.get('note'),'实际出车依据',500),'plan_version':plan.get('version'),'pricing_pending':False};action='补齐配送趟次结算对象与运费' if old else '确认实际配送趟次与运费'
    elif kind=='transport-rates':
        return {'areas':save_rates(c,b,role,now,audit)}
    elif kind=='void-trip':
        old=next((r for r in records(c,'trip') if r['id']==b.get('id')),None)
        if not old or b.get('version')!=old['version'] or old.get('voided') or old.get('document_id'):raise ValueError('已作废或已结算的趟次不能作废')
        if old.get('closure_version'):raise ValueError('请在车辆排班中调整该趟配送，或在配送费结算中撤销未付款结算')
        rc.open_period(c,old['business_date']);r={**old,'voided':True,'void_reason':rc.text(b.get('note'),'作废原因',500)};kind='trip';action='作废重复配送趟次'
    elif kind=='transport-issue':
        import datetime
        month=rc.text(b.get('month'),'结算月份',7);rc.day(month+'-01');partner=rc.text(b.get('partner'),'运输结算对象',100)
        eligible=sorted((r for r in records(c,'trip') if r['business_date'].startswith(month) and (r.get('provider_id')==b.get('provider_id') if b.get('provider_id') else not r.get('provider_id') and r['partner']==partner) and not r.get('voided') and not r.get('document_id')),key=lambda r:r['id'])
        if not eligible:raise ValueError('该对象当月没有未结算趟次')
        if b.get('source_fingerprint')!=digest(eligible):raise ValueError('趟次数据已变化，请重新读取核对')
        if any(not tc.ready(x) for x in eligible):raise ValueError('尚有趟次未补齐服务商或运费，请先核对后月结')
        for x in eligible:
            if x.get('closure_version') and x.get('source_snapshot') is not None and x.get('source_snapshot')!=tc.source(c,tc.plan_for(c,x['business_date']),x['trip_id']):raise ValueError('实发来源已变化，请先在车辆排班保存并同步当趟配送，再核对月结')
        pid=b.get('provider_id','');p=tc.provider(c,pid,False) if pid else None
        if p:partner=p['name']
        total=sum(x['amount_cents'] for x in eligible);doc='YS-'+month.replace('-','')+'-'+secrets.token_hex(5).upper();last=month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:]))[1]);rc.open_period(c,last)
        expense=rc.Operations(c,now,audit).expense({'request_key':'transport:'+doc,'business_date':last,'period':month,'category':'transport','amount':str(Decimal(total)/100),'department':'配送','partner':partner,**({'counterparty_id':pid} if pid else {}),'reference':doc,'source_document_id':doc,'note':f'{month} 配送 {len(eligible)} 趟，按运输结算单计费','handler':rc.text(b.get('handler'),'结算经办人',80)},role,_system_source='transport-settlement')
        r={'company':__import__('company').current(c),'id':doc,'month':month,'provider_id':pid,'partner':partner,'trip_count':len(eligible),'amount_cents':total,'lines':eligible,'expense_id':expense['id'],'operator_name':rc.text(b.get('handler'),'结算经办人',80),'business_date':last,'note':rc.text(b.get('note',''),'备注',500,False)}
        for t in eligible:
            c.execute('UPDATE trade_records SET payload=? WHERE id=?',(rc.dump({**t,'document_id':doc,'version':t['version']+1}),t['id']))
        kind='transport-document';action='生成月度运输结算单并登记配送应付'
    if old and b.get('version')!=old['version']:raise ValueError('记录已更新，请重新打开')
    r.update(id=r.get('id',(old or {}).get('id','TR-'+secrets.token_hex(8))),kind=kind,version=(old or {}).get('version',0)+1,updated_at=now(),handler=role)
    if old:c.execute('UPDATE trade_records SET payload=? WHERE id=?',(rc.dump(r),r['id']))
    else:c.execute('INSERT INTO trade_records VALUES(?,?)',(r['id'],rc.dump(r)))
    result={**r,'fingerprint':finger};c.execute('INSERT INTO trade_submissions VALUES(?,?)',(key,rc.dump(result)));audit(c,role,action,r['id'],old,r)
    return result
