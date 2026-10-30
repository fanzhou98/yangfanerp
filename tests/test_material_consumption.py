"""Inventory value conservation, packaging quantities and processing entry guards."""
import json
import unittest
from decimal import Decimal
import test_workshop_transfer as fixture
import material_consumption as mc
import material_allocation as ma
import resources_costs as rc
import product_profit
import production_daily

erp = fixture.erp


class ConsumptionTests(unittest.TestCase):
    setUp = fixture.WorkshopTransferTests.setUp
    tearDown = fixture.WorkshopTransferTests.tearDown
    receipt = fixture.WorkshopTransferTests.receipt
    issue = fixture.WorkshopTransferTests.issue
    count = fixture.WorkshopTransferTests.count

    def prior(self, qty='100', cents=10000):
        payload = {'qty_close': qty, 'closing_cents': cents, 'product_ids': ['P001']}
        with erp.connect(True) as c:
            c.execute('INSERT INTO workshop_counts VALUES(?,?,?,?,?,?,?)', ('prior', '2026-09', 'A-GYPSUM', qty, '合成期初', 1, json.dumps(payload)))

    def test_opening_only_consumption_reaches_product_cost(self):
        self.prior(); self.count('0')
        with erp.connect() as c:
            report = product_profit.month(c, '2026-10')
            row = next(r for r in report['rows'] if r['product_id'] == 'P001')
            self.assertEqual(row['direct_material_cents'], 10000)
            self.assertEqual(report['costs']['workshop_adjust_cents'], 10000)
            self.assertEqual(ma.issue_report(c, '2026-10')['total_cents'], 10000)

    def test_opening_and_new_issues_use_weighted_average(self):
        self.prior(); self.receipt('100', '200'); self.issue('100', pids=('P001',)); self.count('100')
        with erp.connect() as c:
            row = rc.workshop_report(c, '2026-10')['rows'][0]
            self.assertEqual(row['closing_cents'], 15000)
            self.assertEqual(row['actual_cents'], 15000)
            self.assertEqual(row['opening_cents'] + row['issue_cents'], row['closing_cents'] + row['actual_cents'])

    def test_bags_use_packaged_quantity_and_unit_conversion(self):
        self.receipt('10', '100'); self.issue('10')
        with erp.connect(True) as c:
            mc.save_settings(c, 'A-GYPSUM', {'cost_mode': 'count', 'cost_from': '2026-10', 'bag_units': '100', 'packaging_rates': {'P001': '1', 'P002': '2'}})
            plan = {'business_date': '2026-10-20', 'stock': [{'product_id': 'P001', 'produced_qty': '100'}, {'product_id': 'P002', 'produced_qty': '50'}]}
            c.execute('INSERT INTO warehouse_plans VALUES(?,?)', ('2026-10-20', json.dumps(plan)))
        self.count('8')
        with erp.connect() as c:
            row = rc.workshop_report(c, '2026-10')['rows'][0]
            self.assertEqual(row['packaging_expected'], '200')
            self.assertEqual(row['packaging_actual'], '200')
            report = ma.issue_report(c, '2026-10')
            self.assertEqual(report['total_cents'], 2000)
            self.assertEqual([p['amount_cents'] for p in report['products']], [1000, 1000])

    def test_missing_packaging_output_does_not_evenly_split(self):
        self.receipt('10', '100'); self.issue('10')
        with erp.connect(True) as c:
            mc.save_settings(c, 'A-GYPSUM', {'cost_mode': 'count', 'cost_from': '2026-10', 'packaging_rates': {'P001': '1', 'P002': '1'}})
        self.count('0')
        with erp.connect() as c:
            report = ma.issue_report(c, '2026-10')
            self.assertEqual(report['allocated_cents'], 0)
            self.assertEqual(report['unallocated_cents'], 10000)

    def test_cost_modes_are_effective_dated_and_exclusive(self):
        with erp.connect(True) as c:
            with self.assertRaisesRegex(ValueError, '不能同时'):
                mc.save_settings(c, 'A-GYPSUM', {'cost_mode': 'count', 'amortize_months': 3})
            mc.save_settings(c, 'A-GYPSUM', {'cost_mode': 'count', 'cost_from': '2026-11'})
            self.assertEqual(mc.settings(c, 'A-GYPSUM', '2026-10')['cost_mode'], 'legacy')
            self.assertEqual(mc.settings(c, 'A-GYPSUM', '2026-11')['cost_mode'], 'count')

    def test_count_cannot_create_negative_consumption(self):
        self.receipt('10', '100'); self.issue('10')
        with self.assertRaisesRegex(ValueError, '超过期初'):
            self.count('11')

    def test_processing_product_blocks_direct_warehouse_output(self):
        with erp.connect(True) as c:
            c.execute("INSERT INTO meta VALUES('product_trade',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps({'P001': {'supply_kind': 'processing'}}),))
            self.assertEqual(production_daily.main_material(c, {'id': 'P001', 'name': '大豆腐'}), '转加工')
        body = {'business_date': '2026-10-20', 'version': 0, 'order_versions': {}, 'stock': [{'product_id': 'P001', 'existing_qty': '0', 'produced_qty': '10'}], 'allocations': [], 'customers': []}
        with self.assertRaisesRegex(ValueError, '转加工产品'):
            erp.save_warehouse(body, '库管')
