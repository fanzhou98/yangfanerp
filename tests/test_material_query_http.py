import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class MaterialQueryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def seed(self):
        with erp.connect(True) as c:
            r={'id':'MH-HTTP','sequence':1,'material_id':'RM-SOY','material_name':'大豆','unit':'公斤','warehouse_id':'WH-TOFU','business_date':'2026-10-01','kind':'opening','qty':'100','amount_cents':40000}
            c.execute('INSERT INTO material_entries VALUES(?,?,?)',(r['id'],r['id'],erp.dumps(r)))
    def test_roles_and_price_scope(self):
        self.seed();wh,_=self.user('mhwarehouse','库管');accountant,_=self.user('mhaccountant','会计');driver,_=self.user('mhdriver','司机')
        for url in ('/api/material-history?all=1','/api/material-history?view=stock&as_of=2026-10-01&material_id=RM-SOY&warehouse_id=WH-TOFU'):
            code,r,_=wh.request(url);self.assertEqual(code,200,r);self.assertFalse(r['financial']);text=json.dumps(r);self.assertNotIn('_cents',text);self.assertNotIn('price',text)
            code,r,_=accountant.request(url);self.assertEqual(code,200,r);self.assertTrue(r['financial'])
        self.assertEqual(driver.request('/api/material-history')[0],403)
    def test_parameter_contract(self):
        for suffix in ('view=bad','view=stock&start=2026-10-01','view=stock&all=1','view=stock&as_of=bad','view=ledger&as_of=2026-10-01','page=0','page_size=201','entry_kind=bad','status=bad','all=2','all=1&start=2026-10-01','start=2026-10-03&end=2026-10-01','page=1&page=2','unknown=1'):
            code,r,_=self.admin.request('/api/material-history?'+suffix);self.assertEqual(code,400,(suffix,r))
