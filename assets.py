"""Reusable assets and daily crate counts, separate from consumable stock."""
import json,hashlib,secrets
import trade
from decimal import Decimal
from datetime import date,timedelta
import resources_costs as rc
import inventory,erp_access as access
CRATES={'P-LARGE':'大豆腐框','P-MEDIUM':'中豆腐框','P-SMOKED':'熏干框','P-KONJAC':'魔芋框','P-LONG':'长框'}
def rows(c):return rc.rows(c,'asset_records')

def _release_configuration(c,asset_id):
    """Drop current settings that point at a deleted type; historical payloads stay untouched."""
    released=[]
    row=c.execute("SELECT value FROM meta WHERE key='product_crate_attributes'").fetchone();cfg=json.loads(row[0]) if row else {}
    hit=[pid for pid,ids in cfg.items() if isinstance(ids,list) and asset_id in ids]
    touched=False
    for pid in hit:cfg[pid]=[v for v in cfg[pid] if v!=asset_id];touched=True
    import crate_accounting
    if asset_id in {v[0] for v in crate_accounting.VARIANTS}:
        for pid, in c.execute("SELECT id FROM products WHERE unit='筐' AND name='大豆腐'"):
            if pid not in cfg:cfg[pid]=[v[0] for v in crate_accounting.VARIANTS if v[0]!=asset_id];touched=True
    if touched:
        c.execute("INSERT INTO meta VALUES('product_crate_attributes',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(cfg),))
    if hit:released.append('产品可用框型 '+str(len(hit))+' 个产品')
    row=c.execute("SELECT value FROM meta WHERE key='product_crate_tares'").fetchone();tcfg=json.loads(row[0]) if row else {}
    hit=[pid for pid,tares in tcfg.items() if isinstance(tares,dict) and asset_id in tares]
    for pid in hit:tcfg[pid].pop(asset_id,None)
    if hit:
        c.execute("INSERT INTO meta VALUES('product_crate_tares',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(tcfg),));released.append('产品框型皮重 '+str(len(hit))+' 个产品')
    existing={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'customer_crate_tares' in existing:
        count=c.execute('SELECT COUNT(*) FROM customer_crate_tares WHERE variant_id=?',(asset_id,)).fetchone()[0]
        if count:
            c.execute('DELETE FROM customer_crate_tares WHERE variant_id=?',(asset_id,));released.append('客户框型皮重 '+str(count)+' 条')
    row=c.execute("SELECT value FROM meta WHERE key='crate_packaging_catalog_v1'").fetchone()
    if row:
        value=json.loads(row[0]);rules=[x for x in value.get('rules',[]) if x.get('asset_id')!=asset_id];removed=len(value.get('rules',[]))-len(rules)
        if removed:
            value['rules']=rules
            c.execute("INSERT INTO meta VALUES('crate_packaging_catalog_v1',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(value),));released.append('包装方式规则 '+str(removed)+' 条')
    return released

def _crate_references(value,ids,field=''):
    """Match structured identifiers exactly; never search names, notes or JSON text."""
    scalar={'asset_id','parent_asset_id','physical_asset_id','crate_asset_id','crate_type_id','variant_id','parent_id'}
    arrays={'asset_ids','expected_asset_ids','variant_ids','$ids'}
    found=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ids:found.add(key)
            if key in ('payload','before_json','after_json') and isinstance(item,str):
                try:item=json.loads(item)
                except (ValueError,TypeError):raise ValueError('历史框型引用数据格式异常，请先核查后再删除')
            found.update(_crate_references(item,ids,key))
    elif isinstance(value,list):
        for item in value:found.update(_crate_references(item,ids,field))
    elif isinstance(value,str) and field in scalar|arrays and value in ids:found.add(value)
    return found

def deletion_statuses(c,allrows=None):
    """Read-only usage index, shared by the report and the guarded delete write."""
    allrows=rows(c) if allrows is None else allrows
    types={r['id']:r for r in allrows if r['kind']=='asset' and r['category']=='周转筐'}
    ids=set(types);history={key:set() for key in ids};config={key:set() for key in ids}
    def add(value,label,configuration=False,field=''):
        target=config if configuration else history
        for key in _crate_references(value,ids,field):target[key].add(label)
    for row in allrows:
        if row['kind']=='asset':
            if not row.get('deleted'):add(row,'所属框型下仍有属性',True)
        else:add(row,'产品框型对应设置' if row['kind']=='mapping' else '框子业务或盘点记录',row['kind']=='mapping')
    existing={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    tables={'orders':'销售订单','trade_records':'配送业务','trade_submissions':'配送提交记录',
            'archived_orders':'归档订单','trial_archives':'测试业务归档','driver_return_requests':'司机回框填报',
            'driver_return_submissions':'司机回框提交','driver_weight_submissions':'司机称重提交',
            'order_corrections':'实发更正记录','order_correction_submissions':'实发更正提交',
            'statement_documents':'客户结算单','sales_returns':'退货记录','stock_closings':'库存日结',
            'warehouse_plans':'库存发货计划','dispatch_plans':'配送计划','asset_submissions':'框子提交记录'}
    for table,label in tables.items():
        if table not in existing:continue
        columns={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
        if 'payload' not in columns:continue
        for row in c.execute('SELECT payload FROM '+table):
            value=json.loads(row[0])
            # Configuration receipts are obsolete snapshots, not current settings.
            # Current asset/mapping/meta references were checked separately.
            if table=='asset_submissions' and value.get('kind') in ('asset','mapping','delete-asset'):
                continue
            else:add(value,label)
    if 'audit' in existing:
        configuration_entities={'crate_packaging_catalog_v1','product_crate_attributes','product_crate_tares'}
        for row in c.execute('SELECT entity,before_json,after_json FROM audit'):
            if row[0] in configuration_entities:continue
            for raw in (row[1],row[2]):
                if raw in (None,'','null'):continue
                value=json.loads(raw)
                if isinstance(value,dict) and value.get('kind') in ('asset','mapping','delete-asset'):
                    continue
                else:add(value,'历史业务审计记录')
    for key,label in (('product_crate_attributes','产品可用框型设置'),('product_crate_tares','产品框型皮重设置'),('crate_packaging_catalog_v1','包装方式配置')):
        row=c.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        if row:
            value=json.loads(row[0])
            if key=='product_crate_attributes':
                for selected in value.values():add(selected,label,True,'$ids')
            else:add(value,label,True)
    # The legacy default selection is an effective product configuration too.
    import crate_accounting
    row=c.execute("SELECT value FROM meta WHERE key='product_crate_attributes'").fetchone();settings=json.loads(row[0]) if row else {}
    for product in c.execute("SELECT id,name FROM products WHERE unit='筐'"):
        if product['name']=='大豆腐' and product['id'] not in settings:add([v[0] for v in crate_accounting.VARIANTS],'产品默认框型设置',True,'$ids')
    if 'customer_crate_tares' in existing:
        for row in c.execute('SELECT variant_id FROM customer_crate_tares'):add(row[0],'客户框型皮重设置',True,'variant_id')
    result={}
    for key in ids:
        h=sorted(history[key]);cfg=sorted(config[key]);reasons=h+cfg
        result[key]={'can_delete':not reasons,'reasons':reasons,'history_reasons':h,'configuration_reasons':cfg}
    return result

def deletion_status(c,asset_id):
    return deletion_statuses(c).get(asset_id,{'can_delete':False,'reasons':['框型不存在'],'history_reasons':[],'configuration_reasons':[]})
def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'assets')

def integer(value,label):
    v=rc.qty(value,label)
    if v!=v.to_integral_value():raise ValueError(label+'必须是整数个数')
    return int(v)
def return_comparison(c,day,allrows,mapping,types):
    yesterday=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
    orders=[o for o in rc.rows(c,'orders') if o['business_date']==yesterday and o.get('delivery_method')!='pickup']
    plan=next((p for p in rc.rows(c,'dispatch_plans') if p['business_date']==yesterday),{})
    trips={t['id']:t for t in plan.get('trips',[])};assignments={a['market_id']:a.get('trip_id') for a in plan.get('assignments',[])}
    returned=[r for r in allrows if r['kind']=='movement' and r.get('movement')=='return' and r['business_date']==day and not r.get('voided')]
    groups={};expected={};issues=[];unknown_types=False
    def group(key,vehicle_id='',vehicle_name='',driver_ids=None,driver=''):
        g=groups.setdefault(key,{'key':key,'vehicle_id':vehicle_id,'vehicle_name':vehicle_name,'driver_ids':[],'driver':'','shipped':{},'returned':{},'issues':[]})
        g['driver_ids']=list(dict.fromkeys([*g['driver_ids'],*(driver_ids or [])]));g['driver']='、'.join(dict.fromkeys(filter(None,[*g['driver'].split('、'),*driver.split('、')])));return g
    def add(target,asset_id,qty):target[asset_id]=target.get(asset_id,Decimal(0))+Decimal(qty)
    for o in orders:
        market=plan.get('order_markets',{}).get(o['id']);trip=trips.get(assignments.get(market),{})
        ids=trip.get('driver_ids') or ([trip['driver_id']] if trip.get('driver_id') else [])
        vid=trip.get('vehicle_id','');key='vehicle:'+vid if vid else 'driver:'+ids[0] if len(ids)==1 else 'unassigned:'+o['id']
        g=group(key,vid,trip.get('vehicle_name',''),ids,trip.get('driver',''))
        if not trip:g['issues'].append('昨日订单未关联配送趟次')
        elif not vid and len(ids)!=1:g['issues'].append('昨日未明确车辆或唯一司机')
        typed=trade.shipped_crates(c,o) if 'customer_id' in o else []
        if typed:
            for line in typed:
                add(expected,line['asset_id'],line['qty']);add(g['shipped'],line['asset_id'],line['qty'])
        else:
            for line in o['lines']:
                qty=Decimal(line.get('actual_qty') or '0')
                if line.get('unit')!='筐' or qty<=0:continue
                asset_id=mapping.get(line['product_id'])
                if not asset_id:issues.append(line['product_name']+'昨日实发未对应筐型');g['issues'].append('有产品未对应筐型');unknown_types=True;continue
                add(expected,asset_id,qty);add(g['shipped'],asset_id,qty)

    for r in returned:
        vid=r.get('source_vehicle_id') or r.get('vehicle_id','');did=r.get('driver_id','');key='vehicle:'+vid if vid else 'driver:'+did if did else 'legacy:'+r['id']
        g=group(key,vid,r.get('source_vehicle_name') or r.get('vehicle_name',''),[did] if did else [],r.get('driver',''));add(g['returned'],r['asset_id'],r['qty'])
        if r.get('source_date') and r['source_date']!=yesterday:g['issues'].append('原配送日期为 '+r['source_date']+'，不直接按昨日核对')
        if not vid and not did:g['issues'].append('历史回筐未关联司机或车辆档案')
        if not vid and did:
            linked=[x for x in groups.values() if x['vehicle_id'] and did in x['driver_ids']]
            if linked:
                g['issues'].append('回筐未选择车辆，暂不能归入昨日车辆')
                for x in linked:x['issues'].append('有该司机回筐未选择车辆，需先核对归属')
    for g in groups.values():
        if not g['driver'] and g['driver_ids']:g['driver']='、'.join(r['name'] for r in c.execute('SELECT id,name FROM delivery_drivers') if r['id'] in g['driver_ids'])
        if not g['vehicle_name'] and g['vehicle_id']:
            row=c.execute('SELECT name FROM delivery_vehicles WHERE id=?',(g['vehicle_id'],)).fetchone();g['vehicle_name']=row[0] if row else g['vehicle_id']
    def compare(asset,ship,back,pending):
        delta=back-ship
        return {'asset_id':asset['id'],'asset_name':asset['name'],'yesterday_qty':rc.ds(ship),'returned_qty':rc.ds(back),'difference_qty':rc.ds(delta),'status':'pending' if pending else 'mismatch' if delta else 'matched','issues':list(dict.fromkeys(pending))}
    summary=[];details=[]
    for a in types:
        members={a['id']}|{x['id'] for x in types if x.get('parent_asset_id')==a['id']}
        total=sum((Decimal(r['qty']) for r in returned if r['asset_id'] in members),Decimal(0));pending=issues if unknown_types else []
        if not orders and not plan:pending=[*pending,'昨日无配送记录，待核对']
        if any(r['asset_id']==a['id'] and r.get('source_date') and r['source_date']!=yesterday for r in returned):pending=[*pending,'含其他配送日期回筐，请按原配送日期核对']
        summary.append(compare(a,sum((expected.get(i,Decimal(0)) for i in members),Decimal(0)),total,pending))
        for g in groups.values():
            ship=sum((g['shipped'].get(i,Decimal(0)) for i in members),Decimal(0));back=sum((g['returned'].get(i,Decimal(0)) for i in members),Decimal(0))
            if not ship and not back:continue
            pending=list(g['issues'])
            if unknown_types:pending+=issues
            if not orders and not plan:pending.append('昨日无配送记录，待核对')
            details.append({**compare(a,ship,back,pending),'vehicle_id':g['vehicle_id'],'vehicle_name':g['vehicle_name'],'driver_ids':g['driver_ids'],'driver':g['driver']})
    return {'yesterday':yesterday,'summary':summary,'details':details,'issues':list(dict.fromkeys(issues))}

def report(c,day):
    import crate_accounting
    day=rc.day(day);allrows=rows(c);statuses=deletion_statuses(c,allrows)
    alive=[r for r in allrows if r['kind']=='asset' and not r.get('deleted')]
    def deletion_view(row):
        status=statuses.get(row['id'])
        if not status:return {'can_delete':False,'delete_reason':'框型状态未知，请刷新后再试'}
        children=[x['name'] for x in alive if x.get('parent_asset_id')==row['id']]
        if children:return {'can_delete':False,'delete_reason':'先删除该框型下的属性：'+'、'.join(children),'deletion_status':status}
        note=''
        if status['history_reasons']:note='历史单据保留原名称，删除后从所有选择项移除'
        elif status['configuration_reasons']:note='删除时自动解除：'+'；'.join(status['configuration_reasons'])
        return {'can_delete':True,'delete_reason':note,'deletion_status':status}
    assets=[{**r,**deletion_view(r)} for r in alive];types=[a for a in assets if a['category']=='周转筐'];mapping={r['product_id']:r['asset_id'] for r in allrows if r['kind']=='mapping'}
    products=[dict(r) for r in c.execute('SELECT id,name,unit FROM products ORDER BY id')]
    defaults={'大豆腐':'P-LARGE','中豆腐':'P-MEDIUM','熏干':'P-SMOKED','魔芋':'P-KONJAC'}
    for p in products:
        if p['id'] not in mapping and p['name'] in defaults:mapping[p['id']]=defaults[p['name']]
    stock=inventory.stock(c,day)['products'];counts=[r for r in allrows if r['kind']=='count' and r['business_date']==day];events=[r for r in allrows if r['kind']=='movement' and r['business_date']==day and not r.get('voided')];result=[]
    variant_map={p['id']:crate_accounting.variants(c,p['id']) for p in products}
    ambiguous={}
    for pid,vs in variant_map.items():
        if vs and len(vs)==1:mapping[pid]=vs[0]['parent_id']
        if len(vs)>1:
            parents={v['parent_id'] for v in vs}
            if len(parents)==1:mapping[pid]=next(iter(parents))
            else:mapping.pop(pid,None)
            for v in vs:ambiguous.setdefault(v['id'],[]).append(pid)
    unmapped=[p for p in stock if p['unit']=='筐' and not variant_map.get(p['product_id'])]
    for a in types:
        ps=[p for p in stock if mapping.get(p['product_id'])==a['id'] and p['unit']=='筐'];missing=[p['product_name'] for p in ps if p['counted_qty']==''];occupied=None if missing else sum((Decimal(p['counted_qty']) for p in ps),Decimal(0));count=next((r for r in counts if r['asset_id']==a['id']),None)
        split=[p['product_name']+'（多框型待拆分）' for p in stock if p['product_id'] in ambiguous.get(a['id'],[]) and p['product_id'] not in {x['product_id'] for x in ps}]
        if split:missing+=split;occupied=None
        ev=[r for r in events if r['asset_id']==a['id']];empty=count['empty_qty'] if count else None;damaged=count['damaged_qty'] if count else None
        result.append({**a,'occupied_qty':None if occupied is None else rc.ds(occupied),'empty_qty':empty,'damaged_qty':damaged,'total_qty':None if occupied is None or empty is None else rc.ds(occupied+empty+damaged),'missing_products':missing,'shipped_qty':rc.ds(sum((Decimal(str(line['qty'])) for o in rc.rows(c,'orders') if o['business_date']==day for line in trade.shipped_crates(c,o) if line['asset_id']==a['id']),Decimal(0))) if a.get('parent_asset_id') else rc.ds(sum((Decimal(p['shipped_qty']) for p in ps),Decimal(0))),'returned_qty':sum(r['qty'] for r in ev if r['movement']=='return'),'received_qty':sum(r['qty'] for r in ev if r['movement']=='receipt'),'scrapped_qty':sum(r['qty'] for r in ev if r['movement']=='scrap'),'count':count})
    import driver_portal,crate_inventory
    return crate_inventory.decorate(c,day,{'return_requests':driver_portal.pending(c),'comparison':return_comparison(c,day,allrows,mapping,types),'drivers':[dict(r) for r in c.execute('SELECT id,name FROM delivery_drivers WHERE active=1 ORDER BY name,id')],'vehicles':[dict(r) for r in c.execute('SELECT id,name FROM delivery_vehicles WHERE active=1 ORDER BY name,id')],'business_date':day,'assets':assets,'crates':result,'events':events,'mappings':[r for r in allrows if r['kind']=='mapping'],'products':[{**p,'asset_id':mapping.get(p['id'],''),'asset_ids':[v['id'] for v in crate_accounting.variants(c,p['id'])]} for p in products if p['unit']=='筐'],'unmapped':unmapped},stock)
def save(c,kind,b,role,now,audit):
    if kind in ('driver-confirm','driver-reject'):
        import driver_portal
        return driver_portal.review(c,kind,b,role,now,audit)
    access.require_role(role,'assets.write' if kind in ('asset','delete-asset') else 'crates.write')
    key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}).encode()).hexdigest();prior=c.execute('SELECT payload FROM asset_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        r=json.loads(prior[0])
        if r.get('fingerprint')!=finger:raise ValueError('提交编号已使用，请重新打开表单')
        return r
    if kind=='delete-asset':
        old=next((r for r in rows(c) if r['id']==b.get('id') and r['kind']=='asset' and r['category']=='周转筐'),None)
        if not old:raise ValueError('框型不存在，请刷新后重试')
        if int(b.get('version',0))!=old['version']:raise ValueError('记录已更新，请刷新后重试')
        children=[r['name'] for r in rows(c) if r['kind']=='asset' and r.get('parent_asset_id')==old['id'] and not r.get('deleted')]
        if children:raise ValueError('请先删除该框型下的属性：'+'、'.join(children))
        released=_release_configuration(c,old['id'])
        status=deletion_status(c,old['id'])
        soft=bool(status['history_reasons'])
        if soft:
            r={**old,'active':False,'deleted':True,'deleted_at':now(),'version':old['version']+1}
            c.execute('UPDATE asset_records SET payload=? WHERE id=?',(rc.dump(r),old['id']))
            result={'id':old['id'],'kind':'delete-asset','deleted':True,'soft':True,'version':r['version'],'released':released,'fingerprint':finger}
            c.execute('INSERT INTO asset_submissions VALUES(?,?)',(key,rc.dump(result)))
            audit(c,role,'删除框型（历史单据保留归档）',old['id'],old,result)
            return result
        result={'id':old['id'],'kind':'delete-asset','deleted':True,'soft':False,'version':old['version'],'released':released,'fingerprint':finger}
        c.execute('DELETE FROM asset_records WHERE id=?',(old['id'],))
        c.execute('INSERT INTO asset_submissions VALUES(?,?)',(key,rc.dump(result)))
        audit(c,role,'删除未使用框型',old['id'],old,result)
        return result
    if kind=='return-batch':
        day=rc.day(b.get('business_date'));driver=c.execute('SELECT id,name FROM delivery_drivers WHERE id=? AND active=1',(b.get('driver_id'),)).fetchone()
        if not driver:raise ValueError('请选择系统中启用的司机')
        vehicle=c.execute('SELECT id,name FROM delivery_vehicles WHERE id=? AND active=1',(b.get('vehicle_id'),)).fetchone() if b.get('vehicle_id') else None
        if b.get('vehicle_id') and not vehicle:raise ValueError('所选车辆不存在，请刷新后重试')
        trip=rc.text(b.get('trip',''),'趟次',100,False);note=rc.text(b.get('note',''),'备注',500,False);lines=b.get('lines')
        if not isinstance(lines,list) or not 1<=len(lines)<=200:raise ValueError('请至少填写一种筐型的回筐数量')
        types={r['id']:r for r in rows(c) if r['kind']=='asset' and r['category']=='周转筐' and r.get('active',True)};seen=set();records=[];lines=trade.return_lines(c,lines,b.get('source_date',''),b.get('source_trip_id',''),b.get('by_order') is True);batch_id='CR-'+secrets.token_hex(8)
        for line in lines:
            if not isinstance(line,dict):raise ValueError('回筐明细格式无效')
            asset_id=line.get('asset_id');asset=types.get(asset_id)
            if not asset or (line.get('order_id',''),asset_id) in seen:raise ValueError('筐型无效或重复，请核对回筐列表')
            seen.add((line.get('order_id',''),asset_id));qty=integer(line.get('qty'),'回筐数量')
            if qty<=0:raise ValueError('回筐数量必须大于零')
            records.append({'order_id':line.get('order_id',''),'customer_id':line.get('customer_id',''),'customer_name':line.get('customer_name',''),'id':'AS-'+secrets.token_hex(8),'kind':'movement','movement':'return','batch_id':batch_id,'source_date':rc.day(b['source_date']) if b.get('source_date') else '', 'source_trip_id':rc.text(b.get('source_trip_id',''),'原趟次编号',100,False),'source_vehicle_id':rc.text(b.get('source_vehicle_id',''),'原配送车辆编号',100,False),'source_vehicle_name':rc.text(b.get('source_vehicle_name',''),'原配送车辆',100,False),'business_date':day,'asset_id':asset_id,'asset_name':asset['name'],'qty':qty,'driver_id':driver['id'],'driver':driver['name'],'vehicle_id':vehicle['id'] if vehicle else '', 'vehicle_name':vehicle['name'] if vehicle else '', 'trip':trip,'note':note,'handler':role,'updated_at':now(),'version':1})
        for r in records:c.execute('INSERT INTO asset_records VALUES(?,?,?)',(r['id'],'return-line:'+r['id'],rc.dump(r)))
        result={'id':batch_id,'kind':'return-batch','lines':records,'fingerprint':finger}
        c.execute('INSERT INTO asset_submissions VALUES(?,?)',(key,rc.dump(result)));audit(c,role,'登记司机回筐',batch_id,None,result);return result
    allrows=rows(c);old=next((r for r in allrows if r['id']==b.get('id')),None)
    if kind=='count':old=next((r for r in allrows if r['kind']=='count' and r['business_date']==b.get('business_date') and r['asset_id']==b.get('asset_id')),None)
    if kind=='mapping':old=next((r for r in allrows if r['kind']=='mapping' and r['product_id']==b.get('product_id')),None)
    if kind=='occupied-count':old=next((r for r in allrows if r['kind']=='occupied-count' and r['business_date']==b.get('business_date') and r['product_id']==b.get('product_id')),None)
    if old and kind!='void' and (old['kind']!=kind or int(b.get('version',0))!=old['version']):raise ValueError('记录已更新，请刷新后重试')
    if kind=='void':
        if not old or old['kind']!='movement' or old.get('voided') or int(b.get('version',0))!=old['version']:raise ValueError('流水已更新或已作废，请刷新')
        r={**old,'voided':True,'void_reason':rc.text(b.get('note'),'作废原因',500),'version':old['version']+1,'updated_at':now(),'fingerprint':finger}
        c.execute('UPDATE asset_records SET payload=? WHERE id=?',(rc.dump(r),old['id']));c.execute('INSERT INTO asset_submissions VALUES(?,?)',(key,rc.dump(r)));audit(c,role,'作废筐子流水',old['id'],old,r);return r
    if kind=='occupied-count':
        import crate_accounting
        when=rc.day(b.get('business_date'))
        if b.get('inventory_revision')!=inventory.revision(c):raise ValueError('产品库存已更新，请刷新后重新盘点装货框')
        p=next((x for x in inventory.stock(c,when)['products'] if x['product_id']==b.get('product_id') and x['unit']=='筐'),None)
        if not p or p['counted_qty']=='':raise ValueError('请先在库存中盘点该产品结存')
        allowed={x['id'] for x in crate_accounting.variants(c,p['product_id'])}|{x['parent_id'] for x in crate_accounting.variants(c,p['product_id'])};lines=b.get('lines');seen=set();out=[]
        if not isinstance(lines,list) or not lines:raise ValueError('请填写装货框属性数量')
        for x in lines:
            if x.get('asset_id') not in allowed or x['asset_id'] in seen:raise ValueError('装货框属性无效或重复')
            seen.add(x['asset_id']);out.append({'asset_id':x['asset_id'],'qty':integer(x.get('qty'),'装货框数')})
        if sum(x['qty'] for x in out)!=Decimal(p['counted_qty']):raise ValueError('各属性装货框合计必须等于该产品盘点结存 '+str(p['counted_qty']))
        r={'business_date':when,'product_id':p['product_id'],'product_name':p['product_name'],'counted_qty':p['counted_qty'],'lines':out}
    elif kind=='asset':
        category=b.get('category')
        if category not in ('周转筐','设备','车辆','其他'):raise ValueError('资产分类无效')
        if old and old['category']!=category:raise ValueError('已建资产不允许改分类')
        r={'name':rc.text(b.get('name'),'资产名称',80),'category':category,'unit':'个' if category=='周转筐' else rc.text(b.get('unit'),'单位',20),'location':rc.text(b.get('location',''),'存放地点',80,False),'custodian':rc.text(b.get('custodian',''),'责任人',60,False),'active':b.get('active',True) is not False}
        if category=='周转筐':
            if 'special_packaging' in b:
                import crate_packaging
                r['special_packaging']=crate_packaging.normalize_asset_settings(b['special_packaging'],prior=(old or {}).get('special_packaging',[]))
            elif old and 'special_packaging' in old:r['special_packaging']=old['special_packaging']
            parent=b.get('parent_asset_id',(old or {}).get('parent_asset_id','')) or ''
            if parent:
                a=next((x for x in allrows if x['id']==parent and x['kind']=='asset' and x['category']=='周转筐' and not x.get('parent_asset_id')),None)
                if not a or parent==b.get('id') or b.get('id') and any(x.get('parent_asset_id')==b['id'] for x in allrows):raise ValueError('属性必须归属有效的顶层框型，不能循环或多层嵌套')
                if a.get('active') is False and (not old or old.get('parent_asset_id')!=parent):raise ValueError('请先启用所属顶层框型再添加属性')
            if old and parent!=old.get('parent_asset_id',''):
                # Changing a used type's parent would rewrite historical balances.
                referenced=any(old['id'] in json.dumps(x,ensure_ascii=False) for x in allrows if x['kind']!='asset') or any(old['id'] in json.dumps(x,ensure_ascii=False) for table in ('orders','trade_records') for x in rc.rows(c,table))
                if referenced:raise ValueError('该框型已有业务或盘点引用，不能更改所属框型；请新增属性并停用旧属性')
            if parent:r.update(parent_asset_id=parent,attribute_kind=rc.text(b.get('attribute_kind',(old or {}).get('attribute_kind','spec')),'属性类别',20),attribute_name=r['name'])
            if 'unit_cost' in b:
                raw=str(b.get('unit_cost','')).strip()
                r['unit_cost_cents']=0 if not raw else rc.cents(raw,'单个成本')
            elif old and 'unit_cost_cents' in old:r['unit_cost_cents']=old['unit_cost_cents']
            if 'safety_stock' in b:
                raw=str(b.get('safety_stock','')).strip()
                r['safety_stock']=integer(raw,'安全库存') if raw else ''
            elif old and 'safety_stock' in old:r['safety_stock']=old['safety_stock']
            if 'default_tare' in b or old and 'default_tare' in old:
                value=b.get('default_tare',old.get('default_tare','') if old else '')
                if str(value).strip():
                    tare=rc.qty(value,'默认单框皮重')
                    if tare>100:raise ValueError('默认单框皮重不能超过100公斤')
                    r['default_tare']=rc.ds(tare)
        else:r['quantity']=integer(b.get('quantity','0'),'资产数量')
    else:
        if kind=='mapping' and 'asset_ids' in b:
            if not isinstance(b['asset_ids'],list) or not b['asset_ids']:raise ValueError('请至少选择一种对应框型')
            b={**b,'asset_id':b['asset_ids'][0]}
        a=next((r for r in allrows if r['id']==b.get('asset_id') and r['kind']=='asset' and r['category']=='周转筐'),None)
        if not a:raise ValueError('请选择有效筐型')
        r={'asset_id':a['id'],'asset_name':a['name']}
        if kind=='mapping':
            p=c.execute('SELECT * FROM products WHERE id=?',(b.get('product_id'),)).fetchone()
            if not p or p['unit']!='筐':raise ValueError('请选择按筐计数的产品')
            import crate_accounting
            ids=b.get('asset_ids',[a['id']])
            if 'expected_asset_ids' in b and b['expected_asset_ids']!=[v['id'] for v in crate_accounting.variants(c,p['id'])]:raise ValueError('产品框型已在其他页面修改，请刷新后重试')
            crate_accounting.set_variants(c,p['id'],ids)
            r.update(product_id=p['id'],asset_ids=ids)
        elif kind=='count':
            parent_count=next((x for x in allrows if x['kind']=='count' and x['business_date']==b.get('business_date') and x['asset_id']==a.get('parent_asset_id')),None)
            if parent_count and 'attribute_counts' in parent_count:raise ValueError('该属性已由父框统一盘点，请编辑父框盘点明细')
            if old and 'attribute_counts' in old and 'attribute_counts' not in b:raise ValueError('请填写父框下各属性盘点明细，不能覆盖为单一总数')
            r.update(business_date=rc.day(b.get('business_date')),empty_qty=integer(b.get('empty_qty'),'空筐数'),damaged_qty=integer(b.get('damaged_qty','0'),'破损待处理筐数'))
            if 'attribute_counts' in b:
                children={x['id'] for x in allrows if x['kind']=='asset' and x.get('parent_asset_id')==a['id']};lines=b['attribute_counts'];seen=set();out=[]
                if not isinstance(lines,list):raise ValueError('属性盘点格式无效')
                for x in lines:
                    if x.get('asset_id') not in children or x['asset_id'] in seen:raise ValueError('属性盘点无效或重复')
                    seen.add(x['asset_id']);out.append({'asset_id':x['asset_id'],'empty_qty':integer(x.get('empty_qty'),'属性空框数'),'damaged_qty':integer(x.get('damaged_qty'),'属性破损框数')})
                if seen!=children:raise ValueError('框型属性已更新，请刷新后盘点全部属性')
                ue=integer(b.get('unclassified_empty_qty','0'),'未分属性空框数');ud=integer(b.get('unclassified_damaged_qty','0'),'未分属性破损数')
                if r['empty_qty']!=sum(x['empty_qty'] for x in out)+ue or r['damaged_qty']!=sum(x['damaged_qty'] for x in out)+ud:raise ValueError('父框盘点总数必须等于属性明细加未分属性数量')
                r.update(attribute_counts=out,unclassified_empty_qty=ue,unclassified_damaged_qty=ud)
        elif kind=='movement':
            if old:raise ValueError('流水不允许覆盖，请作废后重新登记')
            movement=b.get('movement')
            if movement not in ('return','receipt','scrap'):raise ValueError('筐子流水类型无效')
            qty=integer(b.get('qty'),'筐数')
            if qty<=0:raise ValueError('筐数必须大于零')
            if movement=='receipt' and str(b.get('unit_cost','')).strip():
                cost=rc.cents(b.get('unit_cost'),'单个成本');r['unit_cost_cents']=cost
                target=next((x for x in allrows if x['id']==b.get('asset_id') and x['kind']=='asset'),{})
                if target:
                    target={**target,'unit_cost_cents':cost,'version':target['version']+1,'updated_at':now()}
                    c.execute('UPDATE asset_records SET payload=? WHERE id=?',(rc.dump(target),target['id']))
            r.update(business_date=rc.day(b.get('business_date')),movement=movement,qty=qty,driver=rc.text(b.get('driver',''),'司机姓名',60,movement=='return'),trip=rc.text(b.get('trip',''),'车牌 / 趟次',100,False))
        elif kind=='void':raise ValueError('无效操作')
        else:raise ValueError('未知资产操作')
    r.update(id=(old or {}).get('id','AS-'+secrets.token_hex(8)),kind=kind,version=(old or {}).get('version',0)+1,note=rc.text(b.get('note',''),'备注',500,False),handler=role,updated_at=now(),fingerprint=finger)
    if old:c.execute('UPDATE asset_records SET request_key=?,payload=? WHERE id=?',(key,rc.dump(r),r['id']))
    else:c.execute('INSERT INTO asset_records VALUES(?,?,?)',(r['id'],key,rc.dump(r)))
    c.execute('INSERT INTO asset_submissions VALUES(?,?)',(key,rc.dump(r)))
    audit(c,role,'资产登记',r['id'],old,r);return r
