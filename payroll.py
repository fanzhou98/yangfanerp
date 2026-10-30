"""Monthly attendance and daily-rate payroll; explicit confirmation and payment."""
import calendar,hashlib,json,re,secrets
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal,ROUND_HALF_UP
from html import escape as h
import resources_costs as rc
import erp_access as access
import social_policy

def local_today():return datetime.now(ZoneInfo('Asia/Shanghai')).date()

LABELS={'full':'全','present':'全','half':'半','leave':'假','absent':'缺','rest':'休','draft':'待确认','missing':'未登','conflict':'冲突'}
PAYMENT_METHODS={'cash':'现金','bank_transfer':'银行转账','other':'其他','unspecified':'历史未注明'}
def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'payroll')

def records(c):return rc.rows(c,'payroll_records')
def profile_monthly(profile):
    if profile.get('monthly_cents') is not None:return int(profile['monthly_cents'])
    if profile.get('rate_cents') is not None:return int((Decimal(str(profile['rate_cents']))*365/12).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    return 300000

def daily_cents(monthly):return Decimal(monthly)*12/365

SALARY_CATEGORIES={'wages-production':'生产工资','wages-delivery':'配送工资','wages-management':'管理工资'}

def salary_snapshot(profile):
    result={'salary_mode':profile.get('salary_mode','monthly'),'monthly_cents':profile_monthly(profile),'annual_cents':profile.get('annual_cents'), 'salary_category':profile.get('salary_category','wages-production')}
    if 'social_base_cents' in profile:
        result.update({k:profile[k] for k in ('social_base_cents','social_company_rate','social_personal_rate')})
    if 'social_policy_version' in profile:result.update(social_policy_version=profile['social_policy_version'],social_policy_effective_month=profile['social_policy_effective_month'])
    return result


def social_settings(b,old):
    base=rc.cents(b['social_base'],'社保补偿款基数') if 'social_base' in b else old.get('social_base_cents',0)
    rates={}
    for key in ('social_company_rate','social_personal_rate'):
        try:value=Decimal(str(b.get(key,old.get(key,'0'))))
        except Exception as error:raise ValueError('社保补偿款比例请填写0至100之间的百分数') from error
        if not value.is_finite() or not 0<=value<=100 or value.as_tuple().exponent < -4:raise ValueError('社保补偿款比例须为0至100，最多4位小数')
        rates[key]=rc.ds(value)
    return {'social_base_cents':base,**rates}


def social_amounts(profile):
    base=profile.get('social_base_cents',0)
    amounts={key:int((Decimal(base)*Decimal(profile.get(rate,'0'))/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) for key,rate in [('social_company_cents','social_company_rate'),('social_personal_cents','social_personal_rate')]}
    return {'social_base_cents':base,'social_company_rate':profile.get('social_company_rate','0'),'social_personal_rate':profile.get('social_personal_rate','0'),**amounts}

def payroll_attendance(c,month,profiles,frozen=()):
    a=attendance(c,month,[r['employee_id'] for r in frozen]);standards={r['employee_id']:r for r in frozen} if frozen else profiles
    for e in a['rows']:
        if standards.get(e['employee_id'],{}).get('salary_mode')!='annual':continue
        # Fixed annual salary needs explicit evidence for every calendar day;
        # paid rest is recorded as rest, never inferred from missing attendance.
        for cell in e['cells']:
            if not cell['status'] and cell['date']<=local_today().isoformat():
                cell.update(status='missing',label=LABELS['missing']);e['counts']['missing']+=1
        e['unresolved']=sum(e['counts'][k] for k in ('missing','draft','conflict'))
    a['attendance_token']=hashlib.sha256(rc.dump({k:v for k,v in a.items() if k!='attendance_token'}).encode()).hexdigest()
    return a

def salary_calculation(e,profile,month):
    r=salary_snapshot(profile)
    if r['salary_mode']=='annual':
        annual=int(r['annual_cents']);year=int(month[:4]);days=366 if calendar.isleap(year) else 365
        start=date.fromisoformat(month+'-01');end=date.fromisoformat(month_days(month)[-1]);origin=date(year,1,1)
        rounded=lambda value:int(value.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        # Cumulative rounding keeps the full calendar year's accrual equal to
        # the annual standard, including leap years and fractional cents.
        entitlement=rounded(Decimal(annual)*((end-origin).days+1)/days)-rounded(Decimal(annual)*(start-origin).days/days)
        unpaid=Decimal(e['counts']['leave']+e['counts']['absent'])+Decimal(e['counts']['half'])/2
        rate=Decimal(annual)/days;base=max(0,entitlement-rounded(rate*unpaid))
        r.update(annual_days=days,unpaid_days=rc.ds(unpaid),entitlement_cents=entitlement,calculation_note='年薪按当年日历天数归属月份；休息有薪；假/缺无薪、半天扣半天。加扣项另记说明。')
    else:
        rate=daily_cents(r['monthly_cents']);base=int((Decimal(e['pay_days'])*rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        r['calculation_note']='全天＋半天×0.5，乘月工资×12÷365；休息不计薪。'
    social=social_amounts(profile)
    compensation=social['social_company_cents']+social['social_personal_cents']
    return {**r,**social,'rate_cents':rc.ds(rate),'attendance_cents':base,'monthly_basic_cents':r['monthly_cents']-compensation,'base_cents':base-compensation,'calculation_note':r['calculation_note']+' 先按原工资标准折算，再扣社保补偿款公司部分与个人部分。'}

def year_balances(allrows,year):
    result=[]
    for sheet in sorted((r for r in allrows if r['kind']=='sheet' and r['month'].startswith(year) and r['state']=='confirmed'),key=lambda r:r['month']):
        for row in sheet['rows']:
            paid=sum(r['amount_cents'] for r in allrows if r['kind']=='payment' and not r.get('voided') and r['month']==sheet['month'] and r.get('employee_id')==row['employee_id'])
            result.append({'month':sheet['month'],'employee_id':row['employee_id'],'employee_name':row['employee_name'],'net_cents':row['net_cents'],'paid_cents':paid,'outstanding_cents':row['net_cents']-paid})
    return result

def ensure_profiles(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='factory_employees'").fetchone():return
    profiles={r['employee_id']:r for r in records(c) if r['kind']=='profile'}
    for employee in table_rows(c,'factory_employees'):
        old=profiles.get(employee['id'])
        if old and old.get('monthly_cents') is not None:continue
        monthly=profile_monthly(old or {});record={**(old or {}),'id':(old or {}).get('id','WAGE-'+secrets.token_hex(8)),'kind':'profile','employee_id':employee['id'],'employee_name':employee['name'],'monthly_cents':monthly,'rate_cents':rc.ds(daily_cents(monthly)),'version':(old or {}).get('version',0)+1,'updated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'salary_category':(old or {}).get('salary_category') or ('wages-management' if employee.get('employee_type')=='management' else 'wages-production'),'basis':'monthly-12/365','defaulted':not old,**({'social_policy_mode':'inherit'} if not old else {})}
        if old:c.execute('UPDATE payroll_records SET payload=? WHERE id=?',(rc.dump(record),old['id']))
        else:c.execute('INSERT INTO payroll_records VALUES(?,?,?)',(record['id'],'monthly-default:'+employee['id'],rc.dump(record)))

def month_days(month):
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month):raise ValueError('请选择有效月份')
    try:
        date.fromisoformat(month+'-01');n=calendar.monthrange(int(month[:4]),int(month[5:]))[1]
    except ValueError:raise ValueError('请选择有效月份')
    return [f'{month}-{d:02}' for d in range(1,n+1)]
def table_rows(c,t):return [json.loads(r[0]) for r in c.execute('SELECT payload FROM '+t)]
def month_bounds(month):
    days=month_days(month);return days[0],(date.fromisoformat(days[-1])+timedelta(days=1)).isoformat()
def payload_range(c,t,lo,hi):
    """Read only the payloads whose JSON business_date falls in [lo,hi).

    The expression index on json_extract(payload,'$.business_date') covers
    factory_attendance, factory_schedules and orders, so a month costs one range
    scan instead of materialising the whole table. ORDER BY rowid is load-bearing:
    personnel.attendance_report hashes the schedule rows in this order for its
    schedule_token, so dropping the sort would change already-issued tokens.
    """
    return [json.loads(r[0]) for r in c.execute("SELECT payload FROM "+t+" WHERE json_extract(payload,'$.business_date')>=? AND json_extract(payload,'$.business_date')<? ORDER BY rowid",(lo,hi))]
def attendance(c,month,employee_ids=()):
    days=month_days(month)
    # A record without a business_date belongs to no month. The old full-table pass raised
    # KeyError while filtering, and failing loudly beats silently dropping such a record.
    if c.execute("SELECT 1 FROM factory_attendance WHERE json_extract(payload,'$.business_date') IS NULL LIMIT 1").fetchone():raise KeyError('business_date')
    lo,hi=month_bounds(month);employees=table_rows(c,'factory_employees');groups=table_rows(c,'factory_groups');recs=payload_range(c,'factory_attendance',lo,hi);today=local_today().isoformat()
    cols={t:{r[1] for r in c.execute('PRAGMA table_info('+t+')')} for t in ('factory_daily','factory_schedules','orders','warehouse_plans')}
    table_days=set()
    for t in ('factory_daily','factory_schedules','orders','warehouse_plans'):
        # Warehouse plans keep the date in a primary-key column; the other three in JSON.
        if 'business_date' in cols[t]:table_days.update(r[0] for r in c.execute('SELECT business_date FROM '+t+' WHERE business_date>=? AND business_date<?',(lo,hi)))
        else:table_days.update(r['business_date'] for r in payload_range(c,t,lo,hi) if r.get('business_date','').startswith(month))
    evidence={d for d in ({r['business_date'] for r in recs}|table_days) if d<=today};out=[];indexed={}
    # Management work dates do not create missing production attendance (or vice versa).
    kinds={e['id']:e.get('employee_type','production') for e in employees}
    recorded_days={kind:{r['business_date'] for r in recs if any(kinds.get(x['employee_id'],x.get('employee_type','production'))==kind for x in r.get('entries',[]))} for kind in ('production','management')}
    only_management=recorded_days['management']-recorded_days['production']
    # Production common days are exactly the month's table days; future dates stay in this
    # set but the per-cell loop below clears d>today, so they never become a visible status.
    common_production=table_days
    evidence_by_type={'production':(evidence-only_management)|common_production,'management':recorded_days['management']}
    for r in recs:
        for x in r.get('entries',[]):indexed.setdefault((r['business_date'],x['employee_id']),[]).append((r,x))
    for e in employees:
        cells=[];counts={k:0 for k in ['full','half','leave','absent','rest','missing','draft','conflict']};seen=False
        for d in days:
            matches=indexed.get((d,e['id']),[])
            if len(matches)>1:status='conflict';entry={}
            elif matches:
                seen=True;r,entry=matches[0];status=entry.get('status','missing');status='full' if status=='present' else status
                if entry.get('entry_state',r.get('state'))!='confirmed':status='draft'
            else:entry={};status='missing' if d in evidence_by_type[e.get('employee_type','production')] else ''
            if d>today:status=''
            if status in counts:counts[status]+=1
            cells.append({'date':d,'status':status,'label':LABELS.get(status,'—'),'group_id':entry.get('group_id',''),'group_name':entry.get('group_name',''),'note':entry.get('note','')})
        if e.get('active',True) or seen or e['id'] in employee_ids:out.append({'employee_id':e['id'],'employee_name':e['name'],'employee_type':e.get('employee_type','production'),'department':e.get('department',''),'position':e.get('position',''),'group_id':e.get('group_id',''),'group_name':e.get('group_name',''),'active':e.get('active',True),'cells':cells,'counts':counts,'pay_days':rc.ds(Decimal(counts['full'])+Decimal(counts['half'])/2),'unresolved':sum(counts[k] for k in ['missing','draft','conflict'])})
    out.sort(key=lambda e:(e['group_name'],e['employee_name'],e['employee_id']))
    result={'month':month,'days':days,'groups':groups,'rows':out,'work_dates':sorted(evidence)}
    result['attendance_token']=hashlib.sha256(rc.dump(result).encode()).hexdigest();return result

def confirmed_attendance_basis(rows,employee_ids):
    """Compare frozen payroll evidence, excluding mutable employee/group masters.

    Existing sheets already retain these cells, so old tokens need no migration.
    New employees do not change the scope of a previously confirmed payroll.
    """
    byid={r['employee_id']:r for r in rows};result=[]
    for eid in sorted(employee_ids):
        row=byid.get(eid)
        if row is None:
            result.append({'employee_id':eid,'missing':True});continue
        result.append({'employee_id':eid,'cells':[{k:cell.get(k,'') for k in ('date','status','group_id','note')} for cell in row['cells']]})
    return result

def report(c,month):
    month_days(month)
    allrows=[json.loads(r[0]) for r in c.execute("SELECT payload FROM payroll_records WHERE json_extract(payload,'$.kind')='profile' OR (json_extract(payload,'$.kind') IN ('sheet','payment') AND json_extract(payload,'$.month')>=? AND json_extract(payload,'$.month')<=?) ORDER BY rowid",(month[:4]+'-01',month[:4]+'-12'))];profiles={r['employee_id']:r for r in allrows if r['kind']=='profile'};sheet=next((r for r in allrows if r['kind']=='sheet' and r['month']==month),None)
    policy=social_policy.catalog(c);profiles={eid:social_policy.resolve(p,month,policy) for eid,p in profiles.items()}
    frozen_ids={r['employee_id'] for r in sheet['rows']} if sheet and sheet['state']=='confirmed' else set()
    a=payroll_attendance(c,month,profiles,sheet['rows'] if frozen_ids else ())
    salary_token=hashlib.sha256(rc.dump({r['employee_id']:salary_snapshot(profiles.get(r['employee_id'],{})) for r in a['rows']}).encode()).hexdigest()
    paid=sum(r['amount_cents'] for r in allrows if r['kind']=='payment' and not r.get('voided') and r['month']==month)
    banks={r[0]:json.loads(r[1]) for r in c.execute('SELECT employee_id,payload FROM employee_bank_accounts')}
    rows=json.loads(rc.dump(sheet['rows'])) if sheet else [{**r,'monthly_cents':profile_monthly(profiles.get(r['employee_id'],{})),'bonus_cents':0,'deduction_cents':0,'reason':''} for r in a['rows']]
    for r in rows:
        if not sheet:
            r.update(salary_calculation(r,profiles.get(r['employee_id'],{}),month));r['net_cents']=r['base_cents']
        r['paid_cents']=sum(p['amount_cents'] for p in allrows if p['kind']=='payment' and not p.get('voided') and p['month']==month and p.get('employee_id')==r['employee_id'])
        r['outstanding_cents']=(r['net_cents'] or 0)-r['paid_cents']
        r['payment_methods']=' / '.join(dict.fromkeys(PAYMENT_METHODS.get(p.get('method'),'历史未注明') for p in allrows if p['kind']=='payment' and not p.get('voided') and p['month']==month and p.get('employee_id')==r['employee_id']))
        payments=[p for p in allrows if p['kind']=='payment' and p['month']==month and p.get('employee_id')==r['employee_id']]
        transfers=[p for p in payments if p.get('method')=='bank_transfer']
        # Only the tail is exposed; a full card number must never reach a
        # report, print job or JSON response, even for records saved earlier.
        if transfers:
            r['bank_card']=' / '.join(dict.fromkeys(('尾号'+p['recipient']['card_tail']) if p.get('recipient',{}).get('card_tail') else ('尾号'+(p['recipient'].get('bank_card') or '')[-4:] if (p.get('recipient',{}).get('bank_card') or '')[-4:] else '历史未注明') for p in transfers))
        else:
            card=banks.get(r['employee_id'],{}).get('bank_card','')
            r['bank_card']='' if payments and all(p.get('method')=='cash' for p in payments) else ('尾号'+card[-4:] if card else '历史未注明' if payments else '')
    total=sum(r['net_cents'] or 0 for r in rows)
    attendance_changed=(confirmed_attendance_basis(sheet['rows'],frozen_ids)!=confirmed_attendance_basis(a['rows'],frozen_ids)) if frozen_ids else bool(sheet and sheet['attendance_token']!=a['attendance_token'])
    stale=bool(sheet and (attendance_changed or sheet['state']=='draft' and sheet.get('salary_token')!=salary_token))
    return {**a,'company':(sheet or {}).get('company') or __import__('company').current(c),'company_legacy':bool(sheet and not sheet.get('company')),'year_balances':year_balances(allrows,month[:4]),'salary_token':salary_token,'rows':rows,'profiles':list(profiles.values()),'sheet':sheet,'payments':[{**r,'recipient':{k:v for k,v in (r.get('recipient') or {}).items() if k!='bank_card'}} if r.get('recipient') else r for r in allrows if r['kind']=='payment' and r['month']==month],'paid_cents':paid,'total_cents':total,'outstanding_cents':total-paid,'stale':stale}

def cost_preflight(c,sheet):
    rc.open_period(c,sheet['month']+'-01')
    categories={r.get('salary_category','wages-production') for r in sheet['rows']}
    for expense in rc.period_expenses(c,sheet['month']):
        if expense['category'] in categories and (not expense.get('payroll_sheet_id') or expense.get('payroll_sheet_id')!=sheet.get('id')):
            raise ValueError('本月已有同类手工工资成本 '+expense['id']+'，请先核对并作废重复费用，再确认工资成本，避免重复计入')
    known={r['id']:r for r in __import__('cost_allocation').categories(c)}
    if any(k not in known or not known[k]['active'] and not known[k].get('retired') for k in categories):raise ValueError('工资成本项目已停用，请先启用对应成本项目')

def sync_cost(c,sheet,role,now,audit):
    """One category accrual per confirmed sheet; payment never creates expense."""
    import cost_allocation as ca
    known={r['id']:r for r in ca.categories(c)}
    existing={e['category']:e for e in rc.rows(c,'indirect_expenses') if e.get('payroll_sheet_id')==sheet['id']}
    totals={}
    for row in sheet['rows']:
        key=row.get('salary_category','wages-production');totals[key]=totals.get(key,0)+row['net_cents']
    for key in set(existing)|set(totals):
        old=existing.get(key);amount=totals.get(key,0);active=sheet['state']=='confirmed' and key in totals;scope=known[key].get('product_ids',[])
        record={**(old or {}),'id':(old or {}).get('id') or 'EX-PAYROLL-'+sheet['id']+'-'+key,'business_date':month_days(sheet['month'])[-1],'period':sheet['month'],'category':key,'amount_cents':amount,'department':SALARY_CATEGORIES[key],'product_id':scope[0] if len(scope)==1 else '','product_ids':scope, 'cost_target':'共用','partner':'厂内员工','reference':sheet['id'],'handler':role,'note':sheet['month']+'已确认工资自动计入成本；实际发放在员工工资办理，不重复登记费用。','category_snapshot':known[key],'payment_mode':'payroll','counterparty_kind':'none','allocation_rule':ca.RULE,'payroll_sheet_id':sheet['id'],'payroll_sheet_version':sheet['version'],'source':'payroll-accrual','spread_months':1,'accruals':[{'period':sheet['month'],'amount_cents':amount}],'version':(old or {}).get('version',0)+1,'created_at':(old or {}).get('created_at') or now(),'updated_at':now(),'voided':not active,'void_reason':'' if active else '工资确认撤回，同步撤销成本','role':role}
        if old:c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(rc.dump(record),record['id']))
        else:c.execute('INSERT INTO indirect_expenses VALUES(?,?,?)',(record['id'],'payroll-cost:'+sheet['id']+':'+key,rc.dump(record)))
        audit(c,role,'工资成本自动归集' if active else '工资成本同步撤回',record['id'],old,record)

def void_payment(c,b,role,now,audit):
    # 受控冲销工资发放：保留原发放记录与凭据，只标记作废并从工资表已发金额剔除。
    row=c.execute('SELECT payload FROM payroll_records WHERE id=?',(b.get('payment_id'),)).fetchone()
    if not row:raise ValueError('工资发放记录不存在，请刷新后重试')
    payment=json.loads(row[0])
    if payment.get('kind')!='payment':raise ValueError('请选择工资发放记录')
    if payment.get('voided'):raise ValueError('该笔工资发放已冲销')
    reason=rc.text(b.get('reason'),'冲销原因',500)
    rc.open_period(c,payment['business_date'])
    if b.get('version') is not None and b['version']!=payment.get('version',0):raise ValueError('发放记录已变更，请刷新后重试')
    record={**payment,'voided':True,'void_reason':reason,'voided_at':now(),'voided_by':role,'version':payment.get('version',0)+1,'updated_at':now()}
    c.execute('UPDATE payroll_records SET payload=? WHERE id=?',(rc.dump(record),payment['id']))
    audit(c,role,'冲销工资发放',payment['id'],payment,record)
    return record

def save(c,kind,b,role,now,audit):
    access.require_role(role,'payroll.pay' if kind in ('wage-pay','wage-payment-void') else 'payroll.write')
    if kind=='wage-payment-void':return void_payment(c,b,role,now,audit)
    key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump(b).encode()).hexdigest();oldreq=c.execute('SELECT payload FROM payroll_records WHERE request_key=?',(key,)).fetchone()
    if oldreq:
        r=json.loads(oldreq[0])
        if r.get('fingerprint')==finger:return r
        raise ValueError('提交编号已使用，请重新打开')
    allrows=records(c);old=None
    if kind=='wage-profile':
        eid=b.get('employee_id');e=next((r for r in table_rows(c,'factory_employees') if r['id']==eid),None)
        if not e:raise ValueError('员工不存在')
        old=next((r for r in allrows if r['kind']=='profile' and r['employee_id']==eid),None)
        mode=b.get('salary_mode','monthly');category=b.get('salary_category',(old or {}).get('salary_category','wages-production'))
        if mode not in ('monthly','annual'):raise ValueError('工资标准请选择月工资或固定年薪')
        if category not in SALARY_CATEGORIES:raise ValueError('请选择生产、配送或管理工资归属')
        known={r['id']:r for r in __import__('cost_allocation').categories(c)}
        if category not in known:raise ValueError('工资成本项目已删除，请选择生产或管理工资')
        if known[category].get('retired') and not (old and old.get('salary_category')==category):raise ValueError('配送工资已停用，仅保留原计薪配置；新员工请选择生产或管理工资')
        annual=rc.cents(b.get('annual_salary'),'年薪',True) if mode=='annual' else None
        monthly=int((Decimal(annual)/12).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if annual is not None else rc.cents(b.get('monthly_salary'),'月工资',True)
        social=social_settings(b,old or {});social_mode=b.get('social_policy_mode','override' if any(k in b for k in ('social_base','social_company_rate','social_personal_rate')) else (old or {}).get('social_policy_mode','override'))
        if social_mode not in ('inherit','override'):raise ValueError('补偿款来源请选择跟随统一标准或个人设置')
        social_from=(old or {}).get('social_policy_from_month','')
        if social_mode=='inherit' and (old or {}).get('social_policy_mode')!='inherit':
            social_from=b.get('social_policy_from_month') or b.get('month') or local_today().strftime('%Y-%m');month_days(social_from)
        effective_social=social_policy.resolve({**social,'social_policy_mode':social_mode,'social_policy_from_month':social_from},b.get('month') or local_today().strftime('%Y-%m'),social_policy.catalog(c));amounts=social_amounts(effective_social)
        if amounts['social_company_cents']+amounts['social_personal_cents']>monthly:raise ValueError('双方社保补偿款合计不能超过登记月工资，请核对基数和比例')
        r={'kind':'profile','employee_id':eid,'employee_name':e['name'],'monthly_cents':monthly,'annual_cents':annual,'salary_mode':mode,'salary_category':category,'rate_cents':rc.ds(daily_cents(monthly)),'basis':'annual-calendar' if mode=='annual' else 'monthly-12/365',**social,**({'social_policy_mode':social_mode,'social_policy_from_month':social_from} if 'social_policy_mode' in b or old and 'social_policy_mode' in old else {})}
    else:
        month=b.get('month');current=report(c,month);old=current['sheet'] if kind=='wage-sheet' else None
        if kind=='wage-sheet':
            if old and old['state']=='confirmed':raise ValueError('已确认工资表不能修改；请先撤回，已发放时不能撤回')
            if b.get('attendance_token')!=current['attendance_token']:raise ValueError('考勤已变化，请刷新核对后重算')
            if b.get('salary_token')!=current['salary_token']:raise ValueError('员工月工资已变化，请刷新后重算')
            profiles={r['employee_id']:r for r in allrows if r['kind']=='profile'};policy=social_policy.catalog(c);profiles={eid:social_policy.resolve(p,month,policy) for eid,p in profiles.items()}
            incoming=b.get('rows')
            if not isinstance(incoming,list):raise ValueError('工资明细格式无效')
            byid={x['employee_id']:x for x in incoming}
            if len(byid)!=len(incoming) or set(byid)!={x['employee_id'] for x in current['rows']}:raise ValueError('员工明细不完整，请刷新')
            calculated=[]
            for e in payroll_attendance(c,month,profiles)['rows']:
                x=byid[e['employee_id']];calculation=salary_calculation(e,profiles.get(e['employee_id'],{}),month);bonus=rc.cents(x.get('bonus','0'),'加项');deduct=rc.cents(x.get('deduction','0'),'扣项');reason=rc.text(x.get('reason',''),'工资调整说明',500,False)
                if (bonus or deduct) and not reason:raise ValueError(e['employee_name']+'加扣项需填写说明')
                base=calculation['base_cents'];net=base+bonus-deduct
                if net<0:raise ValueError(e['employee_name']+'考勤工资扣除双方社保补偿款及扣项后小于0，请核对考勤、补偿款设置和加扣项')
                calculated.append({**e,**calculation,'bonus_cents':bonus,'deduction_cents':deduct,'net_cents':net,'reason':reason})
            state=b.get('state','draft')
            if state not in ('draft','confirmed'):raise ValueError('工资状态无效')
            if state=='confirmed' and (not current['work_dates'] or not calculated or any(e['unresolved'] for e in calculated)):raise ValueError('存在未登记、未确认或冲突考勤，请核对后再确认工资')
            if state=='confirmed' and month>=local_today().strftime('%Y-%m'):raise ValueError('请在月份结束后确认整月工资；当前可保存草稿')
            r={'kind':'sheet','month':month,'company':__import__('company').current(c),'basis':'salary-attendance-v2','salary_token':current['salary_token'],'attendance_token':current['attendance_token'],'state':state,'rows':calculated}
        elif kind=='wage-cost-post':
            old=current['sheet']
            if not old or old['state']!='confirmed':raise ValueError('请先确认工资表')
            if current['stale']:raise ValueError('确认后考勤发生变化，请先核对工资表')
            r={**old,'cost_accrual_mode':'auto'}
        elif kind=='wage-reopen':
            old=current['sheet']
            if not old or old['state']!='confirmed':raise ValueError('工资表尚未确认')
            if current['paid_cents']:raise ValueError('已有工资发放记录，不能撤回修改')
            r={**old,'state':'draft'}
        else:
            if not current['sheet'] or current['sheet']['state']!='confirmed':raise ValueError('请先确认工资表')
            if current['stale']:raise ValueError('确认后考勤发生变化，请先核对工资表')
            employee=next((r for r in current['rows'] if r['employee_id']==b.get('employee_id')),None)
            if not employee:raise ValueError('请选择工资表中的员工')
            amount=rc.cents(b.get('amount'),'发放金额',True)
            if amount>employee['outstanding_cents']:raise ValueError('发放金额超过未发金额')
            if b.get('version')!=current['sheet']['version']:raise ValueError('工资表已变化，请刷新')
            if b.get('paid_cents')!=current['paid_cents']:raise ValueError('已有新发放记录，请刷新核对')
            if rc.day(b.get('business_date'))>local_today().isoformat():raise ValueError('实际发放日期不能晚于今天')
            method=b.get('method','unspecified')
            if method not in PAYMENT_METHODS:raise ValueError('请选择现金、银行转账或其他实际发放方式')
            account=rc.fund_account(c,b);snapshot={}
            if account and method in ('cash','bank_transfer'):
                account_kind=c.execute("SELECT json_extract(payload,'$.kind') FROM fund_accounts WHERE id=?",(account,)).fetchone()[0]
                if account_kind!=('现金' if method=='cash' else '银行账户'):raise ValueError('付款资金账户类型与实际发放方式不符')
            if method=='bank_transfer':
                import employee_banks
                recipient=employee_banks.bank(c,employee['employee_id'])
                if not recipient:raise ValueError('请先维护员工银行卡，再登记银行转账；现金发放无需银行卡')
                if b.get('bank_version')!=recipient['version']:raise ValueError('员工银行卡已变化，请重新打开核对')
                snapshot={'bank_version':recipient['version'],'bank_name':recipient['bank_name'],'account_name':recipient['account_name'],'card_tail':recipient['bank_card'][-4:]}
            r={'account_id':account,'kind':'payment','employee_id':employee['employee_id'],'employee_name':employee['employee_name'],'month':month,'amount_cents':amount,'business_date':rc.day(b.get('business_date')),'handler':rc.text(b.get('handler'),'经办人',60),'reference':rc.text(b.get('reference'),'发放凭据',200),'method':method,'recipient':snapshot,'company':__import__('company').current(c)}
    if old and b.get('version')!=old['version']:raise ValueError('记录已修改，请刷新核对')
    if r['kind']=='sheet' and (r['state']=='confirmed' or r.get('cost_accrual_mode')=='auto'):
        if r['state']=='confirmed':cost_preflight(c,r)
        else:rc.open_period(c,r['month']+'-01')
        r['cost_accrual_mode']='auto'
    r.update(id=old['id'] if old else 'WAGE-'+secrets.token_hex(8),version=(old or {}).get('version',0)+1,updated_at=now(),role=role,fingerprint=finger)
    if old:c.execute('UPDATE payroll_records SET request_key=?,payload=? WHERE id=?',(key,rc.dump(r),r['id']))
    else:c.execute('INSERT INTO payroll_records VALUES(?,?,?)',(r['id'],key,rc.dump(r)))
    if r['kind']=='sheet' and r.get('cost_accrual_mode')=='auto':sync_cost(c,r,role,now,audit)
    audit_value=json.loads(rc.dump(r))
    if audit_value.get('recipient',{}).get('bank_card'):audit_value['recipient']['bank_card']=__import__('employee_banks').mask(audit_value['recipient']['bank_card'])
    audit(c,role,'工资'+{'wage-cost-post':'补计成本','wage-profile':'月工资设置','wage-sheet':'核算','wage-reopen':'撤回确认','wage-pay':'发放登记'}[kind],r['id'],old,audit_value);return r

def filtered(report,group='',search='',status='',employee_type=''):
    rows=[r for r in report['rows'] if (not employee_type or r.get('employee_type','production')==employee_type) and (not group or r['group_id']==group or any(x['group_id']==group for x in r['cells'])) and (not search or search.lower() in r['employee_name'].lower()) and (not status or status=='unresolved' and r['unresolved'] or r['counts'].get(status,0))]
    groups={g['id']:i for i,g in enumerate(report.get('groups',[]))}
    return sorted(rows,key=lambda r:(groups.get(r.get('group_id'),len(groups)),r.get('group_id') or '',r['employee_name'],r['employee_id']))

PAYROLL_PRINT_COLUMNS=(('sequence','序号'),('name','姓名'),('basic','基本工资'),('social_company','社保补偿款（公司）'),('social_personal','社保补偿款（个人）'),('deduction','扣项'),('bonus','加项'),('pay_days','计薪天数'),('net','应发工资'),('paid','实发工资'),('method','发放方式'),('bank_card','银行卡号'),('signature','员工签名'),('reason','调整说明'))


def payroll_print_html(report,rows):
    """Salary projection; all selection/preview behavior comes from the shared print component."""
    columns=PAYROLL_PRINT_COLUMNS;money=lambda value:format(Decimal(value or 0)/100,'.2f');body=[]
    for n,row in enumerate(rows,1):
        values=(str(n),row['employee_name'],money(row.get('base_cents')),money(row['social_company_cents']) if 'social_company_cents' in row else '历史未列',money(row['social_personal_cents']) if 'social_personal_cents' in row else '历史未列',money(row.get('deduction_cents')),money(row.get('bonus_cents')),str(row.get('pay_days','')),money(row.get('net_cents')),money(row.get('paid_cents')),row.get('payment_methods') or '未发放',row.get('bank_card') or '—','' if row.get('paid_cents',0)>0 else '未发放',row.get('reason') or '')
        cells=''
        for (key,_),value in zip(columns,values):
            attrs=' data-print-key="'+key+'"'
            if key in ('net','paid'):attrs+=' data-print-value="'+str(row.get('net_cents' if key=='net' else 'paid_cents') or 0)+'" data-print-format="money"'
            attrs+=(' class="wage-signature-cell"' if key=='signature' else ' class="wage-adjustment-cell"' if key=='reason' else '')
            cells+='<td'+attrs+'>'+h(value)+'</td>'
        body.append('<tr data-print-row-key="'+h(row['employee_id'])+'" data-print-label="'+h(row['employee_name']+' · '+(row.get('group_name') or '未分组'))+'">'+cells+'</tr>')
    colgroup='<colgroup>'+''.join('<col class="wage-col-'+str(i)+'">' for i in range(len(columns)))+'</colgroup>'
    heads='<thead><tr>'+''.join('<th scope="col" data-print-key="'+key+'">'+h(label)+'</th>' for key,label in columns)+'</tr></thead>'
    company_name=(report.get('company') or {}).get('name') or '昌吉市洋帆豆制品厂';state='已确认' if (report.get('sheet') or {}).get('state')=='confirmed' else '草稿'
    content='<section class="print-page"><header><div class="company-name">'+h(company_name)+'</div><h1>员工工资表</h1><div class="document-meta"><span>月份：'+h(report['month'])+'</span><span><b data-print-row-count>'+str(len(rows))+'</b> 人 · '+state+'</span></div></header><table class="quantity-matrix workforce-print wage-print" data-print-title="员工工资" data-print-label-column="1" data-print-money-columns="net,paid">'+colgroup+heads+'<tbody>'+''.join(body)+'</tbody></table><footer><span>制表：____________　审核：____________</span><small>员工签名仅确认本表实发工资，未发金额不作为已签收。</small></footer></section>'
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/print.css"><title>'+h(report['month'])+'员工工资表</title><div class="print-toolbar"><button id="print-button">打印所选内容</button><span>横向 A4 · 下方预览与打印内容一致</span></div>'+content+'<script src="/print.js"></script></html>'


def print_html(report,query,wages=False):
    get=lambda k:query.get(k,[''])[0]
    rs=filtered(report,get('group'),get('search'),get('status'),get('employee_type'))
    if wages:return payroll_print_html(report,rs)
    month=report['month'];title='员工工资表' if wages else '月度考勤表'
    heads=['序号','姓名']+(['基本工资','社保补偿款（公司）','社保补偿款（个人）','扣项','加项','计薪天数','应发工资','实发工资','发放方式','银行卡号','员工签名','调整说明'] if wages else [str(int(d[-2:])) for d in report['days']]+['全','半','假','缺','休'])
    money=lambda value:format(Decimal(value or 0)/100,'.2f')
    body=[]
    for n,row in enumerate(rs,1):
        vals=[str(n),row['employee_name']]
        if wages:
            vals += [money(row.get('base_cents')),money(row['social_company_cents']) if 'social_company_cents' in row else '历史未列',money(row['social_personal_cents']) if 'social_personal_cents' in row else '历史未列',money(row.get('deduction_cents')),money(row.get('bonus_cents')),str(row.get('pay_days','')),money(row.get('net_cents')),money(row.get('paid_cents')),row.get('payment_methods') or '未发放',row.get('bank_card') or '—','' if row.get('paid_cents',0)>0 else '未发放',row.get('reason') or '']
        else:
            vals += [('√' if x['status']=='full' else x['label']) if x['status'] in ('full','half','leave','absent','rest') else '—' for x in row['cells']]+[str(row['counts'][k]) for k in ['full','half','leave','absent','rest']]
        body.append('<tr>'+''.join('<td'+(' class="wage-signature-cell"' if wages and i==len(vals)-2 else ' class="wage-adjustment-cell"' if wages and i==len(vals)-1 else '')+'>'+h(v)+'</td>' for i,v in enumerate(vals))+'</tr>')
    note='员工签名仅确认本表实发工资，未发金额不作为已签收。' if wages else '√＝全天　半＝半天　假＝请假　缺＝缺勤　休＝休息　—＝无有效确认记录。'
    columns='<colgroup>'+''.join('<col class="wage-col-'+str(i)+'">' for i in range(14))+'</colgroup>' if wages else '<colgroup><col class="seq"><col class="staff-name"></colgroup>'
    company=__import__('company').header_html(report.get('company'),report.get('company_legacy',False))
    state=' · '+('已确认' if (report.get('sheet') or {}).get('state')=='confirmed' else '草稿') if wages else ''
    content='<section class="print-page"><header>'+company+'<h1>'+title+'</h1><div class="document-meta"><span>月份：'+h(month)+'</span><span><b data-print-row-count>'+str(len(rs))+'</b> 人'+state+'</span></div></header><table class="quantity-matrix workforce-print '+('wage-print' if wages else 'attendance-print')+'">'+columns+'<thead><tr>'+''.join('<th>'+h(v)+'</th>' for v in heads)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table><footer><span>制表：____________　审核：____________</span><small>'+note+'</small></footer></section>'
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/print.css"><title>'+h(month)+h(title)+'</title><div class="print-toolbar"><button id="print-button">打印</button><span>横向 A4 · 按当前筛选打印</span></div>'+content+'<script src="/print.js"></script></html>'


def slip_html(report,employee_id,payment_id=''):
    row=next((r for r in report['rows'] if r['employee_id']==employee_id),None)
    if not row:raise ValueError('工资表中没有该员工')
    if not report['sheet'] or report['sheet']['state']!='confirmed':raise ValueError('请先确认工资表')
    if report.get('stale'):raise ValueError('考勤或工资标准已变化，请核对后打印个人工资单')
    payment=next((p for p in report['payments'] if p['id']==payment_id and p['employee_id']==employee_id),None) if payment_id else None
    if payment_id and not payment:raise ValueError('发放记录与员工不符')
    money=lambda value:format(Decimal(value or 0)/100,'.2f')
    title=('个人现金工资签收单' if payment.get('method')=='cash' else '个人工资签收单') if payment else '个人工资明细单'
    fields=[('员工姓名',row['employee_name']),('工资月份',report['month']),('工资标准',('固定年薪 '+money(row['annual_cents'])+' 元/年') if row.get('salary_mode')=='annual' else money(row.get('monthly_cents'))+' 元/月' if row.get('monthly_cents') is not None else '历史日薪标准'),('月基本工资标准',money(row['monthly_basic_cents'])+' 元' if 'monthly_basic_cents' in row else '历史未列'),('计薪天数',row['pay_days']+' 天'),('折算日工资',format(Decimal(row.get('rate_cents') or 0)/100,'.6f')+' 元/天'),('考勤工资（扣补偿款前）',money(row.get('attendance_cents',row['base_cents']))+' 元'),('社保补偿款基数',money(row['social_base_cents'])+' 元' if 'social_base_cents' in row else '历史未列'),('社保补偿款 · 公司',money(row['social_company_cents'])+' 元（'+str(row.get('social_company_rate','0'))+'%）' if 'social_company_cents' in row else '历史未列'),('社保补偿款 · 个人',money(row['social_personal_cents'])+' 元（'+str(row.get('social_personal_rate','0'))+'%）' if 'social_personal_cents' in row else '历史未列'),('基本工资',money(row['base_cents'])+' 元'),('加项',money(row['bonus_cents'])+' 元'),('扣项',money(row['deduction_cents'])+' 元'),('应发工资',money(row['net_cents'])+' 元'),('累计实发金额',money(row['paid_cents'])+' 元'),('尚未发放',money(row['outstanding_cents'])+' 元'),('计算规则',row.get('calculation_note') or '日工资＝月工资×12÷365'),('无薪扣减天数',row.get('unpaid_days','按月薪出勤核算')),('调整说明',row.get('reason') or '无')]
    if payment:fields += [('本次发放日期',payment['business_date']),('本次实发金额',money(payment['amount_cents'])+' 元'),('实际发放方式',PAYMENT_METHODS.get(payment.get('method'),'历史未注明')),('发放凭据',payment['reference'])]
    if payment and payment.get('recipient'):fields += [('收款银行卡',(payment['recipient'].get('bank_name') or '开户银行未填写')+' · '+payment['recipient']['account_name']+' · 尾号'+payment['recipient']['card_tail'])]
    body=''.join('<tr><th>'+h(k)+'</th><td>'+h(v)+'</td></tr>' for k,v in fields)
    note='本人确认收到本单所列本次实发金额。' if payment else '本单仅用于本人薪资核对，实际发放以发放记录为准。'
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/print.css"><title>'+h(title)+'</title><div class="print-toolbar"><button id="print-button">打印</button><span>每次只打印一位员工；请勿向员工出示汇总工资表。</span></div><section class="print-page personal-wage-slip"><header>'+__import__('company').header_html((payment or {}).get('company') or report.get('company'),bool(payment and not payment.get('company') or not payment and report.get('company_legacy'))) +'<h1>'+h(title)+'</h1></header><table class="quantity-matrix">'+body+'</table><p>'+h(note)+'</p><footer><span>员工签字：________________　签字日期：________________</span><small>月薪按月工资×12÷365折日薪；年薪按当年365/366天归属月份，扣除假、缺及半天差额。金额按分四舍五入。</small></footer></section><script src="/print.js"></script></html>'
