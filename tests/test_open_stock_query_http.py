import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class OpenStockHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_permissions_quantity_only_and_no_source_mutation(self):
        with erp.connect(True) as c:
            r={'business_date':'2026-01-01','version':1,'stock':[{'product_id':'P001','existing_qty':'10','produced_qty':'2','secret_price':'88','amount_cents':999}],'secret':'not public'}
            c.execute('INSERT INTO warehouse_plans VALUES(?,?)',(r['business_date'],json.dumps(r)))
        wh,_=self.user('oswarehouse','库管');driver,_=self.user('osdriver','司机')
        code,r,_=wh.request('/api/open-stock-history?start=2026-01-01&end=2026-01-01&product_id=P001');self.assertEqual(code,200,r);self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['book_qty'],'12');encoded=json.dumps(r);self.assertNotIn('price',encoded);self.assertNotIn('_cents',encoded);self.assertNotIn('secret',encoded)
        self.assertEqual(driver.request('/api/open-stock-history?all=1')[0],403)
        with erp.connect() as c:self.assertEqual(json.loads(c.execute("SELECT payload FROM warehouse_plans WHERE business_date='2026-01-01'").fetchone()[0])['secret'],'not public')
    def test_bad_requests(self):
        for suffix in ('page=0','page_size=201','all=2','all=1&start=2026-09-01','start=2026-10-01&end=2026-09-01','status=bad','all=1&all=1','unknown=1','start=2026-02-30'):
            code,r,_=self.admin.request('/api/open-stock-history?'+suffix);self.assertEqual(code,400,(suffix,r))
