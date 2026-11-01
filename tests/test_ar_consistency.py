"""应收有两条独立路径：cash_query SQL 聚合与 ar_alerts + receipts_paid_asof。

两者必须逐客户、逐日期给出同一个应收合计，否则首页/资金页与应收预警会互相矛盾。
"""
import json
import unittest
import uuid
import test_workflow as fixture
import cash_query
import production_management as pm
import resources_costs as rc

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

    def material(self, day, qty, kind):
        with erp.connect(True) as c:
            return rc.Operations(c, erp.now, erp.audit).material({'request_key': str(uuid.uuid4()), 'revision': rc.revision(c),
                'kind': kind, 'material_id': 'RM-SOY', 'warehouse_id': 'WH-TOFU', 'business_date': day, 'qty': qty,
                'amount': '4000', 'handler': '库管', 'note': '测试', 'production_system_id': 'tofu'}, '管理员')

    def byproduct_sale(self):
        self.material('2026-10-19', '1000', 'receipt')
        self.material('2026-10-20', '100', 'consume')
        with erp.connect(True) as c:
            rc.save_byproduct_config(c, {'buyer': '豆渣收购点', 'add_kg': '10'}, '管理员', erp.now, erp.audit)
            rc.save_byproduct_price(c, {'month': '2026-10', 'price': '0.5'}, '会计', erp.now, erp.audit)
            return rc.settle_byproduct(c, {'month': '2026-10', 'request_key': str(uuid.uuid4()), 'handler': '会计'}, '会计', erp.now, erp.audit)

    def test_byproduct_settlement_agrees(self):
        sale = self.byproduct_sale()
        cash, alerts = self.totals('2026-10-31')
        self.assertEqual(cash, sale['amount_cents'])
        self.assertEqual(cash, alerts)

    def test_byproduct_partial_receipt_across_month_agrees(self):
        sale = self.byproduct_sale()
        with erp.connect(True) as c:
            rc.Operations(c, erp.now, erp.audit).receive_byproduct({'id': sale['id'], 'version': sale['version'],
                'amount': '20', 'business_date': '2026-11-02', 'note': '部分到账'}, '出纳')
        for asof in ('2026-10-31', '2026-11-01', '2026-11-02'):
            cash, alerts = self.totals(asof)
            self.assertEqual(cash, alerts, asof)

    def test_overpayment_rejected_and_fully_paid_clears_both(self):
        order = self.review(self.settle(self.order()))
        self.pay(order, '300')
        with self.assertRaises(ValueError):
            erp.mutate('receipt', {'version': order['version'], 'amount': str((order['total_cents'] - 30000) / 100 + 1),
                'received_date': '2026-10-18', 'method': '银行转账', 'note': '超收测试'}, '出纳', order['id'])
        remaining = order['total_cents'] - 30000
        with erp.connect() as c:
            current = json.loads(c.execute('SELECT payload FROM orders WHERE id=?', (order['id'],)).fetchone()[0])
        erp.mutate('receipt', {'version': current['version'], 'amount': str(remaining / 100), 'received_date': '2026-10-18',
            'method': '银行转账', 'note': '补足尾款'}, '出纳', order['id'])
        cash, alerts = self.totals('2026-10-18')
        self.assertEqual(cash, alerts)
        with erp.connect() as c:
            paid = json.loads(c.execute('SELECT payload FROM orders WHERE id=?', (order['id'],)).fetchone()[0])
        self.assertEqual(paid['paid_cents'], paid['total_cents'])


    def test_receipt_in_closed_month_requires_reopen(self):
        order = self.review(self.settle(self.order()))
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO resource_periods(month,version,payload) VALUES(?,?,?)",
                      ('2026-10', 1, rc.dump({'month': '2026-10', 'state': 'closed', 'version': 1,
                                              'at': '2026-10-31T09:00:00+08:00', 'role': '会计'})))
        with self.assertRaisesRegex(ValueError, '已结账'):
            erp.mutate('receipt', {'version': order['version'], 'amount': '100', 'received_date': '2026-10-18',
                'method': '银行转账', 'note': '结账后补记收款'}, '出纳', order['id'])

    def test_opening_receivable_agrees(self):
        with erp.connect(True) as c:
            c.execute("UPDATE customers SET opening_cents=150000,opening_date='2026-09-30' WHERE id='C001'")
        cash, alerts = self.totals('2026-10-31')
        self.assertEqual(cash, 150000)
        self.assertEqual(cash, alerts)


if __name__ == '__main__':
    unittest.main()
