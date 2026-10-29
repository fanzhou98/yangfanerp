"""Saved payroll evidence and actual payments; no current payroll recalculation."""
import json
from audit_query import _window, _page
from finance_query import _text
from payroll import month_days, PAYMENT_METHODS

STATUSES = {'draft':'草稿','conflict':'同月多份工资单待核查','unknown':'历史金额待核查',
            'unpaid':'未发放','partial':'部分发放','paid':'已发清','overpaid':'超额发放待核查'}
ROW_FIELDS = ('employee_id','employee_name','employee_type','group_name','department','position',
              'salary_mode','monthly_cents','annual_cents','monthly_basic_cents','base_cents',
              'bonus_cents','deduction_cents','social_base_cents','social_company_cents',
              'social_personal_cents','social_company_rate','social_personal_rate','net_cents',
              'pay_days','unpaid_days','entitlement_cents','rate_cents','reason','calculation_note')


def _source(kind, ranged=False):
    date_filter = " AND json_extract(payload,'$.business_date')>=? AND json_extract(payload,'$.business_date')<=?" if ranged else ''
    month_filter = " AND date(json_extract(payload,'$.month')||'-01','+1 month','-1 day')>=? AND date(json_extract(payload,'$.month')||'-01','+1 month','-1 day')<=?" if ranged else ''
    if kind == 'payment':
        return """WITH items AS (
          SELECT id, json_extract(payload,'$.business_date') AS business_date,
           json_extract(payload,'$.month') AS month,
           json_extract(payload,'$.employee_id') AS employee_id,
           COALESCE(json_extract(payload,'$.employee_name'),'未列') AS employee_name,
           json_extract(payload,'$.amount_cents') AS amount_cents,
           COALESCE(json_extract(payload,'$.handler'),'') AS handler,
           COALESCE(json_extract(payload,'$.reference'),'') AS reference,
           COALESCE(json_extract(payload,'$.method'),'unspecified') AS method,
           COALESCE(json_extract(payload,'$.updated_at'),'') AS updated_at
          FROM payroll_records WHERE json_extract(payload,'$.kind')='payment'
        """ + date_filter + ') '
    return """WITH heads AS (
      SELECT id,payload,COUNT(*) OVER (PARTITION BY json_extract(payload,'$.month')) AS matches
      FROM payroll_records WHERE json_extract(payload,'$.kind')='sheet'
    """ + month_filter + """), payments AS (
      SELECT json_extract(payload,'$.month') AS month,json_extract(payload,'$.employee_id') AS employee_id,
       CASE WHEN COUNT(*)=COUNT(json_extract(payload,'$.amount_cents')) THEN SUM(json_extract(payload,'$.amount_cents')) END AS paid_cents
      FROM payroll_records WHERE json_extract(payload,'$.kind')='payment' GROUP BY month,employee_id
    ), saved AS (
      SELECT h.id,CAST(j.key AS INTEGER) AS entry_index,
       json_extract(h.payload,'$.month') AS month,
       date(json_extract(h.payload,'$.month')||'-01','+1 month','-1 day') AS business_date,
       json_extract(j.value,'$.employee_id') AS employee_id,
       COALESCE(json_extract(j.value,'$.employee_name'),'未列') AS employee_name,
       COALESCE(json_extract(j.value,'$.employee_type'),'production') AS employee_type,
       COALESCE(json_extract(j.value,'$.group_name'),'') AS group_name,
       COALESCE(json_extract(j.value,'$.department'),'') AS department,
       COALESCE(json_extract(j.value,'$.reason'),'') AS reason,
       json_extract(j.value,'$.net_cents') AS net_cents,
       CASE WHEN p.employee_id IS NULL THEN 0 ELSE p.paid_cents END AS paid_cents,
       COALESCE(json_extract(h.payload,'$.state'),'') AS state,
       COALESCE(json_extract(h.payload,'$.updated_at'),'') AS updated_at,
       h.matches
      FROM heads h JOIN json_each(COALESCE(json_extract(h.payload,'$.rows'),'[]')) j
      LEFT JOIN payments p ON p.month=json_extract(h.payload,'$.month') AND p.employee_id=json_extract(j.value,'$.employee_id')
    ), items AS (
      SELECT *, CASE WHEN matches>1 THEN 'conflict' WHEN state='draft' THEN 'draft'
       WHEN state<>'confirmed' OR net_cents IS NULL OR paid_cents IS NULL THEN 'unknown'
       WHEN paid_cents>net_cents THEN 'overpaid' WHEN paid_cents=net_cents THEN 'paid'
       WHEN paid_cents=0 THEN 'unpaid' ELSE 'partial' END AS status,
       CASE WHEN state='confirmed' AND matches=1 THEN net_cents-paid_cents END AS outstanding_cents
      FROM saved
    ) """


