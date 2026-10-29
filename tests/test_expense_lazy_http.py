"""Deferred bootstraps, bounded reminders and per-record financial permission."""
import json
import unittest
import test_auth_http as fixture

erp=fixture.erp


class ExpenseLazyHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def seed(self,n=65):
        with erp.connect(True) as c:
            c.execute('DELETE FROM indirect_expenses');c.execute('DELETE FROM expense_payments');c.execute('DELETE FROM expense_reviews')
            for i in range(n):
                row={'id':f'LAZY{i:03d}','version':1,'business_date':'2026-10-19','period':'2026-10','category':'office','amount_cents':10000,'partner':'测试费用方','handler':'测试','note':'按需费用'}
                c.execute('INSERT INTO indirect_expenses VALUES(?,?,?)',(row['id'],row['id'],erp.dumps(row)))

    def test_deferred_payload_reminders_and_fresh_detail(self):
        self.seed()
        code,legacy,_=self.admin.request('/api/bootstrap');self.assertEqual(code,200)
        self.assertEqual(len(legacy['resources']['expenses']),65)
        code,deferred,_=self.admin.request('/api/bootstrap',headers={'X-ERP-Expense-History':'deferred'});self.assertEqual(code,200)
        self.assertTrue(deferred['resources']['expense_history_deferred'])
        for key in ('expenses','expense_payables','expense_payments'):self.assertEqual(deferred['resources'][key],[])
        self.assertEqual(deferred['resources']['revision'],legacy['resources']['revision'])
        code,flow,_=self.admin.request('/api/expense-workflow?date=2026-10-20');self.assertEqual(code,200)
        self.assertEqual(flow['groups']['costs.review']['carry'],65);self.assertEqual(len(flow['groups']['costs.review']['items']),20)
        code,row,_=self.admin.request('/api/expense-record?id=LAZY064');self.assertEqual(code,200)
        self.assertEqual(row['amount_cents'],10000);self.assertEqual(row['version'],1)
        with erp.connect(True) as c:c.execute("UPDATE indirect_expenses SET payload=json_set(payload,'$.version',2,'$.note','已更新') WHERE id='LAZY064'")
        self.assertEqual(self.admin.request('/api/expense-record?id=LAZY064')[1]['version'],2)
        code,value,_=self.admin.request('/api/bootstrap',headers={'X-ERP-Expense-History':'bad'});self.assertEqual(code,400,value)

    def test_record_and_workflow_enforce_module_amount_and_nonpayable_boundaries(self):
        self.seed(1)
        with erp.connect(True) as c:
            row={'id':'NO-CASH','business_date':'2026-10-20','period':'2026-10','category':'depreciation','payment_mode':'noncash','amount_cents':10000,'version':1}
            c.execute('INSERT INTO indirect_expenses VALUES(?,?,?)',(row['id'],row['id'],erp.dumps(row)))
        accountant,_=self.user('lazy-accountant','会计');cashier,_=self.user('lazy-cashier','出纳');warehouse,_=self.user('lazy-wh','库管')
        for client in (accountant,cashier):
            self.assertEqual(client.request('/api/expense-record?id=LAZY000')[0],200)
            self.assertEqual(client.request('/api/expense-workflow?date=2026-10-20')[0],200)
        self.assertEqual(accountant.request('/api/expense-record?id=NO-CASH')[0],200)
        self.assertEqual(cashier.request('/api/expense-record?id=NO-CASH')[0],403)
        for path in ('/api/expense-record?id=LAZY000','/api/expense-workflow?date=2026-10-20'):self.assertEqual(warehouse.request(path)[0],403)
        with erp.connect(True) as c:c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',('会计',2,json.dumps({'modules':['finance.costs'],'actions':[],'data_scopes':[]}),erp.now()))
        self.assertEqual(accountant.request('/api/expense-record?id=LAZY000')[0],403)
        self.assertEqual(accountant.request('/api/expense-workflow?date=2026-10-20')[0],403)

    def test_bad_record_and_date_parameters(self):
        for path,expected in [('/api/expense-record',400),('/api/expense-record?id=missing',404),('/api/expense-record?id=A&id=B',400),('/api/expense-workflow?date=bad',400)]:
            code,value,_=self.admin.request(path);self.assertEqual(code,expected,(path,value))

    def test_expense_options_match_bootstrap_and_enforce_permissions(self):
        self.seed(65)
        with erp.connect() as c:
            before=list(c.iterdump())
        code,options,_=self.admin.request('/api/expense-options')
        self.assertEqual(code,200,options)
        full=self.admin.request('/api/bootstrap')[1]['resources']
        keys={'categories','expense_counterparties','expense_counterparty_kinds'}
        self.assertEqual(set(options),keys)
        self.assertEqual(options,{k:full[k] for k in keys})
        with erp.connect() as c:self.assertEqual(list(c.iterdump()),before)
        for i,role in enumerate(('库管','会计','出纳','老板','厂长','物流负责人','行政负责人')):
            client,_=self.user('options-'+str(i),role)
            grants=erp.erp_access.defaults(role)
            expected=200 if 'finance.costs' in grants['modules'] and erp.erp_access.can_read_data(grants,'material-costs') else 403
            self.assertEqual(client.request('/api/expense-options')[0],expected,role)
        self.assertEqual(self.admin.request('/api/expense-options?unexpected=1')[0],400)
        self.assertEqual(fixture.Client(self).request('/api/expense-options')[0],401)
