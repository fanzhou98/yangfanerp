import unittest,json,tempfile
from pathlib import Path
from decimal import Decimal
import server as erp,stock_history as q,resources_costs as rc,order_corrections as corrections
import test_order_corrections as fixture

class StockHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=erp.DB;erp.DB=Path(self.tmp.name)/'synthetic.db';erp.init_db(demo=False)
        self.ctx=erp.connect(True);self.c=self.ctx.__enter__()
    def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);erp.DB=self.old;self.tmp.cleanup()
    def seed(self,day='2026-09-01',state='closed',**changes):
        p={'product_id':'P001','product_name':'原名称豆腐','unit':'筐',**{k:'0' for k in q.MOVEMENTS},'opening_qty':'10','book_qty':'8','counted_qty':'9','shipped_qty':'2','variance_qty':'1','variance_reason':'合成盘点',**changes}
        r={'business_date':day,'version':1,'state':state,'closed_at':day+'T18:00:00','role':'库管','products':[p]}
        self.c.execute('INSERT INTO stock_closings VALUES(?,?)',(day,rc.dump(r)));return r
    def correction(self,key,delta,anchor='2026-09-01',kind='shipment'):
        a={'id':key,'kind':kind,'business_date':'2026-08-30','stock_anchor_date':anchor,'order_id':'O-SYNTHETIC','reason':'实发更正','at':'2026-10-01','quantity_changes':[{'product_id':'P001','delta_qty':delta}]}
        self.c.execute('INSERT INTO order_corrections VALUES(?,?)',(key,rc.dump(a)))
    def test_restatement_matches_canonical_and_does_not_change_physical_counts(self):
        r=self.seed();self.correction('A','-0.3');self.correction('B','0.1');self.correction('C','100',kind='reopen');self.correction('D','100',anchor='2026-10-01')
        result=q.history(self.c,start='2026-09-01',end='2026-09-01',status='corrected');p=result['rows'][0];expected=corrections.restated_closing(self.c,r)['products'][0]
        for k in q.FIELDS:self.assertEqual(p[k],expected[k],k)
        self.assertEqual(p['counted_qty'],'9');self.assertEqual(p['original_book_qty'],'8');self.assertEqual(p['book_qty'],'8.2');self.assertEqual(p['correction_qty'],'-0.2');self.assertEqual(result['quantities'][0]['shipped_qty'],'1.8')
        self.assertEqual(json.loads(self.c.execute('SELECT payload FROM stock_closings').fetchone()[0]),r)
        self.correction('E','0.2');p=q.history(self.c,all_dates=True,status='corrected')['rows'][0];self.assertEqual(p['correction_qty'],'0');self.assertEqual(p['book_qty'],'8');self.assertTrue(p['corrected'])
    def test_pages_full_summary_stable_dates_and_units(self):
        from datetime import date,timedelta
        for i in range(126):self.seed((date(2026,6,1)+timedelta(days=i)).isoformat(),unit='包' if i==125 else '筐',shipped_qty='0.1',variance_qty='0.01')
        first=q.history(self.c,all_dates=True);seen=[]
        for page in range(1,first['pages']+1):
            r=q.history(self.c,all_dates=True,page=page);self.assertEqual(r['quantities'],first['quantities']);seen += [(x['business_date'],x['product_id']) for x in r['rows']]
        self.assertEqual(len(seen),126);self.assertEqual(len(set(seen)),126);self.assertEqual(first['quantities'][0]['shipped_qty'],'0.1');self.assertEqual(first['quantities'][1]['shipped_qty'],'12.5')
        self.assertNotIn('counted_qty',first['quantities'][0]);self.assertEqual(q.history(self.c,start='2026-06-01',end='2026-06-01')['total'],1)
    def test_reopened_missing_and_literal_search(self):
        self.seed(state='reopened');self.correction('A','5');r=q.history(self.c,all_dates=True);self.assertEqual(r['quantities'],[]);self.assertEqual(r['rows'][0]['book_qty'],'8');self.assertFalse(r['rows'][0]['corrected'])
        self.seed('2026-09-02',shipped_qty=None,opening_qty='',variance_qty='0',variance_reason='literal % _')
        r=q.history(self.c,all_dates=True,search='% _');self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['opening_qty'],None);self.assertEqual(r['quantities'][0]['shipped_qty_missing'],1)
        self.assertEqual(q.history(self.c,start='2026-10-01',end='2026-10-01')['rows'],[]);self.assertEqual(q.history(self.c,all_dates=True,status='variance')['total'],0);self.assertEqual(q.history(self.c,all_dates=True,search='原名称')['total'],2)
    def test_errors_and_query_plan(self):
        self.seed();q.history(self.c,all_dates=True)
        for args in ({'page':0},{'page_size':201},{'status':'bad'},{'all_dates':True,'start':'2026-10-01'},{'start':'2026-11-01','end':'2026-10-01'},{'start':'2026-02-30'}):
            with self.subTest(args=args),self.assertRaises(ValueError):q.history(self.c,**args)
        sql,args=q.source_sql('2026-09-01','2026-09-30',False);plan=' '.join(r[3] for r in self.c.execute('EXPLAIN QUERY PLAN '+sql,args));self.assertIn('sqlite_autoindex_stock_closings_1',plan);self.assertIn('SEARCH a USING INDEX corrections_stock_anchor_kind_id',plan)

class RealClosingHistoryTests(unittest.TestCase):
    setUp=fixture.OrderCorrectionTests.setUp
    tearDown=fixture.OrderCorrectionTests.tearDown
    snapshot=fixture.OrderCorrectionTests.snapshot
    ops=fixture.OrderCorrectionTests.ops
    prepared=fixture.OrderCorrectionTests.prepared
    correct=fixture.OrderCorrectionTests.correct
    day=fixture.OrderCorrectionTests.day
    def test_real_closed_shipment_correction_history_matches_current_projection(self):
        o=self.prepared(count=12);self.correct(o,qty=8)
        with fixture.erp.connect() as c:
            expected=__import__('inventory').closed(c,self.day)['products'];actual=q.history(c,start=self.day,end=self.day)['rows']
            for a in actual:
                b=next(x for x in expected if x['product_id']==a['product_id'])
                for k in q.FIELDS:self.assertEqual(a[k],b[k],k)
