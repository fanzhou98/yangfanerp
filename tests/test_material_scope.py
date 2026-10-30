"""多产品领用：按覆盖期实际用豆量分摊，跨月拒绝，批量整单写入。"""
import unittest,uuid
from decimal import Decimal
import test_production_daily as fixture
import material_allocation as ma
import product_profit
import resources_costs as rc

erp=fixture.erp
class MaterialScopeTests(unittest.TestCase):
    setUp=fixture.DailyFactoryTests.setUp
    tearDown=fixture.DailyFactoryTests.tearDown
    def issue(self,qty='10',pids=('P001','P002'),start='2026-10-20',end='2026-10-20',material_id='A-GYPSUM',kind='consume',role='管理员',**extra):
        body={'request_key':str(uuid.uuid4()),'material_id':material_id,'business_date':'2026-10-20','kind':kind,'qty':qty,'warehouse_id':'WH-COMMON','note':'测试领用','handler':'厂长','product_ids':list(pids),'coverage_start':start,'coverage_end':end,**extra}
        with erp.connect(True) as c:
            body['revision']=rc.revision(c)
            return rc.Operations(c,erp.now,erp.audit).material(body,role)
    def receipt(self,qty='100',amount='400',material_id='A-GYPSUM'):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':material_id,'business_date':'2026-10-20','kind':'receipt','qty':qty,'amount':amount,'warehouse_id':'WH-COMMON','note':'测试入库','handler':'会计'},'管理员')
    def report(self):
        with erp.connect() as c:return product_profit.month(c,'2026-10')
    def test_coverage_bean_weights_split_cents_exactly(self):
        entries=[{'id':'E1','material_id':'A-GYPSUM','material_name':'石膏','business_date':'2026-10-20','kind':'consume','cost_cents':4000,'product_ids':['P001','P002'],'coverage_start':'2026-10-20','coverage_end':'2026-10-22'}]
        day_bean={'2026-10-20':{'P001':Decimal('1'),'P002':Decimal('3')},'2026-10-21':{'P001':Decimal('1'),'P002':Decimal('1')},'2026-10-22':{'P001':Decimal('2'),'P002':Decimal('2')}}
        with erp.connect() as c:detail=ma.scope_allocations(c,'2026-10',entries,day_bean)['E1']
        self.assertEqual(detail['basis'],'coverage-bean');self.assertEqual(detail['days'],3)
        self.assertEqual(detail['allocations'],{'P001':1600,'P002':2400})
    def test_no_bean_basis_falls_back_to_equal_and_return_is_negative(self):
        entries=[{'id':'E1','material_id':'A-GYPSUM','material_name':'石膏','business_date':'2026-10-20','kind':'return','cost_cents':4800,'product_ids':['P001','P002'],'coverage_start':'2026-10-20','coverage_end':'2026-10-20'}]
        with erp.connect() as c:detail=ma.scope_allocations(c,'2026-10',entries,{})['E1']
        self.assertEqual(detail['basis'],'coverage-equal')
        self.assertEqual(detail['allocations'],{'P001':-2400,'P002':-2400})
    def test_multi_product_issue_keeps_products_and_coverage(self):
        self.receipt();entry=self.issue('10',('P001','P002'))
        self.assertEqual(entry['product_ids'],['P001','P002']);self.assertEqual(entry['product_id'],'')
        self.assertEqual(entry['coverage_start'],'2026-10-20');self.assertEqual(entry['coverage_end'],'2026-10-20')
        self.assertEqual(entry['allocation_basis'],'coverage-bean');self.assertEqual(entry['cost_target'],'共用')
    def test_single_product_issue_attributes_directly(self):
        self.receipt();entry=self.issue('1',('P001',))
        self.assertEqual(entry['product_ids'],['P001']);self.assertEqual(entry['product_id'],'P001')
        self.assertEqual(entry['coverage_start'],'2026-10-20')
    def test_cross_month_coverage_is_rejected(self):
        self.receipt()
        with self.assertRaisesRegex(ValueError,'同一个月'):self.issue('1',('P001','P002'),start='2026-10-30',end='2026-11-02')
    def test_reversed_coverage_is_rejected(self):
        self.receipt()
        with self.assertRaisesRegex(ValueError,'不能早于'):self.issue('1',('P001','P002'),start='2026-10-22',end='2026-10-20')
    def test_batch_writes_all_lines_in_one_call(self):
        self.receipt()
        lines=[{'material_id':'A-GYPSUM','kind':'consume','qty':'1','warehouse_id':'WH-COMMON','product_ids':['P001','P002'],'coverage_start':'2026-10-20','coverage_end':'2026-10-20','note':'领用'},
               {'material_id':'A-GYPSUM','kind':'consume','qty':'2','warehouse_id':'WH-COMMON','product_ids':['P001'],'coverage_start':'2026-10-20','coverage_end':'2026-10-20','note':'领用'}]
        with erp.connect(True) as c:
            result=rc.Operations(c,erp.now,erp.audit).material_batch({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'business_date':'2026-10-20','handler':'厂长','note':'批量领用','lines':lines},'厂长')
        self.assertEqual(result['count'],2)
        with erp.connect() as c:entries=[e for e in rc.rows(c,'material_entries') if e['business_date']=='2026-10-20' and e['kind']=='consume']
        self.assertEqual(len(entries),2);self.assertEqual({tuple(e['product_ids']) for e in entries},{('P001','P002'),('P001',)})
    def test_issue_report_shows_product_rows_and_unallocated(self):
        self.receipt();self.issue('10',('P001','P002'));self.issue('1',())
        with erp.connect() as c:r=ma.issue_report(c,'2026-10')
        self.assertEqual(r['total_cents'],4400);self.assertEqual(r['allocated_cents'],4000);self.assertEqual(r['unallocated_cents'],400)
        self.assertEqual({p['product_id']:p['amount_cents'] for p in r['products']},{'P001':2000,'P002':2000})
        self.assertEqual(r['entries'][0]['product_rows'][0]['product_name'],'大豆腐')
    def test_product_profit_includes_scoped_material_and_gap(self):
        self.receipt();self.issue('10',('P001','P002'));r=self.report()
        rows={x['product_id']:x for x in r['rows']}
        self.assertEqual(rows['P001']['scope_material_cents'],2000);self.assertEqual(rows['P002']['scope_material_cents'],2000)
        self.assertEqual(r['costs']['scope_materials_cents'],4000)
        self.assertEqual(len(r['material_allocations']),1)
        self.assertTrue(any('均分' in g['field'] for g in r['gaps']))
    def test_color_material_seeded_for_skin(self):
        with erp.connect() as c:row=c.execute("SELECT name,category,unit FROM material_items WHERE id='A-COLOR'").fetchone()
        self.assertEqual(tuple(row),('豆皮黄色素','辅料','公斤'))
