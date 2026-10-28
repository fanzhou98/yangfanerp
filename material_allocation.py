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
