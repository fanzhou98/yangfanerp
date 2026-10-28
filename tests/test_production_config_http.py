import unittest
from datetime import date, timedelta
import test_auth_http as fixture
import production_config as pc


class ProductionConfigHTTPTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    personal_password = fixture.AuthHTTPTests.personal_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown
    user = fixture.AuthHTTPTests.user

    def test_publish_role_csrf_epoch_and_stale_version(self):
        with fixture.erp.connect() as c:
            cfg = pc.get(c)
        body = {'version': cfg['version'], 'effective_date': (date.today() + timedelta(days=1)).isoformat(), 'config': cfg, 'note': '目录发布验收'}
        for name, role in [('config_dir', '厂长'), ('config_acc', '会计'), ('config_wh', '库管'), ('config_owner', '老板')]:
            client, _ = self.user(name, role)
            self.assertEqual(client.request('/api/factory/production-config', body)[0], 403)
        self.assertEqual(self.admin.request('/api/factory/production-config', body, csrf=False)[0], 403)
        self.assertEqual(self.admin.request('/api/factory/production-config', body, headers={'X-ERP-Data-Epoch':'stale'})[0], 400)
        code, value, _ = self.admin.request('/api/factory/production-config', body)
        self.assertEqual(code, 200, value)
        self.assertEqual(value['version'], cfg['version']+1)
        self.assertEqual(self.admin.request('/api/factory/production-config', body)[0], 400)
        driver, _ = self.user('config_driver', '司机')
        bootstrap = driver.request('/api/bootstrap')[1]
        self.assertFalse(bootstrap['resources'].get('production_configs'))
        self.assertEqual(driver.request('/api/factory/report?kind=system-settings')[0], 403)
