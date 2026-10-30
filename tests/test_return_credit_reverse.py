"""Controlled reversal of a posted return credit: keep the return, restore the bill."""
import unittest
import test_inventory as fixture
import inventory as inv
from ops.business_check import check_database

erp = fixture.erp


class ReturnCreditReverseTests(unittest.TestCase):
    setUp = fixture.InventoryTests.setUp
    tearDown = fixture.InventoryTests.tearDown
    order = fixture.InventoryTests.order
    settle = fixture.InventoryTests.settle
    review = fixture.InventoryTests.review
    ret = fixture.InventoryTests.ret
    pay = fixture.InventoryTests.pay
    ops = fixture.InventoryTests.ops
    act = fixture.InventoryTests.act
    account = fixture.InventoryTests.account

    def posted(self):
        o = self.review(self.settle(self.order()))
        r = self.ret(order_id=o['id'], qty='2', net_kg='20')
        r = self.account(r)
        r = self.act(r, 'review', '出纳', evidence_checked=True)
        return o, r

    def current_order(self, oid):
        return next(o for o in erp.bootstrap()['orders'] if o['id'] == oid)

    def test_refund_date_cannot_be_later_than_today(self):
        r = self.act(self.account(self.ret()), 'review', '出纳', evidence_checked=True)
        with self.assertRaisesRegex(ValueError, '不能晚于今天'):
            self.act(r, 'refund', '出纳', evidence_checked=True, amount='1.00', refund_date='2099-12-31', method='银行转账', note='测试')
    def test_reverse_restores_bill_and_keeps_return_history(self):
        o, r = self.posted()
        credited = self.current_order(o['id'])['return_credit_cents']
        self.assertGreater(credited, 0)
        self.assertEqual(erp.inventory.balance(self.current_order(o['id'])), erp.inventory.balance(o) - credited)
        r = self.act(r, 'reverse-credit', '出纳', reason='退货登记有误，实物未退货')
        after = self.current_order(o['id'])
        self.assertEqual(after['return_credit_cents'], 0)
        self.assertEqual(erp.inventory.balance(after), erp.inventory.balance(o))
        self.assertEqual(r['finance']['state'], 'reversed')
        self.assertEqual(r['finance']['reverse_reason'], '退货登记有误，实物未退货')
        self.assertEqual(r['finance']['amount_cents'], credited)
        self.assertEqual(inv.wallet(r), 0)
        self.assertTrue(check_database(erp.DB)['ok'])

    def test_reverse_guards(self):
        o, r = self.posted()
        with self.assertRaisesRegex(ValueError, '无此操作权限'):
            self.act(r, 'reverse-credit', '库管', reason='越权尝试')
        with self.assertRaisesRegex(ValueError, '冲销原因'):
            self.act(r, 'reverse-credit', '出纳', reason=' ')
        r = self.act(r, 'reverse-credit', '出纳', reason='客户退回登记重复')
        with self.assertRaisesRegex(ValueError, '只有已复核入账'):
            self.act(r, 'reverse-credit', '出纳', reason='重复冲销')
        # 冲销后原退货单可以按普通流程作废，不再占用客户额度。
        voided = self.act(r, 'void', '库管', reason='同一笔退货重复登记')
        self.assertTrue(voided['voided'])
        # 保留 reversed 快照的作废是合法路径，业务检查器不得误报。
        self.assertTrue(check_database(erp.DB)['ok'])

    def test_voiding_receipt_reapplies_unused_return_credit(self):
        import resources_costs as rc
        o = self.review(self.settle(self.order()))
        due = erp.inventory.balance(o)
        o = self.pay(o, f'{due / 100:.2f}')
        r = self.act(self.account(self.ret(order_id=o['id'], qty='2', net_kg='20')), 'review', '出纳', evidence_checked=True)
        self.assertEqual(self.current_order(o['id']).get('return_credit_cents', 0), 0)
        self.assertGreater(inv.wallet(r), 0)
        with erp.connect() as c:
            receipt = next(x for x in rc.rows(c, 'receipts') if x.get('order_id') == o['id'] and not x.get('voided'))
        o = erp.mutate('void-receipt', {'receipt_id': receipt['id'], 'version': o['version'], 'reason': '收款重复登记，冲销后应继续抵扣退货'}, '出纳', o['id'])
        after = self.current_order(o['id'])
        self.assertEqual(after['return_credit_cents'], r['finance']['amount_cents'])
        fresh = next(x for x in erp.bootstrap()['sales_returns'] if x['id'] == r['id'])
        self.assertEqual(inv.wallet(fresh), 0)
        self.assertEqual(erp.inventory.balance(after), due - after['return_credit_cents'])
        self.assertTrue(check_database(erp.DB)['ok'])

    def test_reverse_refund_restores_wallet_and_checker(self):
        r = self.act(self.account(self.ret()), 'review', '出纳', evidence_checked=True)
        wallet0 = inv.wallet(r)
        self.assertGreater(wallet0, 0)
        r = self.act(r, 'refund', '出纳', evidence_checked=True, amount='%.2f' % (wallet0 / 100),
                     refund_date=r['finance']['account_date'], method='银行转账', note='退款凭据001')
        self.assertEqual(inv.wallet(r), 0)
        rid = r['finance']['refunds'][0]['id']
        with self.assertRaisesRegex(ValueError, '冲销原因'):
            self.act(r, 'reverse-refund', '出纳', refund_id=rid, reason='')
        r = self.act(r, 'reverse-refund', '出纳', refund_id=rid, reason='退款被银行退回')
        self.assertEqual(inv.wallet(r), wallet0)
        self.assertTrue(r['finance']['refunds'][0]['voided'])
        self.assertTrue(check_database(erp.DB)['ok'])
        with self.assertRaisesRegex(ValueError, '已冲销'):
            self.act(r, 'reverse-refund', '出纳', refund_id=rid, reason='再次冲销')
