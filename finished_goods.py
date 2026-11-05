"""Purchased finished products: stock receipts, supplier payables and immutable statements.

No commits: every mutation belongs to the caller's transaction. Receipt value is
inventory acquisition, while the FIFO value of shipped goods is sales cost.
"""
import calendar
import hashlib
import json
import secrets
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
import resources_costs as rc
import erp_access as access

PERMISSIONS={'stock-receipt':('inventory.stock',),'stock-edit':('inventory.stock',),'stock-return':('inventory.stock',),'order-edit':('inventory.stock',),'price-return':('purchases.cost',),'price':('purchases.cost',),'refund':('purchases.pay',),'receipt':('purchases.cost',),'payment':('purchases.pay',),'void':('purchases.cost',),'statement':('purchases.cost',)}


def records(c,kind=None):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='finished_goods_records'").fetchone():return []
    return [r for r in rc.rows(c,'finished_goods_records') if kind is None or r['kind']==kind]


def supplied(c,day,pid):
    return sum((Decimal(l['qty']) for r in records(c,'receipt') if not r.get('voided') and r['business_date']==day for l in r['lines'] if l['product_id']==pid),Decimal(0))


def is_purchased(c,pid):
    row=c.execute("SELECT value FROM meta WHERE key='product_trade'").fetchone();cfg=json.loads(row[0]) if row else {}
    return cfg.get(pid,{}).get('supply_kind')=='purchased'


def suggested_price(c,supplier_id,product_id):
    """Supplier archive price first, then the latest confirmed purchase price."""
    supplier=next((s for s in rc.rows(c,'suppliers') if s['id']==supplier_id),None)
    price=(supplier or {}).get('product_prices',{}).get(product_id) if supplier else None
    if price not in (None,''):
        return rc.ds(price)
    for r in sorted(records(c,'receipt'),key=lambda r:(r['business_date'],r['id']),reverse=True):
        if r.get('voided') or r.get('return_of') or r['supplier_id']!=supplier_id:continue
        if r.get('pricing_pending') or r.get('pricing_status')=='recalculate':continue
        for l in r['lines']:
            if l['product_id']==product_id and l.get('price') not in (None,''):
                return rc.ds(l['price'])
    return None


def stock_cost(c,start,end,lot_out=None):
    """FIFO, respecting unknown opening stock rather than inventing a zero price."""
    receipts=[r for r in records(c,'receipt') if not r.get('voided') and r['business_date']<=end]
    released=[(r,d) for r in rc.rows(c,'sales_returns') if not r.get('voided') for d in r.get('disposals',[]) if not d.get('voided') and d['kind']=='restock' and d['business_date']<=end]
    orders=[o for o in rc.rows(c,'orders') if o['business_date']<=end];pids={l['product_id'] for r in receipts for l in r['lines']};pids|={p['id'] for p in c.execute('SELECT id FROM products') if is_purchased(c,p['id'])}
    result=[];plans=rc.rows(c,'warehouse_plans')
    for pid in pids:
        incoming=[(r,l) for r in receipts for l in r['lines'] if l['product_id']==pid]
        days=sorted({d['business_date'] for r,d in released if r['product_id']==pid}|{r['business_date'] for r,l in incoming}|{o['business_date'] for o in orders if any(l['product_id']==pid and Decimal(l['actual_qty'])>0 for l in o['lines'])})
        lots=[];cost=0;unvalued=Decimal(0);sold=Decimal(0);opened=False
        for day in days:
            if not opened:
                p=next((p for p in plans if p['business_date']==day),{});opening=next((r.get('existing_qty','') for r in p.get('stock',[]) if r['product_id']==pid),'')
                if is_purchased(c,pid) and opening not in ('',None) and Decimal(opening)>0:lots.append({'qty':Decimal(opening),'cents':None})
                opened=True
            for r,l in sorted(incoming,key=lambda x:bool(x[0].get('return_of'))):
                if r['business_date']!=day:continue
                if not r.get('return_of'):
                    lots.append({'id':r['id'],'qty':Decimal(l['qty']),'cents':None if r.get('pricing_pending') else l['amount_cents']})
                else:
                    lot=next((v for v in lots if v.get('id')==r['return_of']),None);q=-Decimal(l['qty'])
                    if not lot or q>lot['qty']:raise ValueError('原到货批次可退库存不足，部分已发货；请先核对客户实发及退货，不能重复退给供应商')
                    if lot['cents'] is not None:
                        if -l['amount_cents']>lot['cents']:raise ValueError('退回计价金额超过原批次剩余价值，请核对退回净重')
                        lot['cents']+=l['amount_cents']
                    lot['qty']-=q

            for returned,disposal in released:
                if returned['product_id']==pid and disposal['business_date']==day:lots.append({'qty':Decimal(disposal['stock_qty']),'cents':None})
            out=sum((Decimal(l['actual_qty']) for o in orders if o['business_date']==day for l in o['lines'] if l['product_id']==pid),Decimal(0));remaining=out;daycost=0;unknown=Decimal(0)
            for lot in lots:
                take=min(remaining,lot['qty'])
                if take<=0:continue
                if lot['cents'] is None:unknown+=take
                else:
                    value=lot['cents'] if take==lot['qty'] else int((Decimal(lot['cents'])*take/lot['qty']).quantize(Decimal(1),rounding=ROUND_HALF_UP));lot['cents']-=value;daycost+=value
                lot['qty']-=take;remaining-=take
                if remaining<=0:break
            if is_purchased(c,pid):unknown+=remaining
            if day>=start:cost+=daycost;unvalued+=unknown;sold+=out if is_purchased(c,pid) else out-remaining
        product=c.execute('SELECT name,unit FROM products WHERE id=?',(pid,)).fetchone()
        if lot_out is not None:lot_out[pid]=lots
        result.append({'product_id':pid,'product_name':product['name'] if product else pid,'unit':product['unit'] if product else '', 'sold_qty':rc.ds(sold),'sales_cost_cents':cost,'unvalued_qty':rc.ds(unvalued),'ending_qty':rc.ds(sum((l['qty'] for l in lots),Decimal(0))),'ending_value_cents':sum(l['cents'] or 0 for l in lots),'ending_unvalued_qty':rc.ds(sum((l['qty'] for l in lots if l['cents'] is None),Decimal(0)))})
    return result


