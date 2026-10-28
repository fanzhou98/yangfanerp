"""Outsourced delivery categories: retire wages, protect transport, delete safely."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import test_workflow as fixture
import cost_allocation as ca
import payroll
import reporting
import resources_costs as rc
import trade

erp = fixture.erp


class ExpenseCategoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(erp, 'DB', Path(self.tmp.name) / 'categories.db')
        self.patch.start()
        erp.init_db(demo=False)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def call(self, method, body, role='会计'):
        with erp.connect(True) as c:
            return getattr(rc.Operations(c, erp.now, erp.audit), method)(body, role)

    def categories(self):
        with erp.connect() as c:
            return {r['id']: r for r in ca.categories(c)}

    def expense(self, category='electricity', amount='100', **extra):
        return self.call('expense', {'request_key': str(uuid.uuid4()), 'business_date': '2026-10-20', 'period': '2026-10', 'category': category, 'amount': amount, 'handler': '会计', 'note': '分类验收凭据', **extra})

    def snapshot(self):
        with erp.connect() as c:
            return rc.snapshot(c)

    def test_delivery_wage_is_retired_and_transport_is_system_managed(self):
        cats = self.categories()
        wage = cats['wages-delivery']
        self.assertFalse(wage['active'])
        self.assertTrue(wage['retired'])
        self.assertFalse(wage['manual_entry'])
        self.assertEqual(wage['status'], '历史项目')
        transport = cats['transport']
        self.assertEqual(transport['name'], '外包配送费')
        self.assertTrue(transport['active'])
        self.assertTrue(transport['system_managed'])
        self.assertEqual(transport['system_source'], 'transport-settlement')
        self.assertFalse(transport['manual_entry'])
        self.assertFalse(transport['deletable'])
        self.assertTrue(cats['wages-production']['manual_entry'])
        self.assertTrue(cats['wages-management']['manual_entry'])
        with self.assertRaisesRegex(ValueError, '配送工资已停用'):
            self.expense('wages-delivery')
        with self.assertRaisesRegex(ValueError, '运输月结'):
            self.expense('transport')
        for cat in ('wages-production', 'wages-management', 'rent'):
            self.assertTrue(self.expense(cat)['id'])

    def test_unused_custom_and_builtin_delete_do_not_reappear(self):
        custom = self.call('expense_category', {'id': None, 'name': '验收临时项目', 'group': '其他', 'nature': '变动', 'payment_mode': 'payable', 'counterparty_kind': 'other', 'active': True, 'product_ids': [], 'version': 0})
        self.assertTrue(custom['id'].startswith('cost-'))
        self.call('expense_category_delete', {'id': custom['id'], 'version': custom['version']})
        self.assertNotIn(custom['id'], self.categories())
        meals = self.categories()['meals']
        self.call('expense_category_delete', {'id': 'meals', 'version': meals['version']})
        self.assertNotIn('meals', self.categories())
        erp.init_db(demo=False)
        cats = self.categories()
        self.assertNotIn(custom['id'], cats)
        self.assertNotIn('meals', cats)
        with erp.connect() as c:
            rows = c.execute("SELECT action,entity,before_json,after_json FROM audit WHERE action='删除间接成本项目' AND entity IN (?,?) ORDER BY id", (custom['id'], 'meals')).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r[0] == '删除间接成本项目' for r in rows))
        self.assertTrue(all(json.loads(r[3])['deleted'] is True for r in rows))

    def test_referenced_category_cannot_be_deleted_and_snapshot_is_unchanged(self):
        expense = self.expense('electricity', '321.09')
        cat = self.categories()['electricity']
        with self.assertRaisesRegex(ValueError, '1 笔费用.*停用'):
            self.call('expense_category_delete', {'id': 'electricity', 'version': cat['version']})
        changed = self.call('expense_category', {**cat, 'name': '生产电费（新名称）', 'version': cat['version']})
        self.assertEqual(changed['name'], '生产电费（新名称）')
        with erp.connect() as c:
            current = next(e for e in rc.expense_projection(c) if e['id'] == expense['id'])
            raw = json.loads(c.execute('SELECT payload FROM indirect_expenses WHERE id=?', (expense['id'],)).fetchone()[0])
        self.assertEqual((current['amount_cents'], current['business_date']), (32109, '2026-10-20'))
        self.assertEqual(raw['category_snapshot']['name'], '生产电费（不含冷库）')
        self.assertEqual(raw['category_snapshot']['id'], 'electricity')
        self.assertEqual(self.categories()['electricity']['reference_count'], 1)

    def test_delete_requires_version_permission_and_audit(self):
        cat = self.categories()['meals']
        with self.assertRaisesRegex(ValueError, '当前账号无此操作权限'):
            self.call('expense_category_delete', {'id': 'meals', 'version': cat['version']}, '库管')
        with self.assertRaisesRegex(ValueError, '已变更'):
            self.call('expense_category_delete', {'id': 'meals', 'version': 99})
        self.assertIn('meals', self.categories())
        self.call('expense_category_delete', {'id': 'meals', 'version': cat['version']})
        with erp.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='删除间接成本项目' AND entity='meals'").fetchone()[0], 1)

    def test_payroll_profile_reference_blocks_delete_and_retired_payroll_still_preflights(self):
        with erp.connect(True) as c:
            c.execute('INSERT INTO payroll_records VALUES(?,?,?)', ('WAGE-LEGACY', 'legacy-wage', rc.dump({'kind': 'profile', 'employee_id': 'E-LEGACY', 'salary_category': 'wages-delivery', 'version': 1})))
            payroll.cost_preflight(c, {'id': 'PS-LEGACY', 'month': '2026-10', 'rows': [{'salary_category': 'wages-delivery'}]})
        wage = self.categories()['wages-delivery']
        self.assertEqual(wage['payroll_profile_count'], 1)
        self.assertFalse(wage['deletable'])
        with self.assertRaisesRegex(ValueError, '1 份计薪配置'):
            self.call('expense_category_delete', {'id': 'wages-delivery', 'version': wage['version']})

    def trade_save(self, kind, body, request_key=None):
        with erp.connect(True) as c:
            return trade.save(c, kind, {'request_key': request_key or str(uuid.uuid4()), **body}, '管理员', erp.now, erp.audit)

    def current_expense(self, eid):
        with erp.connect() as c:
            return next(e for e in rc.expense_projection(c) if e['id'] == eid)

    def test_trip_to_settlement_to_partial_and_full_payment_only_counts_once(self):
        plan = {'business_date': '2026-10-20', 'version': 1, 'trips': [{'id': 'T1', 'name': '第一趟', 'driver': '司机', 'vehicle_name': '测试车'}], 'assignments': [{'market_id': 'M001', 'trip_id': 'T1'}]}
        with erp.connect(True) as c:
            c.execute('INSERT INTO dispatch_plans VALUES(?,?)', ('2026-10-20', rc.dump(plan)))
        self.trade_save('trip', {'business_date': '2026-10-20', 'trip_id': 'T1', 'partner': '测试运输公司', 'rate': '120.50', 'note': '实际配送'})
        with erp.connect() as c:
            group = trade.transport_report(c, '2026-10')['groups'][0]
        issue = {'month': '2026-10', 'partner': '测试运输公司', 'handler': '经办人', 'source_fingerprint': group['source_fingerprint']}
        doc = self.trade_save('transport-issue', issue, 'monthly-issue')
        again = self.trade_save('transport-issue', issue, 'monthly-issue')
        self.assertEqual(doc['id'], again['id'])
        with erp.connect() as c:
            expenses = rc.rows(c, 'indirect_expenses')
            self.assertEqual(len(expenses), 1)
            e = expenses[0]
            self.assertEqual(e['category'], 'transport')
            self.assertEqual(e['system_source'], 'transport-settlement')
            self.assertEqual(e['system_source_label'], '运输月结')
            self.assertEqual(e['source_document_id'], doc['id'])
            self.assertEqual(e['category_snapshot']['name'], '外包配送费')
            self.assertEqual(e['amount_cents'], 12050)
            self.assertEqual(rc.period_expenses(c, '2026-10')[0]['amount_cents'], 12050)
            month = reporting.management_month(c, '2026-10')
            self.assertEqual(next(x['value'] for x in month['components'] if x['label'] == '实际配送趟次'), 12050)
            self.assertEqual(next(x['value'] for x in month['components'] if x['label'] == '非运输期间费用'), 0)
        with self.assertRaisesRegex(ValueError, '不能手工重复登记'):
            self.expense('transport', '120.50')
        with self.assertRaisesRegex(ValueError, '不能手工改写'):
            self.call('expense_edit', {'id': e['id'], 'version': 1, 'request_key': str(uuid.uuid4()), 'category': 'transport', 'amount': '120.50', 'business_date': '2026-10-31', 'handler': '会计', 'note': '改写'})
        with self.assertRaisesRegex(ValueError, '不能单独作废'):
            self.call('void', {'ledger': 'expense', 'id': e['id'], 'version': 1, 'reason': '错误'})
        transport = self.categories()['transport']
        with self.assertRaisesRegex(ValueError, '不能删除'):
            self.call('expense_category_delete', {'id': 'transport', 'version': transport['version']})
        with self.assertRaisesRegex(ValueError, '系统维护'):
            self.call('expense_category', {**transport, 'name': '改名'})
        current = self.current_expense(e['id'])
        self.call('expense_review', {'id': e['id'], 'version': current['version'], 'request_key': str(uuid.uuid4()), 'decision': 'approve', 'evidence_checked': True, 'handler': '出纳', 'note': '核对结算单'}, '出纳')
        current = self.current_expense(e['id'])
        self.call('expense_payment', {'id': e['id'], 'version': current['version'], 'request_key': str(uuid.uuid4()), 'business_date': '2026-10-31', 'amount': '50.00', 'payee': '测试运输公司', 'method': '银行转账', 'handler': '出纳', 'reference': '回单1', 'note': '部分付款'}, '出纳')
        current = self.current_expense(e['id'])
        self.assertEqual((current['payment_state'], current['paid_cents'], current['outstanding_cents']), ('partial', 5000, 7050))
        self.call('expense_payment', {'id': e['id'], 'version': current['version'], 'request_key': str(uuid.uuid4()), 'business_date': '2026-10-31', 'amount': '70.50', 'payee': '测试运输公司', 'method': '银行转账', 'handler': '出纳', 'reference': '回单2', 'note': '付清余款'}, '出纳')
        final = self.current_expense(e['id'])
        self.assertEqual((final['payment_state'], final['paid_cents'], final['outstanding_cents']), ('paid', 12050, 0))
        self.assertEqual(len(final['payments']), 2)
        with erp.connect() as c:
            self.assertEqual(len(rc.period_expenses(c, '2026-10')), 1)


class LegacyCategoryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(erp, 'DB', Path(self.tmp.name) / 'legacy.db')
        self.patch.start()
        erp.init_db(demo=False)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_migration_changes_only_category_settings_and_keeps_documents(self):
        legacy_settings = {
            'wages-delivery': {'id': 'wages-delivery', 'name': '配送工资', 'group': '人工工资', 'nature': '固定', 'payment_mode': 'payroll', 'counterparty_kind': 'none', 'active': True, 'version': 0, 'product_ids': []},
            'transport': {'id': 'transport', 'name': '运输配送（油费+车损）', 'group': '配送', 'nature': '变动', 'payment_mode': 'payable', 'counterparty_kind': 'logistics', 'active': True, 'version': 0, 'product_ids': []},
        }
        payload = {'id': 'EX-LEGACY', 'business_date': '2026-10-20', 'period': '2026-10', 'category': 'transport', 'amount_cents': 12345, 'category_snapshot': {'id': 'transport', 'name': '运输配送（油费+车损）'}, 'version': 1, 'voided': False, 'handler': '会计', 'note': '历史运输原单', 'partner': '旧运输方'}
        with erp.connect(True) as c:
            c.execute("INSERT INTO indirect_expenses VALUES(?,?,?)", ('EX-LEGACY', 'legacy-expense', rc.dump(payload)))
            c.execute("INSERT INTO meta VALUES('expense_category_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (rc.dump(legacy_settings),))
            c.execute("DELETE FROM schema_migrations WHERE id='065-outsourced-delivery-categories'")
            c.execute('DELETE FROM audit')
        with erp.connect() as c:
            before = c.execute("SELECT payload FROM indirect_expenses WHERE id='EX-LEGACY'").fetchone()[0]
        erp.init_db(demo=False)
        with erp.connect() as c:
            after = c.execute("SELECT payload FROM indirect_expenses WHERE id='EX-LEGACY'").fetchone()[0]
            self.assertEqual(after, before)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations WHERE id='065-outsourced-delivery-categories'").fetchone()[0], 1)
            settings = json.loads(c.execute("SELECT value FROM meta WHERE key='expense_category_settings'").fetchone()[0])
            self.assertFalse(settings['wages-delivery']['active'])
            self.assertTrue(settings['wages-delivery']['retired'])
            self.assertEqual(settings['transport']['name'], '外包配送费')
            self.assertTrue(settings['transport']['system_managed'])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='调整外包配送费用分类'").fetchone()[0], 1)
            cats = {r['id']: r for r in ca.categories(c)}
            self.assertEqual(cats['transport']['name'], '外包配送费')
            self.assertEqual(json.loads(after)['category_snapshot']['name'], '运输配送（油费+车损）')


if __name__ == '__main__':
    unittest.main(verbosity=2)
