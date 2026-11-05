import unittest
import payroll

class ManagementFixedSalaryTests(unittest.TestCase):
    def profile(self):
        return {'salary_mode':'monthly','monthly_cents':600000}

    def counts(self, **kw):
        values={k:0 for k in ('full','half','leave','absent','rest')}
        values.update(kw)
        return values

    def test_management_full_month_is_paid_without_attendance(self):
        row=payroll.salary_calculation({'employee_type':'management','counts':self.counts(),'pay_days':'0'},self.profile(),'2026-11')
        self.assertEqual(row['pay_days'],'30')
        self.assertEqual(row['base_cents'],600000)
        self.assertIn('管理岗按月固定工资',row['calculation_note'])

    def test_management_leave_and_half_day_are_deducted_from_fixed_salary(self):
        leave=payroll.salary_calculation({'employee_type':'management','counts':self.counts(leave=1),'pay_days':'0'},self.profile(),'2026-11')
        half=payroll.salary_calculation({'employee_type':'management','counts':self.counts(half=1),'pay_days':'0'},self.profile(),'2026-11')
        self.assertEqual(leave['base_cents'],580000)
        self.assertEqual(half['base_cents'],590000)
        self.assertEqual(leave['unpaid_days'],'1')
        self.assertEqual(half['unpaid_days'],'0.5')

if __name__=='__main__':
    unittest.main()
