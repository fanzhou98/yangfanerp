import unittest,uuid
import test_auth_http as fixture
import resources_costs as rc

erp=fixture.erp
class MaterialAllocationHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_report_permission_and_explicit_cost_scope(self):
        for name,role,expected in [('acc_allocation','会计',200),('director_allocation','厂长',403),('warehouse_allocation','库管',403),('cash_allocation','出纳',403),('owner_allocation','老板',200)]:
            client,_=self.user(name,role);self.assertEqual(client.request('/api/factory/report?kind=material-costs&date=2026-10-01')[0],expected)
        with erp.connect(True) as c:
            old=erp.erp_access.permissions(c,'会计')
            erp.erp_access.save_permissions(c,self.admin_user,{'role':'会计','version':old['version'],'modules':['inventory.cost'],'actions':[],'data_scopes':[]},erp.now,erp.audit)
        from test_auth_http import Client
        limited=Client(self);self.assertEqual(limited.request('/api/auth/login',{'username':'acc_allocation','password':self.personal_password})[0],200)
        self.assertEqual(limited.request('/api/factory/report?kind=material-costs&date=2026-10-01')[0],403)
    def test_new_mutation_checks_role_csrf_and_version(self):
        with erp.connect(True) as c:
            ops=rc.Operations(c,erp.now,erp.audit)
            for kind in ('receipt','consume'):
                e=ops.material({'material_id':'A-SALT','warehouse_id':'WH-COMMON','business_date':'2026-10-20','kind':kind,'qty':'1','amount':'10' if kind=='receipt' else '0','revision':rc.revision(c),'request_key':str(uuid.uuid4()),'handler':'会计','note':'验收'},'管理员')
            revision=rc.revision(c)
        accountant,_=self.user('acc_attribute','会计');warehouse,_=self.user('wh_attribute','库管')
        b={'id':e['id'],'version':1,'revision':revision,'product_id':'P001','cost_target':'共用','note':'凭据更正'}
        self.assertEqual(warehouse.request('/api/resources/attribute',b)[0],403)
        self.assertEqual(accountant.request('/api/resources/attribute',b,csrf=False)[0],403)
        code,result,_=accountant.request('/api/resources/attribute',b);self.assertEqual(code,200,result);self.assertEqual(result['product_id'],'P001')
        self.assertEqual(accountant.request('/api/resources/attribute',b)[0],400)
        # 只读报表仍受读权限限制，参数错误回 400。
        self.assertEqual(accountant.request('/api/factory/report?kind=material-costs&date=bad')[0],400)
