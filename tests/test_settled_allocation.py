import json,uuid,unittest
from decimal import Decimal
import test_product_profit as fixture
import cost_allocation as ca
import resources_costs as rc
import product_profit

class SettledAllocationTests(fixture.ProductProfitTests):
    def test_weighted_scope_preserves_every_cent(self):
        self.order('A','P001','100');self.order('B','P002','50')
        with fixture.erp.connect(True) as c:
            ca.save_factor(c,'P002','2','2026-10',[], '管理员',fixture.erp.now,fixture.erp.audit)
            report=ca.allocate(c,'2026-10-01','2026-10-31',[{'id':'E','amount_cents':10001,'product_ids':['P001','P002']}])
        self.assertEqual(report['allocated_cents'],10001);self.assertEqual(report['unallocated_cents'],0)
        self.assertEqual(report['allocations'],{'P001':5001,'P002':5000})
        self.assertEqual(report['details'][0]['denominator'],'200')
    def test_subset_does_not_charge_other_products(self):
        self.order('A','P001','100');self.order('B','P002','50')
        with fixture.erp.connect() as c:r=ca.allocate(c,'2026-10-01','2026-10-31',[{'id':'E','amount_cents':110,'product_ids':['P002']}])
        self.assertEqual(r['allocations'],{'P002':110})
    def test_final_settlement_beats_shipped_kg_no_standard_fallback(self):
        self.assertEqual(ca.settled_kg({'unit':'公斤','actual_qty':'100','bill_qty':'90','billing_unit':'公斤'}),Decimal(90))
        self.assertIsNone(ca.settled_kg({'unit':'公斤','actual_qty':'100','standard_kg':'1'}))
        self.assertIsNone(ca.settled_kg({'unit':'筐','bill_qty':'2','billing_unit':'筐'}))
    def test_pending_order_blocks_pool_without_losing_amount(self):
        self.order('A','P001','100')
        with fixture.erp.connect(True) as c:
            row=json.loads(c.execute("SELECT payload FROM orders WHERE id='A'").fetchone()[0]);row['state']='ready';c.execute('UPDATE orders SET payload=? WHERE id=?',(rc.dump(row),'A'))
            r=ca.allocate(c,'2026-10-01','2026-10-31',[{'id':'E','amount_cents':100,'product_ids':[]}])
        self.assertEqual(r['unallocated_cents'],100);self.assertFalse(r['allocations'])
    def test_external_and_mixed_are_never_guessed(self):
        self.order('A','P001');self.order('B','P002')
        with fixture.erp.connect(True) as c:
            ca.write(c,'product_trade',{'P001':{'supply_kind':'purchased'},'P002':{'supply_kind':'mixed'}})
            r=ca.allocate(c,'2026-10-01','2026-10-31',[{'id':'E','amount_cents':100,'product_ids':[]}])
        self.assertEqual(r['unallocated_cents'],100);self.assertFalse(r['allocations']);self.assertTrue(r['basis']['P001']['excluded'])
    def test_zero_denominator_and_offsetting_pending_not_ready(self):
        with fixture.erp.connect() as c:r=ca.allocate(c,'2026-10-01','2026-10-31',[{'id':'A','amount_cents':100},{'id':'B','amount_cents':-100}])
        self.assertEqual(r['unallocated_cents'],0);self.assertEqual(r['pending_items'],2)
    def test_category_snapshots_and_edit_reset_approval(self):
        with fixture.erp.connect(True) as c:
            op=rc.Operations(c,fixture.erp.now,fixture.erp.audit)
            cat=op.expense_category({'name':'共用设备维护','group':'制造费用','nature':'变动','product_ids':['P001','P002']},'管理员')
            e=op.expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','category':cat['id'],'amount':'100','partner':'设备维修方','handler':'会计','note':'测试'},'管理员')
            self.assertEqual(e['product_ids'],['P001','P002'])
            op.expense_review({'request_key':str(uuid.uuid4()),'id':e['id'],'version':1,'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
            updated=op.expense_edit({'id':e['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','period':'2026-10','category':cat['id'],'amount':'120','product_ids':['P002'],'handler':'会计','note':'更正'},'管理员')
            self.assertEqual(updated['version'],3)
            projection=next(r for r in rc.expense_projection(c) if r['id']==e['id'])
            self.assertEqual(projection['payment_state'],'pending');self.assertEqual(projection['product_ids'],['P002']);self.assertEqual(len(rc.rows(c,'indirect_expenses')),1)
            op.expense_category({**cat,'name':'新名称'},'管理员')
            self.assertEqual(updated['category_snapshot']['name'],'共用设备维护')
    def test_factor_invalid_and_closed_history(self):
        with fixture.erp.connect(True) as c:
            for n in ('0','-1','NaN','Infinity'):
                with self.assertRaises(ValueError):ca.save_factor(c,'P001',n,'2026-10',[], '管理员',fixture.erp.now,fixture.erp.audit)
            c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-10',1,rc.dump({'month':'2026-10','state':'closed'})))
            with self.assertRaisesRegex(ValueError,'结账'):ca.save_factor(c,'P001','2','2026-10',[], '管理员',fixture.erp.now,fixture.erp.audit)
            ca.save_factor(c,'P001','2','2026-11',[], '管理员',fixture.erp.now,fixture.erp.audit)
            self.assertEqual(ca.factor(c,'P001','2026-10'),1)
    def test_public_yield_uses_settlement_not_driver_average(self):
        self.order('A','P001','90')
        report={'products':[{'product_id':'P001','bean_kg':'30','net_kg':'300','yield_kg_per_kg':'10'}]}
        with fixture.erp.connect() as c:r=ca.public_yields(c,report,'2026-10-20')['products'][0]
        self.assertEqual(r['settlement_kg'],'90');self.assertEqual(r['settlement_yield'],'3')
    def test_profit_uses_new_rule_and_reconciles(self):
        self.order('A','P001','100');self.order('B','P002','50');self.expense('100')
        r=self.report();self.assertEqual(r['allocation_version'],ca.RULE)
        self.assertEqual(r['allocation']['amount_cents'],10000)
        self.assertEqual(sum(d['allocated_cents']+d['unallocated_cents'] for d in r['allocation']['details']),10000)
        rows={r['product_id']:r for r in r['rows']};self.assertEqual(rows['P001']['indirect_cents'],6667);self.assertEqual(rows['P002']['indirect_cents'],3333)
    def test_closed_snapshot_is_immutable_and_not_in_resources(self):
        self.order('A','P001','100');self.expense('100')
        with fixture.erp.connect(True) as c:
            op=rc.Operations(c,fixture.erp.now,fixture.erp.audit)
            result=op.period({'month':'2026-10','version':0,'state':'closed','note':'核对完成'},'管理员')
            self.assertNotIn('report_snapshot',result)
            before=product_profit.month(c,'2026-10')
            row=json.loads(c.execute("SELECT payload FROM orders WHERE id='A'").fetchone()[0]);row['lines'][0]['bill_qty']='1'
            c.execute('UPDATE orders SET payload=? WHERE id=?',(rc.dump(row),'A'))
            self.assertEqual(product_profit.month(c,'2026-10'),before)
            self.assertNotIn('report_snapshot',rc.snapshot(c)['periods'][0])

    def test_legacy_closed_month_retains_old_rule(self):
        self.order('A','P001');self.order('B','P002');self.expense('100')
        with fixture.erp.connect(True) as c:
            c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-10',1,rc.dump({'month':'2026-10','state':'closed'})))
            r=product_profit.month(c,'2026-10')
        self.assertEqual(r['allocation_version'],'legacy-closed')

    def test_close_does_not_freeze_unknown_profit_from_pending_allocation(self):
        self.order('A','P001','100');self.expense('100')
        with fixture.erp.connect(True) as c:
            row=json.loads(c.execute("SELECT payload FROM orders WHERE id='A'").fetchone()[0]);row['state']='ready'
            c.execute('UPDATE orders SET payload=? WHERE id=?',(rc.dump(row),'A'))
        with fixture.erp.connect(True) as c:
            report=product_profit.month(c,'2026-10');self.assertIsNone(report['total']['net_cents'])
            opened=rc.Operations(c,fixture.erp.now,fixture.erp.audit).period({'month':'2026-10','version':0,'state':'closed','note':'核对完成'},'管理员')
            self.assertTrue(opened.get('report_snapshot_pending'))
            self.assertNotIn('report_snapshot',opened)
        with fixture.erp.connect(True) as c:
            report=product_profit.month(c,'2026-10');self.assertIsNone(report['total']['net_cents'])
            row=json.loads(c.execute("SELECT payload FROM orders WHERE id='A'").fetchone()[0]);row['state']='reviewed'
            c.execute('UPDATE orders SET payload=? WHERE id=?',(rc.dump(row),'A'))
        with fixture.erp.connect() as c:
            report=product_profit.month(c,'2026-10');self.assertIsNotNone(report['total']['net_cents'])

if __name__=='__main__':unittest.main()
