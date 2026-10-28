"""Kind-specific procurement permissions and validation use synthetic HTTP sessions."""
import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class PurchaseLedgerHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_permissions_quantities_and_financial_scope(self):
        with erp.connect(True) as c:
            r={'id':'HTTP-LR','order_id':'NO-ORDER','business_date':'2026-10-01','amount_cents':30,'due_date':'2026-11-01','lines':[]}
            c.execute('INSERT INTO purchase_receipts VALUES(?,?,?)',(r['id'],r['id'],erp.dumps(r)))
        warehouse,_=self.user('q75wh','库管');cashier,_=self.user('q75cash','出纳');accountant,_=self.user('q75acc','会计');director,_=self.user('q75dir','厂长')
        code,result,_=warehouse.request('/api/purchase-ledger?kind=receipts&all=1');self.assertEqual(code,200,result);self.assertEqual(len(result['rows']),1)
        text=json.dumps(result);self.assertNotIn('_cents',text);self.assertNotIn('due_date',text)
        for kind in ('charges','payments'):self.assertEqual(warehouse.request('/api/purchase-ledger?kind='+kind)[0],403);self.assertEqual(cashier.request('/api/purchase-ledger?kind='+kind)[0],200)
        self.assertEqual(cashier.request('/api/purchase-ledger?kind=receipts')[0],403)
        self.assertEqual(accountant.request('/api/purchase-ledger?kind=receipts&all=1')[1]['summary']['amount_cents'],30)
        self.assertEqual(director.request('/api/purchase-ledger?kind=receipts')[0],403)
        # A financial menu without the sensitive data scope cannot expose payment amounts.
        with erp.connect(True) as c:
            grants={'modules':['finance.payables'],'actions':[],'data_scopes':[]}
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',('会计',2,json.dumps(grants),erp.now()))
        self.assertEqual(accountant.request('/api/purchase-ledger?kind=payments')[0],403)
    def test_invalid_parameters_and_duplicate_values(self):
        for suffix in ('kind=bad','kind=receipts&kind=payments','kind=receipts&status=paid','kind=payments&charge_kind=freight','kind=charges&payment_kind=goods','kind=pending&status=unpaid','all=2','page=0','page_size=201','page=abc','start=2026-10-03&end=2026-10-01','all=1&start=2026-10-01','unknown=1'):
            code,value,_=self.admin.request('/api/purchase-ledger?'+suffix);self.assertEqual(code,400,(suffix,value))
