"""Recent personnel features are represented in the permission UI and real HTTP gates."""
import unittest,uuid
import test_auth_http as fixture
from test_auth_http import Client,erp
import erp_access as access

class PersonnelPermissionTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def config(self,role):
        status,data,_=self.admin.request('/api/role-permissions');self.assertEqual(status,200);return next(r for r in data['roles'] if r['role']==role)
    def login(self,name):
        c=Client(self);self.assertEqual(c.request('/api/auth/login',{'username':name,'password':self.personal_password})[0],200);return c
    def post_staff(self,c):return c.request('/api/factory/contractor-staff',{'request_key':str(uuid.uuid4()),'name':'外包甲','contractor':'承包运输队'})
    def test_contractors_readonly_revoke_and_sessions(self):
        c,_=self.user('logistics','物流负责人');url='/api/factory/report?kind=contractor-personnel&month=2020-09&date=2020-09-03'
        self.assertEqual(c.request(url)[0],200);self.assertEqual(self.post_staff(c)[0],200)
        cfg=self.config('物流负责人');cfg['actions'].remove('delivery.contractors.write');self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],200)
        self.assertEqual(c.request(url)[0],401);c=self.login('logistics');self.assertEqual(c.request(url)[0],200);self.assertEqual(self.post_staff(c)[0],403)
        cfg=self.config('物流负责人');cfg['actions'].remove('delivery.contractors.read');self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],200)
        c=self.login('logistics');self.assertEqual(c.request(url)[0],403);self.assertIn('delivery.schedule',c.request('/api/bootstrap')[1]['permissions']['actions'])
    def test_dependencies_and_role_limits_are_enforced(self):
        cfg=self.config('物流负责人');cfg['actions'].remove('delivery.contractors.read');self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],400)
        cfg=self.config('库管');cfg['actions']+=['delivery.contractors.read','delivery.contractors.write'];self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],400)
        wh,_=self.user();self.assertEqual(self.post_staff(wh)[0],403)
        # Forged request context cannot bypass the role restriction even with a grant.
        token=access.GRANTS.set({'actions':['delivery.contractors.read','delivery.contractors.write']})
        try:self.assertFalse(access.role_can('库管','delivery.contractors.read'))
        finally:access.GRANTS.reset(token)
    def test_factory_staff_attendance_salary_and_cost_gates(self):
        director,_=self.user('director','厂长');body={'employee_type':'management','name':'管理甲','group_id':'','request_key':str(uuid.uuid4())}
        self.assertEqual(director.request('/api/factory/employee',body)[0],403)
        administrator,_=self.user('administrative','行政负责人');status,e,_=administrator.request('/api/factory/employee',body);self.assertEqual(status,200,e)
        self.assertEqual(director.request('/api/factory/employee',{**body,'request_key':str(uuid.uuid4()),'salary_mode':'annual','annual_salary':'36500'})[0],403)
        self.assertEqual(director.request('/api/factory/report?kind=payroll&month=2020-09')[0],403)
        self.assertEqual(director.request('/api/factory/wage-cost-post',{'month':'2020-09','request_key':str(uuid.uuid4())})[0],403)
        accountant,_=self.user('accountant','会计');self.assertEqual(accountant.request('/api/factory/wage-pay',{})[0],403)
        cashier,_=self.user('cashier','出纳');self.assertEqual(cashier.request('/api/factory/wage-sheet',{})[0],403)
        cfg=self.config('厂长');cfg['actions'].remove('production.attendance');self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],200)
        director=self.login('director');self.assertEqual(director.request('/api/factory/attendance-month-save',{})[0],403)
    def test_permission_page_catalog_has_recent_feature_map(self):
        status,c,_=self.admin.request('/api/role-permissions');self.assertEqual(status,200)
        self.assertEqual(c['action_dependencies']['delivery.contractors.write'],['delivery.contractors.read'])
        self.assertTrue(any('整月' in r['feature'] for r in c['feature_permissions']))
        self.assertTrue(any('工资成本' in r['feature'] for r in c['feature_permissions']))
        self.assertTrue(all(m['group']=='hr' for m in c['modules'] if m['id'] in ('production.staff','production.attendance','finance.payroll')))
        actions={a['id']:a for a in c['actions']};self.assertEqual(actions['delivery.contractors.write']['assignable_roles'],['物流负责人'])
        self.assertIn('归集成本',actions['payroll.write']['title'])
        for f in c['feature_permissions']:
            self.assertTrue(set(f['write'])<=set(actions));self.assertTrue(set(f['read'])<={m['id'] for m in c['modules']})
