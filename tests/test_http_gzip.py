"""JSON 响应按 Accept-Encoding 协商 gzip，不声明时字节与响应头不变。"""
import gzip, json, unittest, urllib.request
import test_auth_http as fixture

erp = fixture.erp


class GzipResponseTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown

    def fetch(self, path, accept=None):
        headers = {'X-ERP-Client': 'local-pilot', 'X-ERP-Role': 'accountant', 'Origin': self.url,
                   'Cookie': '; '.join(f'{k}={v}' for k, v in self.admin.cookies.items())}
        if accept: headers['Accept-Encoding'] = accept
        with urllib.request.urlopen(urllib.request.Request(self.url + path, headers=headers), timeout=15) as response:
            return response, response.read()

    def test_gzip_roundtrips_and_shrinks_bootstrap(self):
        plain_response, plain = self.fetch('/api/bootstrap')
        self.assertIsNone(plain_response.headers.get('Content-Encoding'))
        self.assertGreater(len(plain), 20_000)
        response, packed = self.fetch('/api/bootstrap', 'gzip')
        self.assertEqual(response.headers.get('Content-Encoding'), 'gzip')
        self.assertIn('Accept-Encoding', response.headers.get('Vary', ''))
        self.assertLess(len(packed), int(len(plain) * 0.6), (len(packed), len(plain)))
        self.assertEqual(json.loads(gzip.decompress(packed)), json.loads(plain))

    def test_small_body_not_compressed_even_when_offered(self):
        response, packed = self.fetch('/api/health', 'gzip')
        self.assertIsNone(response.headers.get('Content-Encoding'))
        self.assertEqual(json.loads(packed), {'status': 'ok'})

    def test_identity_client_sees_plain_json(self):
        response, body = self.fetch('/api/bootstrap', 'identity')
        self.assertIsNone(response.headers.get('Content-Encoding'))
        self.assertEqual(int(response.headers.get('Content-Length')), len(body))
        self.assertTrue(body.startswith(b'{'))
