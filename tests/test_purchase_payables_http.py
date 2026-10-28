"""Goods payable page route: month filters, amounts scope, admin role boundaries."""
import unittest,json
import test_auth_http as fixture
erp=fixture.erp

class PurchasePayablesHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def seed(self):
        with erp.connect(True) as c:
            order={'id':'PBH1','version':1,'business_date':'2026-10-03','expected_date':'2026-10-05','supplier_id':'S1','supplier_name':'应付测试供应商','state':'confirmed','total_cents':1000,
              'lines':[{'id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'10','price':'100','amount_cents':1000}]}
            receipt={'id':'PBH1-R','order_id':'PBH1','business_date':'2026-10-05','supplier_id':'S1','supplier_name':'应付测试供应商','due_date':'2026-01-01','amount_cents':1000,
              'lines':[{'line_id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'10','amount_cents':1000,'material_entry_id':'M1'}]}
            payment={'id':'PBH1-P','order_id':'PBH1','supplier_id':'S1','supplier_name':'应付测试供应商','business_date':'2026-10-06','amount_cents':400}
            for table,row in (('purchase_orders',order),('purchase_receipts',receipt),('purchase_payments',payment)):
                c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(row['id'],row['id'],erp.dumps(row)))
    def test_month_summary_and_permissions(self):
        self.seed();warehouse,_=self.user('q76wh','库管');accountant,_=self.user('q76acc','会计')
        code,result,_=self.admin.request('/api/purchase-ledger?kind=payables&month=2026-10')
        self.assertEqual(code,200,result);self.assertEqual(result['total'],1)
        self.assertEqual(result['summary']['received_cents'],1000);self.assertEqual(result['summary']['paid_cents'],400)
        self.assertEqual(result['summary']['outstanding_cents'],600);self.assertEqual(result['summary']['overdue_cents'],600)
        self.assertEqual(result['rows'][0]['id'],'PBH1');self.assertEqual(result['month'],'2026-10')
        self.assertEqual(self.admin.request('/api/purchase-ledger?kind=payables&month=2026-09')[1]['total'],0)
        self.assertEqual(warehouse.request('/api/purchase-ledger?kind=payables')[0],403)
        self.assertEqual(accountant.request('/api/purchase-ledger?kind=payables')[0],200)
        with erp.connect(True) as c:
            grants={'modules':['finance.payables'],'actions':[],'data_scopes':[]}
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',('会计',2,json.dumps(grants),erp.now()))
        self.assertEqual(accountant.request('/api/purchase-ledger?kind=payables')[0],403)
    def test_invalid_parameters(self):
        for suffix in ('kind=payables&month=2026-13','kind=payables&month=2026-1','kind=payables&status='+__import__('urllib.parse',fromlist=['quote']).quote('坏状态'),'kind=payables&start=2026-10-01','kind=payables&all=1','kind=payables&payment_kind=goods','kind=payables&month=2026-10&month=2026-10','kind=payables&page=0','kind=payables&page_size=201','kind=payables&unknown=1'):
            code,value,_=self.admin.request('/api/purchase-ledger?'+suffix);self.assertEqual(code,400,(suffix,value))
