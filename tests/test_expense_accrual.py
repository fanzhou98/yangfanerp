"""One annual bill, twelve recognized costs, one payment balance."""
import unittest,tempfile,uuid,json
from pathlib import Path
from unittest.mock import patch
import test_workflow as fixture
import resources_costs as rc,reporting,cost_allocation as ca,product_profit

erp=fixture.erp
class ExpenseAccrualTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(erp,'DB',Path(self.tmp.name)/'accrual.db');self.db.start();erp.init_db();self.ctx=erp.connect(True);self.c=self.ctx.__enter__();self.c.execute('DELETE FROM indirect_expenses');self.op=rc.Operations(self.c,erp.now,erp.audit)
    def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);self.db.stop();self.tmp.cleanup()
    def expense(self,**changes):
        return self.op.expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','period':'2026-10','category':'rent','amount':'120000.01','spread_months':12,'handler':'会计','note':'全年租金','partner':'房东',**changes},'管理员')
    def test_accrual_is_cent_exact_and_crosses_year(self):
        e=self.expense();self.assertEqual(sum(p['amount_cents'] for p in e['accruals']),12000001);self.assertEqual(e['accruals'][-1]['period'],'2027-09')
        self.assertEqual(rc.period_expenses(self.c,'2026-10')[0]['amount_cents'],1000001);self.assertEqual(rc.period_expenses(self.c,'2027-01')[0]['amount_cents'],1000000);self.assertEqual(rc.period_expenses(self.c,'2027-10'),[])
        self.assertEqual(reporting.expense_summary(self.c,'2027-01')['total_cents'],1000000);self.assertEqual(reporting.management_month(self.c,'2027-01')['cost_cents'],1000000)
        self.assertEqual(product_profit.month(self.c,'2027-01')['allocation']['amount_cents'],1000000)
    def test_one_payment_source_and_no_second_cost(self):
        e=self.expense();self.op.expense_review({'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
        payment={'id':e['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','amount':'120000.01','method':'银行转账','payee':'房东','handler':'出纳','reference':'租金凭据','note':'全年付款'}
        self.op.expense_payment(payment,'管理员');p=rc.expense_projection(self.c)[0];self.assertEqual(p['outstanding_cents'],0);self.assertEqual(p['paid_cents'],12000001)
        self.assertEqual(len(rc.rows(self.c,'indirect_expenses')),1);self.assertEqual(reporting.expense_summary(self.c,'2027-01')['total_cents'],1000000)
    def test_closed_covered_month_blocks_create_edit_void_restore(self):
        e=self.expense();self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2027-02',1,rc.dump({'month':'2027-02','state':'closed'})))
        with self.assertRaisesRegex(ValueError,'结账'):self.expense()
        with self.assertRaisesRegex(ValueError,'结账'):self.op.expense_edit({**e,'version':1,'request_key':str(uuid.uuid4()),'amount':'2'},'管理员')
        with self.assertRaisesRegex(ValueError,'结账'):self.op.void({'id':e['id'],'version':1,'ledger':'expense','reason':'更正'},'管理员')
        raw={**e,'voided':True};self.c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(rc.dump(raw),e['id']))
        with self.assertRaisesRegex(ValueError,'结账'):self.op.restore({'id':e['id'],'version':1,'ledger':'expense','reason':'恢复'},'管理员')
    def test_invalid_duration_and_legacy_month(self):
        for months in (0,-1,61,1.5,True,'NaN'):
            with self.assertRaises(ValueError):self.expense(spread_months=months)
        e=self.expense(spread_months=1);self.assertEqual(rc.period_expenses(self.c,'2026-10')[0]['amount_cents'],e['amount_cents'])
        del e['accruals'];del e['spread_months'];self.c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(rc.dump(e),e['id']))
        self.assertEqual(rc.period_expenses(self.c,'2026-10')[0]['amount_cents'],12000001)
    def test_payment_mode_changes_only_future_bills_and_wages_can_change_nature(self):
        e=self.expense();rent=next(x for x in ca.categories(self.c) if x['id']=='rent');self.op.expense_category({**rent,'payment_mode':'noncash'},'管理员')
        self.assertTrue(rc.expense_projection(self.c)[0]['payment_required']);self.assertEqual(self.expense()['payment_mode'],'noncash')
        wage=next(x for x in ca.categories(self.c) if x['id']=='wages-delivery');self.assertFalse(wage['active']);self.assertTrue(wage['retired'])
        changed=self.op.expense_category({**wage,'nature':'变动'},'管理员');self.assertEqual(changed['nature'],'变动');self.assertFalse(changed['active'])
        with self.assertRaisesRegex(ValueError,'工资系统'):self.op.expense_category({**changed,'version':changed['version'],'payment_mode':'payable'},'管理员')
        with self.assertRaisesRegex(ValueError,'不能重新启用'):self.op.expense_category({**changed,'version':changed['version'],'active':True},'管理员')
