"""Operational checks and restore drills only use disposable SQLite databases."""
from contextlib import closing, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('erp_ops', Path(__file__).resolve().parents[1] / 'ops' / 'erp_ops.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'source.db'
        with sqlite3.connect(self.db) as c:
            c.executescript('''
                CREATE TABLE customers(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE products(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE orders(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE receipts(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT,role TEXT,action TEXT,entity TEXT,
                    before_json TEXT,after_json TEXT,actor_id TEXT NOT NULL DEFAULT '',
                    actor_name TEXT NOT NULL DEFAULT '',request_id TEXT NOT NULL DEFAULT '');
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE statement_documents(id TEXT PRIMARY KEY,payload TEXT NOT NULL,content_hash TEXT NOT NULL);
            ''')
            c.execute('INSERT INTO customers VALUES(?,?)', ('test-customer', 'PRIVATE-CUSTOMER-DO-NOT-LOG'))
            c.execute('INSERT INTO products VALUES(?,?)', ('test-product', '测试产品'))
            c.execute('INSERT INTO orders VALUES(?,?)', ('test-order', '{"version":2,"amount_cents":12345}'))
            c.execute('INSERT INTO receipts VALUES(?,?)', ('test-receipt', '{"amount_cents":10000}'))
            c.execute('INSERT INTO audit(action) VALUES(?)', ('测试操作',))
            c.execute('INSERT INTO meta VALUES(?,?)', ('secret', 'PRIVATE-TOKEN-DO-NOT-LOG'))
            raw = json.dumps({'buyer': 'PRIVATE-BUYER', 'amount_cents': 12345})
            c.execute('INSERT INTO statement_documents VALUES(?,?,?)', ('test-statement', raw, hashlib.sha256(raw.encode()).hexdigest()))

    def tearDown(self):
        self.tmp.cleanup()

    def backup(self):
        return ops.backup_database(self.db, self.root / 'backups')

    def test_photo_backup_deduplicates_verifies_and_restores_without_source(self):
        photo=self.root/'driver-photos'/'order'/'weight.jpg'
        photo.parent.mkdir(parents=True);photo.write_bytes(b'photo-original')
        archive=self.root/'photo-archives'/'old.zip'
        archive.parent.mkdir();archive.write_bytes(b'archive-original')
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE driver_photos(path TEXT)')
            c.execute('INSERT INTO driver_photos VALUES(?)',(str(photo),))
        first=Path(self.backup()['backup']);second=Path(self.backup()['backup'])
        self.assertEqual(len(list((first.parent/'.media-objects').iterdir())),2)
        photo.unlink();archive.unlink()
        result=ops.restore_new(second,self.root/'restored.db')
        restored=Path(result['media_directory'])
        self.assertEqual((restored/'driver-photos/order/weight.jpg').read_bytes(),b'photo-original')
        self.assertEqual((restored/'photo-archives/old.zip').read_bytes(),b'archive-original')
        self.assertEqual(ops.restore_drill(first)['restored_media_files'],2)
        manifest=ops.verified_manifest(first)
        digest=manifest['media']['files']['driver-photos/order/weight.jpg']['sha256']
        (first.parent/'.media-objects'/digest).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ops.OpsError,'照片备份文件'):ops.restore_new(first,self.root/'rejected.db')
        self.assertFalse((self.root/'rejected.db').exists())

    def test_missing_photo_prevents_publishing_incomplete_backup(self):
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE driver_photos(path TEXT)')
            c.execute('INSERT INTO driver_photos VALUES(?)',(str(self.root/'driver-photos'/'missing.jpg'),))
        with self.assertRaisesRegex(ops.OpsError,'照片文件缺失'):self.backup()
        self.assertEqual(list((self.root/'backups').glob('erp-*.db')),[])

    def test_readonly_check_does_not_write_or_log_private_values(self):
        original = ops.file_hash(self.db)
        report = ops.check_database(self.db, full=True)
        self.assertTrue(report['ok'])
        self.assertEqual(report['table_counts']['orders'], 1)
        self.assertEqual(ops.file_hash(self.db), original)
        self.assertNotIn('PRIVATE-', json.dumps(report))
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(ops.main(['check-db', '--database', str(self.db)]), 0)
        self.assertNotIn('PRIVATE-', stream.getvalue())

    def test_missing_input_never_creates_a_database(self):
        missing = self.root / 'missing.db'
        with self.assertRaises(ops.OpsError):
            ops.check_database(missing)
        self.assertFalse(missing.exists())

    def test_real_backup_and_restore_drill_preserve_all_content(self):
        original = ops.logical_hash(self.db)
        result = self.backup()
        backup = Path(result['backup'])
        manifest = Path(result['manifest'])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(ops.file_hash(backup), result['sha256'])
        self.assertEqual(ops.logical_hash(backup), original)
        result = ops.restore_drill(backup, self.root / 'drills')
        self.assertTrue(result['ok'])
        self.assertTrue(result['isolated_restore'])
        self.assertTrue(result['temporary_copy_removed'])
        self.assertEqual(list((self.root / 'drills').iterdir()), [])
        self.assertEqual(ops.logical_hash(self.db), original)
        self.assertNotIn('PRIVATE-', json.dumps(result))

    def test_online_backup_includes_uncheckpointed_wal_rows(self):
        with closing(sqlite3.connect(self.db)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('INSERT INTO orders VALUES(?,?)', ('wal-order', '{"version":3}'))
            writer.commit()
            self.assertTrue(Path(str(self.db) + '-wal').exists())
            result = self.backup()
            with sqlite3.connect(result['backup']) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM orders').fetchone()[0], 2)
            self.assertTrue(ops.restore_drill(Path(result['backup']))['ok'])

    def test_backup_hardens_existing_public_directory(self):
        public = self.root / 'public-backups'
        public.mkdir()
        os.chmod(public, 0o755)
        result = ops.backup_database(self.db, public)
        self.assertEqual(public.stat().st_mode & 0o777, 0o700)
        self.assertEqual(Path(result['backup']).stat().st_mode & 0o777, 0o600)

    def test_restore_new_refuses_overwrites_sidecars_and_live_path(self):
        backup = Path(self.backup()['backup'])
        candidate = self.root / 'candidate.db'
        result = ops.restore_new(backup, candidate)
        self.assertTrue(result['ok'])
        before = ops.file_hash(candidate)
        with self.assertRaises(ops.OpsError):
            ops.restore_new(backup, candidate)
        self.assertEqual(ops.file_hash(candidate), before)
        sidecar_target = self.root / 'sidecar.db'
        Path(str(sidecar_target) + '-wal').write_text('do not overwrite')
        with self.assertRaises(ops.OpsError):
            ops.restore_new(backup, sidecar_target)
        self.assertFalse(sidecar_target.exists())
        with self.assertRaises(ops.OpsError):
            ops.restore_new(backup, ops.ROOT / 'data' / 'erp.db')

    def test_tampered_backup_rejected_before_creating_candidate(self):
        backup = Path(self.backup()['backup'])
        with backup.open('ab') as stream:
            stream.write(b'tampered')
        candidate = self.root / 'never-created.db'
        with self.assertRaisesRegex(ops.OpsError, '校验不一致'):
            ops.restore_new(backup, candidate)
        self.assertFalse(candidate.exists())

    def test_invalid_payload_or_statement_hash_is_reported_without_values(self):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE orders SET payload='INVALID-PRIVATE-VALUE'")
            c.execute("UPDATE statement_documents SET content_hash='wrong'")
        result = ops.check_database(self.db)
        self.assertFalse(result['ok'])
        self.assertEqual(result['invalid_payload_rows'], 1)
        self.assertEqual(result['statement_hash_mismatches'], 1)
        self.assertNotIn('PRIVATE-', json.dumps(result))
        with self.assertRaises(ops.OpsError):
            self.backup()
        self.assertEqual(list((self.root / 'backups').iterdir()), [])

    def test_symbolic_inputs_or_outputs_are_rejected(self):
        link = self.root / 'linked.db'
        link.symlink_to(self.db)
        with self.assertRaises(ops.OpsError):
            ops.check_database(link)
        output = self.root / 'linked-dir'
        output.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ops.OpsError):
            ops.backup_database(self.db, output)

    def test_atomic_publication_does_not_overwrite_existing_file(self):
        temporary, target = self.root / 'copy.partial', self.root / 'occupied.db'
        temporary.write_bytes(b'new')
        target.write_bytes(b'original')
        with self.assertRaises(FileExistsError):
            ops.publish_new(temporary, target)
        self.assertEqual(target.read_bytes(), b'original')

    def test_foreign_key_violation_only_reports_boolean(self):
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE child(id TEXT PRIMARY KEY,customer_id TEXT REFERENCES customers(id))')
            c.execute('INSERT INTO child VALUES(?,?)', ('private-child', 'PRIVATE-MISSING-CUSTOMER'))
        result = ops.check_database(self.db)
        self.assertFalse(result['ok'])
        self.assertFalse(result['foreign_keys_ok'])
        self.assertNotIn('PRIVATE-', json.dumps(result))

    def test_health_only_accesses_loopback_anonymous_endpoint_and_redacts_response(self):
        class Response(io.BytesIO):
            status = 200
        fake_response = Response(b'{"status":"ok","private":"PRIVATE-SERVER-VALUE"}')
        with patch.object(ops.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = fake_response
            result = ops.health('http://127.0.0.1:8765')
            self.assertTrue(result['ok'])
            self.assertNotIn('PRIVATE-', json.dumps(result))
            self.assertEqual(build.return_value.open.call_args.args[0], 'http://127.0.0.1:8765/api/health')
        for url in ['http://example.com', 'http://127.0.0.1/?password=secret', 'http://user:pass@localhost',
                    'file:///etc/passwd', 'http://127.0.0.1/api/bootstrap', 'http://127.0.0.1/#secret']:
            with self.subTest(url=url), self.assertRaises(ops.OpsError):
                ops.health(url)

    def test_finalize_only_changes_new_copy_and_invalidates_restored_sessions(self):
        with sqlite3.connect(self.db) as c:
            c.executescript('''
                CREATE TABLE auth_users(id TEXT PRIMARY KEY,role TEXT NOT NULL,active INTEGER NOT NULL);
                CREATE TABLE auth_sessions(id TEXT PRIMARY KEY,user_id TEXT REFERENCES auth_users(id),token_hash TEXT);
                CREATE TABLE auth_login_limits(bucket TEXT PRIMARY KEY,failures INTEGER);
                CREATE TABLE security_events(id INTEGER PRIMARY KEY,at INTEGER,action TEXT,actor_id TEXT,entity TEXT,details_json TEXT);
            ''')
            c.execute('INSERT INTO auth_users VALUES(?,?,?)', ('test-admin', '管理员', 1))
            c.execute('INSERT INTO auth_sessions VALUES(?,?,?)', ('test-session', 'test-admin', 'PRIVATE-OLD-TOKEN-HASH'))
            c.execute('INSERT INTO auth_login_limits VALUES(?,?)', ('PRIVATE-LIMITER-BUCKET', 5))
            c.execute("INSERT INTO meta VALUES('business_data_epoch','old-epoch')")
        restored = self.root / 'restored.db'
        ops.restore_new(Path(self.backup()['backup']), restored)
        source_hash = ops.file_hash(restored)
        final = self.root / 'finalized.db'
        result = ops.finalize_recovery(restored, final)
        self.assertTrue(result['ok'])
        self.assertEqual(result['sessions_invalidated'], 1)
        self.assertEqual(result['active_admin_count'], 1)
        self.assertTrue(result['account_review_required'])
        self.assertEqual(ops.file_hash(restored), source_hash)
        self.assertEqual(final.stat().st_mode & 0o777, 0o600)
        self.assertTrue(Path(str(final) + '.finalized-recovery.json').exists())
        with sqlite3.connect(final) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM auth_sessions').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT count(*) FROM auth_login_limits').fetchone()[0], 0)
            self.assertNotEqual(c.execute("SELECT value FROM meta WHERE key='business_data_epoch'").fetchone()[0], 'old-epoch')
            self.assertEqual(c.execute('SELECT action FROM security_events').fetchone()[0], 'recovery.finalized')
            self.assertEqual(c.execute('SELECT count(*) FROM audit').fetchone()[0], 2)
        self.assertEqual(ops.check_database(final)['statement_hash_mismatches'], 0)
        self.assertNotIn('PRIVATE-', json.dumps(result))
        with self.assertRaises(ops.OpsError):
            ops.finalize_recovery(restored, final)

    def test_finalize_requires_unmodified_restore_provenance(self):
        with self.assertRaises(ops.OpsError):
            ops.finalize_recovery(self.db, self.root / 'blocked.db')
        restored = self.root / 'restored.db'
        ops.restore_new(Path(self.backup()['backup']), restored)
        with sqlite3.connect(restored) as c:
            c.execute("UPDATE customers SET name='changed'")
        with self.assertRaisesRegex(ops.OpsError, '来源或内容校验不一致'):
            ops.finalize_recovery(restored, self.root / 'blocked.db')
        self.assertFalse((self.root / 'blocked.db').exists())
        with self.assertRaises(ops.OpsError):
            ops.finalize_recovery(ops.ROOT / 'data' / 'erp.db', self.root / 'blocked.db')

    def test_finalize_supports_pre_account_backups_without_inventing_users(self):
        restored = self.root / 'restored.db'
        ops.restore_new(Path(self.backup()['backup']), restored)
        result = ops.finalize_recovery(restored, self.root / 'finalized.db')
        self.assertEqual(result['sessions_invalidated'], 0)
        self.assertEqual(result['active_admin_count'], 0)
        self.assertTrue(result['account_review_required'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
