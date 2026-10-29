"""Q04 audit history: date window, filters, pagination and index use."""
from datetime import datetime
import json
import unittest
import audit_query
import test_workflow as fixture

erp = fixture.erp


class AuditQueryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowTests(); self.old = erp.DB; self.case.setUp()
        with erp.connect(True) as c:
            c.execute('DELETE FROM audit'); c.execute('DELETE FROM security_events')
            rows = [
                ('2026-09-01T09:00:00+08:00', '会计', '确认结算', 'SO-1', 'U1', '王会计', 'REQ-1'),
                ('2026-10-01T10:00:00+08:00', '库管', '确认实发', 'SO-2', 'U2', '李库管', 'REQ-2'),
                ('2026-10-02T11:00:00+08:00', '会计', '登记收款', 'SO-3', 'U1', '王会计', 'REQ-3'),
            ]
            for at, role, action, entity, actor, name, req in rows:
                c.execute('INSERT INTO audit(at,role,action,entity,actor_id,actor_name,request_id) VALUES(?,?,?,?,?,?,?)',
                          (at, role, action, entity, actor, name, req))
            c.execute("INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)",
                      (int(datetime.fromisoformat('2026-10-01T10:00:00+08:00').timestamp()), 'login.failed', 'U9', 'auth', '{}'))
            c.execute("INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)",
                      (int(datetime.fromisoformat('2026-09-02T10:00:00+08:00').timestamp()), 'password.changed', 'U1', 'auth', '{}'))
            c.execute("INSERT INTO trial_archives(id,payload,at,reason,restored_at) VALUES(?,?,?,?,?)",
                      ('T-1',json.dumps({'format':'round-v1','business_date':'2026-09-15','counts':{'orders':3,'receipts':1}},ensure_ascii=False),'2026-09-16T09:00:00+08:00','试运行归档',''))
            c.execute("INSERT INTO trial_archives(id,payload,at,reason,restored_at) VALUES(?,?,?,?,?)",
                      ('T-DAY',json.dumps({'format':'day-reset-v1','business_date':'2026-10-02','counts':{'orders':1}},ensure_ascii=False),'2026-10-02T10:00:00+08:00','按日清理',''))
            c.execute("INSERT INTO archived_orders(id,payload,kept_id,reason,archived_at) VALUES(?,?,?,?,?)",
                      ('SO-OLD',json.dumps({'order':{'business_date':'2026-10-03','customer_name':'客户甲'}},ensure_ascii=False),'SO-KEEP','重复订货','2026-10-03T11:00:00+08:00'))
            c.execute('CREATE INDEX IF NOT EXISTS audit_at_id ON audit(at,id)')

    def tearDown(self):
        self.case.tearDown(); erp.DB = self.old

    def test_history_range_filters_summary_and_stable_pages(self):
        with erp.connect() as c:
            r = audit_query.history(c, start='2026-10-01', end='2026-10-31', page_size=1)
            self.assertEqual(r['total'], 2); self.assertEqual(r['pages'], 2); self.assertEqual(r['page'], 1)
            self.assertEqual(r['rows'][0]['action'], '登记收款'); self.assertEqual(r['summary']['actors'], 2)
            self.assertEqual(r['roles'], ['会计', '库管'])
            r2 = audit_query.history(c, start='2026-10-01', end='2026-10-31', page_size=1, page=2)
            self.assertEqual(r2['rows'][0]['action'], '确认实发')
            self.assertEqual(audit_query.history(c, start='2026-10-01', end='2026-10-31', role='会计', search='王会计')['total'], 1)
            self.assertEqual(audit_query.history(c, start='2026-10-01', end='2026-10-31', entity='SO-2')['total'], 1)
            self.assertEqual(audit_query.history(c, all_dates=True)['total'], 3)

    def test_history_rejects_bad_ranges_and_pages(self):
        with erp.connect() as c:
            with self.assertRaisesRegex(ValueError, '开始日期'):
                audit_query.history(c, start='2026-10-02', end='2026-10-01')
            with self.assertRaisesRegex(ValueError, '页码'):
                audit_query.history(c, page=0)
            with self.assertRaisesRegex(ValueError, '日期格式'):
                audit_query.history(c, start='2026/10/01')
            with self.assertRaisesRegex(ValueError, '全部日期'):
                audit_query.history(c, all_dates=True, start='2026-10-01')

    def test_security_range_search_and_pages(self):
        with erp.connect() as c:
            r = audit_query.security(c, start='2026-10-01', end='2026-10-31')
            self.assertEqual(r['total'], 1); self.assertEqual(r['rows'][0]['action'], 'login.failed')
            self.assertEqual(audit_query.security(c, all_dates=True, search='password')['total'], 1)
            self.assertEqual(audit_query.security(c, all_dates=True, page_size=1, page=2)['rows'][0]['action'], 'password.changed')

    def test_audit_date_query_can_use_index(self):
        with erp.connect() as c:
            plan = c.execute('EXPLAIN QUERY PLAN SELECT id FROM audit WHERE at>=? AND at<? ORDER BY at DESC,id DESC', ('2026-10-01', '2026-11-01')).fetchall()
            self.assertIn('audit_at_id', ' '.join(str(x) for row in plan for x in row))

    def test_archive_history_filters_and_pages(self):
        with erp.connect() as c:
            trial = audit_query.archives(c, 'trial', all_dates=True)
            self.assertEqual(trial['total'], 1)
            self.assertEqual(trial['rows'][0]['business_date'], '2026-09-15')
            self.assertEqual(trial['rows'][0]['counts']['orders'], 3)
            order = audit_query.archives(c, 'order', start='2026-10-01', end='2026-10-31', search='客户甲')
            self.assertEqual(order['total'], 1)
            self.assertEqual(order['rows'][0]['kept_id'], 'SO-KEEP')
            self.assertEqual(audit_query.archives(c, 'order', all_dates=True, search='不存在')['total'], 0)
            with self.assertRaises(ValueError):
                audit_query.archives(c, 'unknown')
