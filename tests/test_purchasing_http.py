import unittest,uuid,json
import test_auth_http as fixture

erp=fixture.erp
class PurchaseHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def post(self,path,b,client=None):
        status,result,_=(client or self.admin).request('/api/purchasing/'+path,b);self.assertEqual(status,200,result);return result
    def test_authenticated_purchase_stock_payables_and_rollback(self):
        wh,user=self.user();cash,_=self.user('cashier','出纳')
        sid=self.post('supplier',{'name':'真实权限测试供应商','payment_days':30})['id']
        oid=self.post('order',{'request_key':str(uuid.uuid4()),'supplier_id':sid,'business_date':'2026-10-01','expected_date':'2026-10-02','handler':'采购','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'100','price':'4.6'}]})['id']
        self.post('confirm',{'id':oid,'version':1})
        code,snapshot,_=wh.request('/api/bootstrap');self.assertEqual(code,200,snapshot);self.assertNotIn('"price"',json.dumps(snapshot['purchasing']));self.assertNotIn('_cents',json.dumps(snapshot['purchasing']))
        b={'id':oid,'version':2,'revision':snapshot['resources']['revision'],'request_key':'receipt','business_date':'2026-10-02','handler':'验收员','note':'验收入库','lines':[{'line_id':'L1','qty':'40'}]}
        status,error,_=wh.request('/api/purchasing/receipt',{**b,'lines':b['lines']+[{'line_id':'BAD','qty':'1'}]});self.assertEqual(status,400,error)
        with erp.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM material_entries').fetchone()[0],0)
        self.post('receipt',b,wh);self.post('receipt',b,wh)
        code,redacted,_=wh.request('/api/purchasing');self.assertEqual(code,200);self.assertNotIn('_cents',json.dumps(redacted));self.assertEqual(redacted['orders'][0]['lines'][0]['received_qty'],'40')
        self.assertEqual(wh.request('/api/purchasing/payment',{})[0],403);self.assertEqual(cash.request('/api/purchasing/order',{})[0],403)
        self.assertEqual(wh.request('/api/purchasing/receipt',{**b,'request_key':'no-csrf'},csrf=False)[0],403)
        self.post('payment',{'id':oid,'version':3,'request_key':'payment','business_date':'2026-10-02','amount':'84','method':'现金','handler':'出纳','note':'付款'},cash)
        owner,_=self.user('owner_cost','老板')
        code,result,_=owner.request('/api/bootstrap');self.assertEqual(code,200,result)
        o=next(o for o in result['purchasing']['orders'] if o['id']==oid);self.assertEqual(o['received_cents'],18400);self.assertEqual(o['outstanding_cents'],10000)
        self.assertEqual(next(i for i in result['resources']['items'] if i['id']=='RM-SOY')['value_cents'],18400)
        with erp.connect() as c:
            row=c.execute("SELECT actor_id FROM audit WHERE action='登记采购验收单' ORDER BY id DESC LIMIT 1").fetchone();self.assertEqual(row['actor_id'],user['id'])
    def test_purchase_only_grants_and_scope(self):
        accountant,_=self.user('accountant','会计')
        code,g,_=self.admin.request('/api/role-permissions');self.assertEqual(code,200,g)
        cfg=next(r for r in g['roles'] if r['role']=='会计')
        status,result,_=self.admin.request('/api/role-permissions',{'role':'会计','version':cfg['version'],'modules':['workspace.directory','master.suppliers','purchase.orders','purchase.receipts'],'actions':['suppliers.write','purchases.write','purchases.receive']});self.assertEqual(status,200,result)
        self.assertEqual(accountant.request('/api/bootstrap')[0],401)
        self.assertEqual(accountant.request('/api/auth/login',{'username':'accountant','password':self.personal_password})[0],200)
        sid=self.post('supplier',{'name':'采购独立授权供应商','payment_days':0},accountant)['id']
        self.post('order',{'request_key':'only-order','supplier_id':sid,'business_date':'2026-10-01','expected_date':'2026-10-02','handler':'采购','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'100','price':'4.6'}]},accountant)
        code,data,_=accountant.request('/api/bootstrap');self.assertEqual(code,200,data);self.assertTrue(data['resources']['items']);self.assertEqual(data['purchasing']['orders'][0]['total_cents'],46000);self.assertEqual(data['orders'],[])
    def test_owner_can_read_company_finances_but_cannot_mutate(self):
        owner,_=self.user('owner','老板')
        code,data,_=owner.request('/api/bootstrap');self.assertEqual(code,200,data);self.assertEqual(data['permissions']['actions'],[]);self.assertIn('workspace.analytics',data['permissions']['modules']);self.assertIn('value_cents',data['resources']['items'][0])
        for path in ['/api/resources','/api/purchasing']:
            self.assertEqual(owner.request(path)[0],200)
        for path in ['/api/users','/api/role-permissions','/api/security-events']:
            self.assertEqual(owner.request(path)[0],403)
        for path in ['/api/purchasing/supplier','/api/purchasing/order','/api/purchasing/receipt','/api/purchasing/payment','/api/resources/material','/api/resources/expense','/api/orders','/api/backup','/api/role-permissions']:
            self.assertEqual(owner.request(path,{},role='accountant')[0],403,path)
        code,result,_=self.admin.request('/api/role-permissions',{'role':'老板','version':0,'modules':['sales.orders'],'actions':['orders.write']});self.assertEqual(code,400,result)
    def test_warehouse_charge_permissions_and_receipt_fees_are_atomic(self):
        wh,_=self.user();sid=self.post('supplier',{'name':'费用权限测试供应商','payment_days':0})['id']
        oid=self.post('order',{'supplier_id':sid,'business_date':'2026-10-20','expected_date':'2026-10-20','handler':'采购','request_key':'po-fees','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'100','price':'4'}]})['id'];self.post('confirm',{'id':oid,'version':1})
        snap=self.admin.request('/api/bootstrap')[1];body={'id':oid,'version':2,'revision':snap['resources']['revision'],'request_key':'receipt-fees','business_date':'2026-10-20','handler':'验收','note':'入库费用','lines':[{'line_id':'L1','qty':'100'}],'charges':[{'kind':'freight','billing_unit':'公斤','billing_qty':'100','rate':'0.2','supplier_id':sid}]}
        code,result,_=wh.request('/api/purchasing/receipt',body);self.assertEqual(code,400,result)
        with erp.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM material_entries').fetchone()[0],0)
        # A bad second payee rolls back the first person's new contact, receipt and all stock/fees.
        driver={**body['charges'][0],'payee_type':'driver','payee_id':'new','payee_name':'采购司机测试'}
        invalid={**driver,'kind':'unloading','payee_type':'worker','payee_name':''}
        bad={**body,'charges':[driver,invalid]}
        code,error,_=self.admin.request('/api/purchasing/receipt',bad);self.assertEqual(code,400,error)
        with erp.connect() as c:
            for table in ('material_entries','purchase_receipts','purchase_charges','purchase_payees'):self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        body['charges']=[driver]
        self.post('receipt',body);snap=self.admin.request('/api/bootstrap')[1];self.assertEqual(snap['purchasing']['orders'][0]['inventory_cost_cents'],42000);self.assertEqual(snap['purchasing']['orders'][0]['outstanding_cents'],40000)
        self.assertEqual(snap['purchasing']['orders'][0]['lines'][0]['actual_unit_price'],'4.2')
        charge=snap['purchasing']['charges'][0];self.assertEqual(charge['payee_name'],'采购司机测试');self.assertEqual(charge['supplier_id'],'')
        self.post('charge-payment',{'charge_id':charge['id'],'request_key':'direct-driver-pay','business_date':'2026-10-20','amount':'20','method':'现金','handler':'付款员','note':'直接付给司机'})
        payment=self.admin.request('/api/bootstrap')[1]['purchasing']['payments'][0];self.assertEqual(payment['payee_id'],charge['payee_id'])
        for key,rid in [('order_id',oid),('receipt_id',snap['purchasing']['receipts'][0]['id']),('charge_id',charge['id'])]:
            code,selected,_=self.admin.request('/api/purchasing?'+key+'='+rid);self.assertEqual(code,200,selected)
            self.assertEqual(selected,self.admin.request('/api/purchasing')[1])

        self.assertEqual(wh.request('/api/purchasing/charge',{})[0],403)
        raw=wh.request('/api/bootstrap')[1];self.assertNotIn('_cents',json.dumps(raw['purchasing']));self.assertNotIn('"rate"',json.dumps(raw['purchasing']));self.assertNotIn('warehouse_balance_cents',json.dumps(raw['resources']));self.assertNotIn('purchase_charges_cents',json.dumps(raw['resources']));self.assertNotIn('actual_unit_price',json.dumps(raw['purchasing']))

    def test_selected_order_and_options_do_not_return_other_history(self):
        sid=self.post('supplier',{'name':'按需供应商','payment_days':30})['id']
        ids=[]
        for i in range(2):
            ids.append(self.post('order',{'request_key':'selected-'+str(i),'supplier_id':sid,'business_date':'2026-10-01','expected_date':'2026-10-02','handler':'采购','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'100','price':'4.6'}]})['id'])
        code,options,_=self.admin.request('/api/purchasing?view=options')
        self.assertEqual(code,200,options);self.assertTrue(options['suppliers'])
        for bucket in ('orders','receipts','payments','charges'):self.assertEqual(options[bucket],[])
        for client in (self.admin,self.user('selectwh','库管')[0]):
            code,value,_=client.request('/api/purchasing?order_id='+ids[0]);self.assertEqual(code,200,value)
            self.assertEqual([r['id'] for r in value['orders']],[ids[0]])
            if client is not self.admin:
                self.assertNotIn('_cents',json.dumps(value));self.assertNotIn('"price"',json.dumps(value));self.assertNotIn('payment_days',json.dumps(value))
        for query in ('view=bad','order_id=','order_id=a&order_id=b','view=options&order_id=a','unknown=a'):
            self.assertEqual(self.admin.request('/api/purchasing?'+query)[0],400,query)
        self.assertEqual(self.admin.request('/api/purchasing?order_id=missing')[0],404)
        director,_=self.user('selectdirector','厂长')
        self.assertEqual(director.request('/api/purchasing?order_id='+ids[0])[0],403)
        anonymous=fixture.Client(self)
        self.assertEqual(anonymous.request('/api/purchasing?view=options')[0],401)
