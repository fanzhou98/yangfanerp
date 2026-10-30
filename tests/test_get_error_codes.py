"""GET 路由的错误码：参数/业务错误应为 400，越权仍为 403。"""
from test_auth_http import AuthHTTPFixture


class GetErrorCodeTests(AuthHTTPFixture):
    def test_business_errors_are_400_not_permission_denied(self):
        warehouse, _ = self.user('geterrwh1', '库管')
        status, body, _ = warehouse.request('/api/inventory?date=bad-date')
        self.assertEqual(status, 400, body)
        self.assertIn('YYYY-MM-DD', str(body))
        accountant, _ = self.user('geterracct', '会计')
        cases = {'/api/customer-statement?customer_id=NOPE&date=2026-10-30': '客户不存在',
                 '/api/statement-documents/NOPE': '不存在'}
        for path, hint in cases.items():
            status, body, _ = accountant.request(path)
            self.assertEqual(status, 400, (path, body))
            self.assertIn(hint, str(body), path)

    def test_permission_denials_stay_403(self):
        warehouse, _ = self.user('geterrwh2', '库管')
        for path in ('/api/users', '/api/role-permissions',
                     '/api/customer-statement?customer_id=NOPE&date=2026-10-30'):
            status, _, _ = warehouse.request(path)
            self.assertEqual(status, 403, path)
        driver, _ = self.user('geterrdriver', '司机')
        status, _, _ = driver.request('/api/inventory?date=2026-10-30')
        self.assertEqual(status, 403)

    def test_unknown_api_path_is_404_and_does_not_look_like_denial(self):
        accountant, _ = self.user('geterrunk', '会计')
        for path in ('/api/not-a-route', '/api/reports?source=management-month'):
            status, body, _ = accountant.request(path)
            self.assertEqual(status, 404, (path, body))
            self.assertIn('未知接口', str(body), path)
