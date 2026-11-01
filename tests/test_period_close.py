"""Month close and old-snapshot repair use disposable databases only."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import inventory_valuation
import material_consumption
import migrations
import product_profit
import resources_costs as rc
import test_product_profit as fixture
import server
from ops import period_snapshot_check

OPEN_GAP = {'field': '成本月份未结账，费用可能未录全', 'owner': '会计', 'target': 'expenses'}


class PeriodCloseTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ProductProfitTests()
        self.previous_db = fixture.erp.DB
        self.case.setUp()
        self.case.order('R01-ORDER', 'P001', '100')
        self.case.expense('100')

    def tearDown(self):
        self.case.tearDown()
        fixture.erp.DB = self.previous_db

    def change(self, state, version=0):
        with fixture.erp.connect(True) as c:
            return rc.Operations(c, fixture.erp.now, fixture.erp.audit).period(
                {'month': '2026-10', 'state': state, 'version': version, 'note': '隔离库月结验收'}, '管理员')

    def stored(self):
        with fixture.erp.connect() as c:
            row = c.execute("SELECT version,payload FROM resource_periods WHERE month='2026-10'").fetchone()
            return tuple(row) if row else None


    def test_reopen_keeps_cash_receivable_and_valuation_consistent(self):
        import cash_query, production_management as pm
        asof = '2026-10-31'

        def snapshot():
            with fixture.erp.connect() as c:
                totals = cash_query.report(c, asof)['totals']
                paid = rc.receipts_paid_asof(c, asof)
                ar = sum(pm.outstanding(o, paid.get(o['id'], 0)) for o in rc.rows(c, 'orders')
                         if o.get('state') == 'reviewed' and o['business_date'] <= asof)
                frozen = '2026-10' in inventory_valuation._frozen(c)
                return (totals['receivable_cents'], totals['balance_cents'],
                        totals['monthly_income_cents'], ar, frozen)

        before = snapshot()
        self.change('closed')
        closed = snapshot()
        self.assertTrue(closed[4], '结账后应写入估值冻结')
        self.assertEqual((closed[0], closed[1], closed[3]), (before[0], before[1], before[3]),
                         '结账不应改变资金与应收口径')
        self.change('open', 1)
        self.assertEqual(snapshot(), before, '撤销结账后应完全回到结账前的资金、应收与估值口径')

    def test_close_removes_only_open_state_warning_and_keeps_financial_gaps(self):
        before = self.case.report()
        self.assertIn(OPEN_GAP, before['gaps'])
        result = self.change('closed')
        self.assertEqual(result['state'], 'closed')
        self.assertNotIn('report_snapshot', result)
        report = self.case.report()
        self.assertNotIn(OPEN_GAP, report['gaps'])
        self.assertTrue(any('不能认定净利润' in gap['field'] for gap in report['gaps']))
        before['gaps'].remove(OPEN_GAP)
        self.assertEqual(report, before)

    def test_closed_month_blocks_material_registration_until_reopen(self):
        # 岗位验收发现的行为：结账后库管仍能打开入库界面，必须由服务端挡住写入。
        self.change('closed')
        payload = {'kind': 'receipt', 'material_id': 'RM-SOY', 'business_date': '2026-10-15',
                   'qty': '1', 'amount': '10', 'revision': 0, 'request_key': 'closed-period-probe'}
        with fixture.erp.connect(True) as c:
            with self.assertRaisesRegex(ValueError, '已结账'):
                rc.Operations(c, fixture.erp.now, fixture.erp.audit).material(dict(payload), '库管')
        self.change('open', version=1)
        with fixture.erp.connect(True) as c:
            with self.assertRaises(ValueError) as caught:
                rc.Operations(c, fixture.erp.now, fixture.erp.audit).material(dict(payload), '库管')
        # 重开后不再报“已结账”，后续报错来自物料校验，说明期间锁已解除。
        self.assertNotIn('已结账', str(caught.exception))

    def test_close_refuses_unfinished_month_end_count_and_keeps_period_open(self):
        # 月结是成本口径的最后一道闸：月末盘点/计价没收口时必须拒绝结账，且不得留下半成品状态。
        with patch.object(material_consumption, 'closing_issues', return_value=['大豆 尚未完成月末盘点']):
            with self.assertRaisesRegex(ValueError, '尚未完成月末盘点'):
                self.change('closed')
        with fixture.erp.connect() as c:
            row = c.execute("SELECT payload FROM resource_periods WHERE month='2026-10'").fetchone()
        state = json.loads(row[0])['state'] if row else None
        self.assertNotEqual(state, 'closed')

    def test_frozen_report_survives_source_change_and_same_state_retry(self):
        self.change('closed')
        frozen = self.case.report()
        stored = self.stored()
        with fixture.erp.connect(True) as c:
            row = json.loads(c.execute("SELECT payload FROM orders WHERE id='R01-ORDER'").fetchone()[0])
            row['lines'][0]['amount_cents'] += 12345
            c.execute('UPDATE orders SET payload=? WHERE id=?', (rc.dump(row), row['id']))
        self.assertEqual(self.case.report(), frozen)
        with self.assertRaisesRegex(ValueError, '月份状态已变化'):
            self.change('closed', 0)
        self.change('closed', 1)
        self.assertEqual(self.stored(), stored)
        self.assertEqual(self.case.report(), frozen)
        with fixture.erp.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM audit WHERE action='成本月份结账'").fetchone()[0], 1)

    def test_reopen_rolls_back_frozen_month_and_blocks_when_later_month_closed(self):
        self.change('closed')
        with fixture.erp.connect() as c:
            self.assertIn('2026-10', inventory_valuation._frozen(c))
        self.change('open', 1)
        with fixture.erp.connect() as c:
            self.assertNotIn('2026-10', inventory_valuation._frozen(c))
        # 后续月份已结账时，撤销本月会破坏已冻结的链条，必须按倒序先重开
        with fixture.erp.connect(True) as c:
            c.execute("INSERT INTO resource_periods VALUES('2026-11',1,?) ON CONFLICT(month) DO UPDATE SET payload=excluded.payload",
                      (rc.dump({'month': '2026-11', 'state': 'closed', 'version': 1, 'at': '2026-11-30', 'role': '管理员'}),))
        with self.assertRaisesRegex(ValueError, '后续月份已结账'):
            self.change('closed', 2)

    def stable(self):
        report = self.case.report()
        report.get('report_context', {}).pop('generated_at', None)
        return report

    def test_reopen_reclose_recalculates_and_freezes_fresh_values(self):
        self.change('closed')
        first = self.stable()
        self.change('open', 1)
        self.assertIn(OPEN_GAP, self.case.report()['gaps'])
        self.case.expense('20')
        expected = self.stable()
        expected['gaps'].remove(OPEN_GAP)
        self.change('closed', 2)
        self.assertNotEqual(self.stable()['total'], first['total'])
        # generated_at 精确到秒，冻结快照与实时读取必须忽略该时间戳才能比较
        self.assertEqual(self.stable(), expected)
        self.assertEqual(self.stored()[0], 3)

    def test_snapshot_failure_rolls_back_even_when_caller_catches_it(self):
        for initial in (None, 'open'):
            with self.subTest(initial=initial), fixture.erp.connect(True) as c:
                c.execute('DELETE FROM resource_periods')
                if initial:
                    c.execute('INSERT INTO resource_periods VALUES(?,?,?)',
                              ('2026-10', 1, rc.dump({'month': '2026-10', 'version': 1, 'state': 'open'})))
                before = [tuple(r) for r in c.execute('SELECT * FROM resource_periods')]
                with patch.object(product_profit, 'month', side_effect=RuntimeError('模拟快照失败')):
                    with self.assertRaises(RuntimeError):
                        rc.Operations(c, fixture.erp.now, fixture.erp.audit).period(
                            {'month': '2026-10', 'state': 'closed', 'version': 1 if initial else 0, 'note': '失败演练'}, '管理员')
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM resource_periods')], before)

    def test_audit_failure_rolls_back_period_and_snapshot(self):
        with fixture.erp.connect(True) as c:
            def fail_audit(*args):
                raise RuntimeError('模拟审计失败')
            with self.assertRaises(RuntimeError):
                rc.Operations(c, fixture.erp.now, fail_audit).period(
                    {'month': '2026-10', 'state': 'closed', 'version': 0, 'note': '失败演练'}, '管理员')
            self.assertIsNone(c.execute('SELECT 1 FROM resource_periods').fetchone())


class SnapshotMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'upgrade.db'
        self.db_patch = patch.object(server, 'DB', self.path)
        self.db_patch.start()
        specs = migrations.registry()
        cutoff = next(i for i, m in enumerate(specs) if m.id == '064-period-snapshot-status')
        with patch.object(migrations, 'registry', lambda: specs[:cutoff]):
            server.init_db(demo=False)
        self.original = {
            'month': '2026-10', 'state': 'closed', 'version': 4,
            'allocation_rule': 'historical-rule', 'at': '2026-10-25T12:00:00+08:00', 'note': '原月结说明',
            'report_snapshot': {'month': '2026-10', 'rows': [{'product_id': 'P001', 'net_cents': -12345}],
                                'total': {'net_cents': -12345}, 'gaps': [copy.deepcopy(OPEN_GAP),
                                    {'field': '材料未计价', 'owner': '会计', 'target': 'materials'}]},
        }
        with server.connect(True) as c:
            c.execute('INSERT INTO resource_periods VALUES(?,?,?)', ('2026-10', 4, rc.dump(self.original)))

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_upgrade_changes_only_known_warning_and_retains_audited_original(self):
        before_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        plan = period_snapshot_check.inspect_database(self.path)
        self.assertEqual(plan['affected_count'], 1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before_hash)
        with server.connect() as c:
            migrations.status(c)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before_hash)
        server.init_db(demo=False)
        with server.connect() as c:
            version, raw = c.execute('SELECT version,payload FROM resource_periods').fetchone()
            after = json.loads(raw)
            expected = copy.deepcopy(self.original)
            expected['report_snapshot']['gaps'].remove(OPEN_GAP)
            self.assertEqual(after['report_snapshot'], expected['report_snapshot'])
            self.assertEqual(version, 5)
            self.assertEqual(after['version'], version)
            for key in ('at', 'note', 'allocation_rule'):
                self.assertEqual(after[key], self.original[key])
            audit = c.execute("SELECT before_json,after_json FROM audit WHERE action='修正已结成本快照状态提示'").fetchone()
            self.assertEqual(json.loads(audit[0]), self.original)
            self.assertEqual(json.loads(audit[1]), after)
            canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            self.assertEqual(after['snapshot_status_revision']['before_snapshot_sha256'],
                             hashlib.sha256(canonical(self.original['report_snapshot'])).hexdigest())
            self.assertEqual(after['snapshot_status_revision']['after_snapshot_sha256'],
                             hashlib.sha256(canonical(after['report_snapshot'])).hexdigest())
            self.assertEqual(product_profit.month(c, '2026-10'), after['report_snapshot'])
            stored = [tuple(r) for r in c.execute('SELECT * FROM resource_periods')]
            audits = [tuple(r) for r in c.execute('SELECT * FROM audit')]
        server.init_db(demo=False)
        with server.connect() as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM resource_periods')], stored)
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM audit')], audits)
        self.assertEqual(period_snapshot_check.inspect_database(self.path)['affected_count'], 0)

    def test_open_missing_mismatched_and_unfamiliar_warnings_remain_unchanged(self):
        cases = []
        for i, kind in enumerate(('open', 'missing', 'mismatch', 'unfamiliar'), 1):
            month = f'2026-{i:02d}'
            p = copy.deepcopy(self.original)
            p['month'] = month
            p['report_snapshot']['month'] = month
            if kind == 'open': p['state'] = 'open'
            if kind == 'missing': p.pop('report_snapshot')
            if kind == 'mismatch': p['report_snapshot']['month'] = '2020-01'
            if kind == 'unfamiliar': p['report_snapshot']['gaps'][0]['owner'] = '其他责任岗位'
            cases.append((month, 4, rc.dump(p)))
        with server.connect(True) as c:
            c.execute('DELETE FROM resource_periods')
            c.executemany('INSERT INTO resource_periods VALUES(?,?,?)', cases)
        server.init_db(demo=False)
        with server.connect() as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM resource_periods ORDER BY month')], cases)
        self.assertEqual(period_snapshot_check.inspect_database(self.path)['manual_review_count'], 2)

    def test_failed_repair_rolls_back_metadata_audit_and_migration_ledger(self):
        def failing_audit(*args):
            raise RuntimeError('模拟修订审计失败')
        with server.connect(True) as c:
            before = [tuple(r) for r in c.execute('SELECT * FROM resource_periods')]
            with self.assertRaises(RuntimeError):
                migrations.ensure(c, context={'audit': failing_audit})
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM resource_periods')], before)
            self.assertIsNone(c.execute("SELECT 1 FROM schema_migrations WHERE id='064-period-snapshot-status'").fetchone())

    def test_readonly_inspection_does_not_create_a_missing_database(self):
        missing = Path(self.tmp.name) / 'missing.db'
        with self.assertRaises(sqlite3.Error):
            period_snapshot_check.inspect_database(missing)
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
