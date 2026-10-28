"""Independent pre/post dispatch counts, compared with live registered shipments.
Uses the existing audited trade record/submission stores; never rewrites stock,
orders, settlement, or a driver's liability. Caller owns the transaction.
"""
from decimal import Decimal
import hashlib,json
import erp_access as access
import resources_costs as rc

RULE='pre-post-dispatch-v1'

def digest(value):return hashlib.sha256(rc.dump(value).encode()).hexdigest()
def saved(c,day):
    r=c.execute('SELECT payload FROM trade_records WHERE id=?',('IC-'+day,)).fetchone()
    return json.loads(r[0]) if r else None

def shipments(c,day):
    rows=[]
    for o in rc.rows(c,'orders'):
        if o['business_date']!=day:continue
        for l in o['lines']:
            rows.append({'order_id':o['id'],'customer_id':o['customer_id'],'customer_name':o['customer_name'],'product_id':l['product_id'],'unit':l['unit'],'actual_qty':rc.ds(l.get('actual_qty') or '0'),'ordered_qty':rc.ds(l.get('ordered_qty') or '0')})
    return sorted(rows,key=lambda r:(r['order_id'],r['product_id']))

def report(c,day):
    rc.day(day);record=saved(c,day);source=shipments(c,day);finger=digest(source)
    changed=bool(record and record['source_fingerprint']!=finger)
    counts={r['product_id']:r for r in (record or {}).get('products',[])}
    closing=next((r for r in rc.rows(c,'stock_closings') if r['business_date']==day and r['state']=='closed'),None)
    closing_counts={r['product_id']:r for r in (closing or {}).get('products',[])}
    result=[]
    for p in c.execute('SELECT id,name,unit FROM products ORDER BY id'):
        r=counts.get(p['id'],{});pre=r.get('pre_qty','');post=r.get('post_qty','');inc=r.get('post_in_qty','0');out=r.get('post_out_qty','0')
        lines=[l for l in source if l['product_id']==p['id']]
        same=all(l['unit']==p['unit'] for l in lines) and (not r or r['unit']==p['unit'])
        shipped=sum((Decimal(l['actual_qty']) for l in lines),Decimal(0))
        checked=(record or {}).get('sources_checked',False)
        known=same and pre!='' and post!='' and checked
        expected=Decimal(pre)-shipped+Decimal(inc)-Decimal(out) if pre!='' and same else None
        delta=Decimal(post)-expected if known else None
        closing_changed=r.get('post_source')=='closing' and (not closing or r.get('closing_version')!=closing['version'])
        status='结存来源已变更，请重新带入核对' if closing_changed else '单位变更，待核对' if not same else '实盘待补' if pre=='' or post=='' else '实发及增减完整性待确认' if not checked else '实发来源已变更，请重新核对' if changed else '应剩为负，请核查实盘及实发' if expected<0 else '已对平' if delta==0 else '有差异待核查'
        result.append({'product_id':p['id'],'product_name':p['name'],'unit':p['unit'],'pre_qty':pre,'post_qty':post,'post_in_qty':inc,'post_out_qty':out,'movement_note':r.get('movement_note',''),'post_source':r.get('post_source','manual'),'closing_version':r.get('closing_version'),'shipped_qty':rc.ds(shipped) if same else None,'expected_qty':rc.ds(expected) if expected is not None else None,'difference_qty':rc.ds(delta) if delta is not None else None,'status':status,'closing_qty':closing_counts.get(p['id'],{}).get('counted_qty'),'orders':lines})
    orders={o['id']:o for o in rc.rows(c,'orders') if o['business_date']==day}
    feedback=[{k:r.get(k) for k in ('id','order_id','product_id','product_name','unit','actual_qty','received_qty','difference_qty','feedback_date','note','state','resolution')} for r in rc.rows(c,'trade_records') if r.get('kind')=='feedback' and r.get('order_id') in orders]
    return {'business_date':day,'rule':RULE,'version':(record or {}).get('version',0),'source_fingerprint':finger,'source_changed':changed,'sources_checked':(record or {}).get('sources_checked',False),'handler':(record or {}).get('handler',''),'note':(record or {}).get('note',''),'updated_at':(record or {}).get('updated_at'),'products':result,'feedback':feedback,'history':(record or {}).get('history',[]),'closing_version':(closing or {}).get('version'),'basis':'发货前实盘－本业务日已登记实发＋发货后其他入库－发货后其他出库＝应剩；发货后实盘－应剩＝差异。数量按产品原单位，退货隔离不计可发。未确认实发完整或未核实增减时保留待核对；正差异不自动认定少送，负差异不自动认定司机多送。'}

