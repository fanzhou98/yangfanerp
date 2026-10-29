import json,unittest,copy,uuid
import test_inventory as fixture
import statements
erp=fixture.erp
class StatementDocumentTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    order=fixture.InventoryTests.order
    settle=fixture.InventoryTests.settle
    review=fixture.InventoryTests.review
    def body(self):
        with erp.connect() as c:s=statements.snapshot(c,'C001','2026-10-18',erp.now())
        return {'request_key':str(uuid.uuid4()),'customer_id':'C001','business_date':'2026-10-18','seller_name':'测试供货企业','seller_phone':'123456','buyer_name':'测试购货企业','operator':'测试出纳','identity_checked':True,'source_fingerprint':s['source_fingerprint'],'note':'仅用于测试'}
    def issue(self,b,role='出纳'):
        with erp.connect(True) as c:return statements.issue(c,b,role,erp.now,erp.audit)
    def test_issue_retains_immutable_number_amount_and_explicit_unconfirmed_state(self):
        self.review(self.settle(self.order()));b=self.body();s=self.issue(b)
        self.assertTrue(s['document_id'].startswith('DZ-'));self.assertEqual(s['document_state'],'待客户确认');self.assertEqual(len(s['content_hash']),64);self.assertEqual(s['document_template_version'],'0.20');self.assertIn('视为确认本单金额',s['confirmation_terms']['no_silence']);self.assertIn(s['document_id'],s['wechat_text']);self.assertIn('无误请回复“对”',s['wechat_text']);self.assertIn('3 日内提出',s['wechat_text']);self.assertNotIn('SHA',s['wechat_text'])
        with erp.connect() as c:saved=statements.get_document(c,s['document_id'])
        self.assertEqual(saved,s)
        # Repeating a request retrieves the same issued snapshot, even after later payments.
        with erp.connect(True) as c:
            row=c.execute('SELECT * FROM orders LIMIT 1').fetchone();o=json.loads(row['payload']);o['paid_cents']=1000;c.execute('UPDATE orders SET payload=? WHERE id=?',(erp.dumps(o),o['id']))
        self.assertEqual(self.issue(b),s)
        with erp.connect() as c:self.assertEqual(statements.get_document(c,s['document_id'])['totals'],s['totals'])
    def test_changed_finance_requires_reload_and_does_not_issue(self):
        o=self.review(self.settle(self.order()));b=self.body()
        erp.mutate('receipt',{'version':o['version'],'amount':'1','received_date':'2026-10-18','method':'测试到账'},'出纳',o['id'])
        with self.assertRaisesRegex(ValueError,'已有变化'):self.issue(b)
        with erp.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM statement_documents').fetchone()[0],0)
    def test_identity_permission_and_no_silent_confirmation(self):
        self.settle(self.order());b=self.body()
        for key,value in [('seller_name',''),('identity_checked',False)]:
            bad={**b,key:value}
            with self.assertRaises(ValueError):self.issue(bad)
        with self.assertRaises(ValueError):self.issue(b,'库管')
        s=self.issue({**b,'document_state':'已确认','silent_days':7});self.assertEqual(s['document_state'],'待客户确认')
        self.assertEqual(s['totals']['payable_cents'],0);self.assertGreater(s['totals']['pending_cents'],0)
    def test_archive_detects_modification_and_request_cannot_be_reused_for_other_party(self):
        self.review(self.settle(self.order()));b=self.body();s=self.issue(b)
        with self.assertRaises(ValueError):self.issue({**b,'buyer_name':'另一客户'})
        with erp.connect(True) as c:c.execute('UPDATE statement_documents SET payload=? WHERE id=?',('{}',s['document_id']))
        with erp.connect() as c:
            with self.assertRaisesRegex(ValueError,'校验不一致'):statements.get_document(c,s['document_id'])
    def test_status_reuses_issued_document_only_while_fingerprint_is_current(self):
        o=self.review(self.settle(self.order()));b=self.body()
        with erp.connect() as c:self.assertEqual(statements.latest_status(c,'C001','2026-10-18',erp.now())['document_id'],'')
        s=self.issue(b)
        with erp.connect() as c:current=statements.latest_status(c,'C001','2026-10-18',erp.now())
        self.assertEqual(current['document_id'],s['document_id']);self.assertFalse(current['stale'])
        erp.mutate('receipt',{'version':o['version'],'amount':'1','received_date':'2026-10-18','method':'测试到账'},'出纳',o['id'])
        with erp.connect() as c:changed=statements.latest_status(c,'C001','2026-10-18',erp.now())
        self.assertEqual(changed['document_id'],s['document_id']);self.assertTrue(changed['stale'])
