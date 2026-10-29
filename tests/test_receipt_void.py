"""Controlled receipt reversal: keep the original row, restore the balance, leave a trail."""
from test_workflow import WorkflowTests, erp
import statements
from ops.business_check import check_database


class ReceiptVoidTests(WorkflowTests):
    def paid_order(self):
        o = self.review(self.settle(self.order()))
        o = erp.mutate('receipt', {'version': o['version'], 'amount': '600', 'discount': '60', 'rounding': '9.93',
                                   'received_date': '2026-10-18', 'method': '现金', 'note': '双方确认优惠及尾差'}, '出纳', o['id'])
        return o

    def receipt_id(self):
        return erp.bootstrap()['receipts'][0]['id']

    def void(self, o, receipt_id=None, reason='客户转账被退回', role='出纳'):
        return erp.mutate('void-receipt', {'version': o['version'], 'receipt_id': receipt_id or self.receipt_id(),
                                           'reason': reason}, role, o['id'])

    def test_void_restores_balance_and_hides_receipt(self):
        o = self.paid_order()
        rid = self.receipt_id()
        before = len(erp.bootstrap()['receipts'])
        o = self.void(o, rid)
        self.assertEqual((o['paid_cents'], o['discount_cents'], o['rounding_cents']), (0, 0, 0))
        self.assertEqual(erp.inventory.balance(o), 66993)
        self.assertEqual(o['status'], '待收款')
        self.assertEqual(len(erp.bootstrap()['receipts']), before - 1)
        with erp.connect() as c:
            row = c.execute('SELECT payload FROM receipts WHERE id=?', (rid,)).fetchone()
            voided = erp.json.loads(row[0])
            snapshot = statements.snapshot(c, 'C001', '2026-10-18', erp.now())
        self.assertTrue(voided['voided'])
        self.assertEqual(voided['void_reason'], '客户转账被退回')
        self.assertEqual(snapshot['totals']['payable_cents'], 66993)
        self.assertEqual(snapshot['totals']['current_paid_cents'], 0)
        self.assertTrue(check_database(erp.DB)['ok'])

    def test_void_requires_reason_and_permission_and_is_not_repeatable(self):
        o = self.paid_order()
        rid = self.receipt_id()
        with self.assertRaisesRegex(ValueError, '冲销原因'):
            self.void(o, rid, reason='  ')
        with self.assertRaisesRegex(ValueError, '无此操作权限'):
            self.void(o, rid, role='库管')
        o = self.void(o, rid)
        with self.assertRaisesRegex(ValueError, '已冲销'):
            self.void(o, rid)

    def test_void_unknown_or_foreign_receipt_is_rejected(self):
        o = self.paid_order()
        with self.assertRaisesRegex(ValueError, '收款记录不存在'):
            self.void(o, 'RC-NOTEXIST')
        other = self.review(self.settle(self.order()))
        with self.assertRaisesRegex(ValueError, '收款与账单不匹配'):
            self.void(other, self.receipt_id())
