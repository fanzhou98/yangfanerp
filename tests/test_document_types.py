import unittest
import test_workflow as fixture
erp=fixture.erp
from printing import order_print_html

class DocumentTypeTests(unittest.TestCase):
    setUp=fixture.WorkflowTests.setUp
    tearDown=fixture.WorkflowTests.tearDown
    order=fixture.WorkflowTests.order

    def test_order_is_demand_only(self):
        o=self.order();h=order_print_html(erp.bootstrap(),{'date':[o['business_date']],'mode':['total'],'document':['order']},erp.now())
        self.assertIn('<h1>订货单</h1>',h)
        self.assertIn('客户 × 产品数量总表',h)
        self.assertNotIn('<th>现场实发</th>',h)
        self.assertNotIn('<th>毛重 kg</th>',h)
        self.assertIn('录单 / 备货',h)
        self.assertNotIn('发货 / 司机',h)

    def test_delivery_retains_actual_and_driver_gross(self):
        o=self.order();h=order_print_html(erp.bootstrap(),{'date':[o['business_date']],'mode':['total'],'document':['delivery']},erp.now())
        self.assertIn('<h1>配送单</h1>',h)
        self.assertNotIn('<th>现场实发</th>',h)
        self.assertNotIn('毛重 kg',h)
        self.assertNotIn('>222</td>',h);self.assertIn('data-quantity="10"',h)
        self.assertIn('本页合计',h)
        self.assertIn('发货 / 司机',h)
        self.assertNotIn('<th>分项金额</th>',h)

    def test_delivery_keeps_zero_products_and_continues_all_columns(self):
        o=self.order();data=erp.bootstrap()
        data['products']=[{'id':f'EX{i}', 'name':f'完整产品{i}', 'unit':'筐'} for i in range(23)]+data['products']
        h=order_print_html(data,{'date':[o['business_date']],'mode':['total'],'document':['delivery']},erp.now())
        for p in data['products']:self.assertIn(p['name'],h)
        pages=h.split('<section class="print-page">')[1:]
        self.assertEqual(len(pages),1)
        for page in pages:
            self.assertIn('备注 / 称重</th>',page)
            self.assertIn('<td class="handwritten"></td>',page)
            self.assertIn('客户',page)
        self.assertIn('data-quantity="0">—',h)
        self.assertIn('data-quantity="10">10',h)

    def test_unsupported_type_rejected(self):
        with self.assertRaises(ValueError):order_print_html(erp.bootstrap(),{'date':['2026-10-18'],'document':['statistics']},erp.now())

    def test_product_pages_are_balanced_and_twelve_fit_one_page(self):
        o=self.order();data=erp.bootstrap()
        data['products']=[{'id':f'TW{i}','name':f'产品{i:02d}','unit':'筐'} for i in range(12)]
        h=order_print_html(data,{'date':[o['business_date']],'mode':['total'],'document':['delivery']},erp.now())
        self.assertEqual(len(h.split('<section class="print-page">'))-1,1)
        self.assertNotIn('产品 1—',h)
        data['products']=[{'id':f'TH{i}','name':f'产品{i:02d}','unit':'筐'} for i in range(20)]
        h=order_print_html(data,{'date':[o['business_date']],'mode':['total'],'document':['delivery']},erp.now())
        self.assertEqual(len(h.split('<section class="print-page">'))-1,1)
        for p in data['products']:self.assertIn(p['name'],h)
        self.assertIn('style="width:10mm"',h)
