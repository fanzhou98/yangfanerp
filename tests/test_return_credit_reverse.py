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

