import unittest,json
import test_auth_http as fixture
import delivery_query as q

erp=fixture.erp
class DeliveryQueryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_module_boundaries_and_quantity_only(self):
        with erp.connect(True) as c:
            c.execute('INSERT INTO trade_records VALUES(?,?)',('HQ',json.dumps({'id':'HQ','kind':'trip','business_date':'2026-09-01','amount_cents':101,'document_id':'secret-doc','note':'safe'})))
        wh,_=self.user('dqwh','库管');driver,_=self.user('dqdriver','司机');log,_=self.user('dqlog','物流负责人');accountant,_=self.user('dqacc','会计')
        for client in (wh,log):
            code,r,_=client.request('/api/delivery-history?kind=trips&all=1');self.assertEqual(code,200,r);self.assertNotIn('_cents',json.dumps(r));self.assertNotIn('document_id',json.dumps(r))
            code,r,_=client.request('/api/delivery-history-record?kind=trips&id=HQ');self.assertEqual(code,200,r);self.assertNotIn('_cents',json.dumps(r));self.assertNotIn('document_id',json.dumps(r))
            self.assertEqual(client.request('/api/delivery-history?kind=trips&all=1&status=settled')[0],403)
            self.assertEqual(client.request('/api/delivery-history?kind=documents&all=1')[0],403)
        self.assertEqual(log.request('/api/delivery-history?kind=movements&all=1')[0],403)
        self.assertEqual(driver.request('/api/delivery-history?kind=trips&all=1')[0],403)
        self.assertEqual(accountant.request('/api/delivery-history?kind=documents&all=1')[0],200)
        self.assertEqual(self.admin.request('/api/delivery-history?kind=trips&all=1')[1]['rows'][0]['amount_cents'],101)
    def test_bad_requests_and_missing_original(self):
        for suffix in ('kind=bad','page=0','page_size=201','all=2','all=1&start=2026-09-01','start=2026-10-01&end=2026-09-01','status=bad','all=1&all=1','financial=1','start=2026-02-30'):
            code,r,_=self.admin.request('/api/delivery-history?'+suffix);self.assertEqual(code,400,(suffix,r))
        self.assertEqual(self.admin.request('/api/delivery-history-record?kind=trips&id=absent')[0],404)
        self.assertEqual(self.admin.request('/api/delivery-history-record?kind=trips&id=absent&all=1')[0],400)
