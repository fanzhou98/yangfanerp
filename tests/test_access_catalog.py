import unittest
import erp_access as access

class AccessCatalogTests(unittest.TestCase):
    def test_unique_stable_modules_and_valid_action_ownership(self):
        c=access.catalog();modules={m['id'] for m in c['modules']};groups={g['id'] for g in c['groups']}
        self.assertEqual(len(modules),len(c['modules']))
        self.assertEqual(len({a['id'] for a in c['actions']}),len(c['actions']))
        for m in c['modules']: self.assertIn(m['group'],groups)
        for a in c['actions']:
            self.assertIn(a['module'],modules)
            self.assertTrue(set(a['roles'])<=set(c['roles']))
        self.assertFalse(c['authenticated']);self.assertEqual(c['read_scope'],'shared')
    def test_every_role_matches_each_declared_action(self):
        for a in access.catalog()['actions']:
            for role in access.ROLES:
                if role in a['roles']:access.require(role,a['id'])
                else:
                    with self.assertRaises(ValueError):access.require(role,a['id'])
    def test_atomic_batch_cannot_mix_unauthorized_action_or_update(self):
        with self.assertRaises(ValueError):
            access.authorize('/api/batch',{'operations':[{'action':'order'},{'action':'settle'}]},'库管')
        with self.assertRaises(ValueError):
            access.authorize('/api/batch',{'operations':[{'action':'review','update':{}}]},'出纳')
        access.authorize('/api/batch',{'operations':[{'action':'settle','update':{}}]},'会计')
    def test_sensitive_routes_have_separate_permissions(self):
        for path,body,role in [('/api/warehouse',{'stage':'confirm_dispatch'},'出纳'),('/api/stock-close',{},'出纳'),('/api/returns/action',{'action':'review'},'会计'),('/api/returns/action',{'action':'refund'},'库管'),('/api/master',{},'库管'),('/api/backup',{},'出纳'),('/api/trial-data',{},'库管')]:
            with self.subTest(path=path,body=body):
                with self.assertRaises(ValueError):access.authorize(path,body,role)
