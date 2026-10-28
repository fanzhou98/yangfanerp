import copy,json,unittest
import test_workflow as fixture
import business_reset as reset,inventory,erp_access,statements,assets,uuid

erp=fixture.erp
class BusinessResetTests(unittest.TestCase):
    setUp=fixture.WorkflowTests.setUp
    tearDown=fixture.WorkflowTests.tearDown
    day='2030-01-05'
    def order(self,day=None,cid='C001'):
        return erp.mutate('order',{'customer_id':cid,'business_date':day or self.day,'batch':'清理测试','lines':[{'product_id':'P001','ordered_qty':'2','actual_qty':'2','price':'3','driver':[],'customer':[]}]},'会计')
    def call(self,b,role='管理员'):
        with erp.connect(True) as c:return reset.save(c,b,role,erp.now,erp.audit)
    def preview(self,scope='orders'):
        return self.call({'action':'preview','business_date':self.day,'scope':scope})
    def execute(self,v,**extra):return self.call({'action':'archive','business_date':self.day,'scope':v['scope'],'fingerprint':v['fingerprint'],'confirm_date':self.day,'test_data_confirmed':True,'reason':'首日测试数据重新录入',**extra})
    def test_only_selected_orders_removed_masters_and_other_days_preserved_restore(self):
        a=self.order();b=self.order('2030-01-06','C002')
        with erp.connect() as c:before=reset.snapshot(c);masters={t:[dict(r) for r in c.execute('select * from '+t)] for t in reset.PROTECTED}
        v=self.preview();self.assertEqual(v['order_ids'],[a['id']]);r=self.execute(v)
        with erp.connect() as c:
            self.assertNotIn(a['id'],[x['id'] for x in reset.snapshot(c)['orders']]);self.assertIn(b['id'],[x['id'] for x in reset.snapshot(c)['orders']]);self.assertEqual(masters,{t:[dict(r) for r in c.execute('select * from '+t)] for t in reset.PROTECTED})
        self.call({'action':'restore','id':r['id'],'confirm_date':self.day})
        with erp.connect() as c:self.assertEqual(reset.stable_snapshot(before),reset.stable_snapshot(reset.snapshot(c)))
    def test_admin_only_preview_and_execution(self):
        for role in ('会计','出纳','库管'):
            with self.assertRaisesRegex(ValueError,'仅允许管理员'):self.call({'action':'preview','business_date':self.day},role)
        with self.assertRaises(Exception):erp_access.authorize_authenticated('/api/business-reset',{},'会计')
    def test_fingerprint_not_just_row_count_and_date_confirmation(self):
        o=self.order();v=self.preview();o['note']='另一个页面刚修改';erp.mutate('order',o,'会计',o['id'])
        with self.assertRaisesRegex(ValueError,'重新预览'):self.execute(v)
        v=self.preview()
        for x in ({'test_data_confirmed':False},{'confirm_date':'2030-01-06'}):
            with self.assertRaises(ValueError):self.execute(v,**x)
        self.assertEqual(len(self.preview()['order_ids']),1)
    def test_new_business_prevents_restore_and_stale_epoch_is_rejected(self):
        self.order();r=self.execute(self.preview())
        with self.assertRaisesRegex(ValueError,'旧页面'):erp.mutate('order',{'customer_id':'C001','business_date':self.day,'lines':[]},'会计')
        self.order_with_epoch=r['business_data_epoch']
        erp.mutate('order',{'_data_epoch':r['business_data_epoch'],'customer_id':'C002','business_date':self.day,'batch':'重新录入','lines':[{'product_id':'P001','ordered_qty':'1','actual_qty':'0','price':'3','driver':[],'customer':[]}]},'会计')
        with self.assertRaisesRegex(ValueError,'不能覆盖恢复'):self.call({'action':'restore','id':r['id'],'confirm_date':self.day})
    def test_whole_day_removes_daily_counts_not_asset_or_mapping_and_preserves_config(self):
        self.order()
        with erp.connect(True) as c:
            c.execute('INSERT INTO asset_records VALUES(?,?,?)',('TEST-COUNT','TEST-COUNT',json.dumps({'id':'TEST-COUNT','kind':'count','business_date':self.day,'asset_id':'P-LARGE','empty_qty':20,'damaged_qty':0,'version':1})))
            c.execute('INSERT INTO stock_closings VALUES(?,?)',(self.day,json.dumps({'business_date':self.day,'state':'closed','version':1,'products':[]})))
        self.assertTrue(self.preview()['blockers']);v=self.preview('day');self.assertFalse(v['blockers']);self.execute(v)
        with erp.connect() as c:
            self.assertIsNone(c.execute('select * from stock_closings where business_date=?',(self.day,)).fetchone());self.assertIsNotNone(c.execute("select * from asset_records where id='CR-WHITE'").fetchone());self.assertIsNone(c.execute("select * from asset_records where id='TEST-COUNT'").fetchone())
    def test_later_closing_carry_and_material_fifo_block_full_day(self):
        self.order()
        with erp.connect(True) as c:c.execute('INSERT INTO warehouse_plans VALUES(?,?)',('2030-01-06',json.dumps({'business_date':'2030-01-06','opening_source_date':self.day,'version':1,'stock':[]})))
        v=self.preview('day');self.assertTrue(any('结转' in x for x in v['blockers']))
        with self.assertRaisesRegex(ValueError,'结转'):self.execute(v)
    def test_receipt_from_other_order_day_is_not_deleted_or_detached(self):
        o=self.order('2030-01-04')
        with erp.connect(True) as c:c.execute('INSERT INTO receipts VALUES(?,?)',('R-CROSS',json.dumps({'id':'R-CROSS','order_id':o['id'],'customer_id':'C001','received_date':self.day,'amount_cents':100})))
        v=self.preview();self.assertTrue(v['empty']);v=self.preview('day');self.assertTrue(any('收款关联其他日期' in x for x in v['blockers']))
    def test_related_cash_receipt_and_issued_statement_void_restore_together(self):
        o=self.order();o['lines'][0]['driver']=[{'gross':'20','count':'2','tare':'1.8'}];o=erp.mutate('order',o,'会计',o['id']);o=erp.mutate('settle',{'version':o['version'],'mode':'driver'},'会计',o['id']);o=erp.mutate('review',{'version':o['version'],'evidence_checked':True},'出纳',o['id']);o=erp.mutate('receipt',{'version':o['version'],'amount':'1','received_date':'2026-10-18','method':'现金'},'出纳',o['id'])
        with erp.connect(True) as c:
            snap=statements.snapshot(c,'C001',self.day,erp.now());doc=statements.issue(c,{'request_key':str(uuid.uuid4()),'customer_id':'C001','business_date':self.day,'seller_name':'测试工厂','buyer_name':'测试客户','operator':'出纳','identity_checked':True,'source_fingerprint':snap['source_fingerprint']},'管理员',erp.now,erp.audit)
        v=self.preview();self.assertIn(doc['document_id'],v['document_ids']);self.assertEqual(v['counts']['receipts'],1);r=self.execute(v)
        with erp.connect() as c:self.assertTrue(statements.get_document(c,doc['document_id'])['voided']);self.assertIsNone(c.execute('select * from orders where id=?',(o['id'],)).fetchone())
        self.call({'action':'restore','id':r['id'],'confirm_date':self.day})
        with erp.connect() as c:self.assertFalse(statements.get_document(c,doc['document_id']).get('voided',False));self.assertEqual(erp.get_order(c,o['id'])['paid_cents'],100)
    def test_closed_cost_month_and_later_material_inventory_are_protected(self):
        self.order()
        with erp.connect(True) as c:
            c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2030-01',1,json.dumps({'month':'2030-01','state':'closed'})))
        self.assertTrue(any('成本月结' in x for x in self.preview('day')['blockers']))
        with erp.connect(True) as c:
            c.execute('DELETE FROM resource_periods')
            for key,day in [('B-1',self.day),('B-2','2030-01-06')]:c.execute('INSERT INTO material_entries VALUES(?,?,?)',(key,key,json.dumps({'id':key,'business_date':day,'material_id':'RM-SOY','kind':'receipt','qty':'1'})))
        self.assertTrue(any('原料库存和成本断账' in x for x in self.preview('day')['blockers']))
    def test_master_edits_survive_restoration(self):
        self.order();r=self.execute(self.preview())
        with erp.connect(True) as c:
            c.execute("update customers set phone='12345' where id='C001'")
            a=next(x for x in assets.rows(c) if x['id']=='CR-WHITE');assets.save(c,'asset',{'request_key':str(uuid.uuid4()),'id':a['id'],'version':a['version'],'category':'周转筐','name':'白框改名'},'管理员',erp.now,erp.audit)
        self.call({'action':'restore','id':r['id'],'confirm_date':self.day})
        with erp.connect() as c:
            self.assertEqual(c.execute("select phone from customers where id='C001'").fetchone()[0],'12345');self.assertEqual(next(x for x in assets.rows(c) if x['id']=='CR-WHITE')['name'],'白框改名')
