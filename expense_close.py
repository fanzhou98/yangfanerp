"""Per-item monthly coverage review and automatic unbilled-tail cost completion."""
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
import calendar,json,hashlib
import resources_costs as rc,expense_estimates as es,cost_allocation as ca,expense_coverage as coverage

def intervals(days):
    result=[]
    for day in sorted(days):
        if result and date.fromisoformat(result[-1]['end'])+timedelta(days=1)==date.fromisoformat(day):result[-1]['end']=day;result[-1]['days']+=1
        else:result.append({'start':day,'end':day,'days':1})
    return result

def physical_days(b,month):
    start=date.fromisoformat(b['service_start'])+timedelta(days=1);end=date.fromisoformat(b['service_end']);first=date.fromisoformat(month+'-01');last=first.replace(day=calendar.monthrange(first.year,first.month)[1]);start=max(start,first);end=min(end,last)
    return {(start+timedelta(days=i)).isoformat() for i in range(max(0,(end-start).days+1))}

def stream_id(key):return hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:24]
def fingerprint(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def preview(c,month,exclusions=()):
    first=coverage.day(month+'-01','成本月份');last=first.replace(day=calendar.monthrange(first.year,first.month)[1]);all_days={(first+timedelta(days=i)).isoformat() for i in range(last.day)}
    categories=ca.categories(c);enabled={p['id']:p for p in categories if p.get('irregular_periodic') and p.get('active') and p.get('manual_entry') and p['payment_mode']=='payable'}
    ids=rc.dump(sorted(enabled));bills=[json.loads(r[0]) for r in c.execute("SELECT payload FROM indirect_expenses WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 AND json_extract(payload,'$.accrual_method')='service_days' AND json_extract(payload,'$.category') IN (SELECT value FROM json_each(?)) AND json_extract(payload,'$.service_start')<? ORDER BY json_extract(payload,'$.service_end'),id",(ids,last.isoformat()))]
    pending_sources=es.originals(c,month);streams={}
    for b in bills:
        key=es.key(b);streams.setdefault(key,{'bills':[],'estimates':[]})['bills'].append(b)
    for e in pending_sources:
        if e['category'] in enabled:streams.setdefault(es.key(e),{'bills':[],'estimates':[]})['estimates'].append(e)
    recognized=rc.period_expenses(c,month)
    for category in enabled:
        if not any(k[0]==category for k in streams) and not any(e['category']==category and not e.get('is_estimate') and e.get('accrual_method')!='service_days' for e in recognized):streams[(category,'','')]={'bills':[],'estimates':[]}
    if not isinstance(exclusions,(list,tuple)) or any(not isinstance(v,dict) for v in exclusions):raise ValueError('本月不适用项目格式无效')
    excluded={}
    for v in exclusions:
        sid=rc.text(v.get('stream_id'),'费用来源标识',80);reason=rc.text(v.get('reason'),'本月不适用说明',300)
        if sid in excluded:raise ValueError('本月不适用项目不能重复')
        excluded[sid]=reason
    rows=[];sources=[];used=set()
    for key,group in sorted(streams.items()):
        category=enabled[key[0]];sid=stream_id(key);used.add(sid);actual_days=set();existing_days=set();actual_amount=0;overlap=False;current_bills=[]
        for b in group['bills']:
            days=physical_days(b,month)
            if not days:continue
            if actual_days&days:overlap=True
            actual_days|=days;current_bills.append(b)
            physical=b.get('coverage_accruals',b['accruals']);actual_amount+=sum(p['amount_cents'] for p in physical if p['period']==month)
        monthly_bills=es.actuals(c,month)
        for e in group['estimates']:
            covered=set(es.month_days(e,month));consumed={d for b in monthly_bills if e['id'] in b.get('estimate_ids',[]) for d in covered if b['service_start']<d<=b['service_end']}
            existing_days|=covered-consumed
        missing=all_days-actual_days-existing_days;parts=intervals(missing);prototype=group['bills'][-1] if group['bills'] else group['estimates'][-1] if group['estimates'] else None
        mean_source='month_actual' if actual_days else 'latest_invoice';numerator=actual_amount;denominator=len(actual_days);source_bills=current_bills
        if not denominator:
            old=[b for b in group['bills'] if b['service_end']<first.isoformat()]
            if old:
                latest=max(old,key=lambda b:(b['service_end'],b.get('business_date',''),b['id']));numerator=latest['amount_cents'];denominator=(date.fromisoformat(latest['service_end'])-date.fromisoformat(latest['service_start'])).days;source_bills=[latest];prototype=latest
            else:mean_source='missing';numerator=0
        error='实际费用覆盖区间存在重叠，请先核查原账单' if overlap else '缺少可计算日均的实际账单，请先登记详细日期或说明本月不适用' if missing and not denominator else ''
        if prototype and prototype.get('counterparty_id'):
            party=next((p for p in __import__('expense_parties').catalog(c) if p['id']==prototype['counterparty_id']),None)
            if missing and (not party or not party.get('active')):error='费用收款方已停用，请先核查或说明本月不适用'
        total=int((Decimal(numerator)*len(missing)/denominator).quantize(Decimal(1),rounding=ROUND_HALF_UP)) if denominator else 0
        floors=[total*p['days']//len(missing) for p in parts] if missing else [];remainder=[total*p['days']%len(missing) for p in parts] if missing else []
        for i in sorted(range(len(parts)),key=lambda i:(-remainder[i],i))[:total-sum(floors)]:floors[i]+=1
        for p,value in zip(parts,floors):p['amount_cents']=value
        row={'stream_id':sid,'category':key[0],'category_name':category['name'],'service_account':key[1],'partner':(prototype or {}).get('partner','未建立费用来源'),'product_ids':(prototype or {}).get('product_ids',category.get('product_ids',[])),'actual_intervals':intervals(actual_days),'existing_intervals':intervals(existing_days),'gap_intervals':parts,'actual_days':len(actual_days),'gap_days':len(missing),'mean_source':mean_source,'current_interval_cents':actual_amount,'mean_numerator_cents':numerator,'mean_denominator_days':denominator,'mean_daily_cents':format(Decimal(numerator)/denominator,'.6f') if denominator else None,'source_bills':[{'id':b['id'],'version':b['version'],'service_start':b['service_start'],'service_end':b['service_end'],'amount_cents':b['amount_cents']} for b in source_bills],'supplement_cents':0 if sid in excluded else total,'excluded_reason':excluded.get(sid,''),'error':error if overlap else '' if sid in excluded else error,'hard_error':overlap,'_prototype':prototype,'irregular_periodic':True}
        row['recognized_cents']=sum(e['amount_cents'] for e in recognized if es.key(e)==key)
        rows.append(row);sources.append({'key':key,'bills':group['bills'],'estimates':group['estimates']})
    # Legacy monthly bills cannot be silently treated as metered daily evidence.
    for e in recognized:
        if e['category'] in enabled and not e.get('is_estimate') and e.get('accrual_method')!='service_days':
            sid=stream_id((e['category'],'legacy-monthly',e['id']));used.add(sid)
            rows.append({'stream_id':sid,'category':e['category'],'category_name':enabled[e['category']]['name'],'service_account':'原按月记录','partner':e.get('partner',''),'actual_intervals':[],'existing_intervals':[],'gap_intervals':[],'actual_days':0,'gap_days':0,'source_bills':[{'id':e['id'],'version':e['version']}],'mean_source':'legacy','mean_daily_cents':None,'mean_numerator_cents':0,'mean_denominator_days':0,'recognized_cents':e['amount_cents'],'supplement_cents':0,'excluded_reason':excluded.get(sid,''),'error':'' if sid in excluded else '本月有旧按月费用，核算区间不明确；请核查原单或注明本月不自动补充','irregular_periodic':True,'_prototype':None})
    if set(excluded)-used:raise ValueError('本月不适用项目已变化，请刷新后核对')
    # Non-irregular items stay in the same per-item cost table.
    other={}
    for e in recognized:
        if e['category'] in enabled:continue
        r=other.setdefault(e['category'],{'category':e['category'],'category_name':e.get('category_snapshot',{}).get('name',e['category']),'irregular_periodic':False,'recognized_cents':0,'supplement_cents':0,'actual_intervals':[],'existing_intervals':[],'gap_intervals':[],'error':''})
        r['recognized_cents']+=e['amount_cents']
    result={'month':month,'rows':rows+list(other.values()),'recognized_cents':sum(e['amount_cents'] for e in recognized),'supplement_cents':sum(r['supplement_cents'] for r in rows),'errors':[r['category_name']+' / '+r.get('service_account','')+'：'+r['error'] for r in rows if r['error']]}
    result['total_cents']=result['recognized_cents']+result['supplement_cents'];result['fingerprint']=fingerprint({'month':month,'recognized':recognized,'categories':categories,'sources':sources})
    return result

def public(value):return {**value,'rows':[{k:v for k,v in r.items() if not k.startswith('_')} for r in value['rows']]}

def apply(c,b,role,now,audit):
    value=preview(c,b['month'],b.get('exclude_streams',[]))
    irregular=any(r.get('irregular_periodic') for r in value['rows'])
    if irregular and b.get('close_fingerprint')!=value['fingerprint']:raise ValueError('费用来源或属性已变化，请重新查看月结核算区间后确认')
    if value['errors']:raise ValueError('；'.join(value['errors'][:3]))
    ids=[]
    for row in value['rows']:
        if not row.get('irregular_periodic') or row.get('excluded_reason'):continue
        source=row['_prototype']
        for part in row['gap_intervals']:
            request='CLOSE-'+fingerprint({'month':b['month'],'fingerprint':value['fingerprint'],'stream':row['stream_id'],'start':part['start'],'end':part['end']})
            body={'request_key':request,'business_date':b['month']+'-'+str(calendar.monthrange(int(b['month'][:4]),int(b['month'][5:]))[1]),'accrual_method':'service_days','service_start':(date.fromisoformat(part['start'])-timedelta(days=1)).isoformat(),'service_end':part['end'],'service_account':row['service_account'],'category':row['category'],'amount':format(Decimal(part['amount_cents'])/100,'.2f'),'department':source.get('department','共用'),'product_ids':row['product_ids'],'partner':source.get('partner',''),'supplier_id':source.get('supplier_id',''),'counterparty_id':source.get('counterparty_id',''),'handler':role,'note':'月结按已登记日均补充；'+('本月实际费用' if row['mean_source']=='month_actual' else '沿用最近一期实际账单'),'close_source':{'month':b['month'],'stream_id':row['stream_id'],'mean_source':row['mean_source'],'mean_numerator_cents':row['mean_numerator_cents'],'mean_denominator_days':row['mean_denominator_days'],'source_bills':row['source_bills'],'fingerprint':value['fingerprint']}}
            e=es.save(c,body,role,now,audit,_closing=True);ids.append(e['id'])
    confirmed=[{'id':e['id'],'version':e['version']} for e in es.originals(c,b['month']) if es.project(e,b['month'],es.actuals(c,b['month']))['remaining_days']]
    return {'review':public(value),'estimate_ids':ids,'confirmed_estimates':confirmed}
