"""应收有两条独立路径：cash_query SQL 聚合与 ar_alerts + receipts_paid_asof。

两者必须逐客户、逐日期给出同一个应收合计，否则首页/资金页与应收预警会互相矛盾。
"""
import json
import unittest
import test_workflow as fixture
import cash_query
import production_management as pm

erp = fixture.erp


class ArConsistencyTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    tearDown = fixture.WorkflowTests.tearDown
    order = fixture.WorkflowTests.order
    settle = fixture.WorkflowTests.settle
    review = fixture.WorkflowTests.review
    pay = fixture.WorkflowTests.pay

    def totals(self, asof):
        with erp.connect() as c:
            cash = cash_query.report(c, asof)['totals']['receivable_cents']
            alerts = sum(g['outstanding_cents'] for g in pm.ar_alerts(c, asof))
        return cash, alerts

    def test_partial_receipt_agrees(self):
        order = self.review(self.settle(self.order()))
        order = self.pay(order, '500')
        cash, alerts = self.totals('2026-10-18')
        self.assertEqual(cash, order['total_cents'] - 50000)
        self.assertEqual(cash, alerts)

    def test_receipt_dated_after_asof_not_counted(self):
        order = self.review(self.settle(self.order()))
        self.pay(order, '500')
        before, alerts_before = self.totals('2026-10-17')
        self.assertEqual((before, alerts_before), (0, 0))
        on_day, alerts_on_day = self.totals('2026-10-18')
        self.assertEqual(on_day, alerts_on_day)

    def test_voided_receipt_restores_receivable_in_both(self):
        order = self.review(self.settle(self.order()))
        order = self.pay(order, '500')
        with erp.connect() as c:
            receipt = json.loads(c.execute("SELECT payload FROM receipts WHERE json_extract(payload,'$.order_id')=?", (order['id'],)).fetchone()[0])
        erp.mutate('void-receipt', {'version': order['version'], 'receipt_id': receipt['id'], 'reason': '核对银行退回'}, '出纳', order['id'])
        cash, alerts = self.totals('2026-10-18')
        self.assertEqual(cash, order['total_cents'])
        self.assertEqual(cash, alerts)

    def test_opening_receivable_agrees(self):
        with erp.connect(True) as c:
            c.execute("UPDATE customers SET opening_cents=150000,opening_date='2026-09-30' WHERE id='C001'")
        cash, alerts = self.totals('2026-10-31')
        self.assertEqual(cash, 150000)
        self.assertEqual(cash, alerts)


if __name__ == '__main__':
    unittest.main()
