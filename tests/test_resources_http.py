import unittest,uuid
import test_auth_http as fixture

erp=fixture.erp
class ResourceHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_void_and_restore_round_trip_over_http(self):
        day='2026-10-19'
        code,data,_=self.admin.request('/api/bootstrap');self.assertEqual(code,200)
        body={'request_key':str(uuid.uuid4()),'material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':day,'kind':'receipt','qty':'10','amount':'40','revision':data['resources']['revision'],'handler':'管理员','note':'测试恢复'}
        code,e,_=self.admin.request('/api/resources/material',body);self.assertEqual(code,200,e)
        code,voided,_=self.admin.request('/api/resources/void',{'ledger':'material','id':e['id'],'version':1,'reason':'登记错误'});self.assertEqual(code,200,voided)
        code,res,_=self.admin.request('/api/resources');self.assertEqual(code,200);self.assertIn(e['id'],[x['id'] for x in res['voided_entries']])
        code,restored,_=self.admin.request('/api/resources/restore',{'ledger':'material','id':e['id'],'version':voided['version'],'reason':'撤销作废'});self.assertEqual(code,200,restored);self.assertFalse(restored['voided'])
        code,res,_=self.admin.request('/api/resources');self.assertNotIn(e['id'],[x['id'] for x in res['voided_entries']]);self.assertTrue(any(x['id']==e['id'] for x in res['entries']))
        self.assertEqual(self.admin.request('/api/resources/restore',{'ledger':'material','id':e['id'],'version':restored['version'],'reason':'再次恢复'})[0],400)

    def test_real_permissions_versions_audit_and_quantity_projection(self):
        wh,_=self.user();day='2026-10-19'
        code,data,_=wh.request('/api/bootstrap');self.assertEqual(code,200,data)
        self.assertIn('inventory.materials',data['permissions']['modules']);self.assertNotIn('finance.costs',data['permissions']['modules']);self.assertNotIn('value_cents',data['resources']['items'][0])
        body={'request_key':str(uuid.uuid4()),'material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':day,'kind':'receipt','qty':'10','amount':'0','revision':data['resources']['revision'],'handler':'测试库管','note':'测试收货'}
        code,e,_=wh.request('/api/resources/material',body);self.assertEqual(code,400,e)
        code,e,_=self.admin.request('/api/resources/material',{**body,'request_key':str(uuid.uuid4()),'amount':'40'});self.assertEqual(code,200,e)
        self.assertEqual(wh.request('/api/resources/expense',{'request_key':str(uuid.uuid4())})[0],403)
        self.assertEqual(wh.request('/api/resources/value',{'id':e['id'],'version':1,'amount':'50','note':'越权'})[0],403)
        code,result,_=self.admin.request('/api/resources/value',{'id':e['id'],'version':1,'amount':'50','note':'发票计价'});self.assertEqual(code,200,result)
        self.assertEqual(self.admin.request('/api/resources/value',{'id':e['id'],'version':1,'amount':'60','note':'旧版本'})[0],400)
        code,value,_=wh.request('/api/resources');self.assertEqual(code,200);self.assertNotIn('amount_cents',value['entries'][0]);self.assertNotIn('cost_cents',value['entries'][0]);self.assertNotIn('value_cents',value['items'][0])
        owner,_=self.user('owner_res_cost','老板')
        code,d,_=owner.request('/api/bootstrap');self.assertEqual(code,200)
        self.assertEqual(next(i for i in d['resources']['items'] if i['id']=='RM-SOY')['value_cents'],5000)
        with erp.connect() as c:
            event=c.execute("SELECT actor_id FROM audit WHERE entity=? ORDER BY id DESC LIMIT 1",(e['id'],)).fetchone();self.assertEqual(event['actor_id'],self.admin_user['id'])
