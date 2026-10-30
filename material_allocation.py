"""Daily FIFO soybean pools allocated by actual slurry source, in integer cents."""
from decimal import Decimal, ROUND_FLOOR
import resources_costs as rc
import production_daily as daily
import production_config as pc


def split(total,weights):
    """Largest remainder, stable product order; preserve every cent / .001 kg."""
    denominator=sum(weights.values(),Decimal(0))
    if denominator<=0:return {}
    raw={k:Decimal(total)*v/denominator for k,v in sorted(weights.items()) if v>0}
    result={k:int(v.to_integral_value(rounding=ROUND_FLOOR)) for k,v in raw.items()}
    for k in sorted(raw,key=lambda k:(-(raw[k]-result[k]),k))[:total-sum(result.values())]:result[k]+=1
    return result

def day_report(c,day,record=None,entries=None):
    rc.day(day)
    if record is None:record=next((r for r in rc.rows(c,'factory_daily') if r['business_date']==day),None)
    if entries is None:_,entries=rc.material_ledger(c,day)
    products={p['id']:dict(p) for p in c.execute('SELECT id,name FROM products')}
    config=pc.get(c,day,record)
    cfg=(record or {}).get('settings_snapshot',{});registrations=(record or {}).get('products',[])
    pools=[];allocations=[]
    for item in pc.active_systems(config):
        key=item['id'];label=item['name'];residual=item['allocation_mode']=='residual';skin=item.get('residual_product_id')
        es=[e for e in entries if not e.get('voided') and e['business_date']==day and e['material_id']=='RM-SOY' and pc.source(e)==key and e['kind'] in ('consume','return')]
        issued=sum((Decimal(e['qty'])*(1 if e['kind']=='consume' else -1) for e in es),Decimal(0))
        cost=sum(e.get('cost_cents',0)*(1 if e['kind']=='consume' else -1) for e in es)
        weights={};reasons=[];rs=[r for r in registrations if r.get('system')==key]
        if issued<0 or cost<0:reasons.append('退料超过当天领用，请核对上豆与退料流水')
        if issued==0 and cost!=0:reasons.append('实际领豆为0但领退成本未冲平，请由会计核对退料计价')
        if es and not record:reasons.append('缺少当天供浆登记，请由厂长补录')
        for r in rs:
            pid=r['product_id']
            if residual and pid==skin:continue # own skin has no vats; receives residual
            if pid not in products:reasons.append('产品档案缺失，请核对供浆登记');continue
            weight=pc.bean_basis(r,config)
            if weight is None:reasons.append(products[pid]['name']+'浆缸数未填或用豆参数缺失，请补齐换算参数或填写0');continue
            weights[pid]=weights.get(pid,Decimal(0))+weight
        if residual and record:
            transferred=sum(weights.values(),Decimal(0))
            if transferred>issued:reasons.append('转出浆折豆量超过'+label+'实际领豆量，请核对缸数或上豆量')
            elif issued>0:
                if skin:weights[skin]=issued-transferred
                else:reasons.append('缺少余量产品档案，无法归集剩余用豆')
        base=sum(weights.values(),Decimal(0))
        if base>0 and issued<=0:reasons.append('已有用浆但缺少实际领豆量，请由厂长或库管核对')
        if issued>0 and base<=0:reasons.append('缺少有效产品浆缸数，请由厂长补录')
        if any(Decimal(e.get('uncosted_out_qty') or '0')>0 for e in es):reasons.append('领豆成本未完整计价，请由会计核对入库金额')
        affected={r['product_id'] for r in rs if any(n in ('',None) or Decimal(n or '0')>0 for n in pc.tank_counts(r).values())}
        if residual and skin:affected.add(skin)
        if not record:affected.update(pid for pid,p in products.items() if daily.uses_slurry(daily.main_material(c,p)))
        reasons=list(dict.fromkeys(reasons));valid=not reasons and issued>0 and base>0
        pool={'business_date':day,'system':key,'system_name':label,'issued_kg':rc.ds(issued),'cost_cents':cost,'status':'待核对' if reasons else '已分摊' if valid else '无领用','reasons':reasons,'affected_product_ids':sorted(affected),'unallocated_cents':cost if not valid else 0,'basis_kg':rc.ds(base)}
        pools.append(pool)
        if valid:
            money=split(cost,weights);kilos=split(int(issued*1000),weights)
            for pid in money:
                allocations.append({'business_date':day,'system':key,'system_name':label,'product_id':pid,'product_name':products[pid]['name'],'basis_kg':rc.ds(weights[pid]),'allocated_kg':rc.ds(Decimal(kilos[pid])/1000),'cost_cents':money[pid],'basis':'实际领豆扣除转出折豆量后的余量' if residual and pid==skin else '实际来源浆缸数折豆占比'})
    return {'business_date':day,'pools':pools,'allocations':allocations}

