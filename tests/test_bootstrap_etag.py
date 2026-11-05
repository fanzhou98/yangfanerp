"""bootstrap 条件请求：数据未变返回 304，任何写事务都会让 ETag 失效。"""
from test_auth_http import AuthHTTPFixture


class BootstrapETagTests(AuthHTTPFixture):
    def bootstrap(self, headers=None):
        return self.admin.request('/api/bootstrap', headers={'X-ERP-Expense-History': 'deferred',
                                                             'X-ERP-Byproduct-History': 'deferred',
                                                             **(headers or {})})

    def test_first_read_returns_etag_and_second_read_is_304(self):
        code, body, headers = self.bootstrap()
        self.assertEqual(code, 200)
        etag = headers.get('ETag')
        self.assertTrue(etag, 'bootstrap 必须返回 ETag')
        code, body, headers = self.bootstrap({'If-None-Match': etag})
        self.assertEqual((code, body), (304, b''))
        self.assertEqual(headers.get('ETag'), etag)

    def test_deferred_and_full_history_use_different_etags(self):
        _, _, deferred = self.bootstrap()
        code, _, full_headers = self.admin.request('/api/bootstrap', headers={'X-ERP-Expense-History': 'full',
                                                                             'X-ERP-Byproduct-History': 'deferred'})
        self.assertEqual(code, 200)
        self.assertNotEqual(deferred.get('ETag'), full_headers.get('ETag'))

    def test_write_invalidates_etag(self):
        _, _, headers = self.bootstrap()
        etag = headers['ETag']
        with self.erp_connect() as c:
            c.execute("UPDATE customers SET note=note WHERE id=(SELECT id FROM customers LIMIT 1)")
        code, body, headers = self.bootstrap({'If-None-Match': etag})
        self.assertEqual(code, 200)
        self.assertNotEqual(headers.get('ETag'), etag)
        self.assertTrue(body)

    def erp_connect(self):
        from test_auth_http import erp
        return erp.connect(True)
