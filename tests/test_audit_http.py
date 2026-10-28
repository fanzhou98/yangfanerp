"""Q04 audit history HTTP: system.audit gate, filters and JSON shape."""
import unittest
from datetime import datetime
import test_auth_http as fixture

erp = fixture.erp


class AuditHTTPTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    personal_password = fixture.AuthHTTPTests.personal_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown
    user = fixture.AuthHTTPTests.user

    def seed(self):
        with erp.connect(True) as c:
            c.execute('DELETE FROM audit'); c.execute('DELETE FROM security_events')
            for at, action in [('2026-10-01T09:00:00+08:00', '确认实发'), ('2026-10-02T09:00:00+08:00', '登记收款')]:
                c.execute("INSERT INTO audit(at,role,action,entity,actor_id,actor_name,request_id) VALUES(?,?,?,?,?,?,?)",
                          (at, '会计', action, 'SO-T', 'U1', '王会计', 'REQ-T'))
            c.execute("INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)",
                      (int(datetime.fromisoformat('2026-10-01T09:00:00+08:00').timestamp()), 'login.failed', 'U9', 'auth', '{}'))

    def test_admin_sees_paginated_audit_and_management_routes_require_module(self):
        self.seed()
        code, body, _ = self.admin.request('/api/audit?start=2026-10-01&end=2026-10-31&page_size=1&page=2')
        self.assertEqual(code, 200, body); self.assertEqual(body['total'], 2); self.assertEqual(body['pages'], 2)
        self.assertEqual(body['rows'][0]['action'], '确认实发')
        code, body, _ = self.admin.request('/api/audit?start=2026/10/01')
        self.assertEqual(code, 400, body)
        warehouse, _ = self.user('auditwarehouse', '库管')
        self.assertEqual(warehouse.request('/api/audit')[0], 403)
        self.assertEqual(warehouse.request('/api/security-events')[0], 403)
        code, events, _ = self.admin.request('/api/security-events?start=2026-10-01&end=2026-10-01')
        self.assertEqual(code, 200, events); self.assertEqual(events['total'], 1); self.assertEqual(events['rows'][0]['action'], 'login.failed')
