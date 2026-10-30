"""采购订单 / 验收入库单打印：权限与内容。"""
import json

from test_auth_http import AuthHTTPFixture
from test_workflow import erp


class PurchasePrintTests(AuthHTTPFixture):
    def seed(self):
        with erp.connect(True) as c:
            c.execute("INSERT OR REPLACE INTO suppliers(id,name,version,payload) VALUES(?,?,?,?)", ('S-OK', '测试供应商', 1, json.dumps(
                {'id': 'S-OK', 'name': '测试供应商', 'active': True, 'payment_days': 30}, ensure_ascii=False)))
            order = {'id': 'PO-OK', 'business_date': '2026-10-30', 'expected_date': '2026-11-01',
                     'supplier_id': 'S-OK', 'handler': '会计甲', 'reference': 'HT-001', 'note': '按合同验收',
                     'state': 'confirmed', 'version': 1, 'total_cents': 45000,
                     'lines': [{'id': 'L1', 'material_id': 'RM-SOY', 'material_name': '大豆', 'unit': '公斤',
                                'qty': '100', 'price': '4.5', 'amount_cents': 45000, 'warehouse_id': 'WH-TOFU',
                                'note': ''}]}
            c.execute("INSERT OR REPLACE INTO purchase_orders(id,request_key,payload) VALUES(?,?,?)", ('PO-OK', 'test-print-order', json.dumps(order, ensure_ascii=False)))
            receipt = {'id': 'RC-OK', 'order_id': 'PO-OK', 'business_date': '2026-10-30', 'handler': '库管乙',
                       'reference': 'YS-001', 'note': '全部合格', 'amount_cents': 45000, 'due_date': '2026-11-30',
                       'lines': [{'id': 'R1', 'line_id': 'L1', 'material_entry_id': 'ME-1', 'material_id': 'RM-SOY', 'material_name': '大豆',
                                  'unit': '公斤', 'qty': '100', 'amount_cents': 45000, 'warehouse_id': 'WH-TOFU'}]}
            c.execute("INSERT OR REPLACE INTO purchase_receipts(id,request_key,payload) VALUES(?,?,?)", ('RC-OK', 'test-print-receipt', json.dumps(receipt, ensure_ascii=False)))

    def test_unknown_document_and_missing_id_are_400(self):
        accountant, _ = self.user('pprintacct', '会计')
        status, body, _ = accountant.request('/print/purchases?document=bogus&id=X')
        self.assertEqual(status, 400, body)
        self.assertIn('单据类型无效', str(body))
        status, body, _ = accountant.request('/print/purchases?document=order&id=NOT-EXIST')
        self.assertEqual(status, 400, body)
        self.assertIn('采购单不存在', str(body))

    def test_roles_without_purchase_read_are_403(self):
        driver, _ = self.user('pprintdriver', '司机')
        status, _, _ = driver.request('/print/purchases?document=order&id=PO-OK')
        self.assertEqual(status, 403)

    def test_order_and_receipt_pages_render_supplier_and_amounts(self):
        self.seed()
        accountant, _ = self.user('pprintok', '会计')
        status, body, _ = accountant.request('/print/purchases?document=order&id=PO-OK')
        self.assertEqual(status, 200, body)
        text = body.decode() if isinstance(body, bytes) else str(body)
        self.assertIn('采购订单', text)
        self.assertIn('测试供应商', text)
        self.assertIn('订单合计', text)
        self.assertIn('450.00', text)
        status, body, _ = accountant.request('/print/purchases?document=receipt&id=RC-OK')
        self.assertEqual(status, 200, body)
        text = body.decode() if isinstance(body, bytes) else str(body)
        self.assertIn('验收入库单', text)
        self.assertIn('PO-OK', text)
        self.assertIn('本单合计', text)
