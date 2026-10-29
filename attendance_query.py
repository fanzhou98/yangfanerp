"""Read-only, scoped person/day attendance history; never infer missing days."""
from audit_query import _window, _page
from finance_query import _text
import personnel
import json
from payroll import local_today, month_days

LABELS = {'full': '全天', 'half': '半天', 'leave': '请假', 'absent': '缺勤',
          'rest': '休息', 'draft': '草稿', 'conflict': '同人同日冲突',
          'unrecorded': '未登记', 'unknown': '旧状态待核查', 'future': '未来日期待核查'}
DATE_EXPR = "json_extract(a.payload,'$.business_date')"


def month_record_count(c, month, employee_id, scopes):
    days=month_days(month)
    employee_id=_text(employee_id,'人员编号',100)
    if not employee_id:raise ValueError('请选择员工')
    scopes=sorted(set(scopes))
    if not scopes or any(scope not in personnel.TYPES for scope in scopes):raise ValueError('人员范围无效')
    total=c.execute("""SELECT COUNT(*) FROM factory_attendance a
      WHERE json_extract(a.payload,'$.business_date')>=? AND json_extract(a.payload,'$.business_date')<=?
      AND EXISTS (SELECT 1 FROM json_each(json_extract(a.payload,'$.entries')) j
       LEFT JOIN factory_employees e ON e.id=json_extract(j.value,'$.employee_id')
       WHERE json_extract(j.value,'$.employee_id')=?
       AND COALESCE(json_extract(e.payload,'$.employee_type'),json_extract(j.value,'$.employee_type'),'production') IN ("""+
       ','.join('?' for _ in scopes)+'))',[days[0],days[-1],employee_id,*scopes]).fetchone()[0]
    return {'month':month,'employee_id':employee_id,'record_count':total}


def day_records(c, business_date, scope, grants):
    """Read one working day through the existing personnel projection rules."""
    import resources_costs as rc
    import production_management as factory
    business_date=rc.day(business_date)
    personnel.type_permission(scope)
    source={'employees':rc.rows(c,'factory_employees')}
    for key,table in (('attendance','factory_attendance'),('schedules','factory_schedules')):
        source[key]=[json.loads(r[0]) for r in c.execute(
            "SELECT payload FROM "+table+" WHERE json_extract(payload,'$.business_date')=? ORDER BY rowid",(business_date,))]
    projected=factory.scope(source,{**grants,'modules':[personnel.type_permission(scope)]})
    if len(projected.get('attendance',[]))>1 or len(projected.get('schedules',[]))>1:
        raise ValueError('当天有多份考勤或排班记录，请管理员先核对冲突')
    return {'business_date':business_date,'scope':scope,
            'attendance':next(iter(projected.get('attendance',[])),None),
            'schedule':next(iter(projected.get('schedules',[])),None)}


