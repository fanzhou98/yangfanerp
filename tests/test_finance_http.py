"""Q02 receivable ledger API permissions and parameter validation."""
import json
import unittest
import test_auth_http as fixture

erp = fixture.erp


class FinanceHTTPTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    personal_password = fixture.AuthHTTPTests.personal_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown
    user = fixture.AuthHTTPTests.user

    def test_receivables_require_finance_scope_and_amount_access(self):
        path = '/api/receivables?all=1&page_size=2&page=1&clearance=all'
        for name, role in [('q02_admin', '管理员'), ('q02_accountant', '会计'), ('q02_cashier', '出纳'), ('q02_owner', '老板')]:
            client, _ = self.user(name, role)
            code, value, _ = client.request(path)
            self.assertEqual(code, 200, (name, value))
            self.assertIn('rows', value)
            self.assertIn('summary', value)
            self.assertIn('receipts', value)
            self.assertLessEqual(len(value['rows']), 2)
        for name, role in [('q02_warehouse', '库管'), ('q02_director', '厂长'), ('q02_driver', '司机')]:
            client, _ = self.user(name, role)
            self.assertEqual(client.request(path)[0], 403)
        client, _ = self.user('q02_limited', '会计')
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',
                      ('会计', 2, json.dumps({'modules': ['sales.reports'], 'actions': [], 'data_scopes': []}), erp.now()))
        self.assertEqual(client.request(path)[0], 403)

    def test_receivables_validate_page_source_and_range(self):
        for extra in ('&page=0', '&page_size=0', '&page_size=201', '&source=bad', '&clearance=bad'):
            code, value, _ = self.admin.request('/api/receivables?all=1' + extra)
            self.assertEqual(code, 400, (extra, value))
        code, value, _ = self.admin.request('/api/receivables?start=2026-09-02&end=2026-09-01')
        self.assertEqual(code, 400, value)

    def test_settled_date_scope_and_invalid_basis(self):
        with erp.connect(True) as c:
            row={'id':'HTTP-SETTLED','state':'reviewed','customer_id':'C001','customer_name':'测试客户','business_date':'2026-09-01','settlement':{'at':'2026-10-20T00:00:00+08:00'},'total_cents':10000,'paid_cents':0,'lines':[]}
            c.execute('INSERT INTO orders VALUES(?,?)',(row['id'],erp.dumps(row)))
        code,value,_=self.admin.request('/api/receivables?start=2026-10-20&end=2026-10-20&basis=settled_date&clearance=all')
        self.assertEqual(code,200,value)
        self.assertIn('HTTP-SETTLED',[r['id'] for r in value['rows']])
        for suffix in ('basis=bad','all=2','page=1&page=2'):
            self.assertEqual(self.admin.request('/api/receivables?'+suffix)[0],400)


if __name__ == '__main__':
    unittest.main()
