"""Audit rollback: restore one audited operation to its previous version."""
import json
import unittest

import audit_rollback
import auth
from test_auth_http import AuthHTTPFixture
from test_workflow import erp


def customer(rid, name='旧名'):
    return {'id': rid, 'name': name, 'route': 'A线', 'note': '', 'delivery_method': 'pickup',
            'region': '', 'market_id': '', 'location_kind': 'independent', 'legal_name': '', 'phone': ''}


def order(rid, customer_id='C900'):
    return {'id': rid, 'customer_id': customer_id, 'business_date': '2026-10-20', 'state': 'reviewed',
            'lines': [], 'total_cents': 1000, 'paid_cents': 0, 'return_credit_cents': 0,
            'discount_cents': 0, 'rounding_cents': 0, 'version': 1,
            'created_at': '2026-10-20T09:00:00', 'updated_at': '2026-10-20T09:00:00'}


class AuditRollbackTests(AuthHTTPFixture):
    def add_audit(self, action, entity, before, after):
        with erp.connect(True) as c:
            erp.audit(c, '管理员', action, entity, before, after)
            return c.execute('SELECT max(id) FROM audit').fetchone()[0]

    def insert_customer(self, row):
        with erp.connect(True) as c:
            c.execute('INSERT INTO customers(id,name,route,note,delivery_method,region,market_id,location_kind,legal_name,phone) '
                      'VALUES(:id,:name,:route,:note,:delivery_method,:region,:market_id,:location_kind,:legal_name,:phone)', row)

    def test_restore_column_record_to_previous_version(self):
        old = customer('C900')
        new = {**old, 'name': '新名'}
        self.insert_customer(new)
        audit_id = self.add_audit('修改客户名称', 'C900', old, new)
        with erp.connect() as c:
            plan = audit_rollback.plan(c, audit_id)
        self.assertEqual(plan['mode'], 'restore')
        self.assertEqual(plan['table'], 'customers')
        self.assertEqual(plan['target_id'], 'C900')
        self.assertIn('新名', plan['target_summary'])
        with erp.connect(True) as c:
            result = audit_rollback.execute(c, audit_id, '录错了', plan['fingerprint'], '管理员', erp.now(), erp.audit)
        self.assertTrue(result['ok'])
        with erp.connect() as c:
            self.assertEqual(c.execute('SELECT name FROM customers WHERE id=?', ('C900',)).fetchone()[0], '旧名')

    def test_delete_created_order_and_its_receipt(self):
        payload = order('SO-ROLLBACK')
        with erp.connect(True) as c:
            c.execute('INSERT INTO orders VALUES(?,?)', ('SO-ROLLBACK', json.dumps(payload, ensure_ascii=False)))
            c.execute('INSERT INTO receipts VALUES(?,?)', ('R-ROLLBACK', json.dumps(
                {'id': 'R-ROLLBACK', 'order_id': 'SO-ROLLBACK', 'amount_cents': 500, 'at': '2026-10-20T10:00:00'}, ensure_ascii=False)))
        audit_id = self.add_audit('登记订单', 'SO-ROLLBACK', None, payload)
        with erp.connect() as c:
            plan = audit_rollback.plan(c, audit_id)
        self.assertEqual(plan['mode'], 'delete')
        self.assertIn(('receipts', 'R-ROLLBACK'), {(d['table'], d['id']) for d in plan['dependents']})
        with erp.connect(True) as c:
            audit_rollback.execute(c, audit_id, '重复登记', plan['fingerprint'], '管理员', erp.now(), erp.audit)
        with erp.connect() as c:
            self.assertFalse(c.execute('SELECT 1 FROM orders WHERE id=?', ('SO-ROLLBACK',)).fetchone())
            self.assertFalse(c.execute('SELECT 1 FROM receipts WHERE id=?', ('R-ROLLBACK',)).fetchone())

    def test_date_plan_blocks_rollback_until_cleared(self):
        payload = order('SO-BLOCKED')
        with erp.connect(True) as c:
            c.execute('INSERT INTO orders VALUES(?,?)', ('SO-BLOCKED', json.dumps(payload, ensure_ascii=False)))
            c.execute('INSERT INTO dispatch_plans VALUES(?,?)', ('2026-10-21', json.dumps(
                {'business_date': '2026-10-21', 'orders': [{'id': 'SO-BLOCKED'}]}, ensure_ascii=False)))
        audit_id = self.add_audit('登记订单', 'SO-BLOCKED', None, payload)
        with erp.connect() as c:
            plan = audit_rollback.plan(c, audit_id)
        self.assertTrue(plan['blockers'])
        with erp.connect(True) as c:
            with self.assertRaises(ValueError):
                audit_rollback.execute(c, audit_id, '撤销', plan['fingerprint'], '管理员', erp.now(), erp.audit)
            self.assertTrue(c.execute('SELECT 1 FROM orders WHERE id=?', ('SO-BLOCKED',)).fetchone())

    def test_employee_delete_strips_attendance_entries(self):
        employee = {'id': 'FP-ROLLBACK', 'name': '测试员工', 'employee_type': 'production'}
        with erp.connect(True) as c:
            c.execute('INSERT INTO factory_employees(id,request_key,payload) VALUES(?,?,?)',
                      ('FP-ROLLBACK', 'req-rollback', json.dumps(employee, ensure_ascii=False)))
            c.execute('INSERT INTO factory_attendance(id,request_key,payload) VALUES(?,?,?)',
                      ('FA-ROLLBACK', 'req-att', json.dumps(
                          {'id': 'FA-ROLLBACK', 'business_date': '2026-10-21', 'entries': [{'employee_id': 'FP-ROLLBACK'}]},
                          ensure_ascii=False)))
        audit_id = self.add_audit('登记厂长员工', 'FP-ROLLBACK', None, employee)
        with erp.connect() as c:
            plan = audit_rollback.plan(c, audit_id)
        self.assertIn(('factory_attendance', 'FA-ROLLBACK', 'strip'),
                      {(d['table'], d['id'], d['action']) for d in plan['dependents']})
        with erp.connect(True) as c:
            audit_rollback.execute(c, audit_id, '录错员工', plan['fingerprint'], '管理员', erp.now(), erp.audit)
        with erp.connect() as c:
            self.assertFalse(c.execute('SELECT 1 FROM factory_employees WHERE id=?', ('FP-ROLLBACK',)).fetchone())
            self.assertFalse(c.execute('SELECT 1 FROM factory_attendance WHERE id=?', ('FA-ROLLBACK',)).fetchone())

    def test_role_reason_and_fingerprint_are_enforced(self):
        old = customer('C901')
        new = {**old, 'name': '新名'}
        self.insert_customer(new)
        audit_id = self.add_audit('修改客户名称', 'C901', old, new)
        with erp.connect() as c:
            plan = audit_rollback.plan(c, audit_id)
        with erp.connect(True) as c:
            with self.assertRaises(auth.AuthError):
                audit_rollback.execute(c, audit_id, '原因', plan['fingerprint'], '会计', erp.now(), erp.audit)
            with self.assertRaises(ValueError):
                audit_rollback.execute(c, audit_id, '', plan['fingerprint'], '管理员', erp.now(), erp.audit)
            with self.assertRaises(ValueError):
                audit_rollback.execute(c, audit_id, '原因', 'bad', '管理员', erp.now(), erp.audit)
            self.assertEqual(c.execute('SELECT name FROM customers WHERE id=?', ('C901',)).fetchone()[0], '新名')


    def test_statement_reference_blocks_rollback(self):
        payload = order('SO-STMT')
        with erp.connect(True) as c:
            c.execute('INSERT INTO orders VALUES(?,?)', ('SO-STMT', json.dumps(payload, ensure_ascii=False)))
            c.execute('INSERT INTO statement_documents(id,request_key,customer_id,business_date,issued_at,payload,content_hash) '
                      'VALUES(?,?,?,?,?,?,?)', ('DZ-ROLL', 'req-dz', 'C900', '2026-10-20', '2026-10-20T12:00:00',
                                                json.dumps({'current': [{'id': 'SO-STMT'}]}), 'hash'))
        audit_id = self.add_audit('登记订单', 'SO-STMT', None, payload)
        with erp.connect() as c:
            plan = audit_rollback.plan(c, audit_id)
        self.assertTrue(any('DZ-ROLL' in item for item in plan['blockers']))
        self.assertNotIn('DZ-ROLL', {d['id'] for d in plan['dependents']})

    def test_http_admin_only(self):
        old = customer('C902')
        new = {**old, 'name': '新名'}
        self.insert_customer(new)
        audit_id = self.add_audit('修改客户名称', 'C902', old, new)
        code, plan, _ = self.admin.request('/api/audit-rollback-plan?id=' + str(audit_id))
        self.assertEqual(code, 200, plan)
        self.assertEqual(plan['mode'], 'restore')
        accountant, _ = self.user('rollback-accountant', '会计')
        code, body, _ = accountant.request('/api/audit-rollback-plan?id=' + str(audit_id))
        self.assertEqual(code, 403, body)
        code, body, _ = accountant.request('/api/audit-rollback', {'audit_id': audit_id, 'reason': '原因',
                                                                   'fingerprint': plan['fingerprint']})
        self.assertEqual(code, 403, body)
        code, body, _ = self.admin.request('/api/audit-rollback', {'audit_id': audit_id, 'reason': '',
                                                                   'fingerprint': plan['fingerprint']})
        self.assertEqual(code, 400, body)
        code, body, _ = self.admin.request('/api/audit-rollback', {'audit_id': audit_id, 'reason': '录错',
                                                                   'fingerprint': plan['fingerprint']})
        self.assertEqual(code, 200, body)
        with erp.connect() as c:
            self.assertEqual(c.execute('SELECT name FROM customers WHERE id=?', ('C902',)).fetchone()[0], '旧名')

    def test_closed_period_blocks_rollback_and_revision_is_bumped(self):
        import inventory
        import resources_costs as rc
        payload = order('SO-CLOSED')
        with erp.connect(True) as c:
            c.execute('INSERT INTO orders VALUES(?,?)', ('SO-CLOSED', json.dumps(payload, ensure_ascii=False)))
            c.execute('INSERT INTO resource_periods VALUES(?,?,?)',
                      ('2026-10', 1, rc.dump({'month': '2026-10', 'state': 'closed'})))
        audit_id = self.add_audit('登记订单', 'SO-CLOSED', None, payload)
        with erp.connect() as c:
            plan = audit_rollback.plan(c, audit_id)
        self.assertTrue(any('所属月份已成本结账' in b for b in plan['blockers']))
        with erp.connect(True) as c:
            with self.assertRaises(ValueError):
                audit_rollback.execute(c, audit_id, '重复登记', plan['fingerprint'], '管理员', erp.now(), erp.audit)
            self.assertTrue(c.execute('SELECT 1 FROM orders WHERE id=?', ('SO-CLOSED',)).fetchone())
        with erp.connect(True) as c:
            c.execute("DELETE FROM resource_periods")
            plan = audit_rollback.plan(c, audit_id)
            before = inventory.revision(c)
            audit_rollback.execute(c, audit_id, '重复登记', plan['fingerprint'], '管理员', erp.now(), erp.audit)
        with erp.connect() as c:
            self.assertEqual(inventory.revision(c), before + 1)
            self.assertFalse(c.execute('SELECT 1 FROM orders WHERE id=?', ('SO-CLOSED',)).fetchone())


if __name__ == '__main__':
    unittest.main()
