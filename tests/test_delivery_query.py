"""All history tests use synthetic temporary records, with no operational mutations."""
import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import server as erp,delivery_query as q,resources_costs as rc,trade,assets
import test_delivery_trade as real

class DeliveryQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=erp.DB;erp.DB=Path(self.tmp.name)/'synthetic.db';erp.init_db(demo=False);self.ctx=erp.connect(True);self.c=self.ctx.__enter__()
    def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);erp.DB=self.old;self.tmp.cleanup()
    def seed(self,kind,i=0,**changes):
        table,record_kind,_=q.SOURCES[kind]
        r={'id':kind+str(i).zfill(4),'kind':record_kind,'version':1,'business_date':'2026-09-01','driver_ids':['D1','D2'],'driver_id':'D1','driver':'原司机','vehicle_id':'V1','vehicle_name':'原车辆','trip_name':'原趟次','trip':'原趟次','partner':'运输公司','asset_id':'A1','asset_name':'原白框','qty':2,'customer_id':'C1','customer_name':'原客户','order_id':'O1','product_id':'P1','product_name':'原产品','unit':'筐','actual_qty':'0.3','received_qty':'0.2','difference_qty':'-0.1','feedback_date':'2026-10-01','state':'pending','movement':'return','month':'2026-09','trip_count':1,'amount_cents':101,'note':'真实依据 % _','lines':[{'asset_id':'A1','asset_name':'原白框','qty':2,'order_id':'O1','customer_id':'C1','secret':'hidden','amount_cents':888}], 'user_id':'secret-account','secret':'hidden',**changes}
        if table=='asset_records':self.c.execute('INSERT INTO asset_records VALUES(?,?,?)',(r['id'],r['id'],rc.dump(r)))
        elif table=='driver_return_requests':self.c.execute('INSERT INTO driver_return_requests VALUES(?,?,?)',(r['id'],r['id'],rc.dump(r)))
        else:self.c.execute('INSERT INTO '+table+' VALUES(?,?)',(r['id'],rc.dump(r)))
        return r
    def test_all_kinds_pages_stable_full_summary_and_safe_original(self):
        for kind in q.SOURCES:
            for i in range(126):self.seed(kind,i,business_date='2026-09-01' if i%2 else '2026-10-01')
            first=q.history(self.c,kind=kind,all_dates=True,financial=True);seen=[]
            for page in (1,2,3):
                r=q.history(self.c,kind=kind,all_dates=True,financial=True,page=page);self.assertEqual(r['summary'],first['summary']);seen += [row['id'] for row in r['rows']];self.assertTrue(all('lines' not in row for row in r['rows']))
            self.assertEqual(len(seen),126);self.assertEqual(len(set(seen)),126);self.assertEqual([len(q.history(self.c,kind=kind,all_dates=True,financial=True,page=i)['rows']) for i in (1,2,3)],[50,50,26])
            detail=q.detail(self.c,kind,seen[0],financial=True);self.assertIsNotNone(detail);self.assertNotIn('secret',json.dumps(detail));self.assertNotIn('user_id',json.dumps(detail))
            self.assertEqual(q.history(self.c,kind=kind,all_dates=True,search='% _',financial=True)['total'],126)
        self.assertEqual(q.history(self.c,kind='feedback',all_dates=True)['summary'][0]['difference_qty'],'-12.6')
        self.assertEqual(q.history(self.c,kind='movements',all_dates=True)['summary'][0]['qty'],'252')
        self.assertEqual(q.history(self.c,kind='trips',all_dates=True,financial=True)['summary'][0]['amount_cents'],12726)
    def test_actual_dates_voids_and_no_ledger_loading(self):
        self.seed('feedback');self.seed('trips',voided=True);self.seed('movements',voided=True)
        self.assertEqual(q.history(self.c,kind='feedback',start='2026-09-01',end='2026-09-01')['total'],0)
        self.assertEqual(q.history(self.c,kind='feedback',start='2026-10-01',end='2026-10-01')['total'],1)
        for kind in ('trips','movements'):
            r=q.history(self.c,kind=kind,all_dates=True);self.assertEqual(r['total'],1);self.assertEqual(r['summary'],[]);self.assertEqual(q.history(self.c,kind=kind,all_dates=True,status='active')['total'],0)
        before=self.c.total_changes
        with patch.object(rc,'rows',side_effect=AssertionError('full ledger read')):
            for kind in ('trips','feedback','movements'):q.history(self.c,kind=kind,all_dates=True)
        self.assertEqual(self.c.total_changes,before)
    def test_filters_units_unknown_and_historical_unattributed(self):
        self.seed('trips');self.seed('trips',1,driver_ids=['D3'],driver_id='D3',document_id='DOC')
        self.assertEqual(q.history(self.c,kind='trips',all_dates=True,driver_id='D2')['total'],1)
        self.assertEqual(q.history(self.c,kind='trips',all_dates=True,status='settled',financial=True)['total'],1)
        self.seed('movements',customer_id='');self.seed('movements',1,movement='scrap',qty=3)
        self.assertEqual(q.history(self.c,kind='movements',all_dates=True,status='unattributed')['total'],1)
        self.assertEqual(q.history(self.c,kind='movements',all_dates=True,asset_id='A1',customer_id='C1')['summary'][0]['qty'],'3')
        self.seed('feedback');self.seed('feedback',1,unit='公斤');self.assertEqual(len(q.history(self.c,kind='feedback',all_dates=True)['summary']),2)
    def test_request_states_and_drafts_private_and_not_physical(self):
        for i,state in enumerate(('draft','deleted','pending','confirmed','withdraw_pending','withdrawn','rejected')):self.seed('requests',i,state=state)
        r=q.history(self.c,kind='requests',all_dates=True);self.assertEqual(r['total'],5);self.assertEqual(len(r['summary']),5)
        self.assertIsNone(q.detail(self.c,'requests','requests0000'));self.assertIsNone(q.detail(self.c,'requests','requests0001'))
        self.assertEqual(q.history(self.c,kind='movements',all_dates=True)['total'],0)
    def test_financial_redaction_detail_and_parameters(self):
        self.seed('trips',document_id='SENSITIVE');self.seed('requests');self.seed('documents')
        for kind in ('trips','requests'):
            r=q.history(self.c,kind=kind,all_dates=True);d=q.detail(self.c,kind,kind+'0000');self.assertNotIn('_cents',json.dumps(r));self.assertNotIn('_cents',json.dumps(d));self.assertNotIn('document_id',json.dumps(d))
        for args in ({'kind':'bad'},{'page':0},{'page_size':201},{'all_dates':True,'start':'2026-01-01'},{'start':'2026-02-30'},{'start':'2026-11-01','end':'2026-10-01'},{'status':'bad'},{'kind':'requests','asset_id':'A1'},{'kind':'documents'},{'kind':'trips','status':'settled'}):
            with self.subTest(args=args),self.assertRaises(ValueError):q.history(self.c,**args)
        with self.assertRaises(ValueError):q.detail(self.c,'documents','documents0000')
    def test_missing_quantities_remain_unknown_and_unit_is_not_invented(self):
        self.seed('feedback',actual_qty=None,received_qty=None,difference_qty=None,unit=None)
        summary=q.history(self.c,kind='feedback',all_dates=True)['summary'][0]
        for k in ('actual_qty','received_qty','difference_qty'):
            self.assertIsNone(summary[k]);self.assertEqual(summary[k+'_missing'],1)
        self.assertIsNone(summary['unit'])
    def test_range_indexes_and_no_full_payloads(self):
        expected={'trips':'trade_check_kind_date_id','feedback':'trade_feedback_date_id','movements':'asset_history_kind_date_id','requests':'driver_return_history_date_id','documents':'trade_check_kind_date_id'}
        for kind,index in expected.items():
            sql,args=q.source_sql(kind,'2026-09-01','2026-10-01');plan=' '.join(r[3] for r in self.c.execute('EXPLAIN QUERY PLAN '+sql,args));self.assertIn(index,plan,(kind,plan))

