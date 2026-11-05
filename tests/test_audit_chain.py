"""Audit hash chain: append-only binding and tamper detection."""
import unittest
import audit_chain
import test_workflow as fixture

erp = fixture.erp


class AuditChainTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowTests(); self.old = erp.DB; self.case.setUp()
        with erp.connect(True) as c:
            c.execute('DELETE FROM audit')

    def tearDown(self):
        self.case.tearDown(); erp.DB = self.old

    def append(self, count):
        with erp.connect(True) as c:
            for index in range(count):
                erp.audit(c, '会计', '测试动作%d' % index, 'SO-%d' % index,
                          {'before': index}, {'after': index})

    def test_chain_links_every_row(self):
        self.append(3)
        with erp.connect() as c:
            rows = c.execute('SELECT prev_hash,hash FROM audit ORDER BY id').fetchall()
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0][0], '')
            self.assertEqual(rows[1][0], rows[0][1])
            self.assertEqual(rows[2][0], rows[1][1])
            self.assertTrue(all(len(row[1]) == 64 for row in rows))
            self.assertEqual(audit_chain.verify(c)['ok'], True)

    def test_edited_row_breaks_the_chain_at_that_row(self):
        self.append(3)
        with erp.connect(True) as c:
            target = c.execute('SELECT id FROM audit ORDER BY id LIMIT 1 OFFSET 1').fetchone()[0]
            c.execute("UPDATE audit SET after_json='{\"tampered\":true}' WHERE id=?", (target,))
            result = audit_chain.verify(c)
            self.assertEqual(result['ok'], False)
            self.assertEqual(result['broken_id'], target)
            self.assertEqual(result['total'], 2)

    def test_deleted_row_breaks_the_next_link(self):
        self.append(3)
        with erp.connect(True) as c:
            target = c.execute('SELECT id FROM audit ORDER BY id LIMIT 1 OFFSET 1').fetchone()[0]
            c.execute('DELETE FROM audit WHERE id=?', (target,))
            result = audit_chain.verify(c)
            self.assertEqual(result['ok'], False)
            self.assertIsNotNone(result['broken_id'])

    def test_verify_reports_row_count_and_basis(self):
        self.append(2)
        with erp.connect() as c:
            result = audit_chain.verify(c)
            self.assertEqual(result['total'], 2)
            self.assertIn('SHA-256', result['basis'])

    def test_append_accepts_mapping_without_writing_field_names(self):
        values = {'at': '2026-11-05T10:00:00+08:00', 'role': '管理员', 'action': '补录期初',
                  'entity': 'SO-1', 'before_json': 'null', 'after_json': '{"ok":true}',
                  'actor_id': 'SYSTEM', 'actor_name': '系统补录', 'request_id': 'R1'}
        with erp.connect(True) as c:
            audit_chain.append(c, values)
            row = c.execute('SELECT at,role,action,entity,before_json,after_json FROM audit').fetchone()
            self.assertEqual(tuple(row), (values['at'], values['role'], values['action'],
                                          values['entity'], values['before_json'], values['after_json']))
            self.assertEqual(audit_chain.verify(c)['ok'], True)


if __name__ == '__main__':
    unittest.main()
