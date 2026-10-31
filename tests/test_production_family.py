import copy
import json
import unittest
from decimal import Decimal
import test_workflow as fixture
import production_management as fm
import test_production_daily as tf
import production_daily as daily
import production_config as pc
import material_allocation as ma
import server

erp = fixture.erp
DAY = '2026-10-20'


class FamilySlurryTests(unittest.TestCase):
    setUp = tf.DailyFactoryTests.setUp
    tearDown = tf.DailyFactoryTests.tearDown
    call = tf.DailyFactoryTests.call
    record = tf.DailyFactoryTests.record
    material = tf.DailyFactoryTests.material

    def setUp(self):
        tf.DailyFactoryTests.setUp(self)
        with erp.connect(True) as c:
            c.executemany('INSERT INTO products VALUES(?,?,?,?,?,?)', [
                ('P501', '白干', '公斤', '0', '1', '1'),
                ('P502', '白干（框）', '筐', '0', '1', None),
                ('P503', '黄干', '公斤', '0', '1', '1'),
                ('P504', '黄干（框）', '筐', '0', '2', None)])
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_average_weights',?)", (json.dumps({'P502': '11', 'P504': '12.5'}),))
            version = (c.execute('SELECT MAX(version) FROM production_config_versions').fetchone()[0] or 0) + 1
            config = copy.deepcopy(pc.seed(c))
            config.update({'version': version, 'effective_date': DAY})
            c.execute('INSERT INTO production_config_versions VALUES(?,?,?)', (version, DAY, json.dumps(config, ensure_ascii=False)))

    def plan(self):
        with erp.connect(True) as c:
            server.inventory.open_day(c, DAY)
            rows = [{'product_id': pid, 'existing_qty': '0', 'produced_qty': '0', 'loss_qty': '0', 'counted_qty': qty}
                    for pid, qty in (('P501', '60'), ('P502', '10'), ('P503', '20'), ('P504', '4'))]
            c.execute('INSERT OR REPLACE INTO warehouse_plans(business_date,payload) VALUES(?,?)', (DAY, json.dumps(
                {'business_date': DAY, 'allocation_state': 'confirmed', 'allocations': [], 'stock': rows}, ensure_ascii=False)))

    def family_record(self, **extra):
        return self.record(products=[
            {'product_id': 'P501', 'system': 'tofu', 'large_tanks': '1', 'small_tanks': '0', 'skin_tanks': '0'},
            {'product_id': 'P502', 'system': 'tofu', 'large_tanks': '0', 'small_tanks': '0', 'skin_tanks': '0'},
            {'product_id': 'P503', 'system': 'tofu', 'large_tanks': '0', 'small_tanks': '0', 'skin_tanks': '0'},
            {'product_id': 'P504', 'system': 'tofu', 'large_tanks': '0', 'small_tanks': '0', 'skin_tanks': '0'}], **extra)

    def test_family_beans_by_tank_count(self):
        with erp.connect() as c:
            cfg = pc.get(c, DAY)
            families = daily.family_beans(c, cfg, self.family_record()['products'])
            self.assertEqual(families[('tofu', '白干')]['bean'], Decimal('33'))
            self.assertEqual(families[('tofu', '白干')]['lead'], 'P501')
            self.assertEqual(families[('tofu', '黄干')]['bean'], Decimal('0'))

    def test_duplicate_family_tank_rows_rejected(self):
        with self.assertRaisesRegex(ValueError, '同族产品（.*）共用一组浆缸'):
            self.record(products=[
                {'product_id': 'P501', 'system': 'tofu', 'large_tanks': '1', 'small_tanks': '0', 'skin_tanks': '0'},
                {'product_id': 'P502', 'system': 'tofu', 'large_tanks': '2', 'small_tanks': '0', 'skin_tanks': '0'}])

    def test_allocation_uses_family_basis_once(self):
        self.plan()
        self.family_record()
        self.material('receipt', '100', '400')
        self.material('consume', '100', production_system_id='tofu')
        with erp.connect() as c:
            r = ma.day_report(c, DAY)
        pool = next(p for p in r['pools'] if p['system'] == 'tofu')
        self.assertEqual(pool['issued_kg'], '100')
        self.assertEqual(pool['status'], '已分摊')
        self.assertAlmostEqual(float(pool['basis_kg']), 33.0, places=3)
        a = {x['product_id']: x for x in r['allocations']}
        self.assertEqual(set(a), {'P501'})
        self.assertEqual(a['P501']['product_name'], '白干族')
        self.assertAlmostEqual(float(a['P501']['basis_kg']), 33.0, places=3)
        self.assertAlmostEqual(float(a['P501']['allocated_kg']), 100.0, places=2)

    def test_report_shows_one_family_row_with_family_yield(self):
        self.plan()
        self.family_record()
        self.material('receipt', '100', '400')
        self.material('consume', '100', production_system_id='tofu')
        with erp.connect() as c:
            report = daily.report(c, DAY, fm.settings(c), fm.line_weight)
        ids = {p['product_id'] for p in report['products']}
        self.assertIn('P501', ids)
        for pid in ('P502', 'P504'):
            self.assertNotIn(pid, ids)
        row = next(p for p in report['products'] if p['product_id'] == 'P501')
        self.assertEqual(row['product_name'], '白干族')
        self.assertEqual(row['family'], '白干')
        self.assertEqual(row['net_kg'], '170')
        self.assertEqual(row['bean_kg'], '33')
        self.assertEqual(row['unit'], '公斤')
        self.assertAlmostEqual(float(row['yield_kg_per_kg']), 170 / 33, places=3)
        self.assertIn('族折豆', row['slurry_formula'])
        methods = {m['method']: m for m in report['systems'][0]['methods']}
        self.assertEqual(methods['浆缸估算']['kg'], '33')

    def test_huanggan_family_adds_curing_beans(self):
        self.plan()
        self.family_record()
        with erp.connect(True) as c:
            c.execute('INSERT INTO curing_records(business_date,payload) VALUES(?,?)', (DAY, json.dumps(
                {'business_date': DAY, 'target_product_id': 'P503', 'beans_kg': '12.8'}, ensure_ascii=False)))
        with erp.connect() as c:
            report = daily.report(c, DAY, fm.settings(c), fm.line_weight)
        row = next(p for p in report['products'] if p['product_id'] == 'P503')
        self.assertEqual(row['product_name'], '黄干族')
        self.assertEqual(row['bean_kg'], '12.8')
        self.assertEqual(row['net_kg'], '70')
        self.assertAlmostEqual(float(row['yield_kg_per_kg']), 70 / 12.8, places=3)
        self.assertIn('熏制折豆', row['slurry_formula'])

    def test_kg_unit_reverse_still_requires_matching_unit(self):
        with erp.connect() as c:
            cfg = pc.get(c, DAY)
        reg = {'large_tanks': '1', 'small_tanks': '0', 'skin_tanks': '0'}
        value, formula = daily.selected_tank_conversion(reg, cfg, Decimal('22'), '公斤', cfg)
        self.assertIsNone(value)
        self.assertIn('单位', formula)


if __name__ == '__main__':
    unittest.main()
