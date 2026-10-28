"""Replace evidenced closed-month supplements without changing frozen month totals.
Only the difference reaches the actual bill's registration month; its payable
always remains the full real invoice amount.
"""
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
import json
import resources_costs as rc,expense_estimates as es

def closed(c,month):
    row=c.execute('SELECT payload FROM resource_periods WHERE month=?',(month,)).fetchone()
    value=json.loads(row[0]) if row else None
    return value if value and value.get('state')=='closed' else None

def confirmed(estimate,period,month):
    if {'id':estimate['id'],'version':estimate['version']} in period.get('confirmed_estimates',[]):return True
    if estimate.get('close_source',{}).get('month')==month and estimate['id'] in period.get('automatic_estimate_ids',[]):return True
    details=period.get('report_snapshot',{}).get('allocation',{}).get('details',[])
    original=sum(p['amount_cents'] for p in estimate['accruals'] if p['period']==month)
    return any(p.get('id')==estimate['id'] and p.get('amount_cents')==original for p in details)

def plan(c,record,exclude=''):
    physical=record.get('coverage_accruals',record['accruals']);recognition={p['period']:p['amount_cents'] for p in physical};transfers=[];posting=record.get('business_date') or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat();rc.day(posting);posting=posting[:7]
    ids=set(record.get('estimate_ids',[]));total_delta=0
    for p in physical:
        month=p['period'];period=closed(c,month)
        if not period:continue
        first=date.fromisoformat(month+'-01');days=set();start=date.fromisoformat(record['service_start'])+timedelta(days=1);end=date.fromisoformat(record['service_end'])
        for n in range((end-start).days+1):
            day=(start+timedelta(days=n)).isoformat()
            if day.startswith(month):days.add(day)
        available={};sources=[];bills=es.actuals(c,month,exclude)
        for e in es.originals(c,month):
            if e['id'] not in ids or es.key(e)!=es.key(record) or not confirmed(e,period,month):continue
            amounts=es.month_days(e,month);used={day for bill in bills if e['id'] in bill.get('estimate_ids',[]) for day in amounts if bill['service_start']<day<=bill['service_end']}
            matched=days & (set(amounts)-used)
            for day in matched:
                if day in available:raise ValueError('已结账费用的补充依据存在重叠，请先核查')
                available[day]=amounts[day]
            if matched:sources.append({'id':e['id'],'version':e['version'],'days':len(matched),'recognized_cents':sum(amounts[d] for d in matched)})
        if set(available)!=days:raise ValueError(month+'已结账，且本单未完整匹配已确认的补充区间；请核查旧单或重新打开该月')
        prior=sum(available.values());delta=p['amount_cents']-prior;total_delta+=delta;recognition[month]=prior
        transfers.append({'closed_month':month,'actual_cents':p['amount_cents'],'previous_recognized_cents':prior,'difference_cents':delta,'posting_month':posting,'sources':sources})
    if total_delta:
        if closed(c,posting):raise ValueError('本次登记月份'+posting+'已结账，无法记入跨月差额；请选择未结账登记日期')
        recognition[posting]=recognition.get(posting,0)+total_delta
    if sum(recognition.values())!=record['amount_cents']:raise ValueError('账单成本划转合计与实际金额不一致')
    return {'recognition_accruals':[{'period':month,'amount_cents':amount} for month,amount in sorted(recognition.items())],'recognition_transfers':transfers,'closed_recognition_months':[p['closed_month'] for p in transfers],'posting_month':posting,'registration_adjustment_cents':total_delta}

def apply(c,record,exclude=''):
    value=plan(c,record,exclude)
    if value['recognition_transfers']:
        record['coverage_accruals']=[dict(p) for p in record['accruals']];record.update(value);record['accruals']=value['recognition_accruals']
    return record
