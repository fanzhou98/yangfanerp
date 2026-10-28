import json,unittest,uuid
import test_resources_costs as ledger
import resources_costs as rc
import erp_access as access

erp=ledger.erp
class ExpensePaymentTests(unittest.TestCase):
    setUp=ledger.ResourceLedgerTests.setUp
    tearDown=ledger.ResourceLedgerTests.tearDown
    call=ledger.ResourceLedgerTests.call
    snap=ledger.ResourceLedgerTests.snap
    def expense(self,category='rent',amount='100',**extra):
        return self.call('expense',{'business_date':'2026-10-01','period':'2026-10','category':category,'amount':amount,'partner':'厂房出租方','handler':'会计','note':'租赁凭据','request_key':str(uuid.uuid4()),**extra})
    def current(self,e):return next(r for r in self.snap()['expenses'] if r['id']==e['id'])
    def review(self,e,**extra):return self.call('expense_review',{'id':e['id'],'version':self.current(e)['version'],'decision':'approve','evidence_checked':True,'handler':'出纳','note':'凭据核对一致','request_key':str(uuid.uuid4()),**extra},'出纳')
    def pay(self,e,amount='100',**extra):return self.call('expense_payment',{'id':e['id'],'version':self.current(e)['version'],'business_date':'2026-10-22','amount':amount,'payee':'厂房出租方','method':'银行转账','handler':'出纳','reference':'银行回单','note':'按凭据支付','request_key':str(uuid.uuid4()),**extra},'出纳')
    def test_review_partial_full_payment_does_not_duplicate_cost(self):
        e=self.expense();self.assertEqual(self.current(e)['payment_state'],'pending')
        with self.assertRaisesRegex(ValueError,'尚未核对'):self.pay(e)
        self.review(e);self.assertEqual(self.current(e)['payment_state'],'approved')
        self.pay(e,'30');p=self.current(e);self.assertEqual((p['payment_state'],p['paid_cents'],p['outstanding_cents']),('partial',3000,7000))
        self.pay(e,'70');p=self.current(e);self.assertEqual((p['payment_state'],p['paid_cents'],p['outstanding_cents']),('paid',10000,0))
        self.assertEqual(sum(r['amount_cents'] for r in self.snap()['expenses']),10000)
        self.assertEqual(len(p['payments']),2)
        with self.assertRaisesRegex(ValueError,'未付余额'):self.pay(e,'0.01')
    def test_legacy_expense_is_pending_without_changing_amount(self):
        e=self.expense()
        with erp.connect() as c:raw=json.loads(c.execute('SELECT payload FROM indirect_expenses WHERE id=?',(e['id'],)).fetchone()[0])
        self.assertNotIn('payment_state',raw);self.assertEqual(self.current(e)['outstanding_cents'],10000)
        self.assertEqual(self.current(e)['payment_state'],'pending')
    def test_salary_and_depreciation_never_create_payables(self):
        for cat in ('wages-production','wages-management','depreciation'):
            e=self.expense(cat);self.assertFalse(self.current(e)['payment_required']);self.assertEqual(self.current(e)['outstanding_cents'],0)
            with self.assertRaisesRegex(ValueError,'工资系统'):self.review(e)
            with self.assertRaisesRegex(ValueError,'工资系统'):self.pay(e)
        with self.assertRaisesRegex(ValueError,'配送工资已停用'):self.expense('wages-delivery')
        self.assertEqual(self.snap()['expense_payables'],[])
    def test_reject_requires_reason_and_evidence_is_explicit(self):
        e=self.expense()
        with self.assertRaisesRegex(ValueError,'勾选'):self.review(e,evidence_checked=False)
        with self.assertRaises(ValueError):self.review(e,decision='return',note='')
        self.review(e,decision='return',note='请核对租金凭据');self.assertEqual(self.current(e)['payment_state'],'returned')
        with self.assertRaisesRegex(ValueError,'尚未核对'):self.pay(e)
        self.review(e);self.pay(e);self.assertEqual(self.current(e)['payment_state'],'paid')
    def test_approved_expense_does_not_allow_second_review(self):
        e=self.expense();self.review(e)
        with self.assertRaisesRegex(ValueError,'已核对'):self.review(e)
    def test_idempotent_payment_and_review_and_conflicting_reuse(self):
        e=self.expense();key=str(uuid.uuid4());a=self.review(e,request_key=key);version=a['expense_version'];b=self.review(e,version=version,request_key=key);self.assertEqual(a,b)
        with self.assertRaisesRegex(ValueError,'其他内容'):self.review(e,version=version,request_key=key,note='不同凭据')
        key=str(uuid.uuid4());a=self.pay(e,'40',request_key=key);b=self.pay(e,'40',version=a['expense_version'],request_key=key);self.assertEqual(a,b);self.assertEqual(len(self.snap()['expense_payments']),1)
        with self.assertRaisesRegex(ValueError,'其他内容'):self.pay(e,'41',version=a['expense_version'],request_key=key)
    def test_stale_version_and_overpayment_rollback(self):
        e=self.expense();v=self.current(e)['version'];self.review(e)
        with self.assertRaisesRegex(ValueError,'已被更新'):self.pay(e,version=v)
        with self.assertRaisesRegex(ValueError,'未付余额'):self.pay(e,'100.01')
        self.assertEqual(self.snap()['expense_payments'],[]);self.assertEqual(self.current(e)['outstanding_cents'],10000)
    def test_invalid_payments_leave_no_records(self):
        e=self.expense();self.review(e)
        for extra in ({'amount':'0'},{'amount':'-1'},{'amount':'1.001'},{'amount':True},{'method':'未知'},{'payee':''},{'business_date':'2026-09-30'},{'version':True}):
            with self.assertRaises(ValueError):self.pay(e,**extra)
        self.assertEqual(self.snap()['expense_payments'],[])
    def test_paid_expense_cannot_be_voided_or_returned(self):
        e=self.expense();self.review(e);self.pay(e,'20')
        with self.assertRaisesRegex(ValueError,'已有付款'):self.call('void',{'ledger':'expense','id':e['id'],'version':self.current(e)['version'],'reason':'错误'},'会计')
        with self.assertRaisesRegex(ValueError,'已有付款'):self.review(e,decision='return')
        self.assertFalse(self.current(e).get('voided',False))
    def test_void_unpaid_expense_preserves_review_history(self):
        e=self.expense();self.review(e);self.call('void',{'ledger':'expense','id':e['id'],'version':self.current(e)['version'],'reason':'错误重录'})
        p=self.current(e);self.assertEqual(p['payment_state'],'voided');self.assertEqual(len(p['review_history']),1)
        with self.assertRaisesRegex(ValueError,'作废'):self.pay(e)
    def test_closed_cost_month_allows_review_and_later_payment_only(self):
        e=self.expense(period='2026-09');self.call('period',{'month':'2026-09','version':0,'state':'closed','note':'结账'})
        self.review(e);self.pay(e,'50');self.assertEqual(self.current(e)['paid_cents'],5000)
        self.call('period',{'month':'2026-10','version':0,'state':'closed','note':'结账'})
        with self.assertRaisesRegex(ValueError,'结账'):self.pay(e,'50')
    def test_role_boundaries_and_cashier_visibility(self):
        e=self.expense()
        for role in ('会计','库管','厂长','老板'):
            with self.assertRaises(ValueError):self.call('expense_review',{},role)
            with self.assertRaises(ValueError):self.call('expense_payment',{},role)
        d=access.scope_resources(self.snap(),access.defaults('出纳'));self.assertEqual(d['expenses'],[]);self.assertEqual(d['expense_payables'][0]['amount_cents'],10000)
        self.assertTrue(all('value_cents' not in r for r in d['items']))
        d=access.scope_resources(self.snap(),access.defaults('库管'));self.assertEqual(d['expense_payables'],[]);self.assertEqual(d['expense_payments'],[])
    def test_permission_migration_runs_once_and_keeps_custom_denials(self):
        with erp.connect(True) as c:
            c.execute("DELETE FROM meta WHERE key='expense_payables_v040'");c.execute("DELETE FROM schema_migrations WHERE id='021-expense-payables'")
            for role in ('出纳','会计'):
                p=access.defaults(role);p['modules'].remove('finance.expense-payables');p['actions']=[a for a in p['actions'] if a not in ('costs.pay','costs.review')]
                c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',(role,2,json.dumps(p,ensure_ascii=False),'2026-10-01'))
            access.init_schema(c);p=access.permissions(c,'出纳');self.assertIn('costs.pay',p['actions']);self.assertEqual(p['version'],3)
            p['actions'].remove('costs.pay');c.execute('UPDATE role_permissions SET payload=? WHERE role=?',(json.dumps(p),'出纳'))
            access.init_schema(c);self.assertNotIn('costs.pay',access.permissions(c,'出纳')['actions'])

if __name__=='__main__':unittest.main()
