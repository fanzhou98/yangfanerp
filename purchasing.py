"""Supplier masters and purchase -> receipt -> payable ledgers. Caller owns transaction."""
import hashlib,json,secrets
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
import erp_access
import resources_costs as rc

TABLES=('purchase_orders','purchase_receipts','purchase_payments','purchase_charges')
PERMISSIONS={'category':'suppliers.write','supplier':'suppliers.write','order':'purchases.write','confirm':'purchases.write','close':'purchases.write','receipt':'purchases.receive','payment':'purchases.pay','payment-void':'purchases.pay','charge':'purchases.cost','charge-void':'purchases.cost','charge-payment':'purchases.pay','warehouse':'purchases.write'}
def categories(c):return rc.rows(c,'supplier_categories')
def finished_supplier(c,s):
    return bool(s.get('active') and set(s.get('category_ids',[])) & {r['id'] for r in categories(c) if r['kind']=='finished' and r.get('active')})

def payment_account(c,b):
    import funds
    if any(a.get('active') for a in funds.accounts(c)) and not b.get('account_id'):raise ValueError('请选择本次实际收付款的资金账户')
    return rc.fund_account(c,b)

def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'purchasing')

def fingerprint(b):return hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('_data_epoch','request_key')}).encode()).hexdigest()
def get(c,t,rid):
    r=c.execute('SELECT payload FROM '+t+' WHERE id=?',(rid,)).fetchone()
    if not r:raise ValueError('记录不存在，请同步后核对')
    return json.loads(r[0])
