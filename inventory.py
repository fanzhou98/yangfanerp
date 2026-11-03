import erp_access
"""Daily stock, isolated customer returns, return credits and internal processing.

Quantities in baskets/packs and measured kilograms are separate. Customer returns
can be released to sale or transferred to a linked processing batch after inspection.
All mutations run in the caller's transaction.
"""
import billing
import trade
import finished_goods
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, timedelta
import hashlib, json, secrets, sqlite3


def dump(value): return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def number(value,label,positive=False,integer=False,maximum='100000000'):
    try:
        if isinstance(value,bool):raise ValueError()
        result=Decimal(str(value))
        if not result.is_finite() or result<0 or result>Decimal(maximum) or result.as_tuple().exponent < -3 or positive and result==0 or integer and result!=result.to_integral():raise ValueError()
        return result
    except (ValueError,TypeError,InvalidOperation):raise ValueError(label+'须为有效'+('正' if positive else '非负')+('整数' if integer else '数，最多3位小数'))
def stock_count(value,label,unit,fractional):
    result=number(value,label,integer=False)
    if fractional or result==result.to_integral():return result
    if unit=='筐' and (result*2)==(result*2).to_integral():return result
    raise ValueError(label+'须为整数'+('或半筐（0.5）' if unit=='筐' else ''))
def s(value):return format(Decimal(value).normalize(),'f')
def text(value,label,limit=500,required=True):
    if not isinstance(value,str) or len(value)>limit or required and not value.strip():raise ValueError('请填写有效的'+label)
    return value.strip()
def day(value):
    try:
        if date.fromisoformat(value).isoformat()!=value:raise ValueError()
    except (ValueError,TypeError):raise ValueError('请选择有效业务日期')
    return value

