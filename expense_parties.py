"""Dedicated expense counterparties; never mixed with purchase suppliers."""
import hashlib,json,secrets
import resources_costs as rc
import erp_access

KINDS={'energy':'能源单位','rent':'房屋出租方','logistics':'运输服务','repair':'维修服务','office':'管理服务','meals':'伙食餐饮','other':'其他费用'}
DEFAULTS={'electricity':'energy','cold-power':'energy','gas':'energy','water':'energy','rent':'rent','transport':'logistics','maintenance':'repair','office':'office','meals':'meals'}
KEY='expense_counterparties_v1'

def kind_for(category,mode):
    return 'employee' if mode=='payroll' else 'none' if mode=='noncash' else DEFAULTS.get(category,'other')

def catalog(c):
    row=c.execute('SELECT value FROM meta WHERE key=?',(KEY,)).fetchone()
    return json.loads(row[0]) if row else []

def save(c,b,role,now,audit,permission='costs.write'):
    erp_access.require_role(role,permission)
    values=catalog(c);key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump(b).encode()).hexdigest()
    prior=next((p for p in values if p.get('request_key')==key),None)
    if prior:
        if prior.get('fingerprint')==finger:return prior
        raise ValueError('提交编号已使用，请重新打开')
    old=next((p for p in values if p['id']==b.get('id')),None)
    if b.get('id') and not old:raise ValueError('费用收款方不存在')
    if b.get('version',0)!=(old or {}).get('version',0):raise ValueError('费用收款方已变化，请刷新')
    kind=b.get('kind');name=rc.text(b.get('name'),'收款方名称',100)
    if kind not in KINDS:raise ValueError('请选择费用收款方分类')
    if any(p['id']!=(old or {}).get('id') and p['kind']==kind and p['name']==name for p in values):raise ValueError('此分类已有同名费用收款方，请直接选择原档案')
    r={'id':(old or {}).get('id') or 'ECP-'+secrets.token_hex(6).upper(),'name':name,'kind':kind,'phone':rc.text(b.get('phone',''),'联系电话',60,False),'note':rc.text(b.get('note',''),'备注',500,False),'active':b.get('active',True) is True,'version':(old or {}).get('version',0)+1,'request_key':key,'fingerprint':finger,'updated_at':now()}
    values=[p for p in values if p['id']!=r['id']]+[r]
    c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,rc.dump(values)))
    audit(c,role,'维护费用收款方',r['id'],old,r);return r

def apply(c,b,record,category):
    mode=record['payment_mode'];kind=category.get('counterparty_kind') or kind_for(record['category'],mode)
    if mode!='payable':
        if b.get('counterparty_mode')=='expense-ledger-v1':record.update(partner='',counterparty_id='',counterparty_kind=kind);record.pop('supplier_id',None)
        return
    pid=b.get('counterparty_id','')
    if pid:
        party=next((p for p in catalog(c) if p['id']==pid and p['active']),None)
        if not party:raise ValueError('请选择有效费用收款方，采购供应商不能代替此档案')
        if party['kind']!=kind:raise ValueError('费用收款方分类与所选费用项目不一致')
        record.update(counterparty_id=pid,counterparty_kind=kind,counterparty_snapshot={k:party[k] for k in ('id','name','kind','phone','version')},partner=party['name'])
        record.pop('supplier_id',None)
    elif b.get('counterparty_mode')=='expense-ledger-v1':raise ValueError('此费用需要实际付款，请先选择或新增费用收款方')
