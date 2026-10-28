import copy,json,unittest,uuid
from decimal import Decimal
import test_inventory as fixture
import inventory,order_corrections as corrections,statements,resources_costs as rc

erp=fixture.erp
class OrderCorrectionTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    snapshot=fixture.InventoryTests.snapshot
    ops=fixture.InventoryTests.ops
    day='2026-10-21'
    def prepared(self,reviewed=False,count=None):
        o=erp.mutate('order',{'customer_id':'C001','business_date':self.day,'batch':'历史差错测试','workflow_version':1,'dispatch_required':True,'lines':[{'product_id':'P001','ordered_qty':'10','actual_qty':'0','price':'3','driver':[],'customer':[]}]},'管理员')
        d=erp.bootstrap();r=erp.save_warehouse({'business_date':self.day,'version':0,'inventory_revision':d['inventory_revision'],'stage':'confirm_dispatch','evidence_checked':True,'stock':[{'product_id':p['id'],'existing_qty':'20','produced_qty':'0'} for p in d['products']],'allocations':[{'order_id':o['id'],'product_id':'P001','qty':'10','ordered_qty':'10','mode':'manual'}],'order_versions':{o['id']:o['version']},'customers':[]},'管理员');o=r['orders'][0]
        o['lines'][0]['driver']=[{'gross':'150','count':'10','tare':'0'}];o=erp.mutate('order',o,'管理员',o['id']);o=erp.mutate('confirm-weight',{'version':o['version'],'evidence_checked':True},'管理员',o['id']);o=erp.mutate('settle',{'version':o['version'],'mode':'driver'},'管理员',o['id'])
        if reviewed:o=erp.mutate('review',{'version':o['version'],'evidence_checked':True},'管理员',o['id'])
        if count is not None:
            snap=self.snapshot();d=erp.bootstrap();p=d['warehouse_plans'][0]
            self.ops('close',{'business_date':self.day,'version':0,'inventory_revision':d['inventory_revision'],'plan_version':p['version'],'evidence_checked':True,'counts':[{'product_id':x['product_id'],'counted_qty':str(count) if x['product_id']=='P001' else x['book_qty'],'reason':'原实盘与账面差异待核对'} for x in snap['products']]})
        return o
    def issue(self,day=None):
        with erp.connect(True) as c:
            s=statements.snapshot(c,'C001',day or self.day,erp.now())
            return statements.issue(c,{'request_key':str(uuid.uuid4()),'customer_id':'C001','business_date':day or self.day,'seller_name':'测试工厂','buyer_name':'测试客户','operator':'出纳','identity_checked':True,'source_fingerprint':s['source_fingerprint']},'管理员',erp.now,erp.audit)
    def correct(self,o,qty=None,action='shipment',role='会计',**extra):
        lines=copy.deepcopy(o['lines'])
        if qty is not None:
            lines[0].update(actual_qty=str(qty),driver=[{'gross':'120','count':str(qty),'tare':'0'}])
        b={'action':action,'order_id':o['id'],'version':o['version'],'request_key':str(uuid.uuid4()),'reason':'客户反馈少发，司机照片核对后确认','evidence_checked':True,'physical_count_confirmed':True,'inventory_revision':erp.bootstrap()['inventory_revision'],'lines':lines,**extra}
        with erp.connect(True) as c:return corrections.save(c,b,role,erp.now,erp.audit,erp.normalize_order,erp.save,erp.get_order)
    def test_closed_short_delivery_restates_variance_and_preserves_next_opening(self):
        o=self.prepared(count=12);doc=self.issue();doc2=self.issue('2026-10-22')
        with erp.connect() as c:original=c.execute('SELECT payload FROM stock_closings WHERE business_date=?',(self.day,)).fetchone()[0]
        erp.save_warehouse({'business_date':'2026-10-22','opening_source_date':self.day,'opening_close_version':1,'version':0,'inventory_revision':erp.bootstrap()['inventory_revision'],'stage':'stock','stock':[{'product_id':p['id'],'existing_qty':'12' if p['id']=='P001' else '20','produced_qty':'0'} for p in erp.bootstrap()['products']],'allocations':[],'order_versions':{},'customers':[]},'管理员')
        r=self.correct(o,8);self.assertEqual(set(r['voided_document_ids']),{doc['document_id'],doc2['document_id']})
        p=next(p for p in self.snapshot()['products'] if p['product_id']=='P001');self.assertEqual(p['book_qty'],'12')
        nextday=self.snapshot('2026-10-22')['products'][0];self.assertEqual(nextday['opening_qty'],'12');self.assertEqual(nextday['book_qty'],'12')
        with erp.connect() as c:
            closing=inventory.closed(c,self.day)['products'][0];self.assertEqual(closing['variance_qty'],'0');self.assertEqual(closing['original_variance_qty'],'2')
            self.assertEqual(c.execute('SELECT payload FROM stock_closings WHERE business_date=?',(self.day,)).fetchone()[0],original)
            archived=statements.get_document(c,doc['document_id']);self.assertTrue(archived['voided']);self.assertEqual(archived['content_hash'],doc['content_hash'])
        new=r['order'];result=erp.batch_mutate({'operations':[{'action':'settle','order_id':new['id'],'body':{'version':new['version'],'mode':'driver','confirm_accounting_entry':True,'evidence_checked':True}}]},'管理员');self.assertEqual(result['orders'][0]['state'],'ready');fresh=self.issue();self.assertNotEqual(fresh['document_id'],doc['document_id']);self.assertNotIn('voided',fresh)
    def test_closed_extra_delivery_reduces_variance_without_current_stock_movement(self):
        o=self.prepared(count=8);r=self.correct(o,12)
        with erp.connect() as c:
            p=inventory.closed(c,self.day)['products'][0];self.assertEqual((p['book_qty'],p['counted_qty'],p['variance_qty']),('8','8','0'));self.assertEqual(corrections.effective_plan(c,inventory.get(c,'warehouse_plans',self.day,'business_date'))['allocations'][0]['qty'],'12')
    def test_reviewed_requires_cashier_reopen_then_accountant_resubmits(self):
        o=self.prepared(reviewed=True,count=12);doc=self.issue()
        with self.assertRaisesRegex(ValueError,'出纳'):self.correct(o,action='reopen')
        opened=self.correct(o,action='reopen',role='出纳')['order'];self.assertEqual(opened['total_cents'],0)
        changed=self.correct(opened,8)['order'];self.assertEqual(changed['lines'][0]['actual_qty'],'8')
        with erp.connect() as c:self.assertTrue(statements.get_document(c,doc['document_id'])['voided'])
    def test_paid_orders_keep_cash_and_cannot_reopen(self):
        o=self.prepared(reviewed=True);o=erp.mutate('receipt',{'version':o['version'],'amount':'1','received_date':self.day,'method':'现金'},'出纳',o['id']);doc=self.issue()
        with self.assertRaisesRegex(ValueError,'收款'):self.correct(o,action='reopen',role='出纳')
        with erp.connect() as c:self.assertEqual(erp.get_order(c,o['id'])['paid_cents'],100);self.assertFalse(corrections.void_info(c,doc['document_id']))
    def test_missing_count_confirmation_or_stale_inventory_rolls_back_everything(self):
        o=self.prepared(count=12);doc=self.issue()
        with self.assertRaisesRegex(ValueError,'日终实盘'):self.correct(o,8,physical_count_confirmed=False)
        with self.assertRaisesRegex(ValueError,'库存'):self.correct(o,8,inventory_revision=-1)
        with erp.connect() as c:self.assertFalse(corrections.void_info(c,doc['document_id']));self.assertEqual(erp.get_order(c,o['id'])['version'],o['version']);self.assertEqual(corrections.records(c),[])
    def test_open_day_correction_checks_stock_and_is_idempotent(self):
        o=self.prepared();key=str(uuid.uuid4());before=erp.bootstrap()['inventory_revision'];r=self.correct(o,8,request_key=key,inventory_revision=before);again=self.correct(o,8,request_key=key,inventory_revision=before);self.assertEqual(again['correction_id'],r['correction_id']);self.assertEqual(self.snapshot()['products'][0]['book_qty'],'12')
        with self.assertRaises(ValueError):self.correct(r['order'],30)
        with erp.connect() as c:self.assertEqual(erp.get_order(c,o['id'])['lines'][0]['actual_qty'],'8')
    def test_ordinary_edit_invalidates_all_old_statement_versions(self):
        o=self.prepared();a=self.issue();b=self.issue('2026-10-22');o['lines'][0]['driver'][0]['gross']='140';erp.mutate('order',o,'会计',o['id'])
        with erp.connect() as c:self.assertTrue(corrections.void_info(c,a['document_id']));self.assertTrue(corrections.void_info(c,b['document_id']))
