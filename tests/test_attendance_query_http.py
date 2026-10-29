"""Real HTTP scope gates and financial field exclusion on attendance history."""
import json
import unittest
import test_auth_http as fixture

erp = fixture.erp


class AttendanceHistoryHTTPTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    personal_password = fixture.AuthHTTPTests.personal_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown
    user = fixture.AuthHTTPTests.user

    def test_bootstrap_defers_details_but_retains_dates_and_admin_month_count(self):
        with erp.connect(True) as c:
            for day in ('2020-09-01','2020-09-02','2020-10-01'):
                rid='DAY-'+day
                row={'id':rid,'business_date':day,'state':'confirmed','entries':[{'employee_id':'P-DAY','employee_name':'日期生产甲','employee_type':'production','status':'full'}]}
                c.execute('INSERT INTO factory_attendance VALUES(?,?,?)',(rid,rid,json.dumps(row)))
        code,body,_=self.admin.request('/api/bootstrap')
        self.assertEqual(code,200,body)
        self.assertEqual(body['factory']['attendance'],[])
        self.assertEqual(body['factory']['schedules'],[])
        self.assertTrue(body['factory']['attendance_deferred'])
        self.assertEqual(len(body['factory']['attendance_activity']),3)
        self.assertNotIn('日期生产甲',json.dumps(body['factory']['attendance_activity'],ensure_ascii=False))
        url='/api/attendance-month-count?month=2020-09&employee_id=P-DAY'
        code,result,_=self.admin.request(url);self.assertEqual(code,200,result)
        self.assertEqual(result['record_count'],2)
        director,_=self.user('countdirector','厂长')
        self.assertEqual(director.request(url)[0],403)
        self.assertEqual(self.admin.request('/api/attendance-month-count?month=bad&employee_id=P-DAY')[0],400)
        code,detail,_=self.admin.request('/api/attendance-day?date=2020-09-01&scope=production')
        self.assertEqual(code,200,detail);self.assertEqual(detail['attendance']['entries'][0]['employee_name'],'日期生产甲')

    def test_day_scope_permission_and_invalid_parameters(self):
        director,_=self.user('daydirector','厂长')
        manager,_=self.user('daymanager','行政负责人')
        warehouse,_=self.user('daywarehouse','库管')
        url='/api/attendance-day?date=2020-09-03'
        code,body,_=director.request(url+'&scope=production')
        self.assertEqual(code,200,body)
        self.assertIsNone(body['attendance'])
        self.assertEqual(director.request(url+'&scope=management')[0],403)
        self.assertEqual(manager.request(url+'&scope=production')[0],403)
        self.assertEqual(manager.request(url+'&scope=management')[0],200)
        self.assertEqual(warehouse.request(url)[0],403)
        for suffix in ('&scope=bad','&date=2020-09-04','&extra=1'):
            self.assertEqual(self.admin.request(url+suffix)[0],400)
        self.assertEqual(self.admin.request('/api/attendance-day?date=bad')[0],400)

    def test_scope_is_enforced_before_rows_summary_and_search(self):
        with erp.connect(True) as c:
            payload={'id':'H-HTTP','business_date':'2020-09-01','state':'confirmed','entries':[
                {'employee_id':'P-HTTP','employee_name':'生产甲','employee_type':'production','status':'full','bank_card':'secret'},
                {'employee_id':'M-HTTP','employee_name':'管理秘密','employee_type':'management','status':'half','note':'管理私有'}]}
            c.execute('INSERT INTO factory_attendance VALUES(?,?,?)', ('H-HTTP','H-HTTP',json.dumps(payload)))
        director, _ = self.user('historydirector', '厂长')
        manager, _ = self.user('historymanager', '行政负责人')
        warehouse, _ = self.user('historywarehouse', '库管')
        url='/api/attendance-history?all=1'
        code, body, _ = director.request(url)
        self.assertEqual(code,200,body)
        self.assertEqual(body['total'],1)
        self.assertEqual(body['rows'][0]['employee_name'],'生产甲')
        self.assertNotIn('bank_card',json.dumps(body))
        self.assertEqual(director.request(url+'&scope=management')[0],403)
        self.assertEqual(director.request(url+'&employee_id=M-HTTP')[1]['total'],0)
        self.assertEqual(director.request(url+'&search=%E7%AE%A1%E7%90%86')[1]['total'],0)
        code, body, _ = manager.request(url)
        self.assertEqual(code,200,body)
        self.assertEqual(body['rows'][0]['employee_name'],'管理秘密')
        self.assertEqual(manager.request(url+'&scope=production')[0],403)
        self.assertEqual(warehouse.request(url)[0],403)
        self.assertEqual(self.admin.request(url)[1]['total'],2)
        for suffix in ('&page=0','&scope=invalid','&status=paid','&page=abc'):
            self.assertEqual(self.admin.request(url+suffix)[0],400)
