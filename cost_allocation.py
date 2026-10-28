"""Settled-kilogram allocation, versioned product factors and editable cost items.
No commits; writes use the caller's guarded transaction and audit trail.
"""
from decimal import Decimal
import json,secrets
import resources_costs as rc

RULE='settled-kg-intensity-v1'
BUILTIN_KEYS={r[0] for r in rc.CATEGORIES}
SYSTEM_CATEGORIES={
    'transport':{
        'system_managed':True,'system_source':'transport-settlement','system_source_label':'运输月结',
        'system_note':'由车辆排班 → 运输月结按实际趟次生成，自动形成费用应付；不能手工重复登记或删除。',
    },
}
RETIRED_CATEGORIES={
    'wages-delivery':{
        'retired':True,'active':False,
        'retired_reason':'配送已外包，配送工资不再新增；已有计薪配置、历史工资与历史费用继续保留。',
    },
}
RUNTIME_FIELDS={'manual_entry','selectable','deletable','delete_reason','reference_count','expense_count','payroll_profile_count','status','status_detail'}

def meta(c,key,default):
    row=c.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default

def write(c,key,value):
    c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,rc.dump(value)))

def _references(c):
    """Count durable business links. Voided bills still reference their category."""
    result={}
    for category,count in c.execute("SELECT json_extract(payload,'$.category'),COUNT(*) FROM indirect_expenses GROUP BY json_extract(payload,'$.category')"):
        if category:result.setdefault(category,{'expense_count':0,'payroll_profile_count':0})['expense_count']=count
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='expense_estimates'").fetchone():
        for category,count in c.execute("SELECT json_extract(payload,'$.category'),COUNT(*) FROM expense_estimates GROUP BY json_extract(payload,'$.category')"):
            if category:result.setdefault(category,{'expense_count':0,'payroll_profile_count':0})['expense_count']+=count
    for category,count in c.execute("SELECT json_extract(payload,'$.salary_category'),COUNT(*) FROM payroll_records WHERE json_extract(payload,'$.kind')='profile' GROUP BY json_extract(payload,'$.salary_category')"):
        if category:result.setdefault(category,{'expense_count':0,'payroll_profile_count':0})['payroll_profile_count']=count
    return result

def _base(key,name,group,nature,hint):
    import expense_parties as ep
    mode='payroll' if key.startswith('wages-') else 'noncash' if key=='depreciation' else 'payable'
    value={'id':key,'name':name,'group':group,'nature':nature,'payment_mode':mode,'counterparty_kind':ep.kind_for(key,mode),'allocation_hint':hint,'irregular_periodic':False,'active':True,'version':0,'product_ids':[],'retired':False,'retired_reason':'','system_managed':False,'system_source':'','system_source_label':'','system_note':''}
    value.update(SYSTEM_CATEGORIES.get(key,{}));value.update(RETIRED_CATEGORIES.get(key,{}))
    return value

def _decorate(value,references):
    value=dict(value);expenses=references.get('expense_count',0);profiles=references.get('payroll_profile_count',0)
    value['active']=bool(value.get('active',True));value['retired']=bool(value.get('retired'));value['system_managed']=bool(value.get('system_managed'))
    value['manual_entry']=bool(value['active'] and not value['retired'] and not value['system_managed']);value['selectable']=value['manual_entry']
    value['expense_count']=expenses;value['payroll_profile_count']=profiles;value['reference_count']=expenses+profiles
    if value['system_managed']:
        value['deletable']=False;value['status']='系统自动';value['status_detail']='由运输月结生成'
        value['delete_reason']='运输月结系统项目，不能删除；如暂不使用也须保留，以免自动应付中断。'
    elif value['reference_count']:
        value['deletable']=False;value['status']='历史 / 停用' if value['retired'] or not value['active'] else '可新增'
        parts=[]
        if expenses:parts.append(f'{expenses} 笔费用')
        if profiles:parts.append(f'{profiles} 份计薪配置')
        value['status_detail']='已有'+'、'.join(parts)+'引用，不能删除'
        value['delete_reason']='已有'+'、'.join(parts)+'引用，不能删除；可编辑项目并停用，历史原单与快照继续保留。'
    else:
        value['deletable']=True;value['status']='历史项目' if value['retired'] else '可新增' if value['active'] else '已停用';value['status_detail']='未被引用，可删除';value['delete_reason']='未被费用或计薪配置引用，可删除。'
    return value

