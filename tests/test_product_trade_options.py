import unittest
import test_inventory as fixture
import crate_accounting as ca,assets,purchasing,trade,resources_costs as rc

erp=fixture.erp
class ProductTradeOptionTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    def test_product_accepts_multiple_crate_types_and_independent_tares(self):
        with erp.connect(True) as c:
            old=next(p for p in erp.ordered_products(c) if p['id']=='P002');body={**old,'kind':'product','create':False,'expected':old,'crate_type_ids':['CR-WHITE','P-MEDIUM']};erp.master(body,'管理员',connection=c)
            self.assertEqual([v['id'] for v in ca.variants(c,'P002')],['CR-WHITE','P-MEDIUM'])
            ca.save_rules(c,[{'customer_id':'C001','product_id':'P002','variant_id':v,'tare':t,'expected':None} for v,t in [('CR-WHITE','1'),('P-MEDIUM','2')]],'管理员',erp.now,erp.audit)
            self.assertEqual(ca.defaults(c,'C001','P002'),{'CR-WHITE':'1','P-MEDIUM':'2'})
            self.assertEqual(sum(r['qty'] for r in ca.normalize(c,'P002',[{'asset_id':'CR-WHITE','qty':2,'tare':1},{'asset_id':'P-MEDIUM','qty':3,'tare':2}],5)),5)
            with self.assertRaises(ValueError):erp.master({**body,'crate_type_ids':['BAD']},'管理员',connection=c)
    def test_crate_management_multiple_mapping_uses_same_product_settings(self):
        with erp.connect(True) as c:
            prior=next(r for r in assets.rows(c) if r['kind']=='mapping' and r['product_id']=='P002')
            r=assets.save(c,'mapping',{'request_key':'multi-frame','product_id':'P002','version':prior['version'],'asset_ids':['CR-WHITE','P-MEDIUM'],'expected_asset_ids':[v['id'] for v in ca.variants(c,'P002')]},'管理员',erp.now,erp.audit)
            self.assertEqual(r['asset_ids'],['CR-WHITE','P-MEDIUM']);self.assertEqual([v['id'] for v in ca.variants(c,'P002')],r['asset_ids'])
            # A mixed stock total cannot be silently attributed to the first frame type.
            report=assets.report(c,'2026-10-21');self.assertIsNone(next(r for r in report['crates'] if r['id']=='CR-WHITE')['occupied_qty'])
    def test_external_product_requires_supplier_and_has_no_factory_raw_material(self):
        with erp.connect(True) as c:
            b={'kind':'product','create':True,'id':'OIL','name':'油豆腐','unit':'盒','billing_unit':'盒','price':'3','tare':'0','supply_kind':'purchased','main_material':''}
            # Validate within a savepoint, just as the HTTP transaction rolls back failed writes.
            c.execute('SAVEPOINT missing_supplier')
            with self.assertRaisesRegex(ValueError,'供应商'):erp.master(b,'管理员',connection=c)
            c.execute('ROLLBACK TO missing_supplier');c.execute('RELEASE missing_supplier')
            supplier=purchasing.Operations(c,erp.now,erp.audit).supplier({'name':'油豆腐供应商','category_ids':['SC-FINISHED'],'payment_days':0},'管理员')
            erp.master({**b,'supplier_ids':[supplier['id']]},'管理员',connection=c)
            p=next(p for p in erp.ordered_products(c) if p['id']=='OIL');self.assertEqual(p['supplier_ids'],[supplier['id']]);self.assertEqual(trade.metadata(c,'product_main_materials')['OIL'],'');self.assertEqual(p['supply_kind'],'purchased')
