import json
import unittest
import test_auth_http as fixture

erp=fixture.erp


class PayrollHistoryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_financial_module_gate_detail_and_invalid_requests(self):
        with erp.connect(True) as c:
            sheet={'id':'H-S','kind':'sheet','month':'2020-09','state':'confirmed','rows':[{'employee_id':'E','employee_name':'原员工','net_cents':100}]}
            c.execute('INSERT INTO payroll_records VALUES(?,?,?)',('H-S','H-S',json.dumps(sheet)))
        accountant,_=self.user('historyaccountant','会计')
        cashier,_=self.user('historycashier','出纳')
        director,_=self.user('historydirector','厂长')
        warehouse,_=self.user('historywarehouse','库管')
        url='/api/payroll-history?all=1'
        for client in (accountant,cashier):
            code,body,_=client.request(url);self.assertEqual(code,200,body);self.assertEqual(body['summary']['net_cents'],100)
            code,detail,_=client.request('/api/payroll-history-record?kind=sheet&id=H-S&employee_id=E')
            self.assertEqual(code,200,detail);self.assertEqual(detail['row']['employee_name'],'原员工')
        for client in (director,warehouse):
            self.assertEqual(client.request(url)[0],403)
            self.assertEqual(client.request('/api/payroll-history-record?kind=sheet&id=H-S&employee_id=E')[0],403)
        for suffix in ('&page=0','&kind=profile','&status=bad','&salary_month=bad','&extra=1','&all=0'):
            self.assertEqual(accountant.request(url+suffix)[0],400)
