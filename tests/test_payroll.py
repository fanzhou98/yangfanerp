import unittest,tempfile,uuid,json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch
import test_workflow as fixture
import production_management as fm
import payroll
import erp_access as access

erp=fixture.erp
class PayrollTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(erp,'DB',Path(self.tmp.name)/'test-payroll.db');self.db.start();erp.init_db();self.ctx=erp.connect(True);self.c=self.ctx.__enter__()
        self.c.execute('DELETE FROM orders');self.c.execute('DELETE FROM warehouse_plans')
        self.employee=fm.save(self.c,'employee',{'request_key':str(uuid.uuid4()),'name':'测试员工','group_id':'G-TOFU','active':True},'管理员',erp.now,erp.audit)
        for d,status in [('2020-09-01','full'),('2020-09-02','half')]:
            fm.save(self.c,'attendance',{'request_key':str(uuid.uuid4()),'business_date':d,'format':'group-day-v2','state':'confirmed','groups':[{'group_id':'G-TOFU','start_time':'21:00','end_time':'05:00'}],'entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':status}]},'管理员',erp.now,erp.audit)
    def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);self.db.stop();self.tmp.cleanup()
    def save(self,kind,b,role='管理员'):return fm.save(self.c,kind,{'request_key':str(uuid.uuid4()),**b},role,erp.now,erp.audit)
    def sheet(self,state='confirmed',version=0):
        r=payroll.report(self.c,'2020-09');return self.save('wage-sheet',{'month':'2020-09','version':version,'state':state,'attendance_token':r['attendance_token'],'salary_token':r['salary_token'],'rows':[{'employee_id':self.employee['id'],'daily_rate':'100.01','bonus':'10','deduction':'2','reason':'测试调整'}]})
    def test_attendance_and_rounding_and_payments(self):
        r=payroll.attendance(self.c,'2020-09');self.assertEqual(r['rows'][0]['pay_days'],'1.5');self.assertEqual(r['rows'][0]['unresolved'],0)
        s=self.sheet();self.assertEqual(s['rows'][0]['base_cents'],14795);self.assertEqual(s['rows'][0]['net_cents'],15595)
        b={'request_key':str(uuid.uuid4()),'month':'2020-09','employee_id':self.employee['id'],'version':s['version'],'paid_cents':0,'amount':'50','business_date':'2020-10-01','handler':'测试出纳','reference':'TEST'}
        p=fm.save(self.c,'wage-pay',b,'出纳',erp.now,erp.audit);self.assertEqual(fm.save(self.c,'wage-pay',b,'出纳',erp.now,erp.audit),p)
        self.assertEqual(payroll.report(self.c,'2020-09')['outstanding_cents'],10595)
        with self.assertRaisesRegex(ValueError,'超过'):self.save('wage-pay',{**b,'request_key':str(uuid.uuid4()),'amount':'200'})
        with self.assertRaisesRegex(ValueError,'已有工资发放'):self.save('wage-reopen',{'month':'2020-09','version':s['version']})
    def test_monthly_daily_rate_is_annualized_and_not_month_length_dependent(self):
        profile={'salary_mode':'monthly','monthly_cents':300000}
        counts={k:0 for k in ('full','half','leave','absent','rest')}
        feb=payroll.salary_calculation({'counts':counts,'pay_days':'28'},profile,'2021-02')
        mar=payroll.salary_calculation({'counts':counts,'pay_days':'31'},profile,'2021-03')
        self.assertEqual(feb['rate_cents'],mar['rate_cents'])
        self.assertEqual(feb['rate_cents'],payroll.rc.ds(payroll.daily_cents(300000)))
        self.assertEqual(feb['attendance_cents'],int((Decimal('28')*Decimal(feb['rate_cents'])).quantize(Decimal('1'),rounding=ROUND_HALF_UP)))
        self.assertIn('12÷365',feb['calculation_note'])
    def test_stale_attendance_and_draft_protection(self):
        s=self.sheet();a=fm.rows(self.c,'attendance')[0];a['state']='draft';self.c.execute('UPDATE factory_attendance SET payload=? WHERE id=?',(json.dumps(a),a['id']))
        self.assertTrue(payroll.report(self.c,'2020-09')['stale'])
        with self.assertRaisesRegex(ValueError,'考勤发生变化'):self.save('wage-pay',{'month':'2020-09'})
        self.save('wage-reopen',{'month':'2020-09','version':s['version']})
        with self.assertRaisesRegex(ValueError,'考勤'):self.sheet(version=2)

    def test_partly_paid_sheet_survives_master_changes_without_rewriting_snapshot(self):
        s=self.sheet();snapshot=self.c.execute('SELECT payload FROM payroll_records WHERE id=?',(s['id'],)).fetchone()[0]
        payment={'month':'2020-09','employee_id':self.employee['id'],'version':s['version'],'business_date':'2020-10-01','handler':'测试出纳','reference':'TEST'}
        self.save('wage-pay',{**payment,'paid_cents':0,'amount':'50'})
        employee=self.save('employee',{'id':self.employee['id'],'version':self.employee['version'],'name':'更名员工','group_id':'G-SKIN','active':False})
        self.save('employee',{'name':'后来入职员工','group_id':'G-TOFU','active':True})
        group=next(g for g in fm.rows(self.c,'group') if g['id']=='G-TOFU')
        self.save('group',{'id':group['id'],'version':group['version'],'name':'新组名','active':True})
        r=payroll.report(self.c,'2020-09')
        self.assertFalse(r['stale']);self.assertEqual(r['outstanding_cents'],10595)
        self.assertEqual([row['employee_id'] for row in r['rows']],[employee['id']])
        self.assertEqual(r['rows'][0]['employee_name'],'测试员工')
        self.assertEqual(self.c.execute('SELECT payload FROM payroll_records WHERE id=?',(s['id'],)).fetchone()[0],snapshot)
        # The frozen rows also support sheets created with the old broad token.
        self.assertNotEqual(s['attendance_token'],r['attendance_token'])
        self.save('wage-pay',{**payment,'paid_cents':5000,'amount':'105.95'})
        self.assertEqual(payroll.report(self.c,'2020-09')['outstanding_cents'],0)

    def test_actual_attendance_change_still_blocks_partly_paid_sheet(self):
        s=self.sheet();payment={'month':'2020-09','employee_id':self.employee['id'],'version':s['version'],'business_date':'2020-10-01','handler':'测试出纳','reference':'TEST'}
        self.save('wage-pay',{**payment,'paid_cents':0,'amount':'50'})
        a=next(r for r in fm.rows(self.c,'attendance') if r['business_date']=='2020-09-01')
        self.save('attendance',{'id':a['id'],'version':a['version'],'business_date':a['business_date'],'format':'group-day-v2','state':'confirmed','groups':[{'group_id':'G-TOFU','start_time':'21:00','end_time':'05:00'}],'entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':'half'}]})
        self.assertTrue(payroll.report(self.c,'2020-09')['stale'])
        with self.assertRaisesRegex(ValueError,'考勤发生变化'):self.save('wage-pay',{**payment,'paid_cents':5000,'amount':'1'})
        with self.assertRaisesRegex(ValueError,'核对后打印'):payroll.slip_html(payroll.report(self.c,'2020-09'),self.employee['id'])

    def test_draft_sheet_still_detects_new_staff(self):
        self.sheet(state='draft')
        self.save('employee',{'name':'新增员工','group_id':'G-TOFU','active':True})
        self.assertTrue(payroll.report(self.c,'2020-09')['stale'])
    def test_profiles_permissions_filters_and_print(self):
        p=self.save('wage-profile',{'employee_id':self.employee['id'],'monthly_salary':'3650','version':1},'会计');self.assertEqual(payroll.report(self.c,'2020-09')['rows'][0]['monthly_cents'],365000)
        with self.assertRaises(ValueError):self.save('wage-profile',{'employee_id':self.employee['id'],'monthly_salary':'3650','version':1},'厂长')
        r=payroll.attendance(self.c,'2020-09');self.assertEqual(len(payroll.filtered(r,'G-TOFU','测试','half')),1);self.assertFalse(payroll.filtered(r,'','不存在',''))
        html=payroll.print_html(r,{});self.assertEqual(html.count('class="print-page"'),1);self.assertIn('/print.css',html);self.assertIn('测试员工',html);self.assertNotIn('<th>固定组</th>',html);self.assertNotIn('<th>待核对</th>',html)
        with self.assertRaises(ValueError):payroll.month_days('2020-13')
    def test_conflict_missing_and_future_records(self):
        d=fm.rows(self.c,'attendance')[0];d['id']='duplicate';d['request_key']='duplicate';self.c.execute('INSERT INTO factory_attendance VALUES(?,?,?)',('duplicate','duplicate',json.dumps(d)))
        r=payroll.attendance(self.c,'2020-09');self.assertEqual(r['rows'][0]['counts']['conflict'],1)
        with self.assertRaisesRegex(ValueError,'考勤'):self.sheet()
        d['business_date']='2099-01-01';d['id']='future';self.c.execute('INSERT INTO factory_attendance VALUES(?,?,?)',('future','future',json.dumps(d)))
        self.assertEqual(payroll.attendance(self.c,'2099-01')['rows'][0]['pay_days'],'0')

    def test_defaults_precision_privacy_and_employee_permission(self):
        initial=payroll.report(self.c,'2020-09');self.assertEqual(initial['profiles'][0]['monthly_cents'],300000)
        self.assertEqual(initial['rows'][0]['base_cents'],14795)
        with self.assertRaises(ValueError):self.save('employee',{'id':self.employee['id'],'version':self.employee['version'],'name':'测试员工','group_id':'G-TOFU','monthly_salary':'9000'},'厂长')
        self.sheet();r=payroll.report(self.c,'2020-09');r['rows'].append({**r['rows'][0],'employee_id':'PRIVATE-OTHER','employee_name':'其他员工不可见','net_cents':999999})
        slip=payroll.slip_html(r,self.employee['id']);self.assertNotIn('其他员工不可见',slip);self.assertNotIn('9999.99',slip);self.assertIn('测试员工',slip)
        summary=payroll.print_html(r,{},True);self.assertNotIn('<th>签字</th>',summary)
        with self.assertRaises(ValueError):payroll.slip_html(r,'missing')
        self.assertNotIn('monthly_salary',fm.get(self.c,'employee',self.employee['id']));self.assertNotIn('monthly_cents',fm.get(self.c,'employee',self.employee['id']))

    def test_month_window_reads_plan_column_and_skips_undated_payloads(self):
        # warehouse_plans 的日期在主键列；payload 里没有 business_date 也不影响按月读取。
        self.c.execute("INSERT INTO warehouse_plans VALUES(?,?)",('2020-09-05','{"stock":[]}'))
        # 其他三张表按 payload 里的 business_date 取月；缺这个键的记录旧实现就静默跳过，不能被误报为错误。
        self.c.execute("INSERT INTO factory_daily VALUES(?,?,?)",('D-undated','K-undated',json.dumps({'x':1})))
        r=payroll.attendance(self.c,'2020-09')
        self.assertEqual(r['work_dates'],['2020-09-01','2020-09-02','2020-09-05'])
        self.assertEqual({c['date']:c['status'] for c in r['rows'][0]['cells']}['2020-09-05'],'missing')

    def test_future_table_days_do_not_leak_into_work_dates(self):
        self.c.execute("INSERT INTO factory_daily VALUES(?,?,?)",('D-future','K-future',json.dumps({'business_date':'2099-01-05'})))
        r=payroll.attendance(self.c,'2099-01')
        self.assertEqual(r['work_dates'],[])
        self.assertTrue(all(c['status']=='' for c in r['rows'][0]['cells']))

    def test_payment_void_restores_outstanding_and_report(self):
        s = self.sheet()
        b = {'request_key': str(uuid.uuid4()), 'month': '2020-09', 'employee_id': self.employee['id'],
             'version': s['version'], 'paid_cents': 0, 'amount': '50', 'business_date': '2020-10-01',
             'handler': '测试出纳', 'reference': 'TEST'}
        p = fm.save(self.c, 'wage-pay', b, '出纳', erp.now, erp.audit)
        self.assertEqual(payroll.report(self.c, '2020-09')['outstanding_cents'], 10595)
        with self.assertRaisesRegex(ValueError, '冲销原因'):
            fm.save(self.c, 'wage-payment-void', {'payment_id': p['id'], 'version': p['version'], 'reason': ''}, '出纳', erp.now, erp.audit)
        v = fm.save(self.c, 'wage-payment-void', {'payment_id': p['id'], 'version': p['version'], 'reason': '银行退回'}, '出纳', erp.now, erp.audit)
        self.assertTrue(v['voided'])
        r = payroll.report(self.c, '2020-09')
        self.assertEqual(r['outstanding_cents'], 15595)
        self.assertEqual(r['paid_cents'], 0)
        with self.assertRaisesRegex(ValueError, '已冲销'):
            fm.save(self.c, 'wage-payment-void', {'payment_id': p['id'], 'version': v['version'], 'reason': '再次'}, '出纳', erp.now, erp.audit)
