"""期初应收收款：独立于订单，必须同时进入资金流水并冲减两条应收路径。"""
import unittest
import test_workflow as fixture
import cash_query
import production_management as pm
import resources_costs as rc
import opening_receipts

erp = fixture.erp
NOW = '2026-10-31T09:00:00+08:00'


def audit(c, role, action, entity, before=None, after=None):
    pass


class OpeningReceiptTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    tearDown = fixture.WorkflowTests.tearDown

    def add_customer(self, opening=100000, day='2026-10-01'):
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO customers(id,name,route,note,legal_name,delivery_method,region,market_id,location_kind,phone,business_kind,opening_cents,opening_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      ('C-OPEN', '期初客户', '', '', '', '', '', '', '', '', '', opening, day))

    def totals(self, asof):
        with erp.connect() as c:
            cash = cash_query.report(c, asof)['totals']
            alerts = sum(g['outstanding_cents'] for g in pm.ar_alerts(c, asof))
        return cash, alerts

    def save(self, **body):
        with erp.connect(True) as c:
            return opening_receipts.save(c, body, '出纳', NOW, audit)


    def close_month(self, month):
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO resource_periods(month,version,payload) VALUES(?,?,?)",
                      (month, 1, rc.dump({'month': month, 'state': 'closed', 'version': 1, 'at': NOW, 'role': '会计'})))

    def test_closed_month_blocks_create_and_void(self):
        self.add_customer()
        receipt = self.save(customer_id='C-OPEN', received_date='2026-10-20', amount='300', method='银行转账', account_id='')
        self.close_month('2026-10')
        with self.assertRaisesRegex(ValueError, '已结账'):
            self.save(customer_id='C-OPEN', received_date='2026-10-25', amount='100', method='银行转账', account_id='')
        with self.assertRaisesRegex(ValueError, '已结账'):
            self.save(action='void', id=receipt['id'], reason='测试冲销')

    def test_partial_receipt_reduces_both_paths_and_enters_cash(self):
        self.add_customer()
        self.save(customer_id='C-OPEN', received_date='2026-10-20', amount='300', method='银行转账', account_id='')
        cash, alerts = self.totals('2026-10-31')
        self.assertEqual(70000, cash['receivable_cents'])
        self.assertEqual(70000, alerts)
        self.assertEqual(30000, cash['unassigned_income_cents'])

    def test_later_receipt_does_not_rewrite_earlier_day(self):
        self.add_customer()
        self.save(customer_id='C-OPEN', received_date='2026-10-25', amount='200', method='现金')
        _, before = self.totals('2026-10-20')
        _, after = self.totals('2026-10-31')
        self.assertEqual(100000, before)
        self.assertEqual(80000, after)

    def test_overpay_is_rejected(self):
        self.add_customer()
        self.save(customer_id='C-OPEN', received_date='2026-10-10', amount='900', method='现金')
        with self.assertRaisesRegex(ValueError, '不能超过该客户期初应收未收余额'):
            self.save(customer_id='C-OPEN', received_date='2026-10-11', amount='200', method='现金')

    def test_discount_reduces_receivable_but_not_cash(self):
        self.add_customer()
        self.save(customer_id='C-OPEN', received_date='2026-10-10', amount='100', discount='50', method='现金', note='协商减免')
        cash, alerts = self.totals('2026-10-31')
        self.assertEqual(85000, cash['receivable_cents'])
        self.assertEqual(85000, alerts)
        self.assertEqual(10000, cash['unassigned_income_cents'])

    def test_void_restores_receivable_and_cash(self):
        self.add_customer()
        rec = self.save(customer_id='C-OPEN', received_date='2026-10-10', amount='400', method='现金')
        with erp.connect(True) as c:
            opening_receipts.save(c, {'action': 'void', 'id': rec['id'], 'reason': '账号填错'}, '出纳', NOW, audit)
        cash, alerts = self.totals('2026-10-31')
        self.assertEqual(100000, cash['receivable_cents'])
        self.assertEqual(100000, alerts)
        self.assertEqual(0, cash['unassigned_income_cents'])

    def test_void_requires_reason(self):
        self.add_customer()
        rec = self.save(customer_id='C-OPEN', received_date='2026-10-10', amount='100', method='现金')
        with erp.connect(True) as c:
            with self.assertRaises(ValueError):
                opening_receipts.save(c, {'action': 'void', 'id': rec['id'], 'reason': ''}, '出纳', NOW, audit)


if __name__ == '__main__':
    unittest.main()
