import unittest,uuid,json
import expense_coverage as coverage,resources_costs as rc,reporting,expense_query
import test_expense_accrual as fixture
class ExpenseCoverageTests(unittest.TestCase):
    setUp=fixture.ExpenseAccrualTests.setUp
    tearDown=fixture.ExpenseAccrualTests.tearDown
    expense=fixture.ExpenseAccrualTests.expense
    def bill(self,**changes):return self.expense(category='water',service_account='水表A',amount='320.00',accrual_method='service_days',service_start='2026-08-25',service_end='2026-09-26',business_date='2026-10-05',**changes)
    def test_irregular_meter_interval_exact_months_and_no_duplicate_boundary(self):
        e=self.bill();self.assertEqual(e['period'],'2026-08');self.assertEqual(e['coverage_days'],32);self.assertEqual(e['accruals'],[{'period':'2026-08','amount_cents':6000},{'period':'2026-09','amount_cents':26000}]);self.assertEqual(e['coverage_breakdown'][0]['start'],'2026-08-26')
        other=coverage.plan({'accrual_method':'service_days','service_start':'2026-09-26','service_end':'2026-10-24'},28000);self.assertEqual(other['coverage_days'],28);self.assertEqual(other['coverage_breakdown'][0]['start'],'2026-09-27');self.assertEqual(other['accruals'],[{'period':'2026-09','amount_cents':4000},{'period':'2026-10','amount_cents':24000}])
        self.assertEqual(reporting.expense_summary(self.c,'2026-08')['total_cents'],6000);self.assertEqual(reporting.expense_summary(self.c,'2026-09')['total_cents'],26000);self.assertEqual(reporting.expense_summary(self.c,'2026-10')['total_cents'],0)
        self.assertEqual(self.c.execute("SELECT amount_cents FROM expense_accrual_lookup WHERE expense_id=? AND period='2026-08'",(e['id'],)).fetchone()[0],6000)
    def test_leap_year_rounding_and_legacy_months_unchanged(self):
        r=coverage.plan({'accrual_method':'service_days','service_start':'2024-02-28','service_end':'2024-03-01'},1);self.assertEqual(r['coverage_days'],2);self.assertEqual([p['amount_cents'] for p in r['accruals']],[1,0]);self.assertEqual(sum(p['amount_cents'] for p in r['accruals']),1)
        for amount in (1,2,31,10001):
            r=coverage.plan({'accrual_method':'service_days','service_start':'2025-12-25','service_end':'2026-02-03'},amount);self.assertEqual(sum(p['amount_cents'] for p in r['accruals']),amount)
        old=coverage.plan({'period':'2026-08','spread_months':3},100);self.assertEqual(old['accruals'],[{'period':'2026-08','amount_cents':34},{'period':'2026-09','amount_cents':33},{'period':'2026-10','amount_cents':33}])
    def test_single_payable_and_payment_does_not_duplicate_cost(self):
        e=self.bill();self.op.expense_review({'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
        self.op.expense_payment({'id':e['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-06','amount':'320','method':'银行转账','payee':'水务公司','handler':'出纳','reference':'合成水费凭据','note':'整笔付水费'},'管理员');self.assertEqual(rc.expense_projection(self.c)[0]['outstanding_cents'],0);self.assertEqual(reporting.expense_summary(self.c,'2026-09')['total_cents'],26000)
    def test_preview_is_readonly_closed_months_block_writes(self):
        b={'amount':'320','accrual_method':'service_days','service_start':'2026-08-25','service_end':'2026-09-26'}
        self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-08',1,rc.dump({'month':'2026-08','state':'closed'})));before=self.c.total_changes;r=coverage.preview(self.c,b);self.assertEqual(r['closed_months'],['2026-08']);self.assertEqual(self.c.total_changes,before)
        with self.assertRaisesRegex(ValueError,'结账'):self.bill()
        self.assertEqual(rc.rows(self.c,'indirect_expenses'),[])
    def test_edit_requires_interval_and_invalid_dates_rejected(self):
        e=self.bill()
        with self.assertRaisesRegex(ValueError,'抄表区间'):self.op.expense_edit({'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'business_date':'2026-10-05','period':'2026-08','category':'water','amount':'320','handler':'会计','note':'更正但缺区间'},'管理员')
        for changes in ({'service_end':'2026-08-25'},{'service_end':'2026-08-24'},{'service_start':'2026-02-30'},{'service_start':'20260101'},{'service_start':'2020-01-01'},{'accrual_method':'bad'}):
            b={'accrual_method':'service_days','service_start':'2026-08-25','service_end':'2026-09-26',**changes}
            with self.subTest(changes=changes),self.assertRaises(ValueError):coverage.plan(b,32000)
