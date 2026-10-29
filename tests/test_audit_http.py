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
            c.execute("INSERT INTO archived_orders(id,payload,kept_id,reason,archived_at) VALUES(?,?,?,?,?)",
                      ('SO-HTTP', '{"order":{"business_date":"2026-10-03","customer_name":"客户甲"}}', 'SO-KEEP', '重复订货', '2026-10-03T11:00:00+08:00'))
            c.execute("INSERT INTO trial_archives(id,payload,at,reason,restored_at) VALUES(?,?,?,?,?)",
                      ('T-ROUND', '{"format":"round-v1","business_date":"2026-10-01","counts":{"orders":2}}', '2026-10-01T10:00:00+08:00', '整轮归档', ''))
            c.execute("INSERT INTO trial_archives(id,payload,at,reason,restored_at) VALUES(?,?,?,?,?)",
                      ('T-DAY', '{"format":"day-reset-v1","business_date":"2026-10-02","counts":{"orders":1}}', '2026-10-02T10:00:00+08:00', '按日清理', ''))

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
        self.assertEqual(warehouse.request('/api/archive-records?kind=order&all=1')[0], 403)
        code, archives, _ = self.admin.request('/api/archive-records?kind=order&all=1')
        self.assertEqual(code, 200, archives); self.assertEqual(archives['total'], 1)
        self.assertEqual(archives['rows'][0]['customer_name'], '客户甲')
        code, events, _ = self.admin.request('/api/security-events?start=2026-10-01&end=2026-10-01')
        self.assertEqual(code, 200, events); self.assertEqual(events['total'], 1); self.assertEqual(events['rows'][0]['action'], 'login.failed')

    def test_bootstrap_no_longer_projects_security_history(self):
        self.seed()
        code, body, _ = self.admin.request('/api/bootstrap')
        self.assertEqual(code, 200, body)
        self.assertNotIn('security_events', body)
        self.assertNotIn('archived_orders', body)
        self.assertEqual([r['id'] for r in body.get('trial_archives', [])], ['T-DAY'])
