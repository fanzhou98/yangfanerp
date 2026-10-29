import json
import unittest
import payroll,personnel,production_management as factory,erp_access as access,resources_costs as rc
import test_attendance_separation as fixture

erp=fixture.erp


class AttendanceDateFactsTests(unittest.TestCase):
    """Bootstrap 的日期状态按 SQL 聚合，按月读取改走日期表达式索引。"""
    setUp=fixture.AttendanceSeparationTests.setUp
    tearDown=fixture.AttendanceSeparationTests.tearDown
    save=fixture.AttendanceSeparationTests.save
    manager=fixture.AttendanceSeparationTests.manager

    def insert(self,table,payload):
        """边界样本绕过录入校验直接落库，只考察投影口径。"""
        self.c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(payload['id'],payload['id'],json.dumps(payload)))
        return payload
    def attendance(self,day,entries,**extra):
        return self.insert('factory_attendance',{'id':'A-'+day+'-'+str(len(entries)),'business_date':day,'format':'group-day-v2','state':'confirmed','version':0,'entries':entries,**extra})
    def schedule(self,day,state,entries=()):
        return self.insert('factory_schedules',{'id':'S-'+day,'business_date':day,'format':'group-plan-v1','state':state,'version':0,'groups':[],'entries':list(entries)})
    def entry(self,employee,status='full'):
        return {'employee_id':employee,'group_id':'G-TOFU','status':status}
    def light(self,role):
        return factory.scope(factory.snapshot(self.c,light=True),access.defaults(role),self.c)
    def full(self,role):
        return factory.scope(factory.snapshot(self.c),access.defaults(role))
    def facts(self,role):
        scoped=self.light(role)
        self.assertEqual(rc.dump(scoped['attendance_activity']),rc.dump(self.full(role)['attendance_activity']),role)
        return {r['business_date']:r for r in scoped['attendance_activity']}

    def test_date_facts_match_the_full_projection_for_every_role(self):
        manager=self.manager()
        for i,day in enumerate(('2020-09-01','2020-09-02','2020-09-03')):
            self.attendance(day,[self.entry(self.employee['id'])])
        self.attendance('2020-09-04',[dict(self.entry(self.employee['id']),entry_state='draft')])
        self.attendance('2020-09-05',[{'employee_id':manager['id'],'status':'leave'}])
        for role in ('管理员','厂长','行政负责人'):self.facts(role)
        self.assertEqual(self.light('库管')['attendance_activity'],[])

    def test_workflow_schedule_links_and_empty_entries_follow_the_scoped_state(self):
        self.attendance('2020-09-03',[self.entry(self.employee['id'])],workflow='separate-v1')
        self.attendance('2020-09-04',[])
        self.attendance('2020-09-05',[self.entry(self.employee['id'])],source_schedule_id='S-1')
        self.schedule('2020-09-06','confirmed')
        self.schedule('2020-09-07','draft')
        facts=self.facts('厂长')
        self.assertFalse(facts['2020-09-03']['scheduled'])        # separate-v1 不参与可选排班
        self.assertTrue(facts['2020-09-03']['production_confirmed'])
        self.assertFalse(facts['2020-09-05']['scheduled'])        # 由排班生成的考勤不反向确认排班
        self.assertTrue(facts['2020-09-05']['production_confirmed'])
        self.assertTrue(facts['2020-09-06']['schedule_saved'])
        self.assertFalse(facts['2020-09-06']['production_confirmed'])
        self.assertTrue(facts['2020-09-07']['schedule_saved'])    # 草稿排班也算已保存
        self.assertFalse(facts['2020-09-07']['scheduled'])
        self.assertNotIn('2020-09-04',facts)                      # 无范围内条目的记录不产生日期

    def test_entry_state_falls_back_to_the_recomputed_record_state(self):
        self.attendance('2020-09-03',[self.entry(self.employee['id']),dict(self.entry(self.employee['id'],'half'),entry_state='draft')])
        facts=self.facts('厂长')
        self.assertFalse(facts['2020-09-03']['scheduled'])        # 重算后整单是 draft
        self.assertFalse(facts['2020-09-03']['production_confirmed'])

    def test_explicit_null_entry_state_is_not_confirmed(self):
        self.attendance('2020-09-03',[self.entry(self.employee['id']),dict(self.entry(self.employee['id'],'half'),entry_state=None)])
        facts=self.facts('厂长')
        self.assertFalse(facts['2020-09-03']['scheduled'])
        self.assertFalse(facts['2020-09-03']['production_confirmed'])

    def test_management_scope_sees_management_only_days(self):
        manager=self.manager()
        self.attendance('2020-09-03',[self.entry(self.employee['id'])])
        self.attendance('2020-09-04',[{'employee_id':manager['id'],'status':'full'}])
        self.assertIn('2020-09-03',self.facts('厂长'))            # 生产员工的日期对厂长可见
        self.assertNotIn('2020-09-04',self.facts('厂长'))          # 纯管理记录不计入生产日期状态
        self.assertEqual(sorted(self.facts('行政负责人')),['2020-09-04'])
        self.assertEqual(self.light('库管')['attendance_activity'],[])

    def assert_employee_id_error(self,role):
        """light 与 full 必须同样报错，错误信息保持 v0.95.3 的 KeyError('employee_id')。"""
        with self.assertRaisesRegex(KeyError,'employee_id',msg='full '+role):self.full(role)
        with self.assertRaisesRegex(KeyError,'employee_id',msg='light '+role):self.light(role)

    def test_entries_without_employee_id_key_raise_like_before(self):
        self.attendance('2020-09-03',[{'status':'full'}])                  # 缺键：v0.95.3 按下标取即 KeyError
        for role in ('厂长','库管','行政负责人'):self.assert_employee_id_error(role)
        self.c.execute('DELETE FROM factory_attendance')
        self.schedule('2020-09-04','confirmed',[{'status':'leave'}])       # 排班条目同样先定类型
        self.assert_employee_id_error('厂长')
        self.assertEqual(self.light('行政负责人')['attendance_activity'],[])  # 无排班权限不查看排班条目
        self.assertEqual(self.light('库管')['attendance_activity'],[])

    def test_explicit_null_employee_id_still_falls_back_to_the_entry_type(self):
        self.attendance('2020-09-03',[{'employee_id':None,'group_id':'G-TOFU','status':'full'}])
        facts=self.facts('厂长')                                           # 只判缺键，null 走条目类型回退
        self.assertTrue(facts['2020-09-03']['scheduled'])
        self.assertTrue(facts['2020-09-03']['production_confirmed'])
        self.c.execute('DELETE FROM factory_attendance')
        self.schedule('2020-09-04','confirmed',[{'employee_id':None,'status':'leave'}])
        self.assertTrue(self.facts('厂长')['2020-09-04']['schedule_saved'])

    def test_missing_employee_id_raises_before_scope_and_date_filters(self):
        manager=self.manager()
        self.attendance('',[{'status':'full'}])                            # 无业务日期的记录也会先定类型
        self.assert_employee_id_error('厂长')
        self.c.execute('DELETE FROM factory_attendance')
        self.attendance('2020-09-03',[{'employee_id':manager['id'],'employee_type':'management','status':'full'},{'status':'half'}])
        self.assert_employee_id_error('厂长')                              # 不可见类型与可见条目混排也报错

    def test_deferred_snapshot_requires_a_connection(self):
        snapshot=factory.snapshot(self.c,light=True)
        self.assertNotIn('attendance_activity',json.dumps(snapshot))
        self.assertEqual(snapshot['attendance'],[]);self.assertEqual(snapshot['schedules'],[])
        with self.assertRaises(ValueError):factory.scope(snapshot,access.defaults('厂长'))
        self.assertNotIn('_attendance_deferred',self.light('厂长'))

    def trace(self,fn):
        seen=[]
        self.c.set_trace_callback(seen.append)
        try:result=fn()
        finally:self.c.set_trace_callback(None)
        return result,seen
    def plan(self,sql):
        return ' '.join(str(r[3]) for r in self.c.execute('EXPLAIN QUERY PLAN '+sql))

    def test_monthly_reads_hit_the_business_date_indexes(self):
        self.attendance('2020-09-03',[self.entry(self.employee['id'])])
        self.attendance('2020-08-03',[self.entry(self.employee['id'])])
        self.schedule('2020-09-03','confirmed');self.schedule('2020-08-03','confirmed')
        _,seen=self.trace(lambda:payroll.attendance(self.c,'2020-09'))
        attendance=[s for s in seen if s.startswith('SELECT payload FROM factory_attendance')]
        self.assertTrue(attendance)
        self.assertIn("json_extract(payload,'$.business_date')>='2020-09-01'",attendance[0])
        self.assertIn("json_extract(payload,'$.business_date')<'2020-10-01'",attendance[0])
        self.assertIn('SEARCH factory_attendance USING INDEX factory_attendance_history_date',self.plan(attendance[0]))
        _,seen=self.trace(lambda:personnel.attendance_report(self.c,'2020-09',{'production'}))
        schedules=[s for s in seen if s.startswith('SELECT payload FROM factory_schedules')]
        self.assertTrue(schedules)
        self.assertIn('SEARCH factory_schedules USING INDEX factory_schedules_business_date',self.plan(schedules[0]))

    def test_monthly_reads_return_only_the_requested_month(self):
        self.attendance('2020-09-03',[self.entry(self.employee['id'])])
        self.attendance('2020-08-03',[self.entry(self.employee['id'])])
        self.assertEqual(payroll.month_bounds('2020-09'),('2020-09-01','2020-10-01'))
        rows=payroll.payload_range(self.c,'factory_attendance',*payroll.month_bounds('2020-09'))
        self.assertEqual([r['business_date'] for r in rows],['2020-09-01','2020-09-02','2020-09-03'])
        self.assertNotIn('2020-08-03',[r['business_date'] for r in rows])
        self.assertEqual(payroll.payload_range(self.c,'factory_attendance','2020-09-04','2020-09-05'),[])  # 半月区间为空串接

    def test_record_without_business_date_still_fails_loudly(self):
        self.insert('factory_attendance',{'id':'NO-DATE','format':'group-day-v2','state':'confirmed','version':0,'entries':[]})
        with self.assertRaises(KeyError):payroll.attendance(self.c,'2020-09')

    def test_month_bounds_keeps_the_month_validation(self):
        with self.assertRaises(ValueError):payroll.month_bounds('2020-13')
        self.assertEqual(payroll.month_bounds('2020-02'),('2020-02-01','2020-03-01'))
        self.assertEqual(payroll.month_bounds('2020-12'),('2020-12-01','2021-01-01'))
