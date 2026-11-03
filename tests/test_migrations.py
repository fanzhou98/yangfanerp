"""Upgrade and rollback drills exclusively on temporary/in-memory databases."""
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import urlopen
from unittest.mock import patch

import server
import cloud_app
import migrations
from ops import erp_ops


def failing_step(c, ctx):
    c.execute('CREATE TABLE migration_should_rollback(value TEXT)')
    c.execute("INSERT INTO migration_should_rollback VALUES('not committed')")
    raise RuntimeError('injected upgrade failure')


def counted_step(c, ctx):
    c.execute('UPDATE migration_counter SET count=count+1')


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = server.DB
        self.path = Path(self.temp.name) / 'upgrade.db'
        server.DB = self.path

    def tearDown(self):
        server.DB = self.old
        self.temp.cleanup()

    def rows(self, c):
        return {t: [tuple(r) for r in c.execute('SELECT * FROM "' + t + '" ORDER BY rowid')]
                for t, in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}

    def test_fresh_formal_database_and_repeat_start_are_identical(self):
        server.init_db(demo=False)
        with server.connect() as c:
            before = self.rows(c)
            status = migrations.status(c)
            self.assertTrue(all(s['state'] == 'applied' for s in status['steps']))
            self.assertEqual(status['schema_version'], migrations.SCHEMA_VERSION)
            for table in ('customers', 'products', 'orders', 'auth_users'):
                self.assertEqual(before[table], [])
        server.init_db(demo=False)
        with server.connect() as c: self.assertEqual(self.rows(c), before)

    def test_cross_module_cash_indexes_wait_for_full_initialization(self):
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row
            migrations.ensure(c,'auth')
            self.assertFalse(c.execute("SELECT 1 FROM schema_migrations WHERE id='068-finance-cash-query-indexes'").fetchone())
            self.assertFalse(c.execute("SELECT 1 FROM schema_migrations WHERE id='077-check-history-indexes'").fetchone())
            self.assertFalse(c.execute("SELECT 1 FROM schema_migrations WHERE id='079-expense-estimates'").fetchone())
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='purchase_payments'").fetchone())
        server.init_db(demo=False)
        with server.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations WHERE id='068-finance-cash-query-indexes'").fetchone()[0],1)
            self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='purchase_payments_date_id'").fetchone())
            self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='payroll_payment_kind_date_id'").fetchone())

    def test_demo_mode_does_not_implicitly_convert_package_prices(self):
        server.init_db()
        with server.connect() as c:
            self.assertFalse(server.billing.enabled(c))
            self.assertEqual(c.execute("SELECT price FROM products WHERE id='P004'").fetchone()[0], '75')
            step = next(s for s in migrations.status(c)['steps'] if s['id'] == '900-billing-kilograms')
            self.assertEqual((step['state'], step['mode']), ('pending', 'explicit'))
        server.init_db()
        with server.connect() as c: self.assertFalse(server.billing.enabled(c))

    def test_v042_ledger_and_legacy_flags_are_adopted_without_business_changes(self):
        server.init_db()
        with server.connect(True) as c:
            c.execute("INSERT INTO role_permissions VALUES('出纳',7,?,?)", (json.dumps({'modules': ['finance.receivables'], 'actions': [], 'data_scopes': []}), 'unchanged'))
            c.execute("UPDATE schema_migrations SET applied_at='2026-10-01T00:00:00+08:00' WHERE id='042-production-directory-v1'")
            # Simulate the original two-column v0.42 ledger, not a new ledger.
            c.execute('CREATE TABLE old_ledger(id TEXT PRIMARY KEY,applied_at TEXT NOT NULL)')
            c.execute("INSERT INTO old_ledger SELECT id,applied_at FROM schema_migrations WHERE id='042-production-directory-v1'")
            c.execute('DROP TABLE schema_migrations')
            c.execute('ALTER TABLE old_ledger RENAME TO schema_migrations')
            c.execute('PRAGMA user_version=0')
            before = {k: v for k, v in self.rows(c).items() if k not in ('schema_migrations', 'role_permissions', 'audit') and not k.startswith('chat_') and k not in ('notifications', 'feedback_tickets')}
        server.init_db(demo=False)
        with server.connect() as c:
            after = {k: v for k, v in self.rows(c).items() if k not in ('schema_migrations', 'role_permissions', 'audit') and not k.startswith('chat_') and k not in ('notifications', 'feedback_tickets')}
            self.assertEqual(after, before)
            role = json.loads(c.execute("SELECT payload FROM role_permissions WHERE role='出纳'").fetchone()[0])
            self.assertNotIn('workspace.chat', role['modules']); self.assertIn('system.feedback', role['modules'])
            record = c.execute("SELECT applied_at,source,checksum FROM schema_migrations WHERE id='042-production-directory-v1'").fetchone()
            self.assertEqual(tuple(record[:2]), ('2026-10-01T00:00:00+08:00', 'legacy-ledger'))
            self.assertEqual(len(record[2]), 64)
            self.assertEqual(c.execute("SELECT source FROM schema_migrations WHERE id='021-expense-payables'").fetchone()[0], 'legacy-marker')

    def test_old_marker_deletion_never_regrants_permissions_after_recorded_upgrade(self):
        server.init_db()
        with server.connect(True) as c:
            c.execute("INSERT INTO role_permissions VALUES('出纳',9,?,?)", (json.dumps({'modules': ['finance.expense-payables'], 'actions': []}), 'admin-denied'))
            c.execute("DELETE FROM meta WHERE key='expense_payables_v040'")
        server.init_db()
        with server.connect() as c:
            version, raw = c.execute("SELECT version,payload FROM role_permissions WHERE role='出纳'").fetchone()
            self.assertEqual(version, 9)
            self.assertEqual(json.loads(raw)['actions'], [])

    def test_failure_rolls_back_ddl_and_ledger_without_committing_callers_work(self):
        c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON'); c.execute('CREATE TABLE caller_work(value TEXT)')
        c.execute("INSERT INTO caller_work VALUES('pending')")
        specs = migrations.registry() + (migrations.Migration('999-injected-failure', 'core', 'failure drill', failing_step),)
        with patch.object(migrations, 'registry', return_value=specs):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                migrations.upgrade(c, context={'demo': False})
        self.assertTrue(c.in_transaction)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM caller_work').fetchone()[0], 1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name<>'caller_work'").fetchone()[0], 0)
        c.rollback(); self.assertEqual(c.execute('SELECT COUNT(*) FROM caller_work').fetchone()[0], 0)
        c.close()

    def test_explicit_conversion_failure_rolls_back_the_whole_requested_upgrade(self):
        server.init_db()
        with server.connect(True) as c:
            c.execute("INSERT INTO products VALUES('P099','bad conversion','包','1','0','3')")
            c.execute('CREATE TABLE migration_counter(count INTEGER)'); c.execute('INSERT INTO migration_counter VALUES(0)')
        before = erp_ops.logical_hash(self.path)
        specs = migrations.registry() + (migrations.Migration('999-counted-step', 'core', 'atomic drill', counted_step),)
        with patch.object(migrations, 'registry', return_value=specs):
            with self.assertRaisesRegex(ValueError, '超过3位小数'):
                server.init_db(demo=False, convert_billing=True)
        self.assertEqual(erp_ops.logical_hash(self.path), before)

    def test_unknown_future_or_changed_migration_blocks_startup_without_writes(self):
        server.init_db()
        for mode in ('future', 'checksum', 'version'):
            with server.connect(True) as c:
                if mode == 'future': c.execute("INSERT INTO schema_migrations(id,applied_at) VALUES('future-step','later')")
                elif mode == 'checksum': c.execute("UPDATE schema_migrations SET checksum='wrong' WHERE id='001-core-tables'")
                else: c.execute('PRAGMA user_version=999')
            before = erp_ops.logical_hash(self.path)
            with self.assertRaises(migrations.MigrationError): server.init_db()
            self.assertEqual(erp_ops.logical_hash(self.path), before)
            with server.connect(True) as c:
                c.execute("DELETE FROM schema_migrations WHERE id='future-step'")
                c.execute("UPDATE schema_migrations SET checksum=? WHERE id='001-core-tables'", (migrations.registry()[0].checksum,))
                c.execute('PRAGMA user_version=' + str(migrations.SCHEMA_VERSION))

    def test_status_is_read_only_for_legacy_database_without_a_ledger(self):
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            c.execute("INSERT INTO meta VALUES('customer_locations_v09','1')")
        before = erp_ops.logical_hash(self.path)
        with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as c:
            c.execute('PRAGMA query_only=ON')
            plan = migrations.status(c)
        self.assertEqual(erp_ops.logical_hash(self.path), before)
        self.assertEqual(next(s['state'] for s in plan['steps'] if s['id'] == '046-customer-locations'), 'legacy')

    def test_concurrent_upgraders_execute_new_step_once(self):
        server.init_db(demo=False)
        with server.connect(True) as c:
            c.execute('CREATE TABLE migration_counter(count INTEGER)'); c.execute('INSERT INTO migration_counter VALUES(0)')
        specs = migrations.registry() + (migrations.Migration('999-counted-step', 'core', 'concurrency drill', counted_step),)
        ready = threading.Barrier(2)
        def apply():
            c = sqlite3.connect(self.path, timeout=10); c.row_factory = sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
            try:
                ready.wait(); migrations.ensure(c); c.commit()
            finally: c.close()
        with patch.object(migrations, 'registry', return_value=specs):
            with ThreadPoolExecutor(2) as pool: list(pool.map(lambda _: apply(), range(2)))
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT count FROM migration_counter').fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations WHERE id='999-counted-step'").fetchone()[0], 1)

    def test_cloud_worker_checks_upgrade_state_without_writing(self):
        server.init_db()
        before = erp_ops.logical_hash(self.path)
        cloud_app.create_application(self.path, 'https://example.test')
        self.assertEqual(erp_ops.logical_hash(self.path), before)
        with server.connect(True) as c:
            c.execute("DELETE FROM schema_migrations WHERE id='001-core-tables'")
        before = erp_ops.logical_hash(self.path)
        with self.assertRaisesRegex(migrations.MigrationError, '尚未完成'):
            cloud_app.create_application(self.path, 'https://example.test')
        self.assertEqual(erp_ops.logical_hash(self.path), before)
        missing = self.path.parent / 'missing.db'
        with self.assertRaises(sqlite3.OperationalError):
            cloud_app.create_application(missing, 'https://example.test')
        self.assertFalse(missing.exists())

    def test_cli_plan_is_read_only_and_apply_backs_up_the_old_database(self):
        server.init_db()
        with server.connect(True) as c:
            c.execute("DELETE FROM schema_migrations WHERE id='001-core-tables'")
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable, str(root / 'ops/migrate.py')]
        before = erp_ops.logical_hash(self.path)
        plan = json.loads(subprocess.check_output(command + ['plan', '--database', str(self.path)], cwd=root))
        self.assertTrue(plan['ok'])
        self.assertEqual(erp_ops.logical_hash(self.path), before)
        result = json.loads(subprocess.check_output(command + ['apply', '--database', str(self.path)], cwd=root))
        self.assertTrue(result['ok'])
        backups = list((self.path.parent / 'backups').glob('*.db'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(erp_ops.logical_hash(backups[0]), before)
        self.assertEqual(next(s['state'] for s in result['steps'] if s['id'] == '001-core-tables'), 'applied')
        self.assertEqual(next(s['state'] for s in result['steps'] if s['id'] == '900-billing-kilograms'), 'pending')

    def test_normal_server_start_never_converts_legacy_package_prices(self):
        server.init_db()
        before = erp_ops.logical_hash(self.path)
        root = Path(__file__).resolve().parents[1]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(root / 'server.py'), '--database', str(self.path), '--no-browser', '--port', str(port)], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None: self.fail('server exited before health check')
                try:
                    with urlopen('http://127.0.0.1:' + str(port) + '/api/health', timeout=1) as response:
                        if response.status == 200: break
                except OSError:
                    time.sleep(0.05)
            else: self.fail('server did not become healthy')
            self.assertEqual(erp_ops.logical_hash(self.path), before)
            self.assertFalse((self.path.parent / 'backups').exists())
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()

    def test_domain_entry_points_no_longer_own_ddl_or_implicit_commits(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('auth', 'erp_access', 'resources_costs', 'purchasing', 'production_management', 'payroll', 'assets', 'driver_portal', 'production_config'):
            source = (root / (name + '.py')).read_text()
            self.assertNotIn('executescript(', source)
            self.assertNotIn('ALTER TABLE ', source)
            self.assertNotIn('CREATE TABLE ', source)
        self.assertNotIn('executescript(', (root / 'migration_steps.py').read_text())
