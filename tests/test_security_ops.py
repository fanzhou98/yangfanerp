import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('security_check', ROOT / 'ops/security/check.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class SecurityMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.db = self.path / 'erp.db'
        self.now = 2000000000
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE security_events(at INTEGER, action TEXT, details_json TEXT)')
        self.backup = self.path / 'erp-backup.db'
        self.backup.write_bytes(b'backup')
        Path(str(self.backup) + '.manifest.json').write_text('{}')
        os.utime(self.backup, (self.now, self.now))

    def tearDown(self):
        self.temp.cleanup()

    def test_failure_burst_window_and_no_private_output(self):
        with sqlite3.connect(self.db) as c:
            c.executemany('INSERT INTO security_events VALUES(?,?,?)',
                          [(self.now, 'auth.login.failed', 'private-user-and-ip')] * 9)
            c.execute('INSERT INTO security_events VALUES(?,?,?)', (self.now - 301, 'auth.login.failed', 'old'))
        self.assertEqual(monitor.database_alerts(self.db, self.now), [])
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO security_events VALUES(?,?,?)', (self.now, 'auth.login.rate_limited', 'secret'))
        self.assertEqual(monitor.database_alerts(self.db, self.now), ['LOGIN_FAILURE_BURST'])

    def test_orphan_and_stale_backups_cannot_pass(self):
        self.assertEqual(monitor.backup_alerts(self.path, self.now), [])
        self.assertEqual(monitor.backup_alerts(self.path, self.now + 7201), ['BACKUP_STALE'])
        Path(str(self.backup) + '.manifest.json').unlink()
        self.assertEqual(monitor.backup_alerts(self.path, self.now), ['BACKUP_STALE'])

    def test_missing_database_does_not_create_file(self):
        missing = self.path / 'absent.db'
        with self.assertRaises(sqlite3.Error):
            monitor.database_alerts(missing, self.now)
        self.assertFalse(missing.exists())

    def test_healthy_run_and_read_only_database(self):
        from io import BytesIO
        response = BytesIO(b'{"status":"ok"}')
        response.status = 200
        class Opener:
            def open(self, *args, **kwargs):
                return response
        def systemctl(args, **kwargs):
            return subprocess.CompletedProcess(args, 1 if 'is-failed' in args else 0)
        before = self.db.read_bytes()
        with patch.object(monitor.subprocess, 'run', side_effect=systemctl), \
             patch.object(monitor.urllib.request, 'build_opener', return_value=Opener()), \
             patch.object(monitor.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 10 * 1024**3, 'total': 20 * 1024**3})()):
            report = monitor.check(self.db, self.path, self.now)
        self.assertTrue(report['ok'], report)
        self.assertEqual(self.db.read_bytes(), before)

    def test_failures_are_reported_without_underlying_secrets(self):
        with patch.object(monitor.subprocess, 'run', side_effect=OSError('private credential')), \
             patch.object(monitor.urllib.request, 'build_opener', side_effect=OSError('private cookie')), \
             patch.object(monitor.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 100, 'total': 10000})()):
            report = monitor.check(self.db, self.path, self.now)
        self.assertFalse(report['ok'])
        self.assertIn('DISK_LOW', report['alerts'])
        self.assertIn('HEALTH_FAILED', report['alerts'])
        self.assertNotIn('private', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
