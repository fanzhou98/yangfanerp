"""打印路由的错误码：参数/业务错误应为 400，只有越权才是 403。"""
from test_auth_http import AuthHTTPFixture


class PrintErrorTests(AuthHTTPFixture):
    def test_payroll_slip_parameter_errors_are_400_not_403(self):
        accountant, _ = self.user('printacct', '会计')
        status, body, _ = accountant.request('/print/payroll-slip?month=2026-10')
        self.assertEqual(status, 400, body)
        self.assertIn('工资', str(body))
        status, body, _ = accountant.request('/print/payroll-slip?month=2026-10&employee=missing')
        self.assertEqual(status, 400, body)

    def test_invalid_month_is_400_and_permission_is_403(self):
        accountant, _ = self.user('printacct2', '会计')
        status, body, _ = accountant.request('/print/payroll?month=2026-13')
        self.assertEqual(status, 400, body)
        warehouse, _ = self.user('printwh', '库管')
        for path in ('/print/payroll?month=2026-10', '/print/payroll-slip?month=2026-10',
                     '/print/attendance-month?month=2026-10'):
            status, _, _ = warehouse.request(path)
            self.assertEqual(status, 403, path)
