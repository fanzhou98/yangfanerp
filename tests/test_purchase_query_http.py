"""Procurement query HTTP validation and server-side sensitive field removal."""
import json,unittest
import test_auth_http as fixture

erp=fixture.erp
class PurchaseQueryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def seed(self):
        with erp.connect(True) as c:
            r={'id':'HTTP-PO','version':1,'business_date':'2026-10-01','supplier_id':'Q03-S','supplier_name':'合成供应商','state':'draft','payment_days':30,'total_cents':12500,'lines':[{'id':'L1','material_id':'RM-SOY','qty':'25','price':'5','amount_cents':12500}]}
            c.execute('INSERT INTO purchase_orders VALUES(?,?,?)',(r['id'],r['id'],erp.dumps(r)))
    def test_module_gate_and_money_redaction(self):
        self.seed();url='/api/purchase-orders?all=1'
        code,result,_=self.admin.request(url);self.assertEqual(code,200,result);self.assertEqual(result['summary']['total_cents'],12500)
        for name,role in [('q03wh','库管'),('q03ac','会计'),('q03own','老板')]:
            client,_=self.user(name,role);code,result,_=client.request(url);self.assertEqual(code,200,result)
            if role=='库管':
                text=json.dumps(result);self.assertNotIn('_cents',text);self.assertNotIn('"price"',text);self.assertNotIn('payment_days',text);self.assertEqual(len(result['rows']),1)
            else:self.assertEqual(result['summary']['total_cents'],12500)
        client,_=self.user('q03dir','厂长');self.assertEqual(client.request(url)[0],403)
    def test_bad_parameters_and_empty_scope(self):
        for suffix in ('all=2','all=1&start=2026-10-01','page=0','page_size=201','page=1&page=2','status=bad','start=2026-10-03&end=2026-10-01','start=bad','start=','what=1'):
            code,value,_=self.admin.request('/api/purchase-orders?'+suffix)
            if suffix=='start=':self.assertEqual(code,200,value)
            else:self.assertEqual(code,400,(suffix,value))
        code,r,_=self.admin.request('/api/purchase-orders?all=1&supplier_id=missing');self.assertEqual(code,200);self.assertEqual(r['total'],0);self.assertEqual(r['page'],1)
