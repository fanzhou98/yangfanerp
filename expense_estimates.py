"""Provisional cost evidence without payables; actual bills replace covered days.
Original estimates and bills stay intact. Voiding a bill restores the provisional
coverage automatically; closed-month guards still belong to the original writes.
"""
from datetime import date,timedelta
import json,secrets,hashlib
import resources_costs as rc
import expense_coverage as coverage
import erp_access

def exists(c):return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='expense_estimates'").fetchone())
def key(e):return (e['category'],e.get('service_account',''),e.get('counterparty_id') or e.get('supplier_id') or e.get('partner',''))
def intersects(a,b):return max(a['service_start'],b['service_start'])<min(a['service_end'],b['service_end'])
def actuals(c,month,exclude=''):
    return [json.loads(r[0]) for r in c.execute("SELECT e.payload FROM expense_accrual_lookup a JOIN indirect_expenses e ON e.id=a.expense_id WHERE a.period=? AND e.id!=? AND COALESCE(json_extract(e.payload,'$.voided'),0)=0 AND json_extract(e.payload,'$.accrual_method')='service_days'",(month,exclude))]
def originals(c,month):
    if not exists(c):return []
    coverage.day(month+'-01','月份');y,m=divmod(int(month[:4])*12+int(month[5:]),12);next_month=f'{y:04d}-{m+1:02d}-01'
    return [json.loads(r[0]) for r in c.execute("SELECT payload FROM expense_estimates WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 AND json_extract(payload,'$.service_start')<? AND json_extract(payload,'$.service_end')>=? ORDER BY id",(next_month,month+'-01'))]
def month_days(e,month):
    p=next((p for p in e['coverage_breakdown'] if p['period']==month),None)
    if not p:return {}
    start=date.fromisoformat(p['start']);base,extra=divmod(p['amount_cents'],p['days'])
    return {(start+timedelta(days=i)).isoformat():base+(i<extra) for i in range(p['days'])}
def project(e,month,bills):
    days=month_days(e,month);used=set();links=[]
    for b in sorted(bills,key=lambda b:b['id']):
        if e['id'] not in b.get('estimate_ids',[]):continue
        covered={d for d in days if b['service_start']<d<=b['service_end']} - used
        used|=covered
        if covered:links.append({'expense_id':b['id'],'service_start':b['service_start'],'service_end':b['service_end'],'estimated_cents':sum(days[d] for d in covered),'actual_month_cents':next((a['amount_cents'] for a in b['accruals'] if a['period']==month),0)})
    pending={d:v for d,v in days.items() if d not in used}
    return {'original_cents':sum(days.values()),'settled_cents':sum(days[d] for d in used),'remaining_cents':sum(pending.values()),'remaining_days':len(pending),'covered_days':len(used),'links':links}
def pending_costs(c,month):
    bills=actuals(c,month) if exists(c) else []
    result=[]
    for e in originals(c,month):
        p=project(e,month,bills)
        if p['remaining_cents']:
            result.append({**e,'period':month,'source_amount_cents':e['amount_cents'],'amount_cents':p['remaining_cents'],'is_estimate':True,'payment_required':False,'payment_mode':'estimate','payment_state':'estimate','payment_status':'暂估待到单，不产生付款','paid_cents':0,'outstanding_cents':0})
    return result

def candidates(c,record,exclude=''):
    records={};offsets={}
    for part in record['accruals']:
        month=part['period'];bills=actuals(c,month,exclude)
        for e in originals(c,month):
            if key(e)!=key(record) or not intersects(e,record):continue
            before=project(e,month,bills);after=project(e,month,[*bills,{**record,'id':'~preview','estimate_ids':[e['id']]}]);days=after['covered_days']-before['covered_days']
            if not days:continue
            item=records.setdefault(e['id'],{'id':e['id'],'version':e['version'],'service_start':e['service_start'],'service_end':e['service_end'],'original_amount_cents':e['amount_cents'],'offset_cents':0,'days':0,'months':[]})
            value=before['remaining_cents']-after['remaining_cents'];item['offset_cents']+=value;item['days']+=days;item['months'].append({'period':month,'offset_cents':value,'days':days})
    return sorted(records.values(),key=lambda r:r['id'])
def ensure_no_actual_overlap(c,record,exclude=''):
    if record.get('accrual_method')!='service_days':return
    for part in record['accruals']:
        for other in actuals(c,part['period'],exclude):
            if key(other)==key(record) and intersects(other,record):raise ValueError('同一费用项目、收款方和计量标识已有重叠实际账单：'+other['id'])
def validate_restore(c,record,exclude=''):
    if record.get('accrual_method')!='service_days':return
    ensure_no_actual_overlap(c,record,exclude)
    current=candidates(c,record,exclude)
    fields=('id','version','offset_cents','days')
    signature=lambda rows:sorted([tuple(r.get(k) for k in fields) for r in rows])
    if signature(current)!=signature(record.get('estimate_offsets',[])):raise ValueError('暂估匹配关系已变化，不能直接恢复旧账单；请按当前区间重新登记并核对暂估预览')

