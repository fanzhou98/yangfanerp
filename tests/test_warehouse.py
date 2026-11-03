import copy,unittest
import test_workflow as workflow
from printing import order_print_html
erp=workflow.erp

class WarehouseTests(unittest.TestCase):
    def setUp(self):
        workflow.WorkflowTests.setUp(self)
        # Each allocation case owns its orders, independent of the seed's current date.
        with erp.connect(True) as c:
            c.execute('DELETE FROM receipts');c.execute('DELETE FROM orders')
    tearDown=workflow.WorkflowTests.tearDown
    def create(self,cid='C001',qty='8'):
        return erp.mutate('order',{'customer_id':cid,'business_date':'2026-10-21','batch':'日常订货','lines':[{'product_id':'P001','ordered_qty':qty,'actual_qty':'0','price':'3','driver':[],'customer':[]}]},'库管')
    def body(self,orders,stock='10',qty='5'):
        return {'business_date':'2026-10-21','version':0,'stock':[{'product_id':'P001','existing_qty':stock,'produced_qty':'2'}],
                'order_versions':{o['id']:o['version'] for o in orders},
                'allocations':[{'order_id':o['id'],'product_id':'P001','qty':qty,'ordered_qty':o['lines'][0]['ordered_qty']} for o in orders],
                'customers':[{'customer_id':o['customer_id'],'priority':'重点','note':'库管自主分配'} for o in orders]}
    def test_manual_partial_allocation_preserves_demand_and_actual(self):
        a=self.create();b=self.create('C002');payload=self.body([a,b]);plan=erp.save_warehouse(payload,'库管')
        self.assertNotIn('priority',plan['customers'][0]);self.assertEqual(plan['version'],1);self.assertEqual([a['qty'] for a in plan['allocations']],['5','5'])
        data=erp.bootstrap();self.assertEqual(data['warehouse_plans'],[plan])
        self.assertEqual([(l['ordered_qty'],l['actual_qty']) for o in data['orders'] if o['business_date']=='2026-10-21' for l in o['lines']],[('8','0'),('8','0')])
        html=order_print_html(data,{'date':['2026-10-21'],'mode':['total'],'document':['order']},erp.now());self.assertEqual(html.count('data-quantity="8"'),2);self.assertNotIn('毛重 kg',html)
        erp.init_db();self.assertEqual(erp.bootstrap()['warehouse_plans'],[plan])
    def test_overallocated_and_unknown_stock_roll_back(self):
        a=self.create();b=self.create('C002');body=self.body([a,b],stock='0')
        with self.assertRaisesRegex(ValueError,'超过可用库存'):erp.save_warehouse(body,'库管')
        body['stock'][0]['existing_qty']=''
        with self.assertRaisesRegex(ValueError,'尚未盘点'):erp.save_warehouse(body,'库管')
        self.assertEqual(erp.bootstrap()['warehouse_plans'],[])
    def test_zero_and_partial_plan_do_not_invent_shipment(self):
        a=self.create();body=self.body([a],stock='',qty='0');saved=erp.save_warehouse(body,'库管')
        self.assertEqual(saved['stock'][0]['existing_qty'],'');self.assertEqual(saved['allocations'][0]['qty'],'0')
        self.assertEqual(next(o for o in erp.bootstrap()['orders'] if o['id']==a['id'])['state'],'draft')
    def test_snapshot_and_version_conflicts(self):
        a=self.create();body=self.body([a]);erp.save_warehouse(body,'库管')
        with self.assertRaisesRegex(ValueError,'库存分配已修改'):erp.save_warehouse(body,'库管')
        body['version']=1;new=erp.mutate('order',{**a,'lines':[{**a['lines'][0],'ordered_qty':'7'}]},'库管',a['id'])
        with self.assertRaisesRegex(ValueError,'订货或实发已有变化'):erp.save_warehouse(body,'库管')
        body['order_versions'][a['id']]=new['version']
        with self.assertRaisesRegex(ValueError,'订货已变化'):erp.save_warehouse(body,'库管')
        body['allocations'][0]['ordered_qty']='7';erp.save_warehouse(body,'库管')
    def test_new_orders_require_refresh(self):
        a=self.create();body=self.body([a]);self.create('C002')
        with self.assertRaisesRegex(ValueError,'订货或实发已有变化'):erp.save_warehouse(body,'库管')
    def test_invalid_quantities_scope_and_duplicates(self):
        a=self.create();base=self.body([a])
        for qty in ['9','-1','NaN','1.25',True]:
            b=copy.deepcopy(base);b['allocations'][0]['qty']=qty
            with self.assertRaises(ValueError):erp.save_warehouse(b,'库管')
        for field in ['stock','allocations','customers']:
            b=copy.deepcopy(base);b[field].append(copy.deepcopy(b[field][0]))
            with self.assertRaises(ValueError):erp.save_warehouse(b,'库管')
        b=copy.deepcopy(base);b['allocations'][0]['order_id']='unknown'
        with self.assertRaises(ValueError):erp.save_warehouse(b,'库管')
        with self.assertRaises(ValueError):erp.save_warehouse(base,'出纳')
        with self.assertRaises(ValueError):erp.save_warehouse({**base,'_data_epoch':'old'},'库管')
    def test_archive_and_restore_include_inventory_plans(self):
        a=self.create();plan=erp.save_warehouse(self.body([a]),'库管');data=erp.bootstrap()
        with erp.connect() as c:archived_count=c.execute('SELECT COUNT(*) FROM archived_orders').fetchone()[0]
        counts={k:len(data[k]) for k in ['orders','receipts']}|{'archived_orders':archived_count}
        result=erp.trial_data({'action':'archive','reason':'测试归档','expected':counts},'会计')
        self.assertEqual(erp.bootstrap()['warehouse_plans'],[])
        erp.trial_data({'action':'restore','id':result['id'],'_data_epoch':result['business_data_epoch']},'会计')
        self.assertEqual(erp.bootstrap()['warehouse_plans'],[plan])
