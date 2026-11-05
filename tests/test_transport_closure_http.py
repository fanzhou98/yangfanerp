import json,unittest,uuid
import test_auth_http as fixture
import transport_closure as tc,trade,resources_costs as rc

erp=fixture.erp
class TransportClosureHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def seed(self,quote=True):
        day=self.order_test_day
        with erp.connect(True) as c:
            p=trade.save(c,'transport-provider',{'request_key':str(uuid.uuid4()),'name':'HTTP配送服务商'},'管理员',erp.now,erp.audit)
            if quote:trade.save(c,'transport-quote',{'request_key':str(uuid.uuid4()),'provider_id':p['id'],'area':'昌吉','effective_date':day,'version':0,'rate':'135'},'管理员',erp.now,erp.audit)
            c.execute("UPDATE delivery_markets SET city='昌吉' WHERE id='M001'");c.execute("INSERT INTO delivery_drivers VALUES('HTTP-D','配送司机',1)");o=erp.mutate('order',{'customer_id':'C001','business_date':day,'batch':'HTTP出车核对','lines':[{'product_id':'P001','ordered_qty':'5','actual_qty':'5','price':'3','driver':[],'customer':[]}]},'管理员',connection=c)
            plan={'business_date':day,'version':1,'trips':[{'id':'HTTP-T','name':'HTTP实际配送','period':'下午','provider_id':p['id'],'vehicle_id':'V001','vehicle_name':'车A','driver_ids':['HTTP-D'],'driver_id':'HTTP-D','driver':'配送司机'}],'assignments':[{'market_id':'M001','market_name':c.execute("SELECT name FROM delivery_markets WHERE id='M001'").fetchone()[0],'city':'昌吉','sequence':1,'trip_id':'HTTP-T'}],'order_markets':{o['id']:'M001'}};c.execute('INSERT INTO dispatch_plans VALUES(?,?)',(day,rc.dump(plan)));r=tc.sync(c,day,'管理员',erp.now,erp.audit)[0]
        return p,plan,r
    def issue(self,client,p):
        code,report,_=client.request('/api/transport?month='+self.order_test_day[:7]);self.assertEqual(code,200,report);g=next(g for g in report['groups'] if g['provider_id']==p['id'])
        return client.request('/api/trade/transport-issue',{'month':self.order_test_day[:7],'provider_id':p['id'],'partner':p['name'],'handler':'会计','source_fingerprint':g['source_fingerprint'],'request_key':str(uuid.uuid4())})
    def test_logistics_can_maintain_providers_without_rates_or_price_permission(self):
        p,plan,r=self.seed();client,_=self.user('closelogistics','物流负责人')
        code,report,_=client.request('/api/transport?month='+self.order_test_day[:7]);self.assertEqual(code,200);self.assertFalse(report['financial']);self.assertNotIn('amount_cents',json.dumps(report));self.assertNotIn('quotes',report);self.assertNotIn('documents',report)
        code,v,_=client.request('/api/transport-providers');self.assertEqual(code,200);self.assertIn(p['id'],[x['id'] for x in v['providers']])
        code,created,_=client.request('/api/trade/transport-provider',{'name':'物流自建服务商','phone':'0994-5550000','request_key':str(uuid.uuid4())});self.assertEqual(code,200,created)
        code,rates,_=client.request('/api/transport-provider-quotes');self.assertEqual(code,200);self.assertTrue(rates['regions']);self.assertFalse(rates['quotes']);self.assertIn('vehicle_types',rates)
        code,tasks,_=client.request('/api/transport-task-types');self.assertEqual(code,200,tasks);self.assertIn('delivery',[t['key'] for t in tasks['task_types']])
        code,result,_=client.request('/api/trade/transport-price',{'id':r['id'],'version':r['version'],'provider_id':p['id'],'rate':'1','note':'不允许越权','request_key':str(uuid.uuid4())});self.assertEqual(code,403,result)
        driver,_=self.user('closedriver','司机');self.assertEqual(driver.request('/api/transport-providers')[0],403)
    def test_accountant_can_settle_confirmed_delivery_and_reopen_requires_payment_free(self):
        p,plan,r=self.seed();client,_=self.user('closeaccountant','会计');code,report,_=client.request('/api/transport?month='+self.order_test_day[:7]);self.assertEqual(code,200);self.assertTrue(report['financial']);self.assertEqual(report['trips'][0]['amount_cents'],13500);self.assertEqual(report['trips'][0]['execution_state'],'confirmed')
        code,doc,error=self.issue(client,p);self.assertEqual(code,200,error);self.assertEqual(doc['trip_count'],1)
        code,second,error=self.issue(client,p);self.assertEqual(code,400,error)
        with erp.connect() as c:self.assertEqual(len(trade.records(c,'transport-document')),1)
    def test_missing_quote_blocks_settlement_until_accountant_prices(self):
        p,plan,r=self.seed(False);client,_=self.user('closeaccountant','会计')
        code,error,_=self.issue(client,p);self.assertEqual(code,400,error);self.assertIn('运费',error['error'])
        code,result,_=client.request('/api/trade/transport-price',{'id':r['id'],'version':r['version'],'provider_id':p['id'],'rate':'150','note':'客户地区暂无报价','request_key':str(uuid.uuid4())});self.assertEqual(code,200,result)
        code,doc,error=self.issue(client,p);self.assertEqual(code,200,error);self.assertEqual(doc['amount_cents'],15000)
