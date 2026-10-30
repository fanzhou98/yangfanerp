"""Owner administrator and configurable staff roles at the real HTTP boundary."""
import unittest,uuid
import test_auth_http as fixture
from test_auth_http import Client,erp

class RolePermissionTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    order_body=fixture.AuthHTTPTests.order_body

    def config(self,role='库管'):
        code,result,_=self.admin.request('/api/role-permissions');self.assertEqual(code,200,result)
        return next(r for r in result['roles'] if r['role']==role)

    def login_user(self,name='warehouse'):
        client=Client(self)
        code,value,_=client.request('/api/auth/login',{'username':name,'password':self.personal_password})
        self.assertEqual(code,200,value)
        return client

    def test_owner_admin_can_complete_dispatch_account_review_receipt_and_statement(self):
        code,o,_=self.admin.request('/api/orders',self.order_body());self.assertEqual(code,200,o)
        code,data,_=self.admin.request('/api/bootstrap');self.assertEqual(code,200)
        self.assertEqual(len(data['permissions']['actions']),len(erp.erp_access.action_definitions()))
        day=o['business_date']
        body={'business_date':day,'version':0,'inventory_revision':data['inventory_revision'],'stage':'stock','stock':[{'product_id':'P004','existing_qty':'3','produced_qty':'0'}],'allocations':[],'order_versions':{r['id']:r['version'] for r in data['orders'] if r['business_date']==day}}
        code,result,_=self.admin.request('/api/warehouse',body);self.assertEqual(code,200,result)
        plan=result.get('plan',result)
        code,data,_=self.admin.request('/api/bootstrap')
        body={**plan,'stage':'confirm_dispatch','evidence_checked':True,'inventory_revision':data['inventory_revision'],'order_versions':{r['id']:r['version'] for r in data['orders'] if r['business_date']==day}}
        code,result,_=self.admin.request('/api/warehouse',body);self.assertEqual(code,200,result)
        o=next(r for r in result['orders'] if r['id']==o['id'])
        for action,extra in [('confirm-weight',{'evidence_checked':True}),('settle',{'mode':'customer'}),('review',{'evidence_checked':True}),('receipt',{'amount':'1','received_date':day,'method':'现金'})]:
            code,o,_=self.admin.request('/api/orders/'+o['id']+'/'+action,{'version':o['version'],**extra});self.assertEqual(code,200,o)
        self.assertEqual(o['paid_cents'],100)
        code,draft,_=self.admin.request('/api/customer-statement?customer_id=C001&date='+day);self.assertEqual(code,200,draft)
        code,issued,_=self.admin.request('/api/statements/issue',{'customer_id':'C001','business_date':day,'source_fingerprint':draft['source_fingerprint'],'request_key':str(uuid.uuid4()),'seller_name':'测试厂','buyer_name':'测试客户','operator_user_id':'OP-CASHIER','identity_checked':True})
        self.assertEqual(code,200,issued);self.assertEqual(issued['issued_by'],'管理员')
        with erp.connect() as c:
            entries=[dict(r) for r in c.execute('SELECT role,actor_id,actor_name FROM audit WHERE entity=?',(o['id'],))]
        self.assertTrue(entries);self.assertTrue(all(r['role']=='管理员' and r['actor_id']==self.admin_user['id'] for r in entries))

    def test_grant_and_revoke_are_effective_in_api_and_existing_sessions(self):
        staff,_=self.user()
        self.assertEqual(staff.request('/api/export')[0],403)
        cfg=self.config();cfg['modules'].append('finance.receivables');cfg['actions'].append('finance.receipt');cfg['data_scopes'].append('sales-prices')
        code,result,_=self.admin.request('/api/role-permissions',cfg);self.assertEqual(code,200,result);self.assertEqual(result['revoked_sessions'],1)
        self.assertEqual(staff.request('/api/bootstrap')[0],401)
        staff=self.login_user();self.assertEqual(staff.request('/api/export')[0],200)
        data=staff.request('/api/bootstrap')[1]
        self.assertIn('finance.receipt',data['permissions']['actions'])
        o=next(o for o in data['orders'] if o['state']=='reviewed')
        code,o,_=staff.request('/api/orders/'+o['id']+'/receipt',{'version':o['version'],'amount':'1','method':'现金','received_date':data['today']});self.assertEqual(code,200,o)
        cfg=self.config();cfg['actions'].remove('finance.receipt')
        code,result,_=self.admin.request('/api/role-permissions',cfg);self.assertEqual(code,200,result)
        self.assertEqual(staff.request('/api/bootstrap')[0],401)
        staff=self.login_user();self.assertEqual(staff.request('/api/orders/'+o['id']+'/receipt',{'version':o['version'],'amount':'1','method':'现金','received_date':data['today']})[0],403)
        self.assertEqual(self.admin.request('/api/users')[0],200)

    def test_permissions_cannot_escalate_admin_or_bypass_revision(self):
        staff,_=self.user();cfg=self.config()
        self.assertEqual(staff.request('/api/role-permissions',cfg,role='accountant')[0],403)
        self.assertEqual(staff.request('/api/role-permissions')[0],403)
        for update in [{'role':'管理员'},{'actions':['not.real']},{'modules':['system.users']},{'actions':['system.permissions']},{'actions':['system.parameters']}]:
            code,_,_=self.admin.request('/api/role-permissions',{**cfg,**update});self.assertEqual(code,400)
        code,result,_=self.admin.request('/api/role-permissions',cfg);self.assertEqual(code,200,result)
        self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],409)
        with erp.connect() as c:
            event=c.execute("SELECT actor_id FROM security_events WHERE action='permissions.update' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(event['actor_id'],self.admin_user['id'])

    def test_removing_write_permission_blocks_real_writes_not_only_menu(self):
        staff,_=self.user();cfg=self.config();cfg['actions'].remove('orders.write')
        code,result,_=self.admin.request('/api/role-permissions',cfg);self.assertEqual(code,200,result)
        staff=self.login_user();self.assertEqual(staff.request('/api/orders',self.order_body())[0],403)
        self.assertEqual(staff.request('/api/batch',{'operations':[{'action':'order','body':self.order_body()}]})[0],403)
        data=staff.request('/api/bootstrap')[1];self.assertIn('sales.orders',data['permissions']['modules']);self.assertNotIn('orders.write',data['permissions']['actions'])

    def test_material_issue_uses_its_own_page_module_not_bean_records(self):
        cfg=self.config('厂长');self.assertIn('materials.issue',cfg['actions'])
        self.assertIn('production.issue',cfg['modules'])
        cfg['modules']=[m for m in cfg['modules'] if m!='production.issue']
        code,body,_=self.admin.request('/api/role-permissions',cfg);self.assertEqual(code,400,body)
        self.assertIn('查看权限',str(body))
        cfg['modules'].append('production.issue')
        cfg['actions'].remove('production.record')
        cfg['modules']=[m for m in cfg['modules'] if m!='production.manage']
        code,result,_=self.admin.request('/api/role-permissions',cfg);self.assertEqual(code,200,result)
        saved=self.config('厂长');self.assertIn('production.issue',saved['modules']);self.assertNotIn('production.manage',saved['modules']);self.assertIn('materials.issue',saved['actions'])

    def test_saved_role_without_new_page_module_keeps_action_page_visible(self):
        import json
        payload={'role':'库管','modules':['workspace.dashboard','inventory.materials'],'actions':['materials.issue'],'data_scopes':[]}
        with erp.connect(True) as c:
            c.execute('INSERT INTO role_permissions(role,version,payload,updated_at) VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET version=excluded.version,payload=excluded.payload',('库管',1,json.dumps(payload,ensure_ascii=False),'2026-10-31T00:00:00+08:00'))
        cfg=self.config('库管');self.assertIn('production.issue',cfg['modules']);self.assertIn('inventory.materials',cfg['modules'])

    def test_saved_role_repairs_pages_for_secondary_action_table_without_admin_escalation(self):
        import json
        def save(role,parts):
            payload={'role':role,**parts}
            with erp.connect(True) as c:
                c.execute('INSERT INTO role_permissions(role,version,payload,updated_at) VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET version=excluded.version,payload=excluded.payload',(role,1,json.dumps(payload,ensure_ascii=False),'2026-10-31T00:00:00+08:00'))
        save('库管',{'modules':['workspace.dashboard','sales.orders'],'actions':['weight.write','materials.void'],'data_scopes':[]})
        cfg=self.config('库管');self.assertIn('delivery.weighing',cfg['modules']);self.assertIn('inventory.materials',cfg['modules'])
        save('会计',{'modules':['workspace.dashboard'],'actions':['system.permissions','system.parameters'],'data_scopes':[]})
        cfg=self.config('会计');self.assertNotIn('system.access',cfg['modules']);self.assertNotIn('system.users',cfg['modules'])

    def test_dependencies_and_financial_read_cannot_be_skipped(self):
        cfg=self.config();cfg['actions'].append('finance.review')
        self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],400)
        cfg=self.config();cfg['actions'].remove('inventory.stock')
        self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],400)

if __name__=='__main__':unittest.main()
