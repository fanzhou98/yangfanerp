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
