import json
import unittest
import uuid

import test_workflow as fixture
import funds
import resources_costs as rc

erp=fixture.erp


class FundAccountTests(unittest.TestCase):
    setUp=fixture.WorkflowTests.setUp
    tearDown=fixture.WorkflowTests.tearDown

    def save(self,action,b,role='管理员'):
        with erp.connect(True) as c:return funds.save(c,action,b,role,erp.now,erp.audit)

    def account(self,name='公司基本户',balance='1000',day='2026-10-01'):
        return self.save('account',{'name':name,'kind':'银行账户','opening_date':day,'opening_balance':balance,'active':True})

    def report(self,day='2026-10-31'):
        with erp.connect() as c:return funds.report(c,day)

    def bean(self,amount='100',received='0',account_id=''):
        cid=erp.master({'kind':'customer','create':True,'name':'资金测试豆渣客户','route':'豆渣自取','business_kind':'byproduct'},'管理员')['id']
        with erp.connect(True) as c:return rc.Operations(c,erp.now,erp.audit).byproduct({'request_key':str(uuid.uuid4()),'customer_id':cid,'qty':amount,'price':'1','business_date':'2026-10-20','received':received,'account_id':account_id,'handler':'测试'},'管理员')

    def test_receivable_does_not_move_money_and_actual_receipt_does(self):
        a=self.account();base=self.report()['totals']['balance_cents'];sale=self.bean()
        self.assertEqual(self.report()['totals']['balance_cents'],base)
        with erp.connect(True) as c:
            rc.Operations(c,erp.now,erp.audit).receive_byproduct({'id':sale['id'],'version':sale['version'],'business_date':'2026-10-21','amount':'30','account_id':a['id'],'note':'到账'},'管理员')
        r=self.report();account=next(x for x in r['accounts'] if x['id']==a['id'])
        self.assertEqual(account['balance_cents'],103000)
        self.assertEqual(sum(x['amount_cents'] for x in r['movements'] if x['account_id']==a['id']),3000)

    def test_transfer_is_atomic_idempotent_and_not_operating_cashflow(self):
        a=self.account();b=self.account('现金','100');before=self.report()
        body={'request_key':str(uuid.uuid4()),'from_account_id':a['id'],'to_account_id':b['id'],'business_date':'2026-10-21','amount':'50','note':'提现'}
        t=self.save('transfer',body);self.assertEqual(self.save('transfer',body)['id'],t['id'])
        r=self.report();byid={a['id']:a for a in r['accounts']}
        self.assertEqual(byid[a['id']]['balance_cents'],95000);self.assertEqual(byid[b['id']]['balance_cents'],15000)
        self.assertEqual(before['totals']['balance_cents'],r['totals']['balance_cents'])
        self.assertEqual(before['totals']['monthly_income_cents'],r['totals']['monthly_income_cents'])
        self.assertEqual(before['totals']['monthly_expense_cents'],r['totals']['monthly_expense_cents'])
        with self.assertRaisesRegex(ValueError,'其他内容'):self.save('transfer',{**body,'amount':'60'})
        with self.assertRaisesRegex(ValueError,'不同'):self.save('transfer',{**body,'request_key':str(uuid.uuid4()),'to_account_id':a['id']})
        self.assertEqual(self.report()['totals']['balance_cents'],110000)

    def test_legacy_assignment_changes_no_receivable_or_payment_amounts(self):
        a=self.account();sale=self.bean(received='20');before=self.report();m=next(x for x in before['movements'] if x['id'].startswith('byproduct:'+sale['id']))
        body={'movement_id':m['id'],'fingerprint':m['fingerprint'],'version':0,'account_id':a['id'],'note':'核对银行流水'}
        self.save('assign',body)
        r=self.report();self.assertEqual(r['totals']['balance_cents'],102000)
        self.assertEqual(before['totals']['receivable_cents'],r['totals']['receivable_cents'])
        self.assertEqual(before['totals']['monthly_income_cents'],r['totals']['monthly_income_cents'])
        self.assertEqual(before['totals']['unassigned_count']-1,r['totals']['unassigned_count'])
        with self.assertRaisesRegex(ValueError,'已变化'):self.save('assign',body)

    def test_account_add_edit_disable_delete_and_opening_lock(self):
        a=self.account(balance='0');deleted=self.save('delete',{'id':a['id'],'version':a['version']});self.assertTrue(deleted['deleted'])
        a=self.account(balance='10')
        with self.assertRaisesRegex(ValueError,'不能删除'):self.save('delete',{'id':a['id'],'version':a['version']})
        self.bean(received='1',account_id=a['id'])
        body={**a,'opening_balance':'10','active':False,'name':'基本户（已停用）'}
        disabled=self.save('account',body);self.assertFalse(disabled['active'])
        with erp.connect() as c:
            with self.assertRaisesRegex(ValueError,'已停用'):funds.validate_account(c,a['id'])
        with self.assertRaisesRegex(ValueError,'不能改写'):self.save('account',{**disabled,'opening_balance':'20'})
        with self.assertRaisesRegex(ValueError,'已修改'):self.save('account',body)
        self.assertEqual(self.report()['accounts'][0]['balance_cents'],1100)

    def test_opening_date_excludes_earlier_payments_and_future_events(self):
        a=self.account(day='2026-10-21');self.bean(received='20',account_id=a['id'])
        self.assertEqual(self.report()['accounts'][0]['balance_cents'],100000)
        self.assertEqual(self.report('2026-10-20')['accounts'][0]['balance_cents'],None)
        self.assertEqual(self.report('2026-10-19')['totals']['monthly_income_cents'],sum(x['amount_cents'] for x in self.report('2026-10-19')['movements'] if x['direction']=='in' and x['business_date'].startswith('2026-10')))

    def test_receipts_discounts_expense_payroll_purchases_refunds_project_once(self):
        a=self.account();sources=[('receipts',{'id':'RC-CASH','received_date':'2026-10-21','amount_cents':1000,'rounding_cents':500,'discount_cents':200}),
                ('purchase_payments',{'id':'PP-CASH','business_date':'2026-10-21','amount_cents':200}),
                ('expense_payments',{'id':'EP-CASH','business_date':'2026-10-21','amount_cents':300}),
                ('payroll_records',{'id':'WAGE-CASH','business_date':'2026-10-21','amount_cents':400,'kind':'payment'}),
                ('finished_goods_records',{'id':'FG-CASH','business_date':'2026-10-21','amount_cents':500,'kind':'payment'})]
        with erp.connect(True) as c:
            for table,r in sources:
                r['account_id']=a['id'];cols={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
                if 'request_key' in cols:c.execute('INSERT INTO '+table+'(id,request_key,payload) VALUES(?,?,?)',(r['id'],r['id'],rc.dump(r)))
                else:c.execute('INSERT INTO '+table+'(id,payload) VALUES(?,?)',(r['id'],rc.dump(r)))
            c.execute('INSERT INTO sales_returns(id,payload) VALUES(?,?)',('RET-CASH',rc.dump({'id':'RET-CASH','business_date':'2026-10-21','customer_id':'C001','finance':{'refunds':[{'id':'RF-CASH','refund_date':'2026-10-21','amount_cents':100,'account_id':a['id']}]}})))
            flows=[r for r in funds.movements(c) if r['account_id']==a['id']]
            self.assertEqual(len(flows),6);self.assertEqual(sum(r['amount_cents']*(1 if r['direction']=='in' else -1) for r in flows),-500)

    def test_permissions_and_amount_validation(self):
        for role in ('库管','厂长','司机','老板'):
            with self.assertRaises(ValueError):self.save('account',{},role)
        for amount in ('NaN','Infinity','0.001','100000001'):
            with self.assertRaises(ValueError):self.account(balance=amount)
        with erp.connect() as c:self.assertEqual(funds.accounts(c),[])

    def test_flow_filters_and_server_pages_cover_all_rows(self):
        with erp.connect(True) as c:
            for i in range(55):
                r={'id':'RC-Q02-%03d'%i,'received_date':'2025-01-%02d'%((i%28)+1),'amount_cents':100+i,'order_id':'Q02-%03d'%i,'customer_name':'分页测试客户','account_id':'FA-Q02' if i<30 else 'FA-Q02B'}
                c.execute('INSERT INTO receipts(id,payload) VALUES(?,?)',(r['id'],rc.dump(r)))
        with erp.connect() as c:
            first=funds.report(c,'2025-01-31',month='2025-01',direction='in',page=1,page_size=20)
            last=funds.report(c,'2025-01-31',month='2025-01',direction='in',page=3,page_size=20)
            account=funds.report(c,'2025-01-31',month='2025-01',account_id='FA-Q02',page=1,page_size=50)
            empty=funds.report(c,'2025-01-31',month='2025-01',direction='out',page=1)
        self.assertEqual((first['movement_total'],first['movement_pages'],first['movement_page']),(55,3,1))
        self.assertEqual(len(first['movements']),20);self.assertEqual(len(last['movements']),15)
        self.assertEqual((account['movement_total'],len(account['movements'])),(30,30))
        self.assertEqual(empty['movement_total'],0);self.assertEqual(empty['movement_pages'],1)
        self.assertEqual(first['flow_totals']['count'],55)
        with erp.connect() as c:
            with self.assertRaisesRegex(ValueError,'月份'):funds.report(c,'2025-01-31',month='2025-13')
            with self.assertRaisesRegex(ValueError,'方向'):funds.report(c,'2025-01-31',direction='sideways')
            with self.assertRaisesRegex(ValueError,'每页'):funds.report(c,'2025-01-31',page_size=0)
