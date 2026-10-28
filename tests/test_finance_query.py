"""Q02 receivable ledger server reads: scoped filters, totals and stable pages."""
from datetime import date, timedelta
import unittest
import finance_query
import test_workflow as fixture

erp = fixture.erp


class FinanceQueryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowTests(); self.old = erp.DB; self.case.setUp()
        with erp.connect(True) as c:
            for table in ('orders', 'receipts', 'byproduct_sales'):
                c.execute('DELETE FROM ' + table)
            c.execute("INSERT OR IGNORE INTO delivery_markets(id,name,city) VALUES('M-Q02','测试市场','测试城')")
            for i in range(120):
                cid = f'QC{i % 3:03d}'; day = (date(2026, 9, 1) + timedelta(days=i % 40)).isoformat()
                c.execute("INSERT OR REPLACE INTO customers(id,name,route,note,delivery_method,legal_name,business_kind,region,market_id) VALUES(?,?,?,?,?,?,?,?,?)",
                          (cid, f'客户{i % 3}', '线路A', '', 'delivery', f'客户{i % 3}', 'sales', '城区', 'M-Q02'))
                paid = 10000 if i < 30 else 0
                order = {'id': f'QO{i:03d}', 'version': 2, 'customer_id': cid, 'customer_name': f'客户{i % 3}',
                         'business_date': day, 'state': 'reviewed', 'total_cents': 10000, 'paid_cents': paid,
                         'return_credit_cents': 0, 'discount_cents': 0, 'rounding_cents': 0,
                         'lines': [{'product_id': 'P001', 'product_name': '产品', 'unit': '筐', 'billing_unit': '公斤',
                                    'ordered_qty': '10', 'actual_qty': '10', 'bill_qty': '10', 'amount_cents': 10000}]}
                c.execute('INSERT INTO orders VALUES(?,?)', (order['id'], erp.dumps(order)))
                if paid:
                    receipt = {'id': f'QR{i:03d}', 'order_id': order['id'], 'customer_id': cid, 'customer_name': order['customer_name'],
                               'received_date': '2026-10-05', 'amount_cents': paid, 'discount_cents': 0, 'rounding_cents': 0,
                               'method': '银行转账', 'note': '测试'}
                    c.execute('INSERT INTO receipts VALUES(?,?)', (receipt['id'], erp.dumps(receipt)))
            for i in range(10):
                cid = 'QC000'
                paid = 2000 if i < 5 else 0
                buyer = '豆渣测试客户'
                c.execute("INSERT OR REPLACE INTO customers(id,name,route,note,delivery_method,legal_name,business_kind) VALUES(?,?,?,?,?,?,?)",
                          ('BY-Q02', buyer, '豆渣自取', '', 'pickup', buyer, 'byproduct'))
                record = {'id': f'QB{i:03d}', 'business_date': '2026-09-20', 'customer_id': 'BY-Q02', 'buyer': buyer,
                          'qty': '10', 'unit': '公斤', 'price': '5', 'amount_cents': 5000, 'received_cents': paid,
                          'receipts': ([{'business_date': '2026-10-06', 'amount_cents': paid}] if paid else []),
                          'voided': False, 'version': 1, 'created_at': '2026-09-20T12:00:00+08:00'}
                c.execute('INSERT INTO byproduct_sales(id,request_key,payload) VALUES(?,?,?)',
                          (record['id'], 'req-' + record['id'], erp.dumps(record)))
            c.execute("INSERT INTO orders VALUES('QO-DRAFT',?)", (erp.dumps({'id': 'QO-DRAFT', 'business_date': '2026-09-02', 'state': 'draft', 'customer_id': 'QC000', 'total_cents': 9999}),))

    def tearDown(self):
        self.case.tearDown(); erp.DB = self.old

    def report(self, **kw):
        with erp.connect() as c:
            return finance_query.ledger(c, kw.pop('start', '2026-09-01'), kw.pop('end', '2026-10-31'), **kw)

    def test_all_dates_include_later_byproduct_sales_and_actual_receipts(self):
        with erp.connect(True) as c:
            record={'id':'QB-LATER','version':1,'business_date':'2026-11-30','customer_id':'BY-Q02','buyer':'豆渣测试客户','qty':'10','unit':'公斤','price':'5','amount_cents':5000,'received_cents':1000,'receipts':[{'business_date':'2026-12-04','amount_cents':1000}]}
            c.execute('INSERT INTO byproduct_sales VALUES(?,?,?)',(record['id'],'req-later',erp.dumps(record)))
        result=self.report(all_dates=True,source='byproduct',customer_id='BY-Q02',clearance='all')
        self.assertIn('QB-LATER',[r['id'] for r in result['rows']])
        self.assertEqual(result['end'],'2026-12-04')
        self.assertIn('QB-LATER',[r['order_id'] for r in result['receipts']])

    def test_summary_covers_all_filtered_rows_not_only_page(self):
        result = self.report(clearance='all', page=1, page_size=50)
        self.assertEqual(result['total'], 130)
        self.assertEqual(result['summary']['count'], 130)
        self.assertEqual(result['summary']['total_cents'], 1250000)
        self.assertEqual(result['summary']['paid_cents'], 310000)
        self.assertEqual(result['summary']['outstanding_cents'], 940000)
        self.assertEqual(len(result['rows']), 50)
        self.assertEqual(result['pages'], 3)
        self.assertEqual(result['receipt_total'], 35)
        self.assertEqual(result['receipt_summary']['amount_cents'], 310000)

    def test_pages_are_stable_without_missing_or_duplicate_orders(self):
        seen = []
        for page in (1, 2, 3):
            result = self.report(clearance='all', page=page, page_size=50)
            self.assertEqual(result['page'], page)
            seen.extend(row['id'] for row in result['rows'])
        self.assertEqual(len(seen), 130)
        self.assertEqual(len(set(seen)), 130)

    def test_clearance_source_market_customer_search_and_byproduct_are_scoped(self):
        opened = self.report(page=1, page_size=50)
        self.assertEqual(opened['total'], 100)
        self.assertTrue(all(row['outstanding_cents'] > 0 for row in opened['rows']))
        self.assertEqual(opened['receipt_total'], 35)
        self.assertEqual(opened['receipt_summary']['amount_cents'], 310000)
        byproduct = self.report(source='byproduct', clearance='all', page=1, page_size=50)
        self.assertEqual(byproduct['total'], 10)
        self.assertTrue(all(row['is_byproduct'] and row['market'] == '豆渣客户' for row in byproduct['rows']))
        sales = self.report(source='sales', customer_id='QC001', clearance='all', page=1, page_size=50)
        self.assertEqual(sales['total'], 40)
        self.assertTrue(all(row['customer_id'] == 'QC001' for row in sales['rows']))
        self.assertEqual(self.report(market='测试市场', clearance='all')['total'], 120)
        self.assertEqual(self.report(query='客户2', clearance='all')['total'], 40)
        self.assertEqual(self.report(query='QB00', clearance='all')['total'], 10)
        cleared = self.report(clearance='cleared', page=1, page_size=50)
        self.assertEqual(cleared['total'], 30)

    def test_receipts_use_actual_date_range_and_page_independently(self):
        result = self.report(start='2026-09-01', end='2026-09-30', receipt_start='2026-10-01', receipt_end='2026-10-31',
                             clearance='all', page=1, receipt_page=1, page_size=50)
        self.assertEqual(result['receipt_total'], 35)
        self.assertEqual(len(result['receipts']), 35)
        self.assertEqual(result['receipt_start'], '2026-10-01')
        result = self.report(start='2026-09-01', end='2026-09-30', receipt_start='2026-10-01', receipt_end='2026-10-02',
                             clearance='all', page=1, receipt_page=1, page_size=50)
        self.assertEqual(result['receipt_total'], 0)
        self.assertEqual(result['receipts'], [])

    def test_all_dates_bounds_and_invalid_inputs(self):
        result = self.report(start='2000-01-01', end='2000-01-02', all_dates=True, clearance='all', page=1)
        self.assertEqual((result['start'], result['end']), ('2026-09-01', '2026-10-10'))
        for kw in ({'page': 0}, {'page_size': 201}, {'source': 'bad'}, {'clearance': 'bad'},
                   {'start': '2026-09-02', 'end': '2026-09-01'}):
            with self.assertRaises(ValueError):
                self.report(**kw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
