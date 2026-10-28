import unittest,uuid,json
import test_payroll as fixture
import personnel,payroll,production_management as fm,resources_costs as rc

erp=fixture.erp
class IndependentPersonnelTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    def management(self,**extra):
        role=extra.pop('role','管理员');return self.save('employee',{'name':'管理人员甲','employee_type':'management','department':'行政','position':'负责人','group_id':'',**extra},role)
    def month_body(self,**extra):
        report=payroll.attendance(self.c,'2020-09');return {'employee_id':self.employee['id'],'month':'2020-09','attendance_token':report['attendance_token'],'request_key':str(uuid.uuid4()),'cells':[{'date':d,'status':'full','note':''} for d in report['days']],**extra}
    def test_management_can_be_created_without_production_group_and_set_annual_salary(self):
        e=self.management(salary_mode='annual',annual_salary='36600',salary_version=0);self.assertEqual(e['group_id'],'');self.assertEqual(e['department'],'行政')
        p=next(p for p in payroll.records(self.c) if p['kind']=='profile' and p['employee_id']==e['id']);self.assertEqual((p['salary_mode'],p['annual_cents'],p['salary_category']),('annual',3660000,'wages-management'))
        with self.assertRaises(ValueError):self.save('employee',{'name':'工人','group_id':'','employee_type':'production'})
        with self.assertRaisesRegex(ValueError,'权限'):self.management(annual_salary='36500',salary_mode='annual',salary_version=0,request_key=str(uuid.uuid4()),role='厂长')
    def test_actual_attendance_without_schedule_or_group_time(self):
        e=self.management();r=self.save('management-attendance',{'business_date':'2020-09-03','format':'person-day-v1','state':'confirmed','entries':[{'employee_id':e['id'],'group_id':'','status':'full'}]},'行政负责人')
        self.assertEqual(r['format'],'person-day-v1');self.assertEqual(r['groups'],[]);self.assertNotIn('notice',r);self.assertEqual(fm.rows(self.c,'schedule'),[])
        row=next(x for x in payroll.attendance(self.c,'2020-09')['rows'] if x['employee_id']==e['id']);self.assertEqual(row['pay_days'],'1');self.assertEqual(row['employee_type'],'management')
        import owner_analysis
        self.assertEqual(owner_analysis.people(self.c,'2020-09-03')['schedule_state'],'missing')
    def test_unrecorded_is_not_confirmed_as_full_or_absent(self):
        e=self.management();r=self.save('attendance',{'business_date':'2020-09-03','format':'person-day-v1','state':'confirmed','entries':[{'employee_id':e['id'],'status':'full'},{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':'unrecorded'}]})
        self.assertEqual(len(r['entries']),1);worker=next(e for e in payroll.attendance(self.c,'2020-09')['rows'] if e['employee_id']==self.employee['id']);self.assertEqual(worker['cells'][2]['status'],'')
    def test_full_month_annual_leave_and_idempotent_retry(self):
        self.save('wage-profile',{'employee_id':self.employee['id'],'version':1,'salary_mode':'annual','annual_salary':'36600'})
        b=self.month_body();b['cells'][2].update(status='leave',note='请假');b['cells'][3].update(status='half',note='半天请假');r=personnel.save_month(self.c,b,'厂长',erp.now,erp.audit);self.assertEqual(r['saved_days'],30);self.assertEqual(personnel.save_month(self.c,b,'厂长',erp.now,erp.audit),r)
        report=payroll.report(self.c,'2020-09');row=report['rows'][0];self.assertEqual(row['unresolved'],0);self.assertEqual(row['base_cents'],285000);self.assertEqual(row['unpaid_days'],'1.5')
        self.assertEqual(fm.rows(self.c,'schedule'),[])
        sheet=self.save('wage-sheet',{'month':'2020-09','version':0,'state':'confirmed','attendance_token':report['attendance_token'],'salary_token':report['salary_token'],'rows':[{'employee_id':self.employee['id'],'bonus':'0','deduction':'0','reason':''}]})
        self.assertEqual(sheet['rows'][0]['net_cents'],285000)
        self.save('wage-pay',{'month':'2020-09','employee_id':self.employee['id'],'version':sheet['version'],'paid_cents':0,'amount':'2850','business_date':'2020-12-31','handler':'出纳','reference':'年底发放'})
        self.assertEqual(payroll.report(self.c,'2020-09')['outstanding_cents'],0)
        with self.assertRaisesRegex(ValueError,'提交编号'):personnel.save_month(self.c,{**b,'cells':b['cells'][:1]},'厂长',erp.now,erp.audit)
    def test_month_edit_preserves_other_employees_and_checks_stale_token(self):
        e=self.management();self.save('attendance',{'business_date':'2020-09-03','format':'person-day-v1','state':'confirmed','entries':[{'employee_id':e['id'],'status':'leave','note':'经理请假'}]})
        b=self.month_body(cells=[{'date':'2020-09-03','status':'full','note':'工人全天'}]);personnel.save_month(self.c,b,'厂长',erp.now,erp.audit)
        record=next(r for r in fm.rows(self.c,'attendance') if r['business_date']=='2020-09-03');self.assertEqual(len(record['entries']),2);self.assertEqual(next(x for x in record['entries'] if x['employee_id']==e['id'])['status'],'leave')
        with self.assertRaisesRegex(ValueError,'已变化'):personnel.save_month(self.c,{**b,'request_key':str(uuid.uuid4())},'厂长',erp.now,erp.audit)
    def test_month_validation_is_atomic_and_does_not_confirm_other_drafts(self):
        e=self.management();self.save('attendance',{'business_date':'2020-09-03','format':'person-day-v1','state':'draft','entries':[{'employee_id':e['id'],'status':'full'}]})
        before=rc.dump(fm.rows(self.c,'attendance'));b=self.month_body(cells=[{'date':'2020-09-02','status':'leave'},{'date':'2020-09-03','status':'full'}])
        personnel.save_month(self.c,b,'厂长',erp.now,erp.audit)
        record=next(r for r in fm.rows(self.c,'attendance') if r['business_date']=='2020-09-03')
        self.assertEqual(next(cell for cell in record['entries'] if cell['employee_id']==e['id'])['entry_state'],'draft')
    def test_contractors_do_not_enter_factory_staff_payroll_or_costs(self):
        before={t:rc.dump(rc.rows(self.c,t)) for t in ('factory_employees','factory_attendance','payroll_records','indirect_expenses','trade_records')}
        b={'request_key':str(uuid.uuid4()),'name':'外包司机甲','contractor':'承包运输队','position':'司机','active':True};e=personnel.save_contractor(self.c,'contractor-staff',b,'物流负责人',erp.now,erp.audit)
        self.assertEqual(personnel.save_contractor(self.c,'contractor-staff',b,'物流负责人',erp.now,erp.audit),e)
        personnel.save_contractor(self.c,'contractor-attendance',{'request_key':str(uuid.uuid4()),'employee_id':e['id'],'business_date':'2020-09-01','status':'full'},'物流负责人',erp.now,erp.audit)
        for table,old in before.items():self.assertEqual(rc.dump(rc.rows(self.c,table)),old,table)
        r=personnel.contractor_report(self.c,'2020-09','2020-09-01','物流负责人');self.assertEqual(len(r['staff']),1);self.assertEqual(len(r['attendance']),1)
        self.assertNotIn('外包司机甲',rc.dump(payroll.report(self.c,'2020-09')))
        with self.assertRaises(ValueError):personnel.contractor_report(self.c,'2020-09','2020-09-01','库管')
        with self.assertRaises(ValueError):personnel.save_contractor(self.c,'contractor-staff',{**b,'request_key':str(uuid.uuid4())},'库管',erp.now,erp.audit)
    def test_no_future_actual_attendance(self):
        b=self.month_body(month='2099-01',cells=[{'date':'2099-01-01','status':'full'}],attendance_token=payroll.attendance(self.c,'2099-01')['attendance_token'])
        with self.assertRaisesRegex(ValueError,'未来'):personnel.save_month(self.c,b,'厂长',erp.now,erp.audit)
