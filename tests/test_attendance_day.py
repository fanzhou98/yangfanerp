import json
import unittest
import attendance_query as query
import production_management as factory
import erp_access as access
import test_attendance_separation as fixture

erp=fixture.erp


class AttendanceDayTests(unittest.TestCase):
    setUp=fixture.AttendanceSeparationTests.setUp
    tearDown=fixture.AttendanceSeparationTests.tearDown
    save=fixture.AttendanceSeparationTests.save
    manager=fixture.AttendanceSeparationTests.manager
    day=fixture.AttendanceSeparationTests.day

    def test_month_delete_count_covers_saved_records_without_writing(self):
        manager=self.manager();self.day('production',self.employee['id'],'full');self.day('management',manager['id'],'half','draft')
        before=[tuple(r) for r in self.c.execute('SELECT * FROM factory_attendance ORDER BY id')]
        result=query.month_record_count(self.c,'2020-09',self.employee['id'],{'production'})
        self.assertEqual(result['record_count'],3)
        self.assertEqual(query.month_record_count(self.c,'2020-09',manager['id'],{'management'})['record_count'],1)
        self.assertEqual(query.month_record_count(self.c,'2020-09',manager['id'],{'production'})['record_count'],0)
        self.assertEqual(query.month_record_count(self.c,'2020-10',self.employee['id'],{'production'})['record_count'],0)
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM factory_attendance ORDER BY id')])
        with self.assertRaises(ValueError):query.month_record_count(self.c,'2020-13',self.employee['id'],{'production'})

    def test_one_day_scope_states_notes_and_readonly(self):
        manager=self.manager()
        self.day('production',self.employee['id'],'full')
        self.day('management',manager['id'],'leave','draft',note='管理私有说明')
        before=[tuple(r) for r in self.c.execute('SELECT * FROM factory_attendance ORDER BY id')]
        prod=query.day_records(self.c,'2020-09-03','production',access.defaults('管理员'))
        management=query.day_records(self.c,'2020-09-03','management',access.defaults('管理员'))
        self.assertEqual(prod['attendance']['state'],'confirmed')
        self.assertEqual(management['attendance']['state'],'draft')
        self.assertNotIn('管理私有说明',json.dumps(prod,ensure_ascii=False))
        self.assertNotIn('管理甲',json.dumps(prod,ensure_ascii=False))
        self.assertEqual(len(prod['attendance']['entries']),1)
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM factory_attendance ORDER BY id')])
        missing=query.day_records(self.c,'2020-09-30','production',access.defaults('厂长'))
        self.assertIsNone(missing['attendance']);self.assertIsNone(missing['schedule'])

    def test_complete_date_facts_preserve_pending_basis_without_people(self):
        manager=self.manager();self.day('production',self.employee['id'],'full');self.day('management',manager['id'],'half','draft')
        scoped=factory.scope(factory.snapshot(self.c),access.defaults('厂长'))
        facts=scoped['attendance_activity']
        day=next(d for d in facts if d['business_date']=='2020-09-03')
        self.assertTrue(day['production_confirmed'])
        self.assertFalse(day['scheduled'])  # Independent attendance does not confirm optional scheduling.
        self.assertNotIn('测试员工',json.dumps(facts,ensure_ascii=False))
        self.assertNotIn('管理甲',json.dumps(facts,ensure_ascii=False))
        self.assertEqual(len(facts),3)
        manager_facts=factory.scope(factory.snapshot(self.c),access.defaults('行政负责人'))['attendance_activity']
        self.assertEqual([r['business_date'] for r in manager_facts],['2020-09-03'])
        self.assertFalse(manager_facts[0]['production_confirmed'])

    def test_duplicate_own_day_is_not_silently_treated_as_new_record(self):
        self.day('production',self.employee['id'],'full')
        payload=json.loads(self.c.execute("SELECT payload FROM factory_attendance WHERE json_extract(payload,'$.business_date')='2020-09-03'").fetchone()[0])
        payload['id']='DUPLICATE'
        self.c.execute('INSERT INTO factory_attendance VALUES(?,?,?)',('DUPLICATE','DUPLICATE',json.dumps(payload)))
        with self.assertRaisesRegex(ValueError,'冲突'):query.day_records(self.c,'2020-09-03','production',access.defaults('厂长'))
        with self.assertRaises(ValueError):query.day_records(self.c,'invalid','production',access.defaults('厂长'))
