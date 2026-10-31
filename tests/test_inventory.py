import copy, unittest, uuid
from decimal import Decimal
import test_workflow as workflow
import inventory as inv
erp=workflow.erp
class InventoryTests(unittest.TestCase):
    tearDown=workflow.WorkflowTests.tearDown
    order=workflow.WorkflowTests.order
    settle=workflow.WorkflowTests.settle
    review=workflow.WorkflowTests.review
    pay=workflow.WorkflowTests.pay
    def setUp(self):
        workflow.WorkflowTests.setUp(self)
        with erp.connect(True) as c:
            c.execute('DELETE FROM orders');c.execute('DELETE FROM receipts')
    def ops(self,method,body,role='库管'):
        with erp.connect(True) as c:return getattr(inv.Operations(c,erp.now,erp.audit),method)(body,role)
    def snapshot(self,when='2026-10-21'):
        with erp.connect() as c:return inv.stock(c,when)
    def plan(self,when='2026-10-21',opening='10',production='5',**changes):
        data=erp.bootstrap();old=next((p for p in data['warehouse_plans'] if p['business_date']==when),{})
        body={'business_date':when,'version':old.get('version',0),'inventory_revision':data['inventory_revision'],'stock':[{'product_id':p['id'],'existing_qty':opening,'produced_qty':production} for p in data['products']],'allocations':[],'customers':[],'order_versions':{o['id']:o['version'] for o in data['orders'] if o['business_date']==when},**changes}
        return erp.save_warehouse(body,'库管')
    def ret(self,**changes):
        body={'received_date':'2026-10-21','customer_id':'C001','product_id':'P001','qty':'1','net_kg':'10','condition':'spoiled','reason':'变质退回','source_note':'客户退货电话记录，原单待查','request_key':str(uuid.uuid4()),'received_checked':True,**changes}
        return self.ops('create_return',body)
    def act(self,r,act,role='会计',**changes):return self.ops('return_action',{'id':r['id'],'version':r['version'],'action':act,**changes},role)
    def account(self,r,**changes):return self.act(r,'account',**{'account_date':'2026-10-21','account_qty':'10','price':'3.333','note':'按原销售手机记录核价','price_checked':True,**changes})
    def close_day(self,when='2026-10-21',**changes):
        data=erp.bootstrap();snapshot=self.snapshot(when);plan=next(p for p in data['warehouse_plans'] if p['business_date']==when);old=next((p for p in data['stock_closings'] if p['business_date']==when),{})
        return self.ops('close',{'business_date':when,'version':old.get('version',0),'inventory_revision':data['inventory_revision'],'plan_version':plan['version'],'evidence_checked':True,'counts':[{'product_id':p['product_id'],'counted_qty':p['book_qty'],'reason':''} for p in snapshot['products']],**changes})
    def test_spoiled_returns_quarantine_only_and_original_price_confirmation(self):
        self.plan();r=self.ret();p=self.snapshot()['products'][0]
        self.assertEqual((p['supply_qty'],p['quarantine_qty'],p['quarantine_kg']),('15','1','10'))
        with self.assertRaisesRegex(ValueError,'原销售单价'):self.account(r,price_checked=False)
        a=self.account(r);self.assertEqual(a['finance']['amount_cents'],3333);self.assertIsNone(r['source_price']);self.assertIsNotNone(r['reference_price'])
        with self.assertRaisesRegex(ValueError,'重复减账'):self.account(a)
    def test_closed_day_rejects_new_orders_even_without_shipment(self):
        self.plan();self.close_day()
        with self.assertRaisesRegex(ValueError,'已日结'):
            erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-21','batch':'补录','note':'',
                'lines':[{'product_id':'P001','ordered_qty':'1','actual_qty':'0','price':'75'}]},'库管')
    def test_return_idempotence_version_role_and_caps(self):
        key=str(uuid.uuid4());a=self.ret(request_key=key);b=self.ret(request_key=key);self.assertEqual(a['id'],b['id'])
        with self.assertRaisesRegex(ValueError,'编号重复'):self.ret(request_key=key,net_kg='11')
        with self.assertRaisesRegex(ValueError,'会计'):self.act(a,'account','库管')
        with self.assertRaisesRegex(ValueError,'不能超过'):self.account(a,account_qty='11')
        b=self.account(a)
        with self.assertRaisesRegex(ValueError,'其他页面'):self.account(a)
        with self.assertRaisesRegex(ValueError,'出纳'):self.act(b,'review','会计',evidence_checked=True)
        with self.assertRaises(ValueError):self.ret(net_kg='0')
    def test_credit_fifo_preserves_sale_and_cash_caps_receipts(self):
        o=self.review(self.settle(self.order()));r=self.account(self.ret(order_id=o['id']));r=self.act(r,'review','出纳',evidence_checked=True)
        o=next(x for x in erp.bootstrap()['orders'] if x['id']==o['id']);self.assertEqual(o['total_cents'],66993);self.assertEqual(o['paid_cents'],0);self.assertEqual(o['return_credit_cents'],3333);self.assertEqual(inv.wallet(r),0)
        with self.assertRaises(ValueError):self.pay(o,'669.93')
        o=self.pay(o,'636.60');self.assertEqual(o['status'],'已结清')
        with self.assertRaisesRegex(ValueError,'锁定'):erp.mutate('order',o,'会计',o['id'])
        with self.assertRaisesRegex(ValueError,'待复核'):self.act(r,'review','出纳',evidence_checked=True)
    def test_paid_invoice_credit_wallet_refund_and_new_invoice(self):
        o=self.review(self.settle(self.order()));self.pay(o,'669.93');r=self.act(self.account(self.ret()),'review','出纳',evidence_checked=True);self.assertEqual(inv.wallet(r),3333)
        with self.assertRaises(ValueError):self.act(r,'refund','出纳',amount='34',refund_date='2026-10-21',method='银行',note='退款流水',evidence_checked=True)
        r=self.act(r,'refund','出纳',amount='10',refund_date='2026-10-21',method='银行',note='退款流水',evidence_checked=True);self.assertEqual(inv.wallet(r),2333)
        new=self.review(self.settle(self.order()));self.assertEqual(new['return_credit_cents'],2333);r=next(x for x in erp.bootstrap()['sales_returns'] if x['id']==r['id']);self.assertEqual(inv.wallet(r),0)
    def test_linked_return_caps_and_original_price_lock(self):
        o=self.review(self.settle(self.order()));r=self.ret(order_id=o['id'],qty='6',net_kg='100')
        with self.assertRaisesRegex(ValueError,'实发数量'):self.ret(order_id=o['id'],qty='5',net_kg='10')
        with self.assertRaisesRegex(ValueError,'计价重量'):self.ret(order_id=o['id'],qty='1',net_kg='102')
        with self.assertRaisesRegex(ValueError,'原销售单价'):self.account(r,price='4')
        updated=copy.deepcopy(o);updated['lines'][0]['price']='4'
        with self.assertRaisesRegex(ValueError,'原销售价格'):erp.mutate('order',updated,'会计',o['id'])
    def test_disposal_partial_as_of_and_no_food_processing(self):
        r=self.ret(qty='2',net_kg='20');r=self.act(r,'dispose','库管',business_date='2026-10-22',kind='destroy',qty='1',net_kg='12',note='销毁记录001',handler='库管甲')
        self.assertEqual(inv.remaining_return(r), (Decimal('1'),Decimal('8')))
        self.assertEqual(self.snapshot()['products'][0]['quarantine_kg'],'20');self.assertEqual(self.snapshot('2026-10-22')['products'][0]['quarantine_kg'],'8')
        with self.assertRaisesRegex(ValueError,'请选择'):self.act(r,'dispose','库管',business_date='2026-10-22',kind='food',qty='1',net_kg='8',note='加工',handler='甲')
        with self.assertRaises(ValueError):self.act(r,'void',reason='重录')
        with self.assertRaises(ValueError):self.act(r,'dispose','库管',business_date='2026-10-22',kind='destroy',qty='2',net_kg='8',note='销毁',handler='甲')
    def process(self,**changes):
        return self.ops('process',{'business_date':'2026-10-21','inventory_revision':erp.bootstrap()['inventory_revision'],'origin':'internal','origin_confirmed':True,'inspection_checked':True,'product_id':'P004','input_qty':'2','input_kg':'20','outputs':[{'product_id':'P005','qty':'3','net_kg':'18'}],'request_key':str(uuid.uuid4()),**changes})
    def test_internal_processing_consumes_and_outputs_without_double_count(self):
        self.plan();self.process();rows={p['product_id']:p for p in self.snapshot()['products']};self.assertEqual(rows['P004']['book_qty'],'13');self.assertEqual(rows['P005']['book_qty'],'18')
        with self.assertRaisesRegex(ValueError,'客户退货'):self.process(origin='customer_return')
        with self.assertRaisesRegex(ValueError,'已有变化'):self.process(inventory_revision=0)
        self.process(input_qty='0');self.assertEqual(next(p for p in self.snapshot()['products'] if p['product_id']=='P004')['book_qty'],'13')
    def test_daily_close_and_next_day_carry_lock(self):
        self.plan();close=self.close_day();self.assertEqual(close['products'][0]['counted_qty'],'15');snapshot=self.snapshot('2026-10-22');self.assertEqual(snapshot['products'][0]['opening_qty'],'15')
        with self.assertRaisesRegex(ValueError,'日结'):self.plan()
        with self.assertRaisesRegex(ValueError,'日结'):self.ret()
        self.plan('2026-10-22',opening='15',production='0',opening_source_date='2026-10-21',opening_close_version=close['version'])
        with self.assertRaisesRegex(ValueError,'下一日已引用'):self.ops('close',{'business_date':'2026-10-21','version':close['version'],'action':'reopen','reason':'测试'})
    def test_daily_close_stale_unknown_variance_and_reopen(self):
        self.plan(opening='');
        with self.assertRaises(ValueError):self.close_day()
        self.plan();counts=[{'product_id':p['product_id'],'counted_qty':'14','reason':''} for p in self.snapshot()['products']]
        with self.assertRaisesRegex(ValueError,'差异原因'):self.close_day(counts=counts)
        for row in counts:row['reason']='实盘记录核定差异'
        with self.assertRaisesRegex(ValueError,'已有变化'):self.close_day(inventory_revision=0)
        closed=self.close_day(counts=counts);self.assertEqual(closed['products'][0]['variance_qty'],'-1')
        self.ops('close',{'business_date':'2026-10-21','version':closed['version'],'action':'reopen','reason':'补充核查'});self.plan()
    def test_shipment_reservation_prevents_negative_and_daily_close(self):
        o=erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-21','batch':'日常订货','lines':[{'product_id':'P001','ordered_qty':'20','actual_qty':'0','price':'3','driver':[],'customer':[]}]},'库管')
        self.plan(allocations=[{'order_id':o['id'],'product_id':'P001','qty':'10','ordered_qty':'20'}]);self.assertEqual(self.snapshot()['products'][0]['free_qty'],'5')
        with self.assertRaisesRegex(ValueError,'尚未实发'):self.close_day()
        o['lines'][0]['actual_qty']='16'
        with self.assertRaisesRegex(ValueError,'库存'):erp.mutate('order',o,'库管',o['id'])
        o['lines'][0]['actual_qty']='10';o=erp.mutate('order',o,'库管',o['id']);self.assertEqual(self.snapshot()['products'][0]['book_qty'],'5');self.close_day()
        # Weighing may be supplemented after day close if actual stock movement stays unchanged.
        o['lines'][0]['driver']=[{'gross':'118','count':'10','tare':'1.8'}];o=erp.mutate('order',o,'库管',o['id']);self.assertEqual(o['lines'][0]['driver_net'],'100')
    def test_archive_restore_return_processing_and_close(self):
        self.plan();self.ret();self.process();self.close_day();data=erp.bootstrap()
        with erp.connect() as c:archived_count=c.execute('SELECT COUNT(*) FROM archived_orders').fetchone()[0]
        counts={k:len(data[k]) for k in ['orders','receipts']}|{'archived_orders':archived_count}
        result=erp.trial_data({'action':'archive','reason':'测试库存链路归档','expected':counts},'会计');self.assertEqual(erp.bootstrap()['sales_returns'],[])
        erp.trial_data({'action':'restore','id':result['id'],'_data_epoch':result['business_data_epoch']},'会计');after=erp.bootstrap()
        for key in ['sales_returns','processing_batches','stock_closings']:self.assertEqual(data[key],after[key])

    def test_retract_pending_credit_preserves_history_and_never_posts_twice(self):
        r=self.account(self.ret());r=self.act(r,'retract','出纳',reason='原价依据不充分，退回核查')
        self.assertIsNone(r['finance']);self.assertEqual(len(r['finance_history']),1)
        r=self.account(r,price='3');self.assertEqual(r['finance']['amount_cents'],3000)
        r=self.act(r,'review','出纳',evidence_checked=True)
        with self.assertRaises(ValueError):self.act(r,'retract','会计',reason='不能回退已抵账单')
    def test_processing_stock_opening_cannot_be_erased(self):
        self.plan();self.process()
        with self.assertRaisesRegex(ValueError,'不能删除'):self.plan(opening='')
    def test_pack_credit_uses_confirmed_packages_not_standard_weight(self):
        r=self.ret(product_id='P004',qty='2',net_kg='20');r=self.account(r,account_qty='2',price='75')
        self.assertEqual(r['finance']['amount_cents'],15000);self.assertEqual(r['finance']['billing_unit'],'包')
        other=self.ret(product_id='P004',qty='1',net_kg='50')
        with self.assertRaises(ValueError):self.account(other,account_qty='2',price='75')

    def test_cannot_backdate_stock_into_already_closed_range(self):
        self.plan();self.close_day()
        with self.assertRaisesRegex(ValueError,'日结范围'):self.ret(received_date='2026-10-20')
        with self.assertRaisesRegex(ValueError,'日结范围'):self.plan('2026-10-20')
        r=self.ret(received_date='2026-10-22');self.assertEqual(r['received_date'],'2026-10-22')
