"""Finished-goods history HTTP route: filters, validation and amount scope."""
import json
import unittest
import test_auth_http as fixture
erp=fixture.erp


class FinishedGoodsHistoryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def seed(self):
        with erp.connect(True) as c:
            rows={
              'FGQ1':{'kind':'receipt','business_date':'2026-08-05','supplier_id':'S1','supplier_name':'外购甲','amount_cents':10000,'version':1,'lines':[{'product_id':'OIL','product_name':'油豆腐','unit':'盒','qty':'10','amount_cents':10000}]},
              'FGQ1-P':{'kind':'payment','business_date':'2026-08-06','receipt_id':'FGQ1','supplier_id':'S1','supplier_name':'外购甲','amount_cents':4000,'version':1},
              'FGQ2':{'kind':'receipt','business_date':'2026-09-06','supplier_id':'S2','supplier_name':'外购乙','amount_cents':5000,'version':1,'pricing_pending':True,'lines':[]},
            }
            for rid,value in rows.items():c.execute('INSERT INTO finished_goods_records VALUES(?,?)',(rid,json.dumps(value,ensure_ascii=False)))

    def test_history_and_permissions(self):
        self.seed();warehouse,_=self.user('fgqwh','库管');accountant,_=self.user('fgqacc','会计')
        code,r,_=self.admin.request('/api/finished-goods?view=history&start=2026-08-01&end=2026-08-31')
        self.assertEqual(code,200,r);self.assertEqual(r['total'],1);self.assertEqual(r['summary']['paid_cents'],4000)
        self.assertEqual(r['summary']['outstanding_cents'],6000);self.assertEqual(r['rows'][0]['id'],'FGQ1')
        self.assertEqual(warehouse.request('/api/finished-goods?view=history&start=2026-08-01&end=2026-08-31')[0],403)
        self.assertEqual(accountant.request('/api/finished-goods?view=history&start=2026-08-01&end=2026-08-31')[0],200)
        with erp.connect(True) as c:
            grants={'modules':['purchase.orders','finance.payables'],'actions':[],'data_scopes':[]}
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',('会计',2,json.dumps(grants),erp.now()))
        self.assertEqual(accountant.request('/api/finished-goods?view=history&start=2026-08-01&end=2026-08-31')[0],403)

    def test_invalid_parameters(self):
        for suffix in ('view=bad','view=history&start=2026-08-03&end=2026-08-01','view=history&start=2026-08-01&end=2026-08-02&all=1','view=history&start=2026-08-01&end=2026-08-02&status=bad','view=history&start=2026-08-01&end=2026-08-02&page=0','view=history&start=2026-08-01&end=2026-08-02&page_size=201'):
            code,value,_=self.admin.request('/api/finished-goods?'+suffix)
            self.assertEqual(code,400,(suffix,value))
