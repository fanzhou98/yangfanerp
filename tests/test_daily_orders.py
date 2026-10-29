import copy,unittest
import test_workflow as workflow
erp=workflow.erp
from printing import order_print_html

class DailyOrderTests(unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    def make(self,batch,actual='0',daily=False):
        return erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-20','batch':batch,'daily_order':daily,'lines':[{'product_id':'P001','ordered_qty':'2','actual_qty':actual,'price':'3','driver':[],'customer':[]}]},'会计')
    def test_daily_new_order_rejects_duplicate_across_old_batches(self):
        o=self.make('旧批次')
        with self.assertRaisesRegex(ValueError,'当天已有订货'):self.make('日常订货',daily=True)
        b={**o,'lines':[{**o['lines'][0],'ordered_qty':'3'}]};saved=erp.mutate('order',b,'会计',o['id']);self.assertEqual(saved['lines'][0]['ordered_qty'],'3')
    def test_duplicate_archive_is_recoverable_and_keeps_shipped_original(self):
        keep=self.make('原批次','1');duplicate=self.make('重复批次')
        body={'action':'archive','id':duplicate['id'],'kept_id':keep['id'],'version':duplicate['version'],'reason':'用户核对为重复试填'}
        with self.assertRaises(ValueError):erp.duplicate_order_archive(body,'库管')
        erp.duplicate_order_archive(body,'会计');d=erp.bootstrap()
        with erp.connect() as c:archived=c.execute('SELECT payload FROM archived_orders ORDER BY archived_at DESC LIMIT 1').fetchone()
        self.assertNotIn(duplicate['id'],[o['id'] for o in d['orders']]);self.assertEqual(__import__('json').loads(archived['payload'])['id'],duplicate['id'])
        self.assertEqual(next(o for o in d['orders'] if o['id']==keep['id'])['lines'][0]['actual_qty'],'1')
        erp.duplicate_order_archive({'action':'restore','id':duplicate['id']},'会计');self.assertIn(duplicate['id'],[o['id'] for o in erp.bootstrap()['orders']])
        with self.assertRaises(ValueError):erp.duplicate_order_archive({'action':'archive','id':keep['id'],'kept_id':duplicate['id'],'version':keep['version'],'reason':'不能移除已有实发'},'会计')
    def test_archive_rejects_different_quantity_and_stale_version(self):
        keep=self.make('原批次');duplicate=self.make('重复批次')
        body={'action':'archive','id':duplicate['id'],'kept_id':keep['id'],'version':99,'reason':'核对重复'}
        with self.assertRaises(ValueError):erp.duplicate_order_archive(body,'会计')
        keep=erp.mutate('order',{**keep,'lines':[{**keep['lines'][0],'ordered_qty':'3'}]},'会计',keep['id'])
        with self.assertRaises(ValueError):erp.duplicate_order_archive({**body,'version':duplicate['version']},'会计')
    def test_archive_many_rolls_back_if_one_order_has_changed(self):
        keep=self.make('原单');a=self.make('重复一');b=self.make('重复二')
        rows=[{'id':o['id'],'kept_id':keep['id'],'version':o['version'],'reason':'已确认重复'} for o in [a,b]]
        rows[1]['version']=99
        with self.assertRaises(ValueError):erp.duplicate_order_archive({'action':'archive_many','orders':rows},'会计')
        d=erp.bootstrap()
        with erp.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM archived_orders').fetchone()[0],0)
        self.assertTrue({a['id'],b['id']}<={o['id'] for o in d['orders']})
    def test_print_combines_same_client_and_obeys_selected_order_ids(self):
        a=self.make('甲');b=self.make('乙');d=erp.bootstrap();c=next(c for c in d['customers'] if c['id']=='C001')
        d['orders']=[o for o in d['orders'] if o['id'] in (a['id'],b['id'])];h=order_print_html(d,{'date':['2026-10-20'],'mode':['total'],'document':['order']},erp.now());self.assertEqual(h.count('data-order-ids='),1);self.assertIn('data-quantity="4"',h);self.assertIn(a['id'],h);self.assertIn(b['id'],h)
        h=order_print_html(d,{'date':['2026-10-20'],'mode':['total'],'document':['order'],'scope':['sheet'],'order_id':[b['id']]},erp.now());self.assertIn('data-quantity="2"',h);self.assertNotIn(a['id'],h);self.assertIn('订货表当前筛选',h)
        h=order_print_html(d,{'date':['2026-10-20'],'mode':['total'],'document':['order'],'scope':['sheet']},erp.now());self.assertNotIn(a['id'],h);self.assertIn('没有符合条件',h)
