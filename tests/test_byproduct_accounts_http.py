import json
import unittest
import uuid

import test_auth_http as fixture
import erp_access

erp=fixture.erp


class ByproductAccountsHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_customer_sale_receivable_statement_export_and_permissions(self):
        accountant,_=self.user('bean-accountant','会计');cashier,_=self.user('bean-cashier','出纳');warehouse,_=self.user('bean-warehouse','库管')
        status,client,_=accountant.request('/api/master',{'kind':'customer','create':True,'name':'豆渣客户接口测试','legal_name':'结算养殖场','phone':'12345','route':'豆渣自取','delivery_method':'pickup','business_kind':'byproduct'})
        self.assertEqual(status,200,client);cid=client['id']
        status,sale,_=accountant.request('/api/resources/byproduct',{'request_key':str(uuid.uuid4()),'customer_id':cid,'business_date':'2026-10-20','qty':'100','price':'0.5','received':'0','handler':'会计','note':'豆渣货款'})
        self.assertEqual(status,200,sale);self.assertEqual(sale['amount_cents'],5000)
        query='?customer_id='+cid+'&month=2026-10'
        self.assertEqual(warehouse.request('/api/byproduct-statement'+query)[0],403)
        status,preview,_=cashier.request('/api/byproduct-statement'+query)
        self.assertEqual(status,200,preview);self.assertEqual(preview['totals']['payable_cents'],5000)
        with erp.connect() as c:op=dict(c.execute("SELECT * FROM operator_users WHERE id='OP-CASHIER'").fetchone())
        body={'request_key':str(uuid.uuid4()),'customer_id':cid,'month':'2026-10','seller_name':'测试工厂','seller_phone':'123','buyer_name':'结算养殖场','operator_user_id':op['id'],'operator_version':op['version'],'note':'','identity_checked':True,'source_fingerprint':preview['source_fingerprint']}
        self.assertEqual(warehouse.request('/api/byproduct-statements/issue',body)[0],403)
        self.assertEqual(cashier.request('/api/byproduct-statements/issue',body,csrf=False)[0],403)
        status,doc,_=cashier.request('/api/byproduct-statements/issue',body)
        self.assertEqual(status,200,doc);doc_id=doc['document_id']
        self.assertEqual(cashier.request('/api/byproduct-statements/issue',body)[1]['document_id'],doc_id)
        status,export,headers=cashier.request('/api/byproduct-documents/'+doc_id+'.csv')
        self.assertEqual(status,200);self.assertIn('text/csv',headers['Content-Type']);self.assertIn('50.00',export.decode('utf-8-sig'))
        self.assertNotIn('add_kg',export.decode());self.assertNotIn('加量',export.decode())
        self.assertEqual(warehouse.request('/api/byproduct-documents/'+doc_id+'.csv')[0],403)
        status,docs,_=cashier.request('/api/byproduct-documents?customer_id='+cid)
        self.assertEqual(status,200);self.assertEqual(docs[0]['id'],doc_id)
        status,csv,_=cashier.request('/api/export?scope=receivables&source=byproduct&customer_id='+cid)
        self.assertEqual(status,200);self.assertEqual(csv.decode('utf-8-sig').count(sale['id']),1)
        receipt={'id':sale['id'],'version':sale['version'],'business_date':'2026-10-21','amount':'10','note':'到账'}
        self.assertEqual(accountant.request('/api/resources/receive',receipt)[0],403)
        status,received,_=cashier.request('/api/resources/receive',receipt)
        self.assertEqual(status,200,received);self.assertEqual(received['received_cents'],1000)
        self.assertEqual(cashier.request('/api/byproduct-statement'+query)[1]['totals']['payable_cents'],4000)
        self.assertEqual(cashier.request('/api/byproduct-documents/'+doc_id)[1]['totals']['payable_cents'],5000)
        with erp.connect(True) as c:
            grants=erp_access.defaults('会计');grants['modules']=['finance.receivables'];grants['actions']=[]
            c.execute('INSERT OR REPLACE INTO role_permissions(role,version,payload,updated_at) VALUES(?,?,?,?)',('会计',1,json.dumps(grants),'test'))
        status,bootstrap,_=accountant.request('/api/bootstrap')
        self.assertEqual(status,200,bootstrap)
        self.assertIn(sale['id'],[r['id'] for r in bootstrap['resources']['byproducts']])
        self.assertEqual(accountant.request('/api/byproduct-statement'+query)[0],200)
        self.assertEqual(accountant.request('/api/byproduct-statements/issue',{**body,'request_key':str(uuid.uuid4())})[0],403)
