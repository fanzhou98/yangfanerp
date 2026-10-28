import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class InventoryQueryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_kind_roles_and_redaction(self):
        with erp.connect(True) as c:
            r={'id':'HTTP-IH','received_date':'2026-10-01','product_id':'P001','customer_id':'C001','qty':'1','net_kg':'10','unit':'筐','source_price':'5','reference_price':'5','finance':{'state':'posted','amount_cents':500,'allocations':[],'refunds':[]},'disposals':[]}
            c.execute('INSERT INTO sales_returns VALUES(?,?)',(r['id'],erp.dumps(r)))
        wh,_=self.user('ihwarehouse','库管');accountant,_=self.user('ihaccountant','会计');director,_=self.user('ihdirector','厂长')
        code,r,_=wh.request('/api/inventory-history?kind=returns&all=1');self.assertEqual(code,200,r);self.assertEqual(len(r['rows']),1);encoded=json.dumps(r);self.assertNotIn('_cents',encoded);self.assertNotIn('"finance"',encoded);self.assertNotIn('price',encoded)
        self.assertEqual(wh.request('/api/inventory-history?kind=returns&all=1&status=credit')[0],403)
        code,r,_=accountant.request('/api/inventory-history?kind=returns&all=1');self.assertEqual(code,200,r);self.assertEqual(r['summary']['wallet_cents'],500)
        self.assertEqual(director.request('/api/inventory-history?kind=returns')[0],403)
        self.assertEqual(wh.request('/api/inventory-history?kind=processing')[0],200)
    def test_bad_request_contract(self):
        for suffix in ('kind=bad','page=0','page_size=201','all=2','all=1&start=2026-10-01','start=2026-11-01&end=2026-10-01','status=bad','kind=returns&origin=internal','kind=processing&customer_id=C001','kind=returns&kind=processing','unknown=1'):
            code,r,_=self.admin.request('/api/inventory-history?'+suffix);self.assertEqual(code,400,(suffix,r))