def history(c, kind='sheet', *, start='', end='', all_dates=False, salary_month='',
            employee_id='', status='', search='', page=1, page_size=50):
    if kind not in ('sheet','payment'):raise ValueError('工资历史类型无效')
    start, end = _window(start,end,all_dates)
    page,page_size = _page(page,page_size)
    employee_id = _text(employee_id,'人员编号',100)
    search = _text(search,'搜索',100)
    if salary_month:month_days(salary_month)
    if status and (kind!='sheet' or status not in STATUSES):raise ValueError('工资状态无效')
    where,args = [],[]
    if not all_dates:where += ['business_date>=?','business_date<=?'];args += [start,end]
    if salary_month:where.append('month=?');args.append(salary_month)
    if employee_id:where.append('employee_id=?');args.append(employee_id)
    if status:where.append('status=?');args.append(status)
    if search:
        fields = "employee_name||' '||COALESCE(employee_id,'')||' '||handler||' '||reference" if kind=='payment' else "employee_name||' '||COALESCE(employee_id,'')||' '||group_name||' '||department||' '||reason"
        where.append('instr(lower('+fields+'),lower(?))>0');args.append(search)
    tail = ' FROM items'+(' WHERE '+' AND '.join(where) if where else '')
    source = _source(kind, not all_dates)
    if not all_dates:args = [start,end,*args]
    if kind=='sheet':
        summary = dict(c.execute(source+"SELECT COUNT(*) AS total,COUNT(DISTINCT id) AS sheets,COUNT(DISTINCT month) AS months,COUNT(DISTINCT employee_id) AS employees,"+
            ','.join("COALESCE(SUM(status='"+k+"'),0) AS "+k for k in STATUSES)+""",
            COALESCE(SUM(CASE WHEN state='confirmed' AND matches=1 THEN net_cents END),0) AS net_cents,
            COALESCE(SUM(CASE WHEN state='confirmed' AND matches=1 THEN paid_cents END),0) AS paid_cents,
            COALESCE(SUM(outstanding_cents),0) AS outstanding_cents"""+tail,args).fetchone())
        fields='id,entry_index,business_date,month,employee_id,employee_name,employee_type,group_name,department,reason,net_cents,paid_cents,outstanding_cents,state,status,updated_at'
        order='business_date DESC,id DESC,entry_index ASC'
    else:
        summary = dict(c.execute(source+"SELECT COUNT(*) AS total,COUNT(DISTINCT employee_id) AS employees,COALESCE(SUM(amount_cents),0) AS amount_cents,COALESCE(SUM(amount_cents IS NULL),0) AS unknown"+tail,args).fetchone())
        fields='*';order='business_date DESC,id DESC'
    total = summary.pop('total');pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    rows=[dict(r) for r in c.execute(source+'SELECT '+fields+tail+' ORDER BY '+order+' LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size])]
    for row in rows:
        if kind=='sheet':row['status_label']=STATUSES[row['status']]
        else:row['method_label']=PAYMENT_METHODS.get(row['method'],'历史未注明')
    return {'kind':kind,'rows':rows,'summary':summary,'total':total,'pages':pages,'page':page,'page_size':page_size,
            'range':{'start':start,'end':end,'all_dates':bool(all_dates)},
            'basis':('按工资所属月末日期筛选已保存人员项；应发取原单快照。已发与未发为当前全部发放累计，不按查询日期重建余额；草稿与冲突不计应付汇总。' if kind=='sheet' else '按实际发放日期筛选付款流水；工资所属月份单列。只统计发放，不重复计工资成本。')}


def record(c, kind, record_id, employee_id=''):
    if kind not in ('sheet','payment'):raise ValueError('工资历史类型无效')
    found=c.execute("SELECT payload FROM payroll_records WHERE id=? AND json_extract(payload,'$.kind')=?",(record_id,kind)).fetchone()
    if not found:raise ValueError('工资原记录不存在')
    saved=json.loads(found[0])
    result={k:saved.get(k,'') for k in ('id','month','version','updated_at')}
    result['kind']=kind
    if kind=='payment':
        result.update({k:saved.get(k) for k in ('business_date','employee_id','employee_name','amount_cents','handler','reference','method')})
        recipient=saved.get('recipient') or {}
        result['recipient']={k:recipient.get(k,'') for k in ('bank_name','account_name','card_tail')}
        if not result['recipient']['card_tail'] and recipient.get('bank_card'):result['recipient']['card_tail']=recipient['bank_card'][-4:]
    else:
        row=next((r for r in saved.get('rows',[]) if r.get('employee_id')==employee_id),None)
        if row is None:raise ValueError('工资原单没有此人员')
        result.update(state=saved.get('state',''),confirmed_at=saved.get('confirmed_at',''),cost_accrual_mode=saved.get('cost_accrual_mode',''))
        result['row']={k:row.get(k) for k in ROW_FIELDS}
        result['cells']=[{k:cell.get(k,'') for k in ('date','status','label','group_name','note')} for cell in row.get('cells',[])]
    return result
