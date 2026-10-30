import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ops import business_check


class BusinessCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / 'business.db'
        # Current business table shapes, intentionally independent of server.py,
        # auth initialization, migrations, and the application's demonstration data.
        with sqlite3.connect(self.database) as c:
            c.executescript('''
                CREATE TABLE customers(id TEXT PRIMARY KEY,name TEXT NOT NULL,route TEXT NOT NULL,note TEXT NOT NULL,
                  legal_name TEXT NOT NULL DEFAULT '',delivery_method TEXT NOT NULL DEFAULT 'delivery',
                  region TEXT NOT NULL DEFAULT '',market_id TEXT NOT NULL DEFAULT '',location_kind TEXT NOT NULL DEFAULT 'independent');
                CREATE TABLE products(id TEXT PRIMARY KEY,name TEXT NOT NULL,unit TEXT NOT NULL,price TEXT NOT NULL,tare TEXT NOT NULL,standard_kg TEXT);
                CREATE TABLE orders(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE receipts(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE sales_returns(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE statement_documents(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,customer_id TEXT NOT NULL,
                  business_date TEXT NOT NULL,issued_at TEXT NOT NULL,payload TEXT NOT NULL,content_hash TEXT NOT NULL);
                CREATE TABLE archived_orders(id TEXT PRIMARY KEY,payload TEXT NOT NULL,kept_id TEXT NOT NULL,reason TEXT NOT NULL,archived_at TEXT NOT NULL);
                CREATE TABLE trial_archives(id TEXT PRIMARY KEY,payload TEXT NOT NULL,at TEXT NOT NULL,reason TEXT NOT NULL,restored_at TEXT);
            ''')
        self.seed()

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self):
        with sqlite3.connect(self.database) as c:
            for table in ('customers', 'products', 'orders', 'receipts', 'sales_returns',
                          'statement_documents', 'archived_orders', 'trial_archives'):
                c.execute('DELETE FROM '+table)
            c.executemany('INSERT INTO customers(id,name,route,note) VALUES(?,?,?,?)',
                          [('C001', '敏感客户姓名甲', '测试点', '不可输出的客户凭据'),
                           ('C002', '敏感客户姓名乙', '测试点', '')])
            c.execute('INSERT INTO products VALUES(?,?,?,?,?,?)', ('P001', '当前产品名称', '筐', '3', '1', None))
            orders = [
                {'id': 'O1', 'customer_id': 'C001', 'customer_name': '保留历史客户名', 'state': 'reviewed',
                 'total_cents': 10000, 'paid_cents': 2000, 'return_credit_cents': 3000,
                 'lines': [{'product_id': 'P001', 'product_name': '保留历史产品名'}]},
                {'id': 'O2', 'customer_id': 'C002', 'state': 'reviewed', 'total_cents': 1000,
                 'paid_cents': 0, 'lines': [{'product_id': 'P001', 'product_name': '其他历史产品名'}]},
            ]
            c.executemany('INSERT INTO orders VALUES(?,?)', [(o['id'], json.dumps(o, ensure_ascii=False)) for o in orders])
            receipt = {'id': 'RC1', 'order_id': 'O1', 'customer_id': 'C001', 'amount_cents': 2000,
                       'note': '绝不能输出的银行凭据123456789'}
            c.execute('INSERT INTO receipts VALUES(?,?)', (receipt['id'], json.dumps(receipt, ensure_ascii=False)))
            returns = [
                {'id': 'RT1', 'customer_id': 'C001', 'product_id': 'P001', 'finance':
                    {'state': 'posted', 'amount_cents': 4000, 'allocations': [{'order_id': 'O1', 'amount_cents': 3000}],
                     'refunds': [{'id': 'RF1', 'amount_cents': 500, 'note': '退款私密凭据'}]}},
                {'id': 'RT2', 'customer_id': 'C001', 'product_id': 'P001', 'finance':
                    {'state': 'pending_review', 'amount_cents': 900000, 'allocations': [], 'refunds': []}},
                {'id': 'RT3', 'customer_id': 'C002', 'product_id': 'P001', 'voided': True, 'finance': None},
            ]
            c.executemany('INSERT INTO sales_returns VALUES(?,?)', [(r['id'], json.dumps(r, ensure_ascii=False)) for r in returns])
            raw = json.dumps({'customer': {'name': '敏感客户姓名甲'}, 'parties': {'note': '归档客户凭据'}}, ensure_ascii=False)
            c.execute('INSERT INTO statement_documents VALUES(?,?,?,?,?,?,?)',
                      ('DZ1', 'request-key', 'C001', '2026-10-21', '2026-10-21T12:00:00', raw, hashlib.sha256(raw.encode()).hexdigest()))
            # These records belong to earlier rounds and must never be added to
            # current receipt/credit balances or checked against today's masters.
            c.execute('INSERT INTO archived_orders VALUES(?,?,?,?,?)',
                      ('OLD1', json.dumps({'id': 'OLD1', 'customer_id': 'old-removed-customer',
                                          'lines': [{'product_id': 'old-removed-product'}], 'paid_cents': 999999}),
                       'old-kept', 'old round', '2025-01-01'))
            c.execute('INSERT INTO trial_archives VALUES(?,?,?,?,NULL)',
                      ('OLD-ROUND', json.dumps({'rows': {'receipts': [{'id': 'old-receipt', 'payload': '{historical unparsed payload}'}]}}),
                       '2025-01-01', 'old round'))

    def change_payload(self, table, record_id, change):
        with sqlite3.connect(self.database) as c:
            value = json.loads(c.execute('SELECT payload FROM '+table+' WHERE id=?', (record_id,)).fetchone()[0])
            change(value)
            c.execute('UPDATE '+table+' SET payload=? WHERE id=?', (json.dumps(value, ensure_ascii=False), record_id))

    def error_types(self):
        report = business_check.check_database(self.database)
        self.assertFalse(report['ok'])
        text = json.dumps(report, ensure_ascii=False)
        for secret in ('敏感客户姓名', '123456789', '客户凭据', str(self.database)):
            self.assertNotIn(secret, text)
        return {e['type'] for e in report['errors']}

    def test_valid_data_historical_names_and_other_rounds_pass_without_writes(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        report = business_check.check_database(self.database)
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['read_only'])
        self.assertEqual(report['error_count'], 0)
        self.assertEqual(report['counts']['orders'], 2)
        self.assertEqual(report['counts']['archived_orders_excluded'], 1)
        self.assertEqual(report['counts']['trial_archives_excluded'], 1)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)

    def test_missing_active_customer_and_product_are_reported(self):
        self.change_payload('orders', 'O1', lambda o: o.update(customer_id='missing-customer'))
        self.change_payload('orders', 'O2', lambda o: o['lines'][0].update(product_id='missing-product'))
        types = self.error_types()
        self.assertIn('orders.customer_missing', types)
        self.assertIn('orders.product_missing', types)

    def test_orphan_receipt_and_cross_customer_receipt_are_reported(self):
        self.change_payload('receipts', 'RC1', lambda r: r.update(order_id='missing-order'))
        self.assertIn('receipts.order_missing', self.error_types())
        self.seed()
        self.change_payload('receipts', 'RC1', lambda r: r.update(customer_id='C002'))
        self.assertIn('receipts.customer_mismatch', self.error_types())

    def test_paid_and_credit_counters_are_reconciled_to_source_flows(self):
        self.change_payload('orders', 'O1', lambda o: o.update(paid_cents=2001, return_credit_cents=3001))
        types = self.error_types()
        self.assertIn('orders.paid_receipts_mismatch', types)
        self.assertIn('orders.return_credit_allocations_mismatch', types)

    def test_overspent_return_wallet_and_negative_receivable_are_reported(self):
        self.change_payload('sales_returns', 'RT1', lambda r: r['finance']['refunds'][0].update(amount_cents=2000))
        self.change_payload('orders', 'O1', lambda o: o.update(total_cents=100))
        types = self.error_types()
        self.assertIn('returns.negative_wallet', types)
        self.assertIn('orders.negative_receivable', types)

    def test_return_allocation_must_reference_reviewed_order_of_same_customer(self):
        self.change_payload('sales_returns', 'RT1', lambda r: r['finance']['allocations'][0].update(order_id='O2'))
        self.assertIn('returns.allocation_customer_mismatch', self.error_types())
        self.seed()
        self.change_payload('sales_returns', 'RT1', lambda r: r['finance']['allocations'][0].update(order_id='missing-order'))
        self.assertIn('returns.allocation_order_missing', self.error_types())
        self.seed()
        self.change_payload('orders', 'O1', lambda o: o.update(state='ready'))
        types = self.error_types()
        self.assertIn('returns.allocation_order_not_reviewed', types)
        self.assertIn('receipts.order_not_reviewed', types)

    def test_pending_returns_cannot_allocate_or_refund_credit(self):
        self.change_payload('sales_returns', 'RT2', lambda r: r['finance']['allocations'].append({'order_id': 'O1', 'amount_cents': 1}))
        self.assertIn('returns.unposted_has_allocations_or_refunds', self.error_types())

    def test_voided_return_allows_reversed_credit_but_not_live_finance(self):
        reversed_finance = {'state': 'reversed', 'amount_cents': 3000, 'allocations': [],
                            'refunds': [], 'reversed_allocations': [{'order_id': 'O1', 'amount_cents': 3000}]}
        self.change_payload('sales_returns', 'RT3', lambda r: r.update(finance=reversed_finance))
        report = business_check.check_database(self.database)
        self.assertTrue(report['ok'], report)
        self.change_payload('sales_returns', 'RT3', lambda r: r['finance'].update(state='posted'))
        self.assertIn('returns.voided_has_finance', self.error_types())

    def test_statement_hash_and_malformed_current_payload_are_reported(self):
        with sqlite3.connect(self.database) as c:
            c.execute("UPDATE statement_documents SET content_hash='invalid'")
            c.execute("UPDATE orders SET payload='invalid json' WHERE id='O2'")
        types = self.error_types()
        self.assertIn('statements.content_hash_mismatch', types)
        self.assertIn('orders.invalid_payload', types)

    def test_missing_database_is_not_created_and_cli_sets_failure_exit_status(self):
        missing = Path(self.tmp.name) / 'must-not-create.db'
        report = business_check.check_database(missing)
        self.assertFalse(report['ok'])
        self.assertFalse(missing.exists())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = business_check.main(['--database', str(missing)])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out.getvalue())['ok'])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = business_check.main(['--database', str(self.database)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())['ok'])


if __name__ == '__main__':
    unittest.main()
