"""成品库存金额：自启用日起按日移动加权，不回溯历史。

数量直接复用 inventory.stock 的当日台账；本模块只负责把入库金额、出库成本与结存金额
按移动加权口径落到产品上。外购成品已有 finished_goods.stock_cost 的 FIFO 成本，这里
单列排除，不重复计算。
"""
import calendar
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import erp_access
import finished_cost
import finished_goods
import inventory
import resources_costs as rc

META_KEY='inventory_valuation'
BASIS=('管理口径：自启用日起按日对自产成品做移动加权。入库取实际成本（当月生产归集成本按产量分摊、'
       '外购到货按实际价），出库按当时结存加权单价，结存金额=已计价数量×加权单价，分差留在结存侧；'
       '启用日之前不回溯。外购成品按进销存 FIFO 单独核算，不并入本表。')


def _q(value):
    if value in (None,''):return Decimal(0)
    return Decimal(str(value))


def _round(value):
    return int(Decimal(value).quantize(Decimal(1),rounding=ROUND_HALF_UP))


def config(c):
    row=c.execute('SELECT value FROM meta WHERE key=?',(META_KEY,)).fetchone()
    try:stored=json.loads(row[0]) if row else {}
    except (TypeError,ValueError):stored={}
    start=stored.get('start_date') or date.today().replace(day=1).isoformat()
    try:start=date.fromisoformat(start).replace(day=1).isoformat()
    except ValueError:start=date.today().replace(day=1).isoformat()
    return {'start_date':start,'enabled':stored.get('enabled',True) is not False,
            'updated_at':stored.get('updated_at',''),'updated_by':stored.get('updated_by','')}


def save_settings(c,body,role,now,audit):
    erp_access.require_role(role,'costs.close')
    if body.get('action','save')!='save':raise ValueError('估值设置操作无效')
    try:start=date.fromisoformat(rc.day(body.get('start_date'))).replace(day=1)
    except ValueError:raise ValueError('启用日必须是有效日期')
    if start>date.today():raise ValueError('启用日不能晚于今天')
    before=config(c)
    value={'start_date':start.isoformat(),'enabled':True,'updated_at':now(),'updated_by':role}
    c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(META_KEY,rc.dump(value)))
    audit(c,role,'设置成品库存估值启用日',META_KEY,before,value)
    return value


class Book:
    """已计价数量/金额与待计价数量分开记，避免把未知成本当成零成本。"""
    __slots__=('valued_qty','unvalued_qty','cents')

    def __init__(self):
        self.valued_qty=Decimal(0);self.unvalued_qty=Decimal(0);self.cents=0

    @property
    def qty(self):return self.valued_qty+self.unvalued_qty

    @property
    def unit(self):
        if not self.valued_qty:return None
        return Decimal(self.cents)/self.valued_qty

    def add(self,qty,cents):
        qty=_q(qty)
        if not qty:return
        if cents is None:
            self.unvalued_qty+=qty;return
        self.valued_qty+=qty;self.cents+=int(cents)
        if self.valued_qty<0:
            # 负库存或历史缺数：超出已计价部分转待计价，不把金额记成负数。
            self.unvalued_qty+=self.valued_qty;self.valued_qty=Decimal(0);self.cents=0
        if self.cents<0:self.cents=0

    def take(self,qty):
        qty=_q(qty)
        if qty<=0:return 0
        valued=min(qty,self.valued_qty)
        cents=_round(valued*self.cents/self.valued_qty) if valued and self.valued_qty else 0
        self.valued_qty-=valued;self.cents-=cents
        rest=qty-valued
        if rest:
            self.unvalued_qty=max(Decimal(0),self.unvalued_qty-rest)
        return cents


def production_pool(c,month):
    """当月自产成品归集成本与产量；产量口径与 finished_cost.month 一致。"""
    costs,_,_=finished_cost.costs(c,month)
    produced={}
    for plan in rc.rows(c,'warehouse_plans'):
        if plan['business_date'][:7]!=month:continue
        for row in plan.get('stock') or []:
            pid=row['product_id'];produced[pid]=produced.get(pid,Decimal(0))+_q(row.get('produced_qty'))
    for batch in rc.rows(c,'processing_batches'):
        if batch.get('voided') or batch['business_date'][:7]!=month:continue
        for out in batch.get('outputs') or []:
            pid=out['product_id'];produced[pid]=produced.get(pid,Decimal(0))+_q(out.get('qty'))
    pool={}
    for pid,qty in produced.items():
        if qty<=0 or finished_goods.is_purchased(c,pid):continue
        cents=int(costs.get(pid,0) or 0)
        pool[pid]={'qty':qty,'cents':cents,'priced':cents>0}
    return pool


