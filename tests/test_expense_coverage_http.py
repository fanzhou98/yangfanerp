import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class ExpenseCoverageHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_permissions_preview_estimates_and_no_payables(self):
        acc,_=self.user('coverageacc','会计');wh,_=self.user('coveragewh','库管');url='/api/expense-coverage-preview?amount=320&accrual_method=service_days&service_start=2026-08-25&service_end=2026-09-26'
        code,r,_=acc.request(url);self.assertEqual(code,200,r);self.assertEqual(r['accruals'][0]['amount_cents'],6000);self.assertEqual(wh.request(url)[0],403);self.assertEqual(wh.request('/api/expense-estimates?month=2026-08')[0],403)
        b={'request_key':'estimate-http','business_date':'2026-08-31','category':'water','amount':'60','accrual_method':'service_days','service_account':'HTTP水表','service_start':'2026-08-25','service_end':'2026-08-31','handler':'会计','note':'暂估合成水费','partner':'水务公司'}
        code,e,_=acc.request('/api/resources/expense-estimate',b);self.assertEqual(code,200,e);self.assertTrue(e['is_estimate']);self.assertEqual(acc.request('/api/expense-estimates?month=2026-08')[1]['estimated_cents'],6000)
        with erp.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM indirect_expenses').fetchone()[0],0)
        self.assertEqual(wh.request('/api/resources/expense-estimate',{**b,'request_key':'wh-denied'})[0],403)
        self.assertEqual(self.admin.request('/api/resources/expense-payment',{'id':e['id'],'version':1,'request_key':'deny-est-pay'})[0],400)
    def test_bad_parameters(self):
        for suffix in ('amount=-1','amount=1&accrual_method=bad','amount=1&amount=2','unknown=1','amount=1&accrual_method=service_days&service_start=2026-09-26&service_end=2026-08-25'):
            self.assertEqual(self.admin.request('/api/expense-coverage-preview?'+suffix)[0],400,suffix)
        for suffix in ('month=bad','month=2026-08&page=0','month=2026-08&month=2026-09','month=2026-08&extra=1'):
            self.assertEqual(self.admin.request('/api/expense-estimates?'+suffix)[0],400,suffix)
