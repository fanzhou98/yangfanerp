"""SQL expense states and accrual reads; original bills remain authoritative.

The indexed accrual lookup is maintained by SQLite triggers. Workflow facts
are read from approvals, payments and wage sheets in the same read snapshot.
Only page bills are decoded for the existing full-detail normalizer.
"""
import json
import resources_costs as rc


def register(c):
    c.create_function('erp_strip',1,lambda v:str(v or '').strip(),deterministic=True)


def dicts(c,sql,args=()):
    cur=c.execute(sql,args);names=[d[0] for d in cur.description]
    return [dict(zip(names,row)) for row in cur]


def projection(condition='1',args=(),period='',payables=False):
    recognized="(SELECT COALESCE(SUM(a.amount_cents),0) FROM expense_accrual_lookup a WHERE a.expense_id=e.id AND a.period=?)" if period else "json_extract(e.payload,'$.amount_cents')"
    params=[*([period] if period else []),*args]
    sql="""WITH selected AS (
      SELECT e.id,e.payload,"""+recognized+""" AS recognized_cents,
        json_extract(e.payload,'$.amount_cents') AS amount_cents,
        json_extract(e.payload,'$.business_date') AS business_date,
        json_extract(e.payload,'$.period') AS period,
        json_extract(e.payload,'$.category') AS category,
        COALESCE(json_extract(e.payload,'$.voided'),0) AS voided,
        COALESCE(json_extract(e.payload,'$.partner'),'') AS original_partner,
        COALESCE(json_extract(e.payload,'$.payroll_sheet_id'),'') AS sheet_id,
        CASE WHEN json_type(e.payload,'$.payment_mode') IS NOT NULL THEN json_extract(e.payload,'$.payment_mode')
             WHEN json_type(e.payload,'$.category_snapshot.payment_mode') IS NOT NULL THEN json_extract(e.payload,'$.category_snapshot.payment_mode')
             WHEN substr(json_extract(e.payload,'$.category'),1,6)='wages-' THEN 'payroll'
             WHEN json_extract(e.payload,'$.category')='depreciation' THEN 'noncash' ELSE 'payable' END AS payment_mode,
        COALESCE((SELECT SUM(json_extract(p.payload,'$.amount_cents')) FROM expense_payments p WHERE json_extract(p.payload,'$.expense_id')=+e.id),0) AS event_paid,
        (SELECT r.payload FROM expense_reviews r WHERE json_extract(r.payload,'$.expense_id')=+e.id AND COALESCE(json_extract(r.payload,'$.expense_version'),0)>=COALESCE(json_extract(e.payload,'$.review_reset_version'),0) ORDER BY r.rowid DESC LIMIT 1) AS review_payload,
        (SELECT COUNT(DISTINCT erp_strip(json_extract(p.payload,'$.payee'))) FROM expense_payments p WHERE json_extract(p.payload,'$.expense_id')=+e.id AND erp_strip(json_extract(p.payload,'$.payee'))!='') AS payee_count,
        (SELECT MIN(erp_strip(json_extract(p.payload,'$.payee'))) FROM expense_payments p WHERE json_extract(p.payload,'$.expense_id')=+e.id AND erp_strip(json_extract(p.payload,'$.payee'))!='') AS only_payee
      FROM indirect_expenses e WHERE """+condition+"""
    ), facts AS (
      SELECT *,CASE WHEN erp_strip(original_partner)='' AND payee_count=1 THEN only_payee ELSE original_partner END AS partner,
        COALESCE(payment_mode='payable',0) AS payment_required,
        CASE WHEN sheet_id!='' AND NOT voided THEN COALESCE((
          SELECT SUM(json_extract(p.payload,'$.amount_cents')) FROM payroll_records p
          WHERE json_extract(p.payload,'$.kind')='payment' AND json_extract(p.payload,'$.month')=selected.period
            AND json_extract(p.payload,'$.employee_id') IN (
              SELECT json_extract(s.value,'$.employee_id') FROM payroll_records sheet,json_each(sheet.payload,'$.rows') s
              WHERE sheet.id=selected.sheet_id AND CASE WHEN json_type(s.value,'$.salary_category') IS NULL THEN 'wages-production' ELSE json_extract(s.value,'$.salary_category') END=selected.category)
        ),0) ELSE event_paid END AS paid_cents
      FROM selected
    ), states AS (
      SELECT *,CASE
        WHEN payment_required AND erp_strip(partner)='' AND event_paid=0 THEN 'pending'
        WHEN voided THEN 'voided'
        WHEN payment_mode='payroll' OR substr(category,1,6)='wages-' THEN 'payroll'
        WHEN NOT payment_required THEN 'noncash'
        WHEN event_paid=amount_cents THEN 'paid'
        WHEN event_paid!=0 THEN 'partial'
        WHEN review_payload IS NULL THEN 'pending'
        WHEN json_extract(review_payload,'$.decision')='return' THEN 'returned' ELSE 'approved' END AS payment_state,
        CASE WHEN (payment_required OR sheet_id!='') AND NOT voided THEN amount_cents-paid_cents ELSE 0 END AS outstanding_cents
      FROM facts
    ), projected AS (SELECT * FROM states"""+(" WHERE payment_required=1" if payables else '')+') '
    return sql,params


