import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import billing
import test_workflow as fixture

erp = fixture.erp


class ProductionBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.previous_db = erp.DB
        self.tmp = tempfile.TemporaryDirectory()
        erp.DB = Path(self.tmp.name) / 'production.db'

    def tearDown(self):
        erp.DB = self.previous_db
        self.tmp.cleanup()

    def all_rows(self):
        with erp.connect() as c:
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {table: [tuple(row) for row in c.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                    for table in tables}

    def test_formal_empty_database_has_no_demo_business_and_uses_kilograms(self):
        with patch.object(erp, 'seed_demo', side_effect=AssertionError('正式初始化不能创建演示账款')):
            erp.init_db(demo=False)
        empty_tables = ('customers', 'products', 'rules', 'orders', 'receipts', 'archived_orders',
                        'trial_archives', 'delivery_markets', 'delivery_vehicles', 'delivery_drivers',
                        'dispatch_plans', 'warehouse_plans', 'sales_returns', 'processing_batches',
                        'stock_closings', 'statement_documents', 'auth_users', 'auth_sessions')
        with erp.connect() as c:
            for table in empty_tables:
                with self.subTest(table=table):
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0], 0)
            self.assertTrue(billing.enabled(c))
        self.assertEqual(erp.bootstrap()['settlement_unit'], '公斤')

    def test_repeated_empty_initialization_does_not_seed_or_change_records(self):
        erp.init_db(demo=False)
        before = self.all_rows()
        erp.init_db(demo=False)
        erp.init_db(demo=False)
        self.assertEqual(self.all_rows(), before)

    def test_repeated_initialization_preserves_real_master_orders_and_stock(self):
        erp.init_db(demo=False)
        customer = erp.master({'kind': 'customer', 'create': True, 'name': '初始化保留测试客户',
                               'legal_name': '初始化保留正式名称', 'route': '测试收货点', 'note': '独立测试库'}, '会计')
        erp.master({'kind': 'product', 'create': True, 'id': 'P100', 'name': '公斤结算测试产品',
                    'unit': '包', 'price': '7.5', 'tare': '0', 'standard_kg': '10'}, '会计')
        order = erp.mutate('order', {'customer_id': customer['id'], 'business_date': '2026-10-21',
                                     'batch': '初始化保留测试', 'workflow_version': 1, 'dispatch_required': True,
                                     'lines': [{'product_id': 'P100', 'ordered_qty': '2', 'actual_qty': '0',
                                                'price': '7.5', 'driver': [], 'customer': []}]}, '会计')
        data = erp.bootstrap()
        erp.save_warehouse({'business_date': '2026-10-21', 'stage': 'stock', 'version': 0,
                            'inventory_revision': data['inventory_revision'],
                            'order_versions': {order['id']: order['version']},
                            'stock': [{'product_id': 'P100', 'existing_qty': '0', 'produced_qty': '2'}],
                            'allocations': [], 'customers': []}, '库管')
        before = self.all_rows()
        erp.init_db(demo=False)
        self.assertEqual(self.all_rows(), before)
        saved = erp.bootstrap()
        self.assertEqual(len(saved['orders']), 1)
        self.assertEqual(saved['orders'][0]['lines'][0]['billing_unit'], '公斤')
        self.assertEqual(saved['orders'][0]['lines'][0]['price'], '7.5')


if __name__ == '__main__':
    unittest.main()
