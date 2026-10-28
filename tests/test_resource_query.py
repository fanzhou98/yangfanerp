"""Q02 date semantics, full totals, stable pages and SQL index evidence."""
import json
import time
import unittest
import resource_query as q
import migrations
import test_workflow as fixture

erp=fixture.erp


class ResourceQueryTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.WorkflowTests();self.old=erp.DB;self.case.setUp()
        with erp.connect(True) as c:
            for table in ('indirect_expenses','expense_reviews','expense_payments','byproduct_sales'):c.execute('DELETE FROM '+table)
            for i in range(125):
                eid=f'EXQ{i:03d}'
                e={'id':eid,'version':1,'business_date':'2026-09-15' if i<65 else '2026-10-15','period':'2026-09' if i<65 else '2026-10','category':'office','amount_cents':10000,'partner':'测试收款方','handler':'测试人','note':'跨月费用','reference':'REF','payment_mode':'payable'}
                self.put(c,'indirect_expenses',e)
                self.put(c,'expense_reviews',{'id':f'ERQ{i:03d}','expense_id':eid,'expense_version':1,'decision':'approve'})
                self.put(c,'expense_payments',{'id':f'EPQ{i:03d}','expense_id':eid,'business_date':'2026-10-20','amount_cents':2000,'payee':'测试收款方'})
                b={'id':f'BPQ{i:03d}','version':1,'business_date':e['business_date'],'customer_id':'BQC','buyer':'豆渣客户','qty':'1.125','unit':'吨' if i==0 else '公斤','price':'1','amount_cents':10000,'received_cents':3000,'receipts':[{'business_date':'2026-10-21','amount_cents':2000,'note':'次月到账'}]}
                self.put(c,'byproduct_sales',b)
            self.put(c,'indirect_expenses',{'id':'EX-SPREAD','business_date':'2026-08-01','period':'2026-08','category':'rent','payment_mode':'payable','partner':'房东','amount_cents':30000,'accruals':[{'period':'2026-08','amount_cents':10000},{'period':'2026-09','amount_cents':10000},{'period':'2026-10','amount_cents':10000}],'version':1})
            self.put(c,'indirect_expenses',{'id':'EX-VOID','business_date':'2026-09-15','period':'2026-09','category':'office','amount_cents':99999,'voided':True,'version':1})

    @staticmethod
    def put(c,table,row):
        c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(row['id'],'req-'+row['id'],json.dumps(row)))

    def tearDown(self):self.case.tearDown();erp.DB=self.old

    def read(self,**kw):
        with erp.connect() as c:
            c.execute('BEGIN')
            return q.ledger(c,**{'all_dates':True,**kw})

    def test_expense_accrual_and_business_date_are_separate(self):
        r=self.read(period='2026-09')
        self.assertEqual((r['total'],r['summary']['total_cents']),(66,660000))
        self.assertEqual(r['summary']['paid_cents'],130000)
        self.assertEqual(r['categories'],{'office':650000,'rent':10000})
        r=self.read(period='2026-09',start='2026-09-01',end='2026-09-30')
        self.assertEqual((r['total'],r['summary']['total_cents']),(65,650000))
        self.assertEqual(self.read(period='2026-09',stage='voided')['rows'][0]['id'],'EX-VOID')
        self.assertNotIn('EX-VOID',[e['id'] for e in self.read(stage='review')['rows']])

    def test_pages_have_unique_stable_ids_and_global_totals(self):
        ids=[]
        for page in (1,2,3):
            r=self.read(page=page)
            self.assertEqual(r['summary']['total_cents'],1280000)
            ids.extend(e['id'] for e in r['rows'])
        self.assertEqual(len(ids),126);self.assertEqual(len(set(ids)),126)
        self.assertEqual(self.read(page=100)['page'],3)
        self.assertEqual(self.read(stage='pay')['total'],125)
        self.assertEqual(self.read(query='房东')['total'],1)
        self.assertEqual(self.read(query='办公')['total'],125)

    def test_payment_dates_include_historical_bills(self):
        r=self.read(kind='payments',payment_start='2026-10-20',payment_end='2026-10-20',period='2026-09')
        self.assertEqual((r['total'],r['payment_summary']['amount_cents']),(65,130000))
        self.assertEqual(len(r['rows']),50)
        self.assertEqual(self.read(kind='payments',payment_start='2026-09-01',payment_end='2026-09-30')['total'],0)
        self.assertEqual(self.read(kind='payments',start='2026-10-01',end='2026-10-31')['total'],60)

    def test_byproduct_sale_and_receipt_dates_and_units(self):
        r=self.read(kind='byproducts',start='2026-09-01',end='2026-09-30')
        self.assertEqual((r['total'],r['summary']['amount_cents']),(65,650000))
        self.assertEqual(r['summary']['qty_kg'],'1197')
        ids=[]
        for page in (1,2,3):ids.extend(e['id'] for e in self.read(kind='byproducts',page=page)['rows'])
        self.assertEqual(len(ids),125);self.assertEqual(len(set(ids)),125)
        r=self.read(kind='byproduct-receipts',payment_start='2026-10-21',payment_end='2026-10-21')
        self.assertEqual((r['total'],r['summary']['amount_cents']),(125,250000))
        r=self.read(kind='byproduct-receipts',payment_start='2026-09-01',payment_end='2026-09-30')
        self.assertEqual((r['total'],r['summary']['amount_cents']),(65,65000))
        r=self.read(kind='byproduct-receipts')
        self.assertEqual((r['total'],r['summary']['amount_cents']),(250,375000))

    def test_invalid_parameters_and_empty_result(self):
        for kw in ({'page':0},{'page':'x'},{'page_size':201},{'start':'2026-10-01'}, {'period':'bad'}, {'kind':'bad'}, {'stage':'bad'}, {'start':'2026-10-01','end':'2026-09-01'}, {'query':'x'*101}):
            with self.assertRaises(ValueError,msg=str(kw)):self.read(**kw)
        r=self.read(query='不存在');self.assertEqual((r['total'],r['page'],r['pages']),(0,1,1))

    def test_actual_queries_use_indexes_and_migration_is_idempotent(self):
        evidence=[]
        with erp.connect() as c:
            for kw in ({'kind':'expenses','start':'2026-09-01','end':'2026-09-30'}, {'kind':'payments','payment_start':'2026-10-01','payment_end':'2026-10-31'}, {'kind':'byproducts','start':'2026-09-01','end':'2026-09-30'}):
                statements=[];c.set_trace_callback(statements.append);t=time.perf_counter();q.ledger(c,all_dates=True,**kw);elapsed=time.perf_counter()-t;c.set_trace_callback(None)
                plans=[]
                for sql in statements:
                    if sql.startswith(('SELECT','WITH ')):
                        plans.extend(row[3] for row in c.execute('EXPLAIN QUERY PLAN '+sql))
                text=' '.join(plans)
                expected={'expenses':'expenses_business_date_id','payments':'expense_payments_date_id','byproducts':'byproducts_business_date_id'}[kw['kind']]
                self.assertIn(expected,text)
                evidence.append({'kind':kw['kind'],'seconds':elapsed,'plans':plans})
            before=c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]
            migrations.ensure(c,'resources')
            self.assertEqual(before,c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0])
        print('RESOURCE_QUERY_PLAN '+json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':unittest.main()
