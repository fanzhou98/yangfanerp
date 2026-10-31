"""成品库存估值：日期重放、加权单价与分差守恒。"""
import json
import unittest
import test_workflow as fixture
import test_production_daily as daily
import inventory_valuation as iv

erp = fixture.erp


class ValuationTests(unittest.TestCase):
    material = daily.DailyFactoryTests.material
    record = daily.DailyFactoryTests.record
    call = daily.DailyFactoryTests.call

    def setUp(self):
        daily.DailyFactoryTests.setUp(self)
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO warehouse_plans VALUES(?,?)", ('2026-10-20', json.dumps({'business_date': '2026-10-20', 'stock': [
                {'product_id': 'P001', 'existing_qty': '2', 'produced_qty': '10', 'loss_qty': '0'},
                {'product_id': 'P002', 'existing_qty': '0', 'produced_qty': '12', 'loss_qty': '0'}]})))
            c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (iv.META_KEY, json.dumps({'start_date': '2026-10-01'})))
        self.material('receipt', '100', '400')
        self.material('consume', '100')
        self.record()

    def ledger(self):
        with erp.connect() as c:
            return iv.ledger(c, '2026-10')

    def test_ledger_identity_and_moving_average(self):
        result = self.ledger()
        day = next(d for d in result['days'] if d['business_date'] == '2026-10-20')
        row = {r['product_id']: r for r in day['products']}['P001']
        self.assertEqual(row['opening_qty'], '2')
        self.assertEqual(row['in_qty'], '10')
        self.assertEqual(row['closing_qty'], '12')
        self.assertEqual(row['valued_qty'], '10')
        self.assertEqual(row['unvalued_qty'], '2')
        self.assertEqual(row['closing_cents'], 40000)
        self.assertEqual(int(row['opening_cents']) + int(row['in_cents']) - int(row['out_cents']) + int(row['count_cents']), int(row['closing_cents']))
        self.assertEqual(row['unit_cost'], '4000')
        self.assertEqual(result['days'][-1]['business_date'], '2026-10-31')
        summary = {r['product_id']: r for r in result['products']}
        self.assertEqual(int(summary['P001']['in_cents']) - int(summary['P001']['out_cents']) + int(summary['P001']['count_cents']), int(summary['P001']['closing_cents']))

    def test_cent_rounding_stays_in_closing_value(self):
        book = iv.Book()
        book.add('10', 10001)
        self.assertEqual(book.take('3'), 3000)
        self.assertEqual(book.take('7'), 7001)
        self.assertEqual(book.cents, 0)
        self.assertEqual(book.qty, 0)
        book.add('5', None)
        self.assertEqual(book.unvalued_qty, 5)
        self.assertEqual(book.cents, 0)

    def test_second_production_day_has_no_cent_gap(self):
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO warehouse_plans VALUES(?,?)", ('2026-10-21', json.dumps({'business_date': '2026-10-21', 'stock': [
                {'product_id': 'P001', 'existing_qty': '', 'produced_qty': '5', 'loss_qty': '0'}]})))
        result = self.ledger()
        day20 = next(d for d in result['days'] if d['business_date'] == '2026-10-20')
        day21 = next(d for d in result['days'] if d['business_date'] == '2026-10-21')
        row20 = {r['product_id']: r for r in day20['products']}['P001']
        row21 = {r['product_id']: r for r in day21['products']}['P001']
        self.assertEqual(row21['opening_qty'], '12')
        self.assertEqual(row21['in_qty'], '5')
        self.assertEqual(row21['closing_qty'], '17')
        # 月度归集金额按产量累计分配，两天合计必须等于可分配金额，不能丢分。
        self.assertEqual(int(row20['in_cents']) + int(row21['in_cents']), 40000)
        self.assertEqual(row21['closing_cents'], 40000)

    def test_production_without_cost_is_unvalued_and_reported(self):
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO warehouse_plans VALUES(?,?)", ('2026-10-22', json.dumps({'business_date': '2026-10-22', 'stock': [
                {'product_id': 'P005', 'existing_qty': '0', 'produced_qty': '3', 'loss_qty': '0'}]})))
        result = self.ledger()
        row = {r['product_id']: r for r in result['products']}['P005']
        self.assertEqual(row['closing_qty'], '3')
        self.assertEqual(row['closing_cents'], 0)
        self.assertEqual(row['unvalued_qty'], '3')
        self.assertTrue(any('未计价' in gap for gap in result['gaps']))

    def test_settings_normalize_to_month_start_and_reject_future(self):
        with erp.connect(True) as c:
            saved = iv.save_settings(c, {'start_date': '2026-10-15'}, '管理员', erp.now, erp.audit)
            self.assertEqual(saved['start_date'], '2026-10-01')
            with self.assertRaises(ValueError):
                iv.save_settings(c, {'start_date': '2999-01-01'}, '管理员', erp.now, erp.audit)


if __name__ == '__main__':
    unittest.main()
