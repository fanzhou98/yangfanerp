"""Receipt reductions stay separate from cash and reconcile every balance."""
from test_workflow import WorkflowTests, erp
import statements
from ops.business_check import check_database

class ReceiptAdjustmentTests(WorkflowTests):
    def pay_adjusted(self,o,amount='600',discount='60',rounding='9.93',**extra):
        return erp.mutate('receipt',{'version':o['version'],'amount':amount,'discount':discount,'rounding':rounding,'received_date':'2026-10-18','method':'现金','note':'双方确认优惠及尾差',**extra},'出纳',o['id'])

    def test_reduction_reconciles_cash_statement_and_checker(self):
        o=self.review(self.settle(self.order()))
        o=self.pay_adjusted(o)
        self.assertEqual((o['paid_cents'],o['discount_cents'],o['rounding_cents']),(60000,6000,993))
        self.assertEqual(erp.inventory.balance(o),0)
        self.assertEqual(o['status'],'已结清')
        with erp.connect() as c:
            s=statements.snapshot(c,'C001','2026-10-18',erp.now())
        self.assertEqual(s['totals']['payable_cents'],0)
        self.assertEqual(s['totals']['current_paid_cents'],60000)
        self.assertEqual(s['totals']['current_discount_cents'],6000)
        self.assertTrue(check_database(erp.DB)['ok'])

    def test_zero_cash_partial_waiver_locks_bill_and_later_cash_finishes(self):
        o=self.review(self.settle(self.order()))
        o=self.pay_adjusted(o,'0','10','0')
        self.assertEqual(erp.inventory.balance(o),65993)
        for act,body in [('order',o),('settle',{'version':o['version'],'mode':'customer'}),('negotiate',{'version':o['version'],'reason':'改价'})]:
            with self.assertRaises(ValueError):erp.mutate(act,body,'会计',o['id'])
        o=self.pay_adjusted(o,'659.93','0','0')
        self.assertEqual(erp.inventory.balance(o),0)
        self.assertTrue(check_database(erp.DB)['ok'])

    def test_future_receipt_date_is_rejected(self):
        o=self.review(self.settle(self.order()))
        with self.assertRaisesRegex(ValueError,'到账日期不能晚于今天'):
            erp.mutate('receipt',{'version':o['version'],'amount':'1','discount':'0','rounding':'0','received_date':'2999-01-01','method':'现金'},'出纳',o['id'])

    def test_invalid_reductions_rollback(self):
        o=self.review(self.settle(self.order()))
        initial=len(erp.bootstrap()['receipts'])
        for values in [('660','10','0'),('0','0','0'),('0','-1','0'),('0','1.001','0'),('0','NaN','0'),('0','Infinity','0')]:
            with self.assertRaises(ValueError):self.pay_adjusted(o,*values)
        with self.assertRaises(ValueError):self.pay_adjusted(o,note='')
        with self.assertRaises(ValueError):erp.mutate('receipt',{'version':o['version'],'amount':'1','discount':'1','rounding':'0','received_date':'2026-10-18','method':'现金','note':'原因'},'库管',o['id'])
        self.assertEqual(len(erp.bootstrap()['receipts']),initial)
