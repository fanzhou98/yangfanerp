import unittest,uuid,json
import test_payroll as fixture
import payroll,resources_costs as rc,reporting,funds

erp=fixture.erp
class PayrollAccrualTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    sheet=fixture.PayrollTests.sheet
    def costs(self):return [e for e in rc.period_expenses(self.c,'2020-09') if e.get('payroll_sheet_id')]
    def manual(self,month='2020-09'):
        return rc.Operations(self.c,erp.now,erp.audit).expense({'business_date':month+'-30','period':month,'category':'wages-production','amount':'100','handler':'会计','note':'手工工资','request_key':str(uuid.uuid4())},'管理员')
    def test_unpaid_salary_is_cost_and_payment_only_clears_payable(self):
        draft=self.sheet('draft');self.assertEqual(self.costs(),[])
        sheet=self.sheet(version=draft['version']);self.assertEqual(sum(e['amount_cents'] for e in self.costs()),15595)
        self.assertEqual(reporting.expense_summary(self.c,'2020-09')['total_cents'],15595)
        self.assertEqual(payroll.report(self.c,'2020-09')['outstanding_cents'],15595)
        self.assertFalse([m for m in funds.movements(self.c) if m['direction']=='out'])
        b={'month':'2020-09','employee_id':self.employee['id'],'version':sheet['version'],'paid_cents':0,'amount':'50','business_date':'2020-12-31','handler':'出纳','reference':'年底分次发放','request_key':str(uuid.uuid4())}
        paid=self.save('wage-pay',b);self.assertEqual(self.save('wage-pay',b),paid)
        self.assertEqual(sum(e['amount_cents'] for e in self.costs()),15595)
        cost=next(e for e in rc.expense_projection(self.c) if e.get('payroll_sheet_id'));self.assertEqual((cost['paid_cents'],cost['outstanding_cents']),(5000,10595));self.assertFalse(cost['payment_required'])
        movements=[m for m in funds.movements(self.c) if m['direction']=='out'];self.assertEqual(len(movements),1);self.assertEqual(movements[0]['amount_cents'],5000)
        self.assertEqual(reporting.expense_summary(self.c,'2020-12')['total_cents'],0)
    def test_reopen_reconfirm_and_manual_tamper_protection(self):
        sheet=self.sheet();cost=self.costs()[0];ops=rc.Operations(self.c,erp.now,erp.audit)
        for action in [lambda:ops.void({'ledger':'expense','id':cost['id'],'version':cost['version'],'reason':'不可绕过工资'},'管理员'),lambda:ops.expense_edit({'id':cost['id'],'version':cost['version']},'管理员'),lambda:self.manual()]:
            with self.assertRaisesRegex(ValueError,'工资'):action()
        self.save('wage-reopen',{'month':'2020-09','version':sheet['version']});self.assertEqual(self.costs(),[])
        sheet=self.sheet(version=2);self.assertEqual(len(self.costs()),1);self.assertEqual(self.costs()[0]['id'],cost['id'])
    def test_existing_manual_wages_prevent_duplicate_cost(self):
        manual=self.manual()
        with self.assertRaisesRegex(ValueError,'手工工资'):self.sheet()
        self.assertFalse(any(r['kind']=='sheet' for r in payroll.records(self.c)))
        rc.Operations(self.c,erp.now,erp.audit).void({'ledger':'expense','id':manual['id'],'version':manual['version'],'reason':'改为工资表自动归集'},'管理员')
        self.sheet();self.assertEqual(len(self.costs()),1)
    def test_closed_month_blocks_confirmation_and_reopen_but_not_payment(self):
        self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2020-09',1,rc.dump({'state':'closed'})))
        with self.assertRaisesRegex(ValueError,'结账'):self.sheet()
        self.c.execute('DELETE FROM resource_periods');sheet=self.sheet()
        self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2020-09',1,rc.dump({'state':'closed'})))
        with self.assertRaisesRegex(ValueError,'结账'):self.save('wage-reopen',{'month':'2020-09','version':sheet['version']})
        self.save('wage-pay',{'month':'2020-09','employee_id':self.employee['id'],'version':sheet['version'],'paid_cents':0,'amount':'155.95','business_date':'2020-12-31','handler':'出纳','reference':'年底结清'})
        self.assertEqual(payroll.report(self.c,'2020-09')['outstanding_cents'],0);self.assertEqual(len(self.costs()),1)
    def test_legacy_confirmed_sheet_explicit_cost_post(self):
        sheet=self.sheet();self.c.execute('DELETE FROM indirect_expenses');sheet.pop('cost_accrual_mode');self.c.execute('UPDATE payroll_records SET payload=? WHERE id=?',(rc.dump(sheet),sheet['id']))
        posted=self.save('wage-cost-post',{'month':'2020-09','version':sheet['version']});self.assertEqual(posted['cost_accrual_mode'],'auto');self.assertEqual(len(self.costs()),1)
        self.save('wage-cost-post',{'month':'2020-09','version':posted['version']});self.assertEqual(len(self.costs()),1)
