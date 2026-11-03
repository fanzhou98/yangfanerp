"""Driver-owned delivery views and warehouse-reviewed crate return submissions."""
import base64,json,os,re,secrets,hashlib,uuid
from pathlib import Path
import trade,crate_accounting
from datetime import date,timedelta
from decimal import Decimal
import auth,erp_access as access,resources_costs as rc

PHOTO_ROOT=Path(os.environ.get('ERP_DRIVER_PHOTO_DIR','data/driver-photos'))
PHOTO_MAX=4*1024*1024

def decode_photo(value):
    if not value:return None
    m=re.match(r'^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)$',str(value),re.S)
    if not m:raise ValueError('照片格式无效，请重新拍照')
    raw=base64.b64decode(re.sub(r'\s+','',m.group(2)))
    if not raw or len(raw)>PHOTO_MAX:raise ValueError('照片过大，请重新拍照')
    return raw,m.group(1)

def save_photo(c,user,order_id,kind,raw,mime,at):
    row=c.execute('SELECT payload FROM orders WHERE id=?',(order_id,)).fetchone()
    if not row:raise ValueError('配送单不存在，不能保存照片')
    order=json.loads(row[0]);ext={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}.get(mime,'.jpg')
    rel=PHOTO_ROOT/at[:4]/at[5:7]/f'{order_id}-{kind}-{uuid.uuid4().hex[:10]}{ext}'
    rel.parent.mkdir(parents=True,exist_ok=True);rel.write_bytes(raw)
    c.execute('INSERT INTO driver_photos(order_id,kind,at,driver_id,customer_id,path,mime,bytes,meta) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(order_id,kind) DO UPDATE SET at=excluded.at,driver_id=excluded.driver_id,customer_id=excluded.customer_id,path=excluded.path,mime=excluded.mime,bytes=excluded.bytes,meta=excluded.meta',(order_id,kind,at,user.get('id',''),order.get('customer_id',''),str(rel),mime,len(raw),rc.dump({'number':order.get('number','')})))
    return str(rel)

def photo_kinds(c,order_id,base):
    return [r['kind'] for r in c.execute('SELECT kind FROM driver_photos WHERE order_id=?',(order_id,)) if r['kind']==base or r['kind'].startswith(base+'-')]

def remove_photo(c,order_id,kind):
    r=c.execute('SELECT path FROM driver_photos WHERE order_id=? AND kind=?',(order_id,kind)).fetchone()
    if not r:return
    try:Path(r['path']).unlink()
    except OSError:pass
    c.execute('DELETE FROM driver_photos WHERE order_id=? AND kind=?',(order_id,kind))

def next_photo_kind(c,order_id,base):
    used=set(photo_kinds(c,order_id,base))
    if base not in used:return base
    for n in range(2,21):
        kind=f'{base}-{n}'
        if kind not in used:return kind
    raise ValueError('照片数量过多，请删除后再拍')

def apply_photo_set(c,user,order_id,base,value,at):
    if isinstance(value,str):
        if value=='':
            for kind in photo_kinds(c,order_id,base):remove_photo(c,order_id,kind)
            return
        raw,mime=decode_photo(value);save_photo(c,user,order_id,base,raw,mime,at);return
    if value is None:return
    if not isinstance(value,dict):raise ValueError('照片格式无效')
    keep=value.get('keep');keep=set(keep) if isinstance(keep,list) else set()
    allowed=set(photo_kinds(c,order_id,base))
    if not keep<=allowed:raise ValueError('照片类型无效')
    for kind in allowed-keep:remove_photo(c,order_id,kind)
    adds=value.get('add') or []
    if not isinstance(adds,list) or len(adds)>6:raise ValueError('每项最多保留6张照片，请删除后再拍')
    for item in adds:
        raw,mime=decode_photo(item);save_photo(c,user,order_id,next_photo_kind(c,order_id,base),raw,mime,at)

