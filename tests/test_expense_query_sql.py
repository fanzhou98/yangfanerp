"""Expense workflow SQL must match the established accounting projection."""
import json
import time
import unittest
from unittest.mock import patch
import expense_query as eq
import resource_query as rq
import resources_costs as rc
import test_workflow as fixture

erp=fixture.erp


class ExpenseSQLTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.WorkflowTests();self.old=erp.DB;self.case.setUp()
        with erp.connect(True) as c:
            for table in ('indirect_expenses','expense_reviews','expense_payments','payroll_records'):c.execute('DELETE FROM '+table)
            for number in range(12):self.put(c,'indirect_expenses',self.expense(f'E{number:02d}'))
            self.review(c,'E01','approve');self.review(c,'E02','return')
            self.pay(c,'E03',3000,'\t 唯一收款方\u3000');self.pay(c,'E04',10000)
            self.edit(c,'E03',partner='');self.edit(c,'E05',category='depreciation',payment_mode='noncash')
            self.edit(c,'E06',category='wages-production',payment_mode='payroll',payroll_sheet_id='SHEET',amount_cents=6000)
            self.edit(c,'E07',category='wages-management',payment_mode='payroll',payroll_sheet_id='SHEET',amount_cents=4000)
            self.edit(c,'E08',review_reset_version=4);self.review(c,'E08','approve',version=3)
            self.edit(c,'E09',voided=True,partner='')
            self.edit(c,'E10',payment_mode=None)
            self.edit(c,'E11',partner='');self.pay(c,'E11',2000,'甲');self.pay(c,'E11',1000,'乙')
            self.put(c,'payroll_records',{'id':'SHEET','kind':'sheet','rows':[{'employee_id':'W1'},{'employee_id':'W2','salary_category':'wages-management'}]})
            self.put(c,'payroll_records',{'id':'WP1','kind':'payment','month':'2026-10','employee_id':'W1','business_date':'2026-11-01','amount_cents':3000})
            self.put(c,'payroll_records',{'id':'WP2','kind':'payment','month':'2026-10','employee_id':'W2','business_date':'2026-11-01','amount_cents':1500})
            self.put(c,'indirect_expenses',self.expense('SPREAD',period='2026-09',amount_cents=10001,spread_months=3,accruals=[{'period':'2026-09','amount_cents':3334},{'period':'2026-10','amount_cents':3334},{'period':'2026-11','amount_cents':3333}]))

    @staticmethod
    def expense(key,**extra):return {'id':key,'version':2,'business_date':'2026-10-20','period':'2026-10','category':'office','payment_mode':'payable','partner':'费用方','handler':'测试','note':'合成费用','amount_cents':10000,**extra}
    @staticmethod
    def put(c,table,row):c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(row['id'],row['id'],rc.dump(row)))
    @staticmethod
    def edit(c,key,**extra):
        row=json.loads(c.execute('SELECT payload FROM indirect_expenses WHERE id=?',(key,)).fetchone()[0]);row.update(extra)
        c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(rc.dump(row),key))
    def review(self,c,key,decision,version=2,suffix=''):
        self.put(c,'expense_reviews',{'id':'RV-'+key+suffix,'expense_id':key,'expense_version':version,'decision':decision,'created_at':'2026-10-20T12:00:00+08:00','handler':'测试'})
    def pay(self,c,key,amount,payee='费用方'):
        self.put(c,'expense_payments',{'id':'PAY-'+key+'-'+str(amount),'expense_id':key,'business_date':'2026-11-01','amount_cents':amount,'payee':payee})
    def tearDown(self):self.case.tearDown();erp.DB=self.old

    def test_every_workflow_state_and_payroll_total_matches_existing_projection(self):
        with erp.connect() as c:
            expected={e['id']:e for e in rc.expense_projection(c)};eq.register(c);sql,args=eq.projection()
            actual=eq.dicts(c,sql+'SELECT id,payment_required,payment_state,partner,paid_cents,outstanding_cents FROM projected',args)
        for row in actual:
            original=expected[row['id']]
            for key in ('payment_required','payment_state','partner','paid_cents','outstanding_cents'):self.assertEqual(row[key],original[key],(row['id'],key))
        self.assertEqual(expected['E06']['paid_cents'],3000);self.assertEqual(expected['E07']['paid_cents'],1500)
        self.assertEqual(expected['E03']['partner'],'唯一收款方')

    def test_state_pages_and_full_summary_match_all_source_bills(self):
        with erp.connect() as c:
            expected=rc.expense_projection(c)
            for stage in ('all','review','pay','returned','paid','voided','payroll','noncash'):
                def matches(e):
                    if stage=='voided':return bool(e.get('voided'))
                    if e.get('voided'):return False
                    return stage=='all' or e['payment_state']==('pending' if stage=='review' else stage) or stage=='pay' and e['payment_state'] in ('approved','partial')
                expected_ids={e['id'] for e in expected if matches(e)}
                pages=[]
                for page in range(1,max(1,(len(expected_ids)+2)//3)+1):
                    result=rq.ledger(c,kind='expenses',all_dates=True,stage=stage,page=page,page_size=3);pages.extend(e['id'] for e in result['rows'])
                    active=[e for e in expected if not e.get('voided')]
                    self.assertEqual(result['summary']['paid_cents'],sum(e['paid_cents'] for e in active))
                    self.assertEqual(result['summary']['outstanding_cents'],sum(e['outstanding_cents'] for e in active))
                self.assertEqual(set(pages),expected_ids,stage);self.assertEqual(len(pages),len(set(pages)))

    def test_accrual_lookup_update_delete_and_rollback_follow_source_atomically(self):
        with erp.connect(True) as c:
            self.assertEqual(rq.ledger(c,all_dates=True,period='2026-11')['summary']['total_cents'],3333)
            before=[tuple(r) for r in c.execute("SELECT * FROM expense_accrual_lookup WHERE expense_id='SPREAD' ORDER BY position")]
            source=c.execute("SELECT payload FROM indirect_expenses WHERE id='SPREAD'").fetchone()[0]
            c.execute('SAVEPOINT edit_bill');self.edit(c,'SPREAD',period='2026-12',amount_cents=5000,accruals=[])
            self.assertEqual(c.execute("SELECT period,amount_cents FROM expense_accrual_lookup WHERE expense_id='SPREAD'").fetchone()[:],('2026-12',5000))
            c.execute('ROLLBACK TO edit_bill');c.execute('RELEASE edit_bill')
            self.assertEqual(source,c.execute("SELECT payload FROM indirect_expenses WHERE id='SPREAD'").fetchone()[0])
            self.assertEqual(before,[tuple(r) for r in c.execute("SELECT * FROM expense_accrual_lookup WHERE expense_id='SPREAD' ORDER BY position")])
            c.execute("DELETE FROM indirect_expenses WHERE id='SPREAD'");self.assertEqual(c.execute("SELECT COUNT(*) FROM expense_accrual_lookup WHERE expense_id='SPREAD'").fetchone()[0],0)

    def test_existing_lookup_survives_missing_migration_record(self):
        import migrations
        with erp.connect(True) as c:
            before=[tuple(r) for r in c.execute('SELECT * FROM expense_accrual_lookup ORDER BY expense_id,position')]
            sources=[tuple(r) for r in c.execute('SELECT * FROM indirect_expenses ORDER BY id')]
            c.execute("DELETE FROM schema_migrations WHERE id='069-expense-accrual-query'")
            c.execute('PRAGMA user_version=56');migrations.ensure(c)
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM expense_accrual_lookup ORDER BY expense_id,position')])
            self.assertEqual(sources,[tuple(r) for r in c.execute('SELECT * FROM indirect_expenses ORDER BY id')])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations WHERE id='069-expense-accrual-query'").fetchone()[0],1)

    def test_review_reset_and_latest_insertion_order_are_preserved(self):
        with erp.connect(True) as c:
            self.review(c,'E08','return',4,'-NEW');self.review(c,'E08','approve',4,'-LAST')
            c.execute("UPDATE expense_reviews SET payload=json_set(payload,'$.created_at','2020-01-01') WHERE id='RV-E08-LAST'")
            original=rc.expense_projection(c,[json.loads(c.execute("SELECT payload FROM indirect_expenses WHERE id='E08'").fetchone()[0])])[0]
            actual=rq.ledger(c,all_dates=True,record_id='E08',stage='approved')
        self.assertEqual(original['payment_state'],'approved');self.assertEqual(actual['total'],1)

    def test_workflow_counts_are_complete_while_samples_are_bounded(self):
        with erp.connect(True) as c:
            for i in range(65):self.put(c,'indirect_expenses',self.expense(f'EXTRA{i:03d}',business_date='2026-10-19'))
            expected=rc.expense_projection(c);actual=eq.workflow(c,'2026-10-20')
        for key,states in [('costs.review',('pending',)),('costs.pay',('approved','partial')),('costs.write',('returned',))]:
            matches=[e for e in expected if e['payment_required'] and not e.get('voided') and e['payment_state'] in states]
            group=actual['groups'][key]
            self.assertEqual(group['today']+group['carry'],len(matches));self.assertLessEqual(len(group['items']),20)
        self.assertEqual(actual['groups']['costs.review']['carry'],65)

    def test_scoped_reads_decode_pages_and_use_month_and_event_indexes(self):
        with erp.connect(True) as c:
            for i in range(2000):self.put(c,'indirect_expenses',self.expense(f'HISTORY{i:04d}',business_date='2020-01-01',period='2020-01'))
        original=json.loads
        with erp.connect() as c,patch.object(rc,'rows',side_effect=AssertionError('full payload read')),patch.object(json,'loads',wraps=original) as decoder:
            statements=[];c.set_trace_callback(statements.append);start=time.perf_counter();result=rq.ledger(c,all_dates=True,period='2026-11',page_size=5);elapsed=time.perf_counter()-start;c.set_trace_callback(None)
            plans=[]
            for sql in statements:
                if sql.startswith(('SELECT','WITH ')):plans.extend(r[3] for r in c.execute('EXPLAIN QUERY PLAN '+sql))
        plan=' '.join(plans)
        for index in ('expense_accrual_period_id','expense_payments_expense_id','expense_reviews_expense_id'):self.assertIn(index,plan)
        self.assertEqual(result['total'],1);self.assertEqual(result['summary']['total_cents'],3333);self.assertLessEqual(decoder.call_count,5)
        print('EXPENSE_SQL_PLAN '+json.dumps({'history_bills':2000,'rows':len(result['rows']),'json_decodes':decoder.call_count,'seconds':elapsed,'indexes':sorted({r.split('INDEX ',1)[1].split(' ',1)[0] for r in plans if 'INDEX ' in r and 'VIRTUAL' not in r and not r.split('INDEX ',1)[1].startswith('(')})},ensure_ascii=False))

    def test_bootstrap_deferred_skips_expense_history_and_keeps_legacy_default(self):
        with erp.connect() as c:
            before=rc.revision(c);legacy=rc.snapshot(c)
            def only_no_expenses(connection,table):
                if table in ('indirect_expenses','expense_payments','expense_reviews'):raise AssertionError('unexpected full expense '+table)
                return saved(connection,table)
            saved=rc.rows
            with patch.object(rc,'rows',side_effect=only_no_expenses),patch.object(rc,'expense_projection',side_effect=AssertionError('full expense projection')):
                deferred=rc.snapshot(c,include_expense_history=False)
        self.assertTrue(legacy['expenses']);self.assertTrue(deferred['expense_history_deferred'])
        for key in ('expenses','expense_payables','expense_payments'):self.assertEqual(deferred[key],[])
        self.assertEqual(deferred['revision'],before)
