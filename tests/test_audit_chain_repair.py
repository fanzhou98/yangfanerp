import os, sqlite3, tempfile, unittest
import audit_chain


class AuditChainRepairTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.c = sqlite3.connect(self.path)
        self.c.execute('''CREATE TABLE audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, role TEXT, action TEXT,
            entity TEXT, before_json TEXT, after_json TEXT, actor_id TEXT,
            actor_name TEXT, request_id TEXT, prev_hash TEXT, hash TEXT)''')
        for i in range(1, 6):
            audit_chain.append(self.c, ('2026-11-02T10:00:00+08:00', '管理员',
                                        '测试%d' % i, 'E%d' % i, '', '', '', '', ''))
        self.c.commit()

    def tearDown(self):
        self.c.close()
        os.unlink(self.path)

    def test_repair_emptied_hashes_preserves_business_rows(self):
        before = self.c.execute('SELECT id,at,role,action,entity FROM audit ORDER BY id').fetchall()
        self.c.execute("UPDATE audit SET prev_hash='',hash='' WHERE id IN (2,3)")
        self.c.execute("UPDATE audit SET prev_hash='' WHERE id=4")
        self.c.commit()
        self.assertFalse(audit_chain.verify(self.c)['ok'])
        result = audit_chain.repair(self.c)
        self.assertEqual(result, {'ok': True, 'repaired': 4, 'from_id': 2})
        self.assertTrue(audit_chain.verify(self.c)['ok'])
        after = self.c.execute('SELECT id,at,role,action,entity FROM audit ORDER BY id').fetchall()
        self.assertEqual(before, after)

    def test_repair_refuses_nonempty_tamper(self):
        self.c.execute("UPDATE audit SET hash='bad' WHERE id=2")
        self.c.commit()
        result = audit_chain.repair(self.c)
        self.assertFalse(result['ok'])
        self.assertIn('篡改', result['reason'])


if __name__ == '__main__':
    unittest.main()
