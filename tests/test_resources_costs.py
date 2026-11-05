import unittest,tempfile,uuid
from pathlib import Path
import test_workflow as fixture
import resources_costs as rc
import erp_access

erp=fixture.erp
class ResourceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=erp.DB;erp.DB=Path(self.tmp.name)/'ledger.db';erp.init_db(demo=False)
    def tearDown(self):erp.DB=self.old;self.tmp.cleanup()
    def call(self,method,body,role='会计'):
        with erp.connect(True) as c:return getattr(rc.Operations(c,erp.now,erp.audit),method)(body,role)
    def snap(self):
        with erp.connect() as c:return rc.snapshot(c)
    def material(self,kind,q,amount='0',when='2026-10-01',**extra):
        return self.call('material',{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':when,'kind':kind,'qty':q,'amount':amount,'revision':self.snap()['revision'],'request_key':str(uuid.uuid4()),'handler':'测试经办','note':'测试凭据','department':'豆腐线',**extra})
    def test_average_cost_and_full_depletion_exact_cents(self):
        self.material('opening','100','460');self.material('consume','10');self.material('receipt','10','50');s=self.snap();o=next(i for i in s['items'] if i['id']=='RM-SOY')
        self.assertEqual((o['qty'],o['value_cents']),('100',46400));self.assertEqual(s['entries'][1]['cost_cents'],4600)
        self.material('consume','100');o=next(i for i in self.snap()['items'] if i['id']=='RM-SOY');self.assertEqual((o['qty'],o['value_cents']),('0',0))
    def test_multiple_openings_same_warehouse_keep_separate_variety_lots(self):
        self.material('opening','100','460',quality={'soy_variety':'春豆','origin':'伊犁','sowing_type':'春播'})
        self.material('opening','200','900',quality={'soy_variety':'复播豆','origin':'伊犁','sowing_type':'复播'})
        s=self.snap();o=next(i for i in s['items'] if i['id']=='RM-SOY')
        self.assertEqual((o['qty'],o['value_cents']),('300',136000))
        with erp.connect() as c:
            stock=next(w for w in rc.material_ledger(c,warehouse_details=True)[2] if w['id']=='RM-SOY' and w['warehouse_id']=='WH-TOFU')
            lots=sorted((lot['quality'].get('soy_variety'),lot['qty']) for lot in stock['lots'])
        self.assertEqual(lots,[('复播豆','200'),('春豆','100')])
    def test_overdraw_and_backdated_negative_rollback(self):
        self.material('opening','5','25',when='2026-10-02')
        for args in [('consume','6','0','2026-10-03'),('consume','1','0','2026-10-01')]:
            with self.assertRaises(ValueError):self.material(*args)
        self.assertEqual(len(self.snap()['entries']),1)
    def test_void_receipt_cannot_break_later_stock(self):
        e=self.material('opening','10','50');self.material('consume','7')
        with self.assertRaises(ValueError):self.call('void',{'ledger':'material','id':e['id'],'version':1,'reason':'错误入库'})
        self.assertFalse(self.snap()['entries'][0].get('voided',False))
    def test_idempotency_and_request_content_mismatch(self):
        b={'material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':'2026-10-01','kind':'receipt','qty':'10','amount':'50','revision':self.snap()['revision'],'request_key':str(uuid.uuid4()),'handler':'会计','note':'凭据'}
        a=self.call('material',b);self.assertEqual(a['id'],self.call('material',b)['id']);self.assertEqual(len(self.snap()['entries']),1)
        with self.assertRaises(ValueError):self.call('material',{**b,'qty':'20'})
    def test_valuation_amendment_recomputes_consumption_and_preserves_quantity(self):
        e=self.material('receipt','10','40');self.material('consume','3');self.call('value',{'id':e['id'],'version':1,'amount':'200','note':'补发票'})
        s=self.snap();o=next(i for i in s['items'] if i['id']=='RM-SOY');self.assertEqual((o['qty'],o['value_cents'],o['uncosted_qty']),('7',14000,'0'));self.assertEqual(s['entries'][1]['cost_cents'],6000)
    def test_count_and_immutable_used_unit(self):
        self.material('opening','10','50');self.material('count','8');self.assertEqual(self.snap()['entries'][-1]['delta_qty'],'-2')
        i=next(i for i in self.snap()['items'] if i['id']=='RM-SOY')
        with self.assertRaises(ValueError):self.call('item',{**i,'unit':'吨'})
    def test_backdated_return_uses_business_day_balance_without_future_receipts(self):
        self.material('receipt','100','400',when='2026-10-20')
        self.material('consume','50',when='2026-10-20')
        self.material('receipt','100','1000',when='2026-10-25')
        returned=self.material('return','10',when='2026-10-21')
        self.assertEqual(returned['amount_cents'],4000)
        with erp.connect() as c:
            stock=next(s for s in rc.material_ledger(c,until='2026-10-21',warehouse_details=True)[2] if s['id']=='RM-SOY' and s['warehouse_id']=='WH-TOFU')
            self.assertEqual((stock['qty'],stock['value_cents']),('60',24000))
        self.assertEqual(next(s for s in self.snap()['items'] if s['id']=='RM-SOY')['value_cents'],124000)

    def test_backdated_return_after_depletion_uses_prior_price_not_future_stock(self):
        self.material('receipt','100','400',when='2026-10-20')
        self.material('consume','100',when='2026-10-20')
        self.material('receipt','100','1000',when='2026-10-25')
        self.assertEqual(self.material('return','10',when='2026-10-21')['amount_cents'],4000)

    def test_same_day_return_and_count_include_prior_same_day_entries(self):
        self.material('receipt','10','40')
        returned=self.material('return','2')
        self.assertEqual(returned['amount_cents'],800)
        self.material('receipt','10','100')
        gained=self.material('count','23')
        self.assertEqual((gained['kind'],gained['qty'],gained['amount_cents']),('gain','1',673))
        self.assertGreater(gained['sequence'],returned['sequence'])

    def test_future_price_cannot_supply_missing_historical_return_valuation(self):
        self.material('receipt','100','1000',when='2026-10-25')
        with self.assertRaisesRegex(ValueError,'入库必须有金额'):self.material('return','10',when='2026-10-21')
        self.assertEqual(len(self.snap()['entries']),1)

    def test_backdated_returns_and_counts_do_not_change_closed_future_period(self):
        self.material('receipt','10','40',when='2026-10-20')
        self.call('period',{'month':'2026-11','version':0,'state':'closed','note':'后续月份已结账'})
        before=self.snap()
        for kind,q in [('return','1'),('count','11')]:
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'已结账历史'):self.material(kind,q,when='2026-10-21')
        self.assertEqual(self.snap(),before)
    def test_monthly_expense_close_reopen_and_reference_period(self):
        b={'business_date':'2026-11-03','period':'2026-10','category':'electricity','amount':'5000','request_key':str(uuid.uuid4()),'handler':'会计','note':'十月电费'}
        self.call('expense',b);self.call('period',{'month':'2026-10','version':0,'state':'closed','note':'已核对'})
        with self.assertRaises(ValueError):self.call('expense',{**b,'request_key':str(uuid.uuid4())})
        self.call('period',{'month':'2026-10','version':1,'state':'open','note':'补充费用'});self.call('expense',{**b,'request_key':str(uuid.uuid4())});self.assertEqual(len(self.snap()['expenses']),2)
    def bean_customer(self):
        return erp.master({'kind':'customer','create':True,'name':'豆渣客户','route':'豆渣自取','delivery_method':'pickup','business_kind':'byproduct'},'管理员')['id']
    def test_byproduct_units_cash_and_period_protection(self):
        b={'business_date':'2026-10-04','qty':'2','unit':'吨','price':'350','received':'500','customer_id':self.bean_customer(),'request_key':str(uuid.uuid4()),'handler':'出纳'}
        e=self.call('byproduct',b,'出纳');self.assertEqual((e['amount_cents'],e['received_cents']),(70000,50000))
        with self.assertRaises(ValueError):self.call('receive_byproduct',{'id':e['id'],'version':1,'amount':'201','business_date':'2026-10-05','note':'到账'},'出纳')
        self.call('period',{'month':'2026-10','version':0,'state':'closed','note':'月结'})
        e=self.call('receive_byproduct',{'id':e['id'],'version':1,'amount':'200','business_date':'2026-11-05','note':'到账'},'出纳');self.assertEqual(e['received_cents'],70000)
        with self.assertRaises(ValueError):self.call('void',{'ledger':'byproduct','id':e['id'],'version':2,'reason':'删除'},'出纳')
    def test_grants_and_quantity_only_projection(self):
        self.material('opening','100','460')
        with self.assertRaises(ValueError):self.call('expense',{'request_key':'x'},'库管')
        with self.assertRaises(ValueError):self.call('material',{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':'2026-10-02','kind':'receipt','qty':'1','amount':'5','revision':self.snap()['revision'],'request_key':'wh','handler':'库管','note':'入库'},'库管')
        projected=erp_access.scope_resources(self.snap(),erp_access.defaults('库管'));self.assertNotIn('value_cents',projected['items'][0]);self.assertNotIn('cost_cents',projected['entries'][0]);self.assertEqual(projected['expenses'],[])
        grants={'modules':['finance.costs'],'actions':['costs.write']};self.call('expense',{'business_date':'2026-10-01','period':'2026-10','category':'rent','amount':'300','request_key':'expense','handler':'会计','note':'租金'})
        with erp.connect() as c:d=erp_access.scope_bootstrap(erp.bootstrap(),{'role':'会计','permissions':grants})
        self.assertEqual(d['resources']['expenses'][0]['amount_cents'],30000)
    def test_voided_material_can_be_restored_after_stock_recheck(self):
        self.material('opening','10','50');e=self.material('consume','2')
        with erp.connect() as c:before=rc.material_ledger(c)[0]
        voided=self.call('void',{'ledger':'material','id':e['id'],'version':1,'reason':'重复领用'})
        with erp.connect() as c:self.assertIn(e['id'],[x['id'] for x in rc.snapshot(c)['voided_entries']])
        restored=self.call('restore',{'ledger':'material','id':e['id'],'version':voided['version'],'reason':'撤销作废'})
        self.assertFalse(restored['voided']);self.assertEqual(restored['version'],3)
        with erp.connect() as c:
            self.assertFalse(any(x['id']==e['id'] for x in rc.snapshot(c)['voided_entries']))
            self.assertEqual(next(i for i in rc.material_ledger(c)[0] if i['id']=='RM-SOY')['qty'],'8')
        with self.assertRaises(ValueError):self.call('restore',{'ledger':'material','id':e['id'],'version':restored['version'],'reason':'再次恢复'})

    def test_voided_expense_and_byproduct_restore_and_guards(self):
        expense=self.call('expense',{'business_date':'2026-10-03','period':'2026-10','category':'rent','amount':'300','request_key':str(uuid.uuid4()),'handler':'会计','note':'租金'})
        voided=self.call('void',{'ledger':'expense','id':expense['id'],'version':1,'reason':'重复登记'})
        restored=self.call('restore',{'ledger':'expense','id':expense['id'],'version':voided['version'],'reason':'撤销作废'})
        self.assertFalse(restored['voided'])
        with erp.connect() as c:self.assertFalse(next(e for e in rc.snapshot(c)['expenses'] if e['id']==expense['id'])['voided'])
        sale=self.call('byproduct',{'business_date':'2026-10-04','qty':'1','unit':'吨','price':'300','received':'0','customer_id':self.bean_customer(),'request_key':str(uuid.uuid4()),'handler':'会计'},'会计')
        voided_sale=self.call('void',{'ledger':'byproduct','id':sale['id'],'version':1,'reason':'录入有误'})
        restored_sale=self.call('restore',{'ledger':'byproduct','id':sale['id'],'version':voided_sale['version'],'reason':'撤销作废'})
        self.assertFalse(restored_sale['voided'])
        with self.assertRaises(ValueError):self.call('restore',{'ledger':'expense','id':expense['id'],'version':restored['version'],'reason':'无依据'})

    def test_restore_blocks_closed_month_and_requires_version(self):
        e=self.material('opening','5','25');voided=self.call('void',{'ledger':'material','id':e['id'],'version':1,'reason':'测试'})
        self.call('period',{'month':'2026-10','version':0,'state':'closed','note':'月结'})
        with self.assertRaises(ValueError):self.call('restore',{'ledger':'material','id':e['id'],'version':voided['version'],'reason':'月结后恢复'})
        with self.assertRaises(ValueError):self.call('restore',{'ledger':'material','id':e['id'],'version':99,'reason':'旧版本'})

    def test_reinitialize_preserves_all_entries(self):
        self.material('opening','1','4.6');before=self.snap();erp.init_db(demo=False);self.assertEqual(self.snap(),before)