class RealDeliveryQueryTests(unittest.TestCase):
    setUp=real.DeliveryTradeTests.setUp
    tearDown=real.DeliveryTradeTests.tearDown
    save=real.DeliveryTradeTests.save
    order=real.DeliveryTradeTests.order
    shipment=real.DeliveryTradeTests.shipment
    def test_real_return_batch_and_void_do_not_change_customer_balance_on_reads(self):
        o=self.order();self.shipment(o);self.c.execute("INSERT INTO delivery_drivers VALUES('QUERY-DRIVER','历史司机',1)")
        r=assets.save(self.c,'return-batch',{'request_key':'q-return','business_date':'2026-10-21','driver_id':'QUERY-DRIVER','lines':[{'asset_id':'CR-YELLOW','order_id':o['id'],'qty':3}],'source_date':'2026-10-20'},'管理员',self.erp.now,self.erp.audit)
        before=trade.customer_crates(self.c,'C001','2026-10-21');result=q.history(self.c,kind='movements',start='2026-10-21',end='2026-10-21');self.assertEqual(result['summary'][0]['qty'],'3');self.assertEqual(before,trade.customer_crates(self.c,'C001','2026-10-21'))
        event=result['rows'][0];assets.save(self.c,'void',{'id':event['id'],'version':event['version'],'request_key':'q-void','note':'原回筐核查作废'},'管理员',self.erp.now,self.erp.audit)
        self.assertEqual(q.history(self.c,kind='movements',start='2026-10-21',end='2026-10-21')['summary'],[])
    def test_real_feedback_and_monthly_transport_preserved(self):
        o=self.order();f=self.save('feedback',{'order_id':o['id'],'order_version':o['version'],'product_id':'P001','received_qty':'8','feedback_date':'2026-10-21','note':'客户反馈漏送两筐'})
        self.assertEqual(q.history(self.c,kind='feedback',start='2026-10-21',end='2026-10-21')['rows'][0]['actual_qty'],'10')
        self.save('resolve-feedback',{'id':f['id'],'version':f['version'],'resolution':'关联补送原单核对'})
        p={'business_date':'2026-10-20','version':1,'trips':[{'id':'T1','name':'配送一趟','driver':'司机','vehicle_name':'车一'}],'assignments':[{'market_id':'M001','trip_id':'T1'}]}
        self.c.execute('INSERT INTO dispatch_plans VALUES(?,?)',(p['business_date'],rc.dump(p)))
        t=self.save('trip',{'business_date':'2026-10-20','trip_id':'T1','partner':'运输公司','rate':'120.50','note':'已完成实际配送'})
        group=trade.transport_report(self.c,'2026-10')['groups'][0];doc=self.save('transport-issue',{'month':'2026-10','partner':'运输公司','handler':'经办人','source_fingerprint':group['source_fingerprint']})
        self.assertEqual(q.history(self.c,kind='trips',all_dates=True,financial=True)['summary'][0]['amount_cents'],12050)
        self.assertEqual(q.detail(self.c,'documents',doc['id'],financial=True)['record']['lines'][0]['amount_cents'],12050)
        self.assertEqual(len(rc.rows(self.c,'indirect_expenses')),1);self.assertEqual(trade.transport_report(self.c,'2026-10')['groups'][0]['unsettled_count'],0)
