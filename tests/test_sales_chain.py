import hashlib
import json
import unittest
import sales_chain
import test_workflow as fixture

erp=fixture.erp


class SalesChainTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.WorkflowTests();self.old=erp.DB;self.case.setUp()
        with erp.connect(True) as c:
            for table in ('orders','receipts','sales_returns','warehouse_plans','order_corrections','trade_records'):
                c.execute('DELETE FROM '+table)

    def tearDown(self):
        self.case.tearDown();erp.DB=self.old

    def order(self,oid='A',ordered='600',actual='580',state='reviewed',**extra):
        line={'product_id':'P001','product_name':'测试豆皮','unit':'筐','ordered_qty':ordered,'actual_qty':actual,
              'billing_unit':'公斤','bill_qty':'550','amount_cents':100000}
        o={'id':oid,'version':2,'customer_id':'C001','customer_name':'测试客户','business_date':'2026-10-22',
           'state':state,'total_cents':100000,'paid_cents':0,'lines':[line],**extra}
        with erp.connect(True) as c:c.execute('INSERT INTO orders VALUES(?,?)',(oid,json.dumps(o)))
        return o

    def put(self,table,r):
        with erp.connect(True) as c:c.execute('INSERT INTO '+table+' VALUES(?,?)',(r['id'],json.dumps(r)))

    def report(self,**kw):
        with erp.connect() as c:return sales_chain.report(c,'2026-10-22','2026-10-22',**kw)

    def test_short_excess_are_separate_and_settlement_kg_does_not_replace_units(self):
        self.order();self.order('B',actual='620')
        r=self.report();q=r['quantities'][0]
        self.assertEqual((q['short_qty'],q['excess_qty'],q['unit']),('20','20','筐'))
        self.assertEqual(r['summary']['orders'],2)
        self.assertEqual(r['rows'][0]['lines'][0]['bill_qty'],'550')

    def test_unknown_dispatch_is_not_a_zero_shipment_or_shortage(self):
        self.order(actual='0',state='draft')
        r=self.report();self.assertIsNone(r['rows'][0]['lines'][0]['short_qty'])
        self.assertEqual(r['summary']['short_orders'],0)
        self.assertEqual(r['quantities'][0]['pending_lines'],1)
        o=self.order('B',actual='0',state='draft')
        o['lines'][0]['not_shipped']=True
        with erp.connect(True) as c:c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),'B'))
        self.assertEqual(self.report(status='short')['summary']['orders'],1)

    def test_draft_allocation_is_not_confirmed_and_confirmed_zero_is_known(self):
        self.order(actual='0',state='dispatched',dispatch_required=True)
        plan={'business_date':'2026-10-22','allocation_state':'draft','allocations':[{'order_id':'A','product_id':'P001','qty':'0'}]}
        with erp.connect(True) as c:c.execute('INSERT INTO warehouse_plans VALUES(?,?)',('2026-10-22',json.dumps(plan)))
        self.assertIsNone(self.report()['rows'][0]['lines'][0]['actual_qty'])
        plan['allocation_state']='confirmed'
        with erp.connect(True) as c:c.execute('UPDATE warehouse_plans SET payload=?',(json.dumps(plan),))
        self.assertEqual(self.report()['rows'][0]['lines'][0]['short_qty'],'600')

    def test_controlled_correction_preserves_original_demand_and_feedback_snapshot(self):
        o=self.order(state='dispatched',dispatch_required=True)
        self.put('order_corrections',{'id':'CORR','order_id':'A','kind':'shipment','after':o,'quantity_changes':[{'product_id':'P001','before_qty':'600','after_qty':'580'}]})
        with erp.connect(True) as c:c.execute('INSERT INTO trade_records VALUES(?,?)',('FB',json.dumps({'id':'FB','kind':'feedback','order_id':'A','feedback_date':'2026-10-23','actual_qty':'600','received_qty':'580','source_order_version':1})))
        row=self.report()['rows'][0]
        self.assertEqual(row['lines'][0]['short_qty'],'20')
        self.assertEqual(row['feedback'][0]['actual_qty'],'600')
        self.assertEqual(row['lines'][0]['ordered_qty'],'600')
        self.assertEqual(len(row['corrections']),1)

    def test_cash_equation_does_not_subtract_attributed_returns_twice(self):
        self.order(paid_cents=30000,return_credit_cents=10000,discount_cents=5000,rounding_cents=1)
        self.put('receipts',{'id':'RC','order_id':'A','received_date':'2026-11-01','amount_cents':30000,'discount_cents':5000,'rounding_cents':1})
        self.put('sales_returns',{'id':'RET','order_id':'A','received_date':'2026-11-02','qty':'20','finance':{'state':'posted','amount_cents':20000}})
        r=self.report(view='collection');s=r['summary']
        self.assertEqual(s['outstanding_cents'],54999)
        self.assertEqual(s['attributed_return_cents'],20000)
        self.assertEqual(s['total_cents'],sum(s[k] for k in ('paid_cents','return_credit_cents','discount_cents','rounding_cents','outstanding_cents')))
        self.assertFalse(r['rows'][0]['issues'])
        self.assertEqual(r['rows'][0]['receipts'][0]['received_date'],'2026-11-01')

    def test_each_order_has_one_stage_even_with_many_lines_and_exceptions(self):
        self.order('D',state='draft',actual='0')
        self.order('W',state='dispatched',workflow_version=1)
        self.order('S',state='dispatched')
        self.order('R',state='dispatched',review_return={'status':'pending'})
        self.order('V',state='ready');self.order('U');self.order('C',paid_cents=100000)
        r=self.report(view='collection')
        self.assertEqual(sum(r['summary']['stage_counts'].values()),7)
        self.assertEqual(r['summary']['pending_review_cents'],100000)
        self.assertEqual(r['summary']['total_cents'],200000)
        self.assertIsNone(next(x for x in r['rows'] if x['order_id']=='V')['outstanding_cents'])

    def test_bad_balances_and_receipt_mismatches_are_visible(self):
        self.order(paid_cents=100001)
        r=self.report(view='collection');self.assertEqual(r['rows'][0]['stage'],'unknown')
        self.assertEqual(r['rows'][0]['outstanding_cents'],-1)
        self.assertEqual(r['summary']['issue_orders'],1)

    def test_product_filter_keeps_whole_order_money_and_quantities_do_not_mix_units(self):
        o=self.order();o['lines'].append({**o['lines'][0],'product_id':'P002','unit':'公斤','ordered_qty':'10','actual_qty':'10'})
        with erp.connect(True) as c:c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),'A'))
        self.assertEqual(len(self.report()['quantities']),2)
        r=self.report(product_id='P002');self.assertEqual(len(r['quantities']),1)
        self.assertEqual(len(r['rows'][0]['lines']),2)
        self.assertEqual(r['summary']['total_cents'],100000)
        self.assertEqual(self.report(customer_id='missing')['summary']['orders'],0)
        self.assertEqual(self.report(query='不存在')['summary']['orders'],0)

    def test_mixed_short_excess_order_can_match_either_filter_without_double_counting(self):
        o=self.order();o['lines'].append({**o['lines'][0],'product_id':'P002','actual_qty':'620'})
        with erp.connect(True) as c:c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),'A'))
        self.assertEqual(self.report(status='short')['summary']['orders'],1)
        self.assertEqual(self.report(status='excess')['summary']['orders'],1)
        self.assertEqual(self.report()['summary']['stage_counts']['unpaid'],1)

    def test_paging_does_not_truncate_filtered_totals_and_report_is_readonly(self):
        for i in range(52):self.order(str(i))
        before=hashlib.sha256(erp.DB.read_bytes()).hexdigest()
        r=self.report(page=2);self.assertEqual(len(r['rows']),2)
        self.assertEqual(r['summary']['orders'],52)
        self.assertEqual(r['summary']['total_cents'],5200000)
        self.assertEqual(before,hashlib.sha256(erp.DB.read_bytes()).hexdigest())

    def test_invalid_filters_and_date_ranges_rejected(self):
        for kw in ({'status':'bad'},{'view':'bad'},{'page':0},{'query':'x'*101}):
            with self.assertRaises(ValueError):self.report(**kw)
        with erp.connect() as c:
            with self.assertRaises(ValueError):sales_chain.report(c,'2026-10-23','2026-10-22')


if __name__=='__main__':unittest.main()
