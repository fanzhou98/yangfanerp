import json
import unittest

import test_inventory as fixture

erp = fixture.erp


class BusinessIntegrityTests(unittest.TestCase):
    setUp = fixture.InventoryTests.setUp
    tearDown = fixture.InventoryTests.tearDown
    plan = fixture.InventoryTests.plan
    ret = fixture.InventoryTests.ret
    process = fixture.InventoryTests.process
    close_day = fixture.InventoryTests.close_day
    snapshot = fixture.InventoryTests.snapshot
    ops = fixture.InventoryTests.ops

    def change_unit(self, pid='P003'):
        with erp.connect() as c:
            product = dict(c.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone())
        return erp.master({**product, 'kind': 'product', 'create': False,
                           'expected': product, 'unit': '包', 'tare': '0', 'standard_kg': '5'}, '会计')

    def test_inventory_restore_keeps_archive_identity_and_marks_restored(self):
        self.plan()
        self.ret()
        self.process()
        self.close_day()
        before = erp.bootstrap()
        archive = erp.trial_data({'action': 'archive', 'reason': '隔离测试库存归档',
                                 'expected': {k: len(before[k]) for k in ('orders', 'receipts', 'archived_orders')}}, '会计')
        restored = erp.trial_data({'action': 'restore', 'id': archive['id'],
                                  '_data_epoch': archive['business_data_epoch']}, '会计')
        self.assertEqual(restored['id'], archive['id'])
        with erp.connect() as c:
            record = c.execute('SELECT restored_at FROM trial_archives WHERE id=?', (archive['id'],)).fetchone()
            audit = c.execute("SELECT entity FROM audit WHERE action='恢复整轮试运行业务数据' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(record['restored_at'])
        self.assertEqual(audit['entity'], archive['id'])
        after = erp.bootstrap()
        for key in ('warehouse_plans', 'sales_returns', 'processing_batches', 'stock_closings'):
            self.assertEqual(before[key], after[key])
        with self.assertRaisesRegex(ValueError, '已经恢复'):
            erp.trial_data({'action': 'restore', 'id': archive['id'],
                           '_data_epoch': restored['business_data_epoch']}, '会计')

    def test_all_inventory_and_archived_references_prevent_unit_reinterpretation(self):
        # No sales or price rules refer to P003. Each independent history must
        # still prevent 10 baskets from silently becoming 10 packages.
        examples = [
            ('warehouse_plans', 'business_date', {'stock': [{'product_id': 'P003', 'existing_qty': '10'}]}),
            ('sales_returns', 'id', {'product_id': 'P003', 'voided': True}),
            ('processing_batches', 'id', {'product_id': 'P003', 'outputs': []}),
            ('processing_batches', 'id', {'product_id': 'P002', 'outputs': [{'product_id': 'P003'}]}),
            ('stock_closings', 'business_date', {'products': [{'product_id': 'P003', 'counted_qty': '10'}]}),
            ('archived_orders', 'id', {'lines': [{'product_id': 'P003'}]}),
            ('statement_documents', 'id', {'history': [{'lines': [{'product_id': 'P003'}]}]}),
            ('trial_archives', 'id', {'inventory_rows': {'sales_returns': [{'payload': json.dumps({'product_id': 'P003'})}]}}),
        ]
        for table, key, payload in examples:
            with self.subTest(table=table, payload=payload):
                raw = json.dumps(payload)
                with erp.connect(True) as c:
                    if table == 'archived_orders':
                        c.execute('INSERT INTO archived_orders VALUES(?,?,?,?,?)', ('audit-ref', raw, 'kept', 'test', erp.now()))
                    elif table == 'statement_documents':
                        c.execute('INSERT INTO statement_documents VALUES(?,?,?,?,?,?,?)', ('audit-ref', 'audit-key', 'C001', '2026-10-21', erp.now(), raw, 'test'))
                    elif table == 'trial_archives':
                        c.execute('INSERT INTO trial_archives VALUES(?,?,?,?,NULL)', ('audit-ref', raw, erp.now(), 'test'))
                    else:
                        c.execute('INSERT INTO '+table+'('+key+',payload) VALUES(?,?)', ('audit-ref', raw))
                try:
                    with self.assertRaises(erp.ValidationError) as caught:
                        self.change_unit()
                    self.assertIn('unit', {issue['field'] for issue in caught.exception.issues})
                    with erp.connect() as c:
                        self.assertEqual(c.execute("SELECT unit FROM products WHERE id='P003'").fetchone()[0], '筐')
                finally:
                    with erp.connect(True) as c:
                        c.execute('DELETE FROM '+table+' WHERE '+key+'=?', ('audit-ref',))

    def test_unused_product_unit_can_still_be_corrected(self):
        self.change_unit()
        with erp.connect() as c:
            self.assertEqual(c.execute("SELECT unit FROM products WHERE id='P003'").fetchone()[0], '包')

    def test_later_day_close_prevents_actual_changes_in_unclosed_earlier_day(self):
        body = {'customer_id': 'C001', 'business_date': '2026-10-21', 'batch': '封账范围测试',
                'lines': [{'product_id': 'P001', 'ordered_qty': '2', 'actual_qty': '1',
                           'price': '3', 'driver': [], 'customer': []}]}
        old = erp.mutate('order', body, '库管')
        self.plan('2026-10-22')
        self.close_day('2026-10-22')
        with self.assertRaisesRegex(ValueError, '日结范围'):
            erp.mutate('order', body, '库管')
        changed = {**old, 'lines': [{**old['lines'][0], 'actual_qty': '2'}]}
        with self.assertRaisesRegex(ValueError, '日结范围'):
            erp.mutate('order', changed, '库管', old['id'])
        # Correcting physical weights without changing inventory remains valid.
        weighted = {**old, 'lines': [{**old['lines'][0], 'driver': [{'gross': '11', 'count': '1', 'tare': '1'}]}]}
        saved = erp.mutate('order', weighted, '库管', old['id'])
        self.assertEqual(saved['lines'][0]['driver_net'], '10')
        self.assertEqual(saved['lines'][0]['actual_qty'], '1')

    def test_actual_cannot_be_moved_out_of_a_closed_range(self):
        old = erp.mutate('order', {'customer_id': 'C001', 'business_date': '2026-10-21', 'batch': '跨日测试',
                                 'lines': [{'product_id': 'P001', 'ordered_qty': '1', 'actual_qty': '1',
                                            'price': '3', 'driver': [], 'customer': []}]}, '库管')
        self.plan('2026-10-22')
        self.close_day('2026-10-22')
        with self.assertRaisesRegex(ValueError, '日结范围'):
            erp.mutate('order', {**old, 'business_date': '2026-10-23'}, '库管', old['id'])

    def test_unshipped_draft_date_change_does_not_count_as_stock_movement(self):
        old = erp.mutate('order', {'customer_id': 'C001', 'business_date': '2026-10-21', 'batch': '未发草稿测试',
                                 'lines': [{'product_id': 'P001', 'ordered_qty': '1', 'actual_qty': '0',
                                            'price': '3', 'driver': [], 'customer': []}]}, '库管')
        self.plan('2026-10-22')
        self.close_day('2026-10-22')
        saved = erp.mutate('order', {**old, 'business_date': '2026-10-23'}, '库管', old['id'])
        self.assertEqual(saved['business_date'], '2026-10-23')
        self.assertEqual(saved['lines'][0]['actual_qty'], '0')


if __name__ == '__main__':
    unittest.main()
