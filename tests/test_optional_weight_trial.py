import copy,unittest
import test_workflow as workflow
erp=workflow.erp

class OptionalWeightTrialTests(unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    def draft(self,customer=None,driver=None,actual='2'):
        return {'customer_id':'C001','business_date':'2026-10-21','batch':'日常订货','lines':[{'product_id':'P001','ordered_qty':'2','actual_qty':actual,'price':'3','driver':driver or [],'customer':customer or []}]}
    def test_default_tare_placeholder_does_not_require_customer_reweigh(self):
        body=self.draft(customer=[{'gross':'','count':'2','tare':'1.8'}],driver=[{'gross':'24','count':'2','tare':'1.8'}])
        o=erp.mutate('order',body,'会计');self.assertEqual(o['lines'][0]['customer'],[])
        o=erp.mutate('settle',{'version':o['version'],'mode':'driver'},'会计',o['id']);self.assertEqual(o['lines'][0]['settlement_mode'],'driver');self.assertEqual(o['lines'][0]['bill_qty'],'20.4');self.assertEqual(o['total_cents'],6120)
        self.assertEqual(body['lines'][0]['customer'][0]['tare'],'1.8')
    def test_previously_saved_weight_cannot_be_silently_erased_as_placeholder(self):
        o=erp.mutate('order',self.draft(customer=[{'gross':'24','count':'2','tare':'1.8'}]),'会计');body=copy.deepcopy(o);body['lines'][0]['customer'][0]['gross']=''
        with self.assertRaises(erp.ValidationError):erp.mutate('order',body,'会计',o['id'])
    def test_no_weight_can_save_but_not_settle_and_selected_source_count_must_match(self):
        o=erp.mutate('order',self.draft(),'会计')
        for mode in ['driver','customer','agreed']:
            with self.assertRaises(erp.ValidationError):erp.mutate('settle',{'version':o['version'],'mode':mode,'agreed':{'P001':'20'},'reason':'测试'},'会计',o['id'])
        b={**o,'lines':[{**o['lines'][0],'driver':[{'gross':'12','count':'1','tare':'1.8'}]}]};o=erp.mutate('order',b,'会计',o['id'])
        with self.assertRaises(erp.ValidationError):erp.mutate('settle',{'version':o['version'],'mode':'driver'},'会计',o['id'])
    def test_trial_archive_preserves_master_data_restores_and_blocks_stale_clients(self):
        o=erp.mutate('order',self.draft(),'会计');before=erp.bootstrap()
        with erp.connect() as c:archived_count=c.execute('SELECT COUNT(*) FROM archived_orders').fetchone()[0]
        counts={'orders':len(before['orders']),'receipts':len(before['receipts']),'archived_orders':archived_count}
        with self.assertRaises(ValueError):erp.trial_data({'action':'archive','expected':counts,'reason':'测试'},'库管')
        with self.assertRaises(ValueError):erp.trial_data({'action':'archive','expected':{**counts,'orders':999},'reason':'测试'},'会计')
        r=erp.trial_data({'action':'archive','expected':counts,'reason':'用户要求清理试运行'},'会计');after=erp.bootstrap()
        self.assertEqual(after['orders'],[]);self.assertEqual(after['receipts'],[])
        for key in ['customers','products','rules','delivery_markets','delivery_vehicles','delivery_drivers','dispatch_plans']:self.assertEqual(before[key],after[key])
        with self.assertRaisesRegex(ValueError,'旧页面'):erp.mutate('order',self.draft(),'会计')
        epoch=r['business_data_epoch'];restored=erp.trial_data({'action':'restore','id':r['id'],'_data_epoch':epoch},'会计');d=erp.bootstrap()
        self.assertEqual(d['orders'],before['orders']);self.assertEqual(d['receipts'],before['receipts']);self.assertNotEqual(restored['business_data_epoch'],epoch)
    def test_trial_restore_cannot_overwrite_new_business(self):
        before=erp.bootstrap()
        with erp.connect() as c:archived_count=c.execute('SELECT COUNT(*) FROM archived_orders').fetchone()[0]
        counts={k:len(before[k]) for k in ['orders','receipts']}|{'archived_orders':archived_count};r=erp.trial_data({'action':'archive','expected':counts,'reason':'测试'},'会计')
        o=erp.mutate('order',{**self.draft(),'_data_epoch':r['business_data_epoch']},'会计')
        with self.assertRaisesRegex(ValueError,'不能覆盖'):erp.trial_data({'action':'restore','id':r['id'],'_data_epoch':r['business_data_epoch']},'会计')
        self.assertIn(o['id'],[x['id'] for x in erp.bootstrap()['orders']])
