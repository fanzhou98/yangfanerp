"""客户退货单打印：只读单据、参数错误 400、越权 403、内容完整。"""
import json
from test_auth_http import AuthHTTPFixture
from test_workflow import erp


class PrintReturnTests(AuthHTTPFixture):
    def _return(self):
        payload = {'id': 'RT-TEST-1', 'version': 1, 'received_date': '2026-10-30',
                   'customer_id': 'C-TEST', 'customer_name': '测试客户',
                   'product_id': 'P-TEST', 'product_name': '大豆腐',
                   'qty': '2', 'net_kg': '12.5', 'unit': '筐', 'billing_unit': '筐',
                   'condition': 'spoiled', 'reason': '品质异议：颜色偏暗',
                   'source_note': '原送货单', 'order_id': 'SO-TEST-1',
                   'registered_by': '库管', 'created_at': '2026-10-30T09:00:00+08:00',
                   'voided': False, 'disposals': [],
                   'finance': {'state': 'pending_review', 'amount_cents': 27000,
                               'account_qty': '10', 'billing_unit': '筐', 'original_price': '27'}}
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO sales_returns(id,payload) VALUES(?,?)',
                      ('RT-TEST-1', json.dumps(payload, ensure_ascii=False)))
        return payload

    def test_parameter_errors_are_400(self):
        self._return()
        cashier, _ = self.user('printretcash', '出纳')
        status, body, _ = cashier.request('/print/returns')
        self.assertEqual(status, 400, body)
        self.assertIn('退货单', str(body))
        status, body, _ = cashier.request('/print/returns?id=RT-NOPE')
        self.assertEqual(status, 400, body)
        self.assertIn('不存在', str(body))

    def test_driver_is_denied(self):
        self._return()
        driver, _ = self.user('printretdriver', '司机')
        status, _, _ = driver.request('/print/returns?id=RT-TEST-1')
        self.assertEqual(status, 403)

    def test_document_content(self):
        self._return()
        warehouse, _ = self.user('printretwh', '库管')
        status, body, _ = warehouse.request('/print/returns?id=RT-TEST-1')
        self.assertEqual(status, 200)
        html = body if isinstance(body, str) else body.decode('utf-8')
        for token in ('客户退货单', '测试客户', '大豆腐', '12.5', '变质', '品质异议', 'SO-TEST-1'):
            self.assertIn(token, html)
