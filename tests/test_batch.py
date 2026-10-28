import unittest
import test_workflow as workflow
erp=workflow.erp

class BatchTests(unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    order=workflow.WorkflowTests.order
    settle=workflow.WorkflowTests.settle
    review=workflow.WorkflowTests.review
    def test_batch_creates_one_order_per_customer_with_all_products(self):
        lines=[{'product_id':pid,'ordered_qty':qty,'actual_qty':'0','price':price,'driver':[],'customer':[]} for pid,qty,price in [('P001','10','3.6'),('P003','8','6.2'),('P004','5','75')]]
        result=erp.batch_mutate({'operations':[{'action':'order','body':{'customer_id':cid,'business_date':'2026-10-18','batch':'总表','lines':lines}} for cid in ['C001','C002']]},'库管')
        self.assertEqual(result['count'],2)
        for o in result['orders']:self.assertEqual(len(o['lines']),3)
    def test_invalid_customer_rolls_back_all_creates_and_audit(self):
        before=erp.bootstrap();payload={'customer_id':'C001','business_date':'2026-10-18','batch':'原子批量','lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'0','price':'75','driver':[],'customer':[]}]}
        with self.assertRaises(ValueError):erp.batch_mutate({'operations':[{'action':'order','body':payload},{'action':'order','body':{**payload,'customer_id':'MISSING'}}]},'库管')
        after=erp.bootstrap();self.assertEqual(after['orders'],before['orders']);self.assertEqual(after['audit'],before['audit'])
    def test_update_and_customer_settlement_are_one_transaction(self):
        o=self.order();edit={**o,'note':'总表修改'};edit['lines'][0]['price']='4'
        result=erp.batch_mutate({'operations':[{'action':'settle','order_id':o['id'],'update':edit,'body':{'version':o['version'],'mode':'customer'}}]},'会计')['orders'][0]
        self.assertEqual(result['state'],'ready');self.assertEqual(result['total_cents'],80400);self.assertEqual(result['version'],o['version']+2)
    def test_failed_settlement_restores_original_weight_and_version(self):
        o=self.order();edit={**o,'note':'不应该被保存'};edit['lines'][0]['customer'][0]['count']='9'
        with self.assertRaises(ValueError):erp.batch_mutate({'operations':[{'action':'settle','order_id':o['id'],'update':edit,'body':{'version':o['version'],'mode':'customer'}}]},'会计')
        current=next(x for x in erp.bootstrap()['orders'] if x['id']==o['id'])
        self.assertEqual(current['note'],'测试');self.assertEqual(current['version'],1);self.assertEqual(current['lines'][0]['customer'][0]['count'],'10')
    def test_one_customer_multiple_orders_settled_and_reviewed_together(self):
        orders=[self.order(),self.order('P004')]
        ready=erp.batch_mutate({'operations':[{'action':'settle','order_id':o['id'],'body':{'version':o['version'],'mode':'customer'}} for o in orders]},'会计')['orders']
        result=erp.batch_mutate({'operations':[{'action':'review','order_id':o['id'],'body':{'version':o['version'],'evidence_checked':True}} for o in ready]},'出纳')
        self.assertEqual(result['count'],2);self.assertTrue(all(o['state']=='reviewed' for o in result['orders']))
    def test_products_can_use_different_settlement_bases(self):
        o=self.order();line={**o['lines'][0],'product_id':'P003','price':'6.2'};o['lines'].append(line)
        o=erp.mutate('order',o,'会计',o['id'])
        o=self.settle(o,line_modes={'P001':'customer','P003':'agreed'},agreed={'P003':'200'},reason='豆干电话确认200公斤，豆腐接受复称')
        self.assertEqual(o['settlement']['mode'],'mixed');self.assertEqual(o['lines'][0]['bill_qty'],'201');self.assertEqual(o['lines'][1]['bill_qty'],'200')
        self.assertEqual(o['lines'][1]['driver_net'],'204');self.assertEqual(o['lines'][1]['customer_net'],'201')
        self.assertEqual(o['total_cents'],66993+124000)
    def test_stale_order_prevents_partial_client_submission(self):
        a=self.order();b=self.order('P004');self.settle(b)
        with self.assertRaises(ValueError):erp.batch_mutate({'operations':[{'action':'settle','order_id':o['id'],'body':{'version':o['version'],'mode':'customer'}} for o in [a,b]]},'会计')
        current=next(x for x in erp.bootstrap()['orders'] if x['id']==a['id']);self.assertEqual(current['state'],'dispatched')
    def test_duplicate_operations_and_wrong_role_are_rejected(self):
        o=self.order();item={'action':'settle','order_id':o['id'],'body':{'version':o['version'],'mode':'customer'}}
        with self.assertRaises(ValueError):erp.batch_mutate({'operations':[item,item]},'会计')
        with self.assertRaises(ValueError):erp.batch_mutate({'operations':[item]},'库管')

if __name__=='__main__':unittest.main(verbosity=2)