def driver_crates(c,o):
    explicit=trade.shipment(c,o['id']) or any('crate_lines' in l for l in o['lines'])
    base=trade.shipped_crates(c,o) if explicit else []
    if not base:
        for l in o['lines']:
            if l.get('unit')!='筐' or Decimal(l.get('actual_qty') or '0')<=0:continue
            variants=crate_accounting.variants(c,l['product_id'])
            if variants:
                base.extend({'product_id':l['product_id'],'asset_id':v['id'],'asset_name':v['name'],'qty':None,'tare':'0','inferred':True} for v in variants)
    out=[];seen=set()
    for a in base:
        variants=crate_accounting.variants(c,a.get('product_id'))
        children=[v for v in variants if v.get('parent_id')==a.get('asset_id') and v['id']!=a.get('asset_id')]
        rows=[{**a,'asset_id':v['id'],'asset_name':v['name'],'qty':None,'inferred':True} for v in children] if children else [a]
        for row in rows:
            if row['asset_id'] in seen:continue
            seen.add(row['asset_id']);out.append(row)
    return out

def photo(c,user,order_id,kind):
    if kind not in ('weight','crate') and not re.fullmatch(r'(?:weight|crate)-[A-Za-z0-9_-]{1,80}',kind):raise ValueError('照片类型无效')
    row=c.execute('SELECT payload FROM orders WHERE id=?',(order_id,)).fetchone()
    if not row:raise auth.AuthError(404,'配送单不存在')
    order=json.loads(row[0])
    if user['role']=='司机':
        d=driver(c,user);_,owned=assigned(c,d['id'],order['business_date'])
        if order_id not in {o['id'] for o in owned}:raise auth.AuthError(403,'只能查看本人配送单的照片')
    else:
        try:access.require_role(user['role'],'weight.confirm')
        except Exception:access.require_role(user['role'],'finance.settle')
    r=c.execute('SELECT path,mime FROM driver_photos WHERE order_id=? AND kind=?',(order_id,kind)).fetchone()
    if not r:raise auth.AuthError(404,'尚未上传该照片')
    path=Path(r['path']).resolve();root=PHOTO_ROOT.resolve()
    if not str(path).startswith(str(root)+os.sep):raise auth.AuthError(403,'照片路径无效')
    if not path.exists():raise auth.AuthError(404,'照片文件不存在')
    return {'data':path.read_bytes(),'mime':r['mime']}

def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'driver')

def driver(c,user):
    if not user or user['role']!='司机':raise auth.AuthError(403,'此入口仅供司机本人使用')
    row=c.execute('SELECT d.id,d.name FROM driver_accounts a JOIN delivery_drivers d ON d.id=a.driver_id WHERE a.user_id=? AND d.active=1',(user['id'],)).fetchone()
    if not row:raise auth.AuthError(403,'账号尚未关联启用的司机档案，请联系管理员')
    return dict(row)
def assigned(c,driver_id,day):
    plan=next((p for p in rc.rows(c,'dispatch_plans') if p['business_date']==day),{})
    trips=[t for t in plan.get('trips',[]) if driver_id in (t.get('driver_ids') or ([t['driver_id']] if t.get('driver_id') else []))]
    ids={t['id'] for t in trips};assignments=[a for a in plan.get('assignments',[]) if a.get('trip_id') in ids];market_trip={a['market_id']:a['trip_id'] for a in assignments}
    orders=[o for o in rc.rows(c,'orders') if o['business_date']==day and o.get('delivery_method')!='pickup' and market_trip.get(plan.get('order_markets',{}).get(o['id'])) in ids]
    return {**plan,'business_date':day,'trips':trips,'assignments':assignments,'order_markets':{o['id']:plan['order_markets'][o['id']] for o in orders}},orders

