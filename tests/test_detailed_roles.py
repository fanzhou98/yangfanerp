"""Role and field boundaries at real authenticated HTTP endpoints."""
import json,unittest
import test_auth_http as fixture
from test_auth_http import erp
import erp_access as access

class DetailedRoleTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    order_body=fixture.AuthHTTPTests.order_body
    def test_warehouse_can_save_without_seeing_prices_but_cannot_forge_them(self):
        wh,_=self.user();b=self.order_body();b['lines'][0].pop('price')
        code,order,_=wh.request('/api/orders',b);self.assertEqual(code,200,order);self.assertNotIn('price',json.dumps(order))
        code,bootstrap,_=wh.request('/api/bootstrap');self.assertEqual(code,200)
        for key in ('orders','products','rules'):self.assertNotIn('"price"',json.dumps(bootstrap[key]))
        self.assertNotIn('_cents',json.dumps(bootstrap['purchasing']));self.assertEqual(bootstrap['resources']['expenses'],[])
        b['version']=order['version'];b['lines'][0]['ordered_qty']='3'
        code,updated,_=wh.request('/api/orders/'+order['id']+'/order',b);self.assertEqual(code,200,updated)
        self.assertNotIn('"price"',json.dumps(updated))
        with erp.connect() as c:self.assertEqual(erp.get_order(c,order['id'])['lines'][0]['price'],'75')
        b['version']=updated['version'];b['lines'][0]['price']='1'
        self.assertEqual(wh.request('/api/orders/'+order['id']+'/order',b)[0],400)
        for path in ('/api/master','/api/resources/item','/api/resources/void','/api/purchasing/charge','/api/purchasing/payment'):
            self.assertEqual(wh.request(path,{} if not path.endswith('/void') else {'ledger':'material'})[0],403,path)
    def test_accountant_can_transcribe_driver_weights_but_cannot_confirm_cash(self):
        accountant,_=self.user('accountant','会计');b=self.order_body()
        code,order,_=self.admin.request('/api/orders',b);self.assertEqual(code,200,order)
        data=self.admin.request('/api/bootstrap')[1];day=order['business_date']
        stock={'business_date':day,'version':0,'inventory_revision':data['inventory_revision'],'stage':'stock','stock':[{'product_id':'P004','existing_qty':'3','produced_qty':'0'}],'allocations':[],'order_versions':{o['id']:o['version'] for o in data['orders'] if o['business_date']==day}}
        code,plan,_=self.admin.request('/api/warehouse',stock);self.assertEqual(code,200,plan);plan=plan.get('plan',plan)
        data=self.admin.request('/api/bootstrap')[1]
        code,dispatch,_=self.admin.request('/api/warehouse',{**plan,'stage':'confirm_dispatch','evidence_checked':True,'inventory_revision':data['inventory_revision'],'order_versions':{o['id']:o['version'] for o in data['orders'] if o['business_date']==day}});self.assertEqual(code,200,dispatch)
        b=next(o for o in dispatch['orders'] if o['id']==order['id']);b['lines'][0]['package_net_kg']='21'
        code,updated,_=accountant.request('/api/orders/'+order['id']+'/order',b);self.assertEqual(code,200,updated);self.assertEqual(updated['lines'][0]['package_net_kg'],'21')
        for path in ('/api/orders/'+order['id']+'/receipt','/api/purchasing/payment','/api/purchasing/receipt','/api/resources/receive'):
            self.assertEqual(accountant.request(path,{})[0],403,path)
        with erp.connect() as c:self.assertEqual(erp.get_order(c,order['id'])['lines'][0]['actual_qty'],'2')
    def test_cashier_only_sees_and_handles_relevant_financial_ledgers(self):
        cash,_=self.user('cashier','出纳');data=cash.request('/api/bootstrap')[1]
        self.assertNotIn('workspace.analytics',data['permissions']['modules']);self.assertNotIn('finance.costs',data['permissions']['modules'])
        self.assertEqual(data['resources']['items'],[]);self.assertEqual(data['resources']['expenses'],[])
        self.assertEqual(cash.request('/api/inventory')[0],403)
        for path in ('/api/master','/api/purchasing/order','/api/purchasing/charge','/api/resources/expense','/api/resources/period','/api/resources/byproduct'):
            self.assertEqual(cash.request(path,{})[0],403,path)
    def test_customer_maintenance_does_not_grant_product_or_price_maintenance(self):
        employee,_=self.user('accountant','会计');cfg=next(r for r in self.admin.request('/api/role-permissions')[1]['roles'] if r['role']=='会计')
        body={**cfg,'modules':['workspace.directory','master.customers'],'actions':['master.customers.write'],'data_scopes':[]}
        code,result,_=self.admin.request('/api/role-permissions',body);self.assertEqual(code,200,result)
        self.assertEqual(employee.request('/api/bootstrap')[0],401)
        self.assertEqual(employee.request('/api/auth/login',{'username':'accountant','password':self.personal_password})[0],200)
        code,new,_=employee.request('/api/master',{'kind':'customer','create':True,'name':'档案权限测试客户','route':'权限测试市场'});self.assertEqual(code,200,new)
        for path,b in [('/api/master',{'kind':'product'}),('/api/master',{'kind':'rule'}),('/api/master/batch-rules',{'rules':[]}),('/api/master/product-order',{})]:
            self.assertEqual(employee.request(path,b)[0],403,(path,b))
        bootstrap=employee.request('/api/bootstrap')[1];self.assertEqual(bootstrap['orders'],[]);self.assertEqual(bootstrap['warehouse_plans'],[]);self.assertNotIn('"price"',json.dumps(bootstrap['products']))
    def test_sensitive_data_scope_and_business_action_must_be_granted_together(self):
        cfg=next(r for r in self.admin.request('/api/role-permissions')[1]['roles'] if r['role']=='库管')
        cfg['modules'].append('finance.receivables');cfg['actions'].append('finance.receipt')
        self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],400)
        cfg['data_scopes'].append('sales-prices');self.assertEqual(self.admin.request('/api/role-permissions',cfg)[0],200)
        self.assertEqual(access.defaults('老板')['actions'],[])
        self.assertEqual(set(access.defaults('管理员')['actions']),{a['id'] for a in access.action_definitions()})
