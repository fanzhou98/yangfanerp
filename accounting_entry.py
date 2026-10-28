"""Accountant photo entry: current delivery collects crates from yesterday's source."""
from datetime import date,timedelta
from decimal import Decimal
import hashlib,json
import erp_access as access,resources_costs as rc,trade,assets


def auto_crates(c,cid,pid,actual):
    import crate_accounting
    variants=crate_accounting.variants(c,pid)
    if len(variants)!=1:return None
    v=variants[0];return [{'product_id':pid,'asset_id':v['id'],'asset_name':v['name'],'qty':int(actual),'tare':crate_accounting.defaults(c,cid,pid)[v['id']]}] if actual else []


def return_key(oid,pid,aid):return 'ACR-'+hashlib.sha256((oid+'|'+pid+'|'+aid).encode()).hexdigest()[:28]


def sync_returns(c,order,body,old,role,now,audit):
    if body is None:return
    access.require_role(role,'crates.write')
    if not isinstance(body,dict) or set(body)-{'version','business_date','lines'}:raise ValueError('收回框数格式无效')
    previous=(old or {}).get('accounting_returns') or {};version=previous.get('version',0)
    if type(body.get('version')) is not int or body['version']!=version:raise ValueError('收回框记录已变化，请刷新后核对')
    day=order['business_date'];yesterday=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
    if body.get('business_date')!=day:raise ValueError('随配送收回的框子须记本次配送业务日')
    if previous and (previous['business_date']!=day or (old or {})['customer_id']!=order['customer_id']):raise ValueError('已有回框关联，不能更换本日配送日期或客户')
    raw=body.get('lines')
    if not isinstance(raw,list) or len(raw)>200:raise ValueError('收回框明细无效')
    products={l['product_id']:l for l in order['lines']};clean=[];seen=set();sources={}
    for line in raw:
        if not isinstance(line,dict) or set(line)-{'product_id','asset_id','qty','source_order_id'}:raise ValueError('收回框明细格式无效')
        pid=line.get('product_id');aid=line.get('asset_id')
        if not isinstance(pid,str) or not isinstance(aid,str) or not isinstance(line.get('source_order_id'),str):raise ValueError('收回框原单、产品或框型无效')
        qty=assets.integer(line.get('qty'),'收回框数')
        if not qty:continue
        if pid not in products or products[pid]['unit']!='筐' or (pid,aid) in seen:raise ValueError('收回框产品或框型重复、无效')
        seen.add((pid,aid));sid=line.get('source_order_id');source=trade.get_order(c,sid)
        if source['customer_id']!=order['customer_id'] or source['business_date']!=yesterday:raise ValueError('收回框须关联同一客户昨日的配送原单')
        shipped=[r for r in trade.shipped_crates(c,source) if r.get('product_id')==pid and r['asset_id']==aid]
        if not shipped:raise ValueError('昨日所选原单未发出此产品框型，请重新核对归属')
        clean.append({'product_id':pid,'asset_id':aid,'asset_name':shipped[0].get('asset_name',aid),'qty':qty,'source_order_id':sid});sources[sid]=source
    clean.sort(key=lambda r:(r['product_id'],r['asset_id']))
    equivalent=lambda lines:[{k:r[k] for k in ('product_id','asset_id','qty','source_order_id')} for r in sorted(lines,key=lambda r:(r['product_id'],r['asset_id']))]
    if equivalent(clean)==equivalent(previous.get('lines',[])) and (not previous or previous['business_date']==day):
        if previous:order['accounting_returns']=previous
        return
    event_versions=dict(previous.get('event_versions',{}));desired={return_key(order['id'],r['product_id'],r['asset_id']):r for r in clean}
    for key in set(event_versions)|set(desired):
        found=c.execute('SELECT payload FROM asset_records WHERE id=?',(key,)).fetchone();before=json.loads(found[0]) if found else None
        if before and before.get('version')!=event_versions.get(key):raise ValueError('对应回框已在框子管理修改或作废，请先核对，不能覆盖')
        line=desired.get(key)
        if not line:
            if before and not before.get('voided'):
                value={**before,'voided':True,'void_reason':'会计算票更正收回框数','version':before['version']+1,'updated_at':now()}
            else:continue
        else:
            source=sources[line['source_order_id']]
            value={'id':key,'kind':'movement','movement':'return','version':(before or {}).get('version',0)+1,'business_date':day,'source_date':yesterday,'order_id':source['id'],'customer_id':order['customer_id'],'customer_name':order['customer_name'],'asset_id':line['asset_id'],'asset_name':line['asset_name'],'product_id':line['product_id'],'qty':line['qty'],'driver':'','trip':'','vehicle_name':'','accounting_order_id':order['id'],'accounting_product_id':line['product_id'],'batch_id':'ACCOUNTING-'+order['id'],'handler':role,'note':'随本日配送收回，关联昨日原单 '+source['id']+'；会计算票登记','updated_at':now()}
        c.execute('INSERT INTO asset_records(id,request_key,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(key,'accounting-return:'+key,rc.dump(value)));event_versions[key]=value['version'];audit(c,role,'算票同步收回框数',key,before,value)
    order['accounting_returns']={'version':version+1,'business_date':day,'source_date':yesterday,'lines':clean,'event_versions':event_versions}


def guard_source_edit(c,old,new):
    if not old:return
    if old.get('accounting_returns',{}).get('lines') and (old['customer_id']!=new['customer_id'] or old['business_date']!=new['business_date']):raise ValueError('本单已有随配送回框记录，不能更换客户或配送日期')
    rows=c.execute("SELECT payload FROM asset_records WHERE json_extract(payload,'$.order_id')=? AND json_extract(payload,'$.accounting_order_id') IS NOT NULL AND COALESCE(json_extract(payload,'$.voided'),0)=0",(old['id'],)).fetchall()
    if not rows:return
    if old['customer_id']!=new['customer_id'] or old['business_date']!=new['business_date']:raise ValueError('此原单已有次日回框关联，不能更换客户或配送日期')
    shipped={(r.get('product_id'),r['asset_id']) for r in trade.shipped_crates(c,new)}
    if any((json.loads(row[0]).get('product_id'),json.loads(row[0])['asset_id']) not in shipped for row in rows):raise ValueError('此原单框型已有次日回框关联，不能移除对应产品或框型')
