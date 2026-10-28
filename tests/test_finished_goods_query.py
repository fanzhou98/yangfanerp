"""Q03 external finished-goods history filters, totals and pagination."""
import json
import unittest
import test_accounting_supply as base
import finished_goods_query as fgq


class FinishedGoodsHistoryTests(unittest.TestCase):
    def setUp(self):
        base.AccountingSupplyTests.setUp(self)
        self.add('R1', {'kind':'receipt','business_date':'2026-08-05','supplier_id':'S1','supplier_name':'甲供应人','amount_cents':10000,'version':1,'due_date':'2026-09-04','reference':'GH-1','handler':'库管','lines':[{'product_id':'OIL','product_name':'油豆腐','unit':'盒','qty':'10','amount_cents':10000}]})
        self.add('R1-P', {'kind':'payment','business_date':'2026-08-06','receipt_id':'R1','supplier_id':'S1','supplier_name':'甲供应人','amount_cents':4000,'version':1})
        self.add('R1-F', {'kind':'refund','business_date':'2026-08-08','receipt_id':'R1','supplier_id':'S1','supplier_name':'甲供应人','amount_cents':500,'version':1})
        self.add('R1-C', {'kind':'receipt','business_date':'2026-08-09','return_of':'R1','supplier_id':'S1','supplier_name':'甲供应人','amount_cents':-2000,'version':1,'lines':[{'product_id':'OIL','product_name':'油豆腐','unit':'盒','qty':'-2','amount_cents':-2000}]})
        self.add('R2', {'kind':'receipt','business_date':'2026-09-10','supplier_id':'S2','supplier_name':'乙供应人','amount_cents':5000,'version':1,'pricing_pending':True,'lines':[{'product_id':'OIL','product_name':'油豆腐','unit':'盒','qty':'5','amount_cents':0}]})
        self.add('R3', {'kind':'receipt','business_date':'2026-10-01','supplier_id':'S1','supplier_name':'甲供应人','amount_cents':3000,'version':1,'voided':True,'lines':[]})

    def add(self, rid, payload):
        self.c.execute('INSERT INTO finished_goods_records VALUES(?,?)', (rid, json.dumps(payload, ensure_ascii=False)))

    def test_totals_returns_refunds_and_pending(self):
        r = fgq.history(self.c, start='2026-08-01', end='2026-09-30')
        self.assertEqual(r['total'], 2)
        self.assertEqual([x['id'] for x in r['rows']], ['R2', 'R1'])
        self.assertEqual(r['summary']['amount_cents'], 15000)
        self.assertEqual(r['summary']['returned_cents'], 2000)
        self.assertEqual(r['summary']['net_amount_cents'], 13000)
        self.assertEqual(r['summary']['paid_cents'], 3500)
        self.assertEqual(r['summary']['outstanding_cents'], 9500)
        self.assertEqual(r['summary']['pending_count'], 1)
        r1 = next(x for x in r['rows'] if x['id'] == 'R1')
        self.assertEqual(r1['paid_cents'], 3500)
        self.assertEqual(r1['returned_cents'], 2000)
        self.assertEqual(r1['net_amount_cents'], 8000)
        self.assertEqual(r1['outstanding_cents'], 4500)
        self.assertEqual(len(r1['payments']), 1)
        self.assertEqual(len(r1['refunds']), 1)
        self.assertEqual(r1['returns'], ['R1-C'])

    def test_supplier_status_search_and_page(self):
        self.assertEqual(fgq.history(self.c, start='2026-08-01', end='2026-09-30', supplier_id='S2')['rows'][0]['id'], 'R2')
        self.assertEqual([x['id'] for x in fgq.history(self.c, start='2026-08-01', end='2026-09-30', status='unpaid')['rows']], ['R1'])
        self.assertEqual([x['id'] for x in fgq.history(self.c, start='2026-08-01', end='2026-09-30', status='paid')['rows']], [])
        self.assertEqual([x['id'] for x in fgq.history(self.c, start='2026-08-01', end='2026-09-30', status='pending')['rows']], ['R2'])
        self.assertEqual(fgq.history(self.c, start='2026-08-01', end='2026-09-30', search='油豆腐')['total'], 2)
        self.assertEqual(fgq.history(self.c, start='2026-08-01', end='2026-09-30', search='GH-1')['total'], 1)
        p = fgq.history(self.c, start='2026-08-01', end='2026-09-30', page=2, page_size=1)
        self.assertEqual((p['page'], p['pages'], p['rows'][0]['id']), (2, 2, 'R1'))
        self.assertEqual(fgq.history(self.c, all_dates=True)['total'], 2)

    def test_validation(self):
        for args in (
            {'start':'2026-08-03','end':'2026-08-01'},
            {'start':'2026-08-01','end':'2026-08-03','all_dates':True},
            {'start':'2026-08-01','end':'2026-08-01','status':'bad'},
            {'start':'2026-08-01','end':'2026-08-01','page':0},
            {'start':'2026-08-01','end':'2026-08-01','page_size':201},
            {'start':'2026-08-01','end':'2026-08-01','supplier_id':'x'*41},
        ):
            with self.assertRaises(ValueError):
                fgq.history(self.c, **args)