def projection(c,month):
    rc.day(month+'-01');end=month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:]))[1]);all_receipts=records(c,'receipt');payments=records(c,'payment');receipts=[]
    for r in all_receipts:
        ps=[p for p in payments if p['receipt_id']==r['id']];paid=sum(p['amount_cents'] for p in ps)
        refunds=[p for p in records(c,'refund') if p['receipt_id']==r['id']];refunded=sum(p['amount_cents'] for p in refunds)
        returns=[x for x in all_receipts if x.get('return_of')==r['id'] and not x.get('voided')]
        returned=-sum(x['amount_cents'] for x in returns)
        row={**r,'paid_cents':paid-refunded,'returned_cents':returned,'net_amount_cents':r['amount_cents']-returned,'outstanding_cents':0 if r.get('voided') or r.get('return_of') else r['amount_cents']-returned-paid+refunded,'payments':ps,'refunds':refunds,'returns':[x['id'] for x in returns]}
        if (row.get('pricing_pending') or row.get('pricing_status')=='recalculate') and not row.get('return_of'):
            lines=[]
            for l in row['lines']:
                line=dict(l)
                if not line.get('price'):
                    price=suggested_price(c,row['supplier_id'],line['product_id'])
                    if price:line['suggested_price']=price
                lines.append(line)
            row['lines']=lines
        receipts.append(row)
    selected=[r for r in receipts if r['business_date'].startswith(month) and not r.get('voided')]
    cost=stock_cost(c,month+'-01',end)
    return {'month':month,'receipts':receipts,'payments':payments,'statements':[{**d,'source_changed':any(next((r['version'] for r in all_receipts if r['id']==rid),None)!=version for rid,version in d.get('source_versions',{}).items())} for d in records(c,'statement')],'costs':cost,'totals':{'purchased_cents':sum(r['amount_cents'] for r in selected),'paid_cents':sum(p['amount_cents'] for p in payments if p['business_date'].startswith(month))-sum(p['amount_cents'] for p in records(c,'refund') if p['business_date'].startswith(month)),'pending_count':sum(bool(r.get('pricing_pending') or r.get('pricing_status')=='recalculate') for r in receipts if not r.get('voided') and not r.get('return_of')),'outstanding_cents':sum(r['outstanding_cents'] for r in receipts),'sales_cost_cents':sum(r['sales_cost_cents'] for r in cost),'ending_value_cents':sum(r['ending_value_cents'] for r in cost)}}


