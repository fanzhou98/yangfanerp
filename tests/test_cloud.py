"""Production WSGI security boundary and release isolation, with a fresh DB."""
import io
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auth
import cloud_app
from ops.build_release import release_files
from ops.build_release import ROOT
from ops.cloud.prepare_release import prepare
import server


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB
        self.db = Path(self.temp.name) / 'cloud.db'
        server.DB = self.db
        server.init_db(demo=False)
        with server.connect(True) as c:
            auth.create_initial_admin(c, 'cloudadmin', '测试管理员',
                                      'Test-Cloud-Only-2026!', int(time.time()))
        self.origin = 'https://203.0.113.20'
        self.app = cloud_app.create_application(self.db, self.origin)

    def tearDown(self):
        server.DB = self.old_db
        self.temp.cleanup()

    def request(self, path, body=None, headers=None, scheme='https', ip='198.51.100.2', method=None):
        env = {}
        setup_testing_defaults(env)
        raw = json.dumps(body).encode() if body is not None else b''
        env.update(PATH_INFO=path, REQUEST_METHOD=method or ('POST' if body is not None else 'GET'),
                   HTTP_HOST='203.0.113.20', REMOTE_ADDR=ip, CONTENT_LENGTH=str(len(raw)),
                   CONTENT_TYPE='application/json', HTTP_X_ERP_CLIENT='local-pilot')
        env['wsgi.url_scheme'] = scheme
        env['wsgi.input'] = io.BytesIO(raw)
        env.update(headers or {})
        response = {}
        def start(status, values):
            response.update(code=int(status.split()[0]), headers=values)
        response['body'] = b''.join(self.app(env, start))
        return response

    def login(self):
        return self.request('/api/auth/login', {'username': 'cloudadmin', 'password': 'Test-Cloud-Only-2026!'},
                            {'HTTP_ORIGIN': self.origin})

    def test_empty_business_database_and_no_default_password(self):
        with server.connect() as c:
            for table in ('customers', 'products', 'orders', 'receipts', 'purchase_orders'):
                self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        self.assertEqual(self.request('/api/bootstrap')['code'], 401)

    def test_host_and_tls_required_even_for_static_page(self):
        self.assertEqual(self.request('/')['code'], 200)
        self.assertEqual(self.request('/', scheme='http')['code'], 403)
        self.assertEqual(self.request('/', headers={'HTTP_HOST':'attacker.example'})['code'], 403)
        self.assertEqual(self.request('/', headers={'HTTP_HOST':'203.0.113.20.attacker.example'})['code'], 403)

    def test_local_probe_exception_does_not_allow_business_or_external_access(self):
        local = {'HTTP_HOST': '127.0.0.1:8765'}
        self.assertEqual(self.request('/api/health', headers=local, scheme='http', ip='127.0.0.1')['code'], 200)
        self.assertEqual(self.request('/api/bootstrap', headers=local, scheme='http', ip='127.0.0.1')['code'], 403)
        self.assertEqual(self.request('/api/health', headers=local, scheme='http')['code'], 403)

    def test_login_rejects_cross_origin_and_null_origin(self):
        body = {'username':'cloudadmin', 'password':'Test-Cloud-Only-2026!'}
        for origin in ('https://attacker.example', 'null', 'http://203.0.113.20'):
            self.assertEqual(self.request('/api/auth/login', body, {'HTTP_ORIGIN':origin})['code'], 400)

    def test_login_secure_cookie_and_authenticated_bootstrap(self):
        login = self.login()
        self.assertEqual(login['code'], 200)
        cookies = [v for k,v in login['headers'] if k == 'Set-Cookie']
        self.assertEqual(len(cookies), 2)
        for cookie in cookies:
            self.assertIn('; Secure', cookie)
            self.assertIn('SameSite=Strict', cookie)
        self.assertIn('HttpOnly', cookies[0])
        cookie_header = '; '.join(c.split(';')[0] for c in cookies)
        response = self.request('/api/bootstrap', headers={'HTTP_COOKIE':cookie_header})
        self.assertEqual(response['code'], 200)
        self.assertEqual(json.loads(response['body'])['auth_user']['username'], 'cloudadmin')
        # POST still needs CSRF despite a valid session and correct origin.
        response = self.request('/api/auth/logout', {}, {'HTTP_COOKIE':cookie_header, 'HTTP_ORIGIN':self.origin})
        self.assertEqual(response['code'], 403)

    def test_unsupported_methods_and_head(self):
        self.assertEqual(self.request('/', method='DELETE')['code'], 405)
        response = self.request('/', method='HEAD')
        self.assertEqual(response['code'], 200)
        self.assertEqual(response['body'], b'')
        self.assertGreater(int(dict(response['headers'])['Content-Length']), 0)

    def test_public_origin_is_explicit_https_without_path(self):
        for value in ('http://example.com', 'https://example.com/', 'https://user@example.com',
                      'https://example.com?x=1', 'https://example.com:bad', 'https://EXAMPLE.com'):
            with self.assertRaises(ValueError):
                cloud_app.validate_origin(value)

    def test_release_contains_no_local_data_or_historical_documents(self):
        files = release_files()
        self.assertIn(Path('cloud_app.py'), files)
        # Bookmark icons are the only intentional PNGs in a release. Screenshots,
        # local images and generated documents must still be rejected.
        bookmark_icons = {Path('web/favicon-16x16.png'), Path('web/favicon-32x32.png'),
                          Path('web/apple-touch-icon.png'), Path('web/icon-192.png'),
                          Path('web/icon-512.png'), Path('web/icon-maskable-512.png')}
        for path in files:
            self.assertNotIn(path.parts[0], ('data', 'docs', 'tests', 'output'))
            self.assertNotIn('__pycache__', path.parts)
            self.assertNotIn(path.suffix, ('.db', '.log', '.pyc'))
            if path.suffix == '.png':
                self.assertIn(path, bookmark_icons)

    def test_complete_release_includes_migrations_and_can_be_prepared(self):
        files = release_files()
        required = {'migrations.py', 'migration_steps.py', 'ops/migrate.py', 'ops/build_release.py'}
        self.assertTrue(required <= {str(p) for p in files})
        source = Path(self.temp.name) / 'release'
        source.mkdir()
        digests = {}
        for path in files:
            raw = (ROOT / path).read_bytes()
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            digests[str(path)] = hashlib.sha256(raw).hexdigest()
        (source / 'release.json').write_text(json.dumps({'version': '0.43.0', 'data_included': False, 'files': digests}))
        destination = Path(self.temp.name) / 'installed'
        target = prepare(source, destination)
        for name in required:
            self.assertEqual((target / name).read_bytes(), (ROOT / name).read_bytes())
        # An unpacked release must prepare itself without the source workspace.
        output = subprocess.check_output([sys.executable, str(target / 'ops/cloud/prepare_release.py'), str(source), str(destination / 'again')], cwd=self.temp.name)
        self.assertTrue(Path(output.decode().strip()).is_dir())


if __name__ == '__main__':
    unittest.main()
