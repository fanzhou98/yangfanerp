"""成品库存金额月结对账：恒等式、冻结金额与人为改价报警。"""
import json
import unittest
import test_production_daily as fixture
import inventory_valuation as iv
import resources_costs as rc

erp = fixture.erp


class ReconcileTests(unittest.TestCase):
    material = fixture.DailyFactoryTests.material
    record = fixture.DailyFactoryTests.record
    call = fixture.DailyFactoryTests.call
    tearDown = fixture.DailyFactoryTests.tearDown

    def setUp(self):
        fixture.DailyFactoryTests.setUp(self)
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO warehouse_plans VALUES(?,?)", ('2026-10-20', json.dumps({
                'business_date': '2026-10-20', 'stock': [
                    {'product_id': 'P001', 'existing_qty': '2', 'produced_qty': '10', 'loss_qty': '0'}]})))
        self.material('receipt', '100', '400')
        self.material('consume', '100')
        self.record()

    def receipt(self, rid, amount_cents):
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO finished_goods_records VALUES(?,?)', (rid, json.dumps({
                'id': rid, 'business_date': '2026-10-21', 'kind': 'receipt', 'state': 'reviewed',
                'lines': [{'product_id': 'P001', 'qty': '2', 'amount_cents': amount_cents, 'price': '40'}]})))

    def set_receipt_amount(self, rid, amount_cents):
        with erp.connect(True) as c:
            record = json.loads(c.execute('SELECT payload FROM finished_goods_records WHERE id=?', (rid,)).fetchone()[0])
            record['lines'][0]['amount_cents'] = amount_cents
            c.execute('UPDATE finished_goods_records SET payload=? WHERE id=?', (json.dumps(record), rid))

    def reconcile(self, month='2026-10'):
        with erp.connect() as c:
            return iv.reconcile(c, month)

    def close(self, month='2026-10', version=0):
        with erp.connect(True) as c:
            return rc.Operations(c, erp.now, erp.audit).period(
                {'month': month, 'state': 'closed', 'version': version, 'note': '对账测试'}, '管理员')

    def test_default_start_follows_earliest_data_month(self):
        with erp.connect() as c:
            self.assertEqual(iv.config(c)['start_date'], '2026-10-01')

    def test_identity_holds_and_survives_freeze(self):
        result = self.reconcile()
        self.assertTrue(result['ok'])
        self.assertEqual(result['totals']['identity_diff_cents'], 0)
        self.assertTrue(result['rows'])
        with erp.connect(True) as c:
            iv.freeze(c, '2026-10', erp.now())
        again = self.reconcile()
        self.assertTrue(again['frozen'])
        self.assertTrue(again['ok'])
        self.assertEqual(again['differences'], [])

    def test_manual_receipt_price_change_is_flagged_with_document(self):
        self.receipt('RR-1', 8000)
        with erp.connect(True) as c:
            iv.freeze(c, '2026-10', erp.now())
        self.set_receipt_amount('RR-1', 9000)
        result = self.reconcile()
        self.assertFalse(result['ok'])
        rows = [d for d in result['differences'] if d['documents'][0]['id'] == 'RR-1']
        self.assertTrue(rows)
        self.assertEqual(rows[0]['diff_cents'], 1000)
        self.assertEqual(rows[0]['field'], '外购入库金额')

    def test_close_blocks_after_earlier_month_document_changed(self):
        self.receipt('RR-2', 8000)
        self.close('2026-10', 0)
        self.set_receipt_amount('RR-2', 9500)
        with self.assertRaisesRegex(ValueError, '对账不平') as caught:
            self.close('2026-11', 0)
        self.assertIn('RR-2', str(caught.exception))
        self.assertIn('已结账月 2026-10', str(caught.exception))
        with erp.connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM resource_periods WHERE month='2026-11'").fetchone())

    def test_clean_close_freezes_month_amounts(self):
        self.close('2026-10', 0)
        result = self.reconcile()
        self.assertTrue(result['frozen'])
        self.assertTrue(result['ok'])
        with erp.connect() as c:
            frozen = iv._frozen(c)['2026-10']
        self.assertIn('products', frozen)
        self.assertIn('receipts', frozen)
        self.assertIn('curing', frozen)

    def test_problem_text_lists_product_and_document(self):
        result = {'identity_errors': [{'product_name': '大豆腐', 'identity_diff_cents': 5}],
                  'differences': [{'product_name': '大豆腐', 'field': '外购入库金额', 'diff_cents': 100,
                                   'documents': [{'kind': '外购成品入库', 'id': 'RR-X'}]}]}
        parts = iv._problems(result)
        self.assertEqual(parts[0], '大豆腐 恒等式差异 0.05 元')
        self.assertIn('RR-X', parts[1])


if __name__ == '__main__':
    unittest.main()
