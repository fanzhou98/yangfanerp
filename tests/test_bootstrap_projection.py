"""v0.97.0 bootstrap 投影裁剪：登录态不再随首屏下发审计200条，production_configs 只保留 resources 一份。

登录后订单详情的“操作轨迹”改为按对象读取 /api/audit（audit_query.history），
所以这里同时校验该接口的 entity 精确过滤、顺序与权限；匿名/演示 bootstrap 仍返回最近200条。
"""
import json
import unittest

from test_auth_http import AuthHTTPFixture, Client
from test_workflow import erp

DEFERRED = {'X-ERP-Expense-History': 'deferred', 'X-ERP-Byproduct-History': 'deferred'}
AUDIT_COLUMNS = 'id,at,role,action,entity,actor_id,actor_name,request_id'
SIZE_LIMIT = 125000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()


class BootstrapProjectionTests(AuthHTTPFixture):
    def setUp(self):
        super().setUp()
        # 真实库的审计远超200条；临时库补足到205条，才能验证“最近200条”的截断口径。
        with erp.connect(True) as c:
            for index in range(205):
                erp.audit(c, ['库管', '会计', '管理员'][index % 3], '历史操作%03d：结算与复核' % index,
                          'SO-HISTORY-%03d' % index if index % 7 else 'P001')
        self.order = erp.mutate('order', {'customer_id': 'C001', 'business_date': '2026-10-22', 'batch': '轨迹投影',
                                          'lines': [{'product_id': 'P004', 'ordered_qty': '2', 'actual_qty': '2',
                                                     'price': '75', 'driver': [], 'customer': []}]}, '库管')

    def login_bootstrap(self, client, **headers):
        code, data, _ = client.request('/api/bootstrap', headers={**DEFERRED, **headers})
        self.assertEqual(code, 200, data)
        return data

    def test_login_bootstrap_withholds_audit_while_demo_keeps_latest_200(self):
        administrator = self.login_bootstrap(self.admin)
        self.assertEqual(administrator['audit'], [])
        self.assertIn('audit', administrator)
        warehouse, _ = self.user()
        self.assertEqual(self.login_bootstrap(warehouse)['audit'], [])
        # 匿名/演示 bootstrap 是函数级入口（账号模式下 HTTP 匿名请求仍是401）。
        demo = erp.bootstrap(include_expense_history=False, include_byproduct_history=False)
        self.assertEqual(len(demo['audit']), 200)
        with erp.connect() as c:
            expected = [dict(r) for r in c.execute('SELECT ' + AUDIT_COLUMNS + ' FROM audit ORDER BY id DESC LIMIT 200')]
        self.assertEqual(demo['audit'], expected)
        self.assertEqual([row['id'] for row in demo['audit']], sorted((row['id'] for row in demo['audit']), reverse=True))
        self.assertEqual(sorted(demo['audit'][0]), sorted(AUDIT_COLUMNS.split(',')))

    def test_production_configs_projected_once_and_size_matches_v096_minus_both_slices(self):
        administrator = self.login_bootstrap(self.admin)
        self.assertEqual(administrator['factory'].get('production_configs', []), [])
        self.assertTrue(administrator['resources']['production_configs'])
        new = erp.bootstrap(include_expense_history=False, include_byproduct_history=False, factory_light=True, include_audit=False)
        old = erp.bootstrap(include_expense_history=False, include_byproduct_history=False, factory_light=True, include_audit=True)
        self.assertLessEqual(len(encoded(administrator)), SIZE_LIMIT)
        self.assertLessEqual(len(encoded(new)), SIZE_LIMIT)
        # v0.96.0 口径：audit 200条 + factory 与 resources 各一份同内容 production_configs。
        old['factory']['production_configs'] = old['resources']['production_configs']
        for key in set(new) | set(old):
            if key == 'audit':
                continue
            if key == 'factory':
                left = {k: v for k, v in new[key].items() if k != 'production_configs'}
                right = {k: v for k, v in old[key].items() if k != 'production_configs'}
                self.assertEqual(encoded(left), encoded(right), 'factory 除 production_configs 外应与 v0.96.0 逐字节一致')
                continue
            self.assertEqual(encoded(new.get(key)), encoded(old.get(key)), key + ' 应与 v0.96.0 逐字节一致')
        self.assertEqual(len(old['audit']), 200)
        saved = len(encoded(old)) - len(encoded(new))
        self.assertGreaterEqual(saved, len(encoded(old['resources']['production_configs'])) + 200 * 60)
        self.assertGreater(saved, 0)

    def test_order_trail_reads_entity_exactly_through_audit_history(self):
        code, body, _ = self.admin.request('/api/audit?all=1&entity=' + self.order['id'] + '&page_size=200')
        self.assertEqual(code, 200, body)
        with erp.connect() as c:
            expected = [dict(r) for r in c.execute('SELECT ' + AUDIT_COLUMNS + ' FROM audit WHERE entity=? ORDER BY id DESC LIMIT 200', (self.order['id'],))]
        self.assertTrue(expected)
        self.assertEqual(body['rows'], expected)
        self.assertEqual(body['total'], len(expected))
        self.assertEqual([row['id'] for row in body['rows']], sorted((row['id'] for row in expected), reverse=True))
        self.assertFalse(any(row['entity'] != self.order['id'] for row in body['rows']))
        code, empty, _ = self.admin.request('/api/audit?all=1&entity=SO-NO-TRAIL&page_size=200')
        self.assertEqual(code, 200, empty)
        self.assertEqual(empty['rows'], [])
        self.assertEqual(empty['total'], 0)
        warehouse, _ = self.user()
        self.assertEqual(warehouse.request('/api/audit?all=1&entity=' + self.order['id'] + '&page_size=200')[0], 403)
        self.assertEqual(Client(self).request('/api/audit?all=1&entity=' + self.order['id'] + '&page_size=200')[0], 401)


if __name__ == '__main__':
    unittest.main()