def requests(c):return rc.rows(c,'driver_return_requests')
def pending(c):return sorted((r for r in requests(c) if r['state'] in ('pending','withdraw_pending')),key=lambda r:(r['business_date'],r['submitted_at'],r['id']))
def report(c,user,day,auto=False):
    requested=rc.day(day);day=requested;d=driver(c,user)
    plans=rc.rows(c,'dispatch_plans');own_plans=[p for p in plans if any(d['id'] in (t.get('driver_ids') or ([t['driver_id']] if t.get('driver_id') else [])) for t in p.get('trips',[]))]
    available_dates=sorted({p['business_date'] for p in own_plans},reverse=True)
    plan,orders=assigned(c,d['id'],day)
    customers={r['id']:dict(r) for r in c.execute('SELECT id,name,route,phone FROM customers')};tares={r['id']:r['tare'] for r in c.execute('SELECT id,tare FROM products')};import production_management as pm;product_rows={r['id']:dict(r) for r in c.execute('SELECT * FROM products')};averages={pid:pm.product_average(c,p) for pid,p in product_rows.items()};photo_rows=c.execute('SELECT order_id,kind,at FROM driver_photos').fetchall();photos={}
    for r in photo_rows:photos.setdefault(r['order_id'],{})[r['kind']]=r['at']
    trips=[]
    for t in plan.get('trips',[]):
        mids={a['market_id'] for a in plan['assignments'] if a['trip_id']==t['id']};sequence={a['market_id']:a['sequence'] for a in plan['assignments'] if a['trip_id']==t['id']}
        os=sorted([o for o in orders if plan['order_markets'][o['id']] in mids],key=lambda o:(sequence.get(plan['order_markets'][o['id']],1000),o['customer_name'],o['id']))
        trips.append({k:t.get(k,'') for k in ('id','name','period','vehicle_id','vehicle_name','driver')}|{'orders':[{'id':o['id'],'version':o['version'],'weight_editable':o['state'] in ('draft','dispatched') and not o.get('weight_confirmation') and not __import__('inventory').closed(c,o['business_date']),'day_closed':bool(__import__('inventory').closed(c,o['business_date'])),'weight_confirmed':bool(o.get('weight_confirmation')),'customer_id':o['customer_id'],'customer_name':o['customer_name'],'phone':customers.get(o['customer_id'],{}).get('phone',''),'market':customers.get(o['customer_id'],{}).get('route',''),'lines':[{**{k:l.get(k,'') for k in ('product_id','product_name','unit','ordered_qty','actual_qty','driver','driver_net','package_net_kg','factory_net_kg')},'default_tare':tares.get(l['product_id'],'0'),'default_average_kg':averages.get(l['product_id'])} for l in o['lines']],'business_date':o['business_date'],'trip_id':t['id'],'vehicle_id':t.get('vehicle_id',''),'crates':driver_crates(c,o),'photos':photos.get(o['id'],{})} for o in os]})
    # A driver may return older deliveries today; choices still belong to that driver's saved assignments.
    vehicle_ids={t.get('vehicle_id') for p in own_plans if p['business_date']<=requested for t in p.get('trips',[]) if d['id'] in (t.get('driver_ids') or ([t['driver_id']] if t.get('driver_id') else [])) and t.get('vehicle_id')}
    work_items=[];weight_completed=0
    for when in available_dates:
        if when>requested:continue
        _,own_orders=assigned(c,d['id'],when)
        for order in own_orders:
            tofu=[l for l in order['lines'] if '豆腐' in l['product_name'] and Decimal(l.get('actual_qty') or '0')>0]
            def missing(line):
                if line['unit']=='筐':return not (Decimal(line.get('driver_net') or '0')>0 and sum((Decimal(w.get('count') or '0') for w in line.get('driver',[])),Decimal(0))==Decimal(line['actual_qty']).to_integral_value(rounding='ROUND_CEILING'))
                return line['unit']=='包' and Decimal(line.get('package_net_kg') or '0')<=0
            if any(missing(l) for l in tofu):work_items.append({'id':order['id'],'business_date':when,'customer_name':order['customer_name']})
            elif tofu and when==requested:weight_completed+=1
    return {'business_date':day,'requested_date':requested,'available_dates':available_dates,'home_work':{'weight_items':work_items,'weight_completed':weight_completed},'display_notice':('所选日期暂无本人配送，当前显示最近一次已安排的配送：'+day) if day!=requested else '', 'driver':d,'trips':trips,'vehicles':[dict(r) for r in c.execute('SELECT id,name FROM delivery_vehicles WHERE active=1') if r['id'] in vehicle_ids],'crates':[{'id':r['id'],'name':r['name']} for r in rc.rows(c,'asset_records') if r['kind']=='asset' and r['category']=='周转筐' and r.get('active',True)],'requests':sorted([r for r in requests(c) if r['user_id']==user['id'] and r['state']!='deleted'],key=lambda r:(r['submitted_at'],r['id']),reverse=True)[:100]}

