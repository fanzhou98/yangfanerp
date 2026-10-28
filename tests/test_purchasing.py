import unittest,tempfile,uuid,json
from pathlib import Path
from decimal import Decimal
import server as erp, purchasing as p, resources_costs as rc, erp_access as access

class PurchasingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=erp.DB;erp.DB=Path(self.temp.name)/'erp-test.db';erp.init_db()
        self.context=erp.connect(True);self.c=self.context.__enter__();self.ops=p.Operations(self.c,erp.now,erp.audit)
        self.s=self.ops.supplier({'name':'测试供应商','category':'大豆 / 包装','payment_days':30},'会计')
    def tearDown(self):self.c.rollback();self.context.__exit__(None,None,None);erp.DB=self.old;self.temp.cleanup()
    def order(self,**overrides):
        body={'request_key':str(uuid.uuid4()),'business_date':'2026-10-01','expected_date':'2026-10-03','supplier_id':self.s['id'],'handler':'采购员','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'100','price':'4.6'}],**overrides}
        return self.ops.order(body,'会计')
    def confirm(self,o):return self.ops.confirm({'id':o['id'],'version':o['version']},'会计')
    def receive(self,o,q='40',when='2026-10-03',**extras):
        b={'id':o['id'],'version':o['version'],'request_key':str(uuid.uuid4()),'revision':rc.revision(self.c),'business_date':when,'lines':[{'line_id':'L1','qty':q}],'handler':'库管','note':'合格验收',**extras}
        return self.ops.receipt(b,'库管')
    def current(self,o):return next(x for x in p.projection(self.c)['orders'] if x['id']==o['id'])
    def test_partial_receipts_stock_payables_and_payment(self):
        o=self.confirm(self.order());r=self.receive(o);o=self.current(o)
        self.assertEqual(o['received_cents'],18400);self.assertEqual(o['outstanding_cents'],18400);self.assertEqual(o['status'],'部分入库');self.assertEqual(r['due_date'],'2026-11-02')
        stock=next(i for i in rc.snapshot(self.c)['items'] if i['id']=='RM-SOY');self.assertEqual(stock['qty'],'40');self.assertEqual(stock['value_cents'],18400)
        self.ops.payment({'id':o['id'],'version':o['version'],'business_date':'2026-10-04','amount':'84','method':'银行转账','handler':'出纳','note':'付款','request_key':str(uuid.uuid4())},'出纳')
        o=self.current(o);self.assertEqual(o['outstanding_cents'],10000)
        self.receive(o,'60','2026-10-05');o=self.current(o);self.assertEqual(o['status'],'全部入库');self.assertEqual(o['total_cents'],46000);self.assertEqual(o['received_cents'],46000);self.assertEqual(o['outstanding_cents'],37600)
        self.assertEqual(len(rc.rows(self.c,'indirect_expenses')),0)
    def test_one_order_line_can_be_received_into_two_warehouses(self):
        o=self.confirm(self.order())
        b={'id':o['id'],'version':o['version'],'request_key':str(uuid.uuid4()),'revision':rc.revision(self.c),'business_date':'2026-10-03',
           'lines':[{'line_id':'L1','warehouse_id':'WH-TOFU','qty':'30'},{'line_id':'L1','warehouse_id':'WH-SKIN','qty':'20'}],'handler':'库管','note':'分库验收'}
        r=self.ops.receipt(b,'库管')
        self.assertEqual(len(r['lines']),2)
        self.assertEqual({x['warehouse_id'] for x in r['lines']},{'WH-TOFU','WH-SKIN'})
        self.assertEqual(sum(Decimal(x['qty']) for x in r['lines']),50)
        balances=rc.material_ledger(self.c,warehouse_details=True)[2]
        self.assertEqual(next(b['qty'] for b in balances if b['id']=='RM-SOY' and b['warehouse_id']=='WH-TOFU'),'30')
        self.assertEqual(next(b['qty'] for b in balances if b['id']=='RM-SOY' and b['warehouse_id']=='WH-SKIN'),'20')
        o=self.current(o)
        over={'id':o['id'],'version':o['version'],'request_key':str(uuid.uuid4()),'revision':rc.revision(self.c),'business_date':'2026-10-04',
              'lines':[{'line_id':'L1','warehouse_id':'WH-TOFU','qty':'40'},{'line_id':'L1','warehouse_id':'WH-SKIN','qty':'40'}],'handler':'库管','note':'超额分库验收'}
        with self.assertRaisesRegex(ValueError,'超过未到货'):
            self.ops.receipt(over,'库管')

    def test_draft_validation_over_receipt_stale_version_and_duplicate(self):
        o=self.order()
        with self.assertRaisesRegex(ValueError,'仅已确认'):self.receive(o)
        o=self.confirm(o);b={'request_key':'same','id':o['id'],'version':o['version'],'revision':rc.revision(self.c),'business_date':'2026-10-03','lines':[{'line_id':'L1','qty':'40'}],'handler':'库管','note':'验收'}
        r=self.ops.receipt(b,'库管');self.assertEqual(r,self.ops.receipt(b,'库管'));self.assertEqual(len(rc.rows(self.c,'material_entries')),1)
        with self.assertRaisesRegex(ValueError,'其他内容'):self.ops.receipt({**b,'note':'不同内容'},'库管')
        with self.assertRaisesRegex(ValueError,'其他页面'):self.receive(o)
        with self.assertRaisesRegex(ValueError,'超过'):self.receive(self.current(o),'61')
        with self.assertRaisesRegex(ValueError,'重复'):self.order(lines=[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'1','price':'4'},{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'2','price':'4'}])
    def test_close_remaining_does_not_change_stock_or_payables(self):
        o=self.confirm(self.order());self.receive(o);o=self.current(o);self.ops.close({'id':o['id'],'version':o['version'],'note':'余量取消'},'会计');o=self.current(o)
        self.assertEqual(o['status'],'已关闭余量');self.assertEqual(o['outstanding_cents'],18400)
        with self.assertRaisesRegex(ValueError,'仅已确认'):self.receive(o,'60')
        self.assertEqual(next(i for i in rc.snapshot(self.c)['items'] if i['id']=='RM-SOY')['qty'],'40')
    def test_linked_material_cannot_be_voided_or_repriced(self):
        o=self.confirm(self.order());r=self.receive(o);mid=r['lines'][0]['material_entry_id'];ops=rc.Operations(self.c,erp.now,erp.audit)
        with self.assertRaisesRegex(ValueError,'采购关联'):ops.void({'ledger':'material','id':mid,'version':1,'reason':'测试'},'会计')
        with self.assertRaisesRegex(ValueError,'采购关联'):ops.value({'id':mid,'version':1,'amount':'200','note':'改价'},'会计')
    def test_permissions_and_money_projection(self):
        o=self.confirm(self.order());self.receive(o)
        for method,b,role in [('supplier',{'name':'其他','payment_days':0},'库管'),('order',{},'出纳'),('payment',{},'库管'),('receipt',{},'出纳')]:
            with self.subTest(method=method),self.assertRaises(ValueError):getattr(self.ops,method)(b,role)
        scoped=p.scope(p.projection(self.c),access.defaults('库管'));encoded=json.dumps(scoped);self.assertNotIn('_cents',encoded);self.assertNotIn('"price"',encoded);self.assertTrue(scoped['receipts'])
        self.assertEqual(p.scope(p.projection(self.c),{'modules':[],'actions':[]})['suppliers'],[])
        self.assertTrue(p.scope(p.projection(self.c),access.defaults('出纳'))['orders'][0]['received_cents'])
    def test_closed_period_inactive_supplier_and_unit_guard(self):
        o=self.confirm(self.order());self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-10',1,rc.dump({'month':'2026-10','state':'closed','version':1})))
        with self.assertRaisesRegex(ValueError,'结账'):self.receive(o)
        item=dict(self.c.execute("SELECT * FROM material_items WHERE id='RM-SOY'").fetchone())
        with self.assertRaisesRegex(ValueError,'采购单引用'):rc.Operations(self.c,erp.now,erp.audit).item({**item,'unit':'吨'},'会计')
        self.ops.supplier({**self.s,'active':False},'会计')
        with self.assertRaisesRegex(ValueError,'停用'):self.order()
        # A supplier being paused does not prevent receiving an existing confirmed order after month reopened.
        self.c.execute('DELETE FROM resource_periods');self.receive(o)
    def test_money_limits_and_cumulative_rounding(self):
        with self.assertRaises(ValueError):self.order(lines=[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'100000000','price':'100000000'}])
        o=self.confirm(self.order(lines=[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'0.3','price':'0.333'}]))
        for _ in range(3):self.receive(self.current(o),'0.1')
        current=self.current(o);self.assertEqual(current['total_cents'],10);self.assertEqual(current['received_cents'],10)
        self.assertEqual(next(i for i in rc.snapshot(self.c)['items'] if i['id']=='RM-SOY')['value_cents'],10)
    def test_no_overpay_future_receipt_backdate_and_idempotent_payment(self):
        o=self.confirm(self.order());self.receive(o);o=self.current(o)
        b={'id':o['id'],'version':o['version'],'business_date':'2026-10-04','amount':'185','method':'银行转账','handler':'出纳','note':'付款','request_key':str(uuid.uuid4())}
        with self.assertRaisesRegex(ValueError,'超过'):self.ops.payment(b,'出纳')
        b['amount']='100';r=self.ops.payment(b,'出纳');self.assertEqual(self.ops.payment(b,'出纳'),r);self.assertEqual(len(rc.rows(self.c,'purchase_payments')),1)
        self.receive(self.current(o),'60','2026-10-10')
        with self.assertRaisesRegex(ValueError,'早于'):self.ops.payment({**b,'request_key':'new','version':self.current(o)['version'],'business_date':'2026-10-05'},'出纳')
    def test_business_groups_and_stable_permissions(self):
        self.assertEqual([g[1] for g in access.GROUPS],['基础资料','采购管理','销售管理','生产管理','库存管理','物流管理','财务管理','资产管理','人力资源','系统管理','工作空间'])
        mods={m['id'] for m in access.module_definitions()};self.assertTrue({'sales.orders','inventory.operations','finance.receivables','master.suppliers','purchase.orders','purchase.receipts','finance.payables'}<=mods)
        self.assertNotIn('purchases.pay',access.defaults('会计')['actions']);self.assertIn('purchases.receive',access.defaults('库管')['actions'])
