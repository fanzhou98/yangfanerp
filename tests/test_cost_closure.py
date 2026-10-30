"""Cost closing requires counted, current and fully attributed material facts."""
import json
import unittest
import test_workshop_transfer as fixture
import material_consumption as mc
import material_allocation as ma
import resources_costs as rc
import product_profit as pp
import finished_cost as fc

erp = fixture.erp


class CostClosureTests(unittest.TestCase):
    tearDown = fixture.WorkshopTransferTests.tearDown
    receipt = fixture.WorkshopTransferTests.receipt
    issue = fixture.WorkshopTransferTests.issue
    count = fixture.WorkshopTransferTests.count
    order = fixture.WorkshopTransferTests.order
    batch = fixture.WorkshopTransferTests.batch

    def setUp(self):
        fixture.WorkshopTransferTests.setUp(self)
        with erp.connect(True) as c:
            c.execute('DELETE FROM receipts'); c.execute('DELETE FROM orders')

    def configure(self):
        with erp.connect(True) as c:
            mc.save_settings(c, 'A-GYPSUM', {'cost_mode': 'count', 'cost_from': '2026-10', 'packaging_rates': {'P001': '1', 'P002': '1'}})

    def close(self):
        with erp.connect(True) as c:
            return rc.Operations(c, erp.now, erp.audit).period({'month': '2026-10', 'state': 'closed', 'version': 0, 'note': '隔离核查'}, '管理员')

    def test_uncounted_material_cannot_close(self):
        self.receipt('10', '100'); self.issue('10'); self.configure()
        with self.assertRaisesRegex(ValueError, '盘点'):
            self.close()
        with erp.connect() as c:
            self.assertFalse(c.execute("SELECT 1 FROM resource_periods WHERE month='2026-10'").fetchone())

    def test_pending_packaging_cost_is_visible_and_profit_is_unknown(self):
        self.receipt('10', '100'); self.issue('10'); self.configure(); self.count('0'); self.order()
        with erp.connect() as c:
            report = pp.month(c, '2026-10')
        self.assertEqual(report['statement']['pending_material_cents'], 10000)
        self.assertGreaterEqual(report['statement']['unallocated_cents'], 10000)
        self.assertIsNone(report['statement']['profit_cents'])
        with self.assertRaisesRegex(ValueError, '待分配'):
            self.close()

    def test_new_issue_invalidates_count_until_explicit_recount(self):
        self.receipt('10', '100'); self.issue('10'); self.count('5')
        self.receipt('10', '200'); self.issue('10')
        with erp.connect() as c:
            row = rc.workshop_report(c, '2026-10')['rows'][0]
        self.assertTrue(row['stale_count'])
        with self.assertRaisesRegex(ValueError, '重新盘点'):
            self.close()
        self.count('5', version=1)
        with erp.connect() as c:
            row = rc.workshop_report(c, '2026-10')['rows'][0]
        self.assertFalse(row['stale_count'])
        self.assertEqual((row['closing_cents'], row['actual_cents']), (7500, 22500))

    def test_equal_price_new_issue_also_invalidates_count(self):
        self.receipt('20', '200'); self.issue('10'); self.count('5'); self.issue('10')
        with erp.connect() as c:
            self.assertTrue(rc.workshop_report(c, '2026-10')['rows'][0]['stale_count'])

    def test_all_issued_value_leaves_no_zero_quantity_residue(self):
        row = fc.carry('0', 0, '3', 100, '3', '0')
        self.assertEqual((row['issued_cents'], row['ending_cents']), (100, 0))

    def test_dispatched_stock_leaves_cost_inventory_before_review(self):
        with erp.connect(True) as c:
            c.execute('INSERT INTO warehouse_plans VALUES(?,?)', ('2026-10-18', rc.dump({'business_date': '2026-10-18', 'stock': [{'product_id': 'P001', 'existing_qty': '0', 'produced_qty': '10', 'loss_qty': '0'}]})))
        order = erp.mutate('order', {'customer_id': 'C001', 'business_date': '2026-10-18', 'batch': '测试', 'lines': [{'product_id': 'P001', 'ordered_qty': '10', 'actual_qty': '10', 'price': '3'}]}, '库管')
        self.assertNotEqual(order['state'], 'reviewed')
        with erp.connect() as c:
            row = next(r for r in fc.month(c, '2026-10')['rows'] if r['product_id'] == 'P001')
        self.assertEqual((row['issued_qty'], row['ending_qty']), ('10', '0'))

    def test_material_cost_reaches_second_processing_stage(self):
        self.receipt('10', '100'); self.issue('10', pids=('P001',)); self.batch('10', '10')
        second = {'id': 'PB-SECOND', 'business_date': '2026-10-22', 'product_id': 'P004', 'input_kg': '10', 'outputs': [{'product_id': 'P002', 'qty': '1', 'net_kg': '9'}], 'voided': False}
        with erp.connect(True) as c:
            c.execute('INSERT INTO processing_batches VALUES(?,?)', (second['id'], rc.dump(second)))
        with erp.connect() as c:
            rows = {r['product_id']: r for r in pp.month(c, '2026-10')['rows']}
        self.assertEqual(rows['P001']['direct_cents'], 0)
        self.assertEqual(rows['P004']['direct_cents'], 0)
        self.assertEqual(rows['P002']['direct_cents'], 10000)
        self.assertEqual(sum(r['direct_cents'] for r in rows.values()), 10000)

    def test_unknown_production_cost_keeps_inventory_value_unknown(self):
        row = fc.carry('0', 0, '3', None, '1', '0')
        self.assertIsNone(row['unit_cost'])
        self.assertIsNone(row['issued_cents'])
        self.assertIsNone(row['ending_cents'])

    def test_multiple_processing_batches_conserve_last_cent(self):
        self.receipt('1', '0.01'); self.issue('1', pids=('P001',))
        self.batch('1', '1'); self.batch('1', '1')
        with erp.connect() as c:
            report = pp.month(c, '2026-10')
        self.assertEqual(sum(r['direct_cents'] for r in report['rows']), 1)
        self.assertEqual(sum(t['amount_cents'] for t in report['transfers']), 1)

    def test_processing_cycle_leaves_profit_unknown(self):
        self.receipt('10', '100'); self.issue('10', pids=('P001',)); self.batch()
        with erp.connect(True) as c:
            c.execute('INSERT INTO processing_batches VALUES(?,?)', ('PB-CYCLE', rc.dump({'id':'PB-CYCLE','business_date':'2026-10-22','product_id':'P004','input_kg':'1','outputs':[{'product_id':'P001','net_kg':'1'}]})))
        with erp.connect() as c:
            report = pp.month(c, '2026-10')
        for row in report['rows']:
            if row['product_id'] in ('P001', 'P004'):
                self.assertIsNone(row['net_cents'])
                self.assertTrue(any('环路' in reason for reason in row['missing_data']))
