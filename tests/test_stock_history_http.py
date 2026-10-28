import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class StockHistoryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_permissions_and_quantity_only(self):
        with erp.connect(True) as c:
            r={'business_date':'2026-09-01','state':'closed','version':1,'products':[{'product_id':'P001','product_name':'合成产品','unit':'筐','book_qty':'10','counted_qty':'11','shipped_qty':'2','variance_qty':'1','secret_price':'88','amount_cents':999}]}
            c.execute('INSERT INTO stock_closings VALUES(?,?)',(r['business_date'],json.dumps(r)))
        wh,_=self.user('shwarehouse','库管');driver,_=self.user('shdriver','司机')
        code,r,_=wh.request('/api/stock-history?all=1');self.assertEqual(code,200,r);self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['counted_qty'],'11');encoded=json.dumps(r);self.assertNotIn('price',encoded);self.assertNotIn('_cents',encoded)
        self.assertEqual(driver.request('/api/stock-history?all=1')[0],403)
    def test_bad_requests(self):
        for suffix in ('page=0','page_size=201','all=2','all=1&start=2026-09-01','start=2026-10-01&end=2026-09-01','status=bad','all=1&all=1','unknown=1','start=2026-02-30'):
            code,r,_=self.admin.request('/api/stock-history?'+suffix);self.assertEqual(code,400,(suffix,r))