def _day_bean(allocation):
    result={}
    for a in allocation.get('allocations',[]):
        day=a['business_date'];result.setdefault(day,{})
        result[day][a['product_id']]=result[day].get(a['product_id'],Decimal(0))+Decimal(a['allocated_kg'])
    return result

def scope_allocations(c,month,entries=None,day_bean=None):
    """Issues naming several 承担产品: split by actual vat bean usage over the
    coverage window (same month). Returns {entry_id: detail}."""
    from datetime import date as _date, timedelta
    if entries is None:
        _,ledger=rc.material_ledger(c)
        entries=[e for e in ledger if not e.get('voided') and e['business_date'].startswith(month) and e['kind'] in ('consume','return','loss')]
    if day_bean is None:day_bean=_day_bean(month_report(c,month))
    result={}
    for e in entries:
        pids=list(e.get('product_ids') or [])
        if e['material_id']=='RM-SOY' or len(pids)<2:continue
        start=e.get('coverage_start') or e['business_date'];end=e.get('coverage_end') or e['business_date']
        try:first,last=_date.fromisoformat(start),_date.fromisoformat(end)
        except ValueError:first=last=_date.fromisoformat(e['business_date'])
        if last<first:first,last=last,first
        days=[];d=first
        while d<=last and len(days)<62:days.append(d.isoformat());d+=timedelta(days=1)
        weights={pid:sum((day_bean.get(day,{}).get(pid,Decimal(0)) for day in days),Decimal(0)) for pid in pids}
        basis='coverage-bean'
        if sum(weights.values(),Decimal(0))<=0:
            weights={pid:Decimal(1) for pid in pids};basis='coverage-equal'
        value=int(e.get('cost_cents') or 0)*(-1 if e['kind']=='return' else 1)
        result[e['id']]={'entry_id':e['id'],'material_id':e['material_id'],'material_name':e.get('material_name'),'business_date':e['business_date'],'coverage_start':start,'coverage_end':end,'days':len(days),'amount_cents':value,'product_ids':pids,'basis':basis,'allocations':split(value,weights)}
    return result

def issue_report(c,month):
    """Issue ledger and product attribution for the 原辅料领用 page."""
    rc.day(month+'-01')
    _,ledger=rc.material_ledger(c)
    amortized_ids={row['entry_id'] for row in rc.amortizations(c)}
    entries=[e for e in ledger if not e.get('voided') and e['business_date'].startswith(month) and e['material_id']!='RM-SOY' and e['kind'] in ('consume','return','loss') and e['id'] not in amortized_ids]
    day_bean=_day_bean(month_report(c,month))
    scoped=scope_allocations(c,month,entries,day_bean)
    products={p['id']:p['name'] for p in c.execute('SELECT id,name FROM products')}
    rows=[];totals={}
    for e in entries:
        value=int(e.get('cost_cents') or 0)*(-1 if e['kind']=='return' else 1)
        detail=scoped.get(e['id'])
        if not detail:
            pids=list(e.get('product_ids') or [])
            if len(pids)==1 and e.get('product_id'):
                detail={'entry_id':e['id'],'material_id':e['material_id'],'material_name':e.get('material_name'),'business_date':e['business_date'],'coverage_start':e.get('coverage_start') or e['business_date'],'coverage_end':e.get('coverage_end') or e['business_date'],'days':1,'amount_cents':value,'product_ids':pids,'basis':'direct','allocations':{pids[0]:value}}
            elif not pids:
                detail={'entry_id':e['id'],'material_id':e['material_id'],'material_name':e.get('material_name'),'business_date':e['business_date'],'coverage_start':e.get('coverage_start') or e['business_date'],'coverage_end':e.get('coverage_end') or e['business_date'],'days':1,'amount_cents':value,'product_ids':[],'basis':'unallocated','allocations':{}}
        if not detail:continue
        detail['product_rows']=[{'product_id':pid,'product_name':products.get(pid,pid),'amount_cents':cents} for pid,cents in detail['allocations'].items()]
        for pid,cents in detail['allocations'].items():totals[pid]=totals.get(pid,0)+cents
        rows.append(detail)
    amortizations=amortized_shares(c,month)
    for item in amortizations:
        for pid,value in item['allocations'].items():totals[pid]=totals.get(pid,0)+value
    total=sum(r['amount_cents'] for r in rows)+sum(item['month_cents'] for item in amortizations);allocated=sum(totals.values())
    return {'month':month,'entries':rows,'products':[{'product_id':pid,'product_name':products.get(pid,pid),'amount_cents':value} for pid,value in sorted(totals.items())],'total_cents':total,'allocated_cents':allocated,'unallocated_cents':total-allocated,'amortizations':amortizations,'amortization_cents':sum(item['month_cents'] for item in amortizations),'amortization_remaining_cents':sum(item['remaining_cents'] for item in amortizations),'basis':'领用登记多个承担产品时，按覆盖期内各产品实际供浆用豆量分摊；仅一个承担产品时直接归属；未登记承担产品的领用保留待分摊；登记了摊销月数的耗材按月份分期计入产品成本。'}

