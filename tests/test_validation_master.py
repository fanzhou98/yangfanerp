import unittest,copy
import test_workflow as workflow
erp=workflow.erp

class ValidationAndMasterTests(unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    order=workflow.WorkflowTests.order
    settle=workflow.WorkflowTests.settle
    def test_customer_expected_snapshot_prevents_parallel_overwrite(self):
        old=next(c for c in erp.bootstrap()['customers'] if c['id']=='C001')
        erp.master({'kind':'customer','id':old['id'],'route':old['route'],'name':'其他页面修改','expected':old},'会计')
        with self.assertRaisesRegex(ValueError,'已被其他页面修改'):
            erp.master({'kind':'customer','id':old['id'],'route':old['route'],'name':'旧页面修改','expected':old},'会计')
        self.assertEqual(next(c for c in erp.bootstrap()['customers'] if c['id']=='C001')['name'],'其他页面修改')
    def test_customer_price_reset_restores_product_default(self):
        erp.master({'kind':'rule','customer_id':'C001','product_id':'P001','price':'9.99','tare':'0'},'会计')
        self.assertTrue(any(r['customer_id']=='C001' and r['product_id']=='P001' for r in erp.bootstrap()['rules']))
        with self.assertRaises(ValueError):
            erp.master({'kind':'rule','customer_id':'C001','product_id':'P001','action':'reset','expected':{'price':'1','tare':'0'}},'会计')
        erp.master({'kind':'rule','customer_id':'C001','product_id':'P001','action':'reset','expected':{'price':'9.99','tare':'0'}},'会计')
        self.assertFalse(any(r['customer_id']=='C001' and r['product_id']=='P001' for r in erp.bootstrap()['rules']))
        with self.assertRaises(ValueError):
            erp.master({'kind':'rule','customer_id':'C001','product_id':'P001','action':'reset'},'会计')

    def test_kilogram_product_ignores_packaging_fields(self):
        erp.master({'kind':'product','create':True,'id':'KG1','name':'公斤测试','unit':'公斤','billing_unit':'公斤','price':'2','tare':'0','standard_kg':'10','default_average_kg':'12','main_material':'黄豆'},'会计')
        row=next(p for p in erp.bootstrap()['products'] if p['id']=='KG1')
        self.assertEqual(row['standard_kg'],'1');self.assertIsNone(row['default_average_kg']);self.assertEqual(row['tare'],'0')
        erp.master({'kind':'product','create':True,'id':'CR1','name':'筐测试','unit':'筐','billing_unit':'筐','price':'2','tare':'1.5','standard_kg':'8','default_average_kg':'20','main_material':'黄豆'},'会计')
        row=next(p for p in erp.bootstrap()['products'] if p['id']=='CR1')
        self.assertIsNone(row['standard_kg']);self.assertEqual(row['default_average_kg'],'20')
    def test_product_expected_snapshot_prevents_parallel_overwrite(self):
        old=next(p for p in erp.bootstrap()['products'] if p['id']=='P001')
        erp.master({'kind':'product',**old,'price':'4','expected':old},'会计')
        with self.assertRaisesRegex(ValueError,'已被其他页面修改'):
            erp.master({'kind':'product',**old,'price':'5','expected':old},'会计')
        self.assertEqual(next(p for p in erp.bootstrap()['products'] if p['id']=='P001')['price'],'4')
    def new_customer(self,**extra):
        return erp.master({'kind':'customer','create':True,'name':'新增客户','route':'新联市场','note':'测试',**extra},'会计')
    def test_customer_number_is_automatic_and_ignores_stale_preview(self):
        a=self.new_customer(id='C001');b=self.new_customer(id='C004')
        self.assertEqual((a['id'],b['id']),('C004','C005'))
        self.assertEqual(next(c['name'] for c in erp.bootstrap()['customers'] if c['id']=='C001'),'演示·乌鲁木齐一店')
        self.assertEqual(erp.bootstrap()['next_customer_id'],'C006')
    def test_customer_number_skips_existing_highest_and_preserves_edit_id(self):
        erp.master({'kind':'customer','id':'C009','name':'已有客户','route':'北园春'},'会计')
        self.assertEqual(self.new_customer()['id'],'C010')
        result=erp.master({'kind':'customer','create':False,'id':'C009','name':'改名客户','route':'北园春'},'会计')
        self.assertEqual(result['id'],'C009');self.assertEqual(erp.bootstrap()['next_customer_id'],'C011')
    def test_failed_customer_does_not_consume_number(self):
        with self.assertRaises(ValueError):self.new_customer(name=' ')
        self.assertEqual(self.new_customer()['id'],'C004')
        with self.assertRaises(ValueError):erp.master({'kind':'customer','create':False,'id':'C999','name':'不存在','route':'测试'},'会计')
    def test_simultaneous_customer_additions_are_unique_and_audited(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids=list(pool.map(lambda i:self.new_customer(name='并发客户'+str(i))['id'],range(8)))
        self.assertEqual(len(set(ids)),8)
        self.assertEqual(set(ids),{'C'+str(i).zfill(3) for i in range(4,12)})
        with erp.connect() as c:
            import json
            records=c.execute("SELECT entity,after_json FROM audit WHERE action='新增客户'").fetchall()
            self.assertEqual(len(records),8)
            self.assertTrue(all(entity==json.loads(raw)['id'] for entity,raw in records))
    def test_product_order_persists_without_changing_business_records(self):
        before=erp.bootstrap();ids=[p['id'] for p in before['products']];desired=ids[-1:]+ids[:-1]
        result=erp.save_product_order({'product_ids':desired,'expected':ids},'会计')
        self.assertEqual(result['product_ids'],desired)
        after=erp.bootstrap();self.assertEqual([p['id'] for p in after['products']],desired)
        for key in ['orders','receipts','rules','customers']:self.assertEqual(before[key],after[key])
        self.assertEqual({p['id']:p for p in before['products']},{p['id']:p for p in after['products']})
        erp.init_db();self.assertEqual([p['id'] for p in erp.bootstrap()['products']],desired)
    def test_product_order_rejects_missing_duplicate_unknown_and_stale_ids(self):
        ids=[p['id'] for p in erp.bootstrap()['products']]
        for desired in [ids[:-1],ids[:-1]+[ids[0]],ids[:-1]+['unknown'],[None]+ids[1:]]:
            with self.assertRaises(ValueError):erp.save_product_order({'product_ids':desired,'expected':ids},'会计')
        with self.assertRaises(ValueError):erp.save_product_order({'product_ids':ids[::-1],'expected':ids},'库管')
        erp.save_product_order({'product_ids':ids[::-1],'expected':ids},'会计')
        with self.assertRaises(ValueError):erp.save_product_order({'product_ids':ids,'expected':ids},'会计')
        self.assertEqual([p['id'] for p in erp.bootstrap()['products']],ids[::-1])
    def test_new_product_goes_last_and_edit_preserves_order(self):
        ids=[p['id'] for p in erp.bootstrap()['products']]
        erp.save_product_order({'product_ids':ids[::-1],'expected':ids},'会计')
        erp.master(self.product(id='A001'),'会计')
        desired=ids[::-1]+['A001'];self.assertEqual([p['id'] for p in erp.bootstrap()['products']],desired)
        erp.master(self.product(id='P001',create=False,name='新名称'),'会计')
        self.assertEqual([p['id'] for p in erp.bootstrap()['products']],desired)
        with self.assertRaises(ValueError):erp.save_product_order({'product_ids':ids[::-1],'expected':ids[::-1]},'会计')
    def test_pickup_requires_confirmation_weight_but_no_driver_weight(self):
        erp.master({'kind':'customer','id':'C001','create':False,'name':'自取客户','route':'五彩湾','delivery_method':'pickup'},'会计')
        o=self.order();o['lines'][0]['driver']=[]
        o=erp.mutate('order',o,'会计',o['id']);self.assertEqual(o['delivery_method'],'pickup')
        saved=self.settle(o);self.assertEqual(saved['total_cents'],66993)
        self.assertEqual(saved['lines'][0]['driver'],[])
        bad=self.order();bad['lines'][0]['driver']=[];bad['lines'][0]['customer']=[]
        bad=erp.mutate('order',bad,'会计',bad['id'])
        with self.assertRaises(erp.ValidationError) as caught:self.settle(bad)
        self.assertTrue(any(i.get('source')=='customer' for i in caught.exception.issues))
        self.assertFalse(any(i.get('source')=='driver' for i in caught.exception.issues))
    def test_delivery_customer_only_weight_and_snapshot_is_preserved(self):
        o=self.order();self.assertEqual(o['delivery_method'],'delivery')
        erp.master({'kind':'customer','id':'C001','name':'自取客户','route':'五彩湾','delivery_method':'pickup'},'会计')
        o['lines'][0]['driver']=[];o=erp.mutate('order',o,'会计',o['id'])
        self.assertEqual(o['delivery_method'],'delivery')
        settled=self.settle(o)
        self.assertEqual(settled['lines'][0]['settlement_mode'],'customer')
        self.assertEqual(settled['delivery_method'],'delivery')
    def test_customer_pickup_setting_rejects_invalid_choice(self):
        with self.assertRaises(ValueError):self.new_customer(delivery_method='unknown')
        self.assertEqual(self.new_customer(delivery_method='pickup')['id'],'C004')
    def five_products(self,confirmed=False):
        lines=[{'product_id':'P001','ordered_qty':'28','actual_qty':'28','price':'3.6','driver':[{'gross':'345','count':'28','tare':'1'}],'customer':[{'gross':'467','count':'28','tare':'1.8'}]},
               {'product_id':'P002','ordered_qty':'56','actual_qty':'54','price':'3.8','driver':[{'gross':'567','count':'54','tare':'1.8'}],'customer':[{'gross':'676','count':'54','tare':'1.8'}]},
               {'product_id':'P004','ordered_qty':'20','actual_qty':'20','price':'75','driver':[],'customer':[]},
               {'product_id':'P005','ordered_qty':'5','actual_qty':'0','price':'65','driver':[],'customer':[],'not_shipped':confirmed},
               {'product_id':'P006','ordered_qty':'2','actual_qty':'0','price':'8','driver':[],'customer':[],'not_shipped':confirmed}]
        return erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-19','batch':'复现零实发','lines':lines},'会计')
    def test_current_save_failure_identifies_both_unshipped_products(self):
        o=self.five_products()
        with self.assertRaises(erp.ValidationError) as caught:self.settle(o)
        flags=[i for i in caught.exception.issues if i['field']=='not_shipped']
        self.assertEqual({i['product_id'] for i in flags},{'P005','P006'})
        self.assertTrue(all(i['order_id']==o['id'] and i['customer_id']=='C001' for i in flags))
    def test_confirmed_unshipped_keeps_orders_and_bills_only_delivered(self):
        o=self.settle(self.five_products(True));self.assertEqual(o['total_cents'],519920)
        self.assertEqual(len(o['lines']),5)
        self.assertEqual([(x['ordered_qty'],x['bill_qty'],x['amount_cents']) for x in o['lines'][-2:]],[('5','0',0),('2','0',0)])
        self.assertEqual(o['lines'][0]['driver'][0]['tare'],'1')
    def test_missing_and_invalid_cells_report_multiple_precise_fields(self):
        o=self.order();o['lines'][0]['price']='0';o['lines'][0]['customer'][0].update(gross='',count='11')
        with self.assertRaises(erp.ValidationError) as caught:erp.mutate('order',o,'会计',o['id'])
        fields={(i['field'],i.get('source'),i.get('index')) for i in caught.exception.issues}
        self.assertIn(('price',None,None),fields);self.assertIn(('gross','customer',0),fields);self.assertIn(('count','customer',0),fields)
    def test_all_unshipped_remains_draft_not_zero_receivable(self):
        o=self.order('P004');o['lines'][0].update(actual_qty='0',not_shipped=True)
        o=erp.mutate('order',o,'会计',o['id'])
        with self.assertRaises(erp.ValidationError):self.settle(o)
        self.assertEqual(o['state'],'draft')
    def test_unshipped_cannot_hide_actual_delivery_or_weights(self):
        o=self.order();o['lines'][0]['not_shipped']=True
        with self.assertRaises(erp.ValidationError):erp.mutate('order',o,'会计',o['id'])
    def test_batch_returns_all_orders_errors_and_rolls_back(self):
        a=self.order();b=self.order('P004');a['lines'][0]['price']='0';b['lines'][0]['actual_qty']='1.5'
        with self.assertRaises(erp.ValidationError) as caught:erp.batch_mutate({'operations':[{'action':'order','order_id':o['id'],'body':o} for o in [a,b]]},'会计')
        self.assertEqual({i['order_id'] for i in caught.exception.issues},{a['id'],b['id']})
        self.assertEqual(next(o for o in erp.bootstrap()['orders'] if o['id']==a['id'])['version'],1)
    def product(self,**extra):return {'kind':'product','create':True,'id':'P007','name':'新产品','unit':'筐','price':'5','tare':'1.5',**extra}
    def test_product_add_edit_and_historical_snapshot(self):
        old=self.order();erp.master(self.product(),'会计')
        self.assertIn('P007',[p['id'] for p in erp.bootstrap()['products']])
        erp.master(self.product(id='P001',create=False,name='豆腐新名称',price='9',tare='2'),'会计')
        saved=erp.mutate('order',old,'会计',old['id'])
        self.assertEqual(saved['lines'][0]['product_name'],'大豆腐');self.assertEqual(saved['lines'][0]['price'],'3.333');self.assertEqual(saved['lines'][0]['driver'][0]['tare'],'1.8')
    def test_used_product_unit_change_and_duplicate_id_are_blocked(self):
        self.order()
        for body in [self.product(id='P001'),self.product(id='P001',create=False,unit='包',tare='0',standard_kg='10')]:
            with self.assertRaises(erp.ValidationError):erp.master(body,'会计')
    def test_product_reports_each_invalid_field(self):
        with self.assertRaises(erp.ValidationError) as caught:erp.master(self.product(name=' ',price='0',tare='-1'),'会计')
        self.assertTrue({'name','price','tare'}<={i['field'] for i in caught.exception.issues})
    def test_batch_prices_save_all_and_keep_history_snapshot(self):
        old=self.order();rows=[{'customer_id':cid,'product_id':pid,'price':'8','tare':'1.6','expected':None} for cid in ['C001','C003'] for pid in ['P001','P003']]
        result=erp.batch_rules({'rules':rows},'会计');self.assertEqual(result['count'],4)
        self.assertEqual(next(o for o in erp.bootstrap()['orders'] if o['id']==old['id'])['lines'][0]['price'],'3.333')
    def test_invalid_price_batch_is_atomic_and_located(self):
        before=copy.deepcopy(erp.bootstrap()['rules']);rows=[{'customer_id':'C001','product_id':'P001','price':'5','tare':'1.6','expected':None},{'customer_id':'C003','product_id':'P003','price':'0','tare':'-1','expected':None}]
        with self.assertRaises(erp.ValidationError) as caught:erp.batch_rules({'rules':rows},'会计')
        self.assertEqual(erp.bootstrap()['rules'],before)
        self.assertEqual({i['field'] for i in caught.exception.issues},{'price','tare'})
        self.assertTrue(all(i['customer_id']=='C003' and i['product_id']=='P003' for i in caught.exception.issues))
    def test_prices_stale_expected_and_wrong_role_rejected(self):
        row={'customer_id':'C002','product_id':'P001','price':'5','tare':'1.7','expected':None}
        with self.assertRaises(erp.ValidationError):erp.batch_rules({'rules':[row]},'会计')
        with self.assertRaises(ValueError):erp.batch_rules({'rules':[row]},'库管')

    def test_product_reference_is_editable_validated_and_concurrency_checked(self):
        old=next(p for p in erp.bootstrap()['products'] if p['id']=='P001')
        self.assertEqual(old['default_average_kg'],'18')
        erp.master({'kind':'product',**old,'default_average_kg':'19','expected':old},'会计')
        self.assertEqual(next(p for p in erp.bootstrap()['products'] if p['id']=='P001')['default_average_kg'],'19')
        with self.assertRaisesRegex(ValueError,'已被其他页面修改'):erp.master({'kind':'product',**old,'default_average_kg':'20','expected':old},'会计')
        for bad in ['-1','0','NaN','100001']:
            with self.assertRaises(ValueError):erp.master({'kind':'product',**old,'default_average_kg':bad},'会计')

if __name__=='__main__':unittest.main(verbosity=2)
