"""登录 bootstrap 的人员列表只带页面字段；指纹/更新时间/版本号不下发。"""
import unittest

import test_auth_http as fixture

erp = fixture.erp


class EmployeeProjectionTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    personal_password = fixture.AuthHTTPTests.personal_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown
    user = fixture.AuthHTTPTests.user

    def seed(self):
        person = {'id': 'EP-TEST-1', 'name': '测试人员', 'employee_type': 'management',
                  'department': '管理', 'position': '会计', 'role': '会计', 'group_id': '', 'group_name': '',
                  'sequence': 1, 'active': True, 'phone': '', 'note': '', 'updated_at': '2026-10-01T08:00:00+08:00',
                  'version': 3, 'request_fingerprint': 'f' * 64}
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO factory_employees VALUES(?,?,?)',
                      (person['id'], person['id'], erp.dumps(person)))

    def test_bootstrap_omits_server_only_employee_fields(self):
        self.seed()
        code, value, _ = self.admin.request('/api/bootstrap')
        self.assertEqual(code, 200, value)
        rows = value['factory']['employees']
        self.assertTrue(rows, '测试库应至少有一名人员')
        for row in rows:
            for key in ('request_fingerprint', 'updated_at', 'version'):
                self.assertNotIn(key, row)
            self.assertEqual(row['id'], 'EP-TEST-1')
            for key in ('name', 'employee_type', 'position', 'group_name', 'active'):
                self.assertIn(key, row)

    def test_internal_snapshot_keeps_employee_fields(self):
        self.seed()
        with erp.connect() as c:
            row = next(r for r in erp.production_management.snapshot(c, light=True)['employees'] if r['id'] == 'EP-TEST-1')
        for key in ('request_fingerprint', 'updated_at', 'version'):
            self.assertIn(key, row)


if __name__ == '__main__':
    unittest.main()
