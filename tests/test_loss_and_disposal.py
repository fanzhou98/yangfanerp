import unittest,uuid
import test_inventory as fixture
import resources_costs as rc

erp=fixture.erp
class LossAndDisposalTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    ops=fixture.InventoryTests.ops
    plan=fixture.InventoryTests.plan
    snapshot=fixture.InventoryTests.snapshot
    ret=fixture.InventoryTests.ret
    act=fixture.InventoryTests.act
    close_day=fixture.InventoryTests.close_day
    def loss_body(self,loss='2'):
        data=erp.bootstrap();plan=data['warehouse_plans'][0]
        stock=[{**r,'loss_qty':loss if r['product_id']=='P001' else '0','loss_reason':'搬运损坏' if r['product_id']=='P001' else ''} for r in plan['stock']]
        return {'business_date':'2026-10-21','stage':'stock','version':plan['version'],'inventory_revision':data['inventory_revision'],'order_versions':{},'stock':stock,'allocations':[],'customers':[]}
    def test_loss_requires_reason_reduces_once_and_preserves_history(self):
        self.plan();body=self.loss_body();saved=erp.save_warehouse(body,'库管');self.assertEqual(self.snapshot()['products'][0]['book_qty'],'13')
        body=self.loss_body();erp.save_warehouse(body,'库管');self.assertEqual(self.snapshot()['products'][0]['book_qty'],'13')
        with self.assertRaises(ValueError):erp.save_warehouse(self.loss_body('16'),'库管')
        self.assertEqual(self.snapshot()['products'][0]['book_qty'],'13')
        body=self.loss_body('3');body['stock'][0]['loss_reason']=''
        with self.assertRaisesRegex(ValueError,'原因'):erp.save_warehouse(body,'库管')
        self.close_day()
        with self.assertRaisesRegex(ValueError,'日结'):erp.save_warehouse(self.loss_body('3'),'库管')
    def test_fractional_kg_disposal_and_both_balances_zero(self):
        with erp.connect(True) as c:c.execute("UPDATE products SET unit='公斤' WHERE id='P004'")
        r=self.ret(product_id='P004',qty='1.5',net_kg='1.5');self.assertEqual(r['unit'],'公斤')
        r=self.act(r,'dispose','库管',business_date='2026-10-21',kind='nonfood',qty='.5',net_kg='.5',note='非食用去向记录001',handler='库管')
        import inventory
        self.assertEqual(tuple(map(str,inventory.remaining_return(r))),('1.0','1.0'))
        r=self.act(r,'dispose','库管',business_date='2026-10-22',kind='destroy',qty='1',net_kg='1',note='余量销毁记录002',handler='库管')
        self.assertEqual(inventory.remaining_return(r),(0,0));self.assertEqual(len(r['disposals']),2)
