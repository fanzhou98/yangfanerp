"""Attendance history: complete pages, mixed scopes and saved evidence only."""
import json
import unittest
from datetime import date, timedelta
import attendance_query as query
import test_payroll as fixture

erp = fixture.erp


class AttendanceHistoryTests(unittest.TestCase):
    setUp = fixture.PayrollTests.setUp
    tearDown = fixture.PayrollTests.tearDown

    def add(self, record_id, day, entries, state='confirmed'):
        payload = {'id': record_id, 'business_date': day, 'state': state, 'version': 2,
                   'entries': entries, 'salary_cents': 999999, 'note': '整单私有说明'}
        self.c.execute('INSERT INTO factory_attendance VALUES(?,?,?)', (record_id, record_id, json.dumps(payload)))

    def entry(self, **extra):
        return {'employee_id': self.employee['id'], 'employee_name': '生产甲',
                'employee_type': 'production', 'status': 'full', 'group_name': '豆腐组', **extra}

    def test_complete_pages_filters_summary_and_index(self):
        self.c.execute('DELETE FROM factory_attendance')
        for i in range(126):
            self.add('H-%03d' % i, (date(2020, 1, 1)+timedelta(days=i)).isoformat(),
                     [self.entry(status='half' if i==0 else 'full', note='首条' if i==0 else '')])
        result = query.history(self.c, {'production'}, all_dates=True, page_size=50)
        self.assertEqual((result['total'], result['pages'], result['summary']['attendance_days']), (126, 3, '125.5'))
        ids = []
        for page in (1, 2, 3):
            rows = query.history(self.c, {'production'}, all_dates=True, page=page)['rows']
            ids += [r['record_id'] for r in rows]
        self.assertEqual(len(set(ids)), 126)
        self.assertEqual((ids[0], ids[-1]), ('H-125', 'H-000'))
        first = query.history(self.c, {'production'}, start='2020-01-01', end='2020-01-01')
        self.assertEqual(first['summary']['attendance_days'], '0.5')
        self.assertEqual(query.history(self.c, {'production'}, all_dates=True, search='首条')['total'], 1)
        self.assertEqual(query.history(self.c, {'production'}, all_dates=True, status='half')['total'], 1)
        plan = str([tuple(r) for r in self.c.execute("EXPLAIN QUERY PLAN SELECT a.id FROM factory_attendance a WHERE json_extract(a.payload,'$.business_date')>=? AND json_extract(a.payload,'$.business_date')<=?", ('2020-01-01','2020-01-31'))])
        self.assertIn('factory_attendance_history_date', plan)

    def test_scope_entry_state_conflicts_and_unrecorded_do_not_inflate_attendance(self):
        self.c.execute('DELETE FROM factory_attendance')
        management = {'employee_id': 'M1', 'employee_name': '管理秘密', 'employee_type': 'management', 'status': 'full', 'entry_state': 'draft', 'note': '管理私有备注'}
        self.add('MIX', '2020-09-01', [self.entry(status='half', entry_state='confirmed'), management], 'draft')
        self.add('MISSING', '2020-09-02', [self.entry(status='unrecorded')])
        self.add('DRAFT', '2020-09-03', [self.entry()], 'draft')
        self.add('DUP1', '2020-09-04', [self.entry(status='full')])
        self.add('DUP2', '2020-09-04', [self.entry(status='half')])
        self.add('FUTURE', '2999-01-01', [self.entry()])
        before = [tuple(r) for r in self.c.execute('SELECT * FROM factory_attendance ORDER BY id')]
        result = query.history(self.c, {'production'}, all_dates=True)
        self.assertEqual(result['summary']['attendance_days'], '0.5')
        self.assertEqual((result['summary']['draft'], result['summary']['conflict'], result['summary']['unrecorded'], result['summary']['future']), (1,2,1,1))
        self.assertNotIn('管理秘密', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('salary_cents', json.dumps(result))
        self.assertNotIn('整单私有说明', json.dumps(result, ensure_ascii=False))
        self.assertEqual(query.history(self.c, {'production'}, all_dates=True, status='full')['total'], 0)
        self.assertEqual(query.history(self.c, {'management'}, all_dates=True)['summary']['draft'], 1)
        self.assertEqual(before, [tuple(r) for r in self.c.execute('SELECT * FROM factory_attendance ORDER BY id')])

    def test_legacy_present_empty_results_and_invalid_inputs(self):
        self.add('OLD', '2020-10-01', [self.entry(status='present')])
        self.assertEqual(query.history(self.c, {'production'}, start='2020-10-01', end='2020-10-01')['summary']['attendance_days'], '1')
        empty = query.history(self.c, {'production'}, all_dates=True, search='不存在', page=999)
        self.assertEqual((empty['rows'], empty['total'], empty['page'], empty['summary']['attendance_days']), ([],0,1,'0'))
        for kwargs in ({'start':'bad'}, {'start':'2020-02-01','end':'2020-01-01'}, {'page':0}, {'page_size':201}, {'status':'paid'}, {'all_dates':True,'start':'2020-01-01'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                query.history(self.c, {'production'}, **kwargs)
