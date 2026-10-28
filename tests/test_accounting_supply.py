import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal
import test_workflow as fixture
import finished_goods as fg,crate_accounting as ca,inventory,trade,resources_costs as rc,purchasing,gel_tofu,production_daily as daily,production_management as pm


class AccountingSupplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(fixture.erp,'DB',Path(self.tmp.name)/'new.db');self.patch.start();self.erp=fixture.erp;self.erp.init_db();self.ctx=self.erp.connect(True);self.c=self.ctx.__enter__();self.day=(datetime.now(fixture.erp.TZ).date()+timedelta(days=60)).isoformat();self.month=self.day[:7]
    def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);self.patch.stop();self.tmp.cleanup()
    def product(self,pid,name,unit='盒',kind='purchased'):
        self.erp.master({'kind':'product','create':True,'id':pid,'name':name,'unit':unit,'billing_unit':unit,'price':'3','tare':'0','standard_kg':'','main_material':'黄豆','supply_kind':kind,'supplier_ids':[self.supplier()['id']] if kind=='purchased' else []},'管理员',connection=self.c)
    def order(self,pid='P001',qty='10'):
        return self.erp.mutate('order',{'customer_id':'C001','business_date':self.day,'batch':'日常','workflow_version':1,'lines':[{'product_id':pid,'ordered_qty':qty,'actual_qty':qty,'price':'3','driver':[],'customer':[]}]},'管理员',connection=self.c)
    def plan(self,opening=None):
        stock=[{'product_id':p['id'],'existing_qty':str((opening or {}).get(p['id'],0)),'produced_qty':'0','loss_qty':'0'} for p in self.c.execute('SELECT id FROM products')]
        self.c.execute('INSERT OR REPLACE INTO warehouse_plans VALUES(?,?)',(self.day,json.dumps({'business_date':self.day,'stock':stock,'allocations':[],'allocation_state':'draft'})))
    def supplier(self):
        prior=next((r for r in purchasing.projection(self.c)['suppliers'] if r['name']=='外购成品供应人'),None)
        if prior:return prior
        return purchasing.Operations(self.c,self.erp.now,self.erp.audit).supplier({'name':'外购成品供应人','category_ids':['SC-FINISHED'],'payment_days':30},'管理员')
    def save(self,kind,b,role='管理员'):
        return fg.save(self.c,kind,{'request_key':str(uuid.uuid4()),**b},role,self.erp.now,self.erp.audit)
    def receipt(self,s,pid='OIL',qty='10',price='2'):
        return self.save('receipt',{'business_date':self.day,'supplier_id':s['id'],'inventory_revision':inventory.revision(self.c),'handler':'会计','note':'按供货单核对','lines':[{'product_id':pid,'qty':qty,'billing_unit':'盒','price':price}]})
    def test_accountant_crate_entry_is_snapshot_and_customer_stat(self):
        self.plan({'P001':20});o=self.order();l=o['lines'][0];payload={**o,'lines':[{**l,'driver':[{'gross':'200','count':'10','tare':'0'}],'customer':[{'gross':'205','count':'10','tare':'0'}],'crate_lines':[{'asset_id':'CR-WHITE','qty':4,'tare':'1'},{'asset_id':'CR-YELLOW','qty':6,'tare':'2'}]}]}
        n=self.erp.mutate('order',payload,'管理员',o['id'],connection=self.c);self.assertEqual(n['lines'][0]['crate_lines'][0]['asset_name'],'白框');self.assertEqual(sum(x['qty'] for x in n['lines'][0]['crate_lines']),10)
        stats=trade.customer_crates(self.c,'C001',self.day)['rows'];self.assertEqual(next(r['shipped_qty'] for r in stats if r['asset_id']=='CR-WHITE'),4)
        n=self.erp.mutate('confirm-weight',{'version':n['version'],'evidence_checked':True},'管理员',n['id'],connection=self.c)
        n=self.erp.mutate('settle',{'version':n['version'],'mode':'customer'},'管理员',n['id'],connection=self.c);self.assertEqual(n['lines'][0]['bill_qty'],'189')
    def test_customer_crate_rates_are_independent_and_optimistic(self):
        rows=[{'customer_id':'C001','product_id':'P001','variant_id':'CR-WHITE','tare':'1.2','expected':None},{'customer_id':'C001','product_id':'P001','variant_id':'CR-YELLOW','tare':'1.8','expected':None}]
        self.assertEqual(ca.save_rules(self.c,rows,'管理员',self.erp.now,self.erp.audit),2);self.assertEqual(ca.defaults(self.c,'C001','P001')['CR-WHITE'],'1.2')
        with self.assertRaises(ValueError):ca.save_rules(self.c,rows,'管理员',self.erp.now,self.erp.audit)
        with self.assertRaises(ValueError):ca.normalize(self.c,'P001',[{'asset_id':'CR-WHITE','qty':9,'tare':1}],Decimal(10))
    def test_atomic_photo_confirmation_and_settlement(self):
        self.plan({'P001':20});o=self.order();body={**o,'lines':[{**o['lines'][0],'driver':[{'gross':'200','count':'10','tare':'0'}],'crate_lines':[{'asset_id':'CR-WHITE','qty':10,'tare':1}]}]}
        plan=json.loads(self.c.execute('SELECT payload FROM warehouse_plans WHERE business_date=?',(self.day,)).fetchone()[0]);plan['allocation_state']='confirmed';plan['allocations']=[{'order_id':o['id'],'product_id':'P001','qty':'10','ordered_qty':'10'}];self.c.execute('UPDATE warehouse_plans SET payload=? WHERE business_date=?',(json.dumps(plan),self.day))
        self.c.commit();result=self.erp.batch_mutate({'operations':[{'action':'settle','order_id':o['id'],'update':body,'body':{'version':o['version'],'mode':'driver','confirm_accounting_entry':True,'evidence_checked':True}}]},'管理员');self.assertEqual(result['orders'][0]['state'],'ready');self.assertEqual(result['orders'][0]['lines'][0]['bill_qty'],'200')
    def test_purchase_stock_fifo_payable_payment_statement(self):
        self.product('OIL','油豆腐');self.plan();s=self.supplier();r=self.receipt(s);self.assertEqual(r['amount_cents'],2000);self.assertEqual(next(p['book_qty'] for p in inventory.stock(self.c,self.day)['products'] if p['product_id']=='OIL'),'10')
        o=self.order('OIL','4');cost=fg.stock_cost(self.c,self.day,self.day)[0];self.assertEqual(cost['sales_cost_cents'],800);self.assertEqual(cost['ending_value_cents'],1200)
        p=next(x for x in daily.inferred_outputs(self.c,self.day) if x['product_id']=='OIL');self.assertEqual(p['purchased_qty'],'10');self.assertEqual(daily.main_material(self.c,{'id':'OIL','name':'油豆腐'}),'外购成品')
        payment=self.save('payment',{'receipt_id':r['id'],'version':1,'business_date':self.day,'amount':'5','method':'现金','handler':'出纳','note':'付现金核对'})
        preview=fg.statement_preview(self.c,s['id'],self.month);self.assertEqual(preview['outstanding_cents'],1500)
        issue={'request_key':'issue-once','supplier_id':s['id'],'month':self.month,'source_fingerprint':preview['source_fingerprint'],'handler':'会计'};doc=self.save('statement',issue);self.assertEqual(self.save('statement',issue)['id'],doc['id']);self.assertEqual(len(fg.records(self.c,'statement')),1)
        with self.assertRaises(ValueError):self.save('payment',{'receipt_id':r['id'],'version':2,'business_date':self.day,'amount':'16','method':'现金','handler':'出纳','note':'不能超付'})
        with self.assertRaises(ValueError):self.save('void',{'receipt_id':r['id'],'version':2,'business_date':self.day,'note':'已付款不能作废'})
    def test_receipt_kg_cost_and_idempotency(self):
        self.product('OIL','油豆腐');self.plan();s=self.supplier();b={'request_key':'same','business_date':self.day,'supplier_id':s['id'],'inventory_revision':inventory.revision(self.c),'handler':'会计','note':'公斤验收','lines':[{'product_id':'OIL','qty':'5','billing_unit':'公斤','net_kg':'3','price':'2.5'}]};r=self.save('receipt',b);self.assertEqual(r['amount_cents'],750);self.assertEqual(self.save('receipt',b)['id'],r['id'])
        self.assertEqual(len(fg.records(self.c,'receipt')),1)
        with self.assertRaises(ValueError):self.save('receipt',{**b,'request_key':'other','lines':[{'product_id':'OIL','qty':'5','billing_unit':'公斤','price':'2.5'}]})
    def test_gel_rule_used_beans_and_actual_output(self):
        self.product('GEL','内脂豆腐',kind='self');self.plan();ops=rc.Operations(self.c,self.erp.now,self.erp.audit)
        ops.material({'request_key':'soy-in','revision':rc.revision(self.c),'kind':'receipt','material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':self.day,'qty':'100','amount':'400','handler':'库管','note':'上豆测试'},'管理员')
        ops.material({'request_key':'soy-use','revision':rc.revision(self.c),'kind':'consume','material_id':'RM-SOY','warehouse_id':'WH-TOFU','production_system_id':'gel-tofu','business_date':self.day,'qty':'50','amount':'0','handler':'厂长','note':'独立上豆50公斤'},'管理员')
        gel_tofu.save(self.c,{'business_date':self.day,'product_id':'GEL','qty':'12','version':0,'note':'现场实际12盒'},'管理员',self.erp.now,self.erp.audit)
        report=gel_tofu.report(self.c,self.day);self.assertEqual(report['used_kg'],'50');self.assertEqual(Decimal(report['expected_output_qty']),10);self.assertEqual(report['output_difference_qty'],'2');self.assertEqual(report['standard_required_kg'],'60');self.assertEqual(report['bean_difference_kg'],'-10')
    def test_gel_standard_follows_product_unit(self):
        self.c.execute("UPDATE meta SET value=? WHERE key='gel_tofu_output_standard'",(json.dumps({'effective_date':'2020-01-01','dry_kg':'50','output_qty':'1','unit':'筐'},ensure_ascii=False),))
        self.assertIsNone(gel_tofu.report(self.c,self.day))
        self.product('GELC','内脂豆腐',unit='筐');self.plan();ops=rc.Operations(self.c,self.erp.now,self.erp.audit)
        ops.material({'request_key':'soy-in','revision':rc.revision(self.c),'kind':'receipt','material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':self.day,'qty':'300','amount':'1200','handler':'库管','note':'上豆测试','production_system_id':''},'管理员')
        ops.material({'request_key':'soy-use','revision':rc.revision(self.c),'kind':'consume','material_id':'RM-SOY','warehouse_id':'WH-TOFU','production_system_id':'gel-tofu','business_date':self.day,'qty':'100','amount':'0','handler':'厂长','note':'独立上豆100公斤'},'管理员')
        report=gel_tofu.report(self.c,self.day)
        self.assertEqual(report['unit'],'筐');self.assertEqual([p['id'] for p in report['products']],['GELC'])
        self.assertEqual(Decimal(report['expected_output_qty']),2)
        gel_tofu.save(self.c,{'business_date':self.day,'product_id':'GELC','qty':'3','version':0,'note':'现场实际3筐'},'管理员',self.erp.now,self.erp.audit)
        report=gel_tofu.report(self.c,self.day);self.assertEqual(report['output_difference_qty'],'1');self.assertEqual(report['standard_required_kg'],'150');self.assertEqual(report['bean_difference_kg'],'-50')
        with self.assertRaisesRegex(ValueError,'整数'):gel_tofu.save(self.c,{'business_date':self.day,'product_id':'GELC','qty':'1.5','version':1,'note':'半筐'},'管理员',self.erp.now,self.erp.audit)

    def test_privileges_checked_for_goods(self):
        with self.assertRaises(ValueError):self.save('receipt',{},'库管')
        with self.assertRaises(ValueError):self.save('payment',{},'会计')
