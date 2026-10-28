import copy,json
import test_workflow as workflow
erp=workflow.erp

class DispatchTests(workflow.unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    order=workflow.WorkflowTests.order
    def body(self,date='2026-10-18'):
        return {'business_date':date,'version':0,'trips':[
            {'id':'CJ','name':'昌吉下午','period':'下午','vehicle_id':'V001','driver':'司机甲'},
            {'id':'U1','name':'乌鲁木齐晚间1','period':'晚间','vehicle_id':'V001','driver':'司机乙'},
            {'id':'U2','name':'乌鲁木齐晚间2','period':'晚间','vehicle_id':'V002','driver':'司机丙'}],
            'assignments':[{'market_id':f'M{i:03}','trip_id':'CJ' if i>3 else 'U1' if i<3 else 'U2','sequence':i if i<=3 else i-3} for i in range(1,7)]}
    def test_two_vehicles_make_three_trips_with_different_drivers(self):
        self.assertEqual(len(erp.bootstrap()['delivery_vehicles']),2)
        p=erp.save_dispatch(self.body(),'库管')
        self.assertEqual(p['version'],1);self.assertEqual(p['trips'][0]['vehicle_id'],p['trips'][1]['vehicle_id'])
        self.assertNotEqual(p['trips'][0]['driver'],p['trips'][1]['driver'])
        self.assertEqual(erp.bootstrap()['dispatch_plans'],[p])
    def test_new_market_and_new_trip_are_not_limited_to_six_markets(self):
        erp.master({'kind':'delivery_market','name':'临时监狱配送点','city':'其他区域'},'会计')
        erp.master({'kind':'delivery_vehicle','name':'临时加车'},'会计')
        b=self.body();b['trips'].append({'id':'TEMP','name':'临时加送','period':'中午','vehicle_id':'V003','driver':'临时司机'})
        b['assignments'].append({'market_id':'M007','trip_id':'TEMP','sequence':1})
        p=erp.save_dispatch(b,'会计');self.assertEqual(p['assignments'][-1]['market_name'],'临时监狱配送点')
        self.assertEqual(len(erp.bootstrap()['delivery_markets']),7)
    def test_stale_plan_and_unauthorized_role_do_not_overwrite(self):
        original=erp.save_dispatch(self.body(),'会计')
        with self.assertRaises(ValueError):erp.save_dispatch(self.body(),'会计')
        with self.assertRaises(ValueError):erp.save_dispatch({**self.body(),'version':1},'出纳')
        self.assertEqual(erp.bootstrap()['dispatch_plans'],[original])
    def test_invalid_route_rows_are_rejected_atomically(self):
        for field,value in [('trip_id','NO'),('market_id','NO'),('sequence',0),('sequence',1.5)]:
            b=self.body();b['assignments'][0][field]=value
            with self.assertRaises(ValueError):erp.save_dispatch(b,'库管')
        b=self.body();b['assignments'][1]['sequence']=1
        with self.assertRaises(ValueError):erp.save_dispatch(b,'库管')
        b=self.body();b['trips'][0]['vehicle_id']='NO'
        with self.assertRaises(ValueError):erp.save_dispatch(b,'库管')
        self.assertEqual(erp.bootstrap()['dispatch_plans'],[])
    def test_market_snapshot_does_not_change_orders_or_follow_customer_edit(self):
        erp.master({'kind':'customer','create':False,'id':'C001','name':'客户甲','route':'新联'},'会计')
        o=self.order();p=erp.save_dispatch(self.body(),'库管')
        self.assertEqual(p['order_markets'][o['id']],'M001')
        erp.master({'kind':'customer','create':False,'id':'C001','name':'客户甲','route':'北园春'},'会计')
        p=erp.save_dispatch({**self.body(),'version':1},'库管')
        self.assertEqual(p['order_markets'][o['id']],'M001')
        self.assertEqual(next(x for x in erp.bootstrap()['orders'] if x['id']==o['id']),o)
    def test_legacy_market_can_be_corrected_then_added_to_plan(self):
        o=self.order();p=erp.save_dispatch(self.body(),'库管');self.assertEqual(p['order_markets'][o['id']],'')
        erp.master({'kind':'customer','create':False,'id':'C001','name':'客户甲','route':'新联'},'会计')
        p=erp.save_dispatch({**self.body(),'version':1},'库管');self.assertEqual(p['order_markets'][o['id']],'M001')
    def test_pickup_orders_are_not_saved_in_vehicle_market_map(self):
        erp.master({'kind':'customer','id':'C001','name':'自取客户','route':'新联','delivery_method':'pickup'},'会计')
        o=self.order();plan=erp.save_dispatch(self.body(),'库管')
        self.assertNotIn(o['id'],plan['order_markets'])
    def test_initialization_is_repeatable_and_keeps_added_markets(self):
        erp.master({'kind':'delivery_market','name':'新增点','city':'新区域'},'会计');erp.init_db()
        self.assertEqual(len(erp.bootstrap()['delivery_markets']),7)
        with self.assertRaises(ValueError):erp.master({'kind':'delivery_market','name':'新联','city':'别处'},'会计')
