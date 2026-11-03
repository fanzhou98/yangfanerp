"""Batch-two business parameters affect order lines, supplier defaults and production backfill."""
import unittest
from unittest.mock import patch
import server as erp


class ParameterLimitTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.old = erp.DB
        erp.DB = Path(self.temp.name) / 'limit.db'
        erp.init_db()

    def tearDown(self):
        erp.DB = self.old
        self.temp.cleanup()

    def test_order_max_lines_comes_from_parameter(self):
        lines = [{'product_id': f'P{i:03d}', 'ordered_qty': '1', 'actual_qty': '0'} for i in range(1, 12)]
        body = {'customer_id': 'C001', 'business_date': '2026-10-20', 'batch': '行数上限', 'lines': lines}
        with patch.object(erp.production_management, 'settings', return_value={'order_max_lines': '10'}):
            with self.assertRaises(erp.ValidationError) as raised:
                erp.mutate('order', body, '库管')
            self.assertIn('须有1至10项产品', str(raised.exception.issues))

    def test_production_backfill_days_blocks_too_old_day(self):
        import production_management as fm
        with erp.connect(True) as c:
            with patch.object(fm, 'settings', return_value={'production_backfill_days': '0'}):
                with self.assertRaisesRegex(ValueError, '最多补录 0 天'):
                    fm.save(c, 'daily', {'request_key': 'old-day', 'business_date': '2020-01-01',
                                         'systems': {}, 'products': []}, '管理员', erp.now, erp.audit)

    def test_supplier_uses_default_payment_days(self):
        import purchasing as p
        with erp.connect(True) as c:
            with patch.object(erp.production_management, 'settings', return_value={'purchase_default_payment_days': '15'}):
                supplier = p.Operations(c, erp.now, erp.audit).supplier({'name': '参数默认账期', 'category_ids': ['SC-RAW']}, '会计')
            self.assertEqual(supplier['payment_days'], 15)


if __name__ == '__main__':
    unittest.main()
