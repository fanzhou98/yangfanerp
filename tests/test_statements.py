import unittest,json,copy
import test_inventory as fixture
import statements
erp=fixture.erp
class StatementTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    order=fixture.InventoryTests.order
    settle=fixture.InventoryTests.settle
    review=fixture.InventoryTests.review
    def snapshot(self,cid='C001',day='2026-10-19'):
        with erp.connect() as c:
            c.execute('BEGIN');return statements.snapshot(c,cid,day,'2026-10-19T18:00:00+08:00')
    def test_history_partial_receipt_and_return_credit_are_not_double_deducted(self):
        o=self.review(self.settle(self.order()))
        with erp.connect(True) as c:
            o.update(paid_cents=1000,return_credit_cents=2000);c.execute('UPDATE orders SET payload=? WHERE id=?',(erp.dumps(o),o['id']))
        s=self.snapshot();self.assertEqual(len(s['history']),1);self.assertEqual(s['totals']['payable_cents'],o['total_cents']-3000)
        self.assertEqual(s['history'][0]['paid_cents'],1000);self.assertEqual(s['history'][0]['credit_cents'],2000)
    def test_pending_bills_do_not_form_payable_and_future_bills_excluded(self):
        pending=self.settle(self.order());s=self.snapshot(day='2026-10-18')
        self.assertEqual(s['totals']['pending_cents'],pending['total_cents']);self.assertEqual(s['totals']['payable_cents'],0)
        self.assertEqual(len(self.snapshot(day='2026-10-19')['historical_pending']),1)
        self.assertEqual(len(self.snapshot(day='2026-10-17')['current']),0);self.assertEqual(len(self.snapshot(day='2026-10-17')['history']),0)
    def test_other_customer_and_paid_history_are_not_exposed(self):
        o=self.review(self.settle(self.order()))
        with erp.connect(True) as c:o['paid_cents']=o['total_cents'];c.execute('UPDATE orders SET payload=? WHERE id=?',(erp.dumps(o),o['id']))
        self.assertEqual(self.snapshot()['history'],[]);self.assertEqual(self.snapshot('C002')['history'],[])
    def test_bad_customer_rejected_and_read_is_not_a_receipt_or_review(self):
        self.settle(self.order())
        before=erp.bootstrap()
        with self.assertRaises(ValueError):self.snapshot('missing')
        self.snapshot();after=erp.bootstrap();self.assertEqual(before,after)
