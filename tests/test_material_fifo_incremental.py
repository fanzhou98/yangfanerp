import builtins
import datetime
import time
import unittest
from decimal import Decimal
from unittest.mock import patch
import resources_costs as rc
import test_warehouse_landed_cost as fixture


class MaterialFifoIncrementalTests(unittest.TestCase):
    """FIFO 层栈增量维护（排序游标 / uncosted 桶级标量 / 物料合计增量）的语义守卫。"""

    setUp = fixture.WarehouseLandedTests.setUp
    tearDown = fixture.WarehouseLandedTests.tearDown

    def entry(self, seq, kind, qty, amount='0', day='2026-10-20', wh='WH-TOFU', **extras):
        payload = {'id': 'E%04d' % seq, 'material_id': 'RM-SOY', 'warehouse_id': wh, 'kind': kind,
                   'qty': qty, 'amount_cents': int(Decimal(amount) * 100), 'business_date': day,
                   'sequence': seq, 'unit': '公斤', 'handler': '测试', **extras}
        self.c.execute('INSERT INTO material_entries VALUES(?,?,?)', (payload['id'], payload['id'], rc.dump(payload)))
        return payload

    def ledger(self, **kw):
        return rc.material_ledger(self.c, warehouse_details=True, **kw)

    def balance(self, wh, mid='RM-SOY', **kw):
        return next(s for s in self.ledger(material_ids=[mid], **kw)[2] if s['id'] == mid and s['warehouse_id'] == wh)

    def rows(self, **kw):
        return {e['id']: e for e in self.ledger(material_ids=['RM-SOY'], **kw)[1]}

    def allocs(self, entries):
        return [[a['lot_id'] for a in e['fifo_allocations']] for e in entries if e['fifo_allocations']]

    def test_backdated_receipts_consume_oldest_lot_first(self):
        self.entry(1, 'receipt', '10', '100', day='2026-10-05')
        self.entry(2, 'receipt', '10', '200', day='2026-10-01')
        self.entry(3, 'receipt', '10', '300', day='2026-10-03')
        consume = self.entry(4, 'consume', '15')
        row = self.rows()[consume['id']]
        self.assertEqual([a['lot_id'] for a in row['fifo_allocations']], ['E0002', 'E0003'])
        self.assertEqual([a['qty'] for a in row['fifo_allocations']], ['10', '5'])
        self.assertEqual(row['cost_cents'], 20000 + 15000)
        lots = self.balance('WH-TOFU')['lots']
        self.assertEqual([(l['received_date'], l['fifo_sequence'], l['qty']) for l in lots],
                         [('2026-10-03', 3, '5'), ('2026-10-05', 1, '10')])

    def test_transfer_merges_lots_in_fifo_order_and_moves_uncosted(self):
        self.entry(1, 'receipt', '10', '100', day='2026-10-01')
        self.entry(2, 'receipt', '10', '200', day='2026-10-03')
        self.entry(3, 'receipt', '20', '400', day='2026-10-10', wh='WH-SKIN')
        transfer = self.entry(4, 'transfer', '15', day='2026-10-11', target_warehouse_id='WH-SKIN')
        self.assertEqual([a['lot_id'] for a in self.rows()[transfer['id']]['fifo_allocations']], ['E0001', 'E0002'])
        self.assertEqual([(l['received_date'], l['qty']) for l in self.balance('WH-SKIN')['lots']],
                         [('2026-10-10', '20'), ('2026-10-01', '10'), ('2026-10-03', '5')])
        consume = self.entry(5, 'consume', '12', day='2026-10-12', wh='WH-SKIN')
        row = self.rows()[consume['id']]
        self.assertEqual([(a['lot_id'], a['qty']) for a in row['fifo_allocations']], [('E0001', '10'), ('E0002', '2')])
        self.assertEqual(row['cost_cents'], 10000 + 4000)
        self.assertEqual([(l['received_date'], l['qty']) for l in self.balance('WH-SKIN')['lots']],
                         [('2026-10-10', '20'), ('2026-10-03', '3')])

    def test_uncosted_balance_equals_lot_sum_after_mixed_stream(self):
        self.entry(1, 'receipt', '10', '0', day='2026-10-01')
        self.entry(2, 'receipt', '10', '100', day='2026-10-02')
        self.entry(3, 'consume', '15', day='2026-10-03')
        self.entry(4, 'transfer', '3', day='2026-10-04', target_warehouse_id='WH-SKIN')
        self.entry(5, 'receipt', '5', '0', day='2026-10-05', wh='WH-SKIN')
        self.entry(6, 'consume', '2', day='2026-10-06', wh='WH-SKIN')
        self.entry(7, 'consume', '4', day='2026-10-07', wh='WH-SKIN')
        rows = self.rows()
        self.assertEqual(rows['E0003']['uncosted_out_qty'], '10')
        self.assertEqual(rows['E0004']['uncosted_out_qty'], '0')
        self.assertEqual(rows['E0006']['uncosted_out_qty'], '0')
        self.assertEqual(rows['E0007']['uncosted_out_qty'], '3')
        total = Decimal(0)
        for wh in ('WH-TOFU', 'WH-SKIN'):
            s = self.balance(wh)
            lotsum = sum((Decimal(l['uncosted_qty']) for l in s['lots']), Decimal(0))
            self.assertEqual(Decimal(s['uncosted_qty']), lotsum, wh)
            total += lotsum
        aggregate = next(s for s in self.ledger(material_ids=['RM-SOY'])[0] if s['id'] == 'RM-SOY')
        self.assertEqual(Decimal(aggregate['uncosted_qty']), total)
        for row in rows.values():
            self.assertEqual(Decimal(row['uncosted_out_qty']),
                             sum((Decimal(a['uncosted_qty']) for a in row['fifo_allocations']), Decimal(0)))
        self.assertEqual(rows['E0004']['target_uncosted_balance_qty'], self.balance('WH-SKIN', until='2026-10-04')['uncosted_qty'])

    def test_material_totals_equal_sum_of_warehouse_balances_per_prefix(self):
        self.entry(1, 'receipt', '10', '100', day='2026-10-01')
        self.entry(2, 'receipt', '7', '0', day='2026-10-02', wh='WH-SKIN')
        self.entry(3, 'consume', '4', day='2026-10-03')
        self.entry(4, 'transfer', '6', day='2026-10-04', target_warehouse_id='WH-SKIN')
        self.entry(5, 'consume', '9', day='2026-10-05', wh='WH-SKIN')
        for day in ('2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05'):
            entries = self.ledger(until=day)[1]
            stock = {s['warehouse_id']: s for s in self.ledger(until=day)[2] if s['id'] == 'RM-SOY'}
            aggregate = next(s for s in self.ledger(until=day)[0] if s['id'] == 'RM-SOY')
            last = entries[-1]
            self.assertEqual(Decimal(last['balance_qty']), sum((Decimal(s['qty']) for s in stock.values()), Decimal(0)), day)
            self.assertEqual(last['balance_cents'], sum(s['value_cents'] for s in stock.values()), day)
            self.assertEqual(Decimal(last['uncosted_balance_qty']),
                             sum((Decimal(s['uncosted_qty']) for s in stock.values()), Decimal(0)), day)
            self.assertEqual(Decimal(aggregate['qty']), Decimal(last['balance_qty']))
            self.assertEqual(aggregate['value_cents'], last['balance_cents'])
            self.assertEqual(Decimal(aggregate['uncosted_qty']), Decimal(last['uncosted_balance_qty']))

    def test_long_consume_stream_does_not_resort_layers(self):
        count = 1500
        start = datetime.date(2026, 1, 1)
        for i in range(1, count + 1):
            self.entry(i, 'receipt', '10', '100', day=(start + datetime.timedelta(days=i - 1)).isoformat())
        for i in range(count + 1, 2 * count + 1):
            self.entry(i, 'consume', '10', day=(start + datetime.timedelta(days=i - 1)).isoformat())
        calls = []
        original = builtins.sorted

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        started = time.perf_counter()
        with patch.object(builtins, 'sorted', counting):
            entries = self.ledger(material_ids=['RM-SOY'])[1]
        elapsed = time.perf_counter() - started
        self.assertLessEqual(len(calls), 4, 'FIFO 重放不得逐笔整体重排层栈，sorted() 实际调用 %d 次' % len(calls))
        self.assertLess(elapsed, 1.5, 'FIFO 重放应随流水近似线性，实耗 %.3fs' % elapsed)
        self.assertEqual(entries[-1]['id'], 'E%04d' % (2 * count))
        self.assertEqual([(a['lot_id'], a['qty']) for a in entries[-1]['fifo_allocations']], [('E%04d' % count, '10')])
        self.assertEqual([l['qty'] for l in self.balance('WH-TOFU')['lots']], [])
        self.assertEqual(self.balance('WH-TOFU')['qty'], '0')


    def test_transfer_in_older_lot_than_consumed_prefix_is_allocated(self):
        """F1：transfer 把更旧批次搬入已消耗过的库房后，游标必须回退，否则静默少计。"""
        self.entry(1, 'receipt', '5', '500', day='2026-10-01')
        self.entry(2, 'receipt', '10', '1000', day='2026-10-05')
        self.entry(3, 'receipt', '10', '1000', day='2026-10-06')
        self.entry(4, 'consume', '5', day='2026-10-07')
        self.entry(5, 'consume', '1', day='2026-10-08')
        self.entry(6, 'receipt', '2', '400', day='2026-09-20', wh='WH-SKIN')
        self.entry(7, 'transfer', '2', day='2026-10-09', wh='WH-SKIN', target_warehouse_id='WH-TOFU')
        consume = self.entry(8, 'consume', '3', day='2026-10-10')
        row = self.rows()[consume['id']]
        self.assertEqual([(a['lot_id'], a['qty'], a['value_cents']) for a in row['fifo_allocations']],
                         [('E0006', '2', 40000), ('E0002', '1', 10000)])
        self.assertEqual(row['cost_cents'], 50000)
        self.assertEqual(row['balance_cents'], 180000)

    def test_source_lot_older_than_consumed_prefix_is_not_false_shortage(self):
        """F1：source_lot 指定被搬入的更旧批次时，不能误报余额不足。"""
        self.entry(1, 'receipt', '10', '100', day='2026-10-01')
        self.entry(2, 'receipt', '10', '200', day='2026-10-05')
        self.entry(3, 'receipt', '10', '300', day='2026-10-06')
        self.entry(4, 'consume', '10', day='2026-10-07')
        self.entry(5, 'consume', '1', day='2026-10-08')
        self.entry(6, 'receipt', '2', '400', day='2026-09-20', wh='WH-SKIN')
        self.entry(7, 'transfer', '2', day='2026-10-09', wh='WH-SKIN', target_warehouse_id='WH-TOFU')
        consume = self.entry(8, 'consume', '2', day='2026-10-10', source_lot_id='E0006')
        row = self.rows()[consume['id']]
        self.assertEqual([(a['lot_id'], a['qty']) for a in row['fifo_allocations']], [('E0006', '2')])
        self.assertEqual(row['cost_cents'], 40000)

    def test_equal_key_fragments_keep_insertion_order(self):
        """F2：同一批次碎片（同 lot_id/日期/序号）再次搬入时须插到等键片段之后，恢复旧插入序。"""
        self.entry(1, 'receipt', '10', '1000', day='2026-10-01')
        self.entry(2, 'transfer', '6', day='2026-10-02', target_warehouse_id='WH-SKIN')
        self.entry(3, 'transfer', '6', day='2026-10-03', wh='WH-SKIN', target_warehouse_id='WH-TOFU', source_lot_id='E0001')
        consume = self.entry(4, 'consume', '9', day='2026-10-04')
        tail = self.entry(5, 'consume', '1', day='2026-10-05')
        rows = self.rows()
        self.assertEqual([(a['lot_id'], a['qty']) for a in rows[consume['id']]['fifo_allocations']],
                         [('E0001', '4'), ('E0001', '5')])
        self.assertEqual([(a['lot_id'], a['qty']) for a in rows[tail['id']]['fifo_allocations']], [('E0001', '1')])

    def test_material_uncosted_total_equals_bucket_sum_in_moving_average_mode(self):
        """F3：非 FIFO（历史移动加权）模式下物料合计 uncosted 必须等于各库桶求和，无末位漂移。"""
        self.c.execute("DELETE FROM meta WHERE key='material_fifo_start'")
        self.entry(1, 'gain', '3', '0', day='2026-09-16', wh='WH-MAIN')
        self.entry(2, 'receipt', '20', '1000', day='2026-09-19', wh='WH-MAIN')
        self.entry(3, 'transfer', '5', day='2026-09-23', wh='WH-MAIN', target_warehouse_id='WH-TOFU')
        self.entry(4, 'transfer', '1', day='2026-09-30', wh='WH-MAIN', target_warehouse_id='WH-SKIN')
        led = self.ledger(material_ids=['RM-SOY'])
        total = Decimal(led[1][-1]['uncosted_balance_qty'])
        buckets = sum((Decimal(s['uncosted_qty']) for s in led[2] if s['id'] == 'RM-SOY'), Decimal(0))
        self.assertEqual(total, buckets)


if __name__ == '__main__':
    unittest.main()