def _receipts(c):
    rows=[]
    for record in finished_goods.records(c,'receipt'):
        if record.get('voided'):continue
        pending=bool(record.get('pricing_pending')) or record.get('pricing_status')=='recalculate'
        rows.append((record['business_date'],record,pending))
    rows.sort(key=lambda item:item[0])
    return rows


def _opening(c,start,prev_month):
    """启用日期初数量取当日账面开头，金额取上一月已结存金额；都没有则记待计价。"""
    snap=inventory.stock(c,start)
    previous={}
    if prev_month:
        try:previous={row['product_id']:row for row in finished_cost.month(c,prev_month)['rows']}
        except Exception:previous={}
    books={}
    for row in snap['products']:
        pid=row['product_id'];book=Book();qty=_q(row['opening_qty'])
        if qty:
            prev=previous.get(pid) or {}
            cents=prev.get('ending_cents')
            book.add(qty,None if cents is None else int(cents))
        books[pid]=book
    return books


def _apply_plan_opening(books,pid,opening):
    """仓位计划改期初数量时，按当日单价补/减，保持数量与既有金额一致。"""
    if opening in (None,''):return Decimal(0)
    delta=_q(opening)-books[pid].qty
    if abs(delta)<Decimal('0.0005'):return Decimal(0)
    if delta>0:
        unit=books[pid].unit
        books[pid].add(delta,None if unit is None else _round(delta*unit))
    else:
        books[pid].take(-delta)
    return delta


