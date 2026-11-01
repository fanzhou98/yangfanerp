"""SQL projection of actual cash facts, without copying or rewriting ledgers.

Only small account aggregates and one requested page leave SQLite. Embedded
bean receipts/refunds have their OWN dates; a parent sale date never restricts
these arrays. Fingerprints match funds.movements exactly for safe assignment.
"""
import calendar
import hashlib
import json
import sqlite3
from datetime import date
import resources_costs as rc


def register(c):
    def amount(value,kind):
        if kind!='integer' or type(value) is not int or value<0:
            raise ValueError('资金流水金额无效，请核对原业务台账')
        return value
    def fingerprint(key,day,value,direction):
        return hashlib.sha256(rc.dump({'id':key,'business_date':day,'amount_cents':value,'direction':direction}).encode()).hexdigest()
    c.create_function('erp_cash_amount',2,amount,deterministic=True)
    c.create_function('erp_cash_fingerprint',4,fingerprint,deterministic=True)


def field(key,alias='r'):
    return f"json_extract({alias}.payload,'$.{key}')"


def projection(start='',end=''):
    """All table names, aliases and expressions are trusted constants."""
    def dates(expression):
        return (' AND '+expression+'>=:cash_start' if start else '')+(' AND '+expression+'<=:cash_end' if end else '')
    def note(alias='r'):
        return "COALESCE(NULLIF("+field('note',alias)+",''),"+field('reference',alias)+",'')"
    def checked(value,kind=None):return "erp_cash_amount("+value+","+(kind or "'integer'")+")"
    def direct(table,prefix,day,direction,label,partner,condition='1',account=None):
        value=checked(field('amount_cents'),"json_type(r.payload,'$.amount_cents')")
        return "SELECT '"+prefix+"'||"+field('id')+","+day+","+value+",'"+direction+"','"+label+"',"+partner+",COALESCE("+(account or field('account_id'))+",''),"+note()+" FROM "+table+" r WHERE "+condition+dates(day)+" AND "+value+">0"
    parts=[direct('receipts','receipt:',field('received_date'),'in','产品收款',"COALESCE("+field('customer_name')+",'')","COALESCE("+field('voided')+",0)=0")]
    parts.append(direct('purchase_payments','purchase_payments:',field('business_date'),'out','采购付款',"COALESCE(NULLIF("+field('payee_name')+",''),"+field('supplier_name')+",'')",'COALESCE('+field('voided')+',0)=0'))
    parts.append(direct('expense_payments','expense_payments:',field('business_date'),'out','费用付款',"COALESCE(NULLIF("+field('payee_name')+",''),"+field('payee')+",'')"))
    parts.append(direct('payroll_records','payroll:',field('business_date'),'out','工资发放',"COALESCE("+field('employee_name')+",'')",field('kind')+"='payment' AND COALESCE("+field('voided')+",0)=0"))
    parts.append(direct('finished_goods_records','finished:',field('business_date'),'out','外购成品付款',"COALESCE("+field('supplier_name')+",'')",field('kind')+"='payment' AND COALESCE("+field('voided')+",0)=0"))
    parts.append(direct('finished_goods_records','finished-refund:',field('business_date'),'in','外购成品供应商退款',"COALESCE("+field('supplier_name')+",'')",field('kind')+"='refund'"))
    initial=checked(field('received_cents')+"-COALESCE((SELECT SUM(json_extract(x.value,'$.amount_cents')) FROM json_each(r.payload,'$.receipts') x),0)")
    parts.append("SELECT 'byproduct:'||r.id||':initial',"+field('business_date')+","+initial+",'in','豆渣收款',"+field('buyer')+",COALESCE("+field('account_id')+",''),"+note()+" FROM byproduct_sales r WHERE COALESCE("+field('voided')+",0)=0"+dates(field('business_date'))+' AND '+initial+'>0')
    for table,path,prefix,daykey,direction,label,partner in (
        ('byproduct_sales','receipts',"'byproduct:'||r.id||':'||x.key",'business_date','in','豆渣收款','buyer'),
        ('sales_returns','finance.refunds',"'refund:'||json_extract(x.value,'$.id')",'refund_date','out','退货退款','customer_name')):
        day="json_extract(x.value,'$."+daykey+"')";value=checked("json_extract(x.value,'$.amount_cents')","json_type(x.value,'$.amount_cents')")
        parts.append("SELECT "+prefix+","+day+","+value+",'"+direction+"','"+label+"',COALESCE("+field(partner)+",''),COALESCE(json_extract(x.value,'$.account_id'),''),COALESCE(NULLIF(json_extract(x.value,'$.note'),''),json_extract(x.value,'$.reference'),'') FROM "+table+" r,json_each(r.payload,'$."+path+"') x WHERE COALESCE("+field('voided')+",0)=0 AND COALESCE(json_extract(x.value,'$.voided'),0)=0"+dates(day)+' AND '+value+'>0')
    for suffix,direction,account,other in (('out','out','from_account_id','to_account_id'),('in','in','to_account_id','from_account_id')):
        part=direct('fund_transfers','transfer:',field('business_date'),direction,'内部转账',field(other),account=field(account))
        part=part.replace("'transfer:'||"+field('id')+",","'transfer:'||"+field('id')+"||':"+suffix+"',")
        parts.append(part)
    sql="WITH raw(id,business_date,amount_cents,direction,source,partner,source_account_id,note) AS ("+' UNION ALL '.join(parts)+"""), signed AS (
      SELECT *,erp_cash_fingerprint(id,business_date,amount_cents,direction) AS fingerprint FROM raw
    ), resolved AS (
      SELECT m.*,COALESCE(json_extract(a.payload,'$.version'),0) AS assignment_version,
        CASE WHEN m.source!='内部转账' AND json_extract(a.payload,'$.fingerprint')=m.fingerprint
             THEN json_extract(a.payload,'$.account_id') ELSE m.source_account_id END AS account_id
      FROM signed m LEFT JOIN fund_assignments a ON a.movement_id=m.id
    ) """
    return sql,{'cash_start':start,'cash_end':end}


