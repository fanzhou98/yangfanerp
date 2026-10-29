"""Crate attributes and customer-specific tare, entered with the accountant's photos."""
import json
from decimal import Decimal
import resources_costs as rc

VARIANTS=[('CR-WHITE','白框'),('CR-YELLOW','黄框'),('CR-CLOTH','布')]


def variants(c,pid):
    p=c.execute('SELECT name,unit FROM products WHERE id=?',(pid,)).fetchone()
    if not p or p['unit']!='筐':return []
    row=c.execute("SELECT value FROM meta WHERE key='product_crate_attributes'").fetchone();settings=json.loads(row[0]) if row else {}
    assets={r['id']:r for r in rc.rows(c,'asset_records') if r['kind']=='asset' and r['category']=='周转筐'}
    fallback=[v[0] for v in VARIANTS] if p['name']=='大豆腐' else [r['asset_id'] for r in rc.rows(c,'asset_records') if r['kind']=='mapping' and r['product_id']==pid]
    ids=settings.get(pid,fallback)
    return [{'id':key,'name':assets[key]['name'],'parent_id':assets[key].get('parent_asset_id',key)} for key in ids if key in assets]


def set_variants(c,pid,ids):
    types={r['id'] for r in rc.rows(c,'asset_records') if r['kind']=='asset' and r['category']=='周转筐'}
    if not isinstance(ids,list) or len(ids)>30 or any(not isinstance(v,str) or v not in types for v in ids) or len(set(ids))!=len(ids):raise ValueError('请选择有效且不重复的产品框型')
    assets={r['id']:r for r in rc.rows(c,'asset_records') if r['kind']=='asset' and r['category']=='周转筐'}
    if any(assets[v].get('parent_asset_id') in ids for v in ids):raise ValueError('同一产品请选择具体属性，不能同时选择父框与它的属性')
    prior={v['id'] for v in variants(c,pid)}
    if any(v not in prior and (assets[v].get('active') is False or assets.get(assets[v].get('parent_asset_id'),{}).get('active') is False) for v in ids):raise ValueError('请先启用框型及所属父框，再作为产品可用属性')
    row=c.execute("SELECT value FROM meta WHERE key='product_crate_attributes'").fetchone();cfg=json.loads(row[0]) if row else {};cfg[pid]=ids
    c.execute("INSERT INTO meta VALUES('product_crate_attributes',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(cfg),))
    trow=c.execute("SELECT value FROM meta WHERE key='product_crate_tares'").fetchone();tcfg=json.loads(trow[0]) if trow else {}
    kept={k:v for k,v in (tcfg.get(pid) or {}).items() if k in ids}
    if kept:tcfg[pid]=kept
    else:tcfg.pop(pid,None)
    c.execute("INSERT INTO meta VALUES('product_crate_tares',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(tcfg),))


def product_tares(c,pid):
    row=c.execute("SELECT value FROM meta WHERE key='product_crate_tares'").fetchone();cfg=json.loads(row[0]) if row else {}
    value=cfg.get(pid)
    return value if isinstance(value,dict) else {}


def set_product_tares(c,pid,values):
    if not isinstance(values,dict) or len(values)>30:raise ValueError('产品框型皮重格式无效')
    valid={v['id'] for v in variants(c,pid)};clean={}
    for key,value in values.items():
        if key not in valid:raise ValueError('只能设置本产品已选择的框型皮重')
        if value in (None,''):continue
        try:tare=Decimal(str(value))
        except (ArithmeticError,TypeError,ValueError):raise ValueError('框型皮重无效')
        if not tare.is_finite() or tare<0 or tare>100 or tare.as_tuple().exponent<-3:raise ValueError('框型皮重须在0至100之间，最多三位小数')
        clean[key]=format(tare,'f')
    row=c.execute("SELECT value FROM meta WHERE key='product_crate_tares'").fetchone();cfg=json.loads(row[0]) if row else {}
    if clean:cfg[pid]=clean
    else:cfg.pop(pid,None)
    c.execute("INSERT INTO meta VALUES('product_crate_tares',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(cfg),))


def rules(c):return [dict(r) for r in c.execute('SELECT * FROM customer_crate_tares ORDER BY customer_id,product_id,variant_id')]


def defaults(c,cid,pid):
    product=c.execute('SELECT tare FROM products WHERE id=?',(pid,)).fetchone();base=c.execute('SELECT tare FROM rules WHERE customer_id=? AND product_id=?',(cid,pid)).fetchone()
    assets={r['id']:r for r in rc.rows(c,'asset_records') if r['kind']=='asset'}
    overrides=product_tares(c,pid)
    return {v['id']:(next((r['tare'] for r in rules(c) if r['customer_id']==cid and r['product_id']==pid and r['variant_id']==v['id']),base[0] if base else overrides.get(v['id'],assets.get(v['id'],{}).get('default_tare',assets.get(assets.get(v['id'],{}).get('parent_asset_id'),{}).get('default_tare',product[0] if product else '0'))))) for v in variants(c,pid)}


def normalize(c,pid,raw,actual,prior=None,customer_id=''):
    if raw is None:return None
    if not isinstance(raw,list) or len(raw)>100:raise ValueError('框型数量格式无效')
    types={v['id']:v['name'] for v in variants(c,pid)}
    # Existing user-defined crate types remain valid on products without built-in attributes.
    types.update({r['id']:r['name'] for r in rc.rows(c,'asset_records') if r['kind']=='asset' and r['category']=='周转筐'})
    seen=set();out=[]
    for line in raw:
        if not isinstance(line,dict) or line.get('asset_id') not in types or line['asset_id'] in seen:raise ValueError('框子属性不存在或重复')
        key=line['asset_id'];seen.add(key);qty=rc.qty(line.get('qty'),'框数')
        if qty!=qty.to_integral_value():raise ValueError(types[key]+'数量须为整数')
        tare=rc.qty(line.get('tare'),'单框皮重')
        if tare>100:raise ValueError('单框皮重不能超过100公斤')
        if qty:
            item={'product_id':pid,'asset_id':key,'asset_name':types[key],'qty':int(qty),'tare':rc.ds(tare)}
            if 'packing_lines' in line:
                import crate_packaging
                previous=next((r.get('packing_lines') for r in prior or [] if r.get('asset_id')==key),None)
                item['packing_lines']=crate_packaging.normalize(c,pid,key,line['packing_lines'],int(qty),previous,customer_id,base_tare=item['tare'])
            out.append(item)
    if out and sum(r['qty'] for r in out)!=actual:raise ValueError('白框、黄框等属性数量合计必须等于本行实发数量')
    return out


def save_rules(c,rows,role,now,audit):
    import erp_access
    erp_access.require_role(role,'master.pricing.write')
    if not isinstance(rows,list) or len(rows)>5000:raise ValueError('分框皮重规则格式无效')
    seen=set();pending=[]
    for r in rows:
        if not isinstance(r,dict):raise ValueError('分框皮重规则格式无效')
        key=(r.get('customer_id'),r.get('product_id'),r.get('variant_id'))
        if key in seen:raise ValueError('客户分框皮重重复提交')
        seen.add(key)
        if not c.execute('SELECT 1 FROM customers WHERE id=?',(key[0],)).fetchone() or key[2] not in {v['id'] for v in variants(c,key[1])}:raise ValueError('客户或框子属性无效')
        old=c.execute('SELECT tare,version FROM customer_crate_tares WHERE customer_id=? AND product_id=? AND variant_id=?',key).fetchone();expected=dict(old) if old else None
        if 'expected' not in r or r['expected']!=expected:raise ValueError('客户分框皮重已修改，请同步最新规则后重试')
        tare=rc.qty(r.get('tare'),'分框皮重')
        if tare>100:raise ValueError('分框皮重不能超过100公斤')
        pending.append((key,rc.ds(tare),expected))
    for key,tare,old in pending:
        c.execute('INSERT INTO customer_crate_tares VALUES(?,?,?,?,?) ON CONFLICT(customer_id,product_id,variant_id) DO UPDATE SET tare=excluded.tare,version=excluded.version',(*key,tare,(old or {}).get('version',0)+1))
        audit(c,role,'维护客户分框皮重','/'.join(key),old,{'tare':tare})
    return len(pending)
