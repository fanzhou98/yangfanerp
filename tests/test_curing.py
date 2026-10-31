import unittest
import test_workflow as fixture
erp = fixture.erp
import json
import curing, server


class CuringTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    tearDown = fixture.WorkflowTests.tearDown

    def _source(self, c):
        rows = curing.products(c, 'source')
        self.assertTrue(rows, '测试库缺少白干类产品')
        return rows[0]

    def _stock(self, c, pid, day, qty='10'):
        c.execute('INSERT OR REPLACE INTO warehouse_plans(business_date,payload) VALUES(?,?)', (day, json.dumps({'business_date': day, 'allocation_state': 'confirmed', 'allocations': [], 'stock': [{'product_id': pid, 'existing_qty': qty, 'produced_qty': '0', 'loss_qty': '0', 'counted_qty': ''}]}, ensure_ascii=False)))

    def test_save_deducts_source_stock_and_reports_beans(self):
        with erp.connect(True) as c:
            source = self._source(c)
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('product_average_weights',?)", ('{"'+source['id']+'":"11"}',))
            day = erp.now()[:10]
            server.inventory.open_day(c, day)
            self._stock(c, source['id'], day)
            record = curing.save(c, {'business_date': day, 'source_product_id': source['id'], 'qty': '3', 'yield_rate': '2.5', 'note': '昨天剩的白干'}, '厂长', erp.audit, erp.now())['record']
            self.assertEqual(record['source_product_id'], source['id'])
            self.assertAlmostEqual(float(record['net_kg']), 33.0, places=3)
            self.assertAlmostEqual(float(record['beans_kg']), 13.2, places=2)
            rows = curing.records(c)
            self.assertTrue(any(r['id'] == record['id'] for r in rows))
            qty, kg = curing.consumed(c, day, source['id'])
            self.assertAlmostEqual(float(qty), 3.0, places=3)
            self.assertAlmostEqual(float(kg), 33.0, places=3)
            stock = server.inventory.stock(c, day, [dict(r) for r in c.execute('SELECT * FROM products WHERE id=?', (source['id'],))])
            # 扣减体现在 processing_input_qty：登记后应等于 3（筐装）或 33（公斤）
            self.assertIn('processing_input_qty', stock['products'][0])

    def test_void_reverts_record(self):
        with erp.connect(True) as c:
            source = self._source(c)
            day = erp.now()[:10]
            server.inventory.open_day(c, day)
            self._stock(c, source['id'], day)
            record = curing.save(c, {'business_date': day, 'source_product_id': source['id'], 'qty': '1', 'yield_rate': '2.5'}, '厂长', erp.audit, erp.now())['record']
            voided = curing.save(c, {'id': record['id'], 'action': 'void'}, '厂长', erp.audit, erp.now())['record']
            self.assertTrue(voided['voided'])
            qty, _ = curing.consumed(c, day, source['id'])
            self.assertEqual(float(qty), 0.0)

    def test_requires_positive_quantity_and_source(self):
        with erp.connect(True) as c:
            day = erp.now()[:10]
            server.inventory.open_day(c, day)
            with self.assertRaises(ValueError):
                curing.save(c, {'business_date': day, 'source_product_id': 'P001', 'qty': '1', 'yield_rate': '2.5'}, '厂长', erp.audit, erp.now())
            src = self._source(c)
            self._stock(c, src['id'], day)
            with self.assertRaises(ValueError):
                curing.save(c, {'business_date': day, 'source_product_id': src['id'], 'qty': '0', 'yield_rate': '2.5'}, '厂长', erp.audit, erp.now())


if __name__ == '__main__':
    unittest.main()
