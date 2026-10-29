"""v0.97.0/v0.99.0 bootstrap 投影裁剪：登录态不再随首屏下发审计200条，production_configs 只带当天生效与排期版本。

登录后订单详情的“操作轨迹”改为按对象读取 /api/audit（audit_query.history），
所以这里同时校验该接口的 entity 精确过滤、顺序与权限；匿名/演示 bootstrap 仍返回最近200条。
v0.99.0 起历史配置版本正文不进初始化，只留全量版本头 production_config_index，
完整历史仍由 /api/factory/report?kind=system-settings 按需读取。
"""
import json
import unittest
from datetime import date, timedelta

from test_auth_http import AuthHTTPFixture, Client
from test_workflow import erp
import production_config as pc

DEFERRED = {'X-ERP-Expense-History': 'deferred', 'X-ERP-Byproduct-History': 'deferred'}
AUDIT_COLUMNS = 'id,at,role,action,entity,actor_id,actor_name,request_id'
SIZE_LIMIT = 125000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()


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
        # 追加三份配置：历史、前一天生效、排期到未来；初始化只应带“当天生效 + 排期”两类。
        with erp.connect(True) as c:
            base = pc.seed(c)
            self.start_version = (c.execute('SELECT MAX(version) FROM production_config_versions').fetchone()[0] or 0) + 1
            for offset, delta in ((0, -30), (1, -1), (2, 30)):
                effective = str(date.today() + timedelta(days=delta))
                value = dict(base, version=self.start_version + offset, effective_date=effective)
                c.execute('INSERT INTO production_config_versions VALUES(?,?,?)', (value['version'], effective, json.dumps(value, ensure_ascii=False)))
            self.versions = pc.history(c)
        today = date.today().isoformat()
        self.keep = [next(v for v in reversed(self.versions) if v['effective_date'] <= today)]
        self.keep += [v for v in self.versions if v['effective_date'] > today]

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
        resources = administrator['resources']
        self.assertEqual(administrator['factory'].get('production_configs', []), [])
        self.assertTrue(resources['production_configs'])
        new = erp.bootstrap(include_expense_history=False, include_byproduct_history=False, factory_light=True, include_audit=False)
        old = erp.bootstrap(include_expense_history=False, include_byproduct_history=False, factory_light=True, include_audit=True)
        self.assertLessEqual(len(encoded(administrator)), SIZE_LIMIT)
        self.assertLessEqual(len(encoded(new)), SIZE_LIMIT)
        with erp.connect() as c:
            versions = pc.history(c)
        today = date.today().isoformat()
        keep = [next(v for v in reversed(versions) if v['effective_date'] <= today)]
        keep += [v for v in versions if v['effective_date'] > today]
        self.assertEqual([v['version'] for v in resources['production_configs']], [v['version'] for v in keep])
        self.assertEqual([v['version'] for v in resources['production_config_index']], [v['version'] for v in versions])
        for row in resources['production_config_index']:
            self.assertEqual(sorted(row), ['effective_date', 'note', 'published_at', 'published_by', 'version'])
        full = versions
        # v0.96.0 口径：audit 200条 + factory 与 resources 各一份同内容 production_configs。
        old['resources']['production_configs'] = full
        old['resources'].pop('production_config_index', None)
        old['factory']['production_configs'] = full
        trimmed_keys = ('production_configs', 'production_config_index')
        for key in set(new) | set(old):
            if key == 'audit':
                continue
            if key in ('resources', 'factory'):
                left = {k: v for k, v in new[key].items() if k not in trimmed_keys}
                right = {k: v for k, v in old[key].items() if k not in trimmed_keys}
                self.assertEqual(encoded(left), encoded(right), key + ' 除配置投影外应与 v0.96.0 逐字节一致')
                continue
            self.assertEqual(encoded(new.get(key)), encoded(old.get(key)), key + ' 应与 v0.96.0 逐字节一致')
        self.assertEqual(len(old['audit']), 200)
        trimmed = 2 * len(encoded(full)) - len(encoded(new['resources']['production_configs'])) - len(encoded(new['resources']['production_config_index']))
        self.assertGreater(trimmed, 0)
        saved = len(encoded(old)) - len(encoded(new))
        # 逐键比较已保证除两处裁剪外逐字节一致；这里只校验减少量与裁剪内容同量级（嵌套标点差几十字节）。
        self.assertGreaterEqual(saved, len(encoded(old['audit'])) + trimmed - 100)
        self.assertLessEqual(saved, len(encoded(old['audit'])) + trimmed + 100)

    def test_historical_config_bodies_stay_out_but_full_history_stays_readable(self):
        resources = self.login_bootstrap(self.admin)['resources']
        self.assertEqual([v['version'] for v in resources['production_configs']], [v['version'] for v in self.keep])
        self.assertEqual([v['version'] for v in resources['production_config_index']], [v['version'] for v in self.versions])
        self.assertNotIn(self.start_version, [v['version'] for v in resources['production_configs']])
        code, body, _ = self.admin.request('/api/factory/report?kind=system-settings')
        self.assertEqual(code, 200, body)
        self.assertEqual([v['version'] for v in body['production_config_history']], [v['version'] for v in self.versions])
        self.assertTrue(all(len(v['systems']) for v in body['production_config_history']))

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
