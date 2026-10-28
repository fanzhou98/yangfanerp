import unittest,json,uuid,copy
import test_inventory as fixture
import statements
erp=fixture.erp
class StatementBatchTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    def prepare(self):
        with erp.connect(True) as c:
            c.execute("INSERT INTO meta VALUES('statement_supplier',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(erp.dumps({'name':'测试工厂','phone':'123'}),))
            c.execute("UPDATE customers SET legal_name='执照正式名称' WHERE id='C001'")
        orders=[]
        for cid in ['C001','C002']:
            o=erp.mutate('order',{'customer_id':cid,'business_date':'2026-10-21','batch':'批量归档测试','lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'2','price':'75','driver':[],'customer':[]}]},'库管')
            o=erp.mutate('settle',{'version':o['version'],'mode':'customer'},'会计',o['id']);orders.append(o)
        return orders
    def preview(self):
        with erp.connect() as c:return statements.batch_preview(c,'2026-10-21',erp.now())
    def body(self):return {'request_key':str(uuid.uuid4()),'business_date':'2026-10-21','identity_checked':True,'items':[{'customer_id':r['customer_id'],'source_fingerprint':r['source_fingerprint']} for r in self.preview()['customers']]}
    def issue(self,b):
        with erp.connect(True) as c:return statements.issue_batch(c,b,'出纳',erp.now,erp.audit)
    def test_defaults_license_names_cashier_and_batch_idempotency(self):
        self.prepare();b=self.body();result=self.issue(b);self.assertEqual(result['count'],2)
        docs={d['customer_id']:d for d in result['documents']};self.assertEqual(docs['C001']['buyer_name'],'执照正式名称');self.assertEqual(docs['C002']['buyer_name'],next(c['name'] for c in erp.bootstrap()['customers'] if c['id']=='C002'))
        self.assertTrue(all(d['operator']=='出纳' for d in docs.values()));self.assertEqual(self.issue(b),result)
    def test_one_stale_customer_rolls_back_every_document(self):
        orders=self.prepare();b=self.body();o=copy.deepcopy(orders[-1]);o['lines'][0]['price']='76';erp.mutate('order',o,'会计',o['id'])
        with self.assertRaisesRegex(ValueError,'已有变化'):self.issue(b)
        with erp.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM statement_documents').fetchone()[0],0)
    def test_operator_is_active_versioned_and_archived_name_is_immutable(self):
        self.prepare();b=self.body();u=erp.save_operator_user({'name':'实际出纳','role':'出纳','active':True,'version':0},'会计');b.update(operator_user_id=u['id'],operator_version=u['version']);r=self.issue(b)
        erp.save_operator_user({**u,'name':'改名出纳','active':False},'会计')
        with erp.connect() as c:self.assertEqual(statements.get_document(c,r['documents'][0]['id'])['parties']['operator'],'实际出纳')
        b['request_key']=str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError,'已停用'):self.issue(b)
    def test_legal_name_single_default_and_validation(self):
        self.prepare()
        with erp.connect(True) as c:
            s=statements.snapshot(c,'C001','2026-10-21',erp.now());d=statements.issue(c,{'request_key':str(uuid.uuid4()),'customer_id':'C001','business_date':'2026-10-21','seller_name':'测试工厂','operator_user_id':'OP-CASHIER','identity_checked':True,'source_fingerprint':s['source_fingerprint']},'出纳',erp.now,erp.audit)
            self.assertEqual(d['parties']['buyer_name'],'执照正式名称')
        b=self.body();b['items'].append(b['items'][0])
        with self.assertRaisesRegex(ValueError,'客户重复'):self.issue(b)
