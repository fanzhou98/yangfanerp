"""SQL history parity, exact receipt decimals and index coverage, synthetic DB only."""
import json,unittest
from unittest.mock import patch
import test_purchasing as fixture
import purchase_query as q,purchasing as p,resources_costs as rc

class PurchaseQueryTests(unittest.TestCase):
    setUp=fixture.PurchasingTests.setUp
    tearDown=fixture.PurchasingTests.tearDown
    def put(self,table,r):self.c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(r['id'],r['id'],rc.dump(r)))
    def seed(self):
        for i in range(90):
            state=['draft','confirmed','confirmed','confirmed','closed','cancelled'][i%6]
            r={'id':f'PQ{i:03d}','version':1,'business_date':f'2026-{9+i%3:02d}-01','expected_date':'2026-12-01','supplier_id':self.s['id'],'supplier_name':'分页供应商','state':state,'total_cents':30,'lines':[{'id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'0.3','price':'1','amount_cents':30}],'note':'特殊%说明' if i==8 else '查询测试'}
            self.put('purchase_orders',r)
            if i%6 in (2,3,4):
                for j,qty in enumerate(['0.1','0.2'] if i%6==3 else ['0.1']):
                    receipt={'id':f'QR{i:03d}-{j}','order_id':r['id'],'business_date':'2026-12-01','amount_cents':int(qty[-1])*10,'lines':[{'line_id':'L1','material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':qty,'amount_cents':int(qty[-1])*10,'material_entry_id':f'M-{i}-{j}'}]}
                    self.put('purchase_receipts',receipt)
    def test_sql_status_pages_and_total_parity(self):
        self.seed();all_rows=p.projection(self.c)['orders'];expected=sorted(all_rows,key=lambda r:(r['business_date'],r['id']),reverse=True)
        seen=[]
        for page in range(1,8):
            result=q.orders(self.c,all_dates=True,page=page,page_size=13);seen.extend(result['rows']);self.assertEqual(result['total'],90);self.assertEqual(result['summary']['total_cents'],2250)
        self.assertEqual(seen,expected)
        for status in q.STATUSES:
            got=q.orders(self.c,all_dates=True,status=status,page_size=200)
            self.assertEqual(got['rows'],[r for r in expected if r['status']==status],status)
        self.assertEqual(q.orders(self.c,all_dates=True,page=100)['page'],2)
    def test_ranges_search_and_selected_projection_only(self):
        self.seed();original=rc.rows
        def guarded(c,table):
            self.assertNotIn(table,('purchase_orders','purchase_receipts','purchase_payments','purchase_charges'))
            return original(c,table)
        with patch.object(rc,'rows',guarded):
            r=q.orders(self.c,start='2026-10-01',end='2026-10-01',page_size=11)
        self.assertEqual(r['total'],30);self.assertEqual(len(r['rows']),11)
        self.assertEqual(q.orders(self.c,all_dates=True,search='%')['rows'][0]['id'],'PQ008')
        self.assertEqual(q.orders(self.c,all_dates=True,supplier_id='missing')['total'],0)
        self.assertEqual(q.orders(self.c,start='2026-10-02',end='2026-10-20')['rows'],[])
    def test_parameters_and_query_plans(self):
        for args in ({'start':'bad'},{'start':'2026-11-01','end':'2026-10-01'},{'page':0},{'page_size':201},{'status':'bad'},{'all_dates':True,'start':'2026-10-01'}):
            with self.subTest(args=args),self.assertRaises(ValueError):q.orders(self.c,**args)
        q._register(self.c)
        for supplier,index in [('', 'purchase_orders_business_date_id'),(self.s['id'],'purchase_orders_supplier_business_date_id')]:
            sql,params=q.sql_scope(start='2026-10-01',end='2026-10-31',all_dates=False,supplier_id=supplier,search='',status='')
            plan=' '.join(r[3] for r in self.c.execute('EXPLAIN QUERY PLAN '+sql,params))
            self.assertIn(index,plan);self.assertIn('purchase_receipts_order_id',plan)
