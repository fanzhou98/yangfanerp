"""Module and amount grants are enforced before any resource ledger payload."""
import json
import unittest
import test_auth_http as fixture

erp=fixture.erp


class ResourceQueryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_module_and_amount_scope(self):
        for name,role in [('res_accountant','会计'),('res_cashier','出纳'),('res_owner','老板')]:
            client,_=self.user(name,role)
            for kind in ('expenses','payables','payments','byproducts','byproduct-receipts'):
                code,value,_=client.request('/api/resource-ledger?all=1&kind='+kind)
                self.assertEqual(code,200,(role,kind,value))
        for name,role in [('res_warehouse','库管'),('res_director','厂长'),('res_driver','司机')]:
            client,_=self.user(name,role)
            for kind in ('expenses','payments','byproducts'):
                self.assertEqual(client.request('/api/resource-ledger?all=1&kind='+kind)[0],403)
        client,_=self.user('res_limited','会计')
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',('会计',2,json.dumps({'modules':['finance.costs'],'actions':[],'data_scopes':[]}),erp.now()))
        for kind in ('expenses','payments','byproducts'):
            self.assertEqual(client.request('/api/resource-ledger?all=1&kind='+kind)[0],403)

    def test_invalid_parameters_are_400(self):
        for suffix in ('page=0','page_size=201','page_size=x','kind=bad','stage=bad','period=2026-13','all=2','start=2026-10-20&end=2026-09-20'):
            code,value,_=self.admin.request('/api/resource-ledger?all=1&'+suffix)
            self.assertEqual(code,400,(suffix,value))
