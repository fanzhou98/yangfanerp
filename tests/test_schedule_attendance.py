import tempfile,unittest,uuid
from pathlib import Path
import test_workflow as fixture
import production_management as fm
import payroll

erp=fixture.erp
class ScheduleAttendanceTests(unittest.TestCase):
 def setUp(self):
  self.old=erp.DB;self.temp=tempfile.TemporaryDirectory();erp.DB=Path(self.temp.name)/'factory.db';erp.init_db()
  self.e=self.save('employee',{'name':'排班测试员工','group_id':'G-TOFU'})
 def tearDown(self):erp.DB=self.old;self.temp.cleanup()
 def save(self,kind,body,role='厂长'):
  with erp.connect(True) as c:return fm.save(c,kind,{'request_key':str(uuid.uuid4()),**body},role,erp.now,erp.audit)
 def body(self,day='2020-09-02',group='G-TOFU',start='21:00'):
  return {'format':'group-plan-v1','business_date':day,'state':'confirmed','groups':[{'group_id':group,'start_time':start,'end_time':'05:00'}],'entries':[{'employee_id':self.e['id'],'group_id':group,'status':'full'}]}
 def test_schedule_does_not_create_attendance_or_salary(self):
  plan=self.save('schedule',self.body())
  with erp.connect() as c:
   self.assertEqual(fm.rows(c,'attendance'),[]);row=payroll.attendance(c,'2020-09')['rows'][0]
   self.assertEqual(row['pay_days'],'0');self.assertEqual(row['cells'][1]['status'],'missing')
  body={**self.body(),'format':'group-day-v2','source_schedule_id':plan['id'],'source_schedule_version':plan['version']};body['entries'][0]['status']='half'
  actual=self.save('attendance',body)
  with erp.connect() as c:
   self.assertEqual(payroll.attendance(c,'2020-09')['rows'][0]['pay_days'],'0.5');self.assertEqual(fm.rows(c,'schedule')[0],plan)
  self.assertNotIn('notice',actual)
 def test_notice_compares_plans_and_actual_changes_stay_separate(self):
  yesterday=self.save('schedule',self.body('2020-09-01'))
  plan=self.save('schedule',self.body(group='G-SKIN',start='22:00'))
  self.assertIn('豆腐组→豆皮组',plan['notice']);self.assertIn('未排班→22:00',plan['notice']);self.assertNotIn('05:00',plan['notice'])
  body={**self.body(group='G-SKIN',start='22:00'),'format':'group-day-v2','source_schedule_id':plan['id'],'source_schedule_version':plan['version']};body['entries'][0].update(status='absent',note='实际缺勤')
  self.save('attendance',body)
  with erp.connect() as c:self.assertEqual(fm.rows(c,'schedule')[1],plan)
 def test_source_schedule_version_date_and_confirmation_are_checked(self):
  plan=self.save('schedule',self.body());b={**self.body(),'format':'group-day-v2','source_schedule_id':plan['id'],'source_schedule_version':plan['version']}
  changed=self.save('schedule',{**self.body(start='22:00'),'id':plan['id'],'version':plan['version']})
  with self.assertRaisesRegex(ValueError,'排班已修改'):self.save('attendance',b)
  with self.assertRaisesRegex(ValueError,'来源排班无效'):self.save('attendance',{**b,'business_date':'2020-09-03','source_schedule_version':changed['version']})
  with self.assertRaisesRegex(ValueError,'当天已有排班'):self.save('schedule',self.body())
  with self.assertRaisesRegex(ValueError,'权限'):self.save('schedule',self.body('2020-09-03'),role='司机')
 def test_schedule_and_attendance_can_be_saved_independently_for_same_day(self):
  plan=self.save('schedule',self.body());actual=self.save('attendance',{**self.body(),'format':'group-day-v2','state':'draft'})
  updated=self.save('schedule',{**self.body(start='23:00'),'id':plan['id'],'version':plan['version']})
  with erp.connect() as c:
   self.assertEqual(fm.rows(c,'attendance')[0],actual);self.assertEqual(fm.rows(c,'schedule')[0],updated)
