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
    def test_secondary_actions_and_all_account_roles_are_projected(self):
        c=access.catalog();ids={a['id'] for a in c['actions']};mods={m['id'] for m in c['modules']}
        self.assertEqual(c['roles'],['管理员',*access.ACCOUNT_ROLES])
        for key in ('weight.write','materials.void','byproducts.receive','delivery.contractors.read','management.attendance','system.parameters'):
            self.assertIn(key,ids)
        for a in c['actions']:self.assertIn(a['module'],mods)
        self.assertEqual([a['id'] for a in c['actions'] if '老板' in a['roles']],[])
        admin={a['id'] for a in c['actions'] if '管理员' in a['roles']}
        self.assertTrue({'system.users','system.permissions','weight.write','orders.write'}<=admin)
    def test_require_covers_secondary_actions_and_rejects_unknown(self):
        access.require('库管','weight.write');access.require('会计','materials.void')
        with self.assertRaises(ValueError):
            access.require('库管','materials.void')
        with self.assertRaises(ValueError):
            access.require('库管','no.such.action')
    def test_catalog_roles_match_each_role_default_grants(self):
        # 匿名矩阵按岗位默认配置投影（与登录后 permissions() 一致），不再回读静态角色表
        for a in access.catalog()['actions']:
            for role in access.catalog()['roles']:
                self.assertEqual(role in a['roles'],a['id'] in access.defaults(role)['actions'],msg=(role,a['id']))
    def test_require_keeps_declared_role_table(self):
        declared={key:tuple(roles) for key,_,_,roles in [*access.ACTIONS,*access.EXTRA_ACTIONS]}
        for key in declared:
            for role in access.ROLES:
                if role in declared[key]:access.require(role,key)
                else:
                    with self.assertRaises(ValueError):access.require(role,key)
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
    def test_pilot_mode_uses_same_permission_table_as_accounts(self):
        cases=[('/api/resources/void',{'ledger':'material'}),('/api/resources/restore',{'ledger':'expense'}),('/api/resources/receive',{}),('/api/resources/item',{}),('/api/warehouse',{'stage':'confirm_dispatch'}),('/api/social-compensation',{}),('/api/stock-close',{})]
        for path,body in cases:
            for role in ['库管','会计','出纳','厂长','物流负责人','行政负责人']:
                pilot=accounts=False
                try:access.authorize(path,body,role)
                except ValueError:pilot=True
                try:access.authorize_authenticated(path,body,role)
                except Exception:accounts=True
                self.assertEqual(pilot,accounts,msg=(path,role))
    def test_pilot_mode_blocks_ledger_void_and_byproduct_receipt_for_warehouse(self):
        with self.assertRaises(ValueError):access.authorize('/api/resources/void',{'ledger':'material'},'库管')
        access.authorize('/api/resources/void',{'ledger':'material'},'会计')
        with self.assertRaises(ValueError):access.authorize('/api/resources/receive',{},'会计')
        access.authorize('/api/resources/receive',{},'出纳')
    def test_independent_material_modules_read_own_data_without_costs(self):
        for module,path in [('production.issue','/api/material-issue'),('production.workshop','/api/workshop')]:
            with self.subTest(module=module):
                grants={'modules':[module],'actions':[],'data_scopes':[]}
                access.authorize_read(path,{'role':'厂长','permissions':grants})
                value=access.scope_resources({'items':[{'id':'BAG','name':'包装袋','value_cents':100}], 'entries':[]},grants)
                self.assertEqual(value['items'][0]['id'],'BAG')
                self.assertNotIn('value_cents',value['items'][0])
                with self.assertRaises(Exception):
                    access.authorize_read('/api/material-issue' if module=='production.workshop' else '/api/workshop',{'role':'厂长','permissions':grants})