def categories(c):
    changes=meta(c,'expense_category_settings',{});references=_references(c);result=[]
    for key,name,group,nature,hint in rc.CATEGORIES:
        setting=changes.get(key,{})
        if setting.get('deleted'):continue
        value=_base(key,name,group,nature,hint);value.update({k:v for k,v in setting.items() if k not in RUNTIME_FIELDS});value['id']=key;value['version']=int(setting.get('version',0))
        result.append(_decorate(value,references.get(key,{})))
    for key,setting in changes.items():
        if key in BUILTIN_KEYS or setting.get('deleted'):continue
        value={'id':key,'name':setting.get('name',''),'group':setting.get('group',''),'nature':setting.get('nature','变动'),'irregular_periodic':bool(setting.get('irregular_periodic',False)),'payment_mode':setting.get('payment_mode','payable'),'counterparty_kind':setting.get('counterparty_kind','other'),'allocation_hint':setting.get('allocation_hint','结算公斤 × 加工强度（指定承担范围）'),'active':setting.get('active',True),'version':int(setting.get('version',0)),'product_ids':setting.get('product_ids',[]),'retired':False,'retired_reason':'','system_managed':False,'system_source':'','system_source_label':'','system_note':''}
        result.append(_decorate(value,references.get(key,{})))
    return result

def product_ids(c,ids):
    if not isinstance(ids,list) or any(not isinstance(p,str) for p in ids) or len(set(ids))!=len(ids):raise ValueError('承担产品须为不重复的产品列表')
    valid={r[0] for r in c.execute('SELECT id FROM products')}
    if set(ids)-valid:raise ValueError('承担产品不存在，请刷新档案')
    return sorted(ids)

def save_category(c,b,role,now,audit):
    import erp_access
    erp_access.require_role(role,'costs.write')
    values=meta(c,'expense_category_settings',{});old=next((r for r in categories(c) if r['id']==b.get('id')),None)
    if b.get('id') and old is None:raise ValueError('费用项目不存在或已删除，请刷新')
    if b.get('version',0)!=(old or {}).get('version',0):raise ValueError('费用项目已变更，请刷新')
    if old and old.get('system_managed'):raise ValueError('外包配送费由运输月结自动归集，名称、状态和付款方式由系统维护，不能手工修改')
    key=old['id'] if old else 'cost-'+secrets.token_hex(4)
    mode=b.get('payment_mode',(old or {}).get('payment_mode','payable'))
    if mode not in ('payable','noncash','payroll'):raise ValueError('付款属性无效')
    if old and old['payment_mode']!=mode and __import__('expense_estimates').category_pending(c,key):raise ValueError('此项目尚有未核销暂估，不能切换付款属性；请先核对实际账单或撤销剩余暂估')
    if old and (old['payment_mode']=='payroll' or mode=='payroll') and mode!=old['payment_mode']:raise ValueError('工资项目在工资系统发放；可修改固定/变动、名称与承担产品，不能切换付款通道')
    if not old and mode=='payroll':raise ValueError('工资发放属性仅由工资系统项目使用')
    retired=bool((old or {}).get('retired'))
    if retired and b.get('active') is True:raise ValueError('配送工资已停用，仅保留历史计薪和历史费用，不能重新启用新增入口')
    import expense_parties as ep
    party_kind=b.get('counterparty_kind',(old or {}).get('counterparty_kind') or ep.kind_for(key,mode)) if mode=='payable' else ep.kind_for(key,mode)
    if mode=='payable' and party_kind not in ep.KINDS:raise ValueError('请选择需要付款的费用收款方分类')
    r={'counterparty_kind':party_kind,'id':key,'name':rc.text(b.get('name'),'项目名称',80),'group':rc.text(b.get('group'),'项目分类',40),'nature':rc.text(b.get('nature'),'固定/变动属性',20),'payment_mode':mode,'active':False if retired else b.get('active',True) is True,'product_ids':product_ids(c,b.get('product_ids',[])),'version':(old or {}).get('version',0)+1,
       'retired':retired,'retired_reason':(old or {}).get('retired_reason',''),'system_managed':False,'system_source':'','system_source_label':'','system_note':''}
    irregular=b.get('irregular_periodic',(old or {}).get('irregular_periodic',False))
    if not isinstance(irregular,bool):raise ValueError('不定期费用属性无效')
    if irregular and (mode!='payable' or retired):raise ValueError('不定期费用仅适用于普通实际账单项目')
    r['irregular_periodic']=irregular
    if r['nature'] not in ('固定','变动'):raise ValueError('费用属性请选择固定或变动')
    values[key]=r;write(c,'expense_category_settings',values);audit(c,role,'维护间接成本项目',key,old,r);return _decorate(r,_references(c).get(key,{}))

