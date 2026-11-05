import unittest
from unittest.mock import patch
import daily_costs
import payroll

class ManagementDailyPeopleTests(unittest.TestCase):
    def test_management_without_attendance_is_included_in_daily_labor(self):
        employee={'id':'E-M','name':'管理甲','employee_type':'management','active':True}
        profile={'kind':'profile','employee_id':'E-M','salary_mode':'monthly','monthly_cents':600000}
        with patch.object(daily_costs.owner_analysis,'people',return_value={'rows':[],'attendance_state':'missing'}), \
             patch.object(payroll,'records',return_value=[profile]), \
             patch.object(payroll,'table_rows',return_value=[employee]):
            present,draft,state,detail,days=daily_costs._people(None,'2026-11-05',15000)
        self.assertEqual(present,1)
        self.assertEqual(detail[0]['employee_name'],'管理甲')
        self.assertTrue(detail[0]['management'])
        self.assertEqual(detail[0]['amount_cents'],20000)
        self.assertEqual(str(days),'1')

    def test_sales_value_uses_stored_amount_or_price(self):
        self.assertEqual(daily_costs._sales_value({'amount_cents':1200},'筐'),1200)
        self.assertEqual(daily_costs._sales_value({'amount_cents':0,'price':'3.5','actual_qty':'2','bill_qty':'10'},'包'),3500)
        self.assertEqual(daily_costs._sales_value({'amount_cents':0,'price':'3.5','actual_qty':'2','bill_qty':'0','billing_unit':'公斤','standard_unit_kg':'20'},'筐'),14000)

if __name__=='__main__':
    unittest.main()
