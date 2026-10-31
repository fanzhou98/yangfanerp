"""退货抵扣串起四本账：算票、退货、收款、应收预警。

已收款订单的退货先形成客户钱包余额，下一张审核通过的账单自动抵扣；
抵扣后钱包清零，退款不能超过未抵余额，两条应收路径保持同数。
"""
import json
import unittest
import test_inventory as fixture
import inventory as inv
import cash_query
import production_management as pm

erp = fixture.erp


class ArWalletFlowTests(unittest.TestCase):
    setUp = fixture.InventoryTests.setUp
    tearDown = fixture.InventoryTests.tearDown
    order = fixture.InventoryTests.order
    settle = fixture.InventoryTests.settle
    review = fixture.InventoryTests.review
    pay = fixture.InventoryTests.pay
    ret = fixture.InventoryTests.ret
    account = fixture.InventoryTests.account
    act = fixture.InventoryTests.act
    ops = fixture.InventoryTests.ops

    def current_return(self, rid):
        with erp.connect() as c:
            return json.loads(c.execute('SELECT payload FROM sales_returns WHERE id=?', (rid,)).fetchone()[0])

    def totals(self, asof='2026-10-31'):
        with erp.connect() as c:
            return cash_query.report(c, asof)['totals']['receivable_cents'], sum(g['outstanding_cents'] for g in pm.ar_alerts(c, asof))

    def test_return_credit_offsets_next_bill_and_stays_consistent(self):
        first = self.review(self.settle(self.order()))
        first = self.pay(first, str(first['total_cents'] / 100))
        returned = self.act(self.account(self.ret(order_id=first['id'], qty='2', net_kg='20')), 'review', '出纳', evidence_checked=True)
        self.assertEqual(returned['finance']['state'], 'posted')
        self.assertEqual(inv.wallet(self.current_return(returned['id'])), 3333)

        second = self.review(self.settle(self.order()))
        self.assertEqual(second['return_credit_cents'], 3333)
        self.assertEqual(inv.wallet(self.current_return(returned['id'])), 0)
        cash, alerts = self.totals()
        self.assertEqual(cash, alerts)
        with erp.connect() as c:
            stored = json.loads(c.execute('SELECT payload FROM orders WHERE id=?', (second['id'],)).fetchone()[0])
        self.assertEqual(inv.balance(stored), stored['total_cents'] - 3333)

        fresh = self.current_return(returned['id'])
        with self.assertRaisesRegex(ValueError, '退款不能超过'):
            self.act(fresh, 'refund', '出纳', evidence_checked=True, amount='1.00', refund_date='2026-10-31', method='银行转账', note='已抵扣不应再退')

    def test_reversed_credit_restores_bill_and_allows_void(self):
        first = self.review(self.settle(self.order()))
        first = self.pay(first, str(first['total_cents'] / 100))
        returned = self.act(self.account(self.ret(order_id=first['id'], qty='2', net_kg='20')), 'review', '出纳', evidence_checked=True)
        second = self.review(self.settle(self.order()))
        self.assertEqual(second['return_credit_cents'], 3333)
        revoked = self.act(self.current_return(returned['id']), 'reverse-credit', '出纳', reason='退货登记有误')
        self.assertEqual(revoked['finance']['state'], 'reversed')
        with erp.connect() as c:
            stored = json.loads(c.execute('SELECT payload FROM orders WHERE id=?', (second['id'],)).fetchone()[0])
        self.assertEqual(stored['return_credit_cents'], 0)
        voided = self.act(self.current_return(returned['id']), 'void', '会计', reason='客户取消退货')
        self.assertTrue(voided.get('voided'))
        cash, alerts = self.totals()
        self.assertEqual(cash, alerts)


if __name__ == '__main__':
    unittest.main()

    def test_cross_month_return_credit_offsets_once(self):
        first = self.review(self.settle(self.order(day='2026-10-20')))
        first = self.pay(first, str(first['total_cents'] / 100))
        returned = self.act(self.account(self.ret(order_id=first['id'], qty='2', net_kg='20')), 'review', '出纳', evidence_checked=True)
        self.assertEqual(inv.wallet(self.current_return(returned['id'])), 3333)

        second = self.review(self.settle(self.order(day='2026-11-02')))
        self.assertEqual(second['return_credit_cents'], 3333)
        self.assertEqual(inv.wallet(self.current_return(returned['id'])), 0)

        third = self.review(self.settle(self.order(day='2026-11-03')))
        self.assertEqual(third['return_credit_cents'], 0)
        cash, alerts = self.totals(asof='2026-11-03')
        self.assertEqual(cash, alerts)