def delete_category(c,b,role,now,audit):
    """Soft-delete a template. Business documents and their snapshots are never rewritten."""
    import erp_access
    erp_access.require_role(role,'costs.write')
    old=next((r for r in categories(c) if r['id']==b.get('id')),None)
    if old is None:raise ValueError('费用项目不存在或已删除，请刷新')
    if b.get('version')!=old.get('version'):raise ValueError('费用项目已变更，请刷新后重试')
    if old.get('system_managed'):raise ValueError(old.get('delete_reason') or '系统自动项目不能删除')
    if old.get('reference_count'):
        raise ValueError(old.get('delete_reason') or '费用项目已有历史引用，不能删除；请停用并保留历史')
    values=meta(c,'expense_category_settings',{})
    record={k:v for k,v in old.items() if k not in RUNTIME_FIELDS}
    record.update(deleted=True,deleted_at=now(),deleted_by=role,version=old['version']+1,active=False)
    values[old['id']]=record;write(c,'expense_category_settings',values)
    audit(c,role,'删除间接成本项目',old['id'],old,record)
    return {'id':old['id'],'name':old['name'],'deleted':True,'version':record['version']}

def factor_history(c,pid):return meta(c,'processing_intensity_history',{}).get(pid,[])

def factor(c,pid,month):
    history=[r for r in factor_history(c,pid) if r['month']<=month]
    return Decimal(max(history,key=lambda r:r['month'])['value']) if history else Decimal('1')

def save_factor(c,pid,value,month,expected,role,now,audit):
    value=rc.qty(value,'加工强度系数',positive=True)
    if value>1000:raise ValueError('加工强度系数不能超过1000')
    rc.day(month+'-01')
    history=factor_history(c,pid)
    if expected is not None and expected!=history:raise ValueError('产品系数已被其他页面修改，请刷新')
    if value==factor(c,pid,month):return
    future=next((r['month'] for r in history if r['month']>month),None)
    stop=future or '9999-99'
    if any(r['state']=='closed' and month<=r['month']<stop for r in rc.rows(c,'resource_periods')):raise ValueError('系数生效范围包含已结账月份，请先重开或选择后续月份')
    old=list(history);history=[r for r in history if r['month']!=month]+[{'month':month,'value':rc.ds(value),'at':now()}]
    history.sort(key=lambda r:r['month']);values=meta(c,'processing_intensity_history',{});values[pid]=history;write(c,'processing_intensity_history',values);audit(c,role,'维护加工强度系数',pid,old,history)

def settled_kg(line):
    """Only final kilogram settlement. Never substitute standard/average weight."""
    if line.get('billing_unit')=='公斤' and line.get('bill_qty') not in ('',None):
        q=Decimal(line['bill_qty']);return q if q.is_finite() and q>=0 else None
    return None

def settlement_basis(c,start,end):
    import trade
    products={r['id']:dict(r) for r in c.execute('SELECT * FROM products')}
    result={pid:{'kg':Decimal(0),'self_kg':Decimal(0),'orders':0,'pending':0,'missing':0,'mixed':False,'excluded':trade.product_config(c,p).get('supply_kind','self')=='purchased'} for pid,p in products.items()}
    for o in rc.rows(c,'orders'):
        if not start<=o['business_date']<=end:continue
        for l in o.get('lines',[]):
            pid=l['product_id']
            if pid not in result or Decimal(l.get('actual_qty') or '0')<=0:continue
            r=result[pid]
            if o.get('state')!='reviewed':r['pending']+=1;continue
            q=settled_kg(l);r['orders']+=1
            if q is None:
                if not r['excluded']:r['missing']+=1
                continue
            r['kg']+=q
            source=trade.product_config(c,products[pid]).get('supply_kind','self')
            if source=='self':r['self_kg']+=q
            elif source=='mixed':
                # Without order-line origin attribution, FIFO kilograms alone
                # cannot identify which reviewed settlement came from own stock.
                r['mixed']=True
    return result

