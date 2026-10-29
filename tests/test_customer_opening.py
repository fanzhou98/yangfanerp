"""期初应收：客户档案的历史欠款要进账龄预警与对账口径。"""
import test_workflow as workflow
import production_management as pm
import cash_query

erp=workflow.erp


class CustomerOpeningTests(workflow.unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown

    def add(self,**extra):
        return erp.master({'kind':'customer','create':True,'name':'期初客户','region':'昌吉',
            'location_kind':'market','market_id':'M005',**extra},'会计')['id']

    def test_opening_saved_and_scoped_by_date(self):
        cid=self.add(opening='123.45',opening_date='2026-09-01')
        row=next(c for c in erp.bootstrap()['customers'] if c['id']==cid)
        self.assertEqual((row['opening_cents'],row['opening_date']),(12345,'2026-09-01'))
        with erp.connect() as c:
            before={a['customer_id']:a for a in pm.ar_alerts(c,'2026-08-31')}
            after={a['customer_id']:a for a in pm.ar_alerts(c,'2026-09-02')}
            self.assertNotIn(cid,before)
            self.assertEqual(after[cid]['opening_cents'],12345)
            self.assertEqual(after[cid]['outstanding_cents'],12345)
            self.assertEqual(after[cid]['oldest_date'],'2026-09-01')
            later={a['customer_id']:a for a in pm.ar_alerts(c,'2026-09-20')}
            self.assertEqual(later[cid]['days'],19)
            self.assertTrue(later[cid]['days_alert'])
            self.assertFalse(after[cid]['days_alert'])
            self.assertEqual(cash_query.report(c,'2026-09-02')['totals']['receivable_cents'],12345)
            self.assertEqual(cash_query.report(c,'2026-08-31')['totals']['receivable_cents'],0)

    def test_opening_can_be_cleared_and_validated(self):
        cid=self.add(opening='50',opening_date='2026-09-01')
        erp.master({'kind':'customer','create':False,'id':cid,'name':'期初客户','region':'昌吉',
            'location_kind':'market','market_id':'M005','opening':'','opening_date':''},'会计')
        row=next(c for c in erp.bootstrap()['customers'] if c['id']==cid)
        self.assertEqual((row['opening_cents'],row['opening_date']),(0,''))
        with self.assertRaises(ValueError):self.add(opening='10')
        with self.assertRaises(ValueError):self.add(opening='-1',opening_date='2026-09-01')
        with self.assertRaises(ValueError):self.add(opening='1.234',opening_date='2026-09-01')
        with self.assertRaises(ValueError):self.add(opening='10',opening_date='2099-01-01')
