import importlib.util
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal

spec=importlib.util.spec_from_file_location('erp',Path(__file__).resolve().parents[1]/'server.py')
erp=importlib.util.module_from_spec(spec);spec.loader.exec_module(erp)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        erp.DB=Path(self.tmp.name)/'test.db'
        erp.init_db()
    def tearDown(self): self.tmp.cleanup()
    def order(self, unit='P001'):
        kg=unit=='P001'
        return erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-18','batch':'跨零点批次','note':'测试',
          'lines':[{'product_id':unit,'ordered_qty':'10','actual_qty':'10','price':'3.333' if kg else '75',
                    'driver':[{'gross':'110','count':'5','tare':'1.8'},{'gross':'112','count':'5','tare':'1.8'}] if kg else [],
                    'customer':[{'gross':'219','count':'10','tare':'1.8'}] if kg else []}]},'库管')
    def settle(self,o,**kwargs): return erp.mutate('settle',{'version':o['version'],'mode':'customer',**kwargs},'会计',o['id'])
    def review(self,o): return erp.mutate('review',{'version':o['version'],'evidence_checked':True},'出纳',o['id'])
    def pay(self,o,amount): return erp.mutate('receipt',{'version':o['version'],'amount':amount,'received_date':'2026-10-18','method':'银行转账'},'出纳',o['id'])
    def test_full_workflow_exact_arithmetic_and_partial_receipts(self):
        o=self.order()
        self.assertEqual(o['lines'][0]['driver_net'],'204')
        self.assertEqual(o['lines'][0]['customer_net'],'201')
        o=self.settle(o)
        self.assertEqual(o['total_cents'],66993) # 201 * 3.333 = 669.933, round to cents
        o=self.review(o)
        o=self.pay(o,'500')
        self.assertEqual(o['status'],'部分收款')
        o=self.pay(o,'169.93')
        self.assertEqual(o['status'],'已收清')
        data=erp.bootstrap()
        self.assertEqual(next(x for x in data['orders'] if x['id']==o['id'])['paid_cents'],66993)
    def test_negotiation_requires_reason_preserves_both_weights(self):
        o=self.order()
        o=erp.mutate('negotiate',{'version':o['version'],'reason':'待确认'},'会计',o['id'])
        with self.assertRaises(ValueError): self.review(o)
        with self.assertRaises(ValueError): self.settle(o,mode='agreed',agreed={'P001':'202'},reason='')
        o=self.settle(o,mode='agreed',agreed={'P001':'202'},reason='双方电话确认202公斤')
        self.assertEqual(o['lines'][0]['driver_net'],'204')
        self.assertEqual(o['lines'][0]['customer_net'],'201')
        self.assertEqual(o['lines'][0]['agreed_net'],'202')
        self.assertEqual(o['total_cents'],67327)
    def test_edit_invalidates_review_and_receivable(self):
        o=self.review(self.settle(self.order()))
        before=o['version'];o=erp.mutate('order',o,'会计',o['id'])
        self.assertEqual(o['state'],'dispatched');self.assertIsNone(o['review']);self.assertIsNone(o['settlement'])
        self.assertEqual(o['total_cents'],0);self.assertEqual(o['version'],before+1)
        with self.assertRaises(ValueError): self.pay(o,'1')
    def test_payment_blocks_overpayment_edit_and_resettlement(self):
        o=self.review(self.settle(self.order()))
        with self.assertRaises(ValueError):self.pay(o,'999999')
        o=self.pay(o,'1')
        with self.assertRaises(ValueError):erp.mutate('order',o,'会计',o['id'])
        with self.assertRaises(ValueError):self.settle(o)
        with self.assertRaises(ValueError):erp.mutate('negotiate',{'version':o['version'],'reason':'新原因'},'会计',o['id'])
    def test_version_prevents_stale_overwrite_and_duplicate_receipt(self):
        o=self.order();old=dict(o)
        newer=self.settle(o)
        with self.assertRaises(ValueError):erp.mutate('order',old,'会计',o['id'])
        reviewed=self.review(newer);self.pay(reviewed,'1')
        with self.assertRaises(ValueError):self.pay(reviewed,'1')
    def test_wrong_role_and_no_evidence_cannot_review(self):
        o=self.settle(self.order())
        with self.assertRaises(ValueError):erp.mutate('review',{'version':o['version'],'evidence_checked':True},'会计',o['id'])
        with self.assertRaises(ValueError):erp.mutate('review',{'version':o['version'],'evidence_checked':False},'出纳',o['id'])
    def test_incomplete_weighing_rejected_before_settlement(self):
        o=self.order();o['lines'][0]['customer'][0]['count']='9'
        o=erp.mutate('order',o,'库管',o['id'])
        with self.assertRaises(ValueError):self.settle(o)
    def test_bad_tare_and_nonfinite_values_rejected(self):
        for x in ['NaN','Infinity','-1','0.0001',True]:
            with self.assertRaises(ValueError):erp.dec(x)
        o=self.order();o['lines'][0]['driver'][0]['gross']='1'
        with self.assertRaises(ValueError):erp.mutate('order',o,'库管',o['id'])
    def test_pack_billing_does_not_invent_measured_weight(self):
        o=self.settle(self.order('P004'))
        self.assertEqual(o['lines'][0]['bill_qty'],'10');self.assertEqual(o['total_cents'],75000)
        self.assertEqual(o['lines'][0]['driver'],[])
    def test_customer_rule_snapshot_and_audit(self):
        o=self.order();line=o['lines'][0]
        erp.master({'kind':'rule','customer_id':'C001','product_id':'P001','price':'9','tare':'2'},'会计')
        stored=next(x for x in erp.bootstrap()['orders'] if x['id']==o['id'])
        self.assertEqual(stored['lines'][0]['price'],line['price'])
        self.assertEqual(stored['lines'][0]['driver'][0]['tare'],'1.8')
        with erp.connect() as c:
            entry=c.execute('SELECT after_json FROM audit WHERE entity=?',(o['id'],)).fetchone()
            self.assertIn('driver',entry[0])
    def test_database_reopen_retains_records(self):
        o=self.order();erp.init_db()
        self.assertIn(o['id'],[x['id'] for x in erp.bootstrap()['orders']])

if __name__=='__main__':unittest.main(verbosity=2)