def return_options(c,user,day):
    driver(c,user);day=rc.day(day);plan=next((p for p in rc.rows(c,'dispatch_plans') if p['business_date']==day),{})
    orders=[o for o in rc.rows(c,'orders') if o['business_date']==day and o.get('delivery_method')!='pickup']
    return {'business_date':day,'orders':[{'id':o['id'],'customer_id':o['customer_id'],'customer_name':o['customer_name'],'trip_id':next((a.get('trip_id','') for a in plan.get('assignments',[]) if a['market_id']==plan.get('order_markets',{}).get(o['id'])) ,''),'crates':trade.shipped_crates(c,o)} for o in orders],'trips':[{k:t.get(k,'') for k in ('id','name','period','vehicle_id','vehicle_name','driver')} for t in plan.get('trips',[])],'vehicles':[dict(r) for r in c.execute('SELECT id,name FROM delivery_vehicles WHERE active=1')]}

def submit(c,user,b,now,audit):
    access.require_role(user['role'],'driver.returns');d=driver(c,user);key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch','photo','photos')}).encode()).hexdigest();prior=c.execute('SELECT payload FROM driver_return_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        r=json.loads(prior[0])
        if r['user_id']!=user['id'] or r['fingerprint']!=finger:raise ValueError('提交编号已使用，请重新打开表单')
        return r
    state=b.get('state','pending')
    if state not in ('draft','pending'):raise ValueError('只能保存草稿或提交库管确认')
    row=c.execute('SELECT payload FROM driver_return_requests WHERE id=?',(b.get('id'),)).fetchone();old=json.loads(row[0]) if row else None
    if b.get('id') and (not old or old['user_id']!=user['id']):raise auth.AuthError(403,'不能修改其他司机的填报')
    if old and (old['state']!='draft' or b.get('version')!=old['version']):raise ValueError('草稿已更新或已提交，请刷新后重试')
    day=rc.day(b.get('business_date'));view=report(c,user,day);vehicle_id=b.get('vehicle_id','');vehicle=c.execute('SELECT id,name FROM delivery_vehicles WHERE id=? AND active=1',(vehicle_id,)).fetchone() if vehicle_id else None
    if vehicle_id and not vehicle:raise ValueError('请选择系统中启用的回筐车辆')
    source_date=rc.day(b.get('source_date',day));source_trip_id=b.get('source_trip_id','');source=next((t for t in return_options(c,user,source_date)['trips'] if t['id']==source_trip_id),None)
    if source_trip_id and not source:raise ValueError('所选配送趟次已变更，请重新选择')
    if state=='pending' and b.get('source_date') and not source:raise ValueError('请选择对应配送日期和趟次')
    if source_date>day and state=='pending':raise ValueError('原配送日期不能晚于回筐日期')
    import assets
    lines=b.get('lines')
    if not isinstance(lines,list) or len(lines)>200 or state=='pending' and not lines:raise ValueError('请至少填写一种筐型数量')
    out=trade.return_lines(c,lines,source_date if source_trip_id else '',source_trip_id,b.get('by_order') is True)
    photo_data=decode_photo(b.get('photo',''))
    r={'id':old['id'] if old else 'DR-'+secrets.token_hex(8),'version':old['version']+1 if old else 1,'state':state,'user_id':user['id'],'driver_id':d['id'],'driver':d['name'],'vehicle_id':vehicle_id,'vehicle_name':vehicle['name'] if vehicle else '', 'business_date':day,'source_date':source_date,'source_trip_id':source_trip_id,'source_vehicle_id':source.get('vehicle_id','') if source else '', 'source_vehicle_name':source.get('vehicle_name','') if source else '', 'trip':source['name'] if source else rc.text(b.get('trip',''),'配送趟次',100,False),'note':rc.text(b.get('note',''),'备注',500,False),'lines':out,'submitted_at':now(),'fingerprint':finger}
    if old:c.execute('UPDATE driver_return_requests SET payload=? WHERE id=?',(rc.dump(r),r['id']))
    else:c.execute('INSERT INTO driver_return_requests VALUES(?,?,?)',(r['id'],key,rc.dump(r)))
    c.execute('INSERT INTO driver_return_submissions VALUES(?,?)',(key,rc.dump(r)));audit(c,user['role'],'保存司机回筐草稿' if state=='draft' else '司机提交回筐待确认',r['id'],old,r)
    order_ids={l.get('order_id') for l in out if l.get('order_id')}
    photo_sets=b.get('photos') or {}
    if not isinstance(photo_sets,dict):raise ValueError('照片格式无效')
    for oid in order_ids:
        if oid in photo_sets:apply_photo_set(c,user,oid,'crate',photo_sets[oid],now())
    if photo_data:
        for oid in order_ids:save_photo(c,user,oid,'crate',photo_data[0],photo_data[1],now())
    return r

