"""Cent-exact expense recognition over irregular service/meter intervals.
Dates describe cost coverage; business date and the single payment source stay separate.
"""
from datetime import date,timedelta

def day(value,label):
    if not isinstance(value,str):raise ValueError(label+'无效')
    try:d=date.fromisoformat(value)
    except ValueError:raise ValueError(label+'无效')
    if d.isoformat()!=value:raise ValueError(label+'须为YYYY-MM-DD')
    return d

def plan(body,amount):
    method=body.get('accrual_method','months')
    if method not in ('months','service_days'):raise ValueError('费用归属方式无效')
    if method=='months':
        period=body.get('period') or str(body.get('business_date',''))[:7];day(period+'-01','费用起始月')
        try:
            months=int(body.get('spread_months',1))
            if str(months)!=str(body.get('spread_months',1)) or not 1<=months<=60:raise ValueError()
        except (ValueError,TypeError):raise ValueError('分摊月数须为1至60的整数')
        year=int(period[:4]);mon=int(period[5:]);base,remainder=divmod(amount,months);schedule=[]
        for n in range(months):
            y,m=divmod(year*12+mon-1+n,12);part=f'{y:04d}-{m+1:02d}';day(part+'-01','费用月份');schedule.append({'period':part,'amount_cents':base+(n<remainder)})
        return {'period':period,'spread_months':months,'accruals':schedule}
    start=day(body.get('service_start'),'上次抄表日期');end=day(body.get('service_end'),'本次抄表日期')
    if start>=end:raise ValueError('本次抄表日期须晚于上次抄表日期')
    first=start+timedelta(days=1);cursor=first;parts=[];total=(end-start).days
    while cursor<=end:
        y,m=divmod(cursor.year*12+cursor.month,12)
        following=date(y,m+1,1) if y<=9999 else None
        stop=min(end,following-timedelta(days=1)) if following else end
        parts.append({'period':f'{cursor.year:04d}-{cursor.month:02d}','start':cursor.isoformat(),'end':stop.isoformat(),'days':(stop-cursor).days+1})
        if stop==end:break
        cursor=stop+timedelta(days=1)
        if len(parts)>=60:raise ValueError('费用覆盖范围最多60个月')
    floors=[amount*p['days']//total for p in parts];remainders=[amount*p['days']%total for p in parts]
    for i in sorted(range(len(parts)),key=lambda i:(-remainders[i],i))[:amount-sum(floors)]:floors[i]+=1
    for p,value in zip(parts,floors):p['amount_cents']=value
    return {'period':parts[0]['period'],'spread_months':len(parts),'accrual_method':'service_days','service_start':start.isoformat(),'service_end':end.isoformat(),'coverage_days':total,'coverage_basis':'不含覆盖起点日，包含覆盖终点日；按各月覆盖天数分摊，余分按小数余数从大到小分配，同余优先较早月份。','coverage_breakdown':parts,'accruals':[{'period':p['period'],'amount_cents':p['amount_cents']} for p in parts]}

def preview(c,body):
    import resources_costs as rc
    value=plan(body,rc.cents(body.get('amount'),positive=True));closed=[]
    for p in value['accruals']:
        row=c.execute('SELECT payload FROM resource_periods WHERE month=?',(p['period'],)).fetchone()
        if row and __import__('json').loads(row[0]).get('state')=='closed':closed.append(p['period'])
    record={**body,**value,'amount_cents':sum(p['amount_cents'] for p in value['accruals']),'service_account':rc.text(body.get('service_account',''),'计量标识',80,False),'partner':rc.text(body.get('partner',''),'费用对象',100,False)}
    matches=__import__('expense_estimates').candidates(c,record,body.get('exclude_expense','')) if body.get('accrual_method')=='service_days' and body.get('category') and body.get('service_account') and body.get('estimate_mode')!='1' else []
    recognition={};recognition_error=''
    if body.get('accrual_method')=='service_days' and body.get('estimate_mode')!='1':
        try:recognition=__import__('expense_recognition').plan(c,{**record,'estimate_ids':[p['id'] for p in matches]},body.get('exclude_expense',''))
        except ValueError as error:recognition_error=str(error)
    allowed=set(recognition.get('closed_recognition_months',[]))
    return {**value,**recognition,'recognition_error':recognition_error,'blocked_months':[m for m in closed if m not in allowed],'estimate_candidates':matches,'estimate_offset_cents':sum(p['offset_cents'] for p in matches),'estimate_difference_cents':record['amount_cents']-sum(p['offset_cents'] for p in matches),'closed_months':closed,'amount_cents':sum(p['amount_cents'] for p in value['accruals'])}
