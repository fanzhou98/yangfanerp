import copy,unittest
import test_inventory as fixture
import billing_migration,inventory
from decimal import Decimal
erp=fixture.erp

class KilogramBillingTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    ops=fixture.InventoryTests.ops
    ret=fixture.InventoryTests.ret
    act=fixture.InventoryTests.act
    def enable(self):
        with erp.connect(True) as c:return billing_migration.migrate(c,erp.now,erp.audit)
    def epoch(self):return erp.bootstrap()['business_data_epoch']
    def order(self,qty='2',net=''):
        return erp.mutate('order',{'_data_epoch':self.epoch(),'customer_id':'C001','business_date':'2026-10-21','batch':'公斤口径验证','lines':[{'product_id':'P004','ordered_qty':qty,'actual_qty':qty,'price':'7.5','package_net_kg':net,'driver':[],'customer':[]}]},'库管')
    def settle(self,o):return erp.mutate('settle',{'_data_epoch':self.epoch(),'version':o['version'],'mode':'customer','reason':''},'会计',o['id'])
    def test_package_standard_in_kg_keeps_same_sale_amount(self):
        self.enable();o=self.settle(self.order());l=o['lines'][0]
        self.assertEqual((l['actual_qty'],l['bill_qty'],l['billing_unit'],l['price'],l['amount_cents']),('2','20','公斤','7.5',15000))
        self.assertEqual(l['settlement_mode'],'package_standard')
    def test_explicit_measured_package_kg_overrides_standard_and_is_retained(self):
        self.enable();o=self.settle(self.order(net='18.6'));l=o['lines'][0]
        self.assertEqual((l['bill_qty'],l['amount_cents'],l['settlement_mode']),('18.6',13950,'package_actual'))
        self.assertEqual(l['package_net_kg'],'18.6')
        with self.assertRaises(ValueError):self.order(net='-1')
    def test_package_return_requires_actual_kg_and_finance_cannot_exceed_it(self):
        self.enable();o=self.settle(self.order())
        with self.assertRaises(ValueError):self.ret(product_id='P004',qty='1',net_kg='0',order_id=o['id'])
        r=self.ret(product_id='P004',qty='1',net_kg='8.2',order_id=o['id'])
        self.assertEqual((r['billing_unit'],r['source_price'],r['net_kg']),('公斤','7.5','8.2'))
        opts={'account_date':'2026-10-21','price':'7.5','price_checked':True,'note':'核对原价，按实退公斤数'}
        with self.assertRaises(ValueError):self.act(r,'account',account_qty='8.3',**opts)
        r=self.act(r,'account',account_qty='8',**opts)
        self.assertEqual((r['finance']['account_weight_kg'],r['finance']['billing_unit'],r['finance']['amount_cents']),('8','公斤',6000))
        self.assertEqual(r['net_kg'],'8.2')
    def test_migration_converts_rules_and_order_snapshots_without_changing_amount(self):
        with erp.connect(True) as c:
            c.execute("INSERT INTO rules VALUES('C001','P004','80','0')")
            c.execute("INSERT INTO products VALUES('P008','五公斤包装','包','6.3','0','5')")
        o=erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-21','batch':'旧包价','lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'2','price':'75','driver':[],'customer':[]}]},'库管')
        o=erp.mutate('settle',{'version':o['version'],'mode':'customer','reason':''},'会计',o['id'])
        self.assertEqual(o['total_cents'],15000)
        self.enable();d=erp.bootstrap();new=d['orders'][0];l=new['lines'][0]
        self.assertEqual((new['total_cents'],l['price'],l['bill_qty'],l['actual_qty']),(15000,'7.5','20','2'))
        self.assertEqual(next(p for p in d['products'] if p['id']=='P008')['price'],'1.26')
        self.assertEqual(next(r for r in d['rules'] if r['product_id']=='P004')['price'],'8')
        self.assertTrue(l['legacy_billing']);self.assertTrue(self.enable()['already_enabled'])
        with self.assertRaisesRegex(ValueError,'已经清理或恢复'):erp.mutate('order',copy.deepcopy(new),'库管',new['id'])
    def test_cumulative_return_weight_cannot_exceed_billed_kg(self):
        self.enable();o=self.settle(self.order(net='18'))
        self.ret(product_id='P004',qty='1',net_kg='10',order_id=o['id'])
        with self.assertRaisesRegex(ValueError,'累计退货净重'):
            self.ret(product_id='P004',qty='1',net_kg='9',order_id=o['id'])
    def test_price_conversion_failure_rolls_back_all_updates(self):
        with erp.connect(True) as c:c.execute("INSERT INTO products VALUES('P099','无法精确换算','包','1','0','3')")
        before=erp.bootstrap()
        with self.assertRaises(ValueError):self.enable()
        after=erp.bootstrap();self.assertEqual(before['products'],after['products']);self.assertEqual(before['business_data_epoch'],after['business_data_epoch'])

    def test_package_weight_survives_unrelated_order_revision(self):
        self.enable();o=self.order(net='18.6');body=copy.deepcopy(o);body['_data_epoch']=self.epoch();body['note']='补充备注';body['lines'][0].pop('package_net_kg')
        updated=erp.mutate('order',body,'库管',o['id']);self.assertEqual(updated['lines'][0]['package_net_kg'],'18.6')