def history(c, scopes, *, start='', end='', all_dates=False, employee_id='',
            status='', search='', page=1, page_size=50):
    scopes = sorted(set(scopes))
    if not scopes or any(s not in personnel.TYPES for s in scopes):
        raise ValueError('请选择有效的人员范围')
    start, end = _window(start, end, all_dates)
    page, page_size = _page(page, page_size)
    employee_id = _text(employee_id, '人员编号', 100)
    search = _text(search, '搜索', 100)
    if status and status not in LABELS:
        raise ValueError('考勤状态无效')
    dates, args = '', []
    if not all_dates:
        dates = ' WHERE ' + DATE_EXPR + '>=? AND ' + DATE_EXPR + '<=?'
        args += [start, end]
    # Count duplicates before status, person and keyword filtering. A filtered
    # list must not make a conflicting person/day appear valid for attendance.
    sql = """WITH entries AS (
      SELECT a.id AS record_id, json_extract(a.payload,'$.business_date') AS business_date,
       CAST(j.key AS INTEGER) AS entry_index,
       COALESCE(json_extract(j.value,'$.employee_id'),'') AS employee_id,
       COALESCE(json_extract(j.value,'$.employee_name'),json_extract(e.payload,'$.name'),'未列') AS employee_name,
       COALESCE(json_extract(e.payload,'$.employee_type'),json_extract(j.value,'$.employee_type'),'production') AS scope,
       COALESCE(json_extract(j.value,'$.group_name'),'') AS group_name,
       COALESCE(json_extract(j.value,'$.department'),'') AS department,
       COALESCE(json_extract(j.value,'$.note'),'') AS note,
       COALESCE(json_extract(j.value,'$.recorded_by'),'') AS recorded_by,
       COALESCE(json_extract(j.value,'$.recorded_at'),'') AS recorded_at,
       COALESCE(json_extract(a.payload,'$.version'),0) AS version,
       COALESCE(json_extract(j.value,'$.entry_state'),json_extract(a.payload,'$.state'),'') AS entry_state,
       COALESCE(json_extract(j.value,'$.status'),'') AS raw_status
      FROM factory_attendance a JOIN json_each(COALESCE(json_extract(a.payload,'$.entries'),'[]')) j
      LEFT JOIN factory_employees e ON e.id=json_extract(j.value,'$.employee_id')
    """ + dates + """), scoped AS (
      SELECT *,COUNT(*) OVER (PARTITION BY business_date,employee_id) AS matches
      FROM entries WHERE scope IN (""" + ','.join('?' for _ in scopes) + """ )
    ), classified AS (
      SELECT *,CASE WHEN matches>1 THEN 'conflict'
       WHEN business_date>? THEN 'future'
       WHEN entry_state<>'confirmed' THEN 'draft'
       WHEN raw_status='present' THEN 'full'
       WHEN raw_status IN ('full','half','leave','absent','rest') THEN raw_status
       WHEN raw_status IN ('','unrecorded','missing') THEN 'unrecorded'
       ELSE 'unknown' END AS status FROM scoped
    ) """
    args += [*scopes, local_today().isoformat()]
    where, filters = [], []
    if employee_id:
        where.append('employee_id=?'); filters.append(employee_id)
    if status:
        where.append('status=?'); filters.append(status)
    if search:
        where.append("instr(lower(employee_name||' '||employee_id||' '||group_name||' '||department||' '||note||' '||recorded_by),lower(?))>0")
        filters.append(search)
    tail = ' FROM classified' + (' WHERE ' + ' AND '.join(where) if where else '')
    args += filters
    summary = dict(c.execute(sql + "SELECT COUNT(*) AS total,COUNT(DISTINCT business_date) AS dates,COUNT(DISTINCT employee_id) AS employees," +
                            ','.join("COALESCE(SUM(status='" + k + "'),0) AS " + k for k in LABELS) + tail, args).fetchone())
    total = summary.pop('total')
    summary['attendance_days'] = str(summary['full'] + summary['half'] / 2).removesuffix('.0')
    pages = max(1, (total + page_size - 1) // page_size); page = min(page, pages)
    fields = 'record_id,business_date,entry_index,employee_id,employee_name,scope,group_name,department,note,recorded_by,recorded_at,version,entry_state,raw_status,status'
    rows = [dict(r) for r in c.execute(sql + 'SELECT ' + fields + tail +
            ' ORDER BY business_date DESC,record_id DESC,entry_index ASC LIMIT ? OFFSET ?', [*args, page_size, (page-1)*page_size])]
    for row in rows:
        row['status_label'] = LABELS[row['status']]
    return {'rows': rows, 'summary': summary, 'total': total, 'pages': pages, 'page': page, 'page_size': page_size,
            'range': {'start': start, 'end': end, 'all_dates': bool(all_dates)}, 'scopes': scopes,
            'basis': '仅列已保存的人员考勤项；缺少日期不补零。草稿、冲突、未登记及未来记录不计出勤折合天数；不等于工资计薪天数。'}
