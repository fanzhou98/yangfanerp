"""Factory personnel and independent attendance; contractor records stay separate."""
import hashlib,json,secrets
import resources_costs as rc
import erp_access as access

TYPES={'production':'生产工人','management':'管理人员'}
STATUSES=('full','half','leave','absent','rest')

def employee(c,b,old):
    kind=b.get('employee_type',(old or {}).get('employee_type','production'))
    if kind not in TYPES:raise ValueError('厂内人员请选择生产工人或管理人员；承包方运输人员在独立运输台账登记')
    gid=b.get('group_id',(old or {}).get('group_id','')) or ''
    group=next((g for g in rc.rows(c,'factory_groups') if g['id']==gid and g.get('active',True)),None)
    if gid and not group or kind=='production' and not group:raise ValueError('生产工人请选择有效班组；管理人员可不选生产班组')
    return {'name':rc.text(b.get('name'),'员工姓名',60),'employee_type':kind,'department':rc.text(b.get('department',''),'所属部门',80,False),'position':rc.text(b.get('position',''),'岗位',80,False),'group_id':gid,'group_name':group['name'] if group else '', 'phone':rc.text(b.get('phone',''),'联系电话',40,False),'note':rc.text(b.get('note',''),'员工备注',500,False),'active':b.get('active',True) is True}

def type_permission(scope,staff=False):
    if scope not in TYPES:raise ValueError('请选择生产或管理人员范围')
    return ('management' if scope=='management' else 'production')+('.staff' if staff else '.attendance')

def entry_type(e,employees):return employees.get(e['employee_id'],{}).get('employee_type',e.get('employee_type','production'))

def attendance_report(c,month,scopes):
    import payroll
    report=payroll.attendance(c,month);report['rows']=[r for r in report['rows'] if r.get('employee_type','production') in scopes]
    if scopes=={'management'}:report['groups']=[]
    if scopes=={'production'}:
        schedules=payroll.payload_range(c,'factory_schedules',*payroll.month_bounds(month))
        report['schedule_token']=hashlib.sha256(rc.dump([(r['id'],r['version'],r['state']) for r in schedules]).encode()).hexdigest()
        report['planned_leave']=[{'employee_id':e['employee_id'],'date':r['business_date']} for r in schedules if r['state']=='confirmed' for e in r.get('entries',[]) if e.get('status')=='leave']
    report['attendance_token']=hashlib.sha256(rc.dump({k:v for k,v in report.items() if k!='attendance_token'}).encode()).hexdigest();return report

def save_day(c,b,scope,role,now,audit,actor=None):
    import production_daily as daily
    access.require_role(role,type_permission(scope));key=rc.text(b.get('request_key'),'提交编号',100);day=rc.day(b.get('business_date'));employees={e['id']:e for e in rc.rows(c,'factory_employees')}
    entries=b.get('entries')
    if not isinstance(entries,list) or not entries:raise ValueError('请登记本类人员的实际考勤')
    if any(e.get('employee_id') not in employees or entry_type(e,employees)!=scope for e in entries):raise ValueError('不能跨人员类型登记考勤，请使用对应的考勤入口')
    finger=hashlib.sha256(rc.dump(b).encode()).hexdigest();claim='scoped-attendance:'+key
    prior=c.execute('SELECT value FROM meta WHERE key=?',(claim,)).fetchone()
    if prior:
        result=json.loads(prior[0])
        if result['fingerprint']==finger and result['scope']==scope:return result['record']
        raise ValueError('提交编号已用于其他考勤内容')
    matches=[r for r in rc.rows(c,'factory_attendance') if r['business_date']==day]
    if len(matches)>1:raise ValueError('当天存在考勤冲突，请先由管理员核对')
    old=matches[0] if matches else None;own=[e for e in (old or {}).get('entries',[]) if entry_type(e,employees)==scope]
    if b.get('id') and b['id']!=(old or {}).get('id'):raise ValueError('考勤记录已变化，请刷新')
    if (own or b.get('id')) and b.get('version',0)!=(old or {}).get('version',0):raise ValueError('考勤已变化，请刷新核对')
    if b.get('source_schedule_id'):
        schedule=next((r for r in rc.rows(c,'factory_schedules') if r['id']==b['source_schedule_id']),None)
        if scope!='production' or not schedule or schedule['business_date']!=day or schedule.get('state')!='confirmed' or schedule['version']!=b.get('source_schedule_version'):raise ValueError('来源排班已变化，请刷新后核对实际考勤')
    state=b.get('state','draft');normalized=daily.normalize_attendance(c,{**b,'format':'person-day-v1','groups':[]},old,rc.rows(c,'factory_groups'),list(employees.values()))
    others=[{**e,'entry_state':e.get('entry_state',(old or {}).get('state','draft'))} for e in (old or {}).get('entries',[]) if entry_type(e,employees)!=scope]
    selected=[{**e,'entry_state':state,'recorded_by':(actor or {}).get('display_name') or role,'recorded_user_id':(actor or {}).get('id',''),'recorded_at':now()} for e in normalized['entries']]
    if b.get('source_schedule_id'):normalized.update(source_schedule_id=b['source_schedule_id'],source_schedule_version=b['source_schedule_version'])
    notes={**(old or {}).get('scope_notes',{}),scope:normalized['note']}
    record={**(old or {}),**normalized,'id':(old or {}).get('id') or 'FP-'+secrets.token_hex(6).upper(),'entries':[*others,*selected],'scope_notes':notes,'note':(old or {}).get('note',''),'version':(old or {}).get('version',0)+1,'updated_at':now(),'role':role,'sequence':(old or {}).get('sequence',len(rc.rows(c,'factory_attendance'))+1)}
    if scope=='production' and not b.get('source_schedule_id'):
        record.pop('source_schedule_id',None);record.pop('source_schedule_version',None)
    record['state']='confirmed' if all(e['entry_state']=='confirmed' for e in record['entries']) else 'draft'
    if old:c.execute('UPDATE factory_attendance SET request_key=?,payload=? WHERE id=?',(key,rc.dump(record),record['id']))
    else:c.execute('INSERT INTO factory_attendance VALUES(?,?,?)',(record['id'],key,rc.dump(record)))
    result={**record,'entries':selected,'state':state,'note':normalized['note'],'scope_notes':{scope:normalized['note']}}
    c.execute('INSERT INTO meta VALUES(?,?)',(claim,rc.dump({'fingerprint':finger,'scope':scope,'record':result})))
    audit(c,role,'登记'+TYPES[scope]+'考勤',record['id'],old,record);return result

