import unittest,uuid,json
import test_payroll as fixture
import personnel,payroll,production_management as fm,erp_access as access

erp=fixture.erp
class AttendanceSeparationTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    def manager(self):return self.save('employee',{'name':'管理甲','employee_type':'management','group_id':''},'行政负责人')
    def day(self,scope,eid,status,state='confirmed',**extra):
        rows=[r for r in fm.rows(self.c,'attendance') if r['business_date']=='2020-09-03'];old=rows[0] if rows else {}
        return personnel.save_day(self.c,{'request_key':str(uuid.uuid4()),'business_date':'2020-09-03','id':old.get('id'),'version':old.get('version',0),'state':state,'entries':[{'employee_id':eid,'group_id':'G-TOFU' if scope=='production' else '', 'status':status}],**extra},scope,'厂长' if scope=='production' else '行政负责人',erp.now,erp.audit)
    def test_draft_and_confirmation_are_independent_and_payroll_combines(self):
        m=self.manager();self.day('production',self.employee['id'],'full');self.day('management',m['id'],'leave','draft')
        report=payroll.attendance(self.c,'2020-09');rows={r['employee_id']:r for r in report['rows']};self.assertEqual(rows[self.employee['id']]['cells'][2]['status'],'full');self.assertEqual(rows[m['id']]['cells'][2]['status'],'draft')
        self.day('management',m['id'],'half');report=payroll.attendance(self.c,'2020-09');self.assertEqual({r['employee_id']:r['cells'][2]['status'] for r in report['rows']},{self.employee['id']:'full',m['id']:'half'})
    def test_cross_type_staff_and_attendance_are_rejected(self):
        m=self.manager()
        with self.assertRaisesRegex(ValueError,'权限'):self.save('employee',{'name':'管理乙','employee_type':'management','group_id':''},'厂长')
        with self.assertRaisesRegex(ValueError,'权限'):self.save('employee',{'id':m['id'],'version':m['version'],'name':'改名','employee_type':'production','group_id':'G-TOFU'},'厂长')
        with self.assertRaisesRegex(ValueError,'跨人员类型'):self.day('production',m['id'],'full')
        with self.assertRaisesRegex(ValueError,'权限'):self.save('attendance',{'business_date':'2020-09-03','format':'person-day-v1','state':'confirmed','entries':[{'employee_id':m['id'],'status':'full'}]},'厂长')
    def test_bootstrap_and_monthly_report_hide_other_personnel(self):
        m=self.manager();self.day('production',self.employee['id'],'full');self.day('management',m['id'],'leave',note='管理私有说明')
        prod=fm.scope(fm.snapshot(self.c),access.defaults('厂长'));admin=fm.scope(fm.snapshot(self.c),access.defaults('行政负责人'))
        self.assertNotIn('管理甲',json.dumps(prod,ensure_ascii=False));self.assertNotIn('管理私有说明',json.dumps(prod,ensure_ascii=False));self.assertNotIn('测试员工',json.dumps(admin,ensure_ascii=False))
        self.assertEqual([r['employee_id'] for r in personnel.attendance_report(self.c,'2020-09',{'management'})['rows']],[m['id']])
    def test_management_month_preserves_production_and_does_not_require_schedule(self):
        m=self.manager();self.day('production',self.employee['id'],'full');r=personnel.attendance_report(self.c,'2020-09',{'management'})
        b={'request_key':str(uuid.uuid4()),'employee_id':m['id'],'month':'2020-09','attendance_scope':'management','attendance_token':r['attendance_token'],'cells':[{'date':'2020-09-03','status':'leave'}]};personnel.save_month(self.c,b,'行政负责人',erp.now,erp.audit)
        self.assertEqual({r['employee_id']:r['cells'][2]['status'] for r in payroll.attendance(self.c,'2020-09')['rows']},{self.employee['id']:'full',m['id']:'leave'})
    def test_management_only_day_does_not_create_production_missing_attendance(self):
        m=self.manager();self.day('management',m['id'],'full')
        rows={r['employee_id']:r for r in payroll.attendance(self.c,'2020-09')['rows']}
        self.assertEqual(rows[self.employee['id']]['cells'][2]['status'],'');self.assertEqual(rows[m['id']]['cells'][2]['status'],'full')
    def test_legacy_mixed_record_does_not_leak_management_names_or_notes(self):
        m=self.manager();self.save('attendance',{'business_date':'2020-09-03','format':'person-day-v1','state':'confirmed','note':'管理旧私有说明','entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':'full'},{'employee_id':m['id'],'status':'leave'}]})
        record=next(r for r in fm.rows(self.c,'attendance') if r['business_date']=='2020-09-03');record['notice']='管理甲请假';self.c.execute('UPDATE factory_attendance SET payload=? WHERE id=?',(json.dumps(record),record['id']))
        projected=json.dumps(fm.scope(fm.snapshot(self.c),access.defaults('厂长')),ensure_ascii=False)
        self.assertNotIn('管理甲',projected);self.assertNotIn('管理旧私有说明',projected)
    def test_monthly_plan_prefill_is_from_latest_report_and_stale_plan_is_rejected(self):
        plan=self.save('schedule',{'business_date':'2020-09-03','format':'group-plan-v1','state':'confirmed','groups':[],'entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':'leave'}]})
        report=personnel.attendance_report(self.c,'2020-09',{'production'});self.assertEqual(report['planned_leave'],[{'employee_id':self.employee['id'],'date':'2020-09-03'}])
        self.save('schedule',{'id':plan['id'],'version':plan['version'],'business_date':'2020-09-03','format':'group-plan-v1','state':'draft','groups':[],'entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':'rest'}]})
        with self.assertRaisesRegex(ValueError,'排班已变化'):personnel.save_month(self.c,{'request_key':str(uuid.uuid4()),'employee_id':self.employee['id'],'month':'2020-09','attendance_scope':'production','attendance_token':report['attendance_token'],'cells':[{'date':'2020-09-03','status':'leave'}]},'厂长',erp.now,erp.audit)
    def test_stale_schedule_and_idempotent_requests(self):
        schedule=self.save('schedule',{'business_date':'2020-09-03','format':'group-plan-v1','state':'confirmed','groups':[],'entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':'leave'}]})
        with self.assertRaisesRegex(ValueError,'排班已变化'):self.day('production',self.employee['id'],'leave',source_schedule_id=schedule['id'],source_schedule_version=0)
        b={'request_key':str(uuid.uuid4()),'business_date':'2020-09-03','state':'confirmed','source_schedule_id':schedule['id'],'source_schedule_version':schedule['version'],'entries':[{'employee_id':self.employee['id'],'group_id':'G-TOFU','status':'leave'}]}
        r=personnel.save_day(self.c,b,'production','厂长',erp.now,erp.audit);self.assertEqual(personnel.save_day(self.c,b,'production','厂长',erp.now,erp.audit),r);self.assertEqual(r['entries'][0]['status'],'leave')
