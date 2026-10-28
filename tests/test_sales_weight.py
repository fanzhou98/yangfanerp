import unittest
from decimal import Decimal
from production_management import sales_line_kg
class SalesWeightTests(unittest.TestCase):
 def test_settlement_weight_precedes_driver(self):
  l={'unit':'筐','actual_qty':'2','bill_qty':'45','driver':[{'count':'2','gross':'52','tare':'1'}]}
  self.assertEqual(sales_line_kg(l,'reviewed'),(Decimal(45),False));self.assertEqual(sales_line_kg(l,'draft'),(Decimal(50),False))
 def test_standard_is_explicit_estimate_and_unknown_is_not_zero(self):
  self.assertEqual(sales_line_kg({'unit':'包','actual_qty':'3','standard_kg':'5'},'draft'),(Decimal(15),True))
  self.assertEqual(sales_line_kg({'unit':'包','actual_qty':'3'},'draft'),(None,False))
  self.assertEqual(sales_line_kg({'unit':'包','actual_qty':'0'},'draft'),(Decimal(0),False))
 def test_package_actual_and_direct_kg(self):
  self.assertEqual(sales_line_kg({'unit':'包','actual_qty':'3','standard_kg':'5','package_net_kg':'14'},'draft'),(Decimal(14),False))
  self.assertEqual(sales_line_kg({'unit':'公斤','actual_qty':'12'},'draft'),(Decimal(12),False))
