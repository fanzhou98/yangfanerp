"""Configurable packaging tare; packaging never creates a physical crate asset."""
import json,secrets
from decimal import Decimal
import resources_costs as rc
import erp_access as access

KEY='crate_packaging_catalog_v1'
ORDINARY='__ordinary__'

def catalog(c):
    row=c.execute('SELECT value FROM meta WHERE key=?',(KEY,)).fetchone()
    value=json.loads(row[0]) if row else {'version':0,'methods':[],'default_method_id':'','rules':[]}
    value['special_assets']={a['id']:a.get('special_packaging',[]) for a in rc.rows(c,'asset_records') if a.get('kind')=='asset' and a.get('category')=='周转筐'}
    return value

def normalize_asset_settings(lines,prior=None):
    """Validate special packaging in the same transaction/version as its physical asset."""
    if not isinstance(lines,list) or len(lines)>30:raise ValueError('特殊包装设置格式无效')
    out=[];ids=set();names=set()
    for line in lines:
        if not isinstance(line,dict):raise ValueError('特殊包装设置格式无效')
        mid=rc.text(line.get('id'),'特殊包装编号',80) if line.get('id') else 'PACK-'+secrets.token_hex(6).upper()
        name=rc.text(line.get('name'),'特殊包装名称',60)
        if mid==ORDINARY or mid in ids or name in names:raise ValueError('特殊包装编号或名称不能重复')
        if type(line.get('active',True)) is not bool:raise ValueError('特殊包装启用状态无效')
        out.append({'id':mid,'name':name,'tare':tare_value(line.get('tare')),'active':line.get('active',True)})
        ids.add(mid);names.add(name)
    if any(p['id'] not in ids for p in prior or []):raise ValueError('已有特殊包装请停用保留，不要删除')
    return out

def tare_value(value):
    if value in (None,''):raise ValueError('请先设置框型与包法的组合皮重')
    try:v=Decimal(str(value))
    except Exception:raise ValueError('组合皮重无效')
    if not v.is_finite() or not 0<=v<=100 or v.as_tuple().exponent<-3:raise ValueError('组合皮重须在0至100公斤之间，最多三位小数')
    return rc.ds(v)

def save(c,body,role,now,audit):
    access.require_role(role,'master.pricing.write')
    old=catalog(c)
    if type(body.get('version')) is not int or body['version']!=old['version']:raise ValueError('包法与组合皮重已变化，请刷新后修改')
    methods=body.get('methods');rules=body.get('rules');default=body.get('default_method_id','')
    if not isinstance(methods,list) or len(methods)>100 or not isinstance(rules,list) or len(rules)>10000:raise ValueError('包法或组合皮重格式无效')
    clean=[];ids=set();names=set()
    for m in methods:
        if not isinstance(m,dict):raise ValueError('包法格式无效')
        mid=rc.text(m.get('id'),'包法编号',80) if m.get('id') else 'PACK-'+secrets.token_hex(6).upper()
        name=rc.text(m.get('name'),'包法名称',60)
        if mid==ORDINARY and not any(p['id']==mid for p in old['methods']) or mid in ids or name in names:raise ValueError('包法编号或名称不能重复或占用普通包装保留编号')
        if type(m.get('active',True)) is not bool:raise ValueError('包法启用状态无效')
        ids.add(mid);names.add(name);clean.append({'id':mid,'name':name,'active':m.get('active',True)})
    if any(m['id'] not in ids for m in old['methods']):raise ValueError('已有包法请停用保留，不要删除')
    if default and not any(m['id']==default and m['active'] for m in clean):raise ValueError('默认包法必须为已启用的包法')
    assets={a['id'] for a in rc.rows(c,'asset_records') if a.get('kind')=='asset' and a.get('category')=='周转筐'}
    normalized=[];seen=set()
    for row in rules:
        if not isinstance(row,dict):raise ValueError('组合皮重格式无效')
        pid=row.get('product_id');aid=row.get('asset_id');mid=row.get('method_id');cid=row.get('customer_id','')
        if not all(isinstance(v,str) for v in (pid,aid,mid,cid)):raise ValueError('组合皮重编号无效')
        key=(pid,aid,mid,cid)
        if key in seen or mid not in ids or aid not in assets:raise ValueError('组合皮重重复或框型/包法不存在')
        if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise ValueError('组合皮重产品不存在')
        if cid and not c.execute('SELECT 1 FROM customers WHERE id=?',(cid,)).fetchone():raise ValueError('组合皮重客户不存在')
        seen.add(key);normalized.append({'product_id':pid,'asset_id':aid,'method_id':mid,'customer_id':cid,'tare':tare_value(row.get('tare'))})
    value={'version':old['version']+1,'methods':clean,'default_method_id':default,'rules':normalized,'updated_at':now()}
    c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,rc.dump(value)))
    audit(c,role,'维护包法及组合皮重',KEY,old,value)
    return value

def normalize(c,pid,aid,lines,qty,prior=None,customer_id='',base_tare=None):
    if not isinstance(lines,list) or not lines or len(lines)>100:raise ValueError('请填写包法分项数量和组合皮重')
    cfg=catalog(c);methods={m['id']:m for m in cfg['methods']};special={m['id']:m for m in cfg['special_assets'].get(aid,[])};old={p['method_id']:p for p in prior or []};out=[];seen=set()
    for line in lines:
        if not isinstance(line,dict):raise ValueError('包法分项格式无效')
        mid=line.get('method_id')
        if not isinstance(mid,str):raise ValueError('包法编号无效')
        before=old.get(mid)
        q=rc.qty(line.get('qty'),'包法框数')
        if q<=0 or q!=q.to_integral_value() or mid in seen:raise ValueError('包法数量须为正整数，且同一框型下包法不能重复')
        tare=tare_value(line.get('tare'))
        unchanged=before and str(before['qty'])==str(int(q)) and Decimal(before['tare'])==Decimal(tare)
        ordinary=mid==ORDINARY and line.get('packing_kind')=='ordinary' and (not before or before.get('packing_kind')=='ordinary')
        if ordinary:
            expected=before['tare'] if before else base_tare
            if expected is None or Decimal(tare)!=Decimal(str(expected)):raise ValueError('普通包装皮重须沿用本单物理框型皮重')
            name='普通（无纺布）'
        elif mid in special:
            if not unchanged and not special[mid]['active']:raise ValueError('新增或修改的特殊包装须先启用')
            expected=before['tare'] if before else special[mid]['tare']
            if Decimal(tare)!=Decimal(expected):raise ValueError('特殊包装皮重已变化，请刷新后填写数量')
            name=before.get('method_name') if before else special[mid]['name']
        else:
            if not unchanged and (mid not in methods or not methods[mid]['active']):raise ValueError('新增或修改的包法必须为已启用的档案')
            if not unchanged and not any(r['product_id']==pid and r['asset_id']==aid and r['method_id']==mid and r.get('customer_id','') in ('',customer_id) for r in cfg['rules']):raise ValueError('请先维护该产品、物理框型与包法的组合皮重标准')
            name=before.get('method_name') if before else methods[mid]['name']
        out.append({'method_id':mid,'method_name':name,'qty':int(q),'tare':tare,**({'packing_kind':'ordinary'} if ordinary else {})});seen.add(mid)
    if sum(r['qty'] for r in out)!=qty:raise ValueError('各包法数量合计必须等于该物理框型数量')
    return out

def total_tare(line):
    if 'packing_lines' in line:
        return sum((Decimal(str(p['qty']))*Decimal(p['tare']) for p in line['packing_lines']),Decimal(0))
    return Decimal(str(line['qty']))*Decimal(line['tare'])
