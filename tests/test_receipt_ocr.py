"""收款截图识别：规则解析、权限、证据链与收款登记校验。"""
import base64
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import struct
import unittest
import zlib

import receipt_ocr
import erp_access
from test_auth_http import AuthHTTPFixture, erp


def _png(width=600, height=800, shade=b'\xee\xee\xee'):
    raw = b''.join(b'\x00' + shade * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


WECHAT_TEXT = '''微信支付
转账成功
¥1,280.00
转账时间 2026-10-26 14:32:18
转账单号 1000050001202610261234567890
付款方 昌吉市洋帆豆制品厂
收款方 乌鲁木齐市某某商行'''

ALIPAY_TEXT = '''支付宝
转账成功
金额 1,500.00 元
创建时间 2026-10-25 09:08:07
交易号 2026102522001234567890
收款方 张三
付款方 李四'''

BANK_TEXT = '''中国建设银行 转账回单
转账金额：人民币 8,000.00 元
交易时间：2026-10-24 10:20
流水号：6217000010001234567
付款人：昌吉市洋帆豆制品厂
收款人：乌鲁木齐市某某商行'''


class ReceiptOcrParserTests(unittest.TestCase):
    def test_tls_context_has_trusted_roots(self):
        self.assertGreater(receipt_ocr._TLS_CONTEXT.cert_store_stats()['x509'], 0)

    def test_wechat_receipt_fields(self):
        fields, warnings = receipt_ocr.extract_fields(WECHAT_TEXT)
        fields, warnings, confidence, status, message = receipt_ocr._finalize(fields, warnings)
        self.assertEqual(fields['amount_cents'], 128000)
        self.assertEqual(fields['occurred_at'], '2026-10-26T14:32:18+08:00')
        self.assertEqual(fields['transaction_no'], '1000050001202610261234567890')
        self.assertEqual(fields['payer'], '昌吉市洋帆豆制品厂')
        self.assertEqual(fields['payee'], '乌鲁木齐市某某商行')
        self.assertEqual(fields['method'], '微信收款')
        self.assertEqual(fields['direction'], 'in')
        self.assertGreaterEqual(confidence, 80)
        self.assertEqual(status, 'recognized')
        self.assertFalse([w for w in warnings if '金额' in w])

    def test_alipay_and_bank_receipts(self):
        alipay, _ = receipt_ocr.extract_fields(ALIPAY_TEXT)
        self.assertEqual(alipay['amount_cents'], 150000)
        self.assertEqual(alipay['transaction_no'], '2026102522001234567890')
        self.assertEqual(alipay['method'], '支付宝')
        self.assertEqual(alipay['payer'], '李四')
        self.assertEqual(alipay['payee'], '张三')
        bank, _ = receipt_ocr.extract_fields(BANK_TEXT)
        self.assertEqual(bank['amount_cents'], 800000)
        self.assertEqual(bank['transaction_no'], '6217000010001234567')
        self.assertEqual(bank['method'], '银行转账')
        self.assertEqual(bank['payer'], '昌吉市洋帆豆制品厂')
        self.assertEqual(bank['payee'], '乌鲁木齐市某某商行')

    def test_balance_and_unlabelled_amounts_are_not_mistaken(self):
        text = '微信零钱余额 ¥9,999.00\n转账金额 ¥100.00\n转账时间 2026-10-26 08:00:00'
        fields, _ = receipt_ocr.extract_fields(text)
        self.assertEqual(fields['amount_cents'], 10000)
        text = '零钱余额 ¥9,999.00\n可用额度 ¥5,000.00\n转账时间 2026-10-26 08:00:00'
        fields, warnings = receipt_ocr.extract_fields(text)
        fields, warnings, confidence, status, message = receipt_ocr._finalize(fields, warnings)
        self.assertIsNone(fields['amount_cents'])
        self.assertIn(status, ('recognized', 'failed'))
        self.assertTrue(any('金额' in w for w in warnings))

    def test_standalone_signed_amount_and_canonical_transaction(self):
        fields, _ = receipt_ocr.extract_fields('+1,234.50\n2026/10/24 09:30\n交易单号：ABC-123-456')
        self.assertEqual(fields['amount_cents'], 123450)
        self.assertEqual(fields['occurred_at'], '2026-10-24T09:30:00+08:00')
        self.assertEqual(receipt_ocr.normalize_tx('ABC-123-456'), 'ABC123456')
        self.assertEqual(receipt_ocr.normalize_tx('abc 123 456'), 'ABC123456')

    def test_payment_screenshots_are_flagged_not_receipts(self):
        text = '''账单详情
淘宝平台商户
-158.00
支付成功
支付时间 2026年10月22日 13:36:44
商户简称 淘宝平台商户
支付方式 零钱
交易单号 4500000581202610225685436143
发起群收款'''
        fields, warnings = receipt_ocr.extract_fields(text)
        fields, warnings, confidence, status, message = receipt_ocr._finalize(fields, warnings)
        self.assertEqual(fields['amount_cents'], 15800)
        self.assertEqual(fields['direction'], 'out')
        self.assertEqual(fields['method'], '微信收款')
        self.assertEqual(fields['payee'], '淘宝平台商户')
        self.assertFalse(any('未识别到金额' in w for w in warnings))
        self.assertTrue(any('付款/转出' in w for w in warnings))
        text = '''收支详情
+8,579.55
余额: 8,836.12
交易时间 2026-09-07 18:16:17
交易金额 8,579.55'''
        fields, _ = receipt_ocr.extract_fields(text)
        self.assertEqual(fields['amount_cents'], 857955)
        self.assertEqual(fields['direction'], 'in')
        self.assertEqual(receipt_ocr._parse_amount(text)[0], 857955)

    def test_payment_method_is_not_mistaken_for_payer(self):
        text = '''账单详情
-2.00
交易成功
支付时间 2026-09-23 14:36:22
付款方式 工商银行储蓄卡(3015)
订单号 2026092323001430711426869759'''
        fields, _ = receipt_ocr.extract_fields(text)
        self.assertEqual(fields['direction'], 'out')
        self.assertEqual(fields['method'], '银行转账')
        self.assertIsNone(fields['payer'])
        self.assertEqual(fields['transaction_no'], '2026092323001430711426869759')

    def test_model_values_cannot_override_ocr_values(self):
        fields, warnings = receipt_ocr.extract_fields(WECHAT_TEXT)
        fields, warnings, confidence, status, message = receipt_ocr._finalize(fields, warnings)
        before = fields['amount_cents']
        receipt_ocr._merge_model(fields, warnings, {
            'amount': '9999.00', 'occurred_at': '2020-01-01T00:00:00+08:00',
            'transaction_no': 'FAKE0000000000', 'payer': '模型编造', 'payee': '乌鲁木齐市某某商行'})
        self.assertEqual(fields['amount_cents'], before)
        self.assertTrue(warnings)
        self.assertEqual(fields['payee'], '乌鲁木齐市某某商行')


class ReceiptEvidenceHTTPTests(AuthHTTPFixture):
    def setUp(self):
        super().setUp()
        self.warehouse = self.user('ocrwarehouse', '库管')[0]
        self.accountant = self.user('ocraccountant', '会计')[0]
        self.cashier = self.user('ocrcashier', '出纳')[0]
        code, self.settings, _ = self.admin.request('/api/receipt-ocr/settings', {
            'provider': 'off', 'base_url': '', 'model': '', 'timeout': 35,
            'api_key': '', 'clear_key': True})
        self.assertEqual(code, 200, self.settings)
        self.assertEqual(self.settings['provider'], 'off')
        self.assertFalse(self.settings['available'])

    def _order(self, suffix):
        order = {
            'id': 'SO-OCR-' + suffix, 'customer_id': 'C001', 'customer_name': '演示·乌鲁木齐一店',
            'business_date': '2026-10-21', 'state': 'reviewed', 'total_cents': 150000,
            'paid_cents': 0, 'discount_cents': 0, 'rounding_cents': 0, 'version': 1,
            'lines': [{'product_id': 'P003', 'product_name': '白豆干', 'bill_qty': 20,
                       'billing_unit': '筐', 'price': '75', 'amount_cents': 150000}],
        }
        with erp.connect(True) as c:
            c.execute('INSERT INTO orders(id,payload) VALUES(?,?)', (order['id'], json.dumps(order)))
        return order

    def _recognize(self, image, order_id, filename='shot.png'):
        return self.cashier.request('/api/receipt-evidence/recognize', {
            'image_base64': base64.b64encode(image).decode(), 'mime': 'image/png',
            'filename': filename, 'order_id': order_id})

    def _receipt(self, order, evidence_id='', transaction_no='', amount='1500', confirmed=False):
        body = {'version': order['version'], 'amount': amount, 'discount': '0', 'rounding': '0',
                'received_date': '2026-10-26', 'method': '微信收款', 'note': '截图登记'}
        if evidence_id:
            body['evidence_id'] = evidence_id
        if transaction_no:
            body['transaction_no'] = transaction_no
        if confirmed:
            body['evidence_confirmed'] = True
        return self.cashier.request('/api/orders/' + order['id'] + '/receipt', body)

    def test_settings_are_admin_only_and_never_return_the_key(self):
        self.assertEqual(self.cashier.request('/api/receipt-ocr/settings')[0], 403)
        self.assertEqual(self.accountant.request('/api/receipt-ocr/settings')[0], 403)
        code, saved, _ = self.admin.request('/api/receipt-ocr/settings', {
            'provider': 'openai', 'base_url': 'https://example.com/v1', 'model': 'qwen-vl-plus',
            'timeout': 40, 'api_key': 'sk-test-12345678', 'clear_key': False})
        self.assertEqual(code, 200, saved)
        self.assertTrue(saved['key_configured'])
        self.assertEqual(saved['key_hint'][-4:], '5678')
        self.assertNotIn('sk-test-12345678', json.dumps(saved))
        code, public, _ = self.admin.request('/api/receipt-ocr/settings')
        self.assertEqual(code, 200, public)
        self.assertNotIn('api_key', public)
        self.assertIn('finance.evidence', erp_access.defaults('会计')['actions'])
        self.assertIn('finance.evidence', erp_access.defaults('出纳')['actions'])

    def test_upload_evidence_link_receipt_and_verify_size(self):
        order = self._order('LINK')
        image = _png()
        code, evidence, _ = self._recognize(image, order['id'])
        self.assertEqual(code, 200, evidence)
        self.assertEqual(evidence['status'], 'failed')
        self.assertEqual(evidence['order_id'], order['id'])
        self.assertTrue(evidence['has_image'])
        code, again, _ = self._recognize(image, order['id'])
        self.assertEqual(code, 200, again)
        self.assertEqual(again['id'], evidence['id'])
        self.assertTrue(again['duplicate'])
        code, meta, _ = self.accountant.request('/api/receipt-evidence/' + evidence['id'])
        self.assertEqual(code, 200, meta)
        self.assertEqual(meta['id'], evidence['id'])
        self.assertEqual(self.warehouse.request('/api/receipt-evidence/' + evidence['id'])[0], 403)
        code, image_bytes, headers = self.cashier.request('/api/receipt-evidence/' + evidence['id'] + '/image')
        self.assertEqual(code, 200)
        self.assertEqual(headers.get_content_type(), 'image/png')
        self.assertTrue(image_bytes.startswith(b'\x89PNG'))
        code, result, _ = self._receipt(order, evidence['id'], 'OCR-TX-001')
        self.assertEqual(code, 200, result)
        with erp.connect() as c:
            receipt = json.loads(c.execute("SELECT payload FROM receipts WHERE json_extract(payload,'$.evidence_id')=?", (evidence['id'],)).fetchone()[0])
        self.assertEqual(receipt['evidence_id'], evidence['id'])
        self.assertEqual(receipt['transaction_no'], 'OCR-TX-001')
        code, ledger, _ = self.cashier.request('/api/receivables?all=1&clearance=all&page_size=50')
        self.assertEqual(code, 200, ledger)
        projected = [r for r in ledger['receipts'] if r['id'] == receipt['id']]
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]['evidence_id'], evidence['id'])
        self.assertEqual(projected[0]['transaction_no'], 'OCR-TX-001')
        code, linked, _ = self.cashier.request('/api/receipt-evidence/' + evidence['id'])
        self.assertEqual(linked['status'], 'linked')
        self.assertEqual(linked['linked_receipt_id'], receipt['id'])
        second = self._order('SECOND')
        self.assertEqual(self._receipt(second, evidence['id']) [0], 400)
        self.assertEqual(self._receipt(second, '', 'OCR-TX-001')[0], 400)

    def test_amount_mismatch_requires_explicit_confirm_and_order_scope(self):
        first = self._order('SCOPE-A')
        second = self._order('SCOPE-B')
        image = _png(601)
        code, evidence, _ = self._recognize(image, first['id'])
        self.assertEqual(code, 200, evidence)
        with erp.connect(True) as c:
            fields = json.loads(c.execute('SELECT fields_json FROM receipt_evidence WHERE id=?', (evidence['id'],)).fetchone()[0])
            fields['amount_cents'] = 128000
            fields['method'] = '微信收款'
            c.execute("UPDATE receipt_evidence SET fields_json=?,status='recognized' WHERE id=?", (json.dumps(fields), evidence['id']))
        self.assertEqual(self._receipt(second, evidence['id'], amount='1280')[0], 400)
        self.assertEqual(self._receipt(first, evidence['id'], amount='1300')[0], 400)
        self.assertEqual(self._receipt(first, evidence['id'], amount='1300', confirmed=True)[0], 200)

    def test_image_validation_duplicate_image_and_order_scope(self):
        first = self._order('VALID-A')
        second = self._order('VALID-B')
        code, value, _ = self.cashier.request('/api/receipt-evidence/recognize', {
            'image_base64': base64.b64encode(b'GIF89a' + b'0' * 200).decode(),
            'mime': 'image/gif', 'filename': 'x.gif'})
        self.assertEqual(code, 400, value)
        code, value, _ = self.cashier.request('/api/receipt-evidence/recognize', {
            'image_base64': base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 700000).decode(),
            'mime': 'image/png', 'filename': 'big.png'})
        self.assertEqual(code, 400, value)
        image = _png(602)
        code, evidence, _ = self._recognize(image, first['id'])
        self.assertEqual(code, 200, evidence)
        code, other, _ = self._recognize(_png(603), second['id'])
        self.assertEqual(code, 200, other)
        self.assertEqual(self._receipt(second, evidence['id'])[0], 400)
        self.assertEqual(self.cashier.request('/api/receipt-evidence/' + 'EV-NOPE')[0], 404)


if __name__ == '__main__':
    unittest.main()