def dicts(c,sql,params):
    cur=c.execute(sql,params);names=[r[0] for r in cur.description]
    return [dict(zip(names,r)) for r in cur]


def report(c,asof,*,month='',start='',end='',account_id='',direction='',page=None,page_size=50):
    rc.day(asof)
    if direction not in ('','in','out'):raise ValueError('资金收支方向无效')
    if not isinstance(account_id,str) or len(account_id)>100:raise ValueError('资金账户编号无效')
    if type(page_size) is not int or not 1<=page_size<=200:raise ValueError('每页条数须在 1 到 200 之间')
    if page is not None and (type(page) is not int or not 1<=page<=100000):raise ValueError('页码无效')
    if bool(start)!=bool(end):raise ValueError('请同时填写资金流水开始和结束日期')
    if start:
        rc.day(start);rc.day(end)
        if start>end or (date.fromisoformat(end)-date.fromisoformat(start)).days>3651:raise ValueError('资金流水日期须正序且不超过3652天')
    if month:
        try:
            if len(month)!=7:raise ValueError()
            rc.day(month+'-01')
        except (ValueError,TypeError):raise ValueError('资金流水月份无效')
        if start:raise ValueError('月份与自定义流水日期不能同时使用')
        start=month+'-01';end=month+'-%02d'%calendar.monthrange(int(month[:4]),int(month[5:]))[1]
    flow_end=min(end,asof) if end else asof
    if not c.in_transaction:c.execute('BEGIN')
    register(c)
    try:
        return _report(c,asof,start,flow_end,account_id,direction,page,page_size)
    except sqlite3.OperationalError as error:
        if 'user-defined function raised exception' in str(error):raise ValueError('资金流水金额无效，请核对原业务台账') from error
        raise


