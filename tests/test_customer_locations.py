import copy
import test_dispatch as dispatch
import test_workflow as workflow
from printing import order_print_html

erp=workflow.erp

class CustomerLocationTests(workflow.unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    def add(self,**extra):
        return erp.master({'kind':'customer','create':True,'name':'客户甲','region':'昌吉',
            'location_kind':'market','market_id':'M005',**extra},'会计')['id']
    def customer(self,cid):return next(c for c in erp.bootstrap()['customers'] if c['id']==cid)
    def test_market_must_belong_to_region(self):
        cid=self.add();c=self.customer(cid)
        self.assertEqual((c['region'],c['route'],c['market_id']),('昌吉','亚中','M005'))
        before=erp.bootstrap()
        for changes in [{'region':'乌鲁木齐'},{'market_id':'unknown'},{'location_kind':'invalid'},{'location_kind':'independent'},{'region':''}]:
            with self.assertRaises(ValueError):self.add(**changes)
        self.assertEqual(before,erp.bootstrap())
    def test_independent_point_reused_and_dispatch_print_connected(self):
        cid=self.add(market_id='',location_kind='independent',location_name='某单位收货处')
        point=self.customer(cid)['market_id'];self.assertTrue(point)
        other=self.add(market_id='',location_kind='independent',location_name='某单位收货处')
        self.assertEqual(self.customer(other)['market_id'],point)
        self.assertEqual(len(erp.bootstrap()['delivery_markets']),7)
        o=erp.mutate('order',{'customer_id':cid,'business_date':'2026-10-18','batch':'日常订货','lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'0','price':'75'}]},'库管')
        plan=dispatch.DispatchTests.body(self)
        plan['assignments'].append({'market_id':point,'trip_id':'CJ','sequence':4})
        saved=erp.save_dispatch(plan,'库管');self.assertEqual(saved['order_markets'][o['id']],point)
        html=order_print_html(erp.bootstrap(),{'date':['2026-10-18'],'mode':['trip'],'trip':['CJ'],'document':['order']},erp.now())
        self.assertIn('某单位收货处',html);self.assertIn(o['id'],html)
        erp.master({'kind':'customer','create':False,'id':cid,'name':'客户甲','region':'乌鲁木齐','location_kind':'market','market_id':'M001'},'会计')
        plan['version']=1
        self.assertEqual(erp.save_dispatch(plan,'库管')['order_markets'][o['id']],point)
    def test_pickup_needs_no_market_or_vehicle_stop(self):
        cid=self.add(market_id='',location_kind='independent',region='五彩湾',location_name='五彩湾',delivery_method='pickup')
        c=self.customer(cid);self.assertEqual((c['route'],c['region'],c['market_id']),('五彩湾','五彩湾',''))
        self.assertEqual(len(erp.bootstrap()['delivery_markets']),6)
        erp.master({'kind':'customer','create':False,'id':cid,'name':'客户甲','region':'五彩湾','location_kind':'independent','location_name':'五彩湾','delivery_method':'delivery'},'会计')
        self.assertTrue(self.customer(cid)['market_id'])
    def test_create_new_market_and_region_and_reject_name_collision_atomically(self):
        cid=self.add(region='新地区',market_id='',location_name='新市场')
        self.assertEqual(self.customer(cid)['route'],'新市场')
        before=erp.bootstrap()
        with self.assertRaises(ValueError):self.add(region='其他地区',market_id='',location_name='新市场')
        with self.assertRaises(ValueError):self.add(market_id='',location_kind='independent',location_name='   ')
        with self.assertRaises(ValueError):self.add(market_id='',location_kind='independent',location_name='不会留下孤立点',note='x'*501)
        self.assertEqual(before,erp.bootstrap())
    def test_legacy_exact_match_migration_preserves_orders_and_unmatched_routes(self):
        with erp.connect(True) as c:
            c.execute("UPDATE customers SET route='亚中',region='',market_id='' WHERE id='C001'")
            c.execute("DELETE FROM meta WHERE key='customer_locations_v09'");c.execute("DELETE FROM schema_migrations WHERE id='046-customer-locations'")
        before=erp.bootstrap();erp.init_db();after=erp.bootstrap()
        self.assertEqual(self.customer('C001')['market_id'],'M005')
        self.assertEqual(self.customer('C002')['route'],'昌吉线')
        self.assertEqual(self.customer('C002')['region'],'')
        for key in ('orders','receipts','rules','dispatch_plans'):self.assertEqual(before[key],after[key])
        erp.init_db();self.assertEqual(after,erp.bootstrap())
