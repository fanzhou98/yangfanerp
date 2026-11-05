import json
import sqlite3
import unittest

import migration_steps


class PermissionSyncTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE role_permissions(role TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0,updated_at TEXT)')
        self.audits = []

    def add(self, role, modules, actions):
        payload = {'role': role, 'modules': modules, 'actions': actions, 'data_scopes': []}
        self.c.execute('INSERT INTO role_permissions(role,payload,version) VALUES(?,?,0)', (role, json.dumps(payload)))

    def run_step(self):
        migration_steps.material_pin_permissions(self.c, {
            'now': lambda: '2026-11-04T00:00:00+08:00',
            'audit': lambda *args: self.audits.append(args),
        })

    def row(self, role):
        return json.loads(self.c.execute('SELECT payload FROM role_permissions WHERE role=?', (role,)).fetchone()[0])

    def test_repairs_modules_and_grants_new_actions(self):
        self.add('库管', ['inventory.materials'], ['materials.write'])
        self.add('会计', ['inventory.materials'], ['materials.catalog'])
        self.add('厂长', ['inventory.materials', 'production.manage'], ['materials.issue', 'production.record'])
        self.run_step()
        self.assertIn('materials.pin', self.row('库管')['actions'])
        self.assertIn('materials.pin', self.row('会计')['actions'])
        factory = self.row('厂长')
        self.assertIn('production.curing.write', factory['actions'])
        self.assertIn('production.curing', factory['modules'])
        self.assertIn('production.issue', factory['modules'])
        self.assertEqual(len(self.audits), 1)
        self.assertEqual(self.audits[0][2], '补齐原辅料常用设置与生产页面授权')

    def test_is_idempotent(self):
        self.add('库管', ['inventory.materials'], ['materials.write'])
        self.run_step()
        version = self.c.execute("SELECT version FROM role_permissions WHERE role='库管'").fetchone()[0]
        self.run_step()
        self.assertEqual(self.c.execute("SELECT version FROM role_permissions WHERE role='库管'").fetchone()[0], version)
        self.assertEqual(len(self.audits), 1)


if __name__ == '__main__':
    unittest.main()