def save_month(c,b,role,now,audit,actor=None):
    import payroll,production_management as fm
    eid=b.get('employee_id');worker=next((e for e in rc.rows(c,'factory_employees') if e['id']==eid),None)
    if not worker:raise ValueError('厂内员工不存在')
    scope=worker.get('employee_type','production');access.require_role(role,type_permission(scope))
    if b.get('attendance_scope',scope)!=scope:raise ValueError('不能跨人员类型登记整月考勤')
    key=rc.text(b.get('request_key'),'提交编号',60);meta_key='person-attendance-month:'+key;finger=hashlib.sha256(rc.dump(b).encode()).hexdigest()
    prior=c.execute('SELECT value FROM meta WHERE key=?',(meta_key,)).fetchone()
    if prior:
        prior=json.loads(prior[0])
        if prior['fingerprint']==finger:return prior['result']
        raise ValueError('提交编号已用于其他考勤内容，请重新打开')
    month=b.get('month');days=payroll.month_days(month);report=attendance_report(c,month,{scope}) if b.get('attendance_scope') else payroll.attendance(c,month)
    if b.get('attendance_token')!=report['attendance_token']:raise ValueError('本月考勤、人员或排班已变化，请重新读取再核对')
    eid=b.get('employee_id');worker=next((e for e in rc.rows(c,'factory_employees') if e['id']==eid),None)
    if not worker:raise ValueError('厂内员工不存在')
    cells=b.get('cells')
    if not isinstance(cells,list) or not cells or len(cells)>len(days):raise ValueError('请选择本月要登记的日期和考勤')
    seen=set();plans=[];records=rc.rows(c,'factory_attendance')
    for cell in cells:
        day=cell.get('date');status=cell.get('status')
        if day not in days or day in seen:raise ValueError('考勤日期不属于所选月份或重复')
        seen.add(day)
        if day>payroll.local_today().isoformat():raise ValueError('未来日期不能登记为实际出勤')
        if status not in STATUSES:raise ValueError('请选择全天、半天、请假、缺勤或休息')
        matches=[r for r in records if r['business_date']==day]
        if len(matches)>1:raise ValueError(day+' 有多份考勤，请先在当天考勤核对冲突')
        old=matches[0] if matches else None;entries=(old or {}).get('entries',[])
        others=[{**e,'status':'full' if e.get('status')=='present' else e.get('status')} for e in entries if e['employee_id']!=eid]
        if old and any(e.get('entry_state',old.get('state'))!='confirmed' and e.get('status') not in ('unrecorded','') and entry_type(e,{p['id']:p for p in rc.rows(c,'factory_employees')})==scope for e in others):raise ValueError(day+' 其他人员考勤尚为草稿，请先核对当天考勤，避免代替他人确认')
        if old:others=[e for e in others if e.get('entry_state',old.get('state'))=='confirmed' or entry_type(e,{p['id']:p for p in rc.rows(c,'factory_employees')})!=scope]
        note=rc.text(cell.get('note',''),'考勤备注',200,False)
        plans.append((day,old,[*others,{'employee_id':eid,'group_id':worker.get('group_id',''),'status':status,'note':note}]))
    c.execute('SAVEPOINT personnel_month_attendance')
    try:
        for day,old,entries in plans:
            scoped_entries=[e for e in entries if entry_type(e,{p['id']:p for p in rc.rows(c,'factory_employees')})==scope]
            save_day(c,{'request_key':'month:'+key+':'+day,'id':(old or {}).get('id'),'version':(old or {}).get('version',0),'business_date':day,'state':'confirmed','entries':scoped_entries,'note':(old or {}).get('scope_notes',{}).get(scope,(old or {}).get('note',''))},scope,role,now,audit,actor=actor)
        result={'employee_id':eid,'month':month,'saved_days':len(plans),'state':'confirmed'}
        c.execute('INSERT INTO meta VALUES(?,?)',(meta_key,rc.dump({'fingerprint':finger,'result':result})))
        c.execute('RELEASE SAVEPOINT personnel_month_attendance');return result
    except Exception:
        c.execute('ROLLBACK TO SAVEPOINT personnel_month_attendance');c.execute('RELEASE SAVEPOINT personnel_month_attendance');raise

