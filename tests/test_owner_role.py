import sqlite3,unittest,json
import auth,erp_access as access
class OwnerRoleTests(unittest.TestCase):
    def test_legacy_role_constraints_migrate_without_losing_users_sessions_or_grants(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        c.execute("CREATE TABLE auth_users(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,display_name TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('管理员','库管','会计','出纳')),password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),must_change_password INTEGER NOT NULL DEFAULT 1 CHECK(must_change_password IN (0,1)),version INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)")
        c.execute('CREATE TABLE auth_sessions(id TEXT PRIMARY KEY,token_hash TEXT NOT NULL UNIQUE,csrf_hash TEXT NOT NULL,user_id TEXT NOT NULL REFERENCES auth_users(id),user_version INTEGER NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)')
        c.execute("INSERT INTO auth_users VALUES('u1','admin','管理员','管理员','unchanged-hash',1,0,1,100,100)")
        c.execute("INSERT INTO auth_sessions VALUES('s1','token-hash','csrf-hash','u1',1,100,9999999999)")
        c.execute("CREATE TABLE role_permissions(role TEXT PRIMARY KEY CHECK(role IN ('库管','会计','出纳')),version INTEGER NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL)")
        c.execute('INSERT INTO role_permissions VALUES(?,?,?,?)',('会计',3,json.dumps({'modules':['sales.orders'],'actions':['orders.write']}),'unchanged'))
        before=[dict(r) for r in c.execute('SELECT * FROM auth_users')];sessions=[dict(r) for r in c.execute('SELECT * FROM auth_sessions')]
        auth.init_schema(c);access.init_schema(c);auth.init_schema(c);access.init_schema(c)
        self.assertEqual(before,[dict(r) for r in c.execute('SELECT * FROM auth_users')]);self.assertEqual(sessions,[dict(r) for r in c.execute('SELECT * FROM auth_sessions')]);self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual(access.permissions(c,'会计')['version'],7);self.assertEqual(access.permissions(c,'会计')['actions'],['orders.write','finance.evidence','crates.write','assets.write','payroll.write']);self.assertEqual(access.permissions(c,'会计')['modules'],['workspace.dashboard','workspace.directory','sales.orders','asset.register','asset.crates','finance.payroll','delivery.providers','finance.transport-settlement','finance.receivables','system.parameters','workspace.report-map'])  # 读取时补齐动作所属页面（旧配置不写库）
        self.assertNotIn('workspace.report-map',json.loads(c.execute("SELECT payload FROM role_permissions WHERE role='会计'").fetchone()[0])['modules'])
        self.assertIn('老板',c.execute("SELECT sql FROM sqlite_master WHERE name='auth_users'").fetchone()[0]);self.assertIn('老板',c.execute("SELECT sql FROM sqlite_master WHERE name='role_permissions'").fetchone()[0]);c.close()
    def test_owner_is_read_only_and_has_business_financial_visibility(self):
        d=access.defaults('老板');self.assertEqual(d['actions'],[])
        self.assertTrue({'workspace.analytics','finance.receivables','finance.costs','finance.payables','purchase.orders','inventory.materials'}<=set(d['modules']));self.assertNotIn('system.users',d['modules']);self.assertNotIn('system.access',d['modules']);self.assertNotIn('system.audit',d['modules'])
        for a in access.action_definitions():self.assertFalse(access.role_can('老板',a['id']))
        # Preserve analytics records in scope even for a custom read-only analytics grant.
        r=access.scope_bootstrap({'orders':[{'total_cents':100,'id':'o'}],'resources':{},'purchasing':{},'receipts':[]}, {'role':'老板','permissions':{'modules':['workspace.analytics'],'actions':[]}})
        self.assertEqual(r['orders'][0]['total_cents'],100)
