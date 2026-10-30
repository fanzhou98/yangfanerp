"""Finished-goods cost carry-over for self-produced products (management basis).

Opening/ending quantities come from warehouse plans, production cost from the
monthly material/expense allocations. Purchased finished goods are valued by
finished_goods.stock_cost instead and are reported as a gap here.
"""
import calendar
from decimal import Decimal, ROUND_HALF_UP
import resources_costs as rc
import finished_goods as fg
import material_allocation as ma
import product_profit as pp
import transport_closure as tc

PERMISSIONS={'finished-cost':('reports.view',)}
BASIS='管理口径：期初＋本月生产－本月发出－损耗＝期末；单位成本按加权平均（期初金额＋本月生产成本）/（期初数量＋本月生产数量），发出与外购成品不计入库存成本。'


def _q(value):
    return Decimal(str(value or 0))


def _ds(value):
    return '' if value is None else rc.ds(Decimal(value))


def _plan_stock(payload, pid):
    for row in payload.get('stock') or []:
        if row.get('product_id')==pid: return row
    return {}


def costs(c, year_month):
    """Production cost per self-produced product for the month."""
    allocation=ma.month_report(c, year_month)
    soy={}
    for row in allocation['allocations']:
        pid=row['product_id']
        soy[pid]=soy.get(pid,0)+int(row['cost_cents'])
    report=pp.month(c, year_month)
    extra={}
    for row in report.get('rows') or []:
        pid=row['product_id']
        extra[pid]={'material_cents':int(row.get('direct_material_cents') or 0)+int(row.get('scope_material_cents') or 0)+int(row.get('amortized_cents') or 0),'indirect_cents':int(row.get('indirect_cents') or 0)}
    costs={}
    for pid, value in soy.items():
        if fg.is_purchased(c,pid): continue
        detail=extra.get(pid,{})
        costs[pid]=value+detail.get('material_cents',0)+detail.get('indirect_cents',0)
    return costs, allocation, report


def carry(opening_qty, opening_cents, produced_qty, produced_cents, issued_qty, loss_qty):
    """Weighted-average carry; opening_cents None means the opening was never valued."""
    opening_qty=_q(opening_qty); produced_qty=_q(produced_qty); issued_qty=_q(issued_qty); loss_qty=_q(loss_qty)
    total_qty=opening_qty+produced_qty
    known=opening_cents is not None or not opening_qty
    unit=None if not total_qty or not known else int((Decimal(opening_cents or 0)+Decimal(produced_cents or 0))/total_qty)
    ending_qty=total_qty-issued_qty-loss_qty
    total_cents=int(opening_cents or 0)+int(produced_cents or 0)
    issued=None if unit is None else int(issued_qty*unit)
    loss=None if unit is None else int(loss_qty*unit)
    ending=total_cents-issued-loss if unit is not None else None
    return {'opening_qty':_ds(opening_qty),'opening_cents':opening_cents,'produced_qty':_ds(produced_qty),'produced_cents':produced_cents,
            'issued_qty':_ds(issued_qty),'issued_cents':issued,'loss_qty':_ds(loss_qty),'loss_cents':loss,
            'ending_qty':_ds(ending_qty),'ending_cents':ending,'unit_cost':unit,'total_qty':_ds(total_qty)}


def _months(c):
    return sorted({row['business_date'][:7] for row in rc.rows(c,'warehouse_plans')})


def _issued(c, year_month, products):
    start=year_month+'-01'; end=year_month+'-'+str(calendar.monthrange(int(year_month[:4]),int(year_month[5:7]))[1])
    kg={}
    for order in rc.rows(c,'orders'):
        if order.get('state')!='reviewed' or not start<=order['business_date']<=end: continue
        for line in order.get('lines') or []:
            pid=line['product_id']
            if line.get('actual_qty') in ('',None): continue
            kg[pid]=kg.get(pid,Decimal(0))+Decimal(str(line['actual_qty']))
    for row in rc.rows(c,'sales_returns'):
        if row.get('voided') or not start<=row['business_date']<=end: continue
        for disposal in row.get('disposals') or []:
            if disposal.get('voided') or disposal.get('kind')!='restock': continue
            if not start<=disposal['business_date']<=end: continue
            pid=row['product_id'];kg[pid]=kg.get(pid,Decimal(0))-Decimal(str(disposal.get('stock_qty') or 0))
    return kg