def rows(c,table):return [json.loads(r[0]) for r in c.execute('SELECT payload FROM '+table)]
def get(c,table,key,field='id'):
    row=c.execute('SELECT payload FROM '+table+' WHERE '+field+'=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None
def put(c,table,value,key='id'):
    c.execute('INSERT INTO '+table+'('+key+',payload) VALUES(?,?) ON CONFLICT('+key+') DO UPDATE SET payload=excluded.payload',(value[key],dump(value)))
def revision(c):
    r=c.execute("SELECT value FROM meta WHERE key='inventory_revision'").fetchone()
    return int(r[0]) if r else 0

def bump(c):
    value=revision(c)+1
    c.execute("INSERT INTO meta VALUES('inventory_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(value),))
    return value

PROCESSING_RULES_KEY='processing_rules'
DEFAULT_PROCESSING_RULES=(
    {'source_product_id':'P004','output_product_id':'P005'},
    {'source_product_id':'P003','output_product_id':'P006'},
    {'source_product_id':'P003','output_product_id':'P007'},
    {'source_product_id':'P008','output_product_id':'P006'},
    {'source_product_id':'P008','output_product_id':'P007'},
)

def processing_rules(c):
    row=c.execute("SELECT value FROM meta WHERE key='processing_rules'").fetchone();rules=json.loads(row[0]).get('rules',[]) if row else list(DEFAULT_PROCESSING_RULES)
    products={r['id'] for r in c.execute('SELECT id FROM products')}
    return [{'source_product_id':r.get('source_product_id',''),'output_product_id':r.get('output_product_id','')} for r in rules if r.get('source_product_id') in products and r.get('output_product_id') in products]

def save_processing_rules(c,body,role,now,audit):
    erp_access.require_role(role,'production.settings')
    raw=body.get('rules')
    if not isinstance(raw,list) or not 1<=len(raw)<=100:raise ValueError('请填写1至100条转加工规则')
    products={r['id']:r['name'] for r in c.execute('SELECT id,name FROM products')};seen=set();rules=[]
    for row in raw:
        if not isinstance(row,dict):raise ValueError('转加工规则格式无效')
        source=row.get('source_product_id');output=row.get('output_product_id')
        if source not in products or output not in products:raise ValueError('转加工规则中的产品不存在，请重新选择')
        if source==output:raise ValueError('来源产品和产出产品不能相同')
        key=(source,output)
        if key in seen:raise ValueError('同一来源和产出规则重复')
        seen.add(key);rules.append({'source_product_id':source,'output_product_id':output})
    old=c.execute("SELECT value FROM meta WHERE key='processing_rules'").fetchone();version=json.loads(old[0]).get('version',0)+1 if old else 1
    record={'version':version,'rules':rules,'updated_at':now()}
    c.execute("INSERT INTO meta VALUES('processing_rules',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dump(record),))
    audit(c,role,'维护厂内转加工规则','processing_rules',json.loads(old[0]) if old else None,record)
    return record

def expect_revision(c,body):
    if type(body.get('inventory_revision')) is not int or body['inventory_revision']!=revision(c):raise ValueError('库存、生产或退货已有变化，请同步最新数据后重新核对')
def closed(c,when):
    record=get(c,'stock_closings',when,'business_date')
    if record and record['state']=='closed':
        import order_corrections
        return order_corrections.restated_closing(c,record)
    return None

def open_day(c,when):
    locked=[r['business_date'] for r in rows(c,'stock_closings') if r['state']=='closed' and r['business_date']>=when]
    if locked:raise ValueError(when+'已在'+max(locked)+'日结范围内，不能补改库存数量；请在当前未结业务日登记或核查日结')
def expected(record,body,label):
    if not record:raise ValueError(label+'不存在')
    if type(body.get('version')) is not int or body['version']!=record['version']:raise ValueError(label+'已被其他页面修改，请重新打开核对')
def cash(value,label='退货扣款金额',allow_zero=False):
    amount=number(value,label,positive=not allow_zero)
    if amount.as_tuple().exponent < -2:raise ValueError(label+'最多2位小数')
    return int((amount*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def remaining_return(r,when='9999-12-31'):
    if r.get('receipt_mode')=='merchant_disposed':return Decimal(0),Decimal(0)
    disposal=[d for d in r.get('disposals',[]) if not d.get('voided') and d['business_date']<=when]
    return (Decimal(r['qty'])-sum((Decimal(d['qty']) for d in disposal),Decimal(0)),Decimal(r['net_kg'])-sum((Decimal(d['net_kg']) for d in disposal),Decimal(0)))
def restocked(c,when,pid):
    return sum((Decimal(d['stock_qty']) for r in rows(c,'sales_returns') if r['product_id']==pid and not r.get('voided') for d in r.get('disposals',[]) if not d.get('voided') and d['kind']=='restock' and d['business_date']==when),Decimal(0))

def wallet(r):
    finance=r.get('finance') or {}
    if finance.get('state')!='posted':return 0
    return finance['amount_cents']-sum(a['amount_cents'] for a in finance.get('allocations',[]))-sum(a['amount_cents'] for a in finance.get('refunds',[]) if not a.get('voided'))

def balance(o):return o['total_cents']-o.get('return_credit_cents',0)-o['paid_cents']-o.get('discount_cents',0)-o.get('rounding_cents',0)
def customer_wallet(c,cid):return sum(wallet(r) for r in rows(c,'sales_returns') if r['customer_id']==cid and not r.get('voided'))

def allocation_locked(o,l):
    return o['state'] not in ('draft','dispatched') or bool(o.get('paid_cents') or o.get('return_credit_cents') or o.get('weight_confirmation') or l.get('driver') or l.get('customer') or l.get('package_net_kg') or l.get('factory_net_kg') or l.get('package_customer_net_kg'))

def proposed_allocations(plan,orders):
    current={(a['order_id'],a['product_id']):a for a in plan.get('allocations',[])}
    result=[]
    for o in orders:
        for l in o['lines']:
            a=current.get((o['id'],l['product_id']))
            locked=allocation_locked(o,l)
            ordered=l.get('ordered_qty',l.get('actual_qty') or '0')
            if locked:qty=l['actual_qty'];mode='locked'
            elif not a and l.get('not_shipped'):qty='0';mode='manual'
            elif not a or a.get('mode')=='auto':qty=ordered;mode='auto'
            else:qty=s(Decimal(a['qty']));mode='manual'
            result.append({'order_id':o['id'],'product_id':l['product_id'],'qty':qty,'ordered_qty':ordered,'mode':mode})
    return result

def validate_dispatch(c,new,old=None):
    import order_corrections
    plan=order_corrections.effective_plan(c,get(c,'warehouse_plans',new['business_date'],'business_date') or {})
    allocations={(a['order_id'],a['product_id']):a for a in plan.get('allocations',[])}
    products={p['product_id']:p for p in stock(c,new['business_date'])['products']}
    for l in new['lines']:
        qty=Decimal(l['actual_qty'])
        prior=next((x for x in (old or {}).get('lines',[]) if x['product_id']==l['product_id']),None)
        if old and old['business_date']==new['business_date'] and prior and qty<=Decimal(prior['actual_qty']):continue
        if qty<=0:continue
        a=allocations.get((new['id'],l['product_id']))
        if plan.get('allocation_state','confirmed' if plan else 'draft')!='confirmed' or not a:raise ValueError(l['product_name']+'请先填写当日库存，并在发货分配页确认拟实发数量')
        if products[l['product_id']]['supply_qty'] is None:raise ValueError(l['product_name']+'当日库存尚未确认，不能填写实发')
        if qty>Decimal(a['qty']):raise ValueError(l['product_name']+'实发超过已确认分配，请回发货分配页调整并确认')

def stock(c,when,products=None,*,_sources=None):
    """Book movement for the whole day; allocation is a reservation, not shipment."""
    products=products or [dict(p) for p in c.execute('SELECT * FROM products ORDER BY id')]
    import order_corrections
    if _sources is None:
        plan=order_corrections.effective_plan(c,get(c,'warehouse_plans',when,'business_date') or {})
        previous=closed(c,(date.fromisoformat(when)-timedelta(days=1)).isoformat())
        orders=[json.loads(r[0]) for r in c.execute("SELECT payload FROM orders WHERE json_extract(payload,'$.business_date')=?",(when,))]
        returns=[r for r in rows(c,'sales_returns') if r.get('receipt_mode','physical')=='physical' and not r.get('voided') and r['received_date']<=when]
        processing=[json.loads(r[0]) for r in c.execute("SELECT payload FROM processing_batches WHERE json_extract(payload,'$.business_date')=? AND COALESCE(json_extract(payload,'$.voided'),0)=0",(when,))]
    else:
        plan=_sources['plan'];previous=_sources['previous_closing'];orders=_sources['orders'];returns=_sources['returns'];processing=_sources['processing']
    allocations={(a['order_id'],a['product_id']):Decimal(a['qty']) for a in plan.get('allocations',[])}
    proposed={(a['order_id'],a['product_id']):Decimal(a['qty']) for a in proposed_allocations(plan,orders)}
    confirmed=plan.get('allocation_state','confirmed' if plan else 'draft')=='confirmed'
    output=[]
    for p in products:
        pid=p['id'];entry=next((r for r in plan.get('stock',[]) if r['product_id']==pid),{})
        prev=next((r for r in (previous or {}).get('products',[]) if r['product_id']==pid),None)
        opening=entry.get('existing_qty','')
        # A saved plan freezes its opening source; a new day can suggest yesterday.
        if not plan and prev:opening=prev['counted_qty']
        known=opening!='';production=Decimal(entry.get('produced_qty') or '0');loss=Decimal(entry.get('loss_qty') or '0')
        incoming=sum((Decimal(o['qty']) for batch in processing for o in batch['outputs'] if o['product_id']==pid),Decimal(0))
        consumed=Decimal(0)
        for batch in processing:
            if batch['product_id']!=pid:continue
            if batch.get('deduct_stock'):
                consumed+=Decimal(batch.get('input_kg') or '0') if p['unit']=='公斤' and batch.get('process_mode')=='processing' else Decimal(batch.get('input_qty') or '0')
            else:
                consumed+=Decimal(batch.get('input_qty') or '0')
        try:
            import curing
            c_qty,c_kg=curing.consumed(c,when,pid)
            consumed+=c_kg if p['unit']=='公斤' else c_qty
        except ImportError:
            pass
        except sqlite3.OperationalError as error:
            if 'no such table: curing_records' not in str(error):
                raise
        shipped=Decimal(0);reserved=Decimal(0);allocated=Decimal(0);demand=Decimal(0);planned=Decimal(0)
        for order in orders:
            for line in order['lines']:
                if line['product_id']!=pid:continue
                actual=Decimal(line['actual_qty']);allocation=allocations.get((order['id'],pid),Decimal(0))
                shipped+=actual;allocated+=allocation;demand+=Decimal(line.get('ordered_qty',line.get('actual_qty') or '0'));planned+=proposed[(order['id'],pid)]
                if confirmed:reserved+=max(allocation-actual,Decimal(0))
        purchased=finished_goods.supplied(c,when,pid) if _sources is None else _sources['purchased'].get(pid,Decimal(0))
        released=restocked(c,when,pid) if _sources is None else _sources['restocked'].get(pid,Decimal(0))
        supply=Decimal(opening)+production+incoming+purchased+released-consumed-loss if known else None
        book=supply-shipped if known else None
        holds=[(r,remaining_return(r,when)) for r in returns if r['product_id']==pid]
        qty=sum((v[0] for r,v in holds),Decimal(0));kg=sum((v[1] for r,v in holds),Decimal(0))
        received_qty=sum((Decimal(r['qty']) for r in returns if r['product_id']==pid and r['received_date']==when),Decimal(0))
        received_kg=sum((Decimal(r['net_kg']) for r in returns if r['product_id']==pid and r['received_date']==when),Decimal(0))
        output.append({'product_id':pid,'product_name':p['name'],'unit':p['unit'],'opening_qty':opening,'production_qty':s(production),'purchased_qty':s(purchased),'return_restock_qty':s(released),'processing_output_qty':s(incoming),'processing_input_qty':s(consumed),'loss_qty':s(loss),
            'ordered_qty':s(demand),'proposed_qty':s(planned),'shortage_qty':None if supply is None else s(max(demand-supply,Decimal(0))),'adjustment_qty':None if supply is None else s(max(planned-supply,Decimal(0))),
            'supply_qty':None if supply is None else s(supply),'shipped_qty':s(shipped),'allocated_qty':s(allocated),'reserved_qty':s(reserved),'book_qty':None if book is None else s(book),
            'free_qty':None if book is None else s(book-reserved),'quarantine_qty':s(qty),'quarantine_kg':s(kg),'returned_qty':s(received_qty),'returned_kg':s(received_kg),
            'counted_qty':entry.get('counted_qty',''),'variance_reason':entry.get('variance_reason','')})
    return {'allocation_state':plan.get('allocation_state','confirmed' if plan else 'draft'),'business_date':when,'products':output,'previous_closing':previous,'closing':closed(c,when) if _sources is None else _sources['closing'],'inventory_revision':revision(c)}

def validate_book(c,when,check_reservations=False):
    for product in stock(c,when)['products']:
        value=product['free_qty'] if check_reservations else product['book_qty']
        if value is not None and Decimal(value)<0:raise ValueError(product['product_name']+('实发加待发预留超过可供库存' if check_reservations else '库存不足，不能发货或转加工；请核对昨日结转、当天生产和实发数量'))

def validate_order(c,new,old):
    if not old and closed(c,new['business_date']):raise ValueError(new['business_date']+'已日结，不能补录订单；请在当前未结业务日登记')
    projection=lambda o:sorted((o['business_date'],l['product_id'],l['actual_qty']) for l in o['lines'] if Decimal(l['actual_qty'])>0)
    if old and projection(new)!=projection(old):
        for when in {old['business_date'],new['business_date']}:open_day(c,when)
    elif not old and any(Decimal(l['actual_qty'])>0 for l in new['lines']):open_day(c,new['business_date'])
    for r in rows(c,'sales_returns'):
        if r.get('voided') or r.get('order_id')!=new['id']:continue
        if new['customer_id']!=r['customer_id'] or new['business_date']>r['received_date']:raise ValueError('已有退货关联，不能更换原单客户或将送货日期改到退货之后')
        line=next((l for l in new['lines'] if l['product_id']==r['product_id']),None)
        quantity=sum((Decimal(x['qty']) for x in rows(c,'sales_returns') if not x.get('voided') and x.get('order_id')==new['id'] and x['product_id']==r['product_id']),Decimal(0))
        if not line or Decimal(line['actual_qty'])<quantity:raise ValueError('原单已有退货，修改后的实发量不能小于累计退货量')
        total_kg=sum((Decimal(x['net_kg']) for x in rows(c,'sales_returns') if not x.get('voided') and x.get('order_id')==new['id'] and x['product_id']==r['product_id']),Decimal(0))
        if line.get('bill_qty') is not None and billing.is_kg(line) and Decimal(line['bill_qty'])<total_kg:raise ValueError('原单计价重量不能小于累计退货净重')
        if r.get('source_price') is not None and Decimal(line['price'])!=Decimal(r['source_price']):raise ValueError('原单已有退货关联，不能改写原销售价格')

def allocate_credits(c,now):
    """Consume each posted return credit once, without changing sale or cash amounts."""
    credits=sorted((r for r in rows(c,'sales_returns') if wallet(r)>0 and not r.get('voided')),key=lambda r:(r['finance']['account_date'],r['id']))
    closed={json.loads(r[0])['month'] for r in c.execute("SELECT payload FROM resource_periods WHERE json_extract(payload,'$.state')='closed'")}
    orders=sorted((o for o in rows(c,'orders') if o['state']=='reviewed' and balance(o)>0 and o['business_date'][:7] not in closed),key=lambda o:(o['business_date'],o['id']))
    changed=[]
    for r in credits:
        allocated=False
        for o in orders:
            if o['customer_id']!=r['customer_id'] or balance(o)<=0 or wallet(r)<=0:continue
            amount=min(wallet(r),balance(o));r['finance'].setdefault('allocations',[]).append({'order_id':o['id'],'amount_cents':amount,'at':now()})
            allocated=True
            o['return_credit_cents']=o.get('return_credit_cents',0)+amount;o['version']+=1;o['updated_at']=now();put(c,'orders',o);changed.append(o['id'])
        if allocated:r['version']+=1;r['updated_at']=now();put(c,'sales_returns',r)
    return sorted(set(changed))

class Operations:
    def __init__(self,c,now,audit):self.c=c;self.now=now;self.audit=audit
    def record(self,table,value,role,action,before=None,key='id',inventory=True):
        put(self.c,table,value,key);self.audit(self.c,role,action,value[key],before,value)
        if inventory:bump(self.c)
        return value
    def create_return(self,body,role):
        erp_access.require_role(role,'returns.register')
        when=day(body.get('received_date'));receipt_mode=body.get('receipt_mode','physical')
        if receipt_mode not in ('physical','merchant_disposed'):raise ValueError('请选择实物退回或商户自行处置')
        cid=body.get('customer_id');pid=body.get('product_id');oid=body.get('order_id','')
        customer=self.c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone();product=self.c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
        if not customer or not product:raise ValueError('请选择客户和退货产品')
        quantity=number(body.get('qty','0'),'退货数量');kg=number(body.get('net_kg','0'),'退货实称净重')
        if trade.product_billing(self.c,product)=='公斤' and kg==0:raise ValueError('公斤计价的退货请先称重并填写净重，不能只凭筐数扣款')
        if quantity==0 and kg==0:raise ValueError('请填写退货数量或实称净重')
        if body.get('received_checked') is not True:raise ValueError('请确认退回实物或商户处置数量的凭据')
        condition=body.get('condition')
        if condition not in ('broken','spoiled','other'):raise ValueError('请选择退货情况')
        source_labels={'sale_order':'原送货单','delivery_record':'订货手机 / 送货记录','customer_report':'客户反馈并核对','merchant_confirmed':'商户处置确认','other':'其他来源'}
        reason_labels={'damaged':'破损 / 碎品','quality':'品质异议','spoiled':'变质','excess':'余货 / 滞销协商','weight':'重量 / 数量异议','other':'其他原因'}
        source_code=body.get('source_code','');reason_code=body.get('reason_code','')
        if source_code and source_code not in source_labels or reason_code and reason_code not in reason_labels:raise ValueError('来源或退货原因选项无效')
        source_detail=text(body.get('source_detail',''),'来源补充说明',500,source_code=='other')
        reason_detail=text(body.get('reason_detail',''),'原因补充说明',500,reason_code=='other')
        entry={'receipt_mode':receipt_mode,'source_code':source_code,'reason_code':reason_code,'source_detail':source_detail,'reason_detail':reason_detail,'received_date':when,'customer_id':cid,'product_id':pid,'order_id':oid,'qty':s(quantity),'net_kg':s(kg),'condition':condition,
            'reason':text((reason_labels[reason_code]+('：'+reason_detail if reason_detail else '')) if reason_code else body.get('reason'),'退货原因'),'source_note':text((source_labels[source_code]+('：'+source_detail if source_detail else '')) if source_code else body.get('source_note',''),'原单 / 批次说明',500,not oid)}
        request_key=text(body.get('request_key'),'退货请求编号',80)
        fingerprint=hashlib.sha256(dump(entry).encode()).hexdigest()
        for r in rows(self.c,'sales_returns'):
            if r.get('request_key')==request_key:
                if r.get('fingerprint')!=fingerprint:raise ValueError('退货请求编号重复，请重新打开登记窗口')
                return r
        if receipt_mode=='physical':open_day(self.c,when)
        original=get(self.c,'orders',oid) if oid else None
        rule=self.c.execute('SELECT price FROM rules WHERE customer_id=? AND product_id=?',(cid,pid)).fetchone()
        reference_price=rule['price'] if rule else product['price']
        price=None;line=None
        if oid:
            if original and body.get('expected_order_version') is not None and body['expected_order_version']!=original['version']:raise ValueError('原送货单已变化，请重新选择原单并核对数量与原价')
            if original and body.get('source_date') and body['source_date']!=original['business_date']:raise ValueError('原送货日期与所选原单不符，请重新选择')
            if not original or original['customer_id']!=cid or original['business_date']>when:raise ValueError('原单客户或送货日期与退货不符')
            line=next((l for l in original['lines'] if l['product_id']==pid),None)
            if not line or Decimal(line['actual_qty'])<=0:raise ValueError('原单没有此产品的实发记录')
            existing=[r for r in rows(self.c,'sales_returns') if r.get('order_id')==oid and r['product_id']==pid and not r.get('voided')]
            if sum((Decimal(r['qty']) for r in existing),Decimal(0))+quantity>Decimal(line['actual_qty']):raise ValueError('累计退货折合数量超过原单实发数量')
            if billing.is_kg(line) and line.get('bill_qty') is not None and sum((Decimal(r['net_kg']) for r in existing),Decimal(0))+kg>Decimal(line['bill_qty']):raise ValueError('累计退货净重超过原单已确认计价重量')
            price=line['price']
        return_unit=line['unit'] if line else product['unit']
        if not next((u['fractional'] for u in trade.units(self.c) if u['id']==return_unit),False) and quantity!=quantity.to_integral():raise ValueError('退货数量须按原单单位填写整数')
        bill_unit=line.get('billing_unit',trade.product_billing(self.c,product)) if line else trade.product_billing(self.c,product)
        if bill_unit=='公斤' and line and not billing.is_kg(line):
            price=s(Decimal(price)/Decimal(line.get('standard_kg') or product['standard_kg']))
        record={'id':'RT-'+secrets.token_hex(6).upper(),'version':1,**entry,'unit':line['unit'] if line else product['unit'],'customer_name':customer['name'],'product_name':line['product_name'] if line else product['name'],
            'billing_unit':bill_unit,'source_price':price,'reference_price':reference_price,'standard_kg':line.get('standard_kg') if line else product['standard_kg'],'source_order_version':original['version'] if original else None,'request_key':request_key,'fingerprint':fingerprint,'created_at':self.now(),'registered_by':role,'voided':False,'disposals':[],'finance':None}
        return self.record('sales_returns',record,role,'登记客户退货并隔离' if receipt_mode=='physical' else '登记商户自行处置及待协商扣款',inventory=receipt_mode=='physical')
    def return_action(self,body,role):
        r=get(self.c,'sales_returns',body.get('id'));expected(r,body,'退货单');before=json.loads(dump(r));act=body.get('action')
        if r.get('voided'):raise ValueError('退货单已作废')
        inventory=False
        if act=='void':
            erp_access.require_role(role,'returns.register')
            fin=r.get('finance') or {}
            if (fin and fin.get('state')!='reversed') or r['disposals']:raise ValueError('已有扣款或处置的退货不能作废，请保留原始记录')
            
            if r.get('receipt_mode','physical')=='physical':open_day(self.c,r['received_date'])
            __import__('resources_costs').open_period(self.c,r['received_date'])
            r['voided']=True;r['void_reason']=text(body.get('reason'),'作废原因');inventory=r.get('receipt_mode','physical')=='physical';label='作废未处理退货'
        elif act=='reverse-credit':
            # 受控冲销退货抵扣：保留退货单与核定金额，只回退已抵到账单的金额，原因留痕。
            erp_access.require_role(role,'returns.review')
            fin=r.get('finance') or {}
            if fin.get('state')!='posted':raise ValueError('只有已复核入账的退货扣款可以冲销')
            if fin.get('refunds'):raise ValueError('该退货已有实际退款，请先按退款流程核对，不能直接冲销')
            reason=text(body.get('reason'),'冲销原因',500)
            reversed_rows=[]
            for a in fin.get('allocations',[]):
                o=get(self.c,'orders',a['order_id'])
                if not o:continue
                if int(o.get('return_credit_cents',0))<int(a['amount_cents']):raise ValueError('原单抵扣已变化，请刷新后重新核对')
                before_order=json.loads(dump(o))
                o['return_credit_cents']=int(o.get('return_credit_cents',0))-int(a['amount_cents'])
                o['version']=int(o['version'])+1;o['updated_at']=self.now()
                self.record('orders',o,role,'冲销退货抵扣',before_order,inventory=False)
                reversed_rows.append({'order_id':o['id'],'amount_cents':int(a['amount_cents'])})
            r['finance']={**fin,'state':'reversed','reversed_at':self.now(),'reversed_by':role,'reverse_reason':reason,
                          'reversed_allocations':list(fin.get('allocations',[])),'allocations':[]}
            label='冲销退货抵扣'
            self.audit(self.c,role,'冲销退货抵扣',r['id'],None,{'return':r['id'],'reason':reason,'orders':reversed_rows})
        elif act=='reverse-refund':
            # 受控冲销实际退款：保留原退款凭据与金额，只标记作废并恢复待抵/待退余额。
            erp_access.require_role(role,'returns.refund')
            fin=r.get('finance') or {}
            if fin.get('state')!='posted':raise ValueError('只有已复核入账的退货扣款可以冲销退款')
            refund=next((x for x in fin.get('refunds',[]) if x.get('id')==body.get('refund_id')),None)
            if not refund:raise ValueError('退款记录不存在，请刷新后重试')
            if refund.get('voided'):raise ValueError('该退款已冲销')
            reason=text(body.get('reason'),'冲销原因',500)
            open_day(self.c,refund['refund_date']);__import__('resources_costs').open_period(self.c,refund['refund_date'])
            refund.update(voided=True,void_reason=reason,voided_at=self.now(),voided_by=role)
            label='冲销退货退款'
        elif act=='void-dispose':
            erp_access.require_role(role,'returns.register')
            disposal=next((x for x in r.get('disposals',[]) if x.get('id')==body.get('disposal_id')),None)
            if not disposal:raise ValueError('处置记录不存在，请刷新后重试')
            if disposal.get('voided'):raise ValueError('该处置已撤销')
            reason=text(body.get('reason'),'撤销原因',500)
            open_day(self.c,disposal['business_date']);__import__('resources_costs').open_period(self.c,disposal['business_date'])
            batch=None
            if disposal.get('processing_batch_id'):
                batch=get(self.c,'processing_batches',disposal['processing_batch_id'])
                if batch.get('state')!='pending' or batch.get('outputs'):raise ValueError('该处置已转加工并登记产出，不能撤销')
            disposal.update(voided=True,void_reason=reason,voided_at=self.now(),voided_by=role)
            if batch:
                self.c.execute('DELETE FROM processing_batches WHERE id=?',(batch['id'],))
                self.audit(self.c,role,'撤销退货转加工待处理批次',batch['id'],batch,None)
            inventory=True;label='撤销退货处置'
        elif act=='dispose':
            if r.get('receipt_mode')=='merchant_disposed':raise ValueError('此记录由商户自行处置，不能再次登记本厂库存出库')
            erp_access.require_role(role,'returns.register')
            when=day(body.get('business_date'));open_day(self.c,when)
            if when<r['received_date']:raise ValueError('处置日期不能早于退货入库日期')
            kind=body.get('kind')
            if kind not in ('destroy','nonfood','restock','reprocess'):raise ValueError('请选择继续发货、转加工、销毁或非食用处理')
            qty=number(body.get('qty','0'),'处置数量',integer=r.get('unit') in ('筐','包','盒','个'));kg=number(body.get('net_kg','0'),'处置净重')
            remaining=remaining_return(r)
            if qty+kg==0 or qty>remaining[0] or kg>remaining[1]:raise ValueError('处置量须大于0且不能超过隔离库存')
            if any(not d.get('voided') and d['business_date']>when for d in r['disposals']):raise ValueError('请按日期顺序登记处置，避免改变历史隔离库存')
            disposal={'id':'RD-'+secrets.token_hex(6).upper(),'business_date':when,'kind':kind,'qty':s(qty),'net_kg':s(kg),'note':text(body.get('note'),'处理去向及凭据'),'handler':text(body.get('handler'),'处理负责人',80),'at':self.now()}
            if kind in ('restock','reprocess'):
                if body.get('inspection_checked') is not True:raise ValueError('请确认本批退货经检验可用于所选用途')
                disposal['inspection_note']=text(body.get('inspection_note'),'检验结论及批次依据')
                disposal['inspection_checked']=True
                expiry=body.get('expiry_date','')
                if expiry and day(expiry)<when:raise ValueError('处理日期超过所填有效期，请核对用途和日期')
                disposal['expiry_date']=expiry
            if kind=='restock':
                erp_access.require_role(role,'inventory.stock')
                product=self.c.execute('SELECT unit FROM products WHERE id=?',(r['product_id'],)).fetchone()
                stock_qty=number(body.get('stock_qty'),'可发库存入库数量',positive=True,integer=not next((u['fractional'] for u in trade.units(self.c) if u['id']==product['unit']),False))
                if qty==0 and r['unit']==product['unit'] and Decimal(r['qty'])>0:raise ValueError('请填写本次从待处理库存转出的数量')
                if r['unit']==product['unit'] and Decimal(r['qty'])>0 and qty!=stock_qty:raise ValueError('原单位相同时，可发入库数量须与本次处理数量一致')
                if kg==0 and Decimal(r['net_kg'])>0:raise ValueError('请填写本次继续发货的实称净重')
                if product['unit']=='公斤' and Decimal(r['qty'])==0 and stock_qty!=kg:raise ValueError('散货按公斤回可发库存时，入库数量须与本次实称净重一致')
                disposal.update(stock_qty=s(stock_qty),stock_unit=product['unit'])
            if kind=='reprocess':
                erp_access.require_role(role,'inventory.process')
                if kg<=0:raise ValueError('转加工须填写实际投入净重')
                batch={'id':'PR-'+secrets.token_hex(6).upper(),'version':1,'business_date':when,'transfer_date':when,'product_id':r['product_id'],'input_qty':'0','input_kg':s(kg),'source_return_qty':s(qty),'source_return_unit':r['unit'],'process_mode':'processing','origin':'customer_return','source_return_id':r['id'],'source_disposal_id':disposal['id'],'state':'pending','outputs':[],'handler':disposal['handler'],'inspection_note':disposal['inspection_note'],'source_lot':r['id'],'at':self.now(),'role':role}
                disposal.update(processing_batch_id=batch['id'],processing_completed=False)
                self.record('processing_batches',batch,role,'退货转入待加工批次')
            r['disposals'].append(disposal);inventory=True;label='登记客户退货处理去向'

        elif act=='account':
            erp_access.require_role(role,'returns.account')
            if r.get('finance'):raise ValueError('此退货已核定扣款，不能重复减账')
            when=day(body.get('account_date'))
            if when<r['received_date']:raise ValueError('扣款日期不能早于退货入库日期')
            qty=number(body.get('account_qty'),'会计核定退货公斤数')
            price=number(body.get('price'),'原销售单价',positive=True,maximum='100000')
            if body.get('price_checked') is not True:raise ValueError('请明确核对原销售单价及核定退货数量')
            if r['source_price'] is not None and price!=Decimal(r['source_price']):raise ValueError('关联原单退货须使用原销售单价')
            if billing.is_kg(r):limit=Decimal(r['net_kg'])
            else:limit=Decimal(r['qty']) if Decimal(r['qty'])>0 else Decimal(r['net_kg'])/Decimal(r.get('standard_kg') or '1')
            if qty>limit:raise ValueError('会计核定退货数量不能超过库管确认的退货公斤数，请先核对实物记录')
            amount=int((qty*price*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP));oid=r.get('order_id');original=get(self.c,'orders',oid) if oid else None
            if original and original['total_cents']>0:
                others=sum((x['finance']['amount_cents'] for x in rows(self.c,'sales_returns') if x['id']!=r['id'] and x.get('order_id')==oid and x.get('finance') and not x.get('voided')),0)
                if others+amount>original['total_cents']:raise ValueError('累计退货扣款超过原单确认销售金额，请核对凭据')
            r['finance']={'state':'pending_review','amount_cents':amount,'account_qty':s(qty),'original_price':s(price),'billing_unit':r.get('billing_unit','公斤' if billing.is_kg(r) else r['unit']),'account_weight_kg':s(qty) if billing.is_kg(r) else None,'account_date':when,'note':text(body.get('note'),'扣款依据'),'accountant':role,'at':self.now(),'allocations':[],'refunds':[]};label='会计核定退货扣款，提交复核'
        elif act=='retract':
            erp_access.require_role(role,'returns.retract')
            if not r.get('finance') or r['finance']['state']!='pending_review':raise ValueError('仅未复核的退货扣款可退回核定')
            r.setdefault('finance_history',[]).append({**r['finance'],'retracted_at':self.now(),'retracted_by':role,'reason':text(body.get('reason'),'退回核定原因')})
            r['finance']=None;label='退回未复核退货扣款，待会计重新核定'
        elif act=='review':
            erp_access.require_role(role,'returns.review')
            if not r.get('finance') or r['finance']['state']!='pending_review':raise ValueError('此退货没有待复核扣款')
            if body.get('evidence_checked') is not True:raise ValueError('请核对库管退货记录和会计扣款依据')
            r['finance'].update(state='posted',reviewed_at=self.now(),reviewer=role);label='复核退货扣款，抵减客户应收'
        elif act=='refund':
            erp_access.require_role(role,'returns.refund')
            if body.get('evidence_checked') is not True:raise ValueError('请确认退款已实际支付并核对凭据')
            amount=cash(body.get('amount'),'实际退款金额')
            if amount>wallet(r):raise ValueError('退款不能超过此退货尚未抵账的余额')
            when=day(body.get('refund_date'))
            if when<r['finance']['account_date']:raise ValueError('退款日期不能早于退货扣款日期')
            if when>date.today().isoformat():raise ValueError('退款日期不能晚于今天；未实际支付的退款请勿登记')
            open_day(self.c,when);__import__('resources_costs').open_period(self.c,when)
            r['finance']['refunds'].append({'account_id':__import__('funds').validate_account(self.c,body.get('account_id')),'id':'RF-'+secrets.token_hex(5).upper(),'amount_cents':amount,'refund_date':when,'method':text(body.get('method'),'退款方式',80),'note':text(body.get('note'),'退款凭据'),'at':self.now(),'role':role});label='登记退货实际退款'
        else:raise ValueError('未知退货操作')
        r['version']+=1;r['updated_at']=self.now();self.record('sales_returns',r,role,label,before,inventory=inventory)
        if act=='review':
            affected=allocate_credits(self.c,self.now)
            self.audit(self.c,role,'退货抵扣分配到未收账单',r['id'],None,{'orders':affected})
            return get(self.c,'sales_returns',r['id'])
        return r
    def _process_entry(self,body,role):
        when=day(body.get('business_date'));pid=body.get('product_id');product=self.c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
        if not product:raise ValueError('请选择厂内来源产品')
        if body.get('origin','internal')!='internal':raise ValueError('客户退货转加工请从退货台账选择原批次，以核对剩余数量')
        kg=number(body.get('input_kg'),'实际投入净重',positive=True)
        outputs=body.get('outputs')
        if not isinstance(outputs,list) or not 1<=len(outputs)<=20:raise ValueError('请记录实际产出的产品数量')
        allowed={(r['output_product_id'],r['source_product_id']) for r in processing_rules(self.c)}
        result=[];seen=set()
        for row in outputs:
            if not isinstance(row,dict):raise ValueError('实际产出格式无效')
            out=self.c.execute('SELECT * FROM products WHERE id=?',(row.get('product_id'),)).fetchone()
            if not out or out['id'] in seen:raise ValueError('转加工产出产品不存在或重复')
            if (out['id'],pid) not in allowed:raise ValueError(out['name']+'不能由'+product['name']+'转加工；请先在“维护规则”中设置允许关系')
            seen.add(out['id']);out_qty=number(row.get('qty'),'实际产出入库数量',positive=True,integer=not next((u['fractional'] for u in trade.units(self.c) if u['id']==out['unit']),False))
            standard=out['standard_kg']
            if out['unit']!='筐' and standard not in (None,''):out_net=s(out_qty*Decimal(standard))
            elif row.get('net_kg') in (None,''):raise ValueError('请填写'+out['name']+'的产出实称净重；筐装成品每筐重量不同，必须按实际称重登记')
            else:out_net=s(number(row['net_kg'],'产出实称净重',positive=True))
            result.append({'product_id':out['id'],'product_name':out['name'],'unit':out['unit'],'qty':s(out_qty),'net_kg':out_net})
        mode=body.get('process_mode','processing')
        if mode not in ('processing','repack'):raise ValueError('转加工类型无效')
        if mode=='repack' and product['unit']!='筐':raise ValueError('筐装转包装请选择按筐发货的来源产品')
        if mode=='processing' and product['unit']!='公斤':
            raw_qty=body.get('input_qty')
            input_qty=number(raw_qty,'投入'+('筐数' if product['unit']=='筐' else '件数'),integer=True) if raw_qty not in (None,'') else Decimal(0)
            if input_qty<0:raise ValueError('投入'+('筐数' if product['unit']=='筐' else '件数')+'不能为负；未按件扣库时留空即可')
        elif mode=='repack':
            input_qty=number(body.get('input_qty'),'转包装来源扣库数量',positive=True,integer=True)
        else:
            input_qty=Decimal(0)
        if mode=='repack' and sum(Decimal(r['net_kg']) for r in result)>kg:raise ValueError('转包装产出净重不能超过实际投入净重')
        return when,{'business_date':when,'product_id':pid,'process_mode':mode,'input_qty':s(input_qty),'input_kg':s(kg),'outputs':result,'deduct_stock':True}

    def _source_deduct(self,entry):
        """本批从来源库存扣减的数量：筐装按筐数，公斤装按投入净重。"""
        product=self.c.execute('SELECT unit FROM products WHERE id=?',(entry['product_id'],)).fetchone()
        unit=product['unit'] if product else '公斤'
        if entry.get('process_mode')=='processing' and unit=='公斤':return Decimal(entry.get('input_kg') or '0')
        return Decimal(entry.get('input_qty') or '0')

    def _check_process_stock(self,when,entry,old=None):
        snapshot=stock(self.c,when)
        need=self._source_deduct(entry)
        if need>0:
            source=next(p for p in snapshot['products'] if p['product_id']==entry['product_id'])
            if source['free_qty'] is None:raise ValueError(source['product_name']+'昨日结转尚未确认，请先补齐库存')
            restored=self._source_deduct(old) if old and old['business_date']==when and old['product_id']==entry['product_id'] else Decimal(0)
            if need>Decimal(source['free_qty'])+restored:raise ValueError(source['product_name']+'可用库存不足，已发货及预留数量不能重复使用')
        for out in entry['outputs']:
            if next(p for p in snapshot['products'] if p['product_id']==out['product_id'])['opening_qty']=='':raise ValueError(out['product_name']+'昨日结转尚未确认，请先补齐库存')

    def process(self,body,role):
        erp_access.require_role(role,'inventory.process')
        when,entry=self._process_entry(body,role)
        key=text(body.get('request_key'),'加工请求编号',80);fingerprint=hashlib.sha256(dump(entry).encode()).hexdigest()
        for batch in rows(self.c,'processing_batches'):
            if batch.get('request_key')==key:
                if batch.get('fingerprint')!=fingerprint:raise ValueError('加工请求编号重复，请重新登记')
                return batch
        expect_revision(self.c,body);open_day(self.c,when);self._check_process_stock(when,entry)
        batch={'id':'PR-'+secrets.token_hex(6).upper(),'version':1,**entry,'origin':'internal','request_key':key,'fingerprint':fingerprint,'at':self.now(),'role':role}
        self.record('processing_batches',batch,role,'登记厂内转加工投入与实际产出');validate_book(self.c,when,True);return batch

    def process_update(self,body,role):
        erp_access.require_role(role,'inventory.process')
        old=get(self.c,'processing_batches',body.get('id'))
        expected(old,body,'转加工记录')
        if old.get('voided'):raise ValueError('该转加工记录已删除，不能修改')
        when,entry=self._process_entry(body,role);old_day=old['business_date']
        if old.get('origin')=='customer_return':
            if entry['product_id']!=old['product_id'] or Decimal(entry['input_kg'])!=Decimal(old['input_kg']) or Decimal(entry['input_qty'])!=0 or entry['process_mode']!='processing':raise ValueError('退货加工须保留原批次投入，不能改来源、投入净重或转包装')
            if when<old['transfer_date']:raise ValueError('实际加工日期不能早于退货转入日期')
            if old.get('state')!='pending':open_day(self.c,old_day)
        else:open_day(self.c,old_day)
        open_day(self.c,when);self._check_process_stock(when,entry,old)
        record={**old,**entry,'version':old['version']+1,'updated_at':self.now(),'fingerprint':hashlib.sha256(dump(entry).encode()).hexdigest()}
        if old.get('origin')=='customer_return':
            record['state']='completed'
            source=get(self.c,'sales_returns',old['source_return_id']);before_source=json.loads(dump(source))
            disposal=next(d for d in source['disposals'] if d.get('id')==old['source_disposal_id'])
            if disposal.get('voided'):raise ValueError('原退货转加工已撤销，请刷新')
            disposal.update(processing_completed=True,processing_date=when)
            source['version']+=1;self.record('sales_returns',source,role,'退货加工完成并关联产出',before_source)
        self.record('processing_batches',record,role,'修改厂内转加工',old)
        validate_book(self.c,old_day,True)
        if when!=old_day:validate_book(self.c,when,True)
        return record

    def process_delete(self,body,role):
        erp_access.require_role(role,'inventory.process')
        old=get(self.c,'processing_batches',body.get('id'))
        expected(old,body,'转加工记录')
        if old.get('voided'):raise ValueError('该转加工记录已删除')
        open_day(self.c,old['business_date'])
        if old.get('origin')=='customer_return':
            open_day(self.c,old['transfer_date'])
            source=get(self.c,'sales_returns',old['source_return_id']);before_source=json.loads(dump(source))
            disposal=next(d for d in source['disposals'] if d.get('id')==old['source_disposal_id'])
            disposal.update(voided=True,void_reason=text(body.get('reason'),'删除原因'),voided_at=self.now())
            source['version']+=1;self.record('sales_returns',source,role,'撤销退货加工并退回待处理库存',before_source)
        record={**old,'voided':True,'void_reason':text(body.get('reason'),'删除原因'),'voided_at':self.now(),'version':old['version']+1}
        self.record('processing_batches',record,role,'删除厂内转加工',old)
        validate_book(self.c,old['business_date'],True);return record

    def close(self,body,role):
        erp_access.require_role(role,'inventory.close')
        when=day(body.get('business_date'));prior=get(self.c,'stock_closings',when,'business_date');version=prior['version'] if prior else 0
        if type(body.get('version')) is not int or body['version']!=version:raise ValueError('此日日结版本已修改，请重新核对')
        if body.get('action')=='reopen':
            if not prior or prior['state']!='closed':raise ValueError('此日尚未日结')
            if any(r['state']=='closed' and r['business_date']>when for r in rows(self.c,'stock_closings')):raise ValueError('已有后续库存日结，不能撤销历史结存；请在当前业务日记录盘点差异')
            next_day=(date.fromisoformat(when)+timedelta(days=1)).isoformat()
            successor=get(self.c,'warehouse_plans',next_day,'business_date')
            if successor and successor.get('opening_source_date')==when:raise ValueError('下一日已引用本日结转，不能撤销；请在当前业务日记录盘点差异')
            record={**prior,'state':'reopened','version':version+1,'reopen_reason':text(body.get('reason'),'撤销日结原因'),'reopened_at':self.now()}
            return self.record('stock_closings',record,role,'撤销库存日结',prior,'business_date')
        if body.get('evidence_checked') is not True:raise ValueError('请核对昨日结转、当天生产、实际发货和盘点数量')
        expect_revision(self.c,body);open_day(self.c,when)
        snapshot=stock(self.c,when);validate_book(self.c,when,True);plan=get(self.c,'warehouse_plans',when,'business_date')
        if not plan or body.get('plan_version')!=plan['version']:raise ValueError('请先保存当天生产、盘点及分配，并重新打开日结')
        if plan.get('allocation_state')=='draft' and any(o['business_date']==when for o in rows(self.c,'orders')):raise ValueError('仍有拟实发未确认，请先在发货分配页确认实发再日结')
        if any(Decimal(p['reserved_qty'])>0 for p in snapshot['products']):raise ValueError('仍有分配量尚未实发，请先核对实际发货或调整分配再日结')
        confirmed={(a['order_id'],a['product_id']):a for a in plan.get('allocations',[])}
        for o in rows(self.c,'orders'):
            if o['business_date']!=when:continue
            for l in o['lines']:
                a=confirmed.get((o['id'],l['product_id']))
                if not a or a['ordered_qty']!=l['ordered_qty'] or Decimal(a['qty'])!=Decimal(l['actual_qty']):raise ValueError('仍有订货或实发未核对，请重新确认发货分配再日结')
        counts=body.get('counts')
        if not isinstance(counts,list) or len(counts)!=len(snapshot['products']):raise ValueError('请逐产品填写日终实盘数量')
        if any(not isinstance(r,dict) or not isinstance(r.get('product_id'),str) for r in counts):raise ValueError('日终盘点格式无效')
        mapped={r['product_id']:r for r in counts}
        if len(mapped)!=len(counts):raise ValueError('日终盘点产品不能重复')
        result=[]
        for p in snapshot['products']:
            entry=mapped.get(p['product_id'])
            if not entry or p['book_qty'] is None:raise ValueError(p['product_name']+'未确认昨日结转或未填日终实盘')
            fractional=next((u['fractional'] for u in trade.units(self.c) if u['id']==p['unit']),False)
            count=stock_count(entry.get('counted_qty'),'日终实盘数量',p['unit'],fractional);variance=count-Decimal(p['book_qty'])
            reason=text(entry.get('reason',''),'盘点差异原因',500,variance!=0)
            result.append({**p,'counted_qty':s(count),'variance_qty':s(variance),'variance_reason':reason})
        record={'business_date':when,'version':version+1,'state':'closed','products':result,'closed_at':self.now(),'role':role,'plan_version':plan['version']}
        return self.record('stock_closings',record,role,'确认库存日结并生成翌日结转',prior,'business_date')
