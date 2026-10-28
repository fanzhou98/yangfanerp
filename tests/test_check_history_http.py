import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class CheckHistoryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_reconciliation_only_role_and_quantity_fields(self):
        wh,_=self.user('chwarehouse','库管');acc,_=self.user('chaccountant','会计');driver,_=self.user('chdriver','司机')
        with erp.connect(True) as c:
            r={'id':'IC-2026-06-01','kind':'inventory-check','business_date':'2026-06-01','version':1,'sources_checked':True,'products':[{'product_id':'P001','unit':'筐','pre_qty':'10','post_qty':'8','post_in_qty':'0','post_out_qty':'0','price':'5'}],'source_snapshot':[{'product_id':'P001','unit':'筐','actual_qty':'2','price':'99'}],'amount_cents':999,'history':[]}
            c.execute('INSERT INTO trade_records VALUES(?,?)',(r['id'],json.dumps(r)))
        for client in (wh,acc):
            code,r,_=client.request('/api/inventory-check-history?all=1');self.assertEqual(code,200,r);self.assertEqual(r['rows'][0]['difference_qty'],'0');self.assertNotIn('price',json.dumps(r));self.assertNotIn('_cents',json.dumps(r))
            code,r,_=client.request('/api/inventory-check-record?date=2026-06-01&version=1');self.assertEqual(code,200,r);self.assertNotIn('price',json.dumps(r));self.assertNotIn('_cents',json.dumps(r))
        permissions=acc.request('/api/bootstrap')[1]['permissions']['modules'];self.assertIn('inventory.reconciliation',permissions);self.assertNotIn('inventory.operations',permissions)
        self.assertEqual(driver.request('/api/inventory-check-history?all=1')[0],403);self.assertEqual(driver.request('/api/inventory-check-record?date=2026-06-01&version=1')[0],403)
    def test_bad_requests_and_not_found(self):
        for suffix in ('page=0','page_size=201','all=2','all=1&start=2026-06-01','start=2026-07-01&end=2026-06-01','status=bad','versions=bad','all=1&all=1','unknown=1'):
            code,r,_=self.admin.request('/api/inventory-check-history?'+suffix);self.assertEqual(code,400,(suffix,r))
        for suffix in ('date=bad&version=1','date=2026-06-01','date=2026-06-01&version=0','date=2026-06-01&version=1&version=1'):
            self.assertEqual(self.admin.request('/api/inventory-check-record?'+suffix)[0],400,suffix)
        self.assertEqual(self.admin.request('/api/inventory-check-record?date=2026-06-01&version=1')[0],404)
