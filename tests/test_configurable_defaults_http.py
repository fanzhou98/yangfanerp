"""Configurable wage defaults and packing catalogs obey actual account gates."""
import unittest
import json
import test_auth_http as fixture


class ConfigurableDefaultsHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_financial_catalog_read_and_write_gates(self):
        accountant,_=self.user('defaultaccountant','会计')
        cashier,_=self.user('defaultcashier','出纳')
        warehouse,_=self.user('defaultwarehouse','库管')
        for path in ('/api/social-compensation','/api/crate-packaging'):
            self.assertEqual(accountant.request(path)[0],200)
            self.assertEqual(warehouse.request(path)[0],200 if path=='/api/crate-packaging' else 403)
            self.assertEqual(warehouse.request(path,{})[0],403)
        self.assertEqual(cashier.request('/api/social-compensation')[0],200)
        self.assertEqual(cashier.request('/api/social-compensation',{})[0],403)
        self.assertEqual(cashier.request('/api/crate-packaging',{})[0],403)
        self.assertEqual(accountant.request('/api/social-compensation?month=bad')[0],400)
        self.assertEqual(accountant.request('/api/crate-packaging?unexpected=1')[0],400)

    def test_custom_catalog_and_versioned_social_defaults_save_over_http(self):
        accountant,_=self.user('settingsaccountant','会计')
        body={'version':0,'effective_month':'2099-01','social_base':'1000','social_company_rate':'10',
              'social_personal_rate':'2','adopt_employee_ids':[],'request_key':'SOCIAL-HTTP-1'}
        code,saved,_=accountant.request('/api/social-compensation',body)
        self.assertEqual(code,200,saved)
        self.assertEqual(saved['version'],1)
        self.assertEqual(accountant.request('/api/social-compensation',body)[1]['version'],1)
        code,report,_=accountant.request('/api/social-compensation?month=2099-01')
        self.assertEqual(code,200,report)
        self.assertEqual(report['active']['social_base_cents'],100000)
        settings={'version':0,'methods':[{'id':'METHOD-REUSABLE','name':'可复用纤维包','active':True}],
                  'default_method_id':'METHOD-REUSABLE','rules':[{'product_id':'P001','asset_id':'CR-WHITE',
                  'method_id':'METHOD-REUSABLE','customer_id':'','tare':'1.235'}]}
        code,saved,_=accountant.request('/api/crate-packaging',settings)
        self.assertEqual(code,200,saved)
        self.assertEqual(saved['methods'][0]['name'],'可复用纤维包')
        self.assertEqual(saved['rules'][0]['tare'],'1.235')
        self.assertEqual(accountant.request('/api/crate-packaging',settings)[0],400)

    def test_packing_order_roundtrip_preserves_snapshot_and_physical_count(self):
        import crate_packaging,trade
        erp=fixture.erp
        with erp.connect(True) as c:
            cfg=crate_packaging.save(c,{'version':0,'methods':[{'id':'M-LIGHT','name':'轻包材','active':True},{'id':'M-HEAVY','name':'重包材','active':True}],
                'default_method_id':'M-LIGHT','rules':[{'product_id':'P001','asset_id':'CR-WHITE','method_id':'M-LIGHT','tare':'2'},
                {'product_id':'P001','asset_id':'CR-WHITE','method_id':'M-HEAVY','tare':'2.501'}]},'管理员',erp.now,erp.audit)
            order=erp.mutate('order',{'customer_id':'C001','business_date':'2020-10-01','batch':'包装分项HTTP',
                'lines':[{'product_id':'P001','ordered_qty':'10','actual_qty':'10','price':'3','driver':[],'customer':[{'gross':'100','count':'10','tare':'2'}],
                'crate_lines':[{'asset_id':'CR-WHITE','qty':10,'tare':'2'}]}]},'管理员',connection=c)
        line=order['lines'][0]
        line['crate_lines'][0]['packing_lines']=[{'method_id':'M-LIGHT','qty':8,'tare':'2'},{'method_id':'M-HEAVY','qty':2,'tare':'2.501'}]
        line['auto_crate']=True
        code,saved,_=self.admin.request('/api/orders/'+order['id']+'/order',order)
        self.assertEqual(code,200,saved)
        with erp.connect() as c:
            current=erp.get_order(c,order['id']);crates=current['lines'][0]['crate_lines']
            self.assertEqual(str(crate_packaging.total_tare(crates[0])),'21.002')
            self.assertEqual(current['lines'][0]['customer_net'],'78.998')
            self.assertEqual([(r['asset_id'],r['qty']) for r in trade.shipped_crates(c,current)],[('CR-WHITE',10)])
        with erp.connect(True) as c:
            crate_packaging.save(c,{**cfg,'methods':[{**m,'active':False} for m in cfg['methods']],
                'default_method_id':'','rules':[]},'管理员',erp.now,erp.audit)
        code,resaved,_=self.admin.request('/api/orders/'+order['id']+'/order',current)
        self.assertEqual(code,200,resaved)

    def test_order_editor_without_weight_permission_cannot_change_packing(self):
        import copy
        erp=fixture.erp
        with erp.connect(True) as c:
            grants=erp.erp_access.defaults('库管');grants['actions']=['orders.write']
            c.execute("INSERT INTO role_permissions(role,version,payload,updated_at) VALUES('库管',1,?,?) ON CONFLICT(role) DO UPDATE SET version=excluded.version,payload=excluded.payload,updated_at=excluded.updated_at",(json.dumps(grants),erp.now()))
            order=erp.mutate('order',{'customer_id':'C001','business_date':'2020-10-01','batch':'称重权限',
                'lines':[{'product_id':'P001','ordered_qty':'10','actual_qty':'10','price':'3','driver':[],'customer':[],
                'crate_lines':[{'asset_id':'CR-WHITE','qty':10,'tare':'2'}]}]},'管理员',connection=c)
        editor,_=self.user('orderonly','库管')
        changed=copy.deepcopy(order);changed['lines'][0]['crate_lines'][0]['tare']='9'
        code,result,_=editor.request('/api/orders/'+order['id']+'/order',changed)
        self.assertEqual(code,400,result)
        self.assertIn('不能更改实发或原始称重',result['error'])
        with erp.connect() as c:self.assertEqual(erp.get_order(c,order['id']),order)
