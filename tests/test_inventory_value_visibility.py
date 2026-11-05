import unittest
import erp_access

class InventoryValueVisibility(unittest.TestCase):
    def test_only_owner_accountant_cashier(self):
        for role in ('老板','会计','出纳','管理员'):
            self.assertTrue(erp_access.can_see_inventory_value({'role':role}), role)
        for role in ('库管','厂长','司机','采购'):
            self.assertFalse(erp_access.can_see_inventory_value({'role':role}), role)

    def test_redact_inventory_costs_keeps_quantities(self):
        value={'qty':'2.999','unit_cost':12.5,'closing_cents':100,'average_price':3,'products':[{'product_id':'P001','closing_qty':'1','closing_cents':10}]}
        got=erp_access.redact_inventory_costs(value)
        self.assertEqual(got['qty'],'2.999')
        self.assertNotIn('unit_cost',got)
        self.assertNotIn('closing_cents',got)
        self.assertNotIn('average_price',got)
        self.assertEqual(got['products'][0]['closing_qty'],'1')
        self.assertNotIn('closing_cents',got['products'][0])

if __name__=='__main__':unittest.main()
