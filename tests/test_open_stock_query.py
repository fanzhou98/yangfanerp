"""Synthetic-only equivalence, prefix, pagination and scope checks."""
import unittest,json,tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import date,timedelta
import server as erp,inventory as inv,open_stock_query as q,resources_costs as rc
import test_order_corrections as fixture

class OpenStockTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=erp.DB;erp.DB=Path(self.tmp.name)/'synthetic.db';erp.init_db(demo=False)
        self.ctx=erp.connect(True);self.c=self.ctx.__enter__()
        self.c.executemany('INSERT INTO products VALUES(?,?,?,?,?,?)', [('P001','合成豆腐','筐','3','0','1'),('P002','合成豆干','包','3','0','1')])
    def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);erp.DB=self.old;self.tmp.cleanup()
    def put(self,table,r,key='id'):inv.put(self.c,table,r,key)
    def plan(self,day,**changes):
        r={'business_date':day,'version':1,'allocation_state':'draft','stock':[{'product_id':'P001','existing_qty':'10','produced_qty':'0.1','loss_qty':'0.01'}],'allocations':[],**changes};self.put('warehouse_plans',r,'business_date');return r
    def order(self,day,key='O',qty='2'):
        r={'id':key,'business_date':day,'state':'draft','lines':[{'product_id':'P001','product_name':'豆腐','ordered_qty':'3','actual_qty':qty,'price':'99','amount_cents':999}]};self.put('orders',r);return r
    def test_canonical_sources_prefix_unknown_and_voided(self):
        day='2026-09-10';self.plan(day,allocation_state='confirmed',allocations=[{'order_id':'O','product_id':'P001','qty':'3'}]);self.order(day)
        self.put('finished_goods_records',{'id':'F','kind':'receipt','business_date':day,'lines':[{'product_id':'P001','qty':'1.25'}]})
        self.put('finished_goods_records',{'id':'FV','kind':'receipt','business_date':day,'voided':True,'lines':[{'product_id':'P001','qty':'100'}]})
        self.put('processing_batches',{'id':'B','business_date':day,'product_id':'P001','input_qty':'0.5','outputs':[{'product_id':'P001','qty':'0.25'}]})
        self.put('sales_returns',{'id':'R','received_date':'2026-08-01','product_id':'P001','qty':'10','net_kg':'100','disposals':[{'business_date':'2026-08-02','kind':'discard','qty':'1','net_kg':'10'},{'business_date':day,'kind':'restock','qty':'2','net_kg':'20','stock_qty':'2'},{'business_date':'2026-10-01','kind':'discard','qty':'3','net_kg':'30'},{'business_date':day,'kind':'discard','qty':'1','net_kg':'10','voided':True}]})
        result=q.history(self.c,start=day,end=day);actual=next(p for p in result['rows'] if p['product_id']=='P001');expected=inv.stock(self.c,day)['products'][0]
        for k,v in expected.items():self.assertEqual(actual[k],v,k)
        self.assertEqual(actual['quarantine_qty'],'7');self.assertEqual(actual['quarantine_kg'],'70');self.assertEqual(actual['book_qty'],'11.09');self.assertEqual(actual['free_qty'],'10.09')
        self.assertEqual(result['days'],1);self.assertEqual(q.history(self.c,start=day,end=day,product_id='P001')['rows'],[actual])
        absent=next(p for p in result['rows'] if p['product_id']=='P002');self.assertIsNone(absent['production_qty']);self.assertIsNone(absent['book_qty']);self.assertEqual(absent['opening_qty'],'')
        self.assertNotIn('amount_cents',json.dumps(result));self.assertNotIn('price',json.dumps(result))
        with patch.object(inv,'rows',side_effect=AssertionError('full ledger read')),patch.object(__import__('order_corrections'),'records',side_effect=AssertionError('full corrections read')):
            self.assertEqual(q.history(self.c,start=day,end=day)['rows'],result['rows'])
    def test_closings_opening_saved_plan_locks_and_reopened(self):
        self.put('stock_closings',{'business_date':'2026-09-01','state':'closed','products':[{'product_id':'P001','counted_qty':'12'}]},'business_date')
        self.order('2026-09-02');self.plan('2026-09-03');self.plan('2026-09-04')
        self.put('stock_closings',{'business_date':'2026-09-04','state':'reopened','products':[]},'business_date')
        self.put('stock_closings',{'business_date':'2026-09-05','state':'closed','products':[]},'business_date');self.plan('2026-09-05')
        r=q.history(self.c,start='2026-09-01',end='2026-09-05',product_id='P001');self.assertEqual(r['total'],3)
        row=next(x for x in r['rows'] if x['business_date']=='2026-09-02');self.assertEqual(row['opening_qty'],'12');self.assertEqual(row['previous_closing_date'],'2026-09-01');self.assertIsNone(row['production_qty']);self.assertEqual(row['lock_date'],'2026-09-05')
        self.plan('2026-09-02',stock=[]);row=q.history(self.c,start='2026-09-02',end='2026-09-02',product_id='P001')['rows'][0];self.assertEqual(row['opening_qty'],'');self.assertIsNone(row['book_qty'])
        self.assertEqual(q.history(self.c,all_dates=True,product_id='P001',status='locked')['total'],3)
    def test_dates_from_returns_disposals_checks_and_voids(self):
        self.put('sales_returns',{'id':'R','product_id':'P001','received_date':'2026-08-01','qty':'2','net_kg':'20','disposals':[{'business_date':'2026-09-01','kind':'discard','qty':'1','net_kg':'10'}]})
        self.put('trade_records',{'id':'C','kind':'inventory-check','business_date':'2026-09-02'})
        self.put('processing_batches',{'id':'V','business_date':'2026-09-03','voided':True})
        r=q.history(self.c,start='2026-09-01',end='2026-09-03',product_id='P001');self.assertEqual(r['days'],2);self.assertEqual({x['quarantine_qty'] for x in r['rows']},{'1'})
        self.assertEqual(q.history(self.c,start='2026-10-01',end='2026-10-02')['rows'],[])
    def test_pages_complete_decimal_summary_filters_and_no_balance_totals(self):
        for i in range(126):self.plan((date(2026,5,1)+timedelta(days=i)).isoformat())
        first=q.history(self.c,all_dates=True,product_id='P001');seen=[]
        for page in range(1,first['pages']+1):
            r=q.history(self.c,all_dates=True,product_id='P001',page=page);self.assertEqual(r['summary'],first['summary']);seen += [x['business_date'] for x in r['rows']]
        self.assertEqual(len(seen),126);self.assertEqual(len(set(seen)),126);self.assertEqual(first['summary'][0]['production_qty'],'12.6');self.assertEqual(first['summary'][0]['loss_qty'],'1.26');self.assertNotIn('book_qty',first['summary'][0])
        r=q.history(self.c,all_dates=True,product_id='P002');self.assertEqual(r['summary'][0]['production_qty_missing'],126);self.assertIsNone(r['summary'][0]['production_qty'])
        self.assertEqual(q.history(self.c,all_dates=True,product_id='P001',status='registered')['total'],126)
        self.assertEqual(q.history(self.c,all_dates=True,search='% _')['total'],0)
        self.order('2026-05-01',qty='20');self.assertEqual(q.history(self.c,all_dates=True,product_id='P001',status='negative')['total'],1)
    def test_errors_and_index(self):
        for args in ({'page':0},{'page_size':201},{'status':'bad'},{'all_dates':True,'start':'2026-10-01'},{'start':'2026-11-01','end':'2026-10-01'},{'start':'2026-02-30'},{'start':'2000-01-01','end':'2026-01-01'}):
            with self.subTest(args=args),self.assertRaises(ValueError):q.history(self.c,**args)
        sql,args=q.days_sql('2026-09-01','2026-09-30',False);plan=' '.join(r[3] for r in self.c.execute('EXPLAIN QUERY PLAN '+sql,args));self.assertIn('orders_business_date_id',plan);self.assertIn('sqlite_autoindex_stock_closings_1',plan)
        plan=' '.join(r[3] for r in self.c.execute("EXPLAIN QUERY PLAN SELECT payload FROM order_corrections WHERE json_extract(payload,'$.business_date')=? AND json_extract(payload,'$.kind')='shipment'",('2026-09-01',)));self.assertIn('corrections_business_date_kind_id',plan)

class RealOpenStockTests(unittest.TestCase):
    setUp=fixture.OrderCorrectionTests.setUp
    tearDown=fixture.OrderCorrectionTests.tearDown
    snapshot=fixture.OrderCorrectionTests.snapshot
    ops=fixture.OrderCorrectionTests.ops
    prepared=fixture.OrderCorrectionTests.prepared
    correct=fixture.OrderCorrectionTests.correct
    day=fixture.OrderCorrectionTests.day
    def test_real_open_shipment_correction_matches_inventory(self):
        o=self.prepared();self.correct(o,qty=8)
        with erp.connect() as c:
            actual=q.history(c,start=self.day,end=self.day)['rows'];expected=inv.stock(c,self.day)['products']
            for a in actual:
                b=next(x for x in expected if x['product_id']==a['product_id'])
                for k,v in b.items():self.assertEqual(a[k],v,k)