def save_weights(c,user,b,now,audit,weight_fn,save_fn):
    access.require_role(user['role'],'driver.weights');d=driver(c,user);key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch','photo','photos')}).encode()).hexdigest();prior=c.execute('SELECT payload FROM driver_weight_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        result=json.loads(prior[0])
        if result['user_id']!=user['id'] or result['fingerprint']!=finger:raise ValueError('提交编号已使用')
        return result
    row=c.execute('SELECT payload FROM orders WHERE id=?',(b.get('order_id'),)).fetchone();old=json.loads(row[0]) if row else None
    if not old:raise ValueError('配送单不存在')
    _,owned=assigned(c,d['id'],old['business_date'])
    if old['id'] not in {o['id'] for o in owned}:raise auth.AuthError(403,'只能填写本人配送单的司机称重')
    if b.get('version')!=old['version']:raise ValueError('配送单已更新，请重新打开后核对')
    if old['state'] not in ('draft','dispatched') or old.get('weight_confirmation') or any(old.get(k) for k in ('paid_cents','discount_cents','rounding_cents','return_credit_cents')):raise ValueError('称重已确认或单据已进入结算，只能查看，请联系库管处理')
    photo_data=decode_photo(b.get('photo',''))
    photos=b.get('photos') or {}
    if not isinstance(photos,dict):raise ValueError('称重照片格式无效')
    import inventory
    inventory.open_day(c,old['business_date']);lines=b.get('lines')
    if not isinstance(lines,list) or not 1<=len(lines)<=200:raise ValueError('称重明细无效')
    new=json.loads(rc.dump(old));by_id={l['product_id']:l for l in new['lines']};seen=set()
    for raw in lines:
        if not isinstance(raw,dict) or raw.get('product_id') not in by_id or raw['product_id'] in seen:raise ValueError('称重产品无效或重复')
        seen.add(raw['product_id']);l=by_id[raw['product_id']];actual=__import__('decimal').Decimal(l['actual_qty'])
        if l['unit']=='筐':
            clean,net,count=weight_fn(raw.get('driver',[]),actual.to_integral_value(rounding='ROUND_CEILING'),'司机称重');l.update(driver=clean,driver_net=rc.ds(net),driver_count=rc.ds(count))
        elif l['unit']!='筐':
            kg=raw.get('package_net_kg','')
            if kg not in ('',None) and actual<=0:raise ValueError('未实发的产品不能填写称重')
            l['package_net_kg']=rc.ds(rc.qty(kg,'包装实称净重',True)) if kg not in ('',None) else ''
        else:raise ValueError('该产品暂不支持司机称重')
    new.update(version=old['version']+1,updated_at=now());save_fn(c,new);inventory.bump(c)
    for pid,value in photos.items():
        if pid not in by_id or by_id[pid].get('unit')!='筐':raise ValueError('称重照片产品无效')
        apply_photo_set(c,user,new['id'],'weight-'+pid,value,now())
    if photo_data:save_photo(c,user,new['id'],'weight',photo_data[0],photo_data[1],now())
    result={'order_id':new['id'],'version':new['version'],'user_id':user['id'],'fingerprint':finger};c.execute('INSERT INTO driver_weight_submissions VALUES(?,?)',(key,rc.dump(result)));audit(c,user['role'],'司机登记本人配送称重',new['id'],old,new);return result

