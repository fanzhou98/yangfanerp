"""Q01 sales range, indexed reads, full-filter totals and stable pages."""
from datetime import date, timedelta
import unittest
import sales_chain
import sales_query
import production_management as fm
import reporting
import test_workflow as fixture

erp = fixture.erp
START = '2026-08-01'
END = '2026-09-29'


class SalesQueryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowTests(); self.old = erp.DB; self.case.setUp()
        self.rows = []
        with erp.connect(True) as c:
            for table in ('orders', 'receipts', 'sales_returns', 'warehouse_plans', 'order_corrections', 'trade_records'):
                c.execute('DELETE FROM ' + table)
            for i in range(60):
                day = (date(2026, 8, 1) + timedelta(days=i)).isoformat()
                cid = f'QC{i:03d}'; pid = f'QP{i:03d}'; region = f'R{i:02d}'; market = f'M{i:02d}'
                c.execute("INSERT INTO customers(id,name,region,route,note,delivery_method,legal_name,business_kind) VALUES(?,?,?,?,?,?,?,?)",
                          (cid, f'客户{i:02d}', region, market, '', 'delivery', f'客户{i:02d}', 'sales'))
                amount = 100000 + (i % 5) * 1000
                order = {'id': f'QO{i:03d}', 'version': 2, 'customer_id': cid, 'customer_name': f'客户{i:02d}',
                         'business_date': day, 'state': 'reviewed', 'total_cents': amount, 'paid_cents': 0,
                         'return_credit_cents': 0, 'discount_cents': 0, 'rounding_cents': 0,
                         'lines': [{'product_id': pid, 'product_name': f'产品{i:02d}', 'unit': '筐', 'ordered_qty': '10',
                                    'actual_qty': '10', 'billing_unit': '公斤', 'bill_qty': '50', 'amount_cents': amount}]}
                c.execute('INSERT INTO orders VALUES(?,?)', (order['id'], erp.dumps(order)))
                self.rows.append(order)

    def tearDown(self):
        self.case.tearDown(); erp.DB = self.old

    def report(self, **kw):
        with erp.connect() as c:
            return fm.sales_report(c, kw.pop('start', START), kw.pop('end', END), **kw)

    def ids(self, view, **kw):
        result = self.report(view=view, paginate=True, page_size=7, **kw)
        key = {'customers': lambda r: r['customer_id'], 'alerts': lambda r: r['customer_id'],
               'products': lambda r: r['product_id'], 'markets': lambda r: (r['region'], r['market'], r['product_id']),
               'regions': lambda r: r['region']}[view]
        return [key(r) for r in result['rows']], result

    def test_indexed_date_and_customer_queries_use_expression_indexes(self):
        with erp.connect() as c:
            plan = ' '.join(str(tuple(r)) for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT payload FROM orders WHERE json_extract(payload,'$.business_date') BETWEEN ? AND ? ORDER BY json_extract(payload,'$.business_date'),id",
                (START, END)))
            self.assertIn('orders_business_date_id', plan)
            plan = ' '.join(str(tuple(r)) for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT payload FROM orders WHERE json_extract(payload,'$.customer_id')=? AND json_extract(payload,'$.business_date') BETWEEN ? AND ? ORDER BY json_extract(payload,'$.business_date'),id",
                ('QC010', START, END)))
            self.assertIn('orders_customer_business_date_id', plan)
            plan = ' '.join(str(tuple(r)) for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT json_extract(payload,'$.business_date') FROM orders WHERE json_extract(payload,'$.business_date') IS NOT NULL ORDER BY json_extract(payload,'$.business_date') ASC,id ASC LIMIT 1"))
            self.assertIn('orders_business_date_id', plan)
            self.assertEqual(len(sales_query.orders(c, START, END)), 60)
            self.assertEqual(len(sales_query.orders(c, START, END, customer_id='QC010')), 1)
            self.assertEqual(sales_query.bounds(c), (START, END))

    def test_each_tab_pages_without_missing_or_duplicate_rows(self):
        for view, expected in [('customers', 60), ('alerts', 60), ('products', 60), ('markets', 60), ('regions', 60)]:
            with self.subTest(view=view):
                result = self.report(view=view, paginate=True, page_size=7, page=1)
                self.assertEqual(result['total'], expected)
                self.assertEqual(result['pages'], 9)
                seen = []
                for page in range(1, result['pages'] + 1):
                    rows, page_result = self.ids(view, page=page)
                    self.assertEqual(page_result['page'], page)
                    seen.extend(rows)
                self.assertEqual(len(seen), 60)
                self.assertEqual(len(set(seen)), 60)
                self.assertGreaterEqual(result['summary']['sales_cents'] if view in ('customers', 'products', 'markets', 'regions') else result['summary']['outstanding_cents'], 0)

    def test_filtered_totals_cover_all_pages_and_page_is_clamped(self):
        result = self.report(view='products', paginate=True, page_size=7, product_id='QP010')
        self.assertEqual(result['total'], 1)
        result = self.report(view='customers', paginate=True, page_size=7, customer_id='QC010')
        self.assertEqual(result['total'], 1)
        result = self.report(view='markets', paginate=True, page_size=7, market='M10')
        self.assertEqual(result['total'], 1)
        result = self.report(view='customers', paginate=True, page_size=7, state='pending')
        self.assertEqual(result['total'], 0)
        result = self.report(view='alerts', paginate=True, page_size=7)
        self.assertEqual(result['total'], 60)
        result = self.report(view='customers', paginate=True, page_size=7, page=99)
        self.assertEqual(result['page'], result['pages'])
        self.assertEqual(result['total'], 60)
        result = self.report(view='customers', paginate=True, page_size=7, query='客户1')
        self.assertEqual(result['total'], 10)
        self.assertEqual(result['summary']['customer_count'], 10)

    def test_filter_changes_and_sort_are_stable(self):
        for page in (1, 2, 9):
            result = self.report(view='customers', paginate=True, page_size=7, page=page, sort='name')
            self.assertEqual(len(result['rows']), 7 if page < 9 else 4)
            self.assertEqual([r['customer_id'] for r in result['rows']], sorted([r['customer_id'] for r in result['rows']]))
        first = self.report(view='products', paginate=True, page_size=7, page=1)['rows']
        second = self.report(view='products', paginate=True, page_size=7, page=2)['rows']
        self.assertFalse({r['product_id'] for r in first} & {r['product_id'] for r in second})

    def test_legacy_full_lists_and_all_dates_bounds_are_preserved(self):
        result = self.report(view='customers')
        self.assertEqual(len(result['customers']), 60)
        self.assertEqual(result['rows'], [])
        with erp.connect() as c:
            decision = reporting.sales(c, '2026-01-01', '2026-01-02', all_dates=True)
            chain = sales_chain.report(c, '2026-01-01', '2026-01-02', all_dates=True, view='fulfillment', page=1, page_size=7)
        self.assertEqual((decision['start'], decision['end']), (START, END))
        self.assertEqual(chain['total'], 60)
        self.assertEqual(chain['summary']['orders'], 60)
        self.assertEqual(len(chain['rows']), 7)

    def test_invalid_page_and_date_bounds_are_rejected(self):
        for kw in ({'page': 0}, {'page_size': 0}, {'page_size': 201}, {'view': 'bad'}, {'state': 'bad'}, {'sort': 'bad'}):
            with self.assertRaises(ValueError):
                self.report(paginate=True, **kw)
        with erp.connect() as c:
            with self.assertRaises(ValueError):
                fm.sales_report(c, '2026-09-02', '2026-09-01', paginate=True)
            with self.assertRaises(ValueError):
                sales_query.resolve(c, '2000-01-01', '2026-01-01')


if __name__ == '__main__':
    unittest.main(verbosity=2)
