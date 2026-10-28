import unittest,uuid,json
from decimal import Decimal
import test_production_daily as fixture
import inventory_reconciliation as check
import resources_costs as rc
import erp_access as access

erp=fixture.erp
class InventoryReconciliationTests(unittest.TestCase):
    setUp=fixture.DailyFactoryTests.setUp
    tearDown=fixture.DailyFactoryTests.tearDown
    def order(self,qty='600',day='2026-10-22'):
        with erp.connect(True) as c:
            unit=c.execute("SELECT unit FROM products WHERE id='P004'").fetchone()[0]
            o={'id':'JD','customer_id':'C001','customer_name':'九鼎','business_date':day,'state':'dispatched','lines':[{'product_id':'P004','product_name':'豆皮','unit':unit,'ordered_qty':'600','actual_qty':qty}]}
            c.execute('INSERT OR REPLACE INTO orders VALUES(?,?)',('JD',rc.dump(o)))
    def report(self):
        with erp.connect() as c:return check.report(c,'2026-10-22')
    def body(self,**extra):
        r=self.report();p=next(p for p in r['products'] if p['product_id']=='P004')
        return {'business_date':'2026-10-22','version':r['version'],'request_key':str(uuid.uuid4()),'source_fingerprint':r['source_fingerprint'],'sources_checked':True,'handler':'库管','note':'独立盘点及客户反馈核查','products':[{'product_id':'P004','unit':p['unit'],'pre_qty':'700','post_qty':'120','post_in_qty':'0','post_out_qty':'0'}],**extra}
    def save(self,b,role='管理员'):
        with erp.connect(True) as c:return check.save(c,b,role,erp.now,erp.audit)
    def row(self):return next(p for p in self.report()['products'] if p['product_id']=='P004')
    def test_jiuding_plus20_correction_preserves_orders_and_recheck_history(self):
        self.order();self.save(self.body());p=self.row();self.assertEqual((p['expected_qty'],p['difference_qty']),('100','20'))
        with erp.connect() as c:original=json.loads(c.execute("SELECT payload FROM orders WHERE id='JD'").fetchone()[0])
        self.assertEqual(original['lines'][0]['actual_qty'],'600')
        self.order('580');self.assertTrue(self.report()['source_changed']);self.assertEqual(self.row()['difference_qty'],'0');self.assertIn('重新核对',self.row()['status'])
        self.save(self.body());r=self.report();self.assertFalse(r['source_changed']);self.assertEqual(self.row()['status'],'已对平');self.assertEqual(len(r['history']),1)
        self.assertEqual(r['history'][0]['source_snapshot'][0]['actual_qty'],'600')
        self.assertEqual(r['history'][0]['products'][0]['post_qty'],'120')
    def test_missing_is_not_zero_and_completeness_must_be_explicit(self):
        self.order();b=self.body(sources_checked=False);self.save(b);self.assertIsNone(self.row()['difference_qty'])
        b=self.body();b['products'][0]['post_qty']='';self.save(b);self.assertIsNone(self.row()['difference_qty'])
        b=self.body();b['products'][0].update(pre_qty='0',post_qty='0');self.save(b);self.assertIn('应剩为负',self.row()['status'])
    def test_other_movements_signed_and_require_evidence(self):
        self.order();b=self.body();b['products'][0].update(post_in_qty='10',post_out_qty='5')
        with self.assertRaisesRegex(ValueError,'依据'):self.save(b)
        b['products'][0]['movement_note']='盘后补产10，报损5';self.save(b);self.assertEqual(self.row()['expected_qty'],'105');self.assertEqual(self.row()['difference_qty'],'15')
    def test_imported_closing_keeps_version_and_flags_changed_source(self):
        self.order()
        def closing(version):
            with erp.connect(True) as c:
                c.execute('INSERT OR REPLACE INTO stock_closings VALUES(?,?)',('SC-test',rc.dump({'id':'SC-test','business_date':'2026-10-22','state':'closed','version':version,'products':[{'product_id':'P004','counted_qty':'120'}]})))
        closing(1);b=self.body(closing_version=1);b['products'][0]['post_source']='closing';self.save(b)
        self.assertEqual(self.row()['closing_version'],1)
        closing(2);self.assertIn('结存来源已变更',self.row()['status'])
        b=self.body(closing_version=1);b['products'][0]['post_source']='closing'
        with self.assertRaisesRegex(ValueError,'已变化'):self.save(b)
        b=self.body(closing_version=2);b['products'][0]['post_source']='closing';self.save(b)
        self.assertEqual(self.row()['closing_version'],2)
        self.assertEqual(self.report()['history'][0]['products'][0]['closing_version'],1)
    def test_negative_difference_does_not_create_driver_debt(self):
        self.order();b=self.body();b['products'][0]['post_qty']='80';self.save(b);self.assertEqual(self.row()['difference_qty'],'-20')
        with erp.connect() as c:self.assertEqual({r['kind'] for r in rc.rows(c,'trade_records')},{'inventory-check'})
    def test_idempotence_stale_sources_and_versions(self):
        self.order();b=self.body();a=self.save(b);self.assertEqual(self.save(b),a)
        with self.assertRaisesRegex(ValueError,'其他内容'):self.save({**b,'note':'别的内容'})
        stale=self.body();self.order('580')
        with self.assertRaisesRegex(ValueError,'实发记录已变化'):self.save(stale)
        b=self.body();self.save(b)
        with self.assertRaisesRegex(ValueError,'核对记录已更新'):self.save({**b,'request_key':str(uuid.uuid4())})
    def test_next_day_feedback_returns_by_original_day_without_amounts(self):
        self.order()
        with erp.connect(True) as c:
            c.execute('INSERT INTO trade_records VALUES(?,?)',('F',rc.dump({'id':'F','kind':'feedback','order_id':'JD','product_id':'P004','product_name':'豆皮','unit':'包','actual_qty':'600','received_qty':'580','difference_qty':'-20','feedback_date':'2026-10-23','state':'pending','amount_cents':99999})))
        r=self.report();self.assertEqual(r['feedback'][0]['feedback_date'],'2026-10-23');self.assertNotIn('amount_cents',json.dumps(r))
    def test_closed_month_blocks_writes_and_unauthorized_role(self):
        self.order();b=self.body()
        token=access.GRANTS.set(access.defaults('会计'))
        try:
            with self.assertRaises(ValueError):self.save(b,'会计')
        finally:access.GRANTS.reset(token)
        with erp.connect(True) as c:c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-10',1,rc.dump({'month':'2026-10','state':'closed'})))
        with self.assertRaisesRegex(ValueError,'结账'):self.save(b)
    def test_product_validation_and_readonly_no_automatic_counts(self):
        self.order();r=self.report();self.assertEqual(self.row()['pre_qty'],'');self.assertEqual(self.row()['post_qty'],'')
        b=self.body();b['products'][0]['pre_qty']='NaN'
        with self.assertRaises(ValueError):self.save(b)
        b=self.body();b['products'].append(b['products'][0])
        with self.assertRaisesRegex(ValueError,'重复'):self.save(b)
        with erp.connect() as c:
            before=c.total_changes;check.report(c,'2026-10-22');self.assertEqual(c.total_changes,before)

if __name__=='__main__':unittest.main()
