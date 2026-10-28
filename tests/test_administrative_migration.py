import unittest,tempfile,time,json
from pathlib import Path
from unittest.mock import patch
import server,auth,migrations,erp_access

class AdministrativeMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_account_hashes_sessions_and_existing_grants(self):
        with tempfile.TemporaryDirectory() as td:
            specs=migrations.registry();old=specs[:next(i for i,m in enumerate(specs) if m.id=='063-administrative-role')]
            with patch.object(server,'DB',Path(td)/'test.db'):
                with patch.object(migrations,'registry',lambda:old):server.init_db()
                with server.connect(True) as c:
                    now=int(time.time());admin=auth.create_initial_admin(c,'admin','管理员','Migration-Test-2026!',now);login=auth.login(c,'admin','Migration-Test-2026!','127.0.0.1',now)
                    cfg={'modules':['production.staff','production.attendance'],'actions':['production.staff','production.attendance'],'data_scopes':[]};c.execute('INSERT INTO role_permissions VALUES(?,?,?,?)',('厂长',1,json.dumps(cfg),str(now)))
                    before={t:[tuple(r) for r in c.execute('SELECT * FROM '+t)] for t in ('auth_users','auth_sessions','auth_session_activity','role_permissions')}
                    migrations.ensure(c)
                    for t,rows in before.items():self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM '+t)],rows,t)
                    self.assertTrue(auth.authenticate(c,login['token'],now));self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
                    created=auth.create_user(c,admin,{'username':'administrative','display_name':'行政负责人','role':'行政负责人','password':'Administrative-2026!','active':True},now)
                    self.assertEqual(created['role'],'行政负责人');self.assertEqual(set(erp_access.defaults('行政负责人')['actions']),{'management.staff','management.attendance'})