def rounded(q,p):return int((Decimal(q)*Decimal(p)*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
def actual_price(cents,quantity):
    return rc.ds((Decimal(cents)/100/Decimal(quantity)).quantize(Decimal('0.000001'),rounding=ROUND_HALF_UP)) if Decimal(quantity)>0 else None
def projection(c,order_ids=None):
    def selected(table):
        if order_ids is None:return rc.rows(c,table)
        if not order_ids:return []
        field='id' if table=='purchase_orders' else "json_extract(payload,'$.order_id')"
        return [json.loads(r[0]) for r in c.execute('SELECT payload FROM '+table+' WHERE '+field+' IN ('+','.join('?' for _ in order_ids)+') ORDER BY rowid',order_ids)]
    orders=selected('purchase_orders');receipts=selected('purchase_receipts');payments=selected('purchase_payments');charges=selected('purchase_charges')
    allocated={}
    for charge in charges:
        if charge.get('voided'):continue
        for a in charge['allocations']:allocated[a['material_entry_id']]=allocated.get(a['material_entry_id'],0)+a['amount_cents']
    for r in receipts:
        for l in r['lines']:
            l['charges_cents']=allocated.get(l['material_entry_id'],0)
            l['inventory_cost_cents']=l['amount_cents']+l['charges_cents']
            l['actual_unit_price']=actual_price(l['inventory_cost_cents'],l.get('arrival_qty') or l['qty'])
    for o in orders:
        rs=[r for r in receipts if r['order_id']==o['id']];ps=[r for r in payments if r['order_id']==o['id'] and not r.get('charge_id') and not r.get('voided')]
        for line in o['lines']:
            line['received_qty']=rc.ds(sum((Decimal(l['qty']) for r in rs for l in r['lines'] if l['line_id']==line['id']),Decimal(0)))
            line['received_arrival_qty']=rc.ds(sum((Decimal(l.get('arrival_qty') or l['qty']) for r in rs for l in r['lines'] if l['line_id']==line['id']),Decimal(0)))
            line['remaining_qty']=rc.ds(Decimal(line['qty'])-Decimal(line['received_qty']))
            received=[l for r in rs for l in r['lines'] if l['line_id']==line['id']]
            line['received_cents']=sum(l['amount_cents'] for l in received)
            line['charges_cents']=sum(l['charges_cents'] for l in received)
            line['inventory_cost_cents']=line['received_cents']+line['charges_cents']
            line['actual_unit_price']=actual_price(line['inventory_cost_cents'],line['received_arrival_qty'])
        o['received_cents']=sum(r['amount_cents'] for r in rs);o['paid_cents']=sum(p['amount_cents'] for p in ps);o['outstanding_cents']=o['received_cents']-o['paid_cents']
        o['charges_cents']=sum(x['amount_cents'] for x in charges if x['order_id']==o['id'] and not x.get('voided'));o['inventory_cost_cents']=o['received_cents']+o['charges_cents']
        for l in o['lines']:l['warehouse_name']=rc.warehouse_names(c).get(l.get('warehouse_id'),'历史待确认库' if l['material_id']=='RM-SOY' else '公共辅料与包装库')
        o['status']=({'draft':'草稿','cancelled':'已取消','closed':'已关闭余量'}.get(o['state']) or ('全部入库' if all(Decimal(l['remaining_qty'])==0 for l in o['lines']) else '部分入库' if rs else '待入库'))
    for r in receipts:
        r['charges_cents']=sum(x['amount_cents'] for x in charges if x['receipt_id']==r['id'] and not x.get('voided'));r['inventory_cost_cents']=r['amount_cents']+r['charges_cents']
        for l in r['lines']:l['warehouse_name']=rc.warehouse_names(c).get(l.get('warehouse_id'),'历史待确认库' if l['material_id']=='RM-SOY' else '公共辅料与包装库')
    for r in charges:
        r['paid_cents']=sum(x['amount_cents'] for x in payments if x.get('charge_id')==r['id'] and not x.get('voided'));r['outstanding_cents']=0 if r.get('voided') else r['amount_cents']-r['paid_cents']
    payees=rc.rows(c,'purchase_payees')+[{'id':'fleet:'+r['id'],'kind':'driver','name':r['name']} for r in c.execute('SELECT id,name FROM delivery_drivers WHERE active=1 ORDER BY id')]
    return {'payees':payees,'categories':categories(c),'suppliers':rc.rows(c,'suppliers'),'orders':orders,'receipts':receipts,'payments':payments,'charges':charges}
def scope(value,grants):
    import copy
    r=copy.deepcopy(value);m=set(grants['modules']);financial=bool(m & {'finance.payables','workspace.analytics'}) or 'purchases.write' in grants['actions'] or 'purchases.pay' in grants['actions'] or 'purchases.cost' in grants['actions']
    if not m & {'master.products','inventory.operations','master.suppliers','purchase.orders','purchase.receipts','finance.payables','workspace.analytics'}:return {'categories':[],'payees':[],'suppliers':[],'orders':[],'receipts':[],'payments':[],'charges':[]}
    if not m & {'purchase.orders','purchase.receipts','finance.payables','workspace.analytics'}:r.update(orders=[],receipts=[],payments=[],charges=[])
    financial=financial and erp_access.can_read_data(grants,'purchase-prices')
    if not erp_access.can_read_data(grants,'supplier-terms'):
        for supplier in r.get('suppliers',[]):
            for key in ('payment_days','tax_id'):supplier.pop(key,None)
        for order in r.get('orders',[]):order.pop('payment_days',None)
        for receipt in r.get('receipts',[]):receipt.pop('due_date',None)
    if not financial:
        def strip(v):
            if isinstance(v,dict):return {k:strip(x) for k,x in v.items() if not k.endswith('_cents') and k not in ('price','actual_unit_price','payments','billing_qty','billing_unit','rate')}
            if isinstance(v,list):return [strip(x) for x in v]
            return v
        r=strip(r);r['payments']=[]
    return r

class Operations:
    def __init__(self,c,now,audit):self.c=c;self.now=now;self.audit=audit
    def prior(self,t,b):
        key=rc.text(b.get('request_key'),'提交编号',100);r=self.c.execute('SELECT payload FROM '+t+' WHERE request_key=?',(key,)).fetchone()
        if r:
            v=json.loads(r[0])
            if v['request_fingerprint']!=fingerprint(b):raise ValueError('提交编号已用于其他内容，请重新打开窗口')
            return v
    def save(self,t,r,b,role,label,old=None):
        if old:self.c.execute('UPDATE '+t+' SET payload=? WHERE id=?',(rc.dump(r),r['id']))
        else:
            r.update(request_fingerprint=fingerprint(b),created_at=self.now())
            self.c.execute('INSERT INTO '+t+' VALUES(?,?,?)',(r['id'],b['request_key'],rc.dump(r)))
        self.audit(self.c,role,label,r['id'],old,r);return r
    def order_record(self,b):
        old=get(self.c,'purchase_orders',b.get('id'))
        if type(b.get('version')) is not int or b['version']!=old['version']:raise ValueError('采购单已被其他页面处理，请同步后重试')
        return old
    def category(self,b,role):
        erp_access.require_role(role,'suppliers.write');old=get(self.c,'supplier_categories',b['id']) if b.get('id') else None
        if old and b.get('version')!=old['version']:raise ValueError('品类已更新，请重新打开')
        used=old and any(old['id'] in s.get('category_ids',[]) for s in rc.rows(self.c,'suppliers'))
        if b.get('action')=='delete':
            if not old:raise ValueError('品类不存在')
            if used:raise ValueError('品类正在被供应商使用，请先调整供应商的供货品类')
            self.c.execute('DELETE FROM supplier_categories WHERE id=?',(old['id'],));self.audit(self.c,role,'删除供货品类',old['id'],old,None);return old
        name=rc.text(b.get('name'),'供货品类名称',60);kind=b.get('kind')
        if kind not in ('raw','finished','other'):raise ValueError('请选择原辅料、成品或其他')
        if old and used and kind!=old['kind']:raise ValueError('已被使用的品类不能更换业务类型，请新建品类后调整关联')
        if any(r['name']==name and (not old or r['id']!=old['id']) for r in categories(self.c)):raise ValueError('供货品类名称已存在')
        r={'id':old['id'] if old else 'SC-'+secrets.token_hex(5),'name':name,'kind':kind,'active':b.get('active',True) is not False,'version':old['version']+1 if old else 1}
        if used and not r['active']:raise ValueError('品类正在使用，请先调整供应商关联后停用')
        self.c.execute('INSERT INTO supplier_categories VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(r['id'],rc.dump(r)))
        self.audit(self.c,role,'维护供货品类',r['id'],old,r);return r

    def supplier(self,b,role):
        erp_access.require_role(role,'suppliers.write');old=get(self.c,'suppliers',b['id']) if b.get('id') else None
        if old and b.get('version')!=old['version']:raise ValueError('供应商资料已变更，请同步后重试')
        days=b.get('payment_days',0)
        try:
            if isinstance(days,bool) or str(int(days))!=str(days) or not 0<=int(days)<=365:raise ValueError()
        except (ValueError,TypeError):raise ValueError('账期须为0至365的整数天')
        category_ids=b.get('category_ids',old.get('category_ids',[]) if old else ['SC-RAW'])
        if not isinstance(category_ids,list) or not category_ids or len(category_ids)!=len(set(category_ids)):raise ValueError('请选择供货品类，可多选')
        valid={r['id'] for r in categories(self.c) if r.get('active')}
        if any(cid not in valid for cid in category_ids):raise ValueError('供货品类不存在或已停用')
        r={'id':old['id'] if old else 'SUP-'+secrets.token_hex(4).upper(),'version':old['version']+1 if old else 1,'name':rc.text(b.get('name'),'供应商名称',100),'contact':rc.text(b.get('contact',''),'联系人',80,False),'phone':rc.text(b.get('phone',''),'联系电话',60,False),'address':rc.text(b.get('address',''),'地址',250,False),'category_ids':category_ids,'category':rc.text(b.get('category',''),'供应品类',100,False),'tax_id':rc.text(b.get('tax_id',''),'税号',80,False),'payment_days':int(days),'note':rc.text(b.get('note',''),'备注',500,False),'active':b.get('active',True) is not False,'updated_at':self.now()}
        if old:self.c.execute('UPDATE suppliers SET name=?,version=?,payload=? WHERE id=?',(r['name'],r['version'],rc.dump(r),r['id']))
        else:self.c.execute('INSERT INTO suppliers VALUES(?,?,?,?)',(r['id'],r['name'],r['version'],rc.dump(r)))
        self.audit(self.c,role,'维护供应商档案',r['id'],old,r);return r
    def order(self,b,role):
        erp_access.require_role(role,'purchases.write')
        if not b.get('id'):
            prior=self.prior('purchase_orders',b)
            if prior:return prior
        old=self.order_record(b) if b.get('id') else None
        if old and old['state']!='draft':raise ValueError('仅草稿采购单可修改，已确认单请关闭未到货余量后另建采购单')
        supplier=get(self.c,'suppliers',b.get('supplier_id'))
        if not supplier['active']:raise ValueError('供应商已停用，不能新建或确认采购')
        when=rc.day(b.get('business_date'));expected=rc.day(b.get('expected_date'))
        if expected<when:raise ValueError('预计到货日期不能早于采购日期')
        lines=b.get('lines')
        if not isinstance(lines,list) or not 1<=len(lines)<=100:raise ValueError('请填写1至100行采购物料')
        result=[];seen=set()
        for l in lines:
            if not isinstance(l,dict):raise ValueError('采购明细格式错误')
            item=self.c.execute('SELECT * FROM material_items WHERE id=? AND active=1',(l.get('material_id'),)).fetchone()
            if not item:raise ValueError('物料不存在或已停用')
            wid=rc.warehouse(item,l.get('warehouse_id'),c=self.c,when=when);key=(item['id'],wid)
            if key in seen:raise ValueError('同一库房物料重复，请合并采购行')
            seen.add(key);q=rc.qty(l.get('qty'),positive=True);price=rc.qty(l.get('price'),'含税单价',positive=True);amount=rounded(q,price)
            if not 0<amount<=10000000000:raise ValueError('采购明细金额须在0.01至100000000元之间')
            result.append({'id':'L'+str(len(result)+1),'material_id':item['id'],'material_name':item['name'],'unit':item['unit'],'warehouse_id':wid,'warehouse_name':rc.warehouse_names(self.c)[wid],'qty':rc.ds(q),'price':rc.ds(price),'amount_cents':amount,'note':rc.text(l.get('note',''),'明细备注',200,False)})
        if sum(l['amount_cents'] for l in result)>10000000000:raise ValueError('采购单总金额不能超过100000000元')
        stored=self.c.execute("SELECT value FROM meta WHERE key='purchase_weight_tolerance_kg'").fetchone()
        default=Decimal(stored[0]) if stored and stored[0] else Decimal('0.5')
        raw_tol=b.get('tolerance_kg')
        tolerance=rc.qty(raw_tol,'磅差容忍公斤') if raw_tol not in (None,'') else default
        if tolerance<0 or tolerance>2000:raise ValueError('磅差容忍公斤应在 0～2000 之间')
        r={'id':old['id'] if old else 'PO-'+when.replace('-','')+'-'+secrets.token_hex(3).upper(),'version':old['version']+1 if old else 1,'state':'draft','business_date':when,'expected_date':expected,'supplier_id':supplier['id'],'supplier_name':supplier['name'],'payment_days':supplier['payment_days'],'lines':result,'total_cents':sum(l['amount_cents'] for l in result),'reference':rc.text(b.get('reference',''),'合同/外部单号',100,False),'note':rc.text(b.get('note',''),'采购说明',500,False),'handler':rc.text(b.get('handler'),'采购经办人',80),'tolerance_kg':rc.ds(tolerance)}
        if old:r.update(created_at=old['created_at'],request_fingerprint=old['request_fingerprint'])
        return self.save('purchase_orders',r,b,role,'保存采购草稿',old)
    def confirm(self,b,role):
        erp_access.require_role(role,'purchases.write');old=self.order_record(b)
        if old['state']!='draft':raise ValueError('仅草稿可确认采购')
        if not get(self.c,'suppliers',old['supplier_id'])['active']:raise ValueError('供应商已停用')
        if any(not self.c.execute('SELECT 1 FROM material_items WHERE id=? AND active=1',(l['material_id'],)).fetchone() for l in old['lines']):raise ValueError('采购物料已停用，请修改草稿')
        for line in old['lines']:rc.warehouse({'id':line['material_id']},line.get('warehouse_id'),c=self.c,when=old['business_date'])
        r={**old,'state':'confirmed','version':old['version']+1,'confirmed_at':self.now()};return self.save('purchase_orders',r,b,role,'确认采购单',old)
    def close(self,b,role):
        erp_access.require_role(role,'purchases.write');old=self.order_record(b)
        if old['state'] not in ('draft','confirmed'):raise ValueError('该采购单已关闭或取消')
        rs=[r for r in rc.rows(self.c,'purchase_receipts') if r['order_id']==old['id']]
        if rs and all(sum((Decimal(l['qty']) for r in rs for l in r['lines'] if l['line_id']==line['id']),Decimal(0))==Decimal(line['qty']) for line in old['lines']):raise ValueError('采购单已全部入库，无需关闭余量')
        r={**old,'state':'closed' if rs else 'cancelled','version':old['version']+1,'close_reason':rc.text(b.get('note'),'关闭原因',500),'closed_at':self.now()};return self.save('purchase_orders',r,b,role,'关闭采购余量' if rs else '取消采购单',old)
    def receipt(self,b,role):
        erp_access.require_role(role,'purchases.receive');prior=self.prior('purchase_receipts',b)
        if prior:return prior
        old=self.order_record(b)
        if old['state']!='confirmed':raise ValueError('仅已确认且未关闭的采购单可验收入库')
        when=rc.day(b.get('business_date'));rc.open_period(self.c,when)
        if when<old['business_date']:raise ValueError('入库日期不能早于采购日期')
        latest=self.c.execute("SELECT MAX(month) FROM resource_periods WHERE json_extract(payload,'$.state')='closed'").fetchone()[0]
        if latest and when[:7]<=latest:raise ValueError('不能在已结账历史期间之前追加采购入库')
        if b.get('revision')!=rc.revision(self.c):raise ValueError('物料库存已变更，请同步后核对再入库')
        lines=b.get('lines')
        if not isinstance(lines,list) or not lines or len(lines)>100:raise ValueError('请填写本次验收数量')
        prior_receipts=[r for r in rc.rows(self.c,'purchase_receipts') if r['order_id']==old['id']];result=[];received_in_receipt={};amount_in_receipt={};rid='GR-'+secrets.token_hex(6).upper();handler=rc.text(b.get('handler'),'验收人',80);reference=rc.text(b.get('reference',''),'送货单/批号',100,False);note=rc.text(b.get('note'),'验收说明',500)
        for l in lines:
            line=next((x for x in old['lines'] if x['id']==l.get('line_id')),None)
            if not line:raise ValueError('验收明细不存在')
            # One order line may arrive split across warehouses in the same receipt.
            wid=rc.warehouse({'id':line['material_id']},l.get('warehouse_id') or line.get('warehouse_id'),c=self.c,when=when)
            q=rc.qty(l.get('qty'),positive=True)
            dispatch=rc.qty(l.get('dispatch_qty'),'发车磅数') if l.get('dispatch_qty') not in (None,'') else q
            arrival=rc.qty(l.get('arrival_qty'),'卸车磅数') if l.get('arrival_qty') not in (None,'') else dispatch
            if dispatch<=0 or arrival<=0:raise ValueError(line['material_name']+'发车磅数与卸车磅数必须大于 0')
            variance=(abs(dispatch-arrival)).quantize(Decimal('0.001'),rounding=ROUND_HALF_UP)
            tolerance=Decimal(str(old.get('tolerance_kg') or '50'))
            negotiated=bool(l.get('negotiated'))
            if variance>tolerance and not negotiated:raise ValueError(line['material_name']+'发车磅与卸车磅差'+rc.ds(variance)+'公斤，超过容忍'+rc.ds(tolerance)+'公斤；请与供应商协商后勾选「已协商」再入库')
            settled=rc.qty(l.get('settled_qty'),line['material_name']+'协商结算重量') if l.get('settled_qty') not in (None,'') else dispatch
            if settled<=0:raise ValueError(line['material_name']+'协商结算重量必须大于 0')
            if variance>tolerance and negotiated and l.get('settled_qty') in (None,''):raise ValueError(line['material_name']+'已勾选协商，请填写协商后的结算重量')
            price=Decimal(str(line['price']))
            if l.get('settled_price') not in (None,''):
                try:price=Decimal(str(l.get('settled_price')))
                except Exception:raise ValueError(line['material_name']+'协商结算单价无效')
                if price<=0:raise ValueError(line['material_name']+'协商结算单价必须大于 0')
                if not negotiated:raise ValueError(line['material_name']+'调整结算单价须先勾选「已协商」')
            history=[x for r in prior_receipts for x in r['lines'] if x['line_id']==line['id']];previous=sum((Decimal(x['qty']) for x in history),Decimal(0))+received_in_receipt.get(line['id'],Decimal(0));remain=Decimal(line['qty'])-previous
            if q>remain:raise ValueError(line['material_name']+'验收超过未到货数量')
            if not self.c.execute('SELECT 1 FROM material_items WHERE id=? AND active=1',(line['material_id'],)).fetchone():raise ValueError('物料已停用，不能入库')
            if any(r['business_date']>when for r in prior_receipts):raise ValueError('本次验收日期不能早于已登记的后续验收')
            # Cumulative rounding makes cents exact even when a line arrives in many small batches.
            same=[x for x in history if Decimal(str(x.get('settled_price') or line['price']))==price]
            same_qty=sum((Decimal(x.get('settled_qty') or x['qty']) for x in same),Decimal(0))
            same_amount=sum(x['amount_cents'] for x in same)
            amount=rounded(same_qty+settled,price)-same_amount
            if amount<=0:raise ValueError('本次验收金额不足0.01元，请合并验收批量')
            mid='MT-'+secrets.token_hex(6).upper();record={'id':mid,'version':1,'created_at':self.now(),'role':role,'business_date':when,'material_id':line['material_id'],'material_name':line['material_name'],'unit':line['unit'],'kind':'receipt','qty':rc.ds(arrival),'amount_cents':amount,'dispatch_qty':rc.ds(dispatch),'arrival_qty':rc.ds(arrival),'settled_qty':rc.ds(settled),'variance_kg':rc.ds(variance),'negotiated':negotiated,'settled_price':rc.ds(price),'product_id':'','warehouse_id':wid,'warehouse_name':rc.warehouse_names(self.c)[wid],'department':{'WH-TOFU':'豆腐线','WH-SKIN':'豆皮线'}.get(wid,'共用'),'partner':old['supplier_name'],'supplier_id':old['supplier_id'],'purchase_order_id':old['id'],'purchase_receipt_id':rid,'reference':reference,'note':note,'handler':handler,'sequence':len(rc.rows(self.c,'material_entries'))+1}
            if line['material_id']=='RM-SOY':record['quality']=rc.quality(l)
            self.c.execute('INSERT INTO material_entries VALUES(?,?,?)',(mid,'purchase:'+rid+':'+line['id']+':'+str(len(result)),rc.dump(record)));self.audit(self.c,role,'采购验收入库',mid,None,record)
            result.append({'line_id':line['id'],'material_id':line['material_id'],'material_name':line['material_name'],'unit':line['unit'],'warehouse_id':wid,'warehouse_name':rc.warehouse_names(self.c)[wid],'qty':rc.ds(q),'arrival_qty':rc.ds(arrival),'dispatch_qty':rc.ds(dispatch),'arrival_qty':rc.ds(arrival),'settled_qty':rc.ds(settled),'settled_price':rc.ds(price),'variance_kg':rc.ds(variance),'negotiated':negotiated,'amount_cents':amount,'material_entry_id':mid,'quality':record.get('quality',{})})
            received_in_receipt[line['id']]=previous+settled;amount_in_receipt[line['id']]=amount_in_receipt.get(line['id'],0)+amount
        rc.material_ledger(self.c)
        r={'id':rid,'order_id':old['id'],'supplier_id':old['supplier_id'],'supplier_name':old['supplier_name'],'business_date':when,'due_date':(date.fromisoformat(when)+timedelta(days=old['payment_days'])).isoformat(),'lines':result,'amount_cents':sum(l['amount_cents'] for l in result),'handler':handler,'reference':reference,'note':note,'version':1}
        self.save('purchase_receipts',r,b,role,'登记采购验收单');self.save('purchase_orders',{**old,'version':old['version']+1},b,role,'更新采购到货进度',old)
        charges=b.get('charges',[])
        if not isinstance(charges,list) or len(charges)>2:raise ValueError('采购附加费格式无效')
        for i,ch in enumerate(charges):
            self.charge({**ch,'receipt_id':rid,'request_key':'receipt-fee:'+rid+':'+str(i),'business_date':when,'revision':rc.revision(self.c),'handler':handler,'note':ch.get('note') or note},role)
        return r
    def payment(self,b,role):
        erp_access.require_role(role,'purchases.pay');prior=self.prior('purchase_payments',b)
        if prior:return prior
        old=self.order_record(b);when=rc.day(b.get('business_date'));rc.open_period(self.c,when)
        receipts=[r for r in rc.rows(self.c,'purchase_receipts') if r['order_id']==old['id']]
        if not receipts or when<max(r['business_date'] for r in receipts):raise ValueError('付款日期不能早于该采购单最近验收日期')
        paid=sum(r['amount_cents'] for r in rc.rows(self.c,'purchase_payments') if r['order_id']==old['id'] and not r.get('charge_id') and not r.get('voided'));amount=rc.cents(b.get('amount'),positive=True)
        if amount>sum(r['amount_cents'] for r in receipts)-paid:raise ValueError('付款超过已验收入库的未付余额')
        method=b.get('method')
        if method not in ('银行转账','现金','微信','支付宝','其他'):raise ValueError('请选择付款方式')
        r={'id':'PP-'+secrets.token_hex(6).upper(),'order_id':old['id'],'supplier_id':old['supplier_id'],'supplier_name':old['supplier_name'],'business_date':when,'amount_cents':amount,'account_id':payment_account(self.c,b),'method':method,'reference':rc.text(b.get('reference',''),'付款凭据',100,False),'note':rc.text(b.get('note'),'付款说明',500),'handler':rc.text(b.get('handler'),'付款经办人',80),'version':1}
        self.save('purchase_payments',r,b,role,'登记采购付款');self.save('purchase_orders',{**old,'version':old['version']+1},b,role,'更新采购付款进度',old);return r
    def payment_void(self,b,role):
        # 受控冲销采购付款：保留原付款记录与凭据号，只将记录标记作废并从应付、资金流水剔除。
        erp_access.require_role(role,'purchases.pay')
        p=get(self.c,'purchase_payments',b.get('payment_id'))
        if p.get('voided'):raise ValueError('该笔采购付款已冲销')
        if b.get('version') is not None and type(b.get('version')) is not int:raise ValueError('付款版本无效，请刷新后重试')
        if b.get('version') is not None and b['version']!=p['version']:raise ValueError('付款记录已变更，请刷新后重试')
        reason=rc.text(b.get('reason'),'冲销原因',500)
        if not reason:raise ValueError('请填写冲销原因')
        when=p['business_date'];rc.open_period(self.c,when)
        record={**p,'voided':True,'void_reason':reason,'voided_at':self.now(),'voided_by':role,'version':p['version']+1,'updated_at':self.now()}
        self.c.execute('UPDATE purchase_payments SET payload=? WHERE id=?',(rc.dump(record),p['id']))
        self.audit(self.c,role,'冲销采购付款',p['id'],p,record)
        return record

    def warehouse(self,b,role):
        erp_access.require_role(role,'purchases.write');old=self.order_record(b);lines=b.get('lines')
        if not isinstance(lines,list) or not lines:raise ValueError('请选择历史采购明细所属库房')
        updated=json.loads(rc.dump(old));changes={}
        for raw in lines:
            line=next((l for l in updated['lines'] if l['id']==raw.get('line_id')),None)
            if not line or line.get('warehouse_id') or line['id'] in changes:raise ValueError('仅未指定库房的历史采购行可确认库房')
            wid=rc.warehouse({'id':line['material_id']},raw.get('warehouse_id'),c=self.c);line.update(warehouse_id=wid,warehouse_name=rc.warehouse_names(self.c)[wid]);changes[line['id']]=wid
        for r in rc.rows(self.c,'purchase_receipts'):
            if r['order_id']!=old['id']:continue
            before=json.loads(rc.dump(r))
            for l in r['lines']:
                if l['line_id'] not in changes:continue
                wid=changes[l['line_id']];entry=get(self.c,'material_entries',l['material_entry_id']);self.cost_period(entry['business_date'])
                revised={**entry,'warehouse_id':wid,'warehouse_name':rc.warehouse_names(self.c)[wid],'version':entry['version']+1,'warehouse_confirmed_at':self.now()}
                self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(rc.dump(revised),entry['id']));self.audit(self.c,role,'确认历史入库库房',entry['id'],entry,revised);l.update(warehouse_id=wid,warehouse_name=rc.warehouse_names(self.c)[wid])
            self.c.execute('UPDATE purchase_receipts SET payload=? WHERE id=?',(rc.dump(r),r['id']));self.audit(self.c,role,'确认历史验收库房',r['id'],before,r)
        rc.material_ledger(self.c);updated['version']+=1;return self.save('purchase_orders',updated,b,role,'确认历史采购库房',old)
    def cost_period(self,when):
        rc.open_period(self.c,when)
        if any(json.loads(r[0])['state']=='closed' and r[1]>=when[:7] for r in self.c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('后续月份已结账，不能修改影响历史库存成本的采购费用或库房')
    def charge_payee(self,b,role):
        # Legacy API records can still explicitly identify a supplier. The UI always sends a type.
        kind=b.get('payee_type')
        if kind is None and b.get('supplier_id'):kind='supplier'
        if kind not in ('supplier','driver','worker','other'):raise ValueError('请选择费用收款方类型及实际收款人')
        rid=b.get('payee_id') if 'payee_type' in b else b.get('supplier_id')
        if not rid:raise ValueError('请选择实际收款方')
        if kind=='supplier':
            supplier=get(self.c,'suppliers',rid)
            if not supplier['active']:raise ValueError('费用收款方已停用，请核对档案')
            return {'payee_type':kind,'payee_id':supplier['id'],'payee_name':supplier['name'],'supplier_id':supplier['id'],'supplier_name':supplier['name']},supplier['payment_days']
        if rid=='new':
            name=rc.text(b.get('payee_name'),'实际收款人姓名',80)
            row=self.c.execute('SELECT payload FROM purchase_payees WHERE kind=? AND name=?',(kind,name)).fetchone()
            if row:payee=json.loads(row[0])
            else:
                payee={'id':'PE-'+secrets.token_hex(6).upper(),'kind':kind,'name':name,'created_at':self.now()}
                self.c.execute('INSERT INTO purchase_payees VALUES(?,?,?,?)',(payee['id'],kind,name,rc.dump(payee)))
                self.audit(self.c,role,'登记采购费用收款人',payee['id'],None,payee)
        elif isinstance(rid,str) and rid.startswith('fleet:') and kind=='driver':
            row=self.c.execute('SELECT id,name FROM delivery_drivers WHERE id=? AND active=1',(rid[6:],)).fetchone()
            if not row:raise ValueError('司机不存在或已停用，请重新选择')
            payee={'id':rid,'kind':kind,'name':row['name']}
        else:
            payee=get(self.c,'purchase_payees',rid)
            if payee['kind']!=kind:raise ValueError('收款人类型不匹配，请重新选择')
        return {'payee_type':kind,'payee_id':payee['id'],'payee_name':payee['name'],'supplier_id':'','supplier_name':payee['name']},0
    def charge(self,b,role):
        erp_access.require_role(role,'purchases.cost');prior=self.prior('purchase_charges',b)
        if prior:return prior
        receipt=get(self.c,'purchase_receipts',b.get('receipt_id'));when=rc.day(b.get('business_date'));rc.open_period(self.c,when);self.cost_period(receipt['business_date'])
        if when<receipt['business_date']:raise ValueError('费用日期不能早于验收入库日期')
        if b.get('revision')!=rc.revision(self.c):raise ValueError('原辅料成本已变更，请同步后核对再提交')
        kind=b.get('kind');unit=b.get('billing_unit')
        if kind not in ('freight','unloading') or unit not in ('公斤','吨'):raise ValueError('请选择运费或装卸费，并指定公斤或吨计价')
        q=rc.qty(b.get('billing_qty'),'计费重量',positive=True);rate=rc.qty(b.get('rate'),'每'+unit+'单价',positive=True);amount=rounded(q,rate)
        if not 0<amount<=10000000000:raise ValueError('采购附加费金额须在0.01至100000000元之间')
        payee,payment_days=self.charge_payee(b,role)
        basis=b.get('allocation_basis','weight');lines=receipt['lines'];weights=[]
        if basis=='weight':
            custom=b.get('weights',[])
            if not isinstance(custom,list) or len({x.get('line_id') for x in custom})!=len(custom) or any(x.get('line_id') not in {l['line_id'] for l in lines} for x in custom):raise ValueError('分摊重量明细无效')
            mapping={x['line_id']:x.get('weight_kg') for x in custom}
            for l in lines:
                value=mapping.get(l['line_id'])
                if value is None:
                    if l['unit'] not in ('公斤','吨'):raise ValueError('非重量单位物料请填写分摊重量，或选择按货款分摊')
                    value=Decimal(l['qty'])*(1000 if l['unit']=='吨' else 1)
                weights.append(rc.qty(value,'分摊公斤数'))
        elif basis=='value':weights=[Decimal(l['amount_cents']) for l in lines]
        else:raise ValueError('分摊依据无效')
        total=sum(weights,Decimal(0))
        if total<=0:raise ValueError('分摊基数须大于零')
        exact=[Decimal(amount)*w/total for w in weights];alloc=[int(v) for v in exact]
        for i in sorted(range(len(lines)),key=lambda i:exact[i]-alloc[i],reverse=True)[:amount-sum(alloc)]:alloc[i]+=1
        rid='PC-'+secrets.token_hex(6).upper();allocations=[]
        for line,w,value in zip(lines,weights,alloc):
            entry=get(self.c,'material_entries',line['material_entry_id']);wid=rc.entry_warehouse(entry)
            if wid=='WH-UNASSIGNED':raise ValueError('请先在采购单确认历史大豆所属库房，再登记费用')
            record={**entry,'version':entry['version']+1,'purchase_goods_cents':entry.get('purchase_goods_cents',entry['amount_cents']),'purchase_charges_cents':entry.get('purchase_charges_cents',0)+value,'amount_cents':entry['amount_cents']+value}
            record.setdefault('purchase_charge_history',[]).append({'charge_id':rid,'amount_cents':value,'kind':kind})
            self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(rc.dump(record),entry['id']));self.audit(self.c,role,'采购费用计入库存',entry['id'],entry,record)
            allocations.append({'line_id':line['line_id'],'material_entry_id':entry['id'],'warehouse_id':wid,'basis_qty':rc.ds(w),'amount_cents':value})
        rc.material_ledger(self.c)
        record={'id':rid,'version':1,'order_id':receipt['order_id'],'receipt_id':receipt['id'],**payee,'business_date':when,'due_date':(date.fromisoformat(when)+timedelta(days=payment_days)).isoformat(),'kind':kind,'billing_qty':rc.ds(q),'billing_unit':unit,'rate':rc.ds(rate),'amount_cents':amount,'allocation_basis':basis,'allocations':allocations,'reference':rc.text(b.get('reference',''),'费用凭据',100,False),'handler':rc.text(b.get('handler'),'经办人',80),'note':rc.text(b.get('note'),'费用说明',500)}
        return self.save('purchase_charges',record,b,role,'登记采购'+('运费' if kind=='freight' else '装卸费'))
    def charge_void(self,b,role):
        # 受控冲销采购附加费：回退已计入库存的运费/装卸费，保留原费用单与原因，不留死账。
        erp_access.require_role(role,'purchases.cost')
        charge=get(self.c,'purchase_charges',b.get('charge_id'))
        if charge.get('voided'):raise ValueError('该笔运费/装卸费已冲销')
        if b.get('version') is not None and b['version']!=charge['version']:raise ValueError('费用记录已变更，请刷新后重试')
        reason=rc.text(b.get('reason'),'冲销原因',500)
        paid=[r for r in rc.rows(self.c,'purchase_payments') if r.get('charge_id')==charge['id'] and not r.get('voided')]
        if paid:raise ValueError('请先冲销该费用的付款，再冲销费用')
        rc.open_period(self.c,charge['business_date'])
        for a in charge.get('allocations',[]):
            entry=get(self.c,'material_entries',a['material_entry_id']);self.cost_period(entry['business_date'])
            rc.open_period(self.c,entry['business_date'])
            record={**entry,'version':entry['version']+1,'purchase_charges_cents':max(0,entry.get('purchase_charges_cents',0)-a['amount_cents']),'amount_cents':max(0,entry['amount_cents']-a['amount_cents'])}
            record.setdefault('purchase_charge_history',[]).append({'charge_id':charge['id'],'amount_cents':-a['amount_cents'],'kind':charge['kind'],'void':True})
            self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(rc.dump(record),entry['id']));self.audit(self.c,role,'采购费用退出库存',entry['id'],entry,record)
        record={**charge,'voided':True,'void_reason':reason,'voided_at':self.now(),'voided_by':role,'version':charge['version']+1}
        self.c.execute('UPDATE purchase_charges SET payload=? WHERE id=?',(rc.dump(record),charge['id']))
        rc.material_ledger(self.c)
        self.audit(self.c,role,'冲销采购附加费',charge['id'],charge,record)
        return record

    def charge_payment(self,b,role):
        erp_access.require_role(role,'purchases.pay');prior=self.prior('purchase_payments',b)
        if prior:return prior
        charge=get(self.c,'purchase_charges',b.get('charge_id'));when=rc.day(b.get('business_date'));rc.open_period(self.c,when)
        if charge.get('voided'):raise ValueError('该笔运费/装卸费已冲销，不能再登记付款')
        if when<charge['business_date']:raise ValueError('付款日期不能早于费用登记日期')
        paid=sum(r['amount_cents'] for r in rc.rows(self.c,'purchase_payments') if r.get('charge_id')==charge['id'] and not r.get('voided'));amount=rc.cents(b.get('amount'),positive=True)
        if amount>charge['amount_cents']-paid:raise ValueError('付款超过该笔运费/装卸费未付余额')
        if b.get('method') not in ('银行转账','现金','微信','支付宝','其他'):raise ValueError('请选择付款方式')
        record={'id':'PP-'+secrets.token_hex(6).upper(),'charge_id':charge['id'],'order_id':charge['order_id'],'supplier_id':charge['supplier_id'],'supplier_name':charge['supplier_name'],'business_date':when,'amount_cents':amount,'account_id':payment_account(self.c,b),'method':b['method'],'reference':rc.text(b.get('reference',''),'付款凭据',100,False),'handler':rc.text(b.get('handler'),'付款经办人',80),'note':rc.text(b.get('note'),'付款说明',500),'version':1}
        record.update({k:charge[k] for k in ('payee_type','payee_id','payee_name') if k in charge})
        return self.save('purchase_payments',record,b,role,'登记采购附加费付款')