def validate_actual(c,b,record):
    if record.get('accrual_method')!='service_days':return
    record['service_account']=rc.text(b.get('service_account'),'计量标识 / 表号',80)
    ensure_no_actual_overlap(c,record,b.get('id',''))
    items=candidates(c,record,b.get('id',''));requested=b.get('estimate_versions',[])
    if not isinstance(requested,list) or any(not isinstance(p,dict) for p in requested):raise ValueError('暂估核销版本格式无效')
    expected=[{'id':p['id'],'version':p['version']} for p in items]
    if sorted(requested,key=lambda p:str(p.get('id','')))!=expected:raise ValueError('匹配的暂估已变化，请重新查看费用分摊及暂估核销预览后保存')
    if items:record.update(estimate_ids=[p['id'] for p in items],estimate_offsets=items,estimate_offset_cents=sum(p['offset_cents'] for p in items),estimate_difference_cents=record['amount_cents']-sum(p['offset_cents'] for p in items))
    __import__('expense_recognition').apply(c,record,b.get('id',''))

def category_pending(c,category):
    if not exists(c):return False
    for row in c.execute("SELECT payload FROM expense_estimates WHERE json_extract(payload,'$.category')=? AND COALESCE(json_extract(payload,'$.voided'),0)=0",(category,)):
        e=json.loads(row[0])
        if any(project(e,p['period'],actuals(c,p['period']))['remaining_days'] for p in e['accruals']):return True
    return False

def save(c,b,role,now,audit,*,_closing=False):
    erp_access.require_role(role,'costs.close' if _closing else 'costs.write');request=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}).encode()).hexdigest()
    prior=c.execute('SELECT payload FROM expense_estimates WHERE request_key=?',(request,)).fetchone()
    if prior:
        value=json.loads(prior[0])
        if value.get('request_fingerprint')!=finger:raise ValueError('提交编号已用于其他暂估')
        return value
    old_row=c.execute('SELECT payload FROM expense_estimates WHERE id=?',(b.get('id',''),)).fetchone();old=json.loads(old_row[0]) if old_row else None
    if b.get('id') and not old:raise ValueError('暂估记录不存在')
    if type(b.get('version',0)) is not int or b.get('version',0)!=(old or {}).get('version',0):raise ValueError('暂估记录已变化，请刷新后核对')
    if old:rc.expense_open_periods(c,old)
    if b.get('action')=='void':
        if not old or old.get('voided'):raise ValueError('该暂估不可撤销')
        value={**old,'voided':True,'void_reason':rc.text(b.get('reason'),'撤销暂估原因',500),'voided_at':now()}
    else:
        if b.get('accrual_method')!='service_days':raise ValueError('暂估须填写实际覆盖日期区间')
        if old:
            for r in c.execute("SELECT payload FROM indirect_expenses WHERE EXISTS(SELECT 1 FROM json_each(payload,'$.estimate_ids') WHERE value=?)",(old['id'],)):
                raise ValueError('暂估已有到单核销留痕，不能改写原依据；请另建未覆盖区间的补充暂估')
        value=rc.Operations(c,now,audit).expense(b,role,_validate_only=True,_estimate=True,_closing=_closing)
        if value['payment_mode']!='payable' or value['category'].startswith('wages-'):raise ValueError('暂估仅用于需实际账单的普通费用，工资及系统归集项目请走原业务')
        value['service_account']=rc.text(b.get('service_account'),'计量标识 / 表号',80)
        for part in value['accruals']:
            for e in originals(c,part['period']):
                if e['id']!=(old or {}).get('id') and key(e)==key(value) and intersects(e,value):raise ValueError('同一计量标识存在重叠暂估，请核对原记录')
            for actual in actuals(c,part['period']):
                if key(actual)==key(value) and intersects(actual,value):raise ValueError('此区间已有实际账单，不应再次暂估')
        value.update(payment_mode='estimate',is_estimate=True)
    __import__('cost_allocation').apply_expense_category_change(c,value,role,now,audit)
    if _closing:value['close_source']=b['close_source']
    value.update(id=(old or {}).get('id') or 'EST-'+secrets.token_hex(6).upper(),version=(old or {}).get('version',0)+1,created_at=(old or {}).get('created_at') or now(),updated_at=now(),request_fingerprint=finger)
    c.execute('INSERT INTO expense_estimates VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(value['id'],request,rc.dump(value)));audit(c,role,'撤销成本暂估' if value.get('voided') else '登记 / 更正成本暂估',value['id'],old,value);return value

def report(c,month,page=1):
    coverage.day(month+'-01','月份')
    try:page=int(page)
    except (ValueError,TypeError):raise ValueError('页码无效')
    if not 1<=page<=100000:raise ValueError('页码无效')
    bills=actuals(c,month);items=[{**e,**project(e,month,bills)} for e in originals(c,month)];total=len(items);pages=max(1,(total+49)//50);page=min(page,pages)
    actual_cents=sum(r[0] for r in c.execute("SELECT a.amount_cents FROM expense_accrual_lookup a JOIN indirect_expenses e ON e.id=a.expense_id WHERE a.period=? AND COALESCE(json_extract(e.payload,'$.voided'),0)=0",(month,)))
    estimated=sum(p['remaining_cents'] for p in items)
    return {'month':month,'rows':items[(page-1)*50:page*50],'total':total,'page':page,'pages':pages,'actual_cents':actual_cents,'estimated_cents':estimated,'total_cents':actual_cents+estimated,'offset_cents':sum(p['settled_cents'] for p in items),'basis':'暂估只归集成本，不产生应付或付款。实际账单按已覆盖天数核销对应暂估，未覆盖天数继续保留；金额补差可正可负，原暂估和实际账单均留存。作废未付款实际账单会恢复对应暂估；已结账月份须先核查并重新打开。'}