def allocate(c,start,end,expenses,extra=()):
    from material_allocation import split
    basis=settlement_basis(c,start,end);month=start[:7];weights={}
    for pid,r in basis.items():
        if not r['excluded'] and not r['mixed'] and not r['missing'] and not r['pending']:weights[pid]=r['self_kg']*factor(c,pid,month)
    allocations={};details=[];unallocated=0
    for e in [*expenses,*extra]:
        scope=e.get('product_ids')
        if scope is None:scope=[e['product_id']] if e.get('product_id') else []
        targets=scope or [pid for pid,r in basis.items() if not r['excluded']]
        reasons=[]
        if e.get('category')=='cold-power' and not scope:reasons.append('冻豆腐专属产品未建立，不能分摊至其他产品')
        if any(basis.get(pid,{}).get('excluded') for pid in targets):reasons.append('承担范围含外购成品，请更正范围')
        if any(basis.get(pid,{}).get('mixed') for pid in targets):reasons.append('自产与外购的结算归属待区分')
        if any(basis.get(pid,{}).get('pending') or basis.get(pid,{}).get('missing') for pid in targets):reasons.append('承担产品存在待复核或缺结算公斤的发货')
        denominator=sum((weights.get(pid,Decimal(0)) for pid in targets),Decimal(0))
        if denominator<=0:reasons.append('没有有效自产结算公斤分母')
        amounts={} if reasons else split(e['amount_cents'],{pid:weights.get(pid,Decimal(0)) for pid in targets})
        pending=e['amount_cents']-sum(amounts.values());unallocated+=pending
        for pid,n in amounts.items():allocations[pid]=allocations.get(pid,0)+n
        details.append({'id':e['id'],'is_estimate':bool(e.get('is_estimate')),'label':(e.get('label') or e.get('category_snapshot',{}).get('name') or e.get('category','共用成本'))+('（暂估待到单）' if e.get('is_estimate') else ''),'amount_cents':e['amount_cents'],'product_ids':targets,'denominator':rc.ds(denominator),'allocated_cents':sum(amounts.values()),'unallocated_cents':pending,'reasons':reasons,'rows':[{'product_id':pid,'settled_kg':rc.ds(basis[pid]['self_kg']),'factor':rc.ds(factor(c,pid,month)),'weight':rc.ds(weights.get(pid,Decimal(0))),'amount_cents':n} for pid,n in amounts.items()]})
    return {'version':RULE,'start':start,'end':end,'amount_cents':sum(e['amount_cents'] for e in [*expenses,*extra]),'allocated_cents':sum(allocations.values()),'unallocated_cents':unallocated,'estimated_cents':sum(e['amount_cents'] for e in expenses if e.get('is_estimate')),'allocations':allocations,'details':details,'pending_items':sum(bool(d['reasons']) and d['amount_cents']!=0 for d in details),'basis':basis}

def public_yields(c,report,day):
    basis=settlement_basis(c,day,day)
    for p in report['products']:
        r=basis.get(p['product_id'],{});pending=r.get('pending',0);missing=r.get('missing',0)
        bean=p.get('processing_input_kg') if p.get('processing_source_name') else p.get('bean_kg');usable=r.get('orders',0)>0 and not pending and not missing and not r.get('excluded') and not r.get('mixed')
        p['settlement_kg']=rc.ds(r['self_kg']) if usable else None;p['settlement_pending']=pending
        p['settlement_yield']=rc.ds(r['self_kg']/Decimal(bean)) if usable and bean and Decimal(bean)>0 else None
        p['settlement_basis']=('已复核结算公斤 ÷ 同日实际转加工投入公斤' if p.get('processing_source_name') else '已复核结算公斤 ÷ 同日归属干豆公斤')+'；包含保水与运输后的综合表现，不代表出厂物理出品率；跨日存货须另行核对。'
    report['yield_basis_version']=RULE
    return report


def apply_expense_category_change(c,record,role,now,audit):
    change=record.pop('_irregular_category_update',None)
    if not change:return
    category=next((p for p in categories(c) if p['id']==change['id']),None)
    if not category or category['version']!=change['version']:raise ValueError('费用项目属性已变化，请刷新后重新核对')
    updated=save_category(c,{**category,'irregular_periodic':change['irregular_periodic']},role,now,audit)
    record['category_snapshot']=updated
