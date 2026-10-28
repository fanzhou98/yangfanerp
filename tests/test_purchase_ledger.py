"""Q03 receipt/fee/payment SQL pages preserve complete-cost and current-balance semantics."""
import unittest
from unittest.mock import patch
import test_purchasing as fixture
import resources_costs as rc,purchasing as p,purchase_query as q

class PurchaseLedgerTests(unittest.TestCase):
    setUp=fixture.PurchasingTests.setUp
    tearDown=fixture.PurchasingTests.tearDown
    def put(self,table,row):self.c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(row['id'],row['id'],rc.dump(row)))
    def seed(self,n=90):
        for i in range(n):
            oid=f'LO{i:03d}';rid=f'LR{i:03d}';cid=f'LC{i:03d}';mid=f'LM{i:03d}';day=f'{1+i%2:02d}'
            self.put('purchase_orders',{'id':oid,'state':'confirmed','version':1,'business_date':'2026-09-01','supplier_id':self.s['id'],'supplier_name':'货源大豆厂','payment_days':30,'total_cents':30,'lines':[{'id':'L1','material_id':'RM-SOY','material_name':'大豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'0.3','price':'1','amount_cents':30}]})
            self.put('purchase_receipts',{'id':rid,'order_id':oid,'business_date':'2026-10-'+day,'supplier_id':self.s['id'],'supplier_name':'货源大豆厂','due_date':'2026-11-01','amount_cents':30,'lines':[{'line_id':'L1','material_id':'RM-SOY','material_name':'大豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'0.3','amount_cents':30,'material_entry_id':mid}],'note':'字面%搜索' if i==8 else '合成验收'})
            self.put('purchase_charges',{'id':cid,'order_id':oid,'receipt_id':rid,'business_date':'2026-11-'+day,'due_date':'2027-01-01','kind':'freight' if i%2 else 'unloading','supplier_id':'TRANSPORT-PAYEE','supplier_name':'运输收款方','payee_name':'测试承运人','amount_cents':30,'allocations':[{'material_entry_id':mid,'amount_cents':30}]})
            self.put('purchase_payments',{'id':f'LPG{i:03d}','order_id':oid,'supplier_id':self.s['id'],'supplier_name':'货源大豆厂','business_date':'2026-12-'+day,'amount_cents':10})
            if i%3:self.put('purchase_payments',{'id':f'LPC{i:03d}','charge_id':cid,'order_id':oid,'supplier_id':'TRANSPORT-PAYEE','supplier_name':'运输收款方','payee_name':'测试承运人','business_date':'2026-12-'+day,'amount_cents':5 if i%3==1 else 30})
    def test_all_pages_match_full_projection_and_summaries(self):
        self.seed();baseline=p.projection(self.c)
        for kind in ('receipts','payments','charges'):
            expected=sorted(baseline[kind],key=lambda r:(r['business_date'],r['id']),reverse=True)
            if kind!='receipts':expected=[{**r,'order_supplier_id':self.s['id'],'order_supplier_name':'货源大豆厂'} for r in expected]
            first=q.ledger(self.c,kind=kind,all_dates=True,page_size=13);seen=[]
            for page in range(1,first['pages']+1):
                result=q.ledger(self.c,kind=kind,all_dates=True,page_size=13,page=page);seen.extend(result['rows']);self.assertEqual(result['summary'],first['summary'])
            self.assertEqual(seen,expected,kind)
            self.assertEqual(first['summary']['amount_cents'],sum(r['amount_cents'] for r in expected))
        self.assertEqual(q.ledger(self.c,kind='charges',all_dates=True)['summary']['outstanding_cents'],1650)
        self.assertEqual(q.ledger(self.c,kind='receipts',all_dates=True)['summary']['inventory_cost_cents'],5400)
    def test_dates_source_supplier_and_current_paid_balance(self):
        self.seed()
        self.assertEqual(q.ledger(self.c,kind='receipts',start='2026-09-01')['total'],0)
        r=q.ledger(self.c,kind='receipts',start='2026-10-01',end='2026-10-01');self.assertEqual(r['total'],45);self.assertEqual(r['summary']['inventory_cost_cents'],2700)
        fees=q.ledger(self.c,kind='charges',start='2026-11-01',end='2026-11-02',supplier_id=self.s['id']);self.assertEqual(fees['total'],90);self.assertEqual(fees['summary']['paid_cents'],1050)
        self.assertEqual(q.ledger(self.c,kind='charges',all_dates=True,supplier_id='TRANSPORT-PAYEE')['total'],0)
        self.assertEqual(q.ledger(self.c,kind='payments',start='2026-11-01',end='2026-11-30')['total'],0)
        self.assertEqual(q.ledger(self.c,kind='payments',all_dates=True,payment_kind='goods')['total'],90)
        self.assertEqual(q.ledger(self.c,kind='payments',all_dates=True,payment_kind='charge',supplier_id=self.s['id'])['total'],60)
        self.assertEqual(q.ledger(self.c,kind='payments',all_dates=True,search='测试承运人')['total'],60)
        self.assertEqual(q.ledger(self.c,kind='charges',all_dates=True,status='paid')['total'],30)
        self.assertEqual(q.ledger(self.c,kind='charges',all_dates=True,status='unpaid')['total'],60)
        self.assertEqual(q.ledger(self.c,kind='charges',all_dates=True,charge_kind='freight')['total'],45)
        self.assertEqual(q.ledger(self.c,kind='receipts',all_dates=True,search='%')['rows'][0]['id'],'LR008')
        self.assertEqual(q.ledger(self.c,kind='charges',all_dates=True,status='overdue')['total'],0)
        self.c.execute("UPDATE purchase_charges SET payload=json_set(payload,'$.due_date','2000-01-01') WHERE id='LC000'")
        self.assertEqual(q.ledger(self.c,kind='charges',all_dates=True,status='overdue')['total'],1)
    def test_indexes_scoped_reads_validation_and_no_writes(self):
        self.seed();before=self.c.total_changes
        original=rc.rows
        def guarded(c,table):
            self.assertNotIn(table,('purchase_orders','purchase_receipts','purchase_payments','purchase_charges'));return original(c,table)
        with patch.object(rc,'rows',guarded):
            for kind in ('receipts','payments','charges'):self.assertEqual(len(q.ledger(self.c,kind=kind,all_dates=True)['rows']),50)
        self.assertEqual(self.c.total_changes,before)
        self.assertFalse(self.c.execute("SELECT 1 FROM sqlite_master WHERE name='purchase_payments_business_date_id'").fetchone())
        for kind in ('receipts','payments','charges'):
            sql,params=q.ledger_sql(kind,start='2026-10-01',end='2026-12-31',all_dates=False)
            plan=' '.join(r[3] for r in self.c.execute('EXPLAIN QUERY PLAN '+sql,params));self.assertIn('purchase_payments_date_id' if kind=='payments' else 'purchase_'+kind+'_business_date_id',plan)
            if kind=='receipts':self.assertIn('purchase_charges_receipt_id',plan)
            if kind=='charges':self.assertIn('purchase_payments_charge_id',plan)
        for args in ({'kind':'bad'},{'kind':'receipts','status':'paid'},{'kind':'charges','payment_kind':'goods'},{'kind':'payments','charge_kind':'freight'},{'kind':'payments','page_size':0},{'all_dates':True,'start':'2026-10-01'},{'start':'2026-11-01','end':'2026-10-01'}):
            with self.subTest(args=args),self.assertRaises(ValueError):q.ledger(self.c,**args)
        self.assertEqual(q.ledger(self.c,kind='receipts',all_dates=True,page=1000)['page'],2)
    def test_pending_orders_include_old_backlog_and_keep_complete_lines(self):
        self.seed(2);self.c.execute("UPDATE purchase_orders SET payload=json_set(payload,'$.lines[0].qty','0.5') WHERE id='LO000'")
        r=q.ledger(self.c,kind='pending',all_dates=True);self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['lines'][0]['remaining_qty'],'0.2')
        self.assertEqual(q.ledger(self.c,kind='pending',start='2026-10-01')['total'],0)
