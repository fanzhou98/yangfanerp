"""登录 bootstrap 只带工作窗口内的材料流水，历史回溯走 /api/material-history。"""
import json
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import test_auth_http as fixture

erp = fixture.erp
TODAY = datetime.now(ZoneInfo('Asia/Shanghai')).date()
TODAY_DAY = TODAY.isoformat()
OLD_DAY = (TODAY - timedelta(days=60)).isoformat()


def entry(id, day, kind='consume', qty='5', sequence=1, **extra):
    row = {'id': id, 'sequence': sequence, 'material_id': 'RM-SOY', 'material_name': '大豆', 'unit': '公斤',
           'warehouse_id': 'WH-TOFU', 'business_date': day, 'kind': kind, 'qty': qty,
           'amount_cents': 0}
    row.update(extra)
    return row


class BootstrapEntriesTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    personal_password = fixture.AuthHTTPTests.personal_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown
    user = fixture.AuthHTTPTests.user

    def seed(self):
        # 旧日期批次全部耗尽 → 不该随 bootstrap 下发；当天入库与领用仍在窗口内。
        rows = [entry('BE-OLD-OPEN', OLD_DAY, 'opening', '100', sequence=1, amount_cents=40000),
                entry('BE-OLD', OLD_DAY, 'consume', '7', sequence=2),
                entry('BE-OLD-RECEIPT', OLD_DAY, 'receipt', '9', sequence=3),
                entry('BE-OLD-CLEAR', OLD_DAY, 'consume', '102', sequence=4),
                entry('BE-TODAY-OPEN', TODAY_DAY, 'opening', '50', sequence=5, amount_cents=20000),
                entry('BE-TODAY', TODAY_DAY, 'consume', '7', sequence=6)]
        with erp.connect(True) as c:
            for row in rows:
                c.execute('INSERT INTO material_entries VALUES(?,?,?)', (row['id'], row['id'], erp.dumps(row)))

    def bootstrap(self, client=None):
        code, value, _ = (client or self.admin).request('/api/bootstrap')
        self.assertEqual(code, 200, value)
        return value

    def test_today_kept_history_dropped(self):
        self.seed()
        resources = self.bootstrap()['resources']
        ids = {row['id'] for row in resources['entries']}
        self.assertEqual(ids, {'BE-TODAY-OPEN', 'BE-TODAY'})
        window = resources['entries_window']
        self.assertEqual(window['days'], 31)
        self.assertEqual(window['start'], (TODAY - timedelta(days=30)).isoformat())
        self.assertEqual(window['kept'], len(resources['entries']))
        self.assertEqual(window['total'], 6)
        beans = {row['business_date']: row for row in resources['bean_days']}
        self.assertEqual(sorted(beans), sorted([OLD_DAY, TODAY_DAY]))
        self.assertEqual((beans[OLD_DAY]['source'], beans[OLD_DAY]['qty']), ('tofu', '109'))
        self.assertEqual((beans[TODAY_DAY]['source'], beans[TODAY_DAY]['qty']), ('tofu', '7'))
        self.assertEqual(resources['consume_days'], sorted([OLD_DAY, TODAY_DAY]))

    def test_pending_valuations_cross_history(self):
        self.seed()
        pending = {row['id']: row for row in self.bootstrap()['resources']['pending_valuations']}
        self.assertEqual(sorted(pending), ['BE-OLD-RECEIPT'])
        self.assertNotIn('BE-TODAY', pending)
        self.assertNotIn('BE-OLD-OPEN', pending)
        for key in ('business_date', 'material_id', 'material_name', 'kind', 'qty', 'unit', 'warehouse_name',
                    'handler', 'reference', 'version'):
            self.assertIn(key, pending['BE-OLD-RECEIPT'])
        self.assertEqual(pending['BE-OLD-RECEIPT']['business_date'], OLD_DAY)

    def test_history_endpoint_returns_everything(self):
        self.seed()
        code, value, _ = self.admin.request('/api/material-history?view=ledger&all=1&page_size=50')
        self.assertEqual(code, 200, value)
        ids = {row['id'] for row in value['rows']}
        self.assertEqual(ids, {'BE-OLD-OPEN', 'BE-OLD', 'BE-OLD-RECEIPT', 'BE-OLD-CLEAR',
                               'BE-TODAY-OPEN', 'BE-TODAY'})
        code, value, _ = self.admin.request('/api/material-history?view=ledger&start=%s&end=%s' % (OLD_DAY, OLD_DAY))
        self.assertEqual(code, 200, value)
        self.assertEqual({row['id'] for row in value['rows']},
                         {'BE-OLD-OPEN', 'BE-OLD', 'BE-OLD-RECEIPT', 'BE-OLD-CLEAR'})

    def test_entry_fields_unchanged(self):
        self.seed()
        kept = next(row for row in self.bootstrap()['resources']['entries'] if row['id'] == 'BE-TODAY')
        code, value, _ = self.admin.request('/api/material-history?view=ledger&all=1&search=BE-TODAY&page_size=5')
        self.assertEqual(code, 200, value)
        history = next(row for row in value['rows'] if row['id'] == 'BE-TODAY')
        self.assertEqual(json.loads(erp.dumps(kept)), json.loads(erp.dumps(history)))

    def test_no_material_grant_gets_empty_resources(self):
        self.seed()
        driver, _ = self.user('be_driver', '司机')
        self.assertEqual(self.bootstrap(driver)['resources'], {})
        warehouse, _ = self.user('be_warehouse', '库管')
        resources = self.bootstrap(warehouse)['resources']
        self.assertTrue(resources['entries'])
        text = json.dumps(resources)
        for key in ('_cents', 'average_price', 'valuation_history'):
            self.assertNotIn(key, text)
        self.assertEqual({row['id'] for row in resources['entries']}, {'BE-TODAY-OPEN', 'BE-TODAY'})
        self.assertTrue(any(row.get('has_entries') for row in resources['warehouse_stocks']))

    # ---- 回归守卫：t8 发现的三个边界 ----
    def test_open_soy_lot_kept_but_exhausted_lots_dropped(self):
        """旧日期里仍未被耗尽的黄豆批次入库行随 bootstrap 下发；已耗尽批次仍丢弃。"""
        rows = [entry('BL-OPENING', OLD_DAY, 'opening', '100', sequence=1, amount_cents=40000),
                entry('BL-EATEN', OLD_DAY, 'receipt', '10', sequence=2, amount_cents=4000),
                entry('BL-OPEN', OLD_DAY, 'receipt', '30', sequence=3, amount_cents=12000),
                entry('BL-USE', OLD_DAY, 'consume', '118', sequence=4)]
        with erp.connect(True) as c:
            for row in rows:
                c.execute('INSERT INTO material_entries VALUES(?,?,?)', (row['id'], row['id'], erp.dumps(row)))
        resources = self.bootstrap()['resources']
        ids = {row['id'] for row in resources['entries']}
        self.assertIn('BL-OPEN', ids)
        self.assertNotIn('BL-EATEN', ids)
        self.assertNotIn('BL-OPENING', ids)
        soy_entries = [row for row in resources['entries'] if row['material_id'] == 'RM-SOY']
        self.assertEqual({row['id'] for row in soy_entries}, {'BL-OPEN'})
        lots = [lot for row in resources['warehouse_stocks'] for lot in row.get('lots') or []]
        self.assertIn('BL-OPEN', {lot['lot_id'] for lot in lots})

    def test_transfer_target_marks_has_entries(self):
        """当日调拨到从未有流水的库房，该库房 warehouse_stocks 行 has_entries=True。"""
        with erp.connect(True) as c:
            for row in [entry('BT-OPEN', TODAY_DAY, 'opening', '100', sequence=1, amount_cents=40000),
                        entry('BT-MOVE', TODAY_DAY, 'transfer', '10', sequence=2, target_warehouse_id='WH-MAIN')]:
                c.execute('INSERT INTO material_entries VALUES(?,?,?)', (row['id'], row['id'], erp.dumps(row)))
        rows = {(row['id'], row['warehouse_id']): row for row in self.bootstrap()['resources']['warehouse_stocks']}
        self.assertTrue(rows[('RM-SOY', 'WH-TOFU')]['has_entries'])
        self.assertTrue(rows[('RM-SOY', 'WH-MAIN')]['has_entries'])
        self.assertEqual(rows[('RM-SOY', 'WH-MAIN')]['qty'], '10')

    def test_window_boundary_keeps_today_minus_30(self):
        """TODAY-30 保留、TODAY-31 丢弃，并断言 window.start。"""
        edge = (TODAY - timedelta(days=30)).isoformat()
        outside = (TODAY - timedelta(days=31)).isoformat()
        with erp.connect(True) as c:
            for row in [{'id': 'BW-EDGE', 'sequence': 1, 'material_id': 'A-GYPSUM', 'material_name': '石膏',
                         'unit': '公斤', 'warehouse_id': 'WH-COMMON', 'business_date': edge, 'kind': 'receipt',
                         'qty': '3', 'amount_cents': 300},
                        {'id': 'BW-OUT', 'sequence': 2, 'material_id': 'A-GYPSUM', 'material_name': '石膏',
                         'unit': '公斤', 'warehouse_id': 'WH-COMMON', 'business_date': outside, 'kind': 'receipt',
                         'qty': '4', 'amount_cents': 400}]:
                c.execute('INSERT INTO material_entries VALUES(?,?,?)', (row['id'], row['id'], erp.dumps(row)))
        resources = self.bootstrap()['resources']
        ids = {row['id'] for row in resources['entries']}
        self.assertIn('BW-EDGE', ids)
        self.assertNotIn('BW-OUT', ids)
        self.assertEqual(resources['entries_window']['start'], edge)
        self.assertEqual({row['business_date']: row['count'] for row in resources['entry_days']},
                         {outside: 1, edge: 1})


if __name__ == '__main__':
    unittest.main()
