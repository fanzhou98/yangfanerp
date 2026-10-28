import concurrent.futures,unittest,uuid
import test_auth_http as fixture

class ExpenseHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def fee(self,accountant):
        code,e,_=accountant.request('/api/resources/expense',{'business_date':'2026-10-01','period':'2026-10','category':'electricity','amount':'100','partner':'供电单位','handler':'会计','note':'当月电费','request_key':str(uuid.uuid4())})
        self.assertEqual(code,200,e);return e
    def test_cashier_payment_contract_and_financial_redaction(self):
        accountant,_=self.user('accountant','会计');cashier,_=self.user('cashier','出纳');wh,_=self.user()
        e=self.fee(accountant)
        code,d,_=cashier.request('/api/resources');self.assertEqual(code,200,d);self.assertEqual(d['expenses'],[]);self.assertEqual(d['expense_payables'][0]['amount_cents'],10000)
        self.assertTrue(all('value_cents' not in i for i in d['items']))
        review={'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'note':'已核对','handler':'出纳'}
        for client in (accountant,wh):self.assertEqual(client.request('/api/resources/expense-review',review)[0],403)
        self.assertEqual(cashier.request('/api/resources/expense',{})[0],403)
        self.assertEqual(cashier.request('/api/resources/expense-review',review,csrf=False)[0],403)
        code,r,_=cashier.request('/api/resources/expense-review',review);self.assertEqual(code,200,r)
        payment={'id':e['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-22','amount':'60','payee':'供电单位','method':'银行转账','reference':'电费付款回单','note':'第一笔付款','handler':'出纳'}
        self.assertEqual(accountant.request('/api/resources/expense-payment',payment)[0],403)
        code,p,_=cashier.request('/api/resources/expense-payment',payment);self.assertEqual(code,200,p);self.assertEqual(p['amount_cents'],6000)
        self.assertEqual(cashier.request('/api/resources/expense-payment',payment)[1]['id'],p['id'])
        fresh=cashier.request('/api/bootstrap')[1]['resources'];self.assertEqual(fresh['expense_payables'][0]['outstanding_cents'],4000)
        self.assertEqual(wh.request('/api/bootstrap')[1]['resources']['expense_payables'],[])
    def test_concurrent_payment_posts_cannot_double_spend(self):
        accountant,_=self.user('accountant','会计');cashier,_=self.user('cashier','出纳');e=self.fee(accountant)
        self.assertEqual(cashier.request('/api/resources/expense-review',{'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'出纳'})[0],200)
        def pay(_):return cashier.request('/api/resources/expense-payment',{'id':e['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-22','amount':'80','payee':'供电单位','method':'银行转账','reference':'回单','note':'并发付款验证','handler':'出纳'})[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:codes=sorted(pool.map(pay,range(2)))
        self.assertEqual(codes,[200,400]);p=cashier.request('/api/resources')[1];self.assertEqual(len(p['expense_payments']),1);self.assertEqual(p['expense_payables'][0]['outstanding_cents'],2000)

    def test_category_delete_endpoint_enforces_permission_and_records_audit(self):
        accountant,_=self.user('accountant','会计');cashier,_=self.user('cashier','出纳')
        body={'name':'验收待删项目','group':'其他','nature':'变动','payment_mode':'payable','counterparty_kind':'other','active':True,'product_ids':[],'version':0,'request_key':str(uuid.uuid4())}
        code,cat,_=accountant.request('/api/resources/expense-category',body);self.assertEqual(code,200,cat)
        code,error,_=cashier.request('/api/resources/expense-category-delete',{'id':cat['id'],'version':cat['version']});self.assertEqual(code,403,error)
        code,deleted,_=accountant.request('/api/resources/expense-category-delete',{'id':cat['id'],'version':cat['version']});self.assertEqual(code,200,deleted)
        self.assertTrue(deleted['deleted'])
        self.assertNotIn(cat['id'],[r['id'] for r in accountant.request('/api/bootstrap')[1]['resources']['categories']])
        with fixture.erp.connect() as c:
            row=c.execute("SELECT action,entity FROM audit WHERE action='删除间接成本项目' AND entity=?",(cat['id'],)).fetchone()
        self.assertIsNotNone(row)
        code,error,_=accountant.request('/api/resources/expense-category-delete',{'id':cat['id'],'version':cat['version']});self.assertEqual(code,400,error)

if __name__=='__main__':unittest.main()
