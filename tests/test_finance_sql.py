"""Q02 SQL reader acceptance: independent facts, real plans and bounded decode."""
import json
import time
import unittest
from unittest.mock import patch
import cash_query
import finance_query as fq
import funds
import resources_costs as rc
import test_workflow as fixture

erp=fixture.erp


class FinanceSQLTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.WorkflowTests();self.old=erp.DB;self.case.setUp()
        with erp.connect(True) as c:
            for table in ('orders','receipts','byproduct_sales','fund_accounts','fund_assignments','fund_transfers','purchase_payments','expense_payments','payroll_records','finished_goods_records','sales_returns'):
                c.execute('DELETE FROM '+table)
            for i in range(2):
                self.put(c,'fund_accounts',{'id':f'FA{i}','name':f'账户{i}','kind':'银行账户','active':i==0,'opening_date':'2026-09-05','opening_balance_cents':10000,'version':1})
            for i in range(150):
                day=('2026-09-15' if i<100 else '2026-10-15');cid='C001' if i%2==0 else 'C002'
                self.put(c,'orders',{'id':f'SQ{i:03d}','version':2,'state':'reviewed','business_date':day,'customer_id':cid,'customer_name':'Straße 老称' if i<10 else '同客户新称','total_cents':10000,'paid_cents':2000,'return_credit_cents':100,'discount_cents':200,'rounding_cents':50,'settlement':{'at':'2026-10-20T01:00:00+08:00'},'lines':[]})
                self.put(c,'receipts',{'id':f'RQ{i:03d}','order_id':f'SQ{i:03d}','received_date':'2026-10-21','amount_cents':2000,'discount_cents':200,'rounding_cents':50,'account_id':'FA0','customer_name':'测试客户'})
            # A sale before the range with a receipt inside it, and an original
            # sale-day receipt; neither may be moved to the other's date.
            self.put(c,'byproduct_sales',{'id':'BQ','version':1,'business_date':'2026-08-31','created_at':'2026-10-20T00:00:00+08:00','customer_id':'C001','buyer':'豆渣客户','qty':'10','unit':'公斤','price':'10','amount_cents':10000,'received_cents':3000,'account_id':'FA1','receipts':[{'business_date':'2026-10-22','amount_cents':2000,'account_id':'FA0','note':'跨月到账'}]})
            self.put(c,'purchase_payments',{'id':'PQ','business_date':'2026-10-22','amount_cents':500,'account_id':'FA0','supplier_name':'供应商'})
            self.put(c,'expense_payments',{'id':'EQ','business_date':'2026-10-22','amount_cents':700,'payee':'费用方'})
            self.put(c,'payroll_records',{'id':'WQ','kind':'payment','business_date':'2026-10-22','amount_cents':300,'account_id':'FA1','employee_name':'员工'})
            self.put(c,'finished_goods_records',{'id':'FQ','kind':'payment','business_date':'2026-10-22','amount_cents':900,'account_id':'FA0','supplier_name':'外购方'})
            self.put(c,'finished_goods_records',{'id':'FQR','kind':'refund','business_date':'2026-10-22','amount_cents':100,'account_id':'FA0','supplier_name':'外购方'})
            self.put(c,'sales_returns',{'id':'RETQ','business_date':'2026-07-01','customer_name':'客户','finance':{'refunds':[{'id':'RFQ','refund_date':'2026-10-22','amount_cents':200,'account_id':'FA0'}]}})
            self.put(c,'fund_transfers',{'id':'TQ','business_date':'2026-10-22','amount_cents':400,'from_account_id':'FA0','to_account_id':'FA1'})
            self.put(c,'receipts',{'id':'RFUTURE','order_id':'FUTURE','received_date':'2026-12-01','amount_cents':100,'account_id':'FA1'})

    @staticmethod
    def put(c,table,row):
        columns=[r[1] for r in c.execute('PRAGMA table_info('+table+')')]
        if 'request_key' in columns:c.execute('INSERT INTO '+table+'(id,request_key,payload) VALUES(?,?,?)',(row['id'],row['id'],rc.dump(row)))
        else:c.execute('INSERT INTO '+table+' VALUES(?,?)',(row['id'],rc.dump(row)))

    def tearDown(self):self.case.tearDown();erp.DB=self.old

    def test_sql_cash_projection_matches_existing_write_fingerprints_for_all_sources(self):
        with erp.connect() as c:
            baseline=funds.movements(c)
            sql,params=cash_query.projection();cash_query.register(c)
            actual=cash_query.dicts(c,sql+'SELECT * FROM resolved ORDER BY business_date DESC,id DESC',params)
        for row in actual:
            if row['source']=='内部转账':row.pop('assignment_version',None)
        self.assertEqual(actual,baseline)
        self.assertEqual(len(actual),161)

    def test_stale_and_current_assignments_keep_original_balance_rules(self):
        with erp.connect(True) as c:
            original=next(r for r in funds.movements(c) if r['id']=='expense_payments:EQ')
            for movement_id,fp in [('expense_payments:EQ',original['fingerprint']),('receipt:RQ000','stale')]:
                value={'movement_id':movement_id,'account_id':'FA1','fingerprint':fp,'version':2}
                c.execute('INSERT INTO fund_assignments VALUES(?,?)',(movement_id,rc.dump(value)))
        with erp.connect() as c:
            expected=funds.movements(c);report=funds.report(c,'2026-10-31')
        self.assertEqual(report['movements'],[r for r in expected if r['business_date']<='2026-10-31'])
        self.assertEqual(next(r for r in report['movements'] if r['id']=='expense_payments:EQ')['account_id'],'FA1')
        self.assertEqual(next(r for r in report['movements'] if r['id']=='receipt:RQ000')['account_id'],'FA0')
        for account in report['accounts']:
            rows=[r for r in expected if r['account_id']==account['id'] and account['opening_date']<=r['business_date']<='2026-10-31']
            balance=10000+sum(r['amount_cents']*(1 if r['direction']=='in' else -1) for r in rows)
            self.assertEqual(account['balance_cents'],balance)
            self.assertEqual(account['movement_count'],sum(r['account_id']==account['id'] or r['source_account_id']==account['id'] for r in expected))

    def test_cash_actual_range_is_inclusive_independent_of_balances_and_pages(self):
        with erp.connect() as c:
            full=funds.report(c,'2026-10-31');first=funds.report(c,'2026-10-31',start='2026-10-21',end='2026-10-21',page=1)
            second=funds.report(c,'2026-10-31',start='2026-10-21',end='2026-10-21',page=2)
            last=funds.report(c,'2026-10-31',start='2026-10-21',end='2026-10-21',page=3)
            clipped=funds.report(c,'2026-10-21',start='2026-10-21',end='2026-12-31',page=1)
            cross=funds.report(c,'2026-10-31',start='2026-10-22',end='2026-10-22',page=1)
        self.assertEqual(first['totals'],full['totals']);self.assertEqual(first['accounts'],full['accounts'])
        self.assertEqual((first['movement_total'],first['flow_totals']['income_cents']),(150,300000))
        ids=[r['id'] for page in (first,second,last) for r in page['movements']]
        self.assertEqual(len(ids),150);self.assertEqual(len(set(ids)),150)
        self.assertEqual(clipped['movement_total'],150)
        self.assertIn('byproduct:BQ:0',[r['id'] for r in cross['movements']])
        self.assertIn('refund:RFQ',[r['id'] for r in cross['movements']])
        self.assertEqual(cross['flow_totals']['count'],9)

    def test_sql_only_reads_do_not_call_full_payload_rows(self):
        with erp.connect() as c,patch.object(rc,'rows',side_effect=AssertionError('unbounded Python reader')):
            cash=funds.report(c,'2026-10-31',page=1,page_size=10)
            bills=fq.ledger(c,'2026-09-01','2026-10-31',clearance='all',page_size=10)
        self.assertEqual(len(cash['movements']),10);self.assertEqual(len(bills['rows']),10)
        self.assertEqual(bills['summary']['total_cents'],1500000)
        self.assertEqual(bills['summary']['outstanding_cents'],1147500)

    def test_settled_date_is_separate_from_bill_and_receipt_dates(self):
        with erp.connect() as c:
            business=fq.ledger(c,'2026-10-20','2026-10-20',clearance='all')
            settled=fq.ledger(c,'2026-10-20','2026-10-20',clearance='all',basis='settled_date',receipt_start='2026-10-21',receipt_end='2026-10-22')
            name=fq.ledger(c,'2026-09-01','2026-10-31',clearance='all',query='STRASSE')
        self.assertEqual(business['total'],0);self.assertEqual(settled['total'],151)
        self.assertEqual(settled['receipt_total'],151);self.assertEqual(name['total'],10)
        self.assertEqual(settled['customers'][0]['customer_name'],'Straße 老称')

    def test_history_growth_keeps_payload_decode_bounded(self):
        with erp.connect(True) as c:
            for i in range(3000):
                self.put(c,'orders',{'id':f'OLD{i:04d}','state':'reviewed','business_date':'2024-01-01','customer_id':'C001','customer_name':'历史客户','total_cents':10000,'paid_cents':10000,'lines':[]})
                self.put(c,'receipts',{'id':f'OLDR{i:04d}','order_id':f'OLD{i:04d}','received_date':'2024-02-01','amount_cents':10000,'account_id':'FA0'})
        original_loads=json.loads
        with erp.connect() as c,patch.object(json,'loads',wraps=original_loads) as decoder:
            begin=time.perf_counter()
            bills=fq.ledger(c,'2026-09-01','2026-10-31',clearance='all',page_size=10)
            cash=funds.report(c,'2026-10-31',start='2026-10-21',end='2026-10-21',page=1,page_size=10)
            elapsed=time.perf_counter()-begin
        self.assertEqual(bills['total'],150);self.assertEqual(cash['movement_total'],150)
        self.assertLessEqual(decoder.call_count,22)
        size=len(json.dumps({'bills':bills,'cash':cash},ensure_ascii=False).encode())
        self.assertLess(size,40000)
        print('FINANCE_SQL_SCALE '+json.dumps({'historical_bills':3000,'historical_receipts':3000,'returned_bill_rows':10,'returned_cash_rows':10,'json_decodes':decoder.call_count,'response_bytes':size,'seconds':elapsed}))

    def test_asof_receivable_uses_receipt_date_not_current_paid(self):
        import production_management as pm
        with erp.connect() as c:
            expected={'2026-10-20':1456500,'2026-10-21':1156500,'2026-10-22':1154500}
            for day,amount in expected.items():
                cash=cash_query.report(c,day)['totals']['receivable_cents']
                self.assertEqual(cash,amount,day)
                self.assertEqual(cash,sum(a['outstanding_cents'] for a in pm.ar_alerts(c,day)),day)

    def test_validation_and_empty_range(self):
        with erp.connect() as c:
            for kw in ({'start':'2026-10-01'},{'start':'2026-10-02','end':'2026-10-01'}, {'start':'2026-10-01','end':'2026-10-02','month':'2026-10'},{'page':0},{'page':100001},{'page_size':201}):
                with self.assertRaises(ValueError,msg=str(kw)):funds.report(c,'2026-10-31',**kw)
            r=funds.report(c,'2026-10-31',start='2026-09-01',end='2026-09-01',page=10)
        self.assertEqual((r['movement_total'],r['movement_pages'],r['movement_page']),(0,1,1))

    def test_corrupt_cash_amount_is_rejected_without_partial_balance(self):
        with erp.connect(True) as c:
            self.put(c,'expense_payments',{'id':'BAD-CASH','business_date':'2026-10-21','amount_cents':-1})
        with erp.connect() as c:
            with self.assertRaisesRegex(ValueError,'金额无效'):funds.report(c,'2026-10-31',page=1)

    def test_actual_sql_query_plans_use_date_indexes(self):
        evidence=[]
        with erp.connect() as c:
            for kind,read in [('receivables',lambda:fq.ledger(c,'2026-09-01','2026-09-30',clearance='all')),
                              ('settled',lambda:fq.ledger(c,'2026-10-20','2026-10-20',clearance='all',basis='settled_date')),
                              ('cash',lambda:funds.report(c,'2026-10-31',start='2026-10-21',end='2026-10-22',page=1))]:
                statements=[];c.set_trace_callback(statements.append);start=time.perf_counter();result=read();elapsed=time.perf_counter()-start;c.set_trace_callback(None)
                plans=[]
                for sql in statements:
                    if sql.startswith('WITH '):plans.extend(row[3] for row in c.execute('EXPLAIN QUERY PLAN '+sql))
                text=' '.join(plans)
                expected=('orders_state_business_date_id','byproducts_business_date_id','receipts_received_date_id') if kind=='receivables' else ('orders_state_settled_date_id','byproducts_created_date_id') if kind=='settled' else ('receipts_received_date_id','purchase_payments_date_id','expense_payments_date_id','payroll_payment_kind_date_id','finished_cash_kind_date_id','fund_transfers_date_id')
                for index in expected:self.assertIn(index,text,(kind,index))
                evidence.append({'kind':kind,'seconds':elapsed,'indexes':sorted({p.split('INDEX ',1)[1].split(' ',1)[0] for p in plans if 'INDEX ' in p and 'VIRTUAL' not in p and not p.split('INDEX ',1)[1].startswith('(')}),'returned_rows':len(result.get('rows',result.get('movements',[])))})
        print('FINANCE_SQL_PLAN '+json.dumps(evidence,ensure_ascii=False))
