"""Real account-mode HTTP boundaries; every test uses an isolated temporary DB."""
from test_workflow import erp
from pathlib import Path
from http.cookies import SimpleCookie
from datetime import date,timedelta
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request


class Client:
    def __init__(self, case):
        self.case = case
        self.cookies = {}

    def request(self, path, body=None, *, csrf=True, role='accountant', headers=None):
        outgoing = {'Content-Type': 'application/json', 'X-ERP-Client': 'local-pilot',
                    'X-ERP-Role': role, 'Origin': self.case.url}
        if self.cookies:
            outgoing['Cookie'] = '; '.join(f'{k}={v}' for k, v in self.cookies.items())
        if csrf and 'erp_csrf' in self.cookies:
            outgoing['X-CSRF-Token'] = self.cookies['erp_csrf']
        outgoing.update(headers or {})
        req = urllib.request.Request(self.case.url + path, headers=outgoing,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            response = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            for line in response.headers.get_all('Set-Cookie', []):
                values = SimpleCookie()
                values.load(line)
                for key, item in values.items():
                    if item.value:
                        self.cookies[key] = item.value
                    else:
                        self.cookies.pop(key, None)
            result = json.loads(raw) if response.headers.get('Content-Type', '').startswith('application/json') else raw
            return response.code, result, response.headers


class AuthHTTPFixture(unittest.TestCase):
    initial_password = 'initial-password-2026'
    personal_password = 'personal-password-2026'

    def setUp(self):
        self.previous_db = erp.DB
        self.tmp = tempfile.TemporaryDirectory()
        erp.DB = Path(self.tmp.name) / 'auth-http.db'
        erp.init_db()
        with erp.connect(True) as c:
            self.admin_user = erp.auth.create_initial_admin(c, 'admin', '系统负责人', self.initial_password, int(time.time()))
            seeded_days={json.loads(row[0])['business_date'] for row in c.execute('SELECT payload FROM orders')}
            test_day=date(2026,10,22)
            while test_day.isoformat() in seeded_days:test_day+=timedelta(days=1)
            self.order_test_day=test_day.isoformat()
        self.server = erp.ThreadingHTTPServer(('127.0.0.1', 0), erp.Handler)
        # No test_pilot flag: this exercises the default real authentication path.
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.admin = Client(self)
        code, body, _ = self.admin.request('/api/auth/login', {'username': 'admin', 'password': self.initial_password})
        self.assertEqual(code, 200, body)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        erp.DB = self.previous_db
        self.tmp.cleanup()

    def user(self, username='warehouse', role='库管', *, change_password=True):
        code, user, _ = self.admin.request('/api/users', {'username': username, 'display_name': '测试' + role,
                                                       'role': role, 'password': self.initial_password, 'active': True})
        self.assertEqual(code, 200, user)
        client = Client(self)
        code, body, _ = client.request('/api/auth/login', {'username': username, 'password': self.initial_password})
        self.assertEqual(code, 200, body)
        if change_password:
            code, body, _ = client.request('/api/auth/password', {'current_password': self.initial_password, 'new_password': self.personal_password})
            self.assertEqual(code, 200, body)
            self.assertFalse(client.cookies)
            code, body, _ = client.request('/api/auth/login', {'username': username, 'password': self.personal_password})
            self.assertEqual(code, 200, body)
            user = body['user']
        return client, user

class AuthHTTPTests(AuthHTTPFixture):
    def test_owner_analysis_and_quality_endpoints_enforce_permissions(self):
        for username,role in [('ownertest','老板'),('whometest','库管'),('acctest','会计'),('cashometest','出纳')]:
            client,_=self.user(username,role)
            status,body,_=client.request('/api/factory/report?kind=owner&date=2026-10-21')
            self.assertEqual(status,200 if role=='老板' else 403)
            if role=='老板':self.assertIn('soy',body);self.assertNotIn('monthly_cents',json.dumps(body))
            status,_,_=client.request('/api/resources/quality',{'id':'missing','version':1,'revision':0,'quality':{'origin':'伊犁'},'note':'测试'})
            self.assertEqual(status,400 if role=='会计' else 403)

    def test_chat_notifications_and_feedback_http(self):
        worker, worker_user = self.user('chatworker', '库管')
        director, director_user = self.user('chatdirector', '厂长')
        code, chat, _ = worker.request('/api/chat')
        self.assertEqual(code, 200, chat)
        self.assertTrue(any(user['id'] == director_user['id'] for user in chat['users']))
        code, thread, _ = worker.request('/api/chat/thread', {'kind': 'direct', 'user_id': director_user['id'], 'request_key': 'http-chat-1'})
        self.assertEqual(code, 200, thread)
        code, sent, _ = worker.request('/api/chat/send', {'thread_id': thread['id'], 'body': '晚上这批豆子分两个库房上', 'request_key': 'http-chat-msg-1'})
        self.assertEqual(code, 200, sent)
        code, messages, _ = director.request('/api/chat/messages?thread_id=' + thread['id'])
        self.assertEqual(code, 200, messages)
        self.assertEqual(messages['messages'][0]['body'], '晚上这批豆子分两个库房上')
        code, inbox, _ = director.request('/api/notifications')
        self.assertEqual(code, 200, inbox)
        self.assertEqual(inbox['unread_count'], 1)
        self.assertEqual(inbox['items'][0]['thread_id'], thread['id'])
        code, read, _ = director.request('/api/chat/read', {'thread_id': thread['id'], 'last_seq': sent['message']['seq']})
        self.assertEqual(code, 200, read)
        self.assertEqual(director.request('/api/notifications')[1]['unread_count'], 0)
        code, ticket, _ = worker.request('/api/feedback', {'category': '功能异常', 'title': '上豆登记缺少记录', 'body': '保存后列表没有显示新登记，请检查', 'request_key': 'http-feedback-1'})
        self.assertEqual(code, 200, ticket)
        code, admin_feedback, _ = self.admin.request('/api/feedback')
        self.assertEqual(code, 200, admin_feedback)
        self.assertTrue(admin_feedback['can_manage'])
        self.assertIn(ticket['id'], [row['id'] for row in admin_feedback['tickets']])
        code, replied, _ = self.admin.request('/api/feedback/reply', {'id': ticket['id'], 'version': ticket['version'], 'body': '已修复，请刷新后重试', 'status': 'replied'})
        self.assertEqual(code, 200, replied)
        code, owner_feedback, _ = worker.request('/api/feedback')
        self.assertEqual(owner_feedback['tickets'][0]['status'], 'replied')
        self.assertEqual(worker.request('/api/notifications')[1]['unread_count'], 1)
        code, other_feedback, _ = director.request('/api/feedback')
        self.assertEqual(code, 200)
        self.assertNotIn(ticket['id'], [row['id'] for row in other_feedback['tickets']])
        self.assertEqual(director.request('/api/feedback/reply', {'id': ticket['id'], 'version': replied['version'], 'body': '越权'})[0], 403)
        with erp.connect(True) as c:
            value = erp.erp_access.defaults('厂长'); value['modules'] = [m for m in value['modules'] if m != 'workspace.chat']
            c.execute("INSERT INTO role_permissions(role,version,payload,updated_at) VALUES('厂长',2,?,?) ON CONFLICT(role) DO UPDATE SET version=excluded.version,payload=excluded.payload,updated_at=excluded.updated_at", (json.dumps(value, ensure_ascii=False), erp.now()))
        self.assertEqual(director.request('/api/chat')[0], 403)

    def test_activity_requires_csrf_and_expired_sessions_cannot_resume(self):
        code, body, _ = self.admin.request('/api/auth/session')
        self.assertEqual(code, 200)
        self.assertEqual(body['session']['idle_timeout_seconds'], 1800)
        sid = body['session']['session_id']
        self.assertEqual(self.admin.request('/api/auth/activity', {}, csrf=False)[0], 403)
        with erp.connect(True) as c:
            c.execute('UPDATE auth_session_activity SET last_activity=? WHERE session_id=?', (int(time.time())-1700, sid))
        self.assertEqual(self.admin.request('/api/auth/activity', {})[0], 200)
        with erp.connect(True) as c:
            c.execute('UPDATE auth_session_activity SET last_activity=? WHERE session_id=?', (int(time.time())-1800, sid))
        for path, body in [('/api/bootstrap',None),('/api/auth/activity',{}),('/api/orders',self.order_body())]:
            self.assertEqual(self.admin.request(path,body)[0],401)

    def order_body(self, **changes):
        return {'customer_id': 'C001', 'business_date': self.order_test_day, 'batch': '账号 HTTP 验证',
                'lines': [{'product_id': 'P004', 'ordered_qty': '2', 'actual_qty': '0',
                           'price': '75', 'driver': [], 'customer': []}], **changes}

    def seed_finance(self):
        order = self.order_body()
        order['lines'][0]['actual_qty'] = '2'
        o = erp.mutate('order', order, '库管')
        o = erp.mutate('settle', {'version': o['version'], 'mode': 'customer'}, '会计', o['id'])
        o = erp.mutate('review', {'version': o['version'], 'evidence_checked': True}, '出纳', o['id'])
        return erp.mutate('receipt', {'version': o['version'], 'amount': '1', 'received_date': '2026-10-22', 'method': '测试收款'}, '出纳', o['id'])

    def test_anonymous_requests_cannot_read_or_mutate_business(self):
        anonymous = Client(self)
        for path in ['/api/bootstrap', '/api/users', '/api/security-events', '/api/export',
                     '/api/customer-statement?customer_id=C001&date=2026-10-22', '/print/orders?date=2026-10-22', '/api/auth/session']:
            code, body, _ = anonymous.request(path)
            self.assertEqual(code, 401, (path, body))
        for path in ['/api/orders', '/api/users', '/api/warehouse', '/api/backup']:
            code, body, _ = anonymous.request(path, self.order_body(), role='warehouse')
            self.assertEqual(code, 401, (path, body))
        self.assertEqual(anonymous.request('/')[0], 200)
        self.assertEqual(anonymous.request('/api/health')[0], 200)

    def test_login_cookies_session_first_password_change_and_logout(self):
        code, body, headers = self.admin.request('/api/auth/login', {'username': 'admin', 'password': self.initial_password})
        self.assertEqual(code, 200)
        self.assertNotIn('token', body)
        self.assertNotIn('csrf_token', body)
        cookies = headers.get_all('Set-Cookie')
        self.assertTrue(any('erp_session=' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie for cookie in cookies))
        code, session, _ = self.admin.request('/api/auth/session')
        self.assertEqual(code, 200)
        self.assertEqual(session['user']['id'], self.admin_user['id'])
        self.assertEqual(session['mode'], 'accounts')
        client, user = self.user(change_password=False)
        self.assertTrue(user['must_change_password'])
        self.assertEqual(client.request('/api/auth/session')[0], 200)
        self.assertEqual(client.request('/api/bootstrap')[0], 403)
        self.assertEqual(client.request('/api/orders', self.order_body())[0], 403)
        old_cookies = dict(client.cookies)
        self.assertEqual(client.request('/api/auth/password', {'current_password': self.initial_password, 'new_password': self.personal_password})[0], 200)
        self.assertFalse(client.cookies)
        stale = Client(self)
        stale.cookies = old_cookies
        self.assertEqual(stale.request('/api/bootstrap')[0], 401)
        self.assertEqual(client.request('/api/auth/login', {'username': 'warehouse', 'password': self.personal_password})[0], 200)
        self.assertEqual(client.request('/api/bootstrap')[0], 200)
        self.assertEqual(client.request('/api/auth/logout', {})[0], 200)
        self.assertFalse(client.cookies)
        self.assertEqual(client.request('/api/bootstrap')[0], 401)

    def test_csrf_origin_and_client_header_are_required_for_writes(self):
        payload = {'username': 'cashier', 'display_name': '测试出纳', 'role': '出纳', 'password': self.initial_password}
        self.assertEqual(self.admin.request('/api/users', payload, csrf=False)[0], 403)
        self.assertEqual(self.admin.request('/api/users', payload, headers={'X-CSRF-Token': 'x' * 43})[0], 403)
        other, _ = self.user('accountant', '会计')
        self.assertEqual(self.admin.request('/api/users', payload, headers={'X-CSRF-Token': other.cookies['erp_csrf']})[0], 403)
        self.assertEqual(self.admin.request('/api/users', payload, headers={'Origin': 'https://evil.example'})[0], 400)
        self.assertEqual(self.admin.request('/api/users', payload, headers={'X-ERP-Client': ''})[0], 400)
        self.assertEqual(self.admin.request('/api/users', payload)[0], 200)

    def test_forged_role_cannot_grant_user_management_or_finance_permission(self):
        warehouse, user = self.user()
        for path in ['/api/users', '/api/security-events', '/api/export', '/api/statement-documents',
                     '/api/statement-batch-preview?date=2026-10-22', '/api/customer-statement?customer_id=C001&date=2026-10-22']:
            code, body, _ = warehouse.request(path, role='cashier')
            self.assertEqual(code, 403, (path, body))
        code, body, _ = warehouse.request('/api/users', {'username': 'fake', 'role': '管理员', 'password': self.initial_password}, role='accountant')
        self.assertEqual(code, 403, body)
        self.assertEqual(warehouse.request('/api/users/' + self.admin_user['id'], {'version': 1, 'active': False}, role='accountant')[0], 403)
        self.assertEqual(warehouse.request('/api/users/' + self.admin_user['id'] + '/reset-password', {'version': 1, 'password': self.personal_password}, role='accountant')[0], 403)
        self.assertEqual(warehouse.request('/api/orders/missing/settle', {'version': 1, 'mode': 'customer'}, role='accountant')[0], 403)
        self.assertEqual(warehouse.request('/api/orders/missing/review', {'version': 1, 'evidence_checked': True}, role='cashier')[0], 403)
        # Administrator now has all business permissions; header still cannot alter identity.
        self.assertEqual(self.admin.request('/api/orders', self.order_body(), role='warehouse')[0], 200)
        self.assertEqual(self.admin.request('/api/users')[0], 200)
        self.assertEqual(self.admin.request('/api/security-events')[0], 200)

    def test_bootstrap_limits_financial_data_and_exposes_account_catalog(self):
        financial = self.seed_finance()
        warehouse, _ = self.user()
        code, data, _ = warehouse.request('/api/bootstrap')
        self.assertEqual(code, 200, data)
        self.assertTrue(data['access_catalog']['authenticated'])
        self.assertEqual(data['access_catalog']['read_scope'], 'role')
        self.assertEqual(data['auth_user']['role'], '库管')
        self.assertEqual(data['receipts'], [])
        self.assertEqual(data['audit'], [])
        self.assertEqual(data['trial_archives'], [])
        self.assertEqual(data['archived_orders'], [])
        o = next(o for o in data['orders'] if o['id'] == financial['id'])
        for name in ['total_cents', 'paid_cents', 'return_credit_cents', 'settlement', 'review', 'review_history', 'review_return', 'receipts', 'return_credits']:
            self.assertNotIn(name, o)
        for line in o['lines']:
            for name in ['bill_qty', 'agreed_net', 'amount_cents', 'settlement_mode']:
                self.assertNotIn(name, line)
        cashier, _ = self.user('cashier', '出纳')
        code, data, _ = cashier.request('/api/bootstrap')
        self.assertEqual(code, 200)
        self.assertTrue(data['receipts'])
        self.assertIn('total_cents', next(o for o in data['orders'] if o['id'] == financial['id']))
        self.assertEqual(data['audit'], [])
        code, data, _ = self.admin.request('/api/bootstrap')
        self.assertEqual(code, 200)
        self.assertTrue(data['audit'])
        self.assertTrue(data['orders'])

    def test_deactivation_and_role_change_immediately_revoke_old_sessions(self):
        warehouse, user = self.user()
        code, updated, _ = self.admin.request('/api/users/' + user['id'], {'version': user['version'], 'active': False})
        self.assertEqual(code, 200, updated)
        self.assertEqual(warehouse.request('/api/bootstrap')[0], 401)
        self.assertEqual(warehouse.request('/api/orders', self.order_body())[0], 401)
        fresh = Client(self)
        self.assertEqual(fresh.request('/api/auth/login', {'username': 'warehouse', 'password': self.personal_password})[0], 401)
        self.assertEqual(self.admin.request('/api/users/' + user['id'], {'version': user['version'], 'active': True})[0], 409)
        code, updated, _ = self.admin.request('/api/users/' + user['id'], {'version': updated['version'], 'active': True, 'role': '会计'})
        self.assertEqual(code, 200)
        self.assertEqual(fresh.request('/api/auth/login', {'username': 'warehouse', 'password': self.personal_password})[0], 200)
        self.assertEqual(fresh.request('/api/export')[0], 200)
        code, updated, _ = self.admin.request('/api/users/' + user['id'], {'version': updated['version'], 'role': '库管'})
        self.assertEqual(code, 200)
        self.assertEqual(fresh.request('/api/export')[0], 401)

    def test_business_audit_uses_logged_in_actor_and_not_forged_header(self):
        warehouse, user = self.user()
        code, order, _ = warehouse.request('/api/orders', self.order_body(), role='cashier')
        self.assertEqual(code, 200, order)
        self.assertEqual(order['workflow_version'], 1)
        self.assertTrue(order['dispatch_required'])
        with erp.connect() as c:
            event = dict(c.execute('SELECT * FROM audit WHERE entity=? ORDER BY id DESC LIMIT 1', (order['id'],)).fetchone())
            created = dict(c.execute("SELECT * FROM audit WHERE entity=? AND action='auth.user.create'", (user['id'],)).fetchone())
        self.assertEqual(event['role'], '库管')
        self.assertEqual(event['actor_id'], user['id'])
        self.assertEqual(event['actor_name'], user['display_name'])
        self.assertEqual(len(event['request_id']), 24)
        self.assertEqual(created['actor_id'], self.admin_user['id'])
        self.assertEqual(created['actor_name'], self.admin_user['display_name'])
        self.assertNotEqual(created['request_id'], event['request_id'])
        self.assertNotIn(self.initial_password, created['after_json'])
        self.assertNotIn(warehouse.cookies['erp_session'], event['after_json'])

    def test_legacy_flags_cannot_bypass_inventory_dispatch_or_weight_handoff(self):
        warehouse, _ = self.user()
        body = self.order_body(workflow_version=0, dispatch_required=False)
        code, order, _ = warehouse.request('/api/orders', body)
        self.assertEqual(code, 200, order)
        self.assertEqual(order['workflow_version'], 1)
        self.assertTrue(order['dispatch_required'])
        body['version'] = order['version']
        body['lines'][0]['actual_qty'] = '2'
        code, error, _ = warehouse.request('/api/orders/' + order['id'] + '/order', body)
        self.assertEqual(code, 400, error)
        with erp.connect() as c:
            saved = erp.get_order(c, order['id'])
        self.assertEqual(saved['version'], order['version'])
        self.assertEqual(saved['lines'][0]['actual_qty'], '0')
        # Atomic batches receive the same mandatory workflow/dispatch flags.
        code, result, _ = warehouse.request('/api/batch', {'operations': [{'action': 'order', 'body': self.order_body(customer_id='C002',workflow_version=0, dispatch_required=False)}]})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['orders'][0]['workflow_version'], 1)
        self.assertTrue(result['orders'][0]['dispatch_required'])

    def test_authenticated_entry_requires_modern_stages_and_server_price(self):
        warehouse, _ = self.user()
        for stage in (None, 'legacy'):
            body={'business_date':'2026-10-22','version':0,'inventory_revision':0}
            if stage is not None:body['stage']=stage
            code,_,_=warehouse.request('/api/warehouse',body)
            self.assertEqual(code,400)
        code,_,_=warehouse.request('/api/warehouse',{'stage':'stock','business_date':'2026-10-22'})
        self.assertEqual(code,409)
        bad=self.order_body()
        bad['lines'][0]['price']='1'
        code,_,_=warehouse.request('/api/orders',bad)
        self.assertEqual(code,400)
        code,order,_=warehouse.request('/api/orders',self.order_body())
        self.assertEqual(code,200)
        code,_,_=warehouse.request('/api/orders',self.order_body())
        self.assertEqual(code,400)
        code,_,_=warehouse.request('/api/operator-users',{'name':'越权修改经办人','role':'出纳','active':True,'version':0})
        self.assertEqual(code,403)

    def test_failed_login_and_password_events_commit_and_rate_limit(self):
        anonymous = Client(self)
        errors = []
        for attempt in range(5):
            code, body, _ = anonymous.request('/api/auth/login', {'username': 'missing-user', 'password': self.initial_password})
            self.assertEqual(code, 401, body)
            errors.append(body['error'])
        self.assertEqual(len(set(errors)), 1)
        self.assertEqual(anonymous.request('/api/auth/login', {'username': 'missing-user', 'password': self.initial_password})[0], 429)
        code, body, _ = self.admin.request('/api/auth/password', {'current_password': 'incorrect-password', 'new_password': self.personal_password})
        self.assertEqual(code, 400, body)
        with erp.connect() as c:
            events = [dict(row) for row in c.execute('SELECT * FROM security_events')]
            self.assertEqual(sum(e['action'] == 'auth.login.failed' for e in events), 5)
            self.assertEqual(sum(e['action'] == 'auth.login.rate_limited' for e in events), 1)
            self.assertEqual(sum(e['action'] == 'auth.password.change_failed' for e in events), 1)
            self.assertTrue(c.execute('SELECT 1 FROM auth_login_limits WHERE failures>=5').fetchone())
        dump = json.dumps(events)
        for secret in [self.initial_password, self.personal_password, self.admin.cookies['erp_session'], self.admin.cookies['erp_csrf']]:
            self.assertNotIn(secret, dump)


if __name__ == '__main__':
    unittest.main(verbosity=2)
