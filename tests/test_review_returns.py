import copy,unittest
import test_inventory as fixture
erp=fixture.erp
class ReviewReturnTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    order=fixture.InventoryTests.order
    settle=fixture.InventoryTests.settle
    review=fixture.InventoryTests.review
    def ret(self,o,reason='原价与订货手机不一致',role='出纳'):
        return erp.mutate('return-review',{'version':o['version'],'reason':reason},role,o['id'])
    def test_return_correct_resubmit_approve_retains_snapshot_and_blocks_receipts(self):
        o=self.settle(self.order());snapshot=copy.deepcopy(o);r=self.ret(o)
        self.assertEqual((r['state'],r['total_cents'],erp.status(r)),('negotiation',0,'待重算'))
        self.assertEqual(r['review_history'][0]['total_cents'],snapshot['total_cents']);self.assertEqual(r['review_history'][0]['lines'],snapshot['lines'])
        self.assertEqual(r['lines'][0]['actual_qty'],snapshot['lines'][0]['actual_qty'])
        with self.assertRaises(ValueError):erp.mutate('receipt',{'version':r['version'],'amount':'1','received_date':'2026-10-21','method':'现金'},'出纳',r['id'])
        edited=copy.deepcopy(r);edited['lines'][0]['price']='3.5';edited=erp.mutate('order',edited,'会计',r['id']);self.assertEqual(edited['review_return']['status'],'pending')
        submitted=self.settle(edited);self.assertEqual(submitted['review_return']['status'],'resubmitted');self.assertTrue(submitted['review_return']['resubmitted_at'])
        self.assertEqual(erp.status(submitted),'待复核');approved=self.review(submitted)
        self.assertEqual([e['status'] for e in approved['review_history']],['resubmitted','approved'])
        self.assertEqual(approved['review_history'][0]['lines'],snapshot['lines'])
    def test_reason_role_version_and_posted_records_protected(self):
        o=self.settle(self.order())
        for role in ['库管','会计']:
            with self.assertRaises(ValueError):self.ret(o,role=role)
        with self.assertRaises(ValueError):self.ret(o,reason=' ')
        r=self.ret(o)
        with self.assertRaises(ValueError):self.ret(o)
        posted=self.review(self.settle(r))
        with self.assertRaises(ValueError):self.ret(posted)
    def test_reviewed_order_must_be_returned_before_recalculation(self):
        o=self.review(self.settle(self.order()))
        with self.assertRaisesRegex(ValueError,'已复核未收款'):
            erp.mutate('settle',{'version':o['version'],'mode':'customer'},'会计',o['id'])
    def test_batch_return_is_atomic_when_one_order_is_no_longer_ready(self):
        a=self.settle(self.order());b=self.review(self.settle(self.order()))
        with self.assertRaises(ValueError):erp.batch_mutate({'operations':[{'action':'return-review','order_id':o['id'],'body':{'version':o['version'],'reason':'核对价格'}} for o in [a,b]]},'出纳')
        current=next(o for o in erp.bootstrap()['orders'] if o['id']==a['id']);self.assertEqual(current['state'],'ready');self.assertFalse(current.get('review_history'))
