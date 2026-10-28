"""Annual salary is evidence-based; fixed pay and actual payment are separate."""
import calendar,uuid,json,unittest
from decimal import Decimal
import test_payroll as fixture
import payroll

class AnnualPayrollTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    sheet=fixture.PayrollTests.sheet
    def annual(self,amount='36600',category='wages-management'):
        return self.save('wage-profile',{'employee_id':self.employee['id'],'salary_mode':'annual','annual_salary':amount,'salary_category':category,'version':1})
    def full_month(self,month='2020-09',overrides=None):
        overrides=overrides or {}
        self.c.execute('DELETE FROM factory_attendance')
        for day in payroll.month_days(month):
            self.save('attendance',{'business_date':day,'format':'group-day-v2','state':'confirmed','groups':[{'group_id':'G-TOFU','start_time':'21:00','end_time':'05:00'}],'entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':overrides.get(day,'full')}]})
    def test_yearly_standard_uses_actual_calendar_and_leave(self):
        self.annual();self.full_month(overrides={'2020-09-01':'leave','2020-09-02':'half','2020-09-03':'rest'})
        r=payroll.report(self.c,'2020-09');e=r['rows'][0]
        self.assertEqual(e['salary_category'],'wages-management');self.assertEqual(e['unpaid_days'],'1.5');self.assertEqual(e['rate_cents'],'10000');self.assertEqual(e['base_cents'],285000)
        sheet=self.sheet();self.assertEqual(sheet['rows'][0]['base_cents'],285000)
        self.assertIn('固定年薪',payroll.slip_html(payroll.report(self.c,'2020-09'),self.employee['id']))
    def test_annual_requires_every_day_including_no_business(self):
        self.annual();r=payroll.report(self.c,'2020-09');self.assertEqual(r['rows'][0]['unresolved'],28)
        with self.assertRaisesRegex(ValueError,'考勤'):self.sheet()
    def test_full_year_sum_exact_even_leap_and_rounding(self):
        for year in (2020,2021):
            total=0
            for month in range(1,13):
                m=f'{year}-{month:02d}';counts={'full':calendar.monthrange(year,month)[1],'half':0,'leave':0,'absent':0,'rest':0}
                calc=payroll.salary_calculation({'counts':counts,'pay_days':str(counts['full'])},{'salary_mode':'annual','annual_cents':10000001},m)
                total+=calc['base_cents']
            self.assertEqual(total,10000001)
    def test_annual_confirmation_is_frozen_and_year_payables_remain(self):
        p=self.annual();self.full_month();s=self.sheet();self.assertEqual(payroll.report(self.c,'2020-09')['year_balances'][0]['net_cents'],300800)
        self.save('wage-profile',{'employee_id':self.employee['id'],'salary_mode':'monthly','monthly_salary':'100','version':p['version']})
        self.assertFalse(payroll.report(self.c,'2020-09')['stale'])
        self.save('wage-pay',{'month':'2020-09','employee_id':self.employee['id'],'version':s['version'],'paid_cents':0,'amount':'1000','business_date':'2020-12-31','handler':'出纳','reference':'年末工资发放'})
        r=payroll.report(self.c,'2020-09');self.assertEqual(r['year_balances'][0]['outstanding_cents'],200800)
    def test_draft_recalculation_uses_latest_attendance(self):
        self.annual();self.full_month();s=self.sheet(state='draft');row=next(r for r in payroll.table_rows(self.c,'factory_attendance') if r['business_date']=='2020-09-01');row['entries'][0]['status']='leave';self.c.execute('UPDATE factory_attendance SET payload=? WHERE id=?',(json.dumps(row),row['id']))
        self.assertTrue(payroll.report(self.c,'2020-09')['stale']);updated=self.sheet(version=s['version']);self.assertEqual(updated['rows'][0]['base_cents'],290000)
