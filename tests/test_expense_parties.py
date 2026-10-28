import unittest,uuid
import test_expense_accrual as fixture
import expense_parties as ep,resources_costs as rc,erp_access as access,cost_allocation as ca,reporting

erp=fixture.erp
class ExpensePartiesTests(unittest.TestCase):
    setUp=fixture.ExpenseAccrualTests.setUp
    tearDown=fixture.ExpenseAccrualTests.tearDown
    def party(self,name='独立房东',kind='rent',**changes):return ep.save(self.c,{'request_key':str(uuid.uuid4()),'version':0,'kind':kind,'name':name,'active':True,**changes},'管理员',erp.now,erp.audit)
    def expense(self,**changes):return self.op.expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','category':'rent','amount':'100','handler':'会计','note':'凭据','counterparty_mode':'expense-ledger-v1',**changes},'管理员')
    def review(self,e):return self.op.expense_review({'id':e['id'],'version':e['version'],'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
    def test_modern_payable_requires_correct_party_but_payroll_and_noncash_do_not(self):
        with self.assertRaisesRegex(ValueError,'费用收款方'):self.expense()
        wrong=self.party(kind='energy')
        with self.assertRaisesRegex(ValueError,'分类'):self.expense(counterparty_id=wrong['id'])
        for category in ('wages-management','depreciation'):
            e=self.expense(category=category);self.assertEqual(e['partner'],'');self.assertFalse(rc.expense_payment_required(e));self.assertFalse(e.get('supplier_id'))
        with self.assertRaisesRegex(ValueError,'配送工资已停用'):self.expense(category='wages-delivery')
    def test_dedicated_identity_full_payout_and_frozen_name(self):
        before=self.c.execute('SELECT COUNT(*) FROM suppliers').fetchone()[0];party=self.party();e=self.expense(counterparty_id=party['id']);self.assertEqual(e['partner'],'独立房东');self.assertNotIn('supplier_id',e)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM suppliers').fetchone()[0],before)
        ep.save(self.c,{**party,'name':'新名称','version':1,'request_key':str(uuid.uuid4())},'管理员',erp.now,erp.audit);self.assertEqual(rc.expense_projection(self.c)[0]['partner'],'独立房东')
        self.review(e);pay={'id':e['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-21','amount':'100','payee':'另一收款方','method':'银行转账','handler':'出纳','note':'凭据'}
        with self.assertRaisesRegex(ValueError,'不一致'):self.op.expense_payment(pay,'管理员')
        self.op.expense_payment({**pay,'payee':'独立房东'},'管理员');self.assertEqual(rc.expense_projection(self.c)[0]['outstanding_cents'],0)
        summary=reporting.expense_summary(self.c,'2026-10');self.assertEqual(summary['total_cents'],10000);self.assertEqual(summary['suppliers'][0]['counterparty_id'],party['id'])
    def test_legacy_missing_payee_stays_pending_until_corrected(self):
        e=self.expense(counterparty_mode='legacy');p=rc.expense_projection(self.c)[0];self.assertTrue(p['counterparty_pending'])
        with self.assertRaisesRegex(ValueError,'补齐'):self.review(e)
        party=self.party();updated=self.op.expense_edit({**e,'request_key':str(uuid.uuid4()),'version':1,'counterparty_mode':'expense-ledger-v1','counterparty_id':party['id'],'amount':'100'},'管理员');self.review(updated)
        self.assertEqual(rc.expense_projection(self.c)[0]['payment_state'],'approved')
    def test_legacy_supplier_association_survives_explicit_edit(self):
        e=self.expense(counterparty_mode='legacy',partner='历史收款人')
        edited=self.op.expense_edit({**e,'request_key':str(uuid.uuid4()),'version':1,'counterparty_mode':'expense-ledger-v1','counterparty_id':'legacy:'+e['id'],'amount':'100'},'管理员')
        self.assertEqual(edited['partner'],'历史收款人');self.review(edited)
    def test_other_roles_do_not_receive_finance_party_catalog(self):
        p=self.party();scoped=access.scope_resources(rc.snapshot(self.c),access.defaults('库管'));self.assertEqual(scoped['expense_counterparties'],[])
        with self.assertRaises(ValueError):ep.save(self.c,{'request_key':str(uuid.uuid4()),'name':'伪造','kind':'rent'},'库管',erp.now,erp.audit)
        self.assertTrue(access.scope_resources(rc.snapshot(self.c),access.defaults('会计'))['expense_counterparties'])
    def test_duplicate_and_idempotent_save(self):
        b={'request_key':str(uuid.uuid4()),'name':'同名测试','kind':'rent','version':0,'active':True};p=ep.save(self.c,b,'管理员',erp.now,erp.audit);self.assertEqual(ep.save(self.c,b,'管理员',erp.now,erp.audit),p)
        with self.assertRaisesRegex(ValueError,'提交编号'):ep.save(self.c,{**b,'name':'其他'},'管理员',erp.now,erp.audit)
        with self.assertRaisesRegex(ValueError,'同名'):self.party('同名测试')
        self.party('同名测试','energy');self.assertEqual(len(ep.catalog(self.c)),2)
    def test_original_bill_keeps_payment_channel_after_category_changes(self):
        party=self.party();e=self.expense(counterparty_id=party['id']);cat=next(c for c in ca.categories(self.c) if c['id']=='rent');self.op.expense_category({**cat,'payment_mode':'noncash'},'管理员')
        edited=self.op.expense_edit({**e,'request_key':str(uuid.uuid4()),'amount':'100','version':1},'管理员');self.assertEqual(edited['payment_mode'],'payable');self.assertEqual(edited['counterparty_id'],party['id']);self.review(edited)

    def test_legacy_partial_payment_resolves_payee_from_existing_cash_record(self):
        e=self.expense(counterparty_mode='legacy',partner='房东');self.review(e)
        paid=self.op.expense_payment({'id':e['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-21','amount':'30','payee':'房东','method':'现金','handler':'出纳','note':'旧系统部分付款'},'管理员')
        raw=rc.rows(self.c,'indirect_expenses')[0];raw['partner']='';self.c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(rc.dump(raw),e['id']))
        projection=rc.expense_projection(self.c)[0];self.assertEqual(projection['partner'],'房东');self.assertTrue(projection['counterparty_from_payment'])
        self.op.expense_payment({'id':e['id'],'version':3,'request_key':str(uuid.uuid4()),'business_date':'2026-10-22','amount':'70','payee':'房东','method':'现金','handler':'出纳','note':'原收款方结清余款'},'管理员')
        self.assertEqual(rc.expense_projection(self.c)[0]['outstanding_cents'],0);self.assertEqual(rc.rows(self.c,'indirect_expenses')[0]['partner'],'')