def ledger(c,month=None):
    """按日重放生成某月的成品库存金额台账；返回当月逐日与逐产品汇总。"""
    cfg=config(c)
    start=date.fromisoformat(cfg['start_date'])
    month=month or date.today().isoformat()[:7]
    try:year,mon=map(int,month.split('-'))
    except ValueError:raise ValueError('月份格式应为 YYYY-MM')
    if not 1<=mon<=12:raise ValueError('月份格式应为 YYYY-MM')
    month=date(year,mon,1).isoformat()[:7]
    end=date(year,mon,calendar.monthrange(year,mon)[1])
    today=date.today()
    if end>today:end=today
    gaps=[]
    if end<start:
        return {'month':month,'start_date':cfg['start_date'],'end_date':end.isoformat(),'basis':BASIS,
                'books':{},'days':[],'products':[],'totals':{'closing_cents':0,'unvalued_qty':'0'},'gaps':['估值启用日晚于本月，尚无金额可算']}
    prev_month=(start.replace(day=1)-timedelta(days=1)).isoformat()[:7]
    books=_opening(c,start.isoformat(),prev_month)
    products={p['id']:p for p in c.execute('SELECT * FROM products ORDER BY id')}
    purchased={pid for pid in products if finished_goods.is_purchased(c,pid)}
    allocations={}  # pid -> {'month':..., 'qty':..., 'cents':...} 累计已分配
    pools=production_pool(c,month)
    receipts=_receipts(c)
    receipts_by_day={}
    for day,record,pending in receipts:
        receipts_by_day.setdefault(day,[]).append((record,pending))
    totals={pid:{'opening_qty':books[pid].qty,'in_qty':Decimal(0),'in_cents':0,'out_qty':Decimal(0),
                 'out_cents':0,'count_qty':Decimal(0),'count_cents':0,'closing_qty':books[pid].qty,
                 'closing_cents':books[pid].cents,'unit_cost':books[pid].unit} for pid in books}
    days=[]
    current=start
    while current<=end:
        day=current.isoformat()
        snap=inventory.stock(c,day)
        rows={row['product_id']:row for row in snap['products']}
        day_products=[]
        for pid,book in books.items():
            if pid not in rows:continue
            row=rows[pid];detail={'product_id':pid,'product_name':products[pid]['name'],'unit':products[pid]['unit']}
            opening_qty=book.qty;opening_cents=book.cents
            if current>start:
                _apply_plan_opening(books,pid,row['opening_qty'])
                opening_qty=book.qty;opening_cents=book.cents
            in_qty=Decimal(0);in_cents=0;unvalued_in=Decimal(0)
            pool=pools.get(pid) or {}
            produced=_q(row['production_qty'])+_q(row['processing_output_qty'])
            if produced:
                alloc=allocations.setdefault(pid,{'qty':Decimal(0),'cents':0,'month':month})
                if alloc['month']!=month:alloc={'qty':Decimal(0),'cents':0,'month':month};allocations[pid]=alloc
                if pool.get('priced') and pool['qty']>0:
                    alloc['qty']+=produced
                    target=min(pool['cents'],_round(alloc['qty']*Decimal(pool['cents'])/pool['qty']))
                    cents=max(0,target-alloc['cents']);alloc['cents']+=cents
                    book.add(produced,cents);in_qty+=produced;in_cents+=cents
                else:
                    book.add(produced,None);in_qty+=produced;unvalued_in+=produced
            purchased_qty=Decimal(0)
            for record,pending in receipts_by_day.get(day,[]):
                for line in record['lines']:
                    if line['product_id']!=pid:continue
                    q=_q(line.get('qty'))
                    cents=None if pending else int(line.get('amount_cents') or 0)
                    book.add(q,cents);purchased_qty+=q;in_qty+=q
                    if cents is None:unvalued_in+=q
                    else:in_cents+=cents
            detail['purchased_qty']=rc.ds(purchased_qty)
            restock=_q(row['return_restock_qty'])
            if restock:
                unit=book.unit
                cents=None if unit is None else _round(restock*unit)
                book.add(restock,cents)
                if cents is None:unvalued_in+=restock
                else:in_cents+=cents
            out_qty=Decimal(0);out_cents=0
            use=_q(row['processing_input_qty'])
            if use:out_cents+=book.take(use);out_qty+=use
            loss=_q(row['loss_qty'])
            if loss:out_cents+=book.take(loss);out_qty+=loss
            shipped=_q(row['shipped_qty'])
            if shipped:out_cents+=book.take(shipped);out_qty+=shipped
            count_qty=Decimal(0);count_cents=0;closing=snap.get('closing')
            if closing:
                counted=next((p for p in closing.get('products',[]) if p['product_id']==pid),None)
                if counted and counted.get('counted_qty') not in (None,''):
                    diff=_q(counted['counted_qty'])-book.qty
                    if diff>0:
                        unit=book.unit
                        cents=None if unit is None else _round(diff*unit)
                        book.add(diff,cents);count_qty+=diff
                        if cents is None:unvalued_in+=diff
                        else:count_cents+=cents
                    elif diff<0:
                        count_cents-=book.take(-diff);count_qty+=diff
            detail.update({'opening_qty':rc.ds(opening_qty),'opening_cents':opening_cents,
                           'in_qty':rc.ds(in_qty),'in_cents':in_cents,'unvalued_in':rc.ds(unvalued_in),
                           'out_qty':rc.ds(out_qty),'out_cents':out_cents,
                           'count_qty':rc.ds(count_qty),'count_cents':count_cents,
                           'closing_qty':rc.ds(book.qty),'valued_qty':rc.ds(book.valued_qty),
                           'unvalued_qty':rc.ds(book.unvalued_qty),'closing_cents':book.cents,
                           'unit_cost':None if book.unit is None else rc.ds(book.unit),
                           'purchased':pid in purchased})
            total=totals[pid]
            total['in_qty']+=in_qty;total['in_cents']+=in_cents;total['out_qty']+=out_qty
            total['out_cents']+=out_cents;total['count_qty']+=count_qty;total['count_cents']+=count_cents
            total['closing_qty']=book.qty;total['closing_cents']=book.cents;total['unit_cost']=book.unit
            day_products.append(detail)
        days.append({'business_date':day,'products':day_products})
        current+=timedelta(days=1)
    product_rows=[]
    for pid,book in books.items():
        total=totals[pid];product=products[pid]
        if pid in purchased:
            gaps.append(f'{product["name"]}：外购成品按进销存 FIFO 单独核算，本表不并入金额')
            continue
        product_rows.append({'product_id':pid,'product_name':product['name'],'unit':product['unit'],
                             'opening_qty':rc.ds(total['opening_qty']),'in_qty':rc.ds(total['in_qty']),
                             'in_cents':total['in_cents'],'out_qty':rc.ds(total['out_qty']),
                             'out_cents':total['out_cents'],'count_qty':rc.ds(total['count_qty']),
                             'count_cents':total['count_cents'],'closing_qty':rc.ds(book.qty),
                             'closing_cents':book.cents,'unvalued_qty':rc.ds(book.unvalued_qty),
                             'unit_cost':None if book.unit is None else rc.ds(book.unit)})
        if book.unvalued_qty>0:
            gaps.append(f'{product["name"]}：结存有 {rc.ds(book.unvalued_qty)} {product["unit"]} 未计价，需补生产归集成本或到货价')
        if book.cents and total['in_cents']==0 and total['opening_qty']==0:
            gaps.append(f'{product["name"]}：本期只有期初/盘存金额，无入库成本可核对')
    return {'month':month,'start_date':cfg['start_date'],'end_date':end.isoformat(),'basis':BASIS,
            'days':days,'products':product_rows,
            'totals':{'closing_cents':sum(row['closing_cents'] for row in product_rows),
                      'unvalued_qty':rc.ds(sum((_q(row['unvalued_qty']) for row in product_rows),Decimal(0)))},
            'gaps':gaps}