def return_action(c,user,b,now,audit):
    access.require_role(user['role'],'driver.returns');driver(c,user);key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}).encode()).hexdigest();prior=c.execute('SELECT payload FROM driver_return_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        r=json.loads(prior[0])
        if r['user_id']!=user['id'] or r['fingerprint']!=finger:raise ValueError('提交编号已使用')
        return r
    row=c.execute('SELECT payload FROM driver_return_requests WHERE id=?',(b.get('id'),)).fetchone();old=json.loads(row[0]) if row else None
    if not old or old['user_id']!=user['id']:raise auth.AuthError(403,'只能处理本人的回筐填报')
    if b.get('version')!=old['version']:raise ValueError('填报已更新，请刷新后重试')
    action=b.get('action');r={**old,'version':old['version']+1,'fingerprint':finger,'updated_at':now()}
    if action=='delete' and old['state']=='draft':r['state']='deleted'
    elif action=='withdraw' and old['state']=='pending':r['state']='draft'
    elif action=='withdraw' and old['state']=='confirmed':r.update(state='withdraw_pending',withdraw_reason=rc.text(b.get('reason'),'撤回原因',500))
    else:raise ValueError('当前状态不能删除或撤回，请刷新核对')
    c.execute('UPDATE driver_return_requests SET payload=? WHERE id=?',(rc.dump(r),r['id']));c.execute('INSERT INTO driver_return_submissions VALUES(?,?)',(key,rc.dump(r)));audit(c,user['role'],'司机删除或撤回回筐',r['id'],old,r);return r

def review(c,kind,b,role,now,audit):
    access.require_role(role,'crates.confirm');key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}).encode()).hexdigest();prior=c.execute('SELECT payload FROM asset_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        r=json.loads(prior[0])
        if r.get('review_fingerprint')!=finger:raise ValueError('提交编号已使用')
        return r
    row=c.execute('SELECT payload FROM driver_return_requests WHERE id=?',(b.get('id'),)).fetchone();old=json.loads(row[0]) if row else None
    if not old or old['state'] not in ('pending','withdraw_pending') or b.get('version')!=old['version']:raise ValueError('该回筐填报已处理或已更新，请刷新')
    note=rc.text(b.get('note',''),'处理说明',500,kind=='driver-reject');r={**old,'state':'confirmed' if kind=='driver-confirm' else 'rejected','version':old['version']+1,'review_note':note,'reviewed_at':now(),'reviewer':role,'review_fingerprint':finger}
    if old['state']=='withdraw_pending':
        if kind=='driver-confirm':
            import assets
            for event in assets.rows(c):
                if event['kind']=='movement' and event.get('batch_id')==old.get('confirmed_batch_id') and not event.get('voided'):
                    assets.save(c,'void',{'id':event['id'],'version':event['version'],'request_key':'driver-withdraw:'+old['id']+':'+event['id'],'note':'库管确认司机撤回：'+old['withdraw_reason']},role,now,audit)
            r['state']='withdrawn'
        else:r['state']='confirmed'
    elif kind=='driver-confirm':
        import assets
        record=assets.save(c,'return-batch',{'request_key':'driver-confirm:'+old['id'],'business_date':old['business_date'],'driver_id':old['driver_id'],'vehicle_id':old['vehicle_id'],'trip':old['trip'],'source_date':old.get('source_date',''),'source_trip_id':old.get('source_trip_id',''),'source_vehicle_id':old.get('source_vehicle_id',''),'source_vehicle_name':old.get('source_vehicle_name',''),'lines':old['lines'],'note':old['note']+('；库管确认：'+note if note else '')},role,now,audit);r['confirmed_batch_id']=record['id']
    c.execute('UPDATE driver_return_requests SET payload=? WHERE id=?',(rc.dump(r),r['id']));c.execute('INSERT INTO asset_submissions VALUES(?,?)',(key,rc.dump(r)));audit(c,role,('库管确认回筐撤回' if kind=='driver-confirm' else '库管不予回筐撤回') if old['state']=='withdraw_pending' else '确认司机回筐' if kind=='driver-confirm' else '退回司机回筐',r['id'],old,r);return r

def print_delivery(c,user,day,trip_id,now):
    day=rc.day(day);d=driver(c,user);plan,orders=assigned(c,d['id'],day)
    if trip_id not in {t['id'] for t in plan['trips']}:raise auth.AuthError(403,'不能查看其他司机的配送单')
    mids={a['market_id'] for a in plan['assignments'] if a['trip_id']==trip_id};orders=[o for o in orders if plan['order_markets'][o['id']] in mids];cids={o['customer_id'] for o in orders};pids={l['product_id'] for o in orders for l in o['lines']}
    from printing import order_print_html
    return order_print_html({'company':__import__('company').current(c),'orders':orders,'customers':[dict(r) for r in c.execute('SELECT id,name,route,market_id FROM customers') if r['id'] in cids],'products':[dict(r) for r in c.execute('SELECT id,name,unit FROM products') if r['id'] in pids],'delivery_markets':[dict(r) for r in c.execute('SELECT * FROM delivery_markets') if r['id'] in mids],'dispatch_plans':[plan]}, {'date':[day],'mode':['trip'],'trip':[trip_id],'document':['delivery']},now())
