"""Use real posted material ledgers, not cost fields invented on raw entries."""
import json,unittest,uuid
import test_production_daily as fixture
import product_profit
import resources_costs as rc

erp=fixture.erp
class ProductProfitTests(unittest.TestCase):
    material=fixture.DailyFactoryTests.material
    record=fixture.DailyFactoryTests.record
    call=fixture.DailyFactoryTests.call
    tearDown=fixture.DailyFactoryTests.tearDown
    def setUp(self):
        fixture.DailyFactoryTests.setUp(self)
        with erp.connect(True) as c:
            for table in ('orders','sales_returns','indirect_expenses','byproduct_sales','trade_records'):c.execute('DELETE FROM '+table)
        self.material('receipt','100','400');self.material('consume','100')
        self.record(products=[{'product_id':'P001','system':'tofu','large_tanks':'1','small_tanks':'0'},{'product_id':'P002','system':'tofu','large_tanks':'2','small_tanks':'0'}])
    def order(self,oid,pid,kg='10',**extra):
        line={'product_id':pid,'product_name':'测试产品','unit':'筐','billing_unit':'公斤','bill_qty':kg,'actual_qty':'1','amount_cents':30000,**extra}
        with erp.connect(True) as c:c.execute('INSERT INTO orders VALUES(?,?)',(oid,json.dumps({'id':oid,'customer_id':'C001','business_date':'2026-10-20','state':'reviewed','total_cents':30000,'lines':[line]})))
    def report(self):
        with erp.connect() as c:return product_profit.month(c,'2026-10')
    def expense(self,amount,category='electricity'):
        with erp.connect(True) as c:rc.Operations(c,erp.now,erp.audit).expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','category':category,'amount':amount,'handler':'会计','note':'凭据'},'管理员')
    def test_actual_tank_basis_beats_sales_weight_and_preserves_cents(self):
        self.order('A','P001','100');self.order('B','P002','100');r=self.report();rows={x['product_id']:x for x in r['rows']}
        self.assertEqual(rows['P001']['soy_cost_cents'],13333);self.assertEqual(rows['P002']['soy_cost_cents'],26667)
        self.assertEqual(sum(x['soy_cost_cents'] for x in r['rows']),40000)
        self.assertEqual(r['total']['net_cents'],20000)
    def test_bean_loss_is_visible_shared_cost_not_silently_dropped(self):
        self.order('A','P001');self.order('B','P002');self.material('receipt','10','40');self.material('loss','1')
        r=self.report();self.assertEqual(r['costs']['soy_loss_cents'],400);self.assertEqual(r['total']['net_cents'],19600)

    def test_missing_weight_stays_unknown_and_suppresses_weight_allocation(self):
        self.order('A','P001',kg='',billing_unit='袋');self.expense('100','wages-production');r=self.report();row=next(x for x in r['rows'] if x['product_id']=='P001')
        self.assertIsNone(row['qty_kg']);self.assertIsNone(row['net_cents']);self.assertIsNone(row['break_even_price']);self.assertTrue(r['gaps'])
    def test_byproduct_credit_can_exceed_shared_cost_without_clamping(self):
        self.order('A','P001');self.order('B','P002');self.expense('50')
        with erp.connect(True) as c:c.execute('INSERT INTO byproduct_sales VALUES(?,?,?)',('B','B',json.dumps({'id':'B','business_date':'2026-10-20','amount_cents':10000})))
        r=self.report();self.assertEqual(r['costs']['bean_pool_cents'],-5000);self.assertEqual(sum(x['indirect_cents'] for x in r['rows']),-5000);self.assertEqual(r['total']['net_cents'],25000)

    def test_management_statement_reconciles_with_total_and_rows(self):
        self.order('A','P001','100');self.order('B','P002','100');self.expense('100')
        r=self.report();st=r['statement'];t=r['total']
        self.assertEqual(st['revenue_cents'],t['revenue_cents'])
        self.assertEqual(st['direct_cents'],t['direct_cents'])
        self.assertEqual(st['material_margin_cents'],st['revenue_cents']-st['direct_cents'])
        self.assertEqual(st['period_cents'],t['indirect_cents'])
        self.assertEqual(st['profit_cents'],t['net_cents'])
        self.assertEqual(st['gross_cents'],st['revenue_cents']-st['direct_cents']-st['period_cents'])
        self.assertEqual(st['gross_cents'],st['profit_cents'])
        self.assertEqual(st['gross_margin'],rc.ds(__import__('decimal').Decimal(st['gross_cents'])/__import__('decimal').Decimal(st['revenue_cents'])))
        self.assertEqual(st['pending_expense_cents'],0)
        self.assertEqual(st['allocated_cost_cents'],st['direct_cents']+st['period_cents'])
        self.assertEqual(st['management_cost_cents'],st['allocated_cost_cents']+st['caliber_difference_cents'])
        self.assertEqual(st['management_cost_cents'],st['management_material_cents']+st['management_expense_cents']+st['management_transport_cents']+st['management_purchased_cents'])
        self.assertEqual(st['caliber_difference_cents'],0)
        self.assertIn('毛利＝营业收入−已分摊直接成本−已分摊期间费用',st['basis'])
        self.assertIn('经营看板口径',st['cost_caliber'])
    def test_caliber_difference_lists_unallocated_cost(self):
        self.order('A','P001',kg='',billing_unit='袋');self.expense('100')
        st=self.report()['statement']
        self.assertIsNone(st['gross_cents']);self.assertIsNone(st['profit_margin'])
        self.assertGreater(st['caliber_difference_cents'],0)
        self.assertEqual(st['management_cost_cents'],st['allocated_cost_cents']+st['caliber_difference_cents'])
        self.assertEqual(st['management_cost_cents'],st['management_material_cents']+st['management_expense_cents']+st['management_transport_cents']+st['management_purchased_cents'])
        self.assertIn('未分摊',st['cost_caliber'])
    def test_statement_leaves_profit_blank_when_data_incomplete(self):
        self.order('A','P001',kg='',billing_unit='袋')
        st=self.report()['statement']
        self.assertIsNone(st['profit_cents']);self.assertIsNone(st['profit_margin'])
        self.assertIn('留空',st['basis'])

if __name__=='__main__':unittest.main()