def month(c, year_month):
    rc.day(year_month+'-01')
    y,m=int(year_month[:4]),int(year_month[5:7])
    end=year_month+'-%02d'%calendar.monthrange(y,m)[1]
    products={p['id']:dict(p) for p in c.execute('SELECT * FROM products')}
    plans=sorted([row for row in rc.rows(c,'warehouse_plans') if year_month+'-01'<=row['business_date']<=end],key=lambda row:row['business_date'])
    production, allocation, report = costs(c, year_month)
    issued=_issued(c, year_month, products)
    earlier=[p for p in _months(c) if p<year_month]
    previous_month=earlier[-1] if plans and earlier else None
    rows=[];gaps=[]
    pids=sorted({pid for pid in production if not fg.is_purchased(c,pid)}|{pid for pid in issued}|{row.get('product_id') for plan in plans for row in (plan.get('payload') or plan).get('stock') or [] if not fg.is_purchased(c,row.get('product_id') or '')})
    for pid in pids:
        product=products.get(pid) or {}
        first=_plan_stock(plans[0].get('payload') or plans[0], pid) if plans else {}
        opening_qty=first.get('existing_qty') or 0
        produced_qty=sum((_q(_plan_stock(row.get('payload') or row,pid).get('produced_qty')) for row in plans),Decimal(0))
        loss_qty=sum((_q(_plan_stock(row.get('payload') or row,pid).get('loss_qty')) for row in plans),Decimal(0))
        opening_cents=None
        if previous_month:
            prior=month(c, previous_month)
            found=next((row for row in prior['rows'] if row['product_id']==pid),None)
            opening_cents=found['ending_cents'] if found else None
        produced_cents=production.get(pid,0) if produced_qty!=0 else 0
        row=carry(opening_qty, opening_cents, produced_qty, produced_cents, issued.get(pid,Decimal(0)), loss_qty)
        row.update({'product_id':pid,'product_name':product.get('name') or pid,'unit':product.get('unit') or '','opening_source':'上月结转' if previous_month else '最早月份无期初金额'})
        if row['opening_cents'] is None and opening_qty: gaps.append('%s 期初库存无金额（%s之前没有可结转的期末金额）'%(row['product_name'],year_month))
        if produced_qty==0 and produced_cents==0: gaps.append('%s 本月没有生产数量，期末数量按账存结转、金额沿用期初'%row['product_name'])
        elif produced_qty and not produced_cents: gaps.append('%s 本月生产成本未归集（材料与费用分摊为空），库存金额暂估为 0'%row['product_name'])
        rows.append(row)
    def total(key):
        values=[row[key] for row in rows if row[key] is not None]
        if len(values)!=len(rows): return None
        return sum(values)
    purchased=[p['id'] for p in c.execute('SELECT id FROM products') if fg.is_purchased(c,p['id'])]
    if purchased: gaps.append('外购成品（%s）按进销存 FIFO 计算，未并入自产成品结转'%'、'.join(purchased))
    for pid in sorted({row['product_id'] for row in report.get('rows') or []}-set(pids)):
        gaps.append('%s 本月有发货测算但无生产或库存记录，未进入结转'%products.get(pid,{}).get('name',pid))
    return {'month':year_month,'rows':rows,'totals':{'opening_qty':_ds(sum((_q(r['opening_qty']) for r in rows),Decimal(0))),'opening_cents':total('opening_cents'),
            'produced_qty':_ds(sum((_q(r['produced_qty']) for r in rows),Decimal(0))),'produced_cents':total('produced_cents'),
            'issued_qty':_ds(sum((_q(r['issued_qty']) for r in rows),Decimal(0))),'issued_cents':total('issued_cents'),
            'loss_qty':_ds(sum((_q(r['loss_qty']) for r in rows),Decimal(0))),'loss_cents':total('loss_cents'),
            'ending_qty':_ds(sum((_q(r['ending_qty']) for r in rows),Decimal(0))),'ending_cents':total('ending_cents')},
            'gaps':gaps,'basis':BASIS,'production_cents':sum(production.values()),'allocation_total_cents':allocation['total_cents'],'transport_basis':tc.cost_basis(c,year_month).get('amount_cents')}
