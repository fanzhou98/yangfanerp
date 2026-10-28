import copy,unittest,uuid
import test_workflow as workflow
import test_inventory as inventory_tests
import inventory as inv
erp=workflow.erp
class WorkflowHandoffTests(unittest.TestCase):
    setUp=inventory_tests.InventoryTests.setUp
    tearDown=inventory_tests.InventoryTests.tearDown
    order=workflow.WorkflowTests.order
    settle=workflow.WorkflowTests.settle
    review=workflow.WorkflowTests.review
    ops=inventory_tests.InventoryTests.ops
    ret=inventory_tests.InventoryTests.ret
    act=inventory_tests.InventoryTests.act
    account=inventory_tests.InventoryTests.account
    snapshot=inventory_tests.InventoryTests.snapshot
    plan=inventory_tests.InventoryTests.plan
    close_day=inventory_tests.InventoryTests.close_day
    def confirm(self,o,**changes):return erp.mutate('confirm-weight',{'version':o['version'],'evidence_checked':True,**changes},'库管',o['id'])
    def test_explicit_weight_handoff_and_price_only_revision(self):
        o=self.order();o=erp.mutate('order',{**o,'workflow_version':1},'库管',o['id']);self.assertEqual(o['status'],'待确认称重')
        with self.assertRaisesRegex(ValueError,'先确认司机照片'):self.settle(o)
        with self.assertRaisesRegex(ValueError,'勾选确认'):self.confirm(o,evidence_checked=False)
        confirmed=self.confirm(o);self.assertEqual(confirmed['status'],'待算票');self.assertIsNotNone(confirmed['weight_confirmation'])
        with self.assertRaisesRegex(ValueError,'无需重复'):self.confirm(confirmed)
        changed=copy.deepcopy(confirmed);changed['lines'][0]['price']='4';changed=erp.mutate('order',changed,'会计',changed['id']);self.assertEqual(changed['weight_confirmation'],confirmed['weight_confirmation'])
        billed=self.settle(changed);self.assertEqual(billed['state'],'ready')
        reviewed=self.review(billed);self.assertEqual(reviewed['state'],'reviewed')
    def test_weight_or_actual_edit_requires_reconfirmation(self):
        o=self.confirm(self.order());o['lines'][0]['driver'][0]['gross']='111';changed=erp.mutate('order',o,'库管',o['id']);self.assertIsNone(changed['weight_confirmation'])
        with self.assertRaisesRegex(ValueError,'先确认司机照片'):self.settle(changed)
        changed=self.confirm(changed);self.settle(changed)
    def test_incomplete_handoff_and_roles_and_stale_versions(self):
        o=self.order();bad=copy.deepcopy(o);bad['lines'][0]['driver']=bad['lines'][0]['driver'][:1];bad['lines'][0]['customer']=[];bad=erp.mutate('order',bad,'库管',o['id'])
        with self.assertRaises(erp.ValidationError):self.confirm(bad)
        with self.assertRaises(ValueError):erp.mutate('confirm-weight',{'version':bad['version'],'evidence_checked':True},'出纳',bad['id'])
        with self.assertRaises(ValueError):self.confirm(o)
        self.assertIsNone(erp.bootstrap()['orders'][0]['weight_confirmation'])
    def test_unsaved_weight_and_handoff_commit_as_one_transaction(self):
        a=self.order();b=self.order();update=copy.deepcopy(a);update['lines'][0]['driver'][0]['gross']='111'
        invalid=copy.deepcopy(b);invalid['lines'][0]['driver']=invalid['lines'][0]['driver'][:1];invalid['lines'][0]['customer']=[]
        operations=[{'action':'confirm-weight','order_id':o['id'],'body':{'version':o['version'],'evidence_checked':True},'update':v} for o,v in [(a,update),(b,invalid)]]
        with self.assertRaises(erp.ValidationError):erp.batch_mutate({'operations':operations},'库管')
        saved={o['id']:o for o in erp.bootstrap()['orders']};self.assertEqual(saved[a['id']]['version'],a['version']);self.assertIsNone(saved[a['id']].get('weight_confirmation'))
        result=erp.batch_mutate({'operations':operations[:1]},'库管');self.assertIsNotNone(result['orders'][0]['weight_confirmation']);self.assertEqual(result['orders'][0]['lines'][0]['driver'][0]['gross'],'111')
    def test_merchant_disposal_is_financial_only_and_not_quarantine(self):
        revision=erp.bootstrap()['inventory_revision'];r=self.ret(receipt_mode='merchant_disposed',source_code='merchant_confirmed',reason_code='quality',source_note='',reason='')
        self.assertEqual(erp.bootstrap()['inventory_revision'],revision);self.assertEqual(self.snapshot()['products'][0]['quarantine_kg'],'0');self.assertEqual(inv.remaining_return(r),(0,0));self.assertEqual(r['source_note'],'商户处置确认')
        r=self.account(r);r=self.act(r,'review','出纳',evidence_checked=True);self.assertEqual(r['finance']['amount_cents'],3333)
        with self.assertRaisesRegex(ValueError,'自行处置'):self.act(r,'dispose','库管',business_date='2026-10-21',kind='destroy',qty='1',net_kg='10',handler='甲',note='重复')
    def test_return_selector_checks_latest_original_and_structured_choices(self):
        o=self.order();r=self.ret(order_id=o['id'],expected_order_version=o['version'],source_date=o['business_date'],source_code='sale_order',reason_code='damaged')
        self.assertEqual(r['source_price'],'3.333');self.assertEqual(r['reason_code'],'damaged')
        with self.assertRaisesRegex(ValueError,'已变化'):self.ret(order_id=o['id'],expected_order_version=o['version']-1)
        with self.assertRaisesRegex(ValueError,'送货日期'):self.ret(order_id=o['id'],source_date='2026-10-17')
        with self.assertRaisesRegex(ValueError,'选项无效'):self.ret(reason_code='bad')
        with self.assertRaisesRegex(ValueError,'补充说明'):self.ret(source_code='other')
        with self.assertRaisesRegex(ValueError,'补充说明'):self.ret(reason_code='other')
