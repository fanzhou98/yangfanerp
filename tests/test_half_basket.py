"""Half a basket of goods uses one whole reusable crate."""
import unittest
from decimal import Decimal
import test_warehouse as fixture
import billing
import trade

erp=fixture.erp

class HalfBasketTests(fixture.WarehouseTests):
    def basket_order(self,qty='0.5',**extra):
        return erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-21','batch':'半筐验证','lines':[{'product_id':'P001','ordered_qty':qty,'actual_qty':qty,'price':'3','driver':[{'gross':'11','count':'1','tare':'1'}],'customer':[{'gross':'11','count':'1','tare':'1'}],'crate_lines':[] if extra.get('actual_qty')=='0' else [{'asset_id':'CR-WHITE','qty':'1','tare':'1'}],**extra}]},'库管')

    def test_half_opening_and_production_round_trip(self):
        saved=erp.save_warehouse({'business_date':'2026-10-21','version':0,'stage':'stock','stock':[{'product_id':'P001','existing_qty':'0.5','produced_qty':'0.5'}],'order_versions':{},'allocations':[]},'库管')
        row=saved['stock'][0]
        self.assertEqual((row['existing_qty'],row['produced_qty']),('0.5','0.5'))
        self.assertEqual(erp.bootstrap()['warehouse_plans'][0]['stock'],saved['stock'])

    def test_half_goods_ship_in_one_whole_crate(self):
        order=self.basket_order();line=order['lines'][0]
        self.assertEqual(line['actual_qty'],'0.5')
        self.assertEqual(line['driver_count'],'1')
        self.assertEqual(line['driver_net'],'10')
        with erp.connect() as c:
            self.assertEqual(sum(x['qty'] for x in trade.shipped_crates(c,order)),1)
        self.assertEqual(billing.settlement_net(line,'customer',{'customer':'2'}),Decimal('10'))
        self.assertEqual(billing.settlement_net({**line,'crate_lines':[]},'customer',{'customer':'2'}),Decimal('9'))

    def test_half_allocation_commits_and_deducts_half_goods(self):
        order=self.basket_order('1',actual_qty='0',driver=[],customer=[])
        saved=erp.save_warehouse({'business_date':'2026-10-21','version':0,'stage':'confirm_dispatch','evidence_checked':True,'stock':[{'product_id':'P001','existing_qty':'0.5','produced_qty':'0.5'}],'order_versions':{order['id']:order['version']},'allocations':[{'order_id':order['id'],'product_id':'P001','ordered_qty':'1','qty':'0.5'}]},'库管')
        current=next(o for o in erp.bootstrap()['orders'] if o['id']==order['id'])
        self.assertEqual(current['lines'][0]['actual_qty'],'0.5')
        import inventory
        with erp.connect() as c:
            row=next(r for r in inventory.stock(c,'2026-10-21')['products'] if r['product_id']=='P001')
        self.assertEqual(row['book_qty'],'0.5')

    def test_quarter_basket_is_rejected(self):
        with self.assertRaises(ValueError):self.basket_order('0.25')

    def test_physical_crate_stays_whole(self):
        with self.assertRaises(ValueError):self.basket_order(driver=[{'gross':'11','count':'0.5','tare':'1'}])

    def test_half_goods_settle_review_and_customer_crate_balance(self):
        order=self.basket_order()
        order=erp.mutate('settle',{'version':order['version'],'mode':'customer'},'会计',order['id'])
        self.assertEqual(order['lines'][0]['bill_qty'],'10')
        order=erp.mutate('review',{'version':order['version'],'evidence_checked':True},'出纳',order['id'])
        self.assertEqual(order['total_cents'],3000)
        with erp.connect() as c:
            report=trade.customer_crates(c,'C001','2026-10-21')
        self.assertFalse(report['issues'])
        self.assertEqual(sum(r['shipped_qty'] for r in report['rows']),1)
