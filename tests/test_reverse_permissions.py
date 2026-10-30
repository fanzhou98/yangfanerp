"""Accounts-mode HTTP coverage for receipt voiding, return-credit reversal and crate ledger reads."""
import json
import unittest
import uuid

import inventory as inv
import test_auth_http as fixture
from test_auth_http import Client, erp


class ReversePermissionTests(fixture.AuthHTTPTests):
    def receipts_for(self, order_id):
        with erp.connect() as c:
            rows = [json.loads(r[0]) for r in c.execute('SELECT payload FROM receipts')]
        return [r for r in rows if r.get('order_id') == order_id]

    def test_ledger_roles_can_read_crate_ledger(self):
        for username, role in [('crateacct', '会计'), ('cratewh', '库管')]:
            client, _ = self.user(username, role)
            code, body, _ = client.request('/api/crate-ledger?date=' + self.order_test_day)
            self.assertEqual(code, 200, body)
            self.assertIn('customers', body)

    def test_cashier_voids_receipt_through_http(self):
        order = self.seed_finance()
        receipt = self.receipts_for(order['id'])[0]
        cashier, _ = self.user('cashvoid', '出纳')
        code, result, _ = cashier.request('/api/orders/' + order['id'] + '/void-receipt',
                                          {'receipt_id': receipt['id'], 'reason': '收款重复登记',
                                           'version': order['version']})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['paid_cents'], 0)
        self.assertTrue(self.receipts_for(order['id'])[0].get('voided'))

    def test_cashier_reverses_posted_return_credit_through_http(self):
        order = self.order_body()
        order['lines'][0]['actual_qty'] = '2'
        o = erp.mutate('order', order, '库管')
        o = erp.mutate('settle', {'version': o['version'], 'mode': 'customer'}, '会计', o['id'])
        o = erp.mutate('review', {'version': o['version'], 'evidence_checked': True}, '出纳', o['id'])
        with erp.connect(True) as c:
            ops = inv.Operations(c, erp.now, erp.audit)
            r = ops.create_return({'received_date': o['business_date'], 'customer_id': 'C001',
                                   'product_id': 'P004', 'qty': '1', 'net_kg': '10',
                                   'condition': 'broken', 'reason': '破损退回', 'source_note': '原单已核',
                                   'order_id': o['id'], 'request_key': str(uuid.uuid4()),
                                   'received_checked': True}, '库管')
            r = ops.return_action({'id': r['id'], 'version': r['version'], 'action': 'account',
                                   'account_date': o['business_date'], 'account_qty': '1',
                                   'price': '75', 'note': '按原销售单价核定', 'price_checked': True}, '会计')
            r = ops.return_action({'id': r['id'], 'version': r['version'], 'action': 'review',
                                   'evidence_checked': True}, '出纳')
        self.assertEqual(r['finance']['state'], 'posted')
        cashier, _ = self.user('cashreverse', '出纳')
        code, result, _ = cashier.request('/api/returns/action', {'id': r['id'], 'version': r['version'],
                                                                  'action': 'reverse-credit',
                                                                  'reason': '退货登记有误'})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['record']['finance']['state'], 'reversed')


