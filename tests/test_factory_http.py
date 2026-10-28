import unittest,uuid
import test_auth_http as fixture

erp=fixture.erp
class FactoryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_director_daily_report_and_finance_settings_boundary(self):
        director,_=self.user('director','厂长')
        code,data,_=director.request('/api/bootstrap');self.assertEqual(code,200)
        self.assertNotIn('receivable_days',str(data['factory']));self.assertEqual(data['receivable_alerts'],[])
        for kind in ('finance-settings','sales','weights'):self.assertEqual(director.request('/api/factory/report?kind='+kind)[0],403)
        self.assertEqual(director.request('/api/factory/finance-settings',{'version':1,'receivable_days':'7'})[0],403)
        self.assertEqual(director.request('/api/factory/settings',{'version':1,'receivable_days':'7'})[0],400)
        body={'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','systems':{'tofu':{'soak_tanks':'1'},'skin':{'soak_tanks':'1'}},'products':[]}
        self.assertEqual(director.request('/api/factory/daily',body)[0],200)
        code,report,_=director.request('/api/factory/report?kind=daily&date=2026-10-20');self.assertEqual(code,200);self.assertNotIn('receivable_days',str(report));self.assertNotIn('value_cents',str(report))
        accountant,_=self.user('accountant','会计')
        code,settings,_=accountant.request('/api/factory/report?kind=finance-settings');self.assertEqual(code,200)
        self.assertEqual(accountant.request('/api/factory/finance-settings',{'version':settings['version'],'receivable_days':'7'})[0],400)
        request=self.request_parameter(accountant,'receivable_days','7')
        self.assertEqual(request['status'],'pending')
        self.assertEqual(self.catalog(self.admin)['settings']['receivable_days'],'5')
        self.assertEqual(self.review(self.admin,request,'approve')[0],200)
        self.assertEqual(self.catalog(self.admin)['settings']['receivable_days'],'7')

    def catalog(self,client):
        code,result,_=client.request('/api/factory/report?kind=system-settings');self.assertEqual(code,200,result);return result

    def request_parameter(self,client,key,value):
        catalog=self.catalog(client)
        body={'request_key':str(uuid.uuid4()),'version':catalog['settings']['version'],'key':key,'value':value,'reason':'核对后申请修改'}
        code,result,_=client.request('/api/factory/parameter-request',body);self.assertEqual(code,200,result)
        again=client.request('/api/factory/parameter-request',body);self.assertEqual(again[0],200);self.assertEqual(again[1]['id'],result['id'])
        return result

    def review(self,client,request,decision,reason='已核对'):
        return client.request('/api/factory/parameter-review',{'id':request['id'],'version':request['version'],'decision':decision,'reason':reason})

    def test_parameter_visibility_and_request_permission_follow_business_roles(self):
        admin=self.catalog(self.admin);keys=[i['key'] for g in admin['groups'] for i in g['items']]
        self.assertEqual(set(keys),set(admin['defaults']));self.assertEqual(len(keys),15)
        for role,name in [('库管','params_wh'),('会计','params_acc'),('出纳','params_cash'),('厂长','params_dir'),('物流负责人','params_log'),('老板','params_owner')]:
            client,user=self.user(name,role)
            catalog=self.catalog(client);self.assertFalse(catalog['can_review'])
            visible=[i for g in catalog['groups'] for i in g['items']]
            self.assertTrue(visible)
            finance='receivable_days' in catalog['settings']
            self.assertEqual(finance,role in ('会计','出纳','老板'))
            editable={i['key'] for i in visible if i['can_request']}
            self.assertEqual(editable,{'receivable_days','receivable_limit_yuan'} if role in ('会计','出纳') else set(keys)-{'receivable_days','receivable_limit_yuan'} if role=='厂长' else set())
            self.assertEqual(client.request('/api/factory/parameter-review',{'id':'none','version':1,'decision':'approve'})[0],403)
            bootstrap=client.request('/api/bootstrap')[1];self.assertIn('system.parameters',bootstrap['permissions']['modules'])
        driver,_=self.user('params_driver','司机')
        self.assertEqual(driver.request('/api/factory/report?kind=system-settings')[0],403)
        self.assertNotIn('system.parameters',driver.request('/api/bootstrap')[1]['permissions']['modules'])

    def test_parameter_approval_validation_and_conflict_do_not_overwrite(self):
        director,_=self.user('params_director','厂长');accountant,_=self.user('params_accountant','会计')
        catalog=self.catalog(self.admin);version=catalog['settings']['version']
        for bad in ('-1','101','',None,'abc'):
            code,_,_=self.admin.request('/api/factory/parameter-request',{'version':version,'request_key':str(uuid.uuid4()),'key':'average_weight_alert_pct','value':bad,'reason':'测试'});self.assertEqual(code,400)
        for kind in ('settings','finance-settings','system-settings'):
            self.assertEqual(self.admin.request('/api/factory/'+kind,{'version':version,'average_weight_alert_pct':'30'})[0],400)
        self.assertEqual(accountant.request('/api/factory/parameter-request',{'version':version,'request_key':str(uuid.uuid4()),'key':'average_weight_alert_pct','value':'20','reason':'测试'})[0],403)
        request=self.request_parameter(director,'average_weight_alert_pct','20')
        self.assertEqual(request['requester_id'],self.catalog(director)['requests'][0]['requester_id'])
        self.assertEqual(self.catalog(self.admin)['settings']['average_weight_alert_pct'],'10')
        self.assertEqual(self.catalog(accountant)['requests'],[])
        concurrent=self.request_parameter(self.admin,'average_weight_alert_pct','30')
        # An unrelated approved parameter does not invalidate this request.
        finance=self.request_parameter(accountant,'receivable_days','8');self.assertEqual(self.review(self.admin,finance,'approve')[0],200)
        self.assertEqual(self.review(self.admin,request,'approve')[0],200)
        self.assertEqual(self.catalog(self.admin)['settings']['average_weight_alert_pct'],'20')
        self.assertEqual(self.review(self.admin,request,'approve')[0],400)
        self.assertEqual(self.review(self.admin,concurrent,'approve')[0],400)
        self.assertEqual(self.review(self.admin,concurrent,'reject','')[0],400)
        self.assertEqual(self.review(self.admin,concurrent,'reject','与已批准参数冲突')[0],200)
        final=self.catalog(self.admin);self.assertEqual(final['settings']['average_weight_alert_pct'],'20');self.assertEqual(final['settings']['receivable_days'],'8')
        self.assertEqual({r['status'] for r in final['requests']},{'approved','rejected'})
        bootstrap=director.request('/api/bootstrap')[1];self.assertEqual(bootstrap['weighing_settings']['average_weight_alert_pct'],'20')

    def test_parameter_page_removed_when_business_view_is_revoked(self):
        warehouse,_=self.user('minimal_params','库管')
        self.catalog(warehouse)
        configs=self.admin.request('/api/role-permissions')[1]['roles'];cfg=next(c for c in configs if c['role']=='库管')
        # The derived page name cannot grant access without a relevant business module.
        cfg.update(modules=['workspace.dashboard','workspace.directory','system.parameters'],actions=[],data_scopes=[])
        self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],200)
        self.assertEqual(warehouse.request('/api/bootstrap')[0],401)
        self.assertEqual(warehouse.request('/api/auth/login',{'username':'minimal_params','password':self.personal_password})[0],200)
        self.assertNotIn('system.parameters',warehouse.request('/api/bootstrap')[1]['permissions']['modules'])
        self.assertEqual(warehouse.request('/api/factory/report?kind=system-settings')[0],403)
