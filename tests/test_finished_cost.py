"""Finished-goods carry: weighted average, quantity identity and cost reconciliation."""
import json,unittest
import test_production_daily as fixture
import finished_cost as fc
import resources_costs as rc

erp=fixture.erp


class CarryTests(unittest.TestCase):
    def test_weighted_average_rounds_to_cents(self):
        row=fc.carry('0',0,'100',123456,'80',0)
        self.assertEqual(row['unit_cost'],1234)
        self.assertEqual(row['issued_cents'],98720)
        self.assertEqual(row['ending_cents'],123456-98720)

    def test_opening_cents_none_keeps_values_empty(self):
        row=fc.carry('5',None,'10',20000,'3',0)
        self.assertIsNone(row['unit_cost'])
        self.assertIsNone(row['issued_cents'])
        self.assertIsNone(row['ending_cents'])
        self.assertEqual(row['ending_qty'],'12')

    def test_identity_holds_with_loss(self):
        row=fc.carry('10',10000,'20',30000,'25','5')
        self.assertEqual(row['ending_qty'],'0')
        self.assertEqual(int(row['issued_cents'])+int(row['loss_cents'])+int(row['ending_cents']),40000)

    def test_zero_total_quantity_does_not_divide(self):
        row=fc.carry('0',0,'0',0,'0',0)
        self.assertIsNone(row['unit_cost'])
        self.assertEqual(row['ending_qty'],'0')


class MonthTests(unittest.TestCase):
    material=fixture.DailyFactoryTests.material
    record=fixture.DailyFactoryTests.record
    call=fixture.DailyFactoryTests.call
    tearDown=fixture.DailyFactoryTests.tearDown
    def setUp(self):
        fixture.DailyFactoryTests.setUp(self)
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO warehouse_plans VALUES(?,?)",('2026-10-20',json.dumps({'business_date':'2026-10-20','stock':[
                {'product_id':'P001','existing_qty':'2','produced_qty':'10','loss_qty':'0'},
                {'product_id':'P002','existing_qty':'0','produced_qty':'12','loss_qty':'0'}]})))
        self.material('receipt','100','400')
        self.material('consume','100')
        self.record()
    def report(self):
        with erp.connect() as c:return fc.month(c,'2026-10')
    def test_quantities_and_identity(self):
        r=self.report()
        self.assertTrue(r['rows'])
        for row in r['rows']:
            self.assertAlmostEqual(float(row['ending_qty']),float(row['opening_qty'])+float(row['produced_qty'])-float(row['issued_qty'])-float(row['loss_qty']),places=4)
        self.assertEqual(float(r['totals']['produced_qty']),22)
        self.assertGreaterEqual(float(r['totals']['issued_qty']),0)
    def test_production_cost_reconciles_with_allocation(self):
        r=self.report()
        self.assertEqual(r['production_cents'],sum(row['produced_cents'] for row in r['rows'] if row['produced_cents'] is not None))
        self.assertGreater(r['allocation_total_cents'],0)
        self.assertGreater(r['production_cents'],0)
        self.assertGreaterEqual(r['allocation_total_cents'],r['production_cents'])
    def test_issued_cost_and_ending_value_add_up(self):
        r=self.report()
        for row in r['rows']:
            if row['unit_cost'] is None: continue
            self.assertEqual(row['ending_cents'],int(round(float(row['ending_qty'])*row['unit_cost'])))
            self.assertEqual(row['issued_cents'],int(round(float(row['issued_qty'])*row['unit_cost'])))
    def test_gaps_are_listed(self):
        r=self.report()
        self.assertIsInstance(r['gaps'],list)
        self.assertTrue(all(isinstance(gap,str) and gap for gap in r['gaps']))
