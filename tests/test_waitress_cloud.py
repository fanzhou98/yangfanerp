"""Real HTTP parsing and proxy boundary, only when cloud dependency is installed."""
import json
import http.client
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloud_app
import server
try:
    from waitress import create_server
except ImportError:
    create_server = None


@unittest.skipIf(create_server is None, 'run with the cloud virtual environment')
class WaitressTests(unittest.TestCase):
    def setUp(self):
        self.previous_db = server.DB
        self.temp = tempfile.TemporaryDirectory()
        server.DB = Path(self.temp.name) / 'real-http.db'
        server.init_db(demo=False)
        application = cloud_app.create_application(server.DB, 'https://203.0.113.20')
        self.service = create_server(application, host='127.0.0.1', port=0, threads=4,
                                     max_request_body_size=server.driver_portal.PHOTO_REQUEST_MAX,
                                     trusted_proxy='127.0.0.1', trusted_proxy_count=1,
                                     trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto'},
                                     clear_untrusted_proxy_headers=True, expose_tracebacks=False)
        self.closing = threading.Event()
        def run():
            try:
                self.service.run()
            except OSError:
                if not self.closing.is_set():
                    raise
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.service.effective_port)

    def tearDown(self):
        self.closing.set()
        self.service.task_dispatcher.shutdown()
        self.service.close()
        self.thread.join(timeout=3)
        server.DB = self.previous_db
        self.temp.cleanup()

    def request(self, path, headers=None, body=None):
        outgoing = {'Host':'203.0.113.20', 'X-Forwarded-Proto':'https', 'X-Forwarded-For':'198.51.100.2'}
        outgoing.update(headers or {})
        req = urllib.request.Request(self.url + path, headers=outgoing, data=body)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read()

    def test_real_proxy_static_auth_and_size_limit(self):
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/api/bootstrap')[0], 401)
        self.assertEqual(self.request('/', {'X-Forwarded-Proto':'http'})[0], 403)
        self.assertEqual(self.request('/', {'Host':'attacker.example'})[0], 403)
        connection = http.client.HTTPConnection('127.0.0.1', self.service.effective_port, timeout=5)
        try:
            connection.request('POST', '/api/auth/login', headers={'Host':'203.0.113.20', 'Content-Length':str(server.driver_portal.PHOTO_REQUEST_MAX+1)})
            self.assertEqual(connection.getresponse().status, 413)
        finally:
            connection.close()

    def test_client_ip_is_validated_at_application_boundary(self):
        # nginx overwrites this header; the application also rejects a malformed
        # address before it can become an authentication rate-limit key.
        # Waitress 3.0.2 may reject this before the application sees REMOTE_ADDR.
        self.assertIn(self.request('/', {'X-Forwarded-For':'[not-an-ip'})[0], (400,403))

    def test_driver_batch_larger_than_old_limits_reaches_authentication(self):
        body=json.dumps({'photos':'x'*(3*1024*1024)}).encode()
        self.assertEqual(self.request('/api/driver/weights',{'Content-Type':'application/json','X-ERP-Client':'local-pilot'},body)[0],401)


if __name__ == '__main__':
    unittest.main()