def statement_preview(c,supplier_id,month):
    supplier=c.execute('SELECT payload FROM suppliers WHERE id=?',(supplier_id,)).fetchone()
    if not supplier:raise ValueError('请选择有效供应人')
    supplier=json.loads(supplier[0]);p=projection(c,month);end=month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:]))[1])
    bases=[r for r in p['receipts'] if r['supplier_id']==supplier_id and not r.get('return_of') and r['business_date']<=end and not r.get('voided') and (r['business_date'].startswith(month) or r['outstanding_cents']!=0 or any(x['business_date'].startswith(month) for x in p['receipts'] if x.get('return_of')==r['id']))]
    ids={r['id'] for r in bases}
    rows=bases+[r for r in p['receipts'] if r.get('return_of') in ids and not r.get('voided') and r['business_date']<=end]
    if any(r.get('pricing_pending') or r.get('pricing_status')=='recalculate' for r in rows):raise ValueError('该供应商存在未计价到货，请先补齐价格再出具结算单')
    value={'company':__import__('company').current(c),'supplier_id':supplier_id,'supplier_name':supplier['name'],'month':month,'as_of':end,'receipts':rows,'amount_cents':sum(r['amount_cents'] for r in rows),'paid_cents':sum(r['paid_cents'] for r in rows),'outstanding_cents':sum(r['outstanding_cents'] for r in rows),'balance_basis':'所选月验收与截至出具时的历史未付；后续付款不改写归档版本'}
    value['source_fingerprint']=hashlib.sha256(rc.dump(value).encode()).hexdigest();return value