def save(c,b,role,now,audit):
    access.require_role(role,'inventory.stock')
    key=rc.text(b.get('request_key'),'提交编号',100);finger=digest({'kind':'inventory-check',**{k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}})
    prior=c.execute('SELECT payload FROM trade_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        result=json.loads(prior[0])
        if result.get('fingerprint')!=finger:raise ValueError('提交编号已用于其他内容，请重新读取')
        return result
    day=rc.day(b.get('business_date'));rc.open_period(c,day);old=saved(c,day)
    if type(b.get('version')) is not int or b['version']!=(old or {}).get('version',0):raise ValueError('核对记录已更新，请重新读取')
    current=shipments(c,day)
    if b.get('source_fingerprint')!=digest(current):raise ValueError('实发记录已变化，请重新读取并核对，未覆盖本次实盘')
    if type(b.get('sources_checked')) is not bool:raise ValueError('请明确确认实发与发货后增减完整性')
    raw=b.get('products');products={p['id']:dict(p) for p in c.execute('SELECT id,name,unit FROM products')}
    if not isinstance(raw,list) or len(raw)>len(products):raise ValueError('产品核对格式无效')
    import trade
    units={u['id']:u['fractional'] for u in trade.units(c)};rows=[];seen=set()
    for r in raw:
        if not isinstance(r,dict) or r.get('product_id') not in products or r['product_id'] in seen:raise ValueError('产品不存在或重复，请刷新')
        p=products[r['product_id']];seen.add(p['id'])
        if r.get('unit')!=p['unit']:raise ValueError('产品单位已变化，请重新核对')
        row={'product_id':p['id'],'unit':p['unit']}
        for field in ('pre_qty','post_qty','post_in_qty','post_out_qty'):
            value=r.get(field,'' if field in ('pre_qty','post_qty') else '0')
            if value in ('',None) and field in ('pre_qty','post_qty'):row[field]='';continue
            q=rc.qty(value,'实盘 / 增减数量')
            if not units.get(p['unit'],False) and q!=q.to_integral_value():raise ValueError(p['name']+'按'+p['unit']+'核对须填整数')
            row[field]=rc.ds(q)
        row['movement_note']=rc.text(r.get('movement_note',''),'发货后增减依据',500,False)
        if (Decimal(row['post_in_qty']) or Decimal(row['post_out_qty'])) and not row['movement_note']:raise ValueError(p['name']+'请填写发货后增减依据')
        row['post_source']=r.get('post_source','manual')
        if row['post_source'] not in ('manual','closing'):raise ValueError('发货后实盘来源无效')
        if row['post_source']=='closing':
            close=next((x for x in rc.rows(c,'stock_closings') if x['business_date']==day and x['state']=='closed'),None)
            value=next((x.get('counted_qty') for x in (close or {}).get('products',[]) if x['product_id']==p['id']),None)
            if not close or b.get('closing_version')!=close['version'] or value is None or Decimal(value)!=Decimal(row['post_qty'] or '-1'):raise ValueError('已日结结存已变化，请重新带入核对')
            row['closing_version']=close['version']
        if row['pre_qty']!='' or row['post_qty']!='' or Decimal(row['post_in_qty']) or Decimal(row['post_out_qty']):rows.append(row)
    if not rows:raise ValueError('请至少登记一个产品的实盘依据')
    history=list((old or {}).get('history',[]))
    if old:history.append({k:v for k,v in old.items() if k!='history'})
    record={'id':'IC-'+day,'kind':'inventory-check','business_date':day,'rule':RULE,'version':(old or {}).get('version',0)+1,'products':rows,'sources_checked':b['sources_checked'],'source_fingerprint':digest(current),'source_snapshot':current,'handler':rc.text(b.get('handler'),'核对经办人',80),'note':rc.text(b.get('note'),'核对依据 / 更正原因',1000),'updated_at':now(),'role':role,'history':history}
    c.execute('INSERT INTO trade_records VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(record['id'],rc.dump(record)))
    result={'ok':True,'business_date':day,'version':record['version'],'fingerprint':finger}
    c.execute('INSERT INTO trade_submissions VALUES(?,?)',(key,rc.dump(result)));audit(c,role,'保存库存与发货核对依据',record['id'],old,record)
    return result
