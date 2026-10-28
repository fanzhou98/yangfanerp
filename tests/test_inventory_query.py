"""Synthetic histories: exact quantities, current closure/credits, stable SQL pages."""
import unittest,json
from decimal import Decimal
from unittest.mock import patch
import test_inventory as fixture
import inventory as inv,inventory_query as q

erp=fixture.erp
class InventoryQueryTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    def seed(self,c,n=125):
        for i in range(n):
            r={'id':f'HRT{i:03d}','version':1,'created_at':'2026-10-01T00:00:00+08:00','source_price':'3','reference_price':'3','received_date':f'2026-{9+i%3:02d}-01','customer_id':'C001','customer_name':'合成客户','product_id':'P001','product_name':'豆腐','unit':'筐','qty':'0.3','net_kg':'0.3','reason':'合成%退货' if i==5 else '合成退货','finance':None,'disposals':[]}
            phase=i%7
            if phase==1:r['finance']={'state':'pending_review','amount_cents':30}
            if phase in (2,3,4,5):r['finance']={'state':'posted','amount_cents':30,'allocations':[{'amount_cents':10}],'refunds':[{'amount_cents':20}] if phase!=2 else []}
            if phase in (3,4):r['disposals']=[{'kind':'destroy','qty':'0.1','net_kg':'0.1','business_date':'2026-12-01'},{'kind':'reprocess' if phase==4 else 'destroy','qty':'0.2','net_kg':'0.2','business_date':'2026-12-01','processing_completed':False}]
            if phase==5:r['receipt_mode']='merchant_disposed'
            if phase==6:r['voided']=True
            inv.put(c,'sales_returns',r)
            b={'id':f'HP{i:03d}','version':1,'at':'2026-10-01T00:00:00+08:00','role':'库管','process_mode':'processing','input_qty':'0','source_return_id':r['id'],'business_date':r['received_date'],'product_id':'P004','input_kg':'0.3','origin':'customer_return' if i%2 else 'internal','outputs':[{'product_id':'P005','product_name':'素鸡','unit':'筐','qty':'0.1','net_kg':'0.2'}]}
            if phase==1:b.update(state='pending',outputs=[])
            if phase==6:b['voided']=True
            inv.put(c,'processing_batches',b)
    def test_full_pages_summary_and_current_state_parity(self):
        with erp.connect(True) as c:
            self.seed(c);all_rows=inv.rows(c,'sales_returns');expected=sorted(all_rows,key=lambda r:(r['received_date'],r['id']),reverse=True)
            first=q.history(c,kind='returns',all_dates=True,page_size=17);seen=[]
            for page in range(1,first['pages']+1):
                r=q.history(c,kind='returns',all_dates=True,page_size=17,page=page);seen+=r['rows'];self.assertEqual(r['summary'],first['summary'])
            self.assertEqual(seen,expected);self.assertEqual(first['total'],125)
            valid=[r for r in all_rows if not r.get('voided')];qty=first['quantities'][0]
            self.assertEqual(Decimal(qty['qty']),Decimal('.3')*len(valid));self.assertEqual(Decimal(qty['remaining_qty']),sum((inv.remaining_return(r)[0] for r in valid),Decimal(0)))
            self.assertEqual(first['summary']['wallet_cents'],sum(inv.wallet(r) for r in valid))
            closed=[r['id'] for r in expected if not r.get('voided') and all(v<=0 for v in inv.remaining_return(r)) and not any(d['kind']=='reprocess' and not d.get('voided') and not d.get('processing_completed') for d in r['disposals']) and (r.get('finance') or {}).get('state')=='posted' and inv.wallet(r)==0]
            self.assertEqual([r['id'] for r in q.history(c,all_dates=True,status='closed',page_size=200)['rows']],closed)
            self.assertTrue(q.history(c,all_dates=True,status='account')['total']);self.assertTrue(q.history(c,all_dates=True,status='processing')['total'])
            self.assertEqual(q.history(c,all_dates=True,search='%')['total'],1)
    def test_processing_legacy_completed_and_outputs_units(self):
        with erp.connect(True) as c:
            self.seed(c);r=q.history(c,kind='processing',all_dates=True,page_size=200);raw=inv.rows(c,'processing_batches')
            self.assertEqual(r['rows'],sorted(raw,key=lambda v:(v['business_date'],v['id']),reverse=True))
            valid=[b for b in raw if not b.get('voided')];self.assertEqual(Decimal(r['quantities'][0]['input_kg']),Decimal('.3')*len(valid))
            self.assertEqual(Decimal(r['outputs'][0]['qty']),sum((Decimal(o['qty']) for b in valid for o in b['outputs']),Decimal(0)))
            self.assertEqual(q.history(c,kind='processing',all_dates=True,status='completed')['total'],sum(not b.get('voided') and b.get('state','completed')=='completed' for b in raw))
            self.assertEqual(q.history(c,kind='processing',all_dates=True,product_id='P005')['total'],sum(bool(b['outputs']) for b in raw))
            self.assertEqual(q.history(c,kind='processing',all_dates=True,origin='internal')['total'],63)
            raw[0]['outputs'][0].pop('net_kg');inv.put(c,'processing_batches',raw[0]);self.assertEqual(q.history(c,kind='processing',all_dates=True)['outputs'][0]['missing_net_kg'],1)
    def test_dates_indexes_no_global_projection_and_parameters(self):
        with erp.connect(True) as c:
            self.seed(c);before=c.total_changes
            with patch.object(inv,'rows',side_effect=AssertionError('global history read')):
                self.assertEqual(q.history(c,start='2026-10-01',end='2026-10-01')['total'],42)
                self.assertEqual(q.history(c,start='2026-10-02',end='2026-10-03')['total'],0)
            self.assertEqual(c.total_changes,before)
            for kind,index in [('returns','sales_returns_received_date_id'),('processing','processing_business_date_id')]:
                sql,args=q.query_sql(kind,'2026-10-01','2026-10-31',False);plan=' '.join(r[3] for r in c.execute('EXPLAIN QUERY PLAN '+sql,args));self.assertIn(index,plan)
            for args in ({'kind':'bad'},{'status':'bad'},{'kind':'processing','customer_id':'C001'},{'origin':'internal'},{'all_dates':True,'start':'2026-10-01'},{'page':0},{'page_size':201},{'start':'2026-10-02','end':'2026-10-01'}):
                with self.subTest(args=args),self.assertRaises(ValueError):q.history(c,**args)
            scoped=q.scope(q.history(c,all_dates=True),False);text=json.dumps(scoped);self.assertNotIn('"finance"',text);self.assertNotIn('_cents',text);self.assertNotIn('price',text)
