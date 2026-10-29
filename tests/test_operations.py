import unittest,copy
import test_workflow as workflow
from printing import order_print_html
erp=workflow.erp

class OperationsTests(unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    def fleet(self,kind,action,row=None,**extra):
        if kind=='vehicle' and 'vehicle_type' not in extra:extra['vehicle_type']='测试车'
        return erp.fleet_master({'kind':kind,'action':action,**({'id':row['id'],'expected':{'name':row['name'],'active':row['active']}} if row else {}),**extra},'库管')
    def plan(self,driver,day='2026-10-19'):
        return {'business_date':day,'version':0,'trips':[{'id':'T1','name':'测试趟次','period':'下午','vehicle_id':'V001','driver_id':driver['id'],'driver':driver['name']}], 'assignments':[{'market_id':'M001','trip_id':'T1','sequence':1}]}
    def test_vehicle_and_driver_crud_with_recovery_and_conflict(self):
        for kind in ['vehicle','driver']:
            row=self.fleet(kind,'create',name='测试'+kind)
            changed=self.fleet(kind,'update',row,name='改名'+kind)
            with self.assertRaises(ValueError):self.fleet(kind,'delete',row)
            deleted=self.fleet(kind,'delete',changed);self.assertEqual(deleted['active'],0)
            restored=self.fleet(kind,'restore',deleted);self.assertEqual(restored['active'],1)
            self.assertEqual(restored['id'],row['id'])
            with self.assertRaises(ValueError):self.fleet(kind,'create',name=restored['name'])
        with self.assertRaises(ValueError):erp.fleet_master({'kind':'driver','action':'create','name':'越权'},'出纳')
    def test_deleted_catalogs_preserve_history_but_cannot_be_newly_assigned(self):
        driver=self.fleet('driver','create',name='原司机')
        plan=erp.save_dispatch(self.plan(driver),'库管')
        vehicle=next(v for v in erp.bootstrap()['delivery_vehicles'] if v['id']=='V001')
        vehicle=self.fleet('vehicle','update',vehicle,name='新车名')
        driver=self.fleet('driver','update',driver,name='新司机名')
        vehicle=self.fleet('vehicle','delete',vehicle);driver=self.fleet('driver','delete',driver)
        saved=erp.save_dispatch({**self.plan(driver),'version':1},'库管')
        self.assertEqual(saved['trips'][0]['driver'],'原司机');self.assertEqual(saved['trips'][0]['vehicle_name'],'车 A')
        with self.assertRaises(ValueError):erp.save_dispatch(self.plan(driver,'2026-10-20'),'库管')
        self.fleet('vehicle','restore',vehicle);driver=self.fleet('driver','restore',driver)
        new=erp.save_dispatch(self.plan(driver,'2026-10-20'),'库管');self.assertEqual(new['trips'][0]['driver'],'新司机名')
    def test_multiple_drivers_per_trip_and_legacy_name_import(self):
        a=self.fleet('driver','create',name='司机甲');b=self.fleet('driver','create',name='司机乙')
        body=self.plan(a);body['trips'][0]['driver_ids']=[a['id'],b['id']]
        saved=erp.save_dispatch(body,'库管');self.assertEqual(saved['trips'][0]['driver'],'司机甲、司机乙')
        self.assertEqual(saved['trips'][0]['driver_ids'],[a['id'],b['id']])
        body['version']=1;body['trips'][0]['driver_ids']=[a['id'],a['id']]
        with self.assertRaises(ValueError):erp.save_dispatch(body,'库管')
        with erp.connect(True) as c:
            import json
            legacy={'business_date':'2026-10-17','version':1,'trips':[{'id':'OLD','driver':'历史甲，历史乙'}],'assignments':[]}
            c.execute('INSERT INTO dispatch_plans VALUES(?,?)',(legacy['business_date'],json.dumps(legacy)))
            c.execute("DELETE FROM meta WHERE key='driver_catalog_initialized'");c.execute("DELETE FROM schema_migrations WHERE id='045-driver-catalog'")
        erp.init_db();d=erp.bootstrap();self.assertTrue({'历史甲','历史乙'}<={r['name'] for r in d['delivery_drivers']})
        self.assertEqual(next(p for p in d['dispatch_plans'] if p['business_date']=='2026-10-17'),legacy)
    def print_data(self):
        erp.master({'kind':'customer','id':'C001','name':'配送验证客户','route':'新联'},'会计')
        erp.master({'kind':'customer','id':'C003','name':'自提验证客户','route':'五彩湾','delivery_method':'pickup'},'会计')
        for cid,qty in [('C001','2'),('C002','1'),('C003','3')]:
            erp.mutate('order',{'customer_id':cid,'business_date':'2026-10-19','batch':'打印验证','lines':[{'product_id':'P004','ordered_qty':qty,'actual_qty':'0','price':'75','driver':[],'customer':[]}]},'库管')
        driver=self.fleet('driver','create',name='打印司机');erp.save_dispatch(self.plan(driver),'库管')
        return erp.bootstrap()
    def test_grouped_print_includes_pickup_unassigned_and_handwritten_fields(self):
        d=self.print_data();html=order_print_html(d,{'date':['2026-10-19'],'mode':['grouped'],'document':['order']},erp.now())
        for value in ['测试趟次','客户自取','配送验证客户','自提验证客户','待排车 / 待匹配市场','客户 × 产品数量','版本','打印 / 保存为 PDF']:self.assertIn(value,html)
        for removed in ['<th>筐数</th>','单筐皮重 kg','净重 kg']:self.assertNotIn(removed,html)
        self.assertIn('quantity-matrix',html)
        trip=order_print_html(d,{'date':['2026-10-19'],'mode':['trip'],'trip':['T1'],'document':['order']},erp.now())
        self.assertIn('配送验证客户',trip);self.assertNotIn('自提验证客户',trip)
        total=order_print_html(d,{'date':['2026-10-19'],'mode':['total'],'document':['order']},erp.now());self.assertIn('配送验证客户',total);self.assertIn('自提验证客户',total)
    def test_print_escapes_names_and_validates_dates(self):
        d=self.print_data();d['orders'][0]['customer_name']='<script>alert(1)</script>'
        next(c for c in d['customers'] if c['id']==d['orders'][0]['customer_id'])['name']='<script>alert(1)</script>'
        html=order_print_html(d,{'date':['2026-10-19'],'mode':['total'],'document':['order']},erp.now())
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(1)',html)
        for query in [{'date':['2026-02-30']},{'date':['2026-10-19'],'mode':['unknown']},{'date':['2026-10-19'],'mode':['trip'],'trip':['NO']}]:
            with self.assertRaises(ValueError):order_print_html(d,query,erp.now())
