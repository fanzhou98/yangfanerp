"""生产日出品率 FIFO：昨日结转先扣、结算均重×当日产量、无自有发货沿用最近均重。"""
import json
import unittest
from decimal import Decimal
from unittest.mock import patch

import production_yield
import cost_allocation
import test_production_daily as fixture

erp = fixture.erp


class ProductionYieldTests(unittest.TestCase):
    setUp = fixture.DailyFactoryTests.setUp
    tearDown = fixture.DailyFactoryTests.tearDown

    def setUp(self):
        fixture.DailyFactoryTests.setUp(self)
        with erp.connect(True) as c:
            c.execute('DELETE FROM orders')  # 去掉演示订单，只保留本组用例数据

    def order(self, day, pid, qty, bill_kg=None, state='reviewed'):
        payload = {'id': 'SO-' + day + '-' + pid, 'business_date': day, 'state': state, 'customer_id': 'C001',
                   'customer_name': '演示客户', 'lines': [{'product_id': pid, 'actual_qty': str(qty),
                   'billing_unit': '公斤', 'bill_qty': None if bill_kg is None else str(bill_kg)}]}
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO orders(id,payload) VALUES(?,?)', (payload['id'], json.dumps(payload)))

    def report_for(self, table):
        def fake(c, day, settings, weight_fn):
            return {'products': [{'product_id': pid, 'product_name': pid, 'unit': unit, 'derived_qty': qty,
                                  'bean_kg': bean, 'processing_input_kg': None, 'processing_source_name': None}
                                 for pid, (unit, qty, bean) in table.get(day, {}).items()]}
        return fake

    def activity(self, *days):
        with erp.connect(True) as c:
            for day in days:
                c.execute('INSERT OR REPLACE INTO stock_closings(business_date,payload) VALUES(?,?)',
                          (day, json.dumps({'business_date': day, 'products': []})))

    def ledger(self, table, day):
        production_yield._CACHE.clear()
        with erp.connect() as c, patch('production_daily.report', side_effect=self.report_for(table)):
            return production_yield.day(c, day, lambda: {}, None)

    def test_carryover_is_consumed_before_own_shipment(self):
        self.order('2026-10-01', 'P001', 80, 1600)
        self.order('2026-10-02', 'P001', 100, 2030)
        table = {'2026-10-01': {'P001': ('筐', '100', '2000')}, '2026-10-02': {'P001': ('筐', '100', '2000')}}
        first = self.ledger(table, '2026-10-01')['P001']
        self.assertEqual(first['unit_kg'], '20')
        self.assertEqual(first['production_kg'], '2000')
        self.assertEqual(first['carry_after'], '20')
        self.assertEqual(first['status'], '结算口径')
        second = self.ledger(table, '2026-10-02')['P001']
        self.assertEqual(second['carry_before'], '20')
        self.assertEqual(second['unit_kg'], '20.375')
        self.assertEqual(second['production_kg'], '2037.5')
        self.assertEqual(second['own_kg'], '1630')
        self.assertEqual(second['carry_after'], '20')

    def test_no_own_shipment_reuses_last_weight_and_marks_estimate(self):
        self.order('2026-10-01', 'P001', 100, 2000)
        self.order('2026-10-03', 'P001', 10, 200)
        self.activity('2026-10-02')
        table = {'2026-10-01': {'P001': ('筐', '100', '2000')}, '2026-10-02': {'P001': ('筐', '100', '2000')},
                 '2026-10-03': {'P001': ('筐', '100', '2000')}}
        third = self.ledger(table, '2026-10-03')['P001']
        self.assertEqual(third['carry_before'], '100')
        self.assertEqual(third['unit_kg'], '20')
        self.assertEqual(third['production_kg'], '2000')
        self.assertEqual(third['status'], '估算（当日发货均为结转）')
        self.assertEqual(third['carry_after'], '190')

    def test_pending_review_does_not_settle_yield(self):
        self.order('2026-10-01', 'P001', 80, None, state='draft')
        table = {'2026-10-01': {'P001': ('筐', '100', '2000')}}
        row = self.ledger(table, '2026-10-01')['P001']
        self.assertIsNone(row['production_kg'])
        self.assertEqual(row['status'], '待复核（当日发货未复核）')
        self.assertIsNone(row['yield'])

    def test_kilogram_product_uses_derived_kg_directly(self):
        self.order('2026-10-01', 'P004', 35, 35)
        table = {'2026-10-01': {'P004': ('公斤', '100', '400')}}
        row = self.ledger(table, '2026-10-01')['P004']
        self.assertEqual(row['production_kg'], '100')
        self.assertEqual(row['yield'], '0.25')
        self.assertEqual(row['carry_after'], '0')

    def test_public_yields_reports_production_day_basis(self):
        self.order('2026-10-01', 'P001', 80, 1600)
        table = {'2026-10-01': {'P001': ('筐', '100', '2000')}}
        production_yield._CACHE.clear()
        report = {'products': [{'product_id': 'P001', 'product_name': '大豆腐', 'unit': '筐', 'bean_kg': '2000'}]}
        with erp.connect() as c, patch('production_daily.report', side_effect=self.report_for(table)):
            cost_allocation.public_yields(c, report, '2026-10-01')
        product = report['products'][0]
        self.assertEqual(product['production_day_kg'], '2000')
        self.assertEqual(product['settlement_yield'], '1')
        self.assertEqual(product['carryover_after_qty'], '20')
        self.assertIn('生产日口径', product['settlement_basis'])

    def test_allocation_uses_production_day_kg_weight(self):
        self.order('2026-10-01', 'P001', 80, 1600)
        table = {'2026-10-01': {'P001': ('筐', '100', '2000')}}
        production_yield._CACHE.clear()
        expense = {'id': 'EX-1', 'amount_cents': 1000, 'product_ids': ['P001'], 'category': 'electricity', 'label': '电费'}
        with erp.connect() as c, patch('production_daily.report', side_effect=self.report_for(table)):
            result = cost_allocation.allocate(c, '2026-10-01', '2026-10-31', [expense])
        row = result['details'][0]['rows'][0]
        self.assertEqual(row['weight_basis'], 'production-day')
        self.assertEqual(row['weight'], '2000')
        self.assertEqual(result['details'][0]['unallocated_cents'], 0)


if __name__ == '__main__':
    unittest.main()
