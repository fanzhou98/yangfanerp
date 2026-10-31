"""隔离库全链路金额对账：采购验收→入库→生产→熏制→发货→日结→月结，差异必须 0。
并做人为改入库价负向验证：已结账月金额变化必须被对账发现并阻断后续月结。"""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

import server as erp
import purchasing as purchasing_ops
import resources_costs as rc
import inventory as inv
import curing
import inventory_valuation as iv
import production_management as fm

DAY = '2026-10-20'


class AmountChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = erp.DB
        erp.DB = Path(self.temp.name) / 'chain.db'
        erp.init_db()

    def tearDown(self):
        erp.DB = self.old
        self.temp.cleanup()

    def chain(self):
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('inventory_valuation',?)",
                      (json.dumps({'start_date': '2026-10-01'}),))
            c.execute("DELETE FROM orders")
            c.execute("DELETE FROM receipts")
            prods = [dict(r) for r in c.execute('SELECT id,name,unit FROM products')]
            ops = purchasing_ops.Operations(c, erp.now, erp.audit)
            s = ops.supplier({'name': '链路供应商', 'category': '大豆 / 包装', 'payment_days': 30}, '会计')
            o = ops.order({'request_key': str(uuid.uuid4()), 'business_date': '2026-10-01', 'expected_date': '2026-10-03',
                           'supplier_id': s['id'], 'handler': '采购员',
                           'lines': [{'material_id': 'RM-SOY', 'warehouse_id': 'WH-TOFU', 'qty': '100', 'price': '4'}]}, '会计')
            o = ops.confirm({'id': o['id'], 'version': o['version']}, '会计')
            ops.receipt({'id': o['id'], 'version': o['version'], 'request_key': str(uuid.uuid4()),
                         'revision': rc.revision(c), 'business_date': '2026-10-03',
                         'lines': [{'line_id': 'L1', 'qty': '100'}], 'handler': '库管', 'note': '全部合格'}, '库管')
            rc.Operations(c, erp.now, erp.audit).material({'request_key': str(uuid.uuid4()), 'revision': rc.revision(c),
                'material_id': 'RM-SOY', 'business_date': DAY, 'kind': 'consume', 'qty': '100',
                'warehouse_id': 'WH-TOFU', 'handler': '库管', 'note': '当日领用'}, '管理员')
        with erp.connect(True) as c:
            fm.save(c, 'daily', {'request_key': str(uuid.uuid4()), 'business_date': DAY,
                'systems': {'tofu': {'soak_tanks': '0.6'}, 'skin': {'soak_tanks': '1'}},
                'products': [{'product_id': 'P003', 'large_tanks': '1', 'small_tanks': '0', 'skin_tanks': '0'},
                             {'product_id': 'P004', 'large_tanks': '0', 'small_tanks': '0', 'skin_tanks': '0'}]},
                '厂长', erp.now, erp.audit)
        data = erp.bootstrap()
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO orders(id,payload) VALUES(?,?)', ('SO-CHAIN', json.dumps({
                'id': 'SO-CHAIN', 'version': 1, 'business_date': DAY, 'state': 'reviewed', 'customer_id': 'C001',
                'lines': [{'product_id': 'P003', 'ordered_qty': '2', 'actual_qty': '2', 'price': '6'}]})))
        stock = [{'product_id': r['id'], 'existing_qty': '0', 'produced_qty': '10' if r['id'] == 'P003' else '0',
                  'loss_qty': '0'} for r in prods]
        plan = erp.save_warehouse({'business_date': DAY, 'version': 0,
            'inventory_revision': data['inventory_revision'], 'stock': stock,
            'allocations': [{'order_id': 'SO-CHAIN', 'product_id': 'P003', 'ordered_qty': '2', 'qty': '2'}],
            'customers': [], 'order_versions': {'SO-CHAIN': 1}}, '库管')
        with erp.connect(True) as c:
            record = curing.save(c, {'business_date': DAY, 'source_product_id': 'P003', 'qty': '2', 'yield_rate': '2.5'},
                                 '厂长', erp.audit, erp.now())['record']
            snap = inv.stock(c, DAY)
            closed = inv.Operations(c, erp.now, erp.audit).close({'business_date': DAY, 'version': 0,
                'inventory_revision': inv.revision(c), 'plan_version': plan['version'], 'evidence_checked': True,
                'counts': [{'product_id': r['product_id'], 'counted_qty': r['book_qty'], 'reason': ''}
                           for r in snap['products']]}, '库管')
        with erp.connect(True) as c:
            period = rc.Operations(c, erp.now, erp.audit).period(
                {'month': '2026-10', 'state': 'closed', 'version': 0, 'note': '链路对账'}, '管理员')
        return record, closed, period

    def test_full_chain_reconciles_to_zero(self):
        record, closed, period = self.chain()
        self.assertEqual(record['material_cost_cents'], 8000)
        self.assertEqual(closed['state'], 'closed')
        self.assertEqual(period['state'], 'closed')
        with erp.connect() as c:
            result = iv.reconcile(c, '2026-10')
        self.assertTrue(result['ok'])
        self.assertEqual(result['totals']['identity_diff_cents'], 0)
        white = next(p for p in result['rows'] if p['product_id'] == 'P003')
        self.assertEqual((white['opening_cents'], white['in_cents'], white['out_cents'], white['closing_cents']),
                         (0, 40000, 16000, 24000))
        self.assertEqual(white['closing_qty'], '6')

    def test_changed_material_price_blocks_later_close(self):
        self.chain()
        with erp.connect(True) as c:
            row = c.execute("SELECT id,payload FROM material_entries WHERE json_extract(payload,'$.kind')='receipt'").fetchone()
            payload = json.loads(row[1])
            payload['amount_cents'] = 45000
            payload['amount'] = '450'
            c.execute('UPDATE material_entries SET payload=? WHERE id=?', (json.dumps(payload, ensure_ascii=False), row[0]))
        with erp.connect() as c:
            result = iv.reconcile(c, '2026-10')
        self.assertFalse(result['ok'])
        diff = next(d for d in result['differences'] if d['product_name'] == '白豆干')
        self.assertEqual(diff['diff_cents'], 3000)
        with self.assertRaisesRegex(ValueError, '对账不平') as caught:
            with erp.connect(True) as c:
                rc.Operations(c, erp.now, erp.audit).period(
                    {'month': '2026-11', 'state': 'closed', 'version': 0, 'note': '改价后应阻断'}, '管理员')
        self.assertIn('已结账月 2026-10', str(caught.exception))
        with erp.connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM resource_periods WHERE month='2026-11'").fetchone())


if __name__ == '__main__':
    unittest.main()