def page_numbers(total,page,page_size):
    pages=max(1,(total+page_size-1)//page_size)
    return min(int(page),pages),pages


def ledger(c,kind,condition,args,*,period='',stage='all',page=1,page_size=50,payment_start='',payment_end=''):
    if not c.in_transaction:c.execute('BEGIN')
    register(c);sql,params=projection(condition,args,period,kind!='expenses')
    summary=dicts(c,sql+"""SELECT COUNT(*) AS count,COALESCE(SUM(recognized_cents),0) AS total_cents,
      COALESCE(SUM(CASE WHEN substr(category,1,6)='wages-' THEN recognized_cents ELSE 0 END),0) AS wages_cents,
      COALESCE(SUM(CASE WHEN category='wages-delivery' THEN recognized_cents ELSE 0 END),0) AS historical_delivery_cents,
      COALESCE(SUM(CASE WHEN COALESCE(json_extract(payload,'$.product_id'),'')='' THEN recognized_cents ELSE 0 END),0) AS shared_cents,
      COALESCE(SUM(paid_cents),0) AS paid_cents,COALESCE(SUM(outstanding_cents),0) AS outstanding_cents,
      COALESCE(SUM(payment_state='pending'),0) AS pending_count,
      COALESCE(SUM(CASE WHEN payment_state IN ('approved','partial') THEN outstanding_cents ELSE 0 END),0) AS approved_outstanding_cents
      FROM projected WHERE NOT voided""",params)[0]
    categories={key:value for key,value in c.execute(sql+'SELECT category,SUM(recognized_cents) FROM projected WHERE NOT voided GROUP BY category',params)}
    if kind=='payments':
        source='expense_payments p'+(' INDEXED BY expense_payments_date_id' if payment_start else '')
        where="json_extract(p.payload,'$.expense_id') IN (SELECT +id FROM projected WHERE NOT voided)";values=list(params)
        if payment_start:where+=" AND json_extract(p.payload,'$.business_date') BETWEEN ? AND ?";values.extend([payment_start,payment_end])
        total,amount=c.execute(sql+'SELECT COUNT(*),COALESCE(SUM(json_extract(p.payload,\'$.amount_cents\')),0) FROM '+source+' WHERE '+where,values).fetchone()
        current,pages=page_numbers(total,page,page_size)
        rows=[json.loads(r[0]) for r in c.execute(sql+'SELECT p.payload FROM '+source+' WHERE '+where+" ORDER BY json_extract(p.payload,'$.business_date') DESC,p.id DESC LIMIT ? OFFSET ?",[*values,page_size,(current-1)*page_size])]
        return dict(rows=rows,total=total,page=current,pages=pages,summary=summary,categories=categories,payment_summary={'count':total,'amount_cents':amount})
    if stage=='voided':where='voided'
    else:
        where='NOT voided'
        if stage=='review':where+=" AND payment_state='pending'"
        elif stage=='pay':where+=" AND payment_state IN ('approved','partial')"
        elif stage!='all':where+=' AND payment_state=?';params=[*params,stage]
    total=c.execute(sql+'SELECT COUNT(*) FROM projected WHERE '+where,params).fetchone()[0]
    current,pages=page_numbers(total,page,page_size)
    selected=[json.loads(r[0]) for r in c.execute(sql+'SELECT payload FROM projected WHERE '+where+' ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?',[*params,page_size,(current-1)*page_size])]
    return dict(rows=rc.expense_projection(c,selected),total=total,page=current,pages=pages,summary=summary,categories=categories)


def record(c,record_id):
    row=c.execute('SELECT payload FROM indirect_expenses WHERE id=?',(record_id,)).fetchone()
    if not row:return None
    return rc.expense_projection(c,[json.loads(row[0])])[0]


def workflow(c,day,limit=20):
    rc.day(day)
    if not c.in_transaction:c.execute('BEGIN')
    register(c);sql,args=projection(payables=True)
    groups={}
    completed_review=c.execute(sql+"SELECT COUNT(*) FROM projected WHERE substr(json_extract(review_payload,'$.created_at'),1,10)=?",[*args,day]).fetchone()[0]
    completed_pay=c.execute("SELECT COUNT(*) FROM expense_payments WHERE json_extract(payload,'$.business_date')=?",(day,)).fetchone()[0]
    for key,states,completed in [('costs.review',('pending',),completed_review),('costs.pay',('approved','partial'),completed_pay),('costs.write',('returned',),0)]:
        where='NOT voided AND payment_state IN ('+','.join('?' for _ in states)+') AND business_date<=?';params=[*args,*states,day]
        current=c.execute(sql+'SELECT COALESCE(SUM(business_date=?),0),COALESCE(SUM(business_date<?),0) FROM projected WHERE '+where,[*args,day,day,*states,day]).fetchone()
        items=dicts(c,sql+"SELECT id,business_date,period,COALESCE(NULLIF(partner,''),json_extract(payload,'$.note'),'') AS customer_name FROM projected WHERE "+where+' ORDER BY business_date,id LIMIT ?',[*params,limit])
        groups[key]={'today':current[0],'carry':current[1],'completed':completed,'items':items,'limit':limit}
    return {'day':day,'groups':groups}
