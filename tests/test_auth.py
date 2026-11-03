import json
import sqlite3
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auth


class AuthTests(unittest.TestCase):
    password = 'correct-horse-豆制品-2026'
    alternate = 'another-password-2026'
    now = 1800000000

    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.execute('PRAGMA foreign_keys=ON')
        auth.init_schema(self.c)
        self.admin = auth.create_initial_admin(self.c, 'Admin', '系统管理员', self.password, self.now)

    def tearDown(self):
        self.c.close()

    def create(self, name='cashier', role='出纳', **kwargs):
        return auth.create_user(self.c, self.admin, {'username': name, 'display_name': '测试人员',
                                'role': role, 'password': self.password, **kwargs}, self.now)

    def login(self, username='admin', password=None, ip='127.0.0.1', now=None, **kwargs):
        return auth.login(self.c, username, self.password if password is None else password,
                          ip, self.now if now is None else now, **kwargs)

    def assert_error(self, status, call, *args, **kwargs):
        with self.assertRaises(auth.AuthError) as cm:
            call(*args, **kwargs)
        self.assertEqual(cm.exception.status, status)
        self.assertEqual(cm.exception.message, str(cm.exception))
        return str(cm.exception)

    def test_schema_is_idempotent_and_has_no_default_password(self):
        c = sqlite3.connect(':memory:')
        try:
            auth.init_schema(c)
            auth.init_schema(c)
            self.assertEqual(auth.list_users(c), [])
            c.commit()  # The shared migration ledger is committed by its caller.
            with c:
                c.execute('CREATE TABLE caller_transaction(value TEXT)')
                c.execute("INSERT INTO caller_transaction VALUES('pending')")
                auth.init_schema(c)
                c.rollback()
            self.assertEqual(c.execute('SELECT count(*) FROM caller_transaction').fetchone()[0], 0)
        finally:
            c.close()
        self.assert_error(409, auth.create_initial_admin, self.c, 'anotheradmin', '另一个管理员', self.password, self.now)
        self.assertEqual(len(auth.list_users(self.c)), 1)

    def test_salted_memory_hard_hash_and_constant_time_verification(self):
        one, two = auth.hash_password(self.password), auth.hash_password(self.password)
        self.assertNotEqual(one, two)
        self.assertTrue(one.startswith('scrypt$32768$8$3$'))
        self.assertNotIn(self.password, one)
        self.assertTrue(auth.verify_password(self.password, one))
        self.assertFalse(auth.verify_password(self.alternate, one))
        for malformed in ['', None, 'plaintext', 'scrypt$999999999$8$3$00$00']:
            self.assertFalse(auth.verify_password(self.password, malformed))

    def test_password_username_and_field_validation(self):
        for password in ['', 'short', ' ' * 12, 'a' * 129, None, 'a' * 12 + '\ud800']:
            self.assert_error(400, auth.hash_password, password)
        self.assertTrue(auth.verify_password('密码🔐' * 4, auth.hash_password('密码🔐' * 4)))
        for username in ['ab', '_abc', 'a b', '中文名', 'a' * 33, 'bad/name', 'good\n']:
            self.assert_error(400, self.create, name=username)
        self.assert_error(400, self.create, role='未定义岗位')
        self.assert_error(400, self.create, active=1)
        self.assert_error(400, self.create, display_name=' ')
        self.assert_error(409, self.create, name='ADMIN')

    def test_login_returns_raw_secrets_only_once_and_persists_only_hashes(self):
        result = self.login()
        self.assertEqual(result['user']['username'], 'admin')
        self.assertEqual(result['expires_at'], self.now + 28800)
        session = auth.authenticate(self.c, result['token'], self.now + 1)
        self.assertEqual(session['user'], self.admin)
        self.assertNotIn('token', session)
        self.assertNotIn('csrf_token', session)
        raw = str(list(self.c.execute('SELECT * FROM auth_sessions')))
        for secret in [result['token'], result['csrf_token'], self.password]:
            self.assertNotIn(secret, raw)
        self.assertTrue(auth.verify_csrf(session, result['csrf_token']))
        for invalid in ['', None, 'a' * 43, result['token']]:
            self.assert_error(403, auth.verify_csrf, session, invalid)
        self.assert_error(401, auth.authenticate, self.c, result['token'], result['expires_at'])
        for invalid in ['', None, 'abc', 'x' * 10000]:
            self.assert_error(401, auth.authenticate, self.c, invalid, self.now)

    def test_idle_timeout_reads_do_not_renew_and_activity_cannot_revive(self):
        result = self.login()
        token = result['token']
        self.assertEqual(result['session']['idle_timeout_seconds'], 1800)
        auth.authenticate(self.c, token, self.now + 1799)
        self.assert_error(401, auth.authenticate, self.c, token, self.now + 1800)
        self.assert_error(401, auth.record_activity, self.c, token, self.now + 1800)
        renewed = self.login()
        auth.record_activity(self.c, renewed['token'], self.now + 1700)
        self.assertTrue(auth.authenticate(self.c, renewed['token'], self.now + 1800))
        self.assert_error(401, auth.authenticate, self.c, renewed['token'], self.now + 3500)

    def test_remember_session_skips_idle_timeout_but_keeps_absolute_limit(self):
        result = self.login(session_ttl=auth.REMEMBER_TTL)
        self.assertEqual(result['expires_at'], self.now + auth.REMEMBER_TTL)
        self.assertEqual(result['session']['idle_timeout_seconds'], auth.REMEMBER_TTL)
        self.assertTrue(auth.authenticate(self.c, result['token'], self.now + auth.SESSION_IDLE_TTL + 1))
        self.assertTrue(auth.authenticate(self.c, result['token'], self.now + auth.REMEMBER_TTL - 1))
        self.assert_error(401, auth.authenticate, self.c, result['token'], self.now + auth.REMEMBER_TTL)

    def test_activity_keeps_absolute_limit_and_logout_cleans_activity(self):
        result = self.login(session_ttl=600)
        auth.record_activity(self.c, result['token'], self.now + 500)
        self.assert_error(401, auth.authenticate, self.c, result['token'], self.now + 600)
        auth.logout(self.c, result['token'], self.now + 601)
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_session_activity').fetchone()[0], 0)

    def test_session_is_unique_configurable_and_logout_is_idempotent(self):
        first = self.login(session_ttl=60)
        second = self.login(session_ttl=600)
        self.assertNotEqual(first['token'], second['token'])
        self.assertNotEqual(first['csrf_token'], second['csrf_token'])
        self.assertEqual(first['expires_at'], self.now + 60)
        auth.logout(self.c, first['token'], self.now + 1)
        self.assert_error(401, auth.authenticate, self.c, first['token'], self.now + 2)
        self.assertTrue(auth.authenticate(self.c, second['token'], self.now + 2))
        self.assertEqual(auth.logout(self.c, first['token'], self.now + 3), {'ok': True})
        for ttl in [0, 59, 2592001, True, '3600']:
            with self.assertRaises(ValueError):
                self.login(session_ttl=ttl)

    def test_unknown_inactive_and_bad_password_have_same_error(self):
        self.create(active=False)
        errors = [self.assert_error(401, self.login, 'missing-user'),
                  self.assert_error(401, self.login, 'cashier'),
                  self.assert_error(401, self.login, 'admin', self.alternate),
                  self.assert_error(401, self.login, None, None),
                  self.assert_error(401, self.login, 'admin', '\ud800' * 12)]
        self.assertEqual(len(set(errors)), 1)

    def test_username_limit_applies_across_ips_and_resets_after_window(self):
        for attempt in range(5):
            self.assert_error(401, self.login, 'admin', self.alternate, ip=f'10.0.0.{attempt}')
        self.assert_error(429, self.login, 'admin', ip='10.0.1.2')
        # Unknown accounts are subject to exactly the same threshold and reply.
        for attempt in range(5):
            self.assert_error(401, self.login, 'missing', self.alternate, ip=f'10.1.0.{attempt}')
        self.assert_error(429, self.login, 'missing', ip='10.1.1.2')
        self.assertTrue(self.login(now=self.now + auth.RATE_WINDOW))

    def test_ip_limit_prevents_password_spraying_and_success_cannot_erase_it(self):
        for attempt in range(auth.IP_ATTEMPTS - 1):
            self.assert_error(401, self.login, f'absent{attempt}')
        self.assertTrue(self.login())
        self.assert_error(401, self.login, 'last-absent')
        self.assert_error(429, self.login)
        self.assertTrue(self.login(ip='other-ip'))

    def test_initial_password_flag_and_password_change_revoke_all_sessions(self):
        user = self.create()
        self.assertTrue(user['must_change_password'])
        first, second = self.login('cashier'), self.login('cashier')
        self.assertTrue(auth.authenticate(self.c, first['token'], self.now)['user']['must_change_password'])
        self.assert_error(400, auth.change_password, self.c, user, 'wrong-password', self.alternate, self.now)
        self.assert_error(400, auth.change_password, self.c, user, self.password, self.password, self.now)
        updated = auth.change_password(self.c, user, self.password, self.alternate, self.now)
        self.assertFalse(updated['must_change_password'])
        self.assertEqual(updated['version'], user['version'] + 1)
        for session in (first, second):
            self.assert_error(401, auth.authenticate, self.c, session['token'], self.now)
        self.assert_error(401, self.login, 'cashier')
        self.assertTrue(self.login('cashier', self.alternate))

    def test_admin_password_reset_revokes_sessions_and_forces_password_change(self):
        user = self.create()
        user = auth.change_password(self.c, user, self.password, self.alternate, self.now)
        session = self.login('cashier', self.alternate)
        reset = auth.reset_password(self.c, self.admin, user['id'], self.password, user['version'], self.now)
        self.assertTrue(reset['must_change_password'])
        self.assert_error(401, auth.authenticate, self.c, session['token'], self.now)
        self.assert_error(401, self.login, 'cashier', self.alternate)
        self.assertTrue(self.login('cashier'))
        self.assert_error(409, auth.reset_password, self.c, self.admin, user['id'], self.alternate, user['version'], self.now)
        self.assert_error(400, auth.reset_password, self.c, self.admin, self.admin['id'], self.alternate, self.admin['version'], self.now)

    def test_update_cas_role_and_disable_revoke_sessions(self):
        user = self.create()
        session = self.login('cashier')
        updated = auth.update_user(self.c, self.admin, user['id'], {'version': user['version'], 'role': '会计'}, self.now)
        self.assertEqual(updated['role'], '会计')
        self.assert_error(401, auth.authenticate, self.c, session['token'], self.now)
        self.assert_error(409, auth.update_user, self.c, self.admin, user['id'], {'version': user['version'], 'active': False}, self.now)
        self.assert_error(409, auth.update_user, self.c, self.admin, user['id'], {'version': True}, self.now)
        self.assert_error(404, auth.update_user, self.c, self.admin, 'missing-id', {'version': 1}, self.now)
        session = self.login('cashier')
        disabled = auth.update_user(self.c, self.admin, user['id'], {'version': updated['version'], 'active': False}, self.now)
        self.assertFalse(disabled['active'])
        self.assert_error(401, auth.authenticate, self.c, session['token'], self.now)
        self.assert_error(401, self.login, 'cashier')

    def test_last_active_admin_cannot_be_disabled_or_downgraded(self):
        for body in ({'active': False}, {'role': '库管'}):
            self.assert_error(409, auth.update_user, self.c, self.admin, self.admin['id'],
                              {'version': self.admin['version'], **body}, self.now)
        other = self.create(name='other-admin', role='管理员')
        # Newly created admins cannot manage users until changing their password.
        self.assert_error(403, auth.create_user, self.c, other, {'username': 'new-user'}, self.now)
        other = auth.change_password(self.c, other, self.password, self.alternate, self.now)
        old_session = self.login()
        auth.update_user(self.c, other, self.admin['id'], {'version': self.admin['version'], 'role': '库管'}, self.now)
        self.assert_error(401, auth.authenticate, self.c, old_session['token'], self.now)
        self.assert_error(409, auth.update_user, self.c, other, other['id'], {'version': other['version'], 'active': False}, self.now)

    def test_privileged_functions_recheck_actor_in_database(self):
        user = self.create()
        forged = {**user, 'role': '管理员', 'must_change_password': False}
        self.assert_error(403, auth.create_user, self.c, forged, {}, self.now)
        self.assert_error(403, auth.update_user, self.c, forged, self.admin['id'], {}, self.now)
        self.assert_error(403, auth.reset_password, self.c, forged, self.admin['id'], self.alternate, 1, self.now)
        self.assert_error(403, auth.create_user, self.c, None, {}, self.now)
        self.assert_error(401, auth.change_password, self.c, {}, self.password, self.alternate, self.now)

    def test_version_guard_rejects_session_even_without_deletion(self):
        session = self.login()
        self.c.execute('UPDATE auth_users SET version=version+1 WHERE id=?', (self.admin['id'],))
        self.assert_error(401, auth.authenticate, self.c, session['token'], self.now)

    def test_security_events_and_public_projection_never_include_secrets(self):
        received = []
        def audit(c, action, entity, before, after):
            received.append((action, entity, before, after))
        user = auth.create_user(self.c, self.admin, {'username': 'cashier', 'display_name': '测试人员',
                                'role': '出纳', 'password': self.password}, self.now, audit=audit)
        session = self.login('cashier', audit=audit)
        self.assert_error(401, self.login, 'nonexistent', self.alternate, audit=audit)
        auth.change_password(self.c, user, self.password, self.alternate, self.now, audit=audit)
        dump = json.dumps({'users': auth.list_users(self.c), 'audit': received,
                           'security_events': list(self.c.execute('SELECT * FROM security_events'))}, ensure_ascii=False)
        for secret in [self.password, self.alternate, session['token'], session['csrf_token'], 'password_hash', 'csrf_hash', 'token_hash']:
            self.assertNotIn(secret, dump)
        actions = [row[0] for row in self.c.execute('SELECT action FROM security_events')]
        for expected in ['auth.bootstrap', 'auth.user.create', 'auth.login.succeeded', 'auth.login.failed', 'auth.password.change']:
            self.assertIn(expected, actions)


if __name__ == '__main__':
    unittest.main()
