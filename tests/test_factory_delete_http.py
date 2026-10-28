import json,uuid
import unittest
import test_auth_http as fixture
import production_management as fm
import resources_costs as rc

erp=fixture.erp
class FactoryDeleteHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def employee(self,c,name,etype='production'):
        return fm.save(c,'employee',{'request_key':str(uuid.uuid4()),'name':name,'employee_type':etype,'group_id':'G-TOFU' if etype=='production' else ''},'管理员',erp.now,erp.audit)
    def schedule(self,c,employee,day):
        return fm.save(c,'schedule',{'request_key':str(uuid.uuid4()),'business_date':day,'format':'group-plan-v1','state':'confirmed','groups':[{'group_id':'G-TOFU','group_name':'豆腐组','start_time':'08:00','end_time':'17:00'}],'entries':[{'employee_id':employee['id'],'group_id':'G-TOFU','status':'leave','note':'测试排班'}]},'管理员',erp.now,erp.audit)
    def attendance(self,c,employee,day,scope='production',state='confirmed'):
        kind='management-attendance' if scope=='management' else 'production-attendance'
        return fm.save(c,kind,{'request_key':str(uuid.uuid4()),'business_date':day,'format':'person-day-v1','workflow':'separate-v1','state':state,'groups':[],'entries':[{'employee_id':employee['id'],'group_id':employee.get('group_id',''),'status':'full','note':'测试考勤'}]},'管理员',erp.now,erp.audit)
    def bootstrap(self):
        code,data,_=self.admin.request('/api/bootstrap');self.assertEqual(code,200);return data
    def delete(self,client,body):
        return client.request('/api/factory/delete',{'reason':'录入错误，删除重登','request_key':str(uuid.uuid4()),**body})

    def test_schedule_delete_admin_only_version_idempotent(self):
        with erp.connect(True) as c:
            employee=self.employee(c,'排班员工')
            plan=self.schedule(c,employee,'2026-03-12')
        director,_=self.user('delete_director','厂长')
        self.assertEqual(self.delete(director,{'kind':'schedule','id':plan['id'],'version':plan['version']})[0],403)
        self.assertEqual(self.delete(self.admin,{'kind':'schedule','id':plan['id'],'version':plan['version']+9})[0],400)
        self.assertEqual(self.delete(self.admin,{'kind':'schedule','id':plan['id'],'version':plan['version'],'reason':''})[0],400)
        body={'kind':'schedule','id':plan['id'],'version':plan['version'],'reason':'重复登记，删除','request_key':str(uuid.uuid4())}
        code,result,_=self.admin.request('/api/factory/delete',body);self.assertEqual(code,200,result);self.assertTrue(result['ok'])
        self.assertNotIn(plan['id'],{r['id'] for r in self.bootstrap()['factory']['schedules']})
        again=self.admin.request('/api/factory/delete',body);self.assertEqual(again[0],200);self.assertEqual(again[1]['id'],result['id'])
        self.assertEqual(self.delete(self.admin,{'kind':'schedule','id':plan['id'],'version':plan['version']})[0],400)

    def test_attendance_scope_merge_and_payroll_guard(self):
        with erp.connect(True) as c:
            worker=self.employee(c,'生产甲');manager=self.employee(c,'管理乙','management')
            self.attendance(c,manager,'2026-03-10','management')
            self.attendance(c,worker,'2026-03-10','production')
            self.attendance(c,worker,'2026-04-07','production')
            c.execute('INSERT INTO payroll_records VALUES(?,?,?)',('WAGE-BLOCK','delete-test:'+str(uuid.uuid4()),rc.dump({'id':'WAGE-BLOCK','kind':'sheet','month':'2026-04','state':'confirmed','attendance_token':'x','rows':[]})))
        record=next(r for r in self.bootstrap()['factory']['attendance'] if r['business_date']=='2026-03-10')
        self.assertEqual(len(record['entries']),2)
        code,result,_=self.delete(self.admin,{'kind':'attendance','id':record['id'],'version':record['version']});self.assertEqual(code,400)
        self.assertIn('删除范围',result['error'])
        code,result,_=self.delete(self.admin,{'kind':'attendance','id':record['id'],'version':record['version'],'scope':'production'});self.assertEqual(code,200,result);self.assertEqual(result['remaining'],1)
        record=next(r for r in self.bootstrap()['factory']['attendance'] if r['id']==record['id'])
        self.assertEqual([e['employee_id'] for e in record['entries']],[manager['id']])
        code,result,_=self.delete(self.admin,{'kind':'attendance','id':record['id'],'version':record['version'],'scope':'management'});self.assertEqual(code,200,result)
        self.assertFalse([r for r in self.bootstrap()['factory']['attendance'] if r['id']==record['id']])
        record=next(r for r in self.bootstrap()['factory']['attendance'] if r['business_date']=='2026-04-07')
        code,result,_=self.delete(self.admin,{'kind':'attendance','id':record['id'],'version':record['version'],'scope':'production'});self.assertEqual(code,400)
        self.assertIn('已确认',result['error'])

    def test_month_delete_removes_only_employee_cells(self):
        with erp.connect(True) as c:
            worker=self.employee(c,'月度甲');other=self.employee(c,'月度乙','management')
            for day in ('2026-05-05','2026-05-06'):
                self.attendance(c,other,day,'management');self.attendance(c,worker,day,'production')
        code,result,_=self.delete(self.admin,{'kind':'attendance-month','employee_id':worker['id'],'month':'2026-05'});self.assertEqual(code,200,result);self.assertEqual(result['days'],2)
        rows=[r for r in self.bootstrap()['factory']['attendance'] if r['business_date'].startswith('2026-05')]
        self.assertEqual(len(rows),2)
        for record in rows:self.assertEqual([e['employee_id'] for e in record['entries']],[other['id']])
        self.assertEqual(self.delete(self.admin,{'kind':'attendance-month','employee_id':worker['id'],'month':'2026-13'})[0],400)
        self.assertEqual(self.delete(self.admin,{'kind':'attendance-month','employee_id':'FE-NONE','month':'2026-05'})[0],400)

    def test_deleting_schedule_clears_attendance_source(self):
        with erp.connect(True) as c:
            employee=self.employee(c,'来源员工')
            plan=self.schedule(c,employee,'2026-06-10')
            fm.save(c,'production-attendance',{'request_key':str(uuid.uuid4()),'business_date':'2026-06-10','format':'person-day-v1','workflow':'separate-v1','state':'confirmed','groups':[],'source_schedule_id':plan['id'],'source_schedule_version':plan['version'],'entries':[{'employee_id':employee['id'],'group_id':'G-TOFU','status':'full'}]},'管理员',erp.now,erp.audit)
        code,result,_=self.delete(self.admin,{'kind':'schedule','id':plan['id'],'version':plan['version']});self.assertEqual(code,200,result)
        record=next(r for r in self.bootstrap()['factory']['attendance'] if r['business_date']=='2026-06-10')
        self.assertNotIn('source_schedule_id',record);self.assertNotIn('source_schedule_version',record)
