"""Receipt reversal must agree across bills, cash, reports and release checks."""
import json
import unittest
import test_workflow as fixture
import funds
import finance_query
import sales_chain
from ops.business_check import check_database

erp = fixture.erp


class ReceiptClosureTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    tearDown = fixture.WorkflowTests.tearDown
    order = fixture.WorkflowTests.order
    settle = fixture.WorkflowTests.settle
    review = fixture.WorkflowTests.review

    def reversed_order(self):
        order = self.review(self.settle(self.order()))
        with erp.connect(True) as c:
            account = funds.save(c, 'account', {'name': '隔离收款账户', 'kind': '银行账户', 'opening_date': '2026-10-01', 'opening_balance': '0', 'active': True}, '管理员', erp.now, erp.audit)
        order = erp.mutate('receipt', {'version': order['version'], 'amount': '100', 'received_date': '2026-10-18', 'method': '银行转账', 'account_id': account['id']}, '出纳', order['id'])
        with erp.connect() as c:
            receipt = json.loads(c.execute("SELECT payload FROM receipts WHERE json_extract(payload,'$.order_id')=?", (order['id'],)).fetchone()[0])
        order = erp.mutate('void-receipt', {'version': order['version'], 'receipt_id': receipt['id'], 'reason': '核对银行退回'}, '出纳', order['id'])
        return order, receipt, account

    def test_void_is_excluded_from_python_and_sql_cash(self):
        order, receipt, account = self.reversed_order()
        with erp.connect() as c:
            self.assertFalse(any(r['id'] == 'receipt:' + receipt['id'] for r in funds.movements(c)))
            report = funds.report(c, '2026-10-31')
            self.assertEqual(next(r for r in report['accounts'] if r['id'] == account['id'])['balance_cents'], 0)
        self.assertEqual(order['paid_cents'], 0)

    def test_void_is_excluded_from_sales_reconciliation(self):
        order, receipt, _ = self.reversed_order()
        with erp.connect() as c:
            report = sales_chain.report(c, '2026-10-01', '2026-10-31', view='collection')
        row = next(r for r in report['rows'] if r['order_id'] == order['id'])
        self.assertEqual(row['receipts'], [])
        self.assertEqual(row['issues'], [])

    def test_bill_detail_matches_cash_receipt_summary(self):
        order, receipt, _ = self.reversed_order()
        with erp.connect() as c:
            report = finance_query.ledger(c, '2026-10-01', '2026-10-31', customer_id=order['customer_id'], clearance='all')
        row = next(r for r in report['rows'] if r['id'] == order['id'])
        self.assertEqual(row['receipts'], [])
        self.assertFalse(any(r['id'] == receipt['id'] for r in report['receipts']))

    def test_voided_receipt_does_not_block_later_order_correction(self):
        order, _, _ = self.reversed_order()
        order = erp.mutate('order', order, '会计', order['id'])
        self.assertEqual(order['state'], 'dispatched')
        self.assertTrue(check_database(erp.DB)['ok'])

    def test_active_receipt_still_requires_reviewed_order(self):
        order, receipt, _ = self.reversed_order()
        with erp.connect(True) as c:
            receipt.pop('voided', None)
            c.execute('UPDATE receipts SET payload=? WHERE id=?', (json.dumps(receipt), receipt['id']))
            order['state'] = 'dispatched'
            c.execute('UPDATE orders SET payload=? WHERE id=?', (json.dumps(order), order['id']))
        result = check_database(erp.DB)
        self.assertTrue(any(r['type'] == 'receipts.order_not_reviewed' for r in result['errors']))
