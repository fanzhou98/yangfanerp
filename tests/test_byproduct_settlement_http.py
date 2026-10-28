import json, unittest, uuid
import test_auth_http as fixture
import resources_costs as rc

erp=fixture.erp


class ByproductSettlementHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_parameter_price_posting_and_read_projection(self):
        accountant,_=self.user('byproduct-accountant','会计')
        warehouse,_=self.user('byproduct-warehouse','库管')
        with erp.connect(True) as c:
            c.execute('DELETE FROM material_entries')
            c.execute('DELETE FROM byproduct_sales')
            ops=rc.Operations(c,erp.now,erp.audit)
            for kind,qty,amount,day in [('receipt','1000','4000','2026-10-19'),('consume','100','0','2026-10-20')]:
                ops.material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'kind':kind,'material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':day,'qty':qty,'amount':amount,'production_system_id':'tofu','handler':'测试','note':'验收'},'管理员')
        body={'action':'config','buyer':'测试购货方','add_kg':'10','version':0}
        self.assertEqual(accountant.request('/api/byproduct-settlement',body)[0],403)
        status,config,_=self.admin.request('/api/byproduct-settlement',body)
        self.assertEqual(status,200,config)
        self.assertEqual(self.admin.request('/api/byproduct-settlement',body)[0],400,'拒绝过期参数覆盖')
        price={'action':'price','month':'2026-10','price':'0.5'}
        self.assertEqual(accountant.request('/api/byproduct-settlement',price,csrf=False)[0],403)
        self.assertEqual(warehouse.request('/api/byproduct-settlement',price)[0],403)
        status,result,_=accountant.request('/api/byproduct-settlement',price)
        self.assertEqual(status,200,result)
        status,result,_=accountant.request('/api/byproduct-settlement',{'action':'settle','month':'2026-10','handler':'会计','request_key':str(uuid.uuid4())})
        self.assertEqual(status,200,result)
        self.assertEqual(result['qty'],'110');self.assertEqual(result['amount_cents'],5500)
        record_id=result['id']
        for client in (self.admin,accountant):
            status,view,_=client.request('/api/byproduct-settlement?month=2026-10')
            self.assertEqual(status,200,view)
            self.assertNotIn('add_kg',json.dumps(view))
            self.assertNotIn('bean_kg',json.dumps(view))
            self.assertNotIn('加量',json.dumps(view,ensure_ascii=False))
            self.assertEqual(view['total_amount_cents'],5500)
        self.assertEqual(warehouse.request('/api/byproduct-settlement?month=2026-10')[0],403)
        status,settings,_=self.admin.request('/api/factory/report?kind=system-settings&date=2026-10-20')
        self.assertEqual(status,200,settings);self.assertEqual(settings['byproduct_settings']['add_kg'],'10')
        status,settings,_=accountant.request('/api/factory/report?kind=system-settings&date=2026-10-20')
        self.assertEqual(status,200,settings);self.assertNotIn('byproduct_settings',settings)
        status,view,_=accountant.request('/api/resources')
        self.assertEqual(status,200);self.assertNotIn('加量',json.dumps(view['byproducts'],ensure_ascii=False))
        with erp.connect(True) as c:
            legacy=json.loads(c.execute('SELECT payload FROM byproduct_sales WHERE id=?',(record_id,)).fetchone()[0])
            legacy['note']='按日结算，上豆与加量合计 110 公斤'
            c.execute('UPDATE byproduct_sales SET payload=? WHERE id=?',(rc.dump(legacy),record_id))
        status,received,_=self.admin.request('/api/resources/receive',{'id':record_id,'version':legacy['version'],'amount':'10','business_date':legacy['business_date'],'note':'测试到账'})
        self.assertEqual(status,200,received)
        self.assertEqual(received['received_cents'],1000)
        self.assertNotIn('加量',json.dumps(received,ensure_ascii=False))
