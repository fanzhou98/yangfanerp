import copy,json,unittest,uuid
from unittest.mock import patch
import test_assets as fixture
import assets,crate_accounting,trade,inventory

erp=fixture.fixture.erp
class CrateGroupTests(unittest.TestCase):
    setUp=fixture.AssetTests.setUp
    tearDown=fixture.AssetTests.tearDown
    save=fixture.AssetTests.save
    day='2030-01-05'
    def product_stock(self,qty='7'):
        return [{'product_id':'P001','product_name':'大豆腐','unit':'筐','counted_qty':qty,'shipped_qty':'10'}]
    def grouped(self,qty='7'):
        with patch.object(inventory,'stock',return_value={'products':self.product_stock(qty)}):return assets.report(self.c,self.day)
    def root(self,v):return next(x for x in v['crate_groups'] if x['id']=='P-LARGE')
    def test_attributes_are_managed_for_any_product_and_defaults_are_shared(self):
        parent=self.save('asset',dict(name='测试中豆腐框',category='周转筐'))
        child=self.save('asset',dict(name='小白框',category='周转筐',parent_asset_id=parent['id'],attribute_kind='spec',default_tare='1.25'))
        self.c.execute("INSERT INTO products VALUES('GROUP-P','测试产品','筐','3','1.8',NULL)")
        self.save('mapping',dict(product_id='GROUP-P',asset_ids=[child['id']]))
        self.assertEqual(crate_accounting.variants(self.c,'GROUP-P')[0]['parent_id'],parent['id'])
        self.assertEqual(crate_accounting.defaults(self.c,'C002','GROUP-P')[child['id']],'1.25')
        self.save('asset',dict(id=child['id'],version=child['version'],name='小白框改名',category='周转筐',default_tare='1.3'))
        self.assertEqual(next(a for a in assets.rows(self.c) if a['id']==child['id'])['parent_asset_id'],parent['id'])
        with self.assertRaisesRegex(ValueError,'同时选择'):crate_accounting.set_variants(self.c,'GROUP-P',[parent['id'],child['id']])
    def test_product_variant_tare_sits_between_customer_and_attribute_defaults(self):
        parent=self.save('asset',dict(name='产品皮重测试框',category='周转筐'))
        child=self.save('asset',dict(name='产品皮重红框',category='周转筐',parent_asset_id=parent['id'],attribute_kind='color',default_tare='1.2'))
        self.c.execute("INSERT INTO products VALUES('GROUP-T','产品皮重测试','筐','3','1.8',NULL)")
        self.save('mapping',dict(product_id='GROUP-T',asset_ids=[child['id']]))
        self.assertEqual(crate_accounting.defaults(self.c,'C002','GROUP-T')[child['id']],'1.2')
        crate_accounting.set_product_tares(self.c,'GROUP-T',{child['id']:'1.35'})
        self.assertEqual(crate_accounting.product_tares(self.c,'GROUP-T'),{child['id']:'1.35'})
        self.assertEqual(crate_accounting.defaults(self.c,'C002','GROUP-T')[child['id']],'1.35')
        crate_accounting.save_rules(self.c,[{'customer_id':'C002','product_id':'GROUP-T','variant_id':child['id'],'tare':'1.5','expected':None}],'管理员',erp.now,erp.audit)
        self.assertEqual(crate_accounting.defaults(self.c,'C002','GROUP-T')[child['id']],'1.5')
        with self.assertRaisesRegex(ValueError,'已选择'):crate_accounting.set_product_tares(self.c,'GROUP-T',{'CR-YELLOW':'1'})
        with self.assertRaisesRegex(ValueError,'三位小数'):crate_accounting.set_product_tares(self.c,'GROUP-T',{child['id']:'1.2345'})
        crate_accounting.set_variants(self.c,'GROUP-T',[])
        self.assertEqual(crate_accounting.product_tares(self.c,'GROUP-T'),{})

    def test_parent_group_and_children_do_not_double_count_legacy_counts(self):
        self.save('count',dict(asset_id='P-LARGE',business_date=self.day,empty_qty=20,damaged_qty=2))
        self.save('count',dict(asset_id='CR-WHITE',business_date=self.day,empty_qty=5,damaged_qty=1))
        v=self.grouped();g=self.root(v)
        self.assertEqual((g['occupied_qty'],g['empty_qty'],g['total_qty']),('7',20,'29'))
        self.assertEqual(g['unclassified']['empty_qty'],15);self.assertEqual(g['unclassified']['occupied_qty'],'7')
        self.assertTrue(next(x for x in g['attributes'] if x['id']=='CR-WHITE')['missing_products'])
    def test_group_physical_count_sum_checked_and_returns_not_added_again(self):
        b=dict(asset_id='P-LARGE',business_date=self.day,empty_qty=14,damaged_qty=1,unclassified_empty_qty=2,unclassified_damaged_qty=0,attribute_counts=[{'asset_id':'CR-WHITE','empty_qty':5,'damaged_qty':1},{'asset_id':'CR-YELLOW','empty_qty':7,'damaged_qty':0},{'asset_id':'CR-CLOTH','empty_qty':0,'damaged_qty':0}])
        with self.assertRaisesRegex(ValueError,'总数'):self.save('count',{**b,'empty_qty':15})
        self.save('count',b);self.save('movement',dict(asset_id='CR-WHITE',business_date=self.day,movement='return',qty=3,driver='测试司机'))
        g=self.root(self.grouped());self.assertEqual((g['empty_qty'],g['damaged_qty'],g['total_qty'],g['returned_qty']),(14,1,'22','3'))
        self.assertEqual(sum(x['empty_qty'] for x in g['attributes'])+g['unclassified']['empty_qty'],g['empty_qty'])
    def test_group_count_cannot_be_overridden_by_legacy_child_or_flat_total(self):
        b=dict(asset_id='P-LARGE',business_date=self.day,empty_qty=3,damaged_qty=0,attribute_counts=[{'asset_id':aid,'empty_qty':1,'damaged_qty':0} for aid in ('CR-WHITE','CR-YELLOW','CR-CLOTH')])
        group=self.save('count',b)
        with self.assertRaisesRegex(ValueError,'父框统一盘点'):self.save('count',dict(asset_id='CR-WHITE',business_date=self.day,empty_qty=8,damaged_qty=0))
        with self.assertRaisesRegex(ValueError,'不能覆盖'):self.save('count',dict(asset_id='P-LARGE',version=group['version'],business_date=self.day,empty_qty=8,damaged_qty=0))
    def test_occupied_attribute_split_must_match_product_count_and_be_current(self):
        b=dict(product_id='P001',business_date=self.day,inventory_revision=inventory.revision(self.c),lines=[{'asset_id':'CR-WHITE','qty':2},{'asset_id':'CR-YELLOW','qty':5}])
        with patch.object(inventory,'stock',return_value={'products':self.product_stock()}):
            with self.assertRaisesRegex(ValueError,'合计'):self.save('occupied-count',{**b,'lines':[{'asset_id':'CR-WHITE','qty':8}]})
            with self.assertRaisesRegex(ValueError,'库存已更新'):self.save('occupied-count',{**b,'inventory_revision':-1})
            self.save('occupied-count',b)
        g=self.root(self.grouped());self.assertEqual(g['occupied_qty'],'7');self.assertEqual(g['unclassified']['occupied_qty'],'0')
        self.assertEqual([x['occupied_qty'] for x in g['attributes'] if x['id'] in ('CR-WHITE','CR-YELLOW')],['5','2'])
        stale=self.root(self.grouped('8'));self.assertEqual(stale['occupied_qty'],'8');self.assertEqual(stale['unclassified']['occupied_qty'],'8')
    def test_frame_membership_cannot_change_after_use_and_has_no_cycles(self):
        b=dict(asset_id='CR-WHITE',business_date=self.day,empty_qty=0,damaged_qty=0);self.save('count',b)
        a=next(x for x in assets.rows(self.c) if x['id']=='CR-WHITE')
        with self.assertRaisesRegex(ValueError,'业务或盘点'):self.save('asset',dict(id=a['id'],version=a['version'],category='周转筐',name=a['name'],parent_asset_id='P-MEDIUM'))
        a=next(x for x in assets.rows(self.c) if x['id']=='P-LARGE')
        with self.assertRaisesRegex(ValueError,'循环或多层'):self.save('asset',dict(id=a['id'],version=a['version'],category='周转筐',name=a['name'],parent_asset_id='P-LARGE'))
    def test_conflicting_legacy_child_count_is_explicitly_pending(self):
        self.save('count',dict(asset_id='P-LARGE',business_date=self.day,empty_qty=2,damaged_qty=0));self.save('count',dict(asset_id='CR-WHITE',business_date=self.day,empty_qty=3,damaged_qty=0));g=self.root(self.grouped());self.assertIsNone(g['empty_qty']);self.assertIsNone(g['total_qty']);self.assertTrue(g['count_issues'])
    def test_new_product_defaults_apply_without_a_legacy_mapping_record(self):
        self.c.execute("INSERT INTO products VALUES('NEW-GROUP-P','新筐装产品','筐','3','1.8',NULL)")
        crate_accounting.set_variants(self.c,'NEW-GROUP-P',['CR-WHITE'])
        o={'id':'NEW-SHIP','lines':[{'product_id':'NEW-GROUP-P','unit':'筐','actual_qty':'3','customer':[]}]}
        shipment=trade.shipped_crates(self.c,o);self.assertEqual(shipment[0]['asset_id'],'CR-WHITE');self.assertEqual(shipment[0]['qty'],3)
    def test_multiple_parent_stock_split_is_required_and_sums_to_product_inventory(self):
        crate_accounting.set_variants(self.c,'P001',['CR-WHITE','P-MEDIUM'])
        v=self.grouped();self.assertEqual(v['unmapped'],[]);self.assertIsNone(self.root(v)['occupied_qty'])
        with patch.object(inventory,'stock',return_value={'products':self.product_stock()}):self.save('occupied-count',dict(product_id='P001',business_date=self.day,inventory_revision=inventory.revision(self.c),lines=[{'asset_id':'CR-WHITE','qty':3},{'asset_id':'P-MEDIUM','qty':4}]))
        v=self.grouped();self.assertEqual(self.root(v)['occupied_qty'],'3');self.assertEqual(next(x for x in v['crate_groups'] if x['id']=='P-MEDIUM')['occupied_qty'],'4')
        self.assertEqual(sum(int(x['occupied_qty']) for x in v['crate_groups']),7)
    def test_parent_default_tare_inherits_without_overwriting_customer_rule(self):
        parent=next(x for x in assets.rows(self.c) if x['id']=='P-LARGE')
        self.save('asset',dict(id=parent['id'],version=parent['version'],name=parent['name'],category='周转筐',default_tare='2.2'))
        self.assertEqual(crate_accounting.defaults(self.c,'C003','P001')['CR-WHITE'],'2.2')
        self.assertEqual(crate_accounting.defaults(self.c,'C002','P001')['CR-WHITE'],'1.7')
    def test_shipments_and_return_comparison_aggregate_attributes_once(self):
        o={'id':'T-SHIP','customer_id':'C001','customer_name':'测试客户','business_date':self.day,'delivery_method':'delivery','lines':[{'product_id':'P001','product_name':'大豆腐','unit':'筐','actual_qty':'3','crate_lines':[{'product_id':'P001','asset_id':'CR-WHITE','asset_name':'白框','qty':1,'tare':'1'},{'product_id':'P001','asset_id':'CR-YELLOW','asset_name':'黄框','qty':2,'tare':'2'}]}]}
        self.c.execute('INSERT INTO orders VALUES(?,?)',(o['id'],json.dumps(o)));g=self.root(self.grouped());self.assertEqual(g['shipped_qty'],'3');self.assertEqual(sum(int(x['shipped_qty']) for x in g['attributes']),3)
        v=assets.report(self.c,'2030-01-06');summary=next(x for x in v['comparison']['summary'] if x['asset_id']=='P-LARGE');self.assertEqual(summary['yesterday_qty'],'3')
