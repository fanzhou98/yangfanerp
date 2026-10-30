import unittest,uuid
import test_inventory as fixture
import inventory as inv,resources_costs as rc

erp=fixture.erp
class ReturnReuseTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    ops=fixture.InventoryTests.ops
    plan=fixture.InventoryTests.plan
    snapshot=fixture.InventoryTests.snapshot
    ret=fixture.InventoryTests.ret
    act=fixture.InventoryTests.act
    close_day=fixture.InventoryTests.close_day
    def dispose(self,r,kind='restock',**extra):
        return self.act(r,'dispose','库管',**{'business_date':'2026-10-21','kind':kind,'qty':'1','net_kg':'10','stock_qty':'1','handler':'库管','note':'退货批次核对记录001','inspection_checked':True,'inspection_note':'外观气味及保存状况核对，可用于所选用途','expiry_date':'2026-10-23',**extra})
    def test_restock_partial_and_no_double_consumption_or_finance_change(self):
        self.plan();r=self.ret(qty='2',net_kg='20');r=self.dispose(r)
        stock=self.snapshot()['products'][0];self.assertEqual((stock['supply_qty'],stock['quarantine_qty'],stock['quarantine_kg']),('16','1','10'));self.assertIsNone(r['finance'])
        with self.assertRaisesRegex(ValueError,'版本|其他页面'):self.dispose({**r,'version':1})
        r=self.dispose(r);self.assertEqual(self.snapshot()['products'][0]['supply_qty'],'17');self.assertEqual(inv.remaining_return(r),(0,0))
        with self.assertRaisesRegex(ValueError,'隔离库存'):self.dispose(r)
        self.close_day();next_stock=self.snapshot('2026-10-22')['products'][0];self.assertEqual(next_stock['opening_qty'],'17');self.assertEqual(next_stock['return_restock_qty'],'0')
    def test_restock_requires_inspection_valid_date_and_same_unit_quantity(self):
        r=self.ret()
        for extra,reason in [({'inspection_checked':False},'检验'),({'inspection_note':''},'检验'),({'expiry_date':'2026-10-20'},'有效期'),({'stock_qty':'2'},'数量一致')]:
            with self.assertRaisesRegex(ValueError,reason):self.dispose(r,**extra)
        with erp.connect() as c:self.assertEqual(len(inv.get(c,'sales_returns',r['id'])['disposals']),0)
        merchant=self.ret(receipt_mode='merchant_disposed')
        with self.assertRaisesRegex(ValueError,'商户自行处置'):self.dispose(merchant)
    def test_reprocess_pending_actual_output_link_and_reverse(self):
        self.plan();r=self.ret(product_id='P004',qty='2',net_kg='20');r=self.dispose(r,'reprocess',qty='2',net_kg='20')
        d=r['disposals'][0];batch_id=d['processing_batch_id']
        with erp.connect() as c:b=inv.get(c,'processing_batches',batch_id)
        self.assertEqual(b['state'],'pending');self.assertEqual(inv.remaining_return(r),(0,0));self.assertEqual(self.snapshot()['products'][3]['book_qty'],'15')
        self.plan('2026-10-22');updated=self.ops('process_update',{'id':b['id'],'version':1,'business_date':'2026-10-22','product_id':'P004','input_kg':'20','outputs':[{'product_id':'P005','qty':'3','net_kg':'18'}]})
        self.assertEqual(updated['origin'],'customer_return');self.assertEqual(updated['state'],'completed')
        with erp.connect() as c:linked=inv.get(c,'sales_returns',r['id'])
        self.assertTrue(linked['disposals'][0]['processing_completed']);self.assertEqual(linked['disposals'][0]['processing_date'],'2026-10-22')
        stock={p['product_id']:p for p in self.snapshot('2026-10-22')['products']};self.assertEqual(stock['P004']['book_qty'],'15');self.assertEqual(stock['P005']['book_qty'],'18')
        self.ops('process_delete',{'id':updated['id'],'version':2,'reason':'实际未加工，撤销转入'})
        with erp.connect() as c:restored=inv.get(c,'sales_returns',r['id'])
        self.assertEqual(inv.remaining_return(restored),(2,20));self.assertTrue(restored['disposals'][0]['voided'])
        self.assertEqual(next(p for p in self.snapshot('2026-10-22')['products'] if p['product_id']=='P005')['book_qty'],'15')
    def test_unlinked_processing_cannot_take_return_without_source(self):
        with self.assertRaisesRegex(ValueError,'退货台账'):self.ops('process',{'business_date':'2026-10-21','product_id':'P004','origin':'customer_return','input_kg':'20','outputs':[{'product_id':'P005','qty':'3','net_kg':'18'}]})
    def test_closed_day_prevents_release_or_reprocess(self):
        self.plan();r=self.ret();self.close_day()
        with self.assertRaisesRegex(ValueError,'日结'):self.dispose(r)

    def test_bulk_kilogram_return_uses_measured_weight_and_marks_cost_gap(self):
        with erp.connect(True) as c:c.execute("UPDATE products SET unit='公斤' WHERE id='P004'")
        self.plan();r=self.ret(product_id='P004',qty='0',net_kg='10');r=self.dispose(r,qty='0',net_kg='10',stock_qty='10')
        p=next(p for p in self.snapshot()['products'] if p['product_id']=='P004');self.assertEqual(p['return_restock_qty'],'10')
        import product_profit
        with erp.connect() as c:report=product_profit.month(c,'2026-10')
        self.assertTrue(any('退货回可发' in g['field'] for g in report['gaps']))

    def test_restocked_goods_can_be_allocated_and_shipped(self):
        self.plan(opening='0',production='0');r=self.ret();self.dispose(r)
        order=erp.mutate('order',{'customer_id':'C002','business_date':'2026-10-21','batch':'日常订货','lines':[{'product_id':'P001','ordered_qty':'1','actual_qty':'0','price':'3','driver':[],'customer':[]}]},'库管')
        data=erp.bootstrap();plan=data['warehouse_plans'][0]
        result=erp.save_warehouse({'business_date':'2026-10-21','stage':'confirm_dispatch','version':plan['version'],'inventory_revision':data['inventory_revision'],'evidence_checked':True,'order_versions':{order['id']:order['version']},'stock':plan['stock'],'allocations':[{'order_id':order['id'],'product_id':'P001','qty':'1','ordered_qty':'1'}],'customers':[]},'库管')
        self.assertEqual(result['orders'][0]['lines'][0]['actual_qty'],'1');self.assertEqual(self.snapshot()['products'][0]['book_qty'],'0')

    def test_void_dispose_restores_quarantine_and_supply(self):
        self.plan(); r = self.ret(qty='2', net_kg='20'); r = self.dispose(r)
        self.assertEqual(self.snapshot()['products'][0]['supply_qty'], '16')
        d = r['disposals'][0]
        with self.assertRaisesRegex(ValueError, '撤销原因'):
            self.act(r, 'void-dispose', '库管', disposal_id=d['id'], reason='')
        r = self.act(r, 'void-dispose', '库管', disposal_id=d['id'], reason='处置登记重复')
        self.assertTrue(r['disposals'][0]['voided'])
        self.assertEqual(tuple(map(int, inv.remaining_return(r))), (2, 20))
        self.assertEqual(self.snapshot()['products'][0]['supply_qty'], '15')
        with self.assertRaisesRegex(ValueError, '已撤销'):
            self.act(r, 'void-dispose', '库管', disposal_id=d['id'], reason='再次撤销')