if __name__ == '__main__':
    unittest.main()

    def test_cashier_voids_purchase_payment_but_warehouse_cannot(self):
        with erp.connect(True) as c:
            order = {'id': 'PBH2', 'version': 1, 'business_date': '2026-10-03', 'expected_date': '2026-10-05',
                     'supplier_id': 'S1', 'supplier_name': '冲销测试供应商', 'state': 'confirmed', 'total_cents': 1000,
                     'lines': [{'id': 'L1', 'material_id': 'RM-SOY', 'material_name': '黄豆', 'warehouse_id': 'WH-TOFU',
                                'unit': '公斤', 'qty': '10', 'price': '100', 'amount_cents': 1000}]}
            receipt = {'id': 'PBH2-R', 'order_id': 'PBH2', 'business_date': '2026-10-05', 'supplier_id': 'S1',
                       'supplier_name': '冲销测试供应商', 'amount_cents': 1000,
                       'lines': [{'line_id': 'L1', 'material_id': 'RM-SOY', 'material_name': '黄豆', 'warehouse_id': 'WH-TOFU',
                                  'unit': '公斤', 'qty': '10', 'amount_cents': 1000, 'material_entry_id': 'M2'}]}
            payment = {'id': 'PBH2-P', 'version': 1, 'order_id': 'PBH2', 'supplier_id': 'S1',
                       'supplier_name': '冲销测试供应商', 'business_date': '2026-10-06', 'amount_cents': 400,
                       'method': '银行转账', 'handler': '出纳', 'reference': 'PAY2'}
            for table, row in (('purchase_orders', order), ('purchase_receipts', receipt), ('purchase_payments', payment)):
                c.execute('INSERT INTO ' + table + ' VALUES(?,?,?)', (row['id'], row['id'], erp.dumps(row)))
        warehouse, _ = self.user('payvoidwh', '库管')
        self.assertEqual(warehouse.request('/api/purchasing/payment-void',
                                           {'payment_id': 'PBH2-P', 'version': 1, 'reason': '重复付款'})[0], 403)
        cashier, _ = self.user('payvoid', '出纳')
        code, result, _ = cashier.request('/api/purchasing/payment-void',
                                          {'payment_id': 'PBH2-P', 'version': 1, 'reason': '重复付款'})
        self.assertEqual(code, 200, result)
        with erp.connect() as c:
            stored = json.loads(c.execute("SELECT payload FROM purchase_payments WHERE id='PBH2-P'").fetchone()[0])
        self.assertTrue(stored['voided'])
        code, ledger, _ = cashier.request('/api/purchase-ledger?kind=payables&month=2026-10')
        self.assertEqual(code, 200, ledger)
        self.assertEqual(ledger['summary']['paid_cents'], 0)

    def test_cashier_reverses_refund_but_warehouse_cannot(self):
        order = self.order_body()
        order['lines'][0]['actual_qty'] = '2'
        o = erp.mutate('order', order, '库管')
        o = erp.mutate('settle', {'version': o['version'], 'mode': 'customer'}, '会计', o['id'])
        o = erp.mutate('review', {'version': o['version'], 'evidence_checked': True}, '出纳', o['id'])
        with erp.connect(True) as c:
            ops = inv.Operations(c, erp.now, erp.audit)
            r = ops.create_return({'received_date': o['business_date'], 'customer_id': 'C001', 'product_id': 'P004',
                                   'qty': '1', 'net_kg': '10', 'condition': 'broken', 'reason': '破损退回',
                                   'source_note': '原单已核', 'order_id': o['id'], 'request_key': str(uuid.uuid4()),
                                   'received_checked': True}, '库管')
            r = ops.return_action({'id': r['id'], 'version': r['version'], 'action': 'account',
                                   'account_date': o['business_date'], 'account_qty': '1', 'price': '75',
                                   'note': '按原销售单价核定', 'price_checked': True}, '会计')
            r = ops.return_action({'id': r['id'], 'version': r['version'], 'action': 'review',
                                   'evidence_checked': True}, '出纳')
            amount = '%.2f' % (inv.wallet(r) / 100)
            r = ops.return_action({'id': r['id'], 'version': r['version'], 'action': 'refund',
                                   'evidence_checked': True, 'amount': amount, 'refund_date': r['finance']['account_date'],
                                   'method': '银行转账', 'note': '退款凭据'}, '出纳')
        rid = r['finance']['refunds'][0]['id']
        warehouse, _ = self.user('refundwh', '库管')
        self.assertEqual(warehouse.request('/api/returns/action',
                                           {'id': r['id'], 'version': r['version'], 'action': 'reverse-refund',
                                            'refund_id': rid, 'reason': '退款被退回'})[0], 403)
        cashier, _ = self.user('refundvoid', '出纳')
        code, result, _ = cashier.request('/api/returns/action',
                                          {'id': r['id'], 'version': r['version'], 'action': 'reverse-refund',
                                           'refund_id': rid, 'reason': '退款被退回'})
        self.assertEqual(code, 200, result)
        self.assertTrue(result['record']['finance']['refunds'][0]['voided'])

    def test_cashier_voids_wage_payment_but_accountant_cannot(self):
        with erp.connect(True) as c:
            row = {'id': 'PRV1', 'version': 1, 'kind': 'payment', 'month': self.order_test_day[:7],
                   'business_date': self.order_test_day, 'employee_id': 'E-REV', 'employee_name': '冲销测试员工',
                   'amount_cents': 10000, 'method': 'cash', 'handler': '出纳', 'reference': 'WAGE-REV'}
            c.execute('INSERT INTO payroll_records VALUES(?,?,?)', (row['id'], row['id'], erp.dumps(row)))
        accountant, _ = self.user('wagevoidacc', '会计')
        self.assertEqual(accountant.request('/api/factory/wage-payment-void',
                                            {'payment_id': 'PRV1', 'version': 1, 'reason': '银行退回'})[0], 403)
        cashier, _ = self.user('wagevoid', '出纳')
        code, result, _ = cashier.request('/api/factory/wage-payment-void',
                                          {'payment_id': 'PRV1', 'version': 1, 'reason': '银行退回'})
        self.assertEqual(code, 200, result)
        self.assertTrue(result['voided'])
