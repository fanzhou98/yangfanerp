import json
import unittest
import test_auth_http as fixture

erp=fixture.erp


class SalesChainHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    url_path='/api/factory/report?kind=sales-chain&start=2026-10-01&end=2026-10-31'

    def test_report_uses_existing_sales_module_and_amount_scope(self):
        for name,role in [('accountant','会计'),('cashier','出纳'),('owner','老板')]:
            client,_=self.user('r02_'+name,role)
            code,value,_=client.request(self.url_path)
            self.assertEqual(code,200,value)
            self.assertEqual(sum(value['summary']['stage_counts'].values()),value['summary']['orders'])
        for name,role in [('warehouse','库管'),('director','厂长'),('driver','司机')]:
            client,_=self.user('r02_'+name,role)
            self.assertEqual(client.request(self.url_path)[0],403)
        client,_=self.user('r02_limited','会计')
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',
                      ('会计',2,json.dumps({'modules':['sales.reports'],'actions':[],'data_scopes':[]}),erp.now()))
        self.assertEqual(client.request(self.url_path)[0],403)

    def test_invalid_range_status_and_page_rejected(self):
        for extra in ('&status=unknown-status','&page=0','&page=NaN','&view=bad'):
            self.assertEqual(self.admin.request(self.url_path+extra)[0],400)


    def test_paginated_sales_tabs_use_sales_permissions_and_validate_params(self):
        path='/api/factory/report?kind=sales&start=2026-10-01&end=2026-10-31&paginate=1&page_size=2&page=1&view=customers'
        for name,role in [('q01_accountant','会计'),('q01_cashier','出纳'),('q01_owner','老板')]:
            client,_=self.user(name,role)
            code,value,_=client.request(path)
            self.assertEqual(code,200,value)
            self.assertLessEqual(len(value['rows']),2)
            self.assertGreaterEqual(value['summary']['customer_count'],len(value['rows']))
        for name,role in [('q01_warehouse','库管'),('q01_director','厂长'),('q01_driver','司机')]:
            client,_=self.user(name,role)
            self.assertEqual(client.request(path)[0],403)
        client,_=self.user('q01_limited','会计')
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',
                      ('会计',2,json.dumps({'modules':['sales.reports'],'actions':[],'data_scopes':[]}),erp.now()))
        self.assertEqual(client.request(path)[0],403)

    def test_paginated_sales_tabs_reject_invalid_filters_and_page_size(self):
        for extra in ('&page=0','&page=NaN','&page_size=0','&page_size=201','&view=bad','&state=bad','&sort=bad'):
            code,value,_=self.admin.request('/api/factory/report?kind=sales&start=2026-10-01&end=2026-10-31&paginate=1'+extra)
            self.assertEqual(code,400,(extra,value))

    def test_all_dates_returns_effective_bounds_without_unbounded_rows(self):
        code,value,_=self.admin.request('/api/factory/report?kind=sales&start=2026-10-01&end=2026-10-31&paginate=1&page_size=2&all=1&view=customers')
        self.assertEqual(code,200,value)
        self.assertLessEqual(value['start'],value['end'])
        self.assertLessEqual(len(value['rows']),2)

if __name__=='__main__':unittest.main()