def month_report(c,month):
    rc.day(month+'-01')
    _,entries=rc.material_ledger(c)
    records={r['business_date']:r for r in rc.rows(c,'factory_daily') if r['business_date'].startswith(month)}
    days=sorted(set(records)|{e['business_date'] for e in entries if not e.get('voided') and e['business_date'].startswith(month) and e['material_id']=='RM-SOY' and e['kind'] in ('consume','return')})
    pools=[];allocations=[]
    for day in days:
        value=day_report(c,day,records.get(day),entries);pools+=value['pools'];allocations+=value['allocations']
    outside=[e for e in entries if not e.get('voided') and e['business_date'].startswith(month) and e['material_id']=='RM-SOY' and e['kind'] in ('consume','return') and pc.source(e) not in {s['id'] for s in pc.active_systems(pc.get(c,e['business_date'],records.get(e['business_date'])))}]
    for e in outside:pools.append({'business_date':e['business_date'],'system':'unknown','system_name':e.get('warehouse_name') or '历史待确认库','issued_kg':e['qty'],'cost_cents':e.get('cost_cents',0)*(1 if e['kind']=='consume' else -1),'status':'待核对','reasons':['历史领用库房无法对应磨浆系统，请核对原始流水'],'unallocated_cents':e.get('cost_cents',0)*(1 if e['kind']=='consume' else -1),'basis_kg':'0'})
    return {'month':month,'pools':pools,'allocations':allocations,'total_cents':sum(p['cost_cents'] for p in pools),'allocated_cents':sum(a['cost_cents'] for a in allocations),'unallocated_cents':sum(p['unallocated_cents'] for p in pools)}


def month_index(value):
    year,month=str(value)[:7].split('-');return int(year)*12+int(month)-1

def amortization_state(row,amount,month=None):
    """Monthly recognition: base share, remainder and any early-close balance land in the closing month."""
    months=int(row['months']);start=row['start_month'];closed=row.get('closed_month') or ''
    start_i=month_index(start);closed_i=month_index(closed) if closed else start_i+months-1
    base=amount//months
    def share(index):
        if index<start_i or index>start_i+months-1 or index>closed_i:return 0
        if index==closed_i:return amount-base*(closed_i-start_i)
        return base
    upto=month_index(month) if month else closed_i
    recognized=sum(share(index) for index in range(start_i,upto+1))
    return {'monthly_cents':base,'recognized_cents':recognized,'remaining_cents':amount-recognized,'month_cents':share(month_index(month)) if month else 0,'status':'closed' if closed and month_index(month)>=closed_i else 'active'}

def month_bean(allocation):
    result={}
    for item in allocation.get('allocations',[]):
        pid=item['product_id'];result[pid]=result.get(pid,Decimal(0))+Decimal(str(item.get('basis_kg') or 0))
    return result

def amortized_shares(c,month):
    """Recognize this month's share of long-life consumables and split it over their products."""
    allocation=month_report(c,month);bean=month_bean(allocation)
    known={row[0] for row in c.execute('SELECT id FROM products')}
    entries={entry['id']:entry for entry in rc.material_ledger(c)[1]}
    result=[]
    for row in rc.amortizations(c):
        entry=entries.get(row['entry_id'])
        if not entry or entry.get('voided'):continue
        amount=int(entry.get('cost_cents') or 0)
        state=amortization_state(row,amount,month)
        share=state['month_cents']
        if not share:continue
        pids=[pid for pid in (row.get('product_ids') or []) if pid in known]
        weights={pid:bean.get(pid,Decimal(0)) for pid in pids}
        basis='amortization-bean'
        if sum(weights.values(),Decimal(0))<=0:
            weights={pid:Decimal(1) for pid in pids};basis='amortization-equal'
        result.append({'entry_id':row['entry_id'],'material_id':row.get('material_id',''),'material_name':row.get('material_name',''),'business_date':entry['business_date'],'months':int(row['months']),'start_month':row['start_month'],'closed_month':row.get('closed_month'),'amount_cents':amount,'month_cents':share,'recognized_cents':state['recognized_cents'],'remaining_cents':state['remaining_cents'],'product_ids':pids,'basis':basis,'allocations':split(share,weights) if weights else {}})
    return result
