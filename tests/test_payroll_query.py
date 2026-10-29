"""Payroll history keeps frozen evidence and separates month/date/current balance."""
import json
import unittest
import payroll_query as query
import test_payroll as fixture

erp=fixture.erp


class PayrollHistoryTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    sheet=fixture.PayrollTests.sheet

    def add(self, payload):
        self.c.execute('INSERT INTO payroll_records VALUES(?,?,?)',(payload['id'],payload['id'],json.dumps(payload)))

    def test_cross_year_payment_is_current_balance_not_date_limited_and_snapshot_is_frozen(self):
        sheet=self.sheet()
        payment=self.save('wage-pay',{'month':'2020-09','employee_id':self.employee['id'],'version':sheet['version'],'paid_cents':0,'amount':'50','business_date':'2021-02-01','handler':'出纳','reference':'跨年付款'})
        # Current employee and salary changes must not rewrite the history view.
        self.c.execute("UPDATE factory_employees SET payload=json_set(payload,'$.name','新姓名') WHERE id=?",(self.employee['id'],))
        self.c.execute("UPDATE payroll_records SET payload=json_set(payload,'$.monthly_cents',999999) WHERE json_extract(payload,'$.kind')='profile'")
        before=[tuple(r) for r in self.c.execute('SELECT * FROM payroll_records ORDER BY id')]
        result=query.history(self.c,start='2020-09-01',end='2020-09-30')
        self.assertEqual(result['total'],1)
        row=result['rows'][0]
        self.assertEqual((row['net_cents'],row['paid_cents'],row['outstanding_cents']),(15595,5000,10595))
        self.assertEqual(row['employee_name'],'测试员工')
        self.assertEqual(query.history(self.c,'payment',start='2020-09-01',end='2020-09-30')['total'],0)
        actual=query.history(self.c,'payment',start='2021-02-01',end='2021-02-01')
        self.assertEqual((actual['total'],actual['rows'][0]['month'],actual['summary']['amount_cents']),(1,'2020-09',5000))
        detail=query.record(self.c,'sheet',sheet['id'],self.employee['id'])
        self.assertEqual(detail['row']['net_cents'],15595)
        self.assertEqual(detail['row']['monthly_cents'],sheet['rows'][0]['monthly_cents'])
        self.assertEqual(detail['cells'][0]['status'],'full')
        self.assertEqual(detail['confirmed_at'],'')
        self.assertNotIn('attendance_token',detail)
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM payroll_records ORDER BY id')])
        self.assertEqual(query.record(self.c,'payment',payment['id'])['business_date'],'2021-02-01')

    def test_complete_pages_summary_filters_and_query_indexes(self):
        self.add({'id':'S-BIG','kind':'sheet','month':'2020-10','state':'confirmed','rows':[{'employee_id':'E-%03d'%i,'employee_name':'人员%03d'%i,'net_cents':100,'monthly_cents':300000} for i in range(126)]})
        for i in range(126):self.add({'id':'P-%03d'%i,'kind':'payment','month':'2020-10','employee_id':'E-%03d'%i,'employee_name':'人员%03d'%i,'amount_cents':100,'business_date':'2021-01-01','handler':'出纳','reference':'流水%03d'%i})
        result=query.history(self.c,all_dates=True,page_size=50)
        self.assertEqual((result['total'],result['pages'],result['summary']['net_cents'],result['summary']['paid_cents']),(126,3,12600,12600))
        ids=[r['employee_id'] for page in (1,2,3) for r in query.history(self.c,all_dates=True,page=page)['rows']]
        self.assertEqual(len(set(ids)),126)
        self.assertEqual(query.history(self.c,all_dates=True,search='人员125')['total'],1)
        self.assertEqual(query.history(self.c,all_dates=True,status='paid')['total'],126)
        self.assertEqual(query.history(self.c,all_dates=True,salary_month='2020-09')['total'],0)
        actual=query.history(self.c,'payment',all_dates=True,page=3)
        self.assertEqual((actual['total'],len(actual['rows']),actual['summary']['amount_cents']),(126,26,12600))
        for kind,start,end,index in [('sheet','2020-10-01','2020-10-31','payroll_history_month'),('payment','2021-01-01','2021-01-01','payroll_payment_kind_date_id')]:
            traces=[];self.c.set_trace_callback(traces.append)
            query.history(self.c,kind,start=start,end=end);self.c.set_trace_callback(None)
            statement=next(s for s in traces if s.startswith('WITH'))
            plan=str([tuple(r) for r in self.c.execute('EXPLAIN QUERY PLAN '+statement)])
            self.assertIn(index,plan)

    def test_draft_unknown_conflicts_and_payment_bank_redaction(self):
        self.add({'id':'D','kind':'sheet','month':'2020-01','state':'draft','rows':[{'employee_id':'E','employee_name':'草稿','net_cents':900}]})
        self.add({'id':'U','kind':'sheet','month':'2020-02','state':'confirmed','rows':[{'employee_id':'E','employee_name':'未知'}]})
        for id in ('C1','C2'):self.add({'id':id,'kind':'sheet','month':'2020-03','state':'confirmed','rows':[{'employee_id':'E','net_cents':100}]})
        result=query.history(self.c,all_dates=True)
        self.assertEqual((result['summary']['draft'],result['summary']['unknown'],result['summary']['conflict']),(1,1,2))
        self.assertEqual(result['summary']['net_cents'],0)
        self.assertIsNone(next(r for r in result['rows'] if r['id']=='U')['net_cents'])
        self.add({'id':'P','kind':'payment','month':'2020-02','employee_id':'E','business_date':'2021-01-01','recipient':{'bank_card':'6222000012345678','bank_name':'原银行','account_name':'原户名'},'fingerprint':'private'})
        detail=query.record(self.c,'payment','P')
        self.assertEqual(detail['recipient']['card_tail'],'5678')
        self.assertNotIn('6222000012345678',json.dumps(detail))
        self.assertNotIn('fingerprint',detail)
        self.assertEqual(query.history(self.c,'payment',all_dates=True)['summary']['unknown'],1)
        for kwargs in ({'page':0},{'kind':'profile'},{'status':'bad'},{'salary_month':'2020-13'},{'all_dates':True,'start':'2020-01-01'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):query.history(self.c,**kwargs)
        with self.assertRaises(ValueError):query.record(self.c,'sheet','D','other')
