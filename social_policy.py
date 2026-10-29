"""Versioned social-compensation defaults; personal exceptions remain explicit."""
import json
import secrets
import resources_costs as rc
import erp_access as access

KEY='payroll_social_policy_v1'
FIELDS=('social_base_cents','social_company_rate','social_personal_rate')


def catalog(c):
    row=c.execute('SELECT value FROM meta WHERE key=?',(KEY,)).fetchone()
    return json.loads(row[0]) if row else {'version':0,'rules':[]}


def effective(policy,month):
    return max((r for r in policy['rules'] if r['effective_month']<=month),key=lambda r:(r['effective_month'],r['version']),default=None)


def resolve(profile,month,policy):
    if profile.get('social_policy_mode','override')!='inherit' or month<profile.get('social_policy_from_month',''):return dict(profile)
    rule=effective(policy,month)
    if not rule:return dict(profile)
    return {**profile,**{k:rule[k] for k in FIELDS},'social_policy_version':rule['version'],'social_policy_effective_month':rule['effective_month']}


def report(c,month=''):
    import payroll
    month=month or payroll.local_today().strftime('%Y-%m');payroll.month_days(month)
    policy=catalog(c)
    profiles=[json.loads(r[0]) for r in c.execute("SELECT payload FROM payroll_records WHERE json_extract(payload,'$.kind')='profile' ORDER BY rowid")]
    return {**policy,'month':month,'active':effective(policy,month),
            'employees':[{'employee_id':r['employee_id'],'employee_name':r.get('employee_name','未列'),'mode':r.get('social_policy_mode','override'),'from_month':r.get('social_policy_from_month',''),
                          'suggest_inherit':r.get('social_policy_mode')=='inherit' or bool(r.get('defaulted') and not r.get('social_base_cents'))} for r in profiles]}


def save(c,b,role,now,audit):
    import payroll
    access.require_role(role,'payroll.write')
    key=rc.text(b.get('request_key'),'提交编号',100)
    prior=c.execute('SELECT value FROM meta WHERE key=?',('social-policy-request:'+key,)).fetchone()
    fingerprint=rc.dump(b)
    if prior:
        saved=json.loads(prior[0])
        if saved['request']!=fingerprint:raise ValueError('提交编号已用于其他补偿款设置')
        return saved['result']
    policy=catalog(c)
    if b.get('version')!=policy['version']:raise ValueError('统一标准已变化，请重新读取')
    month=b.get('effective_month');payroll.month_days(month)
    # A rule must never reach back into a confirmed, paid or closed period.
    locked=c.execute("SELECT MAX(json_extract(payload,'$.month')) FROM payroll_records WHERE (json_extract(payload,'$.kind')='sheet' AND json_extract(payload,'$.state')='confirmed') OR json_extract(payload,'$.kind')='payment'").fetchone()[0]
    closed=c.execute("SELECT MAX(month) FROM resource_periods WHERE json_extract(payload,'$.state')='closed'").fetchone()[0]
    boundary=max((m for m in (locked,closed) if m),default='')
    if boundary and month<=boundary:raise ValueError('生效月份必须晚于已确认、已发放或已结账的工资月份 '+boundary)
    values=payroll.social_settings(b,{})
    selected=b.get('adopt_employee_ids',[])
    if not isinstance(selected,list) or any(not isinstance(e,str) for e in selected) or len(selected)!=len(set(selected)):raise ValueError('跟随人员选择无效')
    profiles={r['employee_id']:r for r in payroll.records(c) if r['kind']=='profile'}
    if any(e not in profiles for e in selected):raise ValueError('所选人员工资档案已变化，请重新读取')
    amounts=payroll.social_amounts(values)
    for eid,p in profiles.items():
        if p.get('social_policy_mode')=='inherit' or eid in selected:
            if amounts['social_company_cents']+amounts['social_personal_cents']>payroll.profile_monthly(p):raise ValueError(p.get('employee_name',eid)+'的补偿款合计超过月工资，请先调整工资或设为个人例外')
    version=policy['version']+1
    rule={'id':'SOCIAL-'+secrets.token_hex(6),'version':version,'effective_month':month,**values,'updated_at':now()}
    result={'version':version,'rules':[*policy['rules'],rule]}
    c.execute('SAVEPOINT social_policy_save')
    try:
        for eid in selected:
            old=profiles[eid]
            if old.get('social_policy_mode')=='inherit':continue
            updated={**old,'social_policy_mode':'inherit','social_policy_from_month':month,'version':old.get('version',0)+1,'updated_at':now()}
            c.execute('UPDATE payroll_records SET request_key=?,payload=? WHERE id=?',('social-policy:'+str(version)+':'+eid,rc.dump(updated),old['id']))
            audit(c,role,'员工补偿款改为跟随统一标准',old['id'],old,updated)
        c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,rc.dump(result)))
        c.execute('INSERT INTO meta VALUES(?,?)',('social-policy-request:'+key,rc.dump({'request':fingerprint,'result':result})))
        audit(c,role,'维护统一社保补偿款标准',KEY,policy,result)
        c.execute('RELEASE social_policy_save')
    except Exception:
        c.execute('ROLLBACK TO social_policy_save');c.execute('RELEASE social_policy_save');raise
    return result
