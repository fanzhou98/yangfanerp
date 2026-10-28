"""Real HTTP monthly close and full payable regression using an isolated DB."""
import unittest,uuid,json
from urllib.parse import urlencode
import test_auth_http as fixture
import resources_costs as rc,cost_allocation as ca
class ExpenseCloseHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_close_preview_permissions_and_full_actual_payable(self):
        acc,_=self.user('closeacc','会计');wh,_=self.user('closewh','库管')
        self.assertEqual(wh.request('/api/expense-close-preview?month=2026-09')[0],403)
        for suffix in ('month=bad','month=2026-09&extra=1','month=2026-09&month=2026-10'):
            self.assertEqual(acc.request('/api/expense-close-preview?'+suffix)[0],400)
        with fixture.erp.connect() as c:version=next(x['version'] for x in ca.categories(c) if x['id']=='water')
        b={'request_key':str(uuid.uuid4()),'business_date':'2026-09-26','category':'water','amount':'260','handler':'会计','note':'合成实际水费','partner':'水务公司','service_account':'HTTP水表','accrual_method':'service_days','service_start':'2026-08-31','service_end':'2026-09-26','irregular_periodic':True,'irregular_category_version':version}
        code,first,_=acc.request('/api/resources/expense',b);self.assertEqual(code,200,first)
        code,p,_=acc.request('/api/expense-close-preview?month=2026-09');self.assertEqual(code,200,p);r=next(x for x in p['rows'] if x['category']=='water');self.assertEqual(r['supplement_cents'],4000);self.assertNotIn('_prototype',r)
        body={'month':'2026-09','state':'closed','version':0,'note':'核对覆盖日期','close_fingerprint':p['fingerprint']}
        self.assertEqual(acc.request('/api/resources/period',{**body,'close_fingerprint':'stale'})[0],400)
        code,period,_=acc.request('/api/resources/period',body);self.assertEqual(code,200,period)
        with fixture.erp.connect() as c:frozen=c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0]
        b.update(request_key=str(uuid.uuid4()),business_date='2026-10-24',amount='336',service_start='2026-09-26',service_end='2026-10-24')
        q={k:v for k,v in b.items() if k in ('business_date','category','amount','partner','service_account','accrual_method','service_start','service_end')}
        code,preview,_=acc.request('/api/expense-coverage-preview?'+urlencode(q));self.assertEqual(code,200,preview);self.assertEqual(preview['blocked_months'],[]);self.assertEqual(preview['registration_adjustment_cents'],800)
        b['estimate_versions']=[{'id':e['id'],'version':e['version']} for e in preview['estimate_candidates']]
        code,second,_=acc.request('/api/resources/expense',b);self.assertEqual(code,200,second);self.assertEqual(second['amount_cents'],33600);self.assertEqual(second['registration_adjustment_cents'],800)
        with fixture.erp.connect() as c:
            bill=next(e for e in rc.expense_projection(c) if e['id']==second['id']);self.assertEqual(bill['outstanding_cents'],33600)
            self.assertEqual(c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0],frozen)
