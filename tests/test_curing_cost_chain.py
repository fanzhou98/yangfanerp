"""隔离库全链路（本期覆盖 采购→生产→熏制→发货 段）：熏制材料成本与白干出库金额必须对平。
日结与月结金额恒等式在 C 阶段接入同一链路，未在本文件冒称通过。"""
import json
import unittest

import test_workflow as fixture
import test_production_daily as daily_fixture

erp = fixture.erp
import curing
import inventory_valuation
import server


class CuringCostChainTests(unittest.TestCase):
    setUp = daily_fixture.DailyFactoryTests.setUp
    tearDown = daily_fixture.DailyFactoryTests.tearDown
    material = daily_fixture.DailyFactoryTests.material
    call = daily_fixture.DailyFactoryTests.call
    record = daily_fixture.DailyFactoryTests.record

    def seed(self, c, day='2026-10-20'):
        c.execute('INSERT OR REPLACE INTO warehouse_plans(business_date,payload) VALUES(?,?)', (day, json.dumps({
            'business_date': day, 'allocation_state': 'confirmed', 'allocations': [],
            'stock': [{'product_id': 'P003', 'existing_qty': '0', 'produced_qty': '10', 'loss_qty': '0', 'counted_qty': ''}],
        }, ensure_ascii=False)))
        c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('inventory_valuation',?)",
                  (json.dumps({'start_date': '2026-10-01'}),))

    def test_curing_cost_equals_white_outflow_and_ledger_identity(self):
        self.material('receipt', '100', '400')
        self.material('consume', '100')
        self.record(products=[{'product_id': 'P003', 'system': 'tofu', 'large_tanks': '1', 'small_tanks': '0'}])
        with erp.connect(True) as c:
            self.seed(c)
            priced = inventory_valuation.unit_cost(c, '2026-10-20', 'P003')
            self.assertIsNotNone(priced, '白干应有结存单价')
            self.assertEqual(priced['unit_cost'], '4000')
            record = curing.save(c, {'business_date': '2026-10-20', 'source_product_id': 'P003', 'qty': '2',
                                     'yield_rate': '2.5'}, '厂长', erp.audit, erp.now())['record']
            self.assertEqual(record['source_unit_cost'], '4000')
            self.assertEqual(record['material_cost_cents'], 8000)
            book = inventory_valuation.ledger(c, '2026-10')
            white = next(p for d in book['days'] if d['business_date'] == '2026-10-20'
                         for p in d['products'] if p['product_id'] == 'P003')
            self.assertEqual(white['out_cents'], 8000)
            self.assertEqual(record['material_cost_cents'], white['out_cents'])
            for d in book['days']:
                for p in d['products']:
                    self.assertEqual(p['opening_cents'] + p['in_cents'] - p['out_cents'] + p['count_cents'],
                                     p['closing_cents'],
                                     '%s %s 金额流水不平' % (d['business_date'], p['product_id']))

    def test_void_removes_curing_cost_and_white_outflow(self):
        self.material('receipt', '100', '400')
        self.material('consume', '100')
        self.record(products=[{'product_id': 'P003', 'system': 'tofu', 'large_tanks': '1', 'small_tanks': '0'}])
        with erp.connect(True) as c:
            self.seed(c)
            record = curing.save(c, {'business_date': '2026-10-20', 'source_product_id': 'P003', 'qty': '2',
                                     'yield_rate': '2.5'}, '厂长', erp.audit, erp.now())['record']
            curing.save(c, {'id': record['id'], 'action': 'void'}, '厂长', erp.audit, erp.now())
            self.assertEqual(curing.material_cost_total(c, '2026-10')['material_cost_cents'], 0)
            book = inventory_valuation.ledger(c, '2026-10')
            white = next(p for d in book['days'] if d['business_date'] == '2026-10-20'
                         for p in d['products'] if p['product_id'] == 'P003')
            self.assertEqual(white['out_cents'], 0)


if __name__ == '__main__':
    unittest.main()