CONTRACTOR_KEY='transport_contractor_personnel_v1'

def contractor_rows(c):
    row=c.execute('SELECT value FROM meta WHERE key=?',(CONTRACTOR_KEY,)).fetchone()
    return json.loads(row[0]) if row else []

def contractor_report(c,month,day,role):
    import payroll
    if role not in ('管理员','物流负责人'):raise ValueError('承包方人员考勤仅供管理员和运输负责人使用')
    access.require_role(role,'delivery.contractors.read')
    payroll.month_days(month);rc.day(day)
    records=contractor_rows(c)
    return {'scope':'transport-contractor','month':month,'business_date':day,'staff':[r for r in records if r.get('kind')=='contractor-staff'],'attendance':[r for r in records if r.get('kind')=='contractor-attendance' and r['business_date'].startswith(month)],'basis':'承包方独立人员与考勤台账；不写入厂内员工、工资或人工成本。工厂运输承包费用沿原运费结算办理。'}

def save_contractor(c,kind,b,role,now,audit):
    import payroll
    access.require_role(role,'delivery.contractors.read');access.require_role(role,'delivery.contractors.write')
    if role not in ('管理员','物流负责人'):raise ValueError('承包方人员考勤仅供管理员和运输负责人维护')
    key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump(b).encode()).hexdigest();records=contractor_rows(c)
    scope=[r for r in records if r.get('kind') in ('contractor-staff','contractor-attendance')]
    prior=next((r for r in scope if r.get('request_key')==key),None)
    if prior:
        if prior.get('fingerprint')==finger:return prior
        raise ValueError('提交编号已用于其他内容')
    old=next((r for r in scope if r['id']==b.get('id') and r['kind']==kind),None)
    if b.get('id') and not old:raise ValueError('承包方记录不存在')
    if b.get('version',0)!=(old or {}).get('version',0):raise ValueError('承包方记录已变化，请刷新')
    if kind=='contractor-staff':
        record={'name':rc.text(b.get('name'),'人员姓名',60),'contractor':rc.text(b.get('contractor'),'所属承包方',100),'position':rc.text(b.get('position',''),'岗位',80,False),'phone':rc.text(b.get('phone',''),'联系电话',40,False),'note':rc.text(b.get('note',''),'备注',500,False),'active':b.get('active',True) is True}
    else:
        eid=b.get('employee_id');worker=next((r for r in scope if r['kind']=='contractor-staff' and r['id']==eid),None)
        if not worker or not worker.get('active') and not old:raise ValueError('请选择有效承包方人员')
        day=rc.day(b.get('business_date'))
        if day>payroll.local_today().isoformat():raise ValueError('未来日期不能登记实际出勤')
        if any(r['kind']=='contractor-attendance' and r['employee_id']==eid and r['business_date']==day and r['id']!=(old or {}).get('id') for r in scope):raise ValueError('此人员当天已有考勤，请打开原记录修改')
        status=b.get('status')
        if status not in STATUSES:raise ValueError('请选择有效考勤状态')
        record={'employee_id':eid,'employee_name':worker['name'],'contractor':worker['contractor'],'business_date':day,'status':status,'note':rc.text(b.get('note',''),'考勤备注',200,False)}
    record.update(id=(old or {}).get('id') or 'EXT-'+secrets.token_hex(8),kind=kind,scope='transport-contractor',version=(old or {}).get('version',0)+1,request_key=key,fingerprint=finger,updated_at=now())
    values=[r for r in records if r['id']!=record['id']]+[record]
    c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(CONTRACTOR_KEY,rc.dump(values)))
    audit(c,role,'维护承包方人员' if kind=='contractor-staff' else '登记承包方独立考勤',record['id'],old,record);return record