def save(c,kind,b,role,now,audit):
    import inventory,trade,purchasing
    if kind in ('stock-receipt','stock-edit','stock-return','order-edit','price-return','price','refund'):return save_stock(c,kind,b,role,now,audit)
    if kind not in PERMISSIONS:raise ValueError('外购成品操作无效')
    for permission in PERMISSIONS[kind]:access.require_role(role,permission)
    key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}).encode()).hexdigest()
    prior=c.execute('SELECT payload FROM finished_goods_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        value=json.loads(prior[0])
        if value['fingerprint']!=finger:raise ValueError('提交编号已使用，请重新打开')
        return value
    old=None;day=rc.day(b.get('business_date')) if kind!='statement' else None
    if day:
        rc.open_period(c,day)
        if any(json.loads(r[0])['state']=='closed' and r[1]>=day[:7] for r in c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('所属或后续成本月份已结账，请先重开')
    if kind=='receipt':
        inventory.open_day(c,day);inventory.expect_revision(c,b)
        sr=c.execute('SELECT payload FROM suppliers WHERE id=?',(b.get('supplier_id'),)).fetchone();supplier=json.loads(sr[0]) if sr else None
        import purchasing
        if not supplier or not purchasing.finished_supplier(c,supplier):raise ValueError('请选择供货品类包含成品的合作供应商')
        lines=b.get('lines')
        if not isinstance(lines,list) or not 1<=len(lines)<=100:raise ValueError('请填写外购成品明细')
        out=[];seen=set()
        for l in lines:
            if not isinstance(l,dict):raise ValueError('成品明细无效')
            p=c.execute('SELECT * FROM products WHERE id=?',(l.get('product_id'),)).fetchone()
            if not p or p['id'] in seen:raise ValueError('外购产品不存在或重复')
            cfg=trade.product_config(c,p)
            if cfg.get('supply_kind') not in ('purchased','mixed'):raise ValueError(p['name']+'请先设为外购成品并关联供应商')
            if supplier['id'] not in cfg.get('supplier_ids',[]):raise ValueError(p['name']+'与当前供应商未关联，请先维护产品供货关系')
            seen.add(p['id']);qty=rc.qty(l.get('qty'),'验收数量',True);fractional=next((u['fractional'] for u in trade.units(c) if u['id']==p['unit']),False)
            if not fractional and qty!=qty.to_integral_value():raise ValueError(p['name']+'验收数量须为整数')
            bill=l.get('billing_unit',p['unit'])
            if bill not in ('公斤',p['unit']):raise ValueError('采购计价单位请选择公斤或本产品发货单位')
            kg=qty if p['unit']=='公斤' else rc.qty(l.get('net_kg'),'采购实称净重',True) if l.get('net_kg') not in ('',None) else None
            if bill=='公斤' and kg is None:raise ValueError(p['name']+'按公斤采购，须填采购实称净重')
            price=rc.qty(l.get('price'),'采购单价',True);bill_qty=kg if bill=='公斤' else qty;amount=int((bill_qty*price*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
            if not 0<amount<=10000000000:raise ValueError('成品采购金额须在0.01至100000000元之间')
            out.append({'product_id':p['id'],'product_name':p['name'],'unit':p['unit'],'qty':rc.ds(qty),'net_kg':None if kg is None else rc.ds(kg),'billing_unit':bill,'bill_qty':rc.ds(bill_qty),'price':rc.ds(price),'amount_cents':amount})
        total=sum(l['amount_cents'] for l in out)
        if total>10000000000:raise ValueError('外购成品总额超限')
        value={'kind':kind,'business_date':day,'supplier_id':supplier['id'],'supplier_name':supplier['name'],'lines':out,'amount_cents':total,'due_date':(date.fromisoformat(day)+timedelta(days=int(supplier.get('payment_days',0)))).isoformat(),'reference':rc.text(b.get('reference',''),'供货单号',100,False),'note':rc.text(b.get('note'),'验收依据',500),'handler':rc.text(b.get('handler'),'验收经办人',80),'voided':False}
        label='验收外购成品并登记供应人应付'
    elif kind in ('payment','void'):
        old=next((r for r in records(c,'receipt') if r['id']==b.get('receipt_id')),None)
        if not old or old.get('voided') or b.get('version')!=old['version']:raise ValueError('外购成品单已更新或作废，请刷新')
        account=next(r for r in projection(c,day[:7])['receipts'] if r['id']==old['id'])
        paid=account['paid_cents']
        if day<old['business_date']:raise ValueError('处理日期不能早于验收日期')
        if kind=='void':
            inventory.open_day(c,old['business_date']);rc.open_period(c,old['business_date'])
            if old.get('return_of') or account.get('returns') or old.get('pricing_pending'):raise ValueError('请通过到货记录更正或退回处理，不能作废关联单据')
            if paid:raise ValueError('已有供应人付款的单据不能作废')
            if any(old['id'] in d.get('source_receipt_ids',[]) for d in records(c,'statement')):raise ValueError('已出具供应人结算单，请保留原单并按实际差异另行核对')
            lots={}
            stock_cost(c,'0000-01-01','9999-12-31',lots)
            for pid in {l['product_id'] for l in old['lines']}:
                expected=sum((Decimal(l['qty']) for l in old['lines'] if l['product_id']==pid),Decimal(0))
                lot=next((l for l in lots.get(pid,[]) if l.get('id')==old['id']),None)
                if not lot or Decimal(lot['qty'])<expected:raise ValueError('该批次已有发货或转加工耗用，不能作废；请按实际退回或到货更正处理')
            value={**old,'voided':True,'void_reason':rc.text(b.get('note'),'作废原因',500)};label='作废外购成品验收'
        else:
            amount=rc.cents(b.get('amount'),positive=True)
            if old.get('pricing_pending') or old.get('pricing_status')=='recalculate' or old.get('return_of'):raise ValueError('请先完成原到货单计价，再登记付款')
            if amount>account['outstanding_cents']:raise ValueError('付款不能超过该成品单未付余额')
            if b.get('method') not in ('银行转账','现金','微信','支付宝','其他'):raise ValueError('请选择付款方式')
            value={'account_id':purchasing.payment_account(c,b),'kind':'payment','business_date':day,'receipt_id':old['id'],'supplier_id':old['supplier_id'],'supplier_name':old['supplier_name'],'amount_cents':amount,'method':b['method'],'reference':rc.text(b.get('reference',''),'付款凭据',100,False),'handler':rc.text(b.get('handler'),'付款经办人',80),'note':rc.text(b.get('note'),'付款说明',500)};label='登记外购成品实际付款'
            c.execute('UPDATE finished_goods_records SET payload=? WHERE id=?',(rc.dump({**old,'version':old['version']+1}),old['id']))
    else:
        preview=statement_preview(c,b.get('supplier_id'),b.get('month'))
        if not preview['receipts']:raise ValueError('该供应人当前范围没有外购成品账款')
        if b.get('source_fingerprint')!=preview['source_fingerprint']:raise ValueError('供应人账款已变化，请重新预览核对')
        value={**preview,'kind':'statement','id':'GY-'+preview['month'].replace('-','')+'-'+secrets.token_hex(5).upper(),'source_receipt_ids':[r['id'] for r in preview['receipts']],'source_versions':{r['id']:r['version'] for r in preview['receipts']},'handler':rc.text(b.get('handler'),'结算经办人',80),'issued_at':now(),'note':rc.text(b.get('note',''),'结算说明',500,False),'state':'待供应人核对'};label='出具外购成品供应人结算单'
    value.update(id=value.get('id','FG-'+secrets.token_hex(8)),version=old['version']+1 if kind=='void' else 1,updated_at=now())
    if kind=='void':c.execute('UPDATE finished_goods_records SET payload=? WHERE id=?',(rc.dump(value),old['id']))
    else:c.execute('INSERT INTO finished_goods_records VALUES(?,?)',(value['id'],rc.dump(value)))
    if kind in ('receipt','void'):
        inventory.validate_book(c,value['business_date'],True);inventory.bump(c)
    result={**value,'fingerprint':finger};c.execute('INSERT INTO finished_goods_submissions VALUES(?,?)',(key,rc.dump(result)));audit(c,role,label,value['id'],old if kind=='void' else None,value)
    return result


def quantity_only(value):
    """Explicit allowlist for warehouse responses, including idempotent replays."""
    allowed={'id','kind','version','updated_at','business_date','supplier_id','supplier_name','product_id','product_name','unit','qty','expected_qty','received_qty','remaining_qty','over_qty','state','note','handler','reference','order_id','return_of','voided','pricing_pending','lines','receipts','orders','net_kg','closed_reason','inventory_revision','pricing_status'}
    if isinstance(value,dict):return {k:quantity_only(v) for k,v in value.items() if k in allowed}
    if isinstance(value,list):return [quantity_only(v) for v in value]
    return value


def inventory_projection(c):
    receipts=[r for r in records(c,'receipt') if not r.get('voided')]
    orders=[]
    for o in records(c,'order'):
        received=sum((Decimal(l['qty']) for r in receipts if r.get('order_id')==o['id'] for l in r['lines']),Decimal(0))
        remaining=Decimal(o['expected_qty'])-received
        orders.append({**o,'received_qty':rc.ds(received),'remaining_qty':rc.ds(max(remaining,Decimal(0))),'over_qty':rc.ds(max(-remaining,Decimal(0)))})
    return quantity_only({'orders':orders,'receipts':receipts})


def store(c,r):
    c.execute('INSERT INTO finished_goods_records VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(r['id'],rc.dump(r)))


def save_stock(c,kind,b,role,now,audit):
    c.execute('SAVEPOINT finished_goods_change')
    try:
        result=_save_stock(c,kind,b,role,now,audit)
        c.execute('RELEASE finished_goods_change');return result
    except Exception:
        c.execute('ROLLBACK TO finished_goods_change');c.execute('RELEASE finished_goods_change');raise


def _save_stock(c,kind,b,role,now,audit):
    import inventory,trade,purchasing
    for permission in PERMISSIONS[kind]:access.require_role(role,permission)
    key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}).encode()).hexdigest()
    prior=c.execute('SELECT payload FROM finished_goods_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        value=json.loads(prior[0])
        if value['fingerprint']!=finger:raise ValueError('提交编号已使用，请重新打开')
        return value
    day=rc.day(b.get('business_date'));old=None;label='';note=rc.text(b.get('note'),'处理依据',500) if kind!='stock-receipt' else rc.text(b.get('note',''),'处理依据',500,False)
    if kind!='order-edit':
        rc.open_period(c,day)
        if any(json.loads(r[0])['state']=='closed' and r[1]>=day[:7] for r in c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('所属或后续成本月份已结账，请先重开')
    if kind in ('stock-receipt','stock-edit','stock-return'):
        inventory.open_day(c,day);inventory.expect_revision(c,b)
    if kind in ('stock-edit','stock-return','price-return','price','refund'):
        old=next((r for r in records(c,'receipt') if r['id']==b.get('receipt_id')),None)
        if not old or old.get('voided') or old.get('return_of') or type(b.get('version')) is not int or old['version']!=b['version']:raise ValueError('原到货单已更新，请同步后重新打开')
        if day<old['business_date']:raise ValueError('处理日期不能早于原到货日期')
    if kind in ('stock-receipt','stock-edit'):
        if kind=='stock-edit':
            if not old.get('pricing_pending'):raise ValueError('已计价到货请使用退回 / 补到处理，以保留结算依据')
            if old['business_date']!=day:raise ValueError('更正到货不能更换日期，跨日差异请用退回或补到')
            if any(r.get('return_of')==old['id'] and not r.get('voided') for r in records(c,'receipt')):raise ValueError('已有退回记录，请用补到或退回修正数量')
            # Supplier and product are the original order identity, even when its category is later disabled.
            supplier_id=b.get('supplier_id') or old['supplier_id'];pid=old['lines'][0]['product_id'];order_id=old.get('order_id')
        else:
            pid=b.get('product_id');order_id=b.get('order_id');unit_price=None
            if kind=='stock-receipt' and not b.get('supplier_id'):
                supplier,unit_price=purchasing.supplier_for_product(c,pid)
                supplier_id=supplier['id']
            else:
                supplier_id=b.get('supplier_id')
                if kind=='stock-receipt':
                    supplier=next((s for s in rc.rows(c,'suppliers') if s['id']==supplier_id),None)
                    if b.get('price') not in (None,''):unit_price=rc.qty(b.get('price'),'采购单价',True)
        p=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
        if not p:raise ValueError('产品不存在')
        cfg=trade.product_config(c,p)
        if kind!='stock-receipt':supplier=next((s for s in rc.rows(c,'suppliers') if s['id']==supplier_id),None)
        if (kind=='stock-receipt' or supplier_id!=old['supplier_id']) and (cfg.get('supply_kind') not in ('purchased','mixed') or not supplier or not purchasing.finished_supplier(c,supplier) or (kind!='stock-receipt' and supplier_id not in cfg.get('supplier_ids',[]))):raise ValueError('请先为产品设置外购或自产＋外购，并关联供货品类包含成品的供应商')
        q=rc.qty(b.get('qty'),'本次实收到货数量',True)
        if not next((u['fractional'] for u in trade.units(c) if u['id']==p['unit']),False) and q!=q.to_integral_value():raise ValueError('该产品到货数量须为整数')
        order=next((r for r in records(c,'order') if r['id']==order_id),None) if order_id else None
        if order_id and not order:raise ValueError('供应商订单不存在')
        if order:
            if kind=='stock-edit' and supplier_id!=order['supplier_id']:
                if any(r.get('order_id')==order['id'] and r['id']!=old['id'] and not r.get('voided') for r in records(c,'receipt')):raise ValueError('订单已有其他到货，不能更换供应商；请用退回和重新外购更正供货关系')
                prior_order=order;order={**order,'supplier_id':supplier_id,'supplier_name':supplier['name'],'version':order['version']+1,'updated_at':now()}
                store(c,order);audit(c,role,'更正未计价外购订单供应商',order['id'],prior_order,order)
            if order['state']=='closed' and kind!='stock-edit':raise ValueError('供应商订单余量已关闭，请先重新打开订单或另建采购')
            if order['supplier_id']!=supplier_id or order['product_id']!=pid:raise ValueError('供应商或产品与原采购订单不一致')
            if day<order['business_date']:raise ValueError('到货日期不能早于订购日期')
        else:
            expected=rc.qty(b.get('expected_qty',b.get('qty')),'供应商订购数量',True)
            order={'id':'FO-'+secrets.token_hex(8),'kind':'order','version':1,'business_date':day,'supplier_id':supplier_id,'supplier_name':supplier['name'],'product_id':pid,'product_name':p['name'],'unit':p['unit'],'expected_qty':rc.ds(expected),'state':'open','note':note,'updated_at':now()}
            store(c,order)
        others=sum((Decimal(l['qty']) for r in records(c,'receipt') if r.get('order_id')==order['id'] and not r.get('voided') and (not old or r['id']!=old['id']) for l in r['lines']),Decimal(0))
        if kind=='stock-receipt' and not b.get('supplier_id') and others+q>Decimal(order['expected_qty']):
            order={**order,'expected_qty':rc.ds(others+q),'version':order['version']+1,'updated_at':now()};store(c,order)
        elif others+q>Decimal(order['expected_qty']) and b.get('accept_over') is not True:raise ValueError('累计实收超过供应商订购量，请明确确认接受多发；不接受的数量不要入库')
        kg=q if p['unit']=='公斤' else rc.qty(b.get('net_kg'),'实收净重',True) if b.get('net_kg') not in ('',None) else None
        if kind=='stock-receipt':kg=q if p['unit']=='公斤' else None
        line_price=unit_price if kind=='stock-receipt' else None
        line_amount=int((q*line_price*100).quantize(Decimal(1),rounding=ROUND_HALF_UP)) if line_price is not None else 0
        line={'product_id':pid,'product_name':p['name'],'unit':p['unit'],'qty':rc.ds(q),'net_kg':rc.ds(kg) if kg is not None else None,'billing_unit':p['unit'],'bill_qty':rc.ds(q),'price':rc.ds(line_price) if line_price is not None else None,'amount_cents':line_amount}
        due=(date.fromisoformat(day)+timedelta(days=int(supplier.get('payment_days',0)))).isoformat() if kind=='stock-receipt' else day
        value={**(old or {}),'id':old['id'] if old else 'FG-'+secrets.token_hex(8),'kind':'receipt','business_date':day,'order_id':order['id'],'supplier_id':supplier_id,'supplier_name':supplier['name'],'lines':[line],'amount_cents':line_amount,'pricing_pending':line_price is None,'due_date':due,'note':note,'handler':rc.text(b.get('handler',''),'验收人',80,False),'reference':rc.text(b.get('reference',''),'供货单号',100,False),'voided':False}
        label='更正未计价外购到货' if old else '库存登记外购并关联供应商订单'
    elif kind=='order-edit':
        old=next((r for r in records(c,'order') if r['id']==b.get('order_id')),None)
        if not old or type(b.get('version')) is not int or old['version']!=b['version']:raise ValueError('供应商订单已变化，请同步后重试')
        expected=rc.qty(b.get('expected_qty'),'订购数量',True)
        state=b.get('state','open')
        if state not in ('open','closed'):raise ValueError('订单状态无效')
        value={**old,'expected_qty':rc.ds(expected),'state':state,'note':note};label='调整供应商订购量或未到货余量'
    elif kind=='price-return':
        if old.get('pricing_pending') or old.get('pricing_status')=='recalculate':raise ValueError('该单已在待算票或待重算队列')
        value={**old,'pricing_status':'recalculate','recalculate_reason':note};label='外购成品退回会计重算'
    elif kind=='price':
        if not old.get('pricing_pending') and old.get('pricing_status')!='recalculate':raise ValueError('请先退回重算，再修改已确认的价格')
        if b.get('evidence_checked') is not True:raise ValueError('请核对逐笔采购价格、数量及差额后确认算票')
        rc.open_period(c,old['business_date'])
        if any(json.loads(r[0])['state']=='closed' and r[1]>=old['business_date'][:7] for r in c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('原到货成本月份已结账，请先重开后计价')
        if day!=old['business_date']:raise ValueError('计价归属原到货日期，请保留原日期')
        entries=b.get('lines')
        if entries is None and len(old['lines'])==1:entries=[{**b,'product_id':old['lines'][0]['product_id']}]
        if not isinstance(entries,list) or len(entries)!=len(old['lines']) or any(not isinstance(e,dict) for e in entries):raise ValueError('请逐产品填写本笔采购单价')
        if len({e.get('product_id') for e in entries})!=len(entries):raise ValueError('计价产品重复')
        out=[]
        for l in old['lines']:
            e=next((e for e in entries if e.get('product_id')==l['product_id']),None)
            if e is None:raise ValueError('计价明细必须完整保留原到货产品')
            bill=e.get('billing_unit',l['unit'])
            if bill not in ('公斤',l['unit']):raise ValueError('计价单位请选择公斤或产品发货单位')
            kg=Decimal(l['qty']) if l['unit']=='公斤' else rc.qty(e.get('net_kg'),'采购实收净重',True) if e.get('net_kg') not in ('',None) else None
            if bill=='公斤' and kg is None:raise ValueError('按公斤采购须补齐实收净重')
            price=rc.qty(e.get('price'),'采购单价',True);bill_qty=kg if bill=='公斤' else Decimal(l['qty']);cents=int((bill_qty*price*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
            if not 0<cents<=10000000000:raise ValueError('采购金额须在0.01至100000000元之间')
            out.append({**l,'billing_unit':bill,'net_kg':rc.ds(kg) if kg is not None else None,'bill_qty':rc.ds(bill_qty),'price':rc.ds(price),'amount_cents':cents})
        total=sum(l['amount_cents'] for l in out)
        if total>10000000000:raise ValueError('本笔采购总金额超限')
        value={**old,'lines':out,'amount_cents':total,'pricing_pending':False,'pricing_note':note,'priced_at':now(),'pricing_status':'confirmed','pricing_history':[*old.get('pricing_history',[]),{'previous_amount_cents':old['amount_cents'],'amount_cents':total,'previous_lines':old['lines'],'reason':note,'at':now(),'role':role}]}
        supplier=next(s for s in rc.rows(c,'suppliers') if s['id']==old['supplier_id'])
        value['due_date']=(date.fromisoformat(day)+timedelta(days=int(supplier.get('payment_days',0)))).isoformat()
        returned=[r for r in records(c,'receipt') if r.get('return_of')==old['id'] and not r.get('voided')]
        for ret in returned:
            rc.open_period(c,ret['business_date']);rl=ret['lines'][0];rq=-Decimal(rl['qty']);l=next(l for l in out if l['product_id']==rl['product_id']);bill=l['billing_unit'];price=Decimal(l['price'])
            rkg=Decimal(rl['net_kg']) if rl.get('net_kg') not in ('',None) else None
            if bill=='公斤' and rkg is None:raise ValueError('原到货有退回，按公斤计价前须在退回时登记净重')
            bq=rkg if bill=='公斤' else rq;amount=int((bq*price*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
            store(c,{**ret,'pricing_pending':False,'amount_cents':-amount,'version':ret['version']+1,'lines':[{**rl,'billing_unit':bill,'bill_qty':rc.ds(-bq),'price':rc.ds(price),'amount_cents':-amount}]})
        for l in out:
            matching=[r for r in records(c,'receipt') if r.get('return_of')==old['id'] and not r.get('voided') and r['lines'][0]['product_id']==l['product_id']]
            if matching and sum((-Decimal(r['lines'][0]['qty']) for r in matching),Decimal(0))==Decimal(l['qty']):
                if l['billing_unit']=='公斤' and sum((Decimal(r['lines'][0]['net_kg'] or 0) for r in matching),Decimal(0))!=Decimal(l['net_kg']):raise ValueError('该产品已全部退回，原到货净重须与退回净重合计一致')
                last=matching[-1];residual=l['amount_cents']-sum(-r['amount_cents'] for r in matching[:-1])
                if residual<0:raise ValueError('退回计价超出原到货金额，请核对')
                store(c,{**last,'amount_cents':-residual,'lines':[{**last['lines'][0],'amount_cents':-residual}]})
        if sum(-r['amount_cents'] for r in records(c,'receipt') if r.get('return_of')==old['id'] and not r.get('voided'))>total:raise ValueError('累计退回金额超过原货款，请核对净重')
        label='逐笔确认或重算外购成品订单'
    elif kind=='stock-return':
        l=next((l for l in old['lines'] if l['product_id']==b.get('product_id')),old['lines'][0] if len(old['lines'])==1 else None)
        if l is None:raise ValueError('请选择原到货单中的退回产品')
        q=rc.qty(b.get('qty'),'本次退回数量',True);p=c.execute('SELECT unit FROM products WHERE id=?',(l['product_id'],)).fetchone()
        if not next((u['fractional'] for u in trade.units(c) if u['id']==p['unit']),False) and q!=q.to_integral_value():raise ValueError('该产品退回数量须为整数')
        returned=[r for r in records(c,'receipt') if r.get('return_of')==old['id'] and not r.get('voided') and r['lines'][0]['product_id']==l['product_id']]
        remaining=Decimal(l['qty'])+sum((Decimal(r['lines'][0]['qty']) for r in returned),Decimal(0))
        if q>remaining:raise ValueError('退回数量超过原到货未退数量')
        kg=q if l['unit']=='公斤' else rc.qty(b.get('net_kg'),'退回实称净重',True) if b.get('net_kg') not in ('',None) else None
        bill=l['billing_unit'];pending=old.get('pricing_pending',False)
        if bill=='公斤' and kg is None:raise ValueError('原单按公斤计价，请填写退回实称净重')
        if kg is not None and l.get('net_kg') is not None and kg+sum((Decimal(r['lines'][0]['net_kg'] or 0) for r in returned),Decimal(0))>Decimal(l['net_kg']):raise ValueError('累计退回净重超过原到货净重')
        bq=kg if bill=='公斤' else q;cents=0 if pending else int((bq*Decimal(l['price'])*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        if q==remaining and not pending:
            if bill=='公斤' and kg+sum((Decimal(r['lines'][0]['net_kg'] or 0) for r in returned),Decimal(0))!=Decimal(l['net_kg']):raise ValueError('全部退回时请核对原到货剩余净重，不能留下无数量的库存金额')
            cents=l['amount_cents']-sum(-r['amount_cents'] for r in returned)
        if cents+sum(-r['amount_cents'] for r in returned)>l['amount_cents'] and not pending:raise ValueError('累计退回金额超过原到货货款')
        value={'id':'FG-'+secrets.token_hex(8),'kind':'receipt','business_date':day,'return_of':old['id'],'order_id':old.get('order_id'),'supplier_id':old['supplier_id'],'supplier_name':old['supplier_name'],'lines':[{**l,'qty':rc.ds(-q),'net_kg':rc.ds(kg) if kg is not None else None,'bill_qty':rc.ds(-bq),'amount_cents':-cents}],'amount_cents':-cents,'pricing_pending':pending,'handler':rc.text(b.get('handler'),'退回经办人',80),'note':note,'voided':False,'due_date':day};label='外购成品退回并冲减原单应付'
        # A return consumes stock today; posted historical receipts stay intact.
        store(c,{**old,'version':old['version']+1})
    else:  # supplier refund following a paid receipt's return credit
        inventory.open_day(c,day);rc.open_period(c,day)
        account=next(r for r in projection(c,day[:7])['receipts'] if r['id']==old['id']);amount=rc.cents(b.get('amount'),positive=True)
        if old.get('pricing_pending') or old.get('pricing_status')=='recalculate' or amount>max(0,-account['outstanding_cents']):raise ValueError('退款不能超过供应商应退余额')
        value={'id':'FG-'+secrets.token_hex(8),'kind':'refund','business_date':day,'receipt_id':old['id'],'supplier_id':old['supplier_id'],'supplier_name':old['supplier_name'],'amount_cents':amount,'account_id':purchasing.payment_account(c,b),'handler':rc.text(b.get('handler'),'退款经办人',80),'note':note,'reference':rc.text(b.get('reference',''),'退款凭据',100,False)};label='登记供应商实际退回货款'
        store(c,{**old,'version':old['version']+1})
    value.update(version=old['version']+1 if kind in ('stock-edit','order-edit','price-return','price') else 1,updated_at=now())
    store(c,value)
    if kind=='price':stock_cost(c,'0001-01-01','9999-12-31')
    if kind in ('stock-receipt','stock-edit','stock-return'):
        # Check every affected future open day, so reductions cannot strand downstream shipments.
        days={day}|{r['business_date'] for table in ('warehouse_plans','orders') for r in rc.rows(c,table) if r['business_date']>=day}
        for when in sorted(days):inventory.validate_book(c,when,True)
        if kind=='stock-return':stock_cost(c,'0001-01-01','9999-12-31')
        inventory.bump(c)
    result={**value,'fingerprint':finger,'inventory_revision':inventory.revision(c)}
    c.execute('INSERT INTO finished_goods_submissions VALUES(?,?)',(key,rc.dump(result)))
    audit(c,role,label,value['id'],old,value)
    return result
