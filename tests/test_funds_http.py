import unittest
import uuid

import test_auth_http as fixture

erp=fixture.erp


class FundsHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_account_crud_actual_receipts_transfer_and_role_boundaries(self):
        accountant,_=self.user('fund-accountant','会计');cashier,_=self.user('fund-cashier','出纳');owner,_=self.user('fund-owner','老板');warehouse,_=self.user('fund-warehouse','库管')
        body={'action':'account','name':'公司基本户','kind':'银行账户','opening_date':'2026-10-01','opening_balance':'1000','active':True,'account_no':'演示尾号1234'}
        self.assertEqual(warehouse.request('/api/fund-accounts')[0],403)
        self.assertEqual(owner.request('/api/fund-accounts',body)[0],403)
        self.assertEqual(accountant.request('/api/fund-accounts',body,csrf=False)[0],403)
        status,a,_=accountant.request('/api/fund-accounts',body);self.assertEqual(status,200,a)
        status,b,_=cashier.request('/api/fund-accounts',{**body,'name':'现金','kind':'现金','opening_balance':'0'});self.assertEqual(status,200,b)
        status,catalog,_=cashier.request('/api/bootstrap');self.assertEqual(status,200)
        entry=next(r for r in catalog['fund_accounts'] if r['id']==a['id']);self.assertNotIn('opening_balance_cents',entry);self.assertNotIn('account_no',entry)
        self.assertEqual(warehouse.request('/api/bootstrap')[1]['fund_accounts'],[])
        cid=accountant.request('/api/master',{'kind':'customer','create':True,'name':'资金账户豆渣客户','route':'豆渣自取','business_kind':'byproduct'})[1]['id']
        status,sale,_=accountant.request('/api/resources/byproduct',{'customer_id':cid,'business_date':'2026-10-20','qty':'100','price':'1','received':'0','handler':'会计','request_key':str(uuid.uuid4())});self.assertEqual(status,200,sale)
        before=cashier.request('/api/fund-accounts?date=2026-10-31')[1]
        self.assertEqual(before['totals']['balance_cents'],100000)
        receipt={'id':sale['id'],'version':sale['version'],'business_date':'2026-10-21','amount':'30','account_id':a['id'],'note':'到账凭据'}
        status,paid,_=cashier.request('/api/resources/receive',receipt);self.assertEqual(status,200,paid)
        report=owner.request('/api/fund-accounts?date=2026-10-31')[1]
        self.assertEqual(report['totals']['balance_cents'],103000)
        paged=cashier.request('/api/fund-accounts?date=2026-10-31&page=1&direction=in&account='+a['id'])[1]
        self.assertGreaterEqual(paged['movement_total'],1);self.assertEqual(paged['movement_page'],1);self.assertTrue(all(r['direction']=='in' and r['account_id']==a['id'] for r in paged['movements']))
        self.assertEqual(cashier.request('/api/fund-accounts?date=2026-10-31&page=0')[0],400)
        transfer={'action':'transfer','request_key':str(uuid.uuid4()),'from_account_id':a['id'],'to_account_id':b['id'],'business_date':'2026-10-21','amount':'10','note':'提现'}
        status,t,_=cashier.request('/api/fund-accounts',transfer);self.assertEqual(status,200,t)
        self.assertEqual(cashier.request('/api/fund-accounts',transfer)[1]['id'],t['id'])
        self.assertEqual(owner.request('/api/fund-accounts?date=2026-10-31')[1]['totals']['balance_cents'],103000)
        self.assertEqual(cashier.request('/api/fund-accounts',{'action':'delete','id':b['id'],'version':b['version']})[0],400)
        status,empty,_=cashier.request('/api/fund-accounts',{**body,'name':'临时未用账户','opening_balance':'0'});self.assertEqual(status,200,empty)
        status,result,_=cashier.request('/api/fund-accounts',{'action':'delete','id':empty['id'],'version':empty['version']});self.assertEqual(status,200,result);self.assertTrue(result['deleted'])
        status,disabled,_=cashier.request('/api/fund-accounts',{**body,'id':a['id'],'version':a['version'],'active':False});self.assertEqual(status,200,disabled)
        self.assertEqual(cashier.request('/api/resources/receive',{**receipt,'version':paid['version']})[0],400)
        self.assertEqual(cashier.request('/api/fund-accounts',{**body,'id':a['id'],'version':a['version']})[0],400)

    def test_custom_actual_range_paging_and_validation(self):
        with erp.connect(True) as c:
            for i in range(60):
                value={'id':f'HTTP-SQL{i:03d}','order_id':'HTTP-ORDER','received_date':'2026-09-30' if i<30 else '2026-10-01','amount_cents':100}
                c.execute('INSERT INTO receipts VALUES(?,?)',(value['id'],erp.dumps(value)))
        path='/api/fund-accounts?date=2026-10-31&start=2026-09-30&end=2026-10-01&page=1&page_size=20'
        code,result,_=self.admin.request(path)
        self.assertEqual(code,200,result)
        self.assertEqual((result['movement_total'],len(result['movements'])),(60,20))
        self.assertEqual(result['flow_totals']['income_cents'],6000)
        for extra in ('start=bad&end=2026-10-01','start=2026-10-01','start=2026-10-02&end=2026-10-01','start=2026-10-01&end=2026-10-02&month=2026-10','page=100001','page_size=201','page_size=bad','page=1&page=2'):
            code,value,_=self.admin.request('/api/fund-accounts?date=2026-10-31&'+extra)
            self.assertEqual(code,400,(extra,value))