def _report(c,asof,start,end,account_id,direction,page,page_size):
    sql,params=projection('',asof)
    clients=[json.loads(r[0]) for r in c.execute('SELECT payload FROM fund_accounts ORDER BY rowid')]
    aggregate=dicts(c,sql+"""SELECT a.id,
      COALESCE(SUM(CASE WHEN m.direction='in' THEN m.amount_cents ELSE 0 END),0) AS income_cents,
      COALESCE(SUM(CASE WHEN m.direction='out' THEN m.amount_cents ELSE 0 END),0) AS expense_cents
      FROM fund_accounts a LEFT JOIN resolved m ON m.account_id=a.id AND m.business_date>=json_extract(a.payload,'$.opening_date') GROUP BY a.id""",params)
    byid={r['id']:r for r in aggregate}
    all_sql,all_params=projection()
    # Future facts must also protect account deletion / opening-balance edits.
    counts=dicts(c,all_sql+'SELECT a.id,COUNT(m.id) AS n FROM fund_accounts a LEFT JOIN resolved m ON m.account_id=a.id OR m.source_account_id=a.id GROUP BY a.id',all_params)
    count_byid={r['id']:r['n'] for r in counts}
    for a in clients:
        row=byid[a['id']];a['income_cents']=row['income_cents'];a['expense_cents']=row['expense_cents']
        a['balance_cents']=a['opening_balance_cents']+a['income_cents']-a['expense_cents'] if a['opening_date']<=asof else None
        a['movement_count']=count_byid[a['id']]
    pending=dicts(c,sql+"SELECT COUNT(*) AS n,COALESCE(SUM(CASE WHEN direction='in' THEN amount_cents ELSE 0 END),0) AS income,COALESCE(SUM(CASE WHEN direction='out' THEN amount_cents ELSE 0 END),0) AS expense FROM resolved m WHERE NOT EXISTS (SELECT 1 FROM fund_accounts a WHERE a.id=m.account_id)",params)[0]
    month_sql,month_params=projection(asof[:7]+'-01',asof)
    monthly=dicts(c,month_sql+"SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount_cents ELSE 0 END),0) AS income,COALESCE(SUM(CASE WHEN direction='out' THEN amount_cents ELSE 0 END),0) AS expense FROM resolved WHERE source!='内部转账'",month_params)[0]
    flow_sql,flow_params=projection(start,end);scope=['1']
    if account_id=='__pending__':scope.append('NOT EXISTS (SELECT 1 FROM fund_accounts a WHERE a.id=m.account_id)')
    elif account_id:scope.append('m.account_id=:account_id');flow_params['account_id']=account_id
    if direction:scope.append('m.direction=:direction');flow_params['direction']=direction
    scope=' AND '.join(scope)
    totals=dicts(c,flow_sql+"SELECT COUNT(*) AS count,COALESCE(SUM(CASE WHEN direction='in' THEN amount_cents ELSE 0 END),0) AS income_cents,COALESCE(SUM(CASE WHEN direction='out' THEN amount_cents ELSE 0 END),0) AS expense_cents FROM resolved m WHERE "+scope,flow_params)[0]
    total=totals['count'];pages=max(1,(total+page_size-1)//page_size);current=min(page or 1,pages)
    page_sql='SELECT * FROM resolved m WHERE '+scope+' ORDER BY business_date DESC,id DESC'
    if page is not None:page_sql+=' LIMIT :limit OFFSET :offset';flow_params.update(limit=page_size,offset=(current-1)*page_size)
    shown=dicts(c,flow_sql+page_sql,flow_params)
    for r in shown:
        if r['source']=='内部转账':r.pop('assignment_version',None)
    # ar_alerts clamps overpaid bills and ignores unlinked legacy bean customers.
    # A bill is collected as of the day only by receipts actually received by
    # then; a later receipt must not rewrite an earlier day's receivable.
    paid={r[0]:int(r[1] or 0) for r in c.execute("""SELECT json_extract(payload,'$.order_id') AS order_id,
      SUM(COALESCE(json_extract(payload,'$.amount_cents'),0)) AS amount_cents FROM receipts
      WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 AND json_extract(payload,'$.received_date')<=:asof
      GROUP BY json_extract(payload,'$.order_id')""",{'asof':asof})}
    receivable=sum(max(0,int(r[1] or 0)-paid.get(r[0],0)-int(r[2] or 0)-int(r[3] or 0)-int(r[4] or 0)) for r in c.execute("""SELECT id,
      json_extract(payload,'$.total_cents'),json_extract(payload,'$.return_credit_cents'),
      json_extract(payload,'$.discount_cents'),json_extract(payload,'$.rounding_cents') FROM orders
      WHERE json_extract(payload,'$.state')='reviewed' AND json_extract(payload,'$.business_date')<=:asof""",{'asof':asof}))
    receivable+=c.execute("""SELECT COALESCE(SUM(balance),0) FROM (
      SELECT MAX(0,COALESCE(json_extract(payload,'$.amount_cents'),0)
        -(MAX(0,COALESCE(json_extract(payload,'$.received_cents'),0)-COALESCE((SELECT SUM(COALESCE(json_extract(x.value,'$.amount_cents'),0)) FROM json_each(payload,'$.receipts') x),0))
         +COALESCE((SELECT SUM(COALESCE(json_extract(x.value,'$.amount_cents'),0)) FROM json_each(payload,'$.receipts') x WHERE COALESCE(json_extract(x.value,'$.business_date'),'')<=:asof),0))) AS balance
        FROM byproduct_sales WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 AND COALESCE(json_extract(payload,'$.customer_id'),'')!='' AND json_extract(payload,'$.business_date')<=:asof
      UNION ALL SELECT MAX(0,opening_cents-COALESCE((SELECT SUM(COALESCE(json_extract(r.payload,'$.amount_cents'),0)+COALESCE(json_extract(r.payload,'$.discount_cents'),0)+COALESCE(json_extract(r.payload,'$.rounding_cents'),0)) FROM receipts r WHERE json_extract(r.payload,'$.order_id')='' AND COALESCE(json_extract(r.payload,'$.voided'),0)=0 AND json_extract(r.payload,'$.customer_id')=customers.id AND json_extract(r.payload,'$.received_date')<=:asof),0)) FROM customers WHERE opening_cents>0 AND opening_date<>'' AND opening_date<=:asof
    )""",{'asof':asof}).fetchone()[0]
    return {'as_of':asof,'flow_start':start,'flow_end':end,'accounts':clients,'movements':shown,'movement_total':total,'movement_pages':pages,'movement_page':current,'flow_totals':totals,'totals':{
        'balance_cents':sum(a['balance_cents'] or 0 for a in clients),'monthly_income_cents':monthly['income'],'monthly_expense_cents':monthly['expense'],'receivable_cents':receivable,
        'unassigned_income_cents':pending['income'],'unassigned_expense_cents':pending['expense'],'unassigned_count':pending['n']},
        'basis':'期初余额为期初日期当天开始时余额；仅累计期初日期起的已登记实际收付款。应收、折扣及抹零不作为资金收入，内部转账不计经营收支。余额为账面余额，未与银行自动核对。流水日期筛选只改变下方明细及范围合计，不改变截至统计日期的账户余额。'}
