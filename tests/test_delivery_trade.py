import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal
import test_workflow as fixture
import trade, assets, resources_costs as rc, inventory, billing, production_config as pc, statements


class DeliveryTradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(fixture.erp,'DB',Path(self.tmp.name)/'trade.db');self.patch.start();fixture.erp.init_db()
        self.ctx=fixture.erp.connect(True);self.c=self.ctx.__enter__();self.erp=fixture.erp
    def tearDown(self):
        self.c.rollback();self.ctx.__exit__(None,None,None);self.patch.stop();self.tmp.cleanup()
    def save(self,kind,b,role='管理员'):
        return trade.save(self.c,kind,{'request_key':str(uuid.uuid4()),**b},role,self.erp.now,self.erp.audit)
    def order(self,pid='P001',actual='10',day='2026-10-20',cid='C001'):
        return self.erp.mutate('order',{'customer_id':cid,'business_date':day,'batch':'日常','lines':[{'product_id':pid,'ordered_qty':actual,'actual_qty':actual,'price':'3','driver':[],'customer':[]}]},'管理员',connection=self.c)
    def product(self,pid,unit,bill,standard=''):
        self.erp.master({'kind':'product','create':True,'id':pid,'name':pid,'unit':unit,'billing_unit':bill,'price':'3','tare':'0','standard_kg':standard,'main_material':'魔芋'},'管理员',connection=self.c)
    def shipment(self,o,**extra):
        return self.save('shipment',{'order_id':o['id'],'order_version':o['version'],'lines':[{'product_id':'P001','asset_id':'CR-YELLOW','qty':6,'tare':'1.8'},{'product_id':'P001','asset_id':'CR-WHITE','qty':4,'tare':'1.2'}],**extra})
    def test_phone_preserved_and_unit_catalog_idempotent(self):
        self.erp.master({'kind':'customer','id':'C001','name':'电话客户','route':'测试市场','phone':'0994-1234567'},'管理员',connection=self.c)
        self.assertEqual(self.c.execute("SELECT phone FROM customers WHERE id='C001'").fetchone()[0],'0994-1234567')
        b={'name':'板','request_key':'unit-1'};self.save('unit',b);self.save('unit',b)
        self.assertEqual(sum(u['id']=='板' for u in trade.units(self.c)),1)
        with self.assertRaises(ValueError):self.save('unit',{'name':'板'})
        with self.assertRaises(ValueError):self.save('unit',{'name':'<img>'})
    def test_count_and_kg_billing_are_independent_of_handling(self):
        for pid,unit,bill,qty,expected in [('BOX','盒','盒','12','12'),('CRATE','筐','筐','2','2'),('KG','公斤','公斤','1.125','1.125')]:
            self.product(pid,unit,bill);o=self.order(pid,qty)
            r=self.erp.mutate('settle',{'version':o['version'],'mode':'auto'},'管理员',o['id'],connection=self.c)
            self.assertEqual(Decimal(r['lines'][0]['bill_qty']),Decimal(expected));self.assertEqual(r['lines'][0]['billing_unit'],bill)
            self.assertEqual(r['total_cents'],int((Decimal(qty)*300).quantize(Decimal(1))))
        self.product('BOXKG','盒','公斤','0.25');o=self.order('BOXKG','12')
        r=self.erp.mutate('settle',{'version':o['version'],'mode':'auto'},'管理员',o['id'],connection=self.c)
        self.assertEqual(r['lines'][0]['bill_qty'],'3');self.assertEqual(r['total_cents'],900)
    def test_typed_tare_customer_only_and_stale_rejected(self):
        o=self.order();entry=self.shipment(o);self.assertEqual(len(entry['lines']),2)
        o['lines'][0].update(customer=[{'gross':'215','count':'10','tare':'0'}],customer_net='215',customer_count='10',driver=[{'gross':'210','count':'10','tare':'0'}],driver_net='210',driver_count='10')
        self.c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),o['id']))
        r=self.erp.mutate('settle',{'version':o['version'],'mode':'customer'},'管理员',o['id'],connection=self.c)
        self.assertEqual(r['lines'][0]['bill_qty'],'199.4')
        self.assertEqual(billing.settlement_net(r['lines'][0],'driver'),Decimal('210'))
        with self.assertRaises(ValueError):self.shipment(r,version=entry['version'])
    def test_return_separated_by_customer_order_and_type_and_void(self):
        first=self.order();second=self.order(cid='C002');self.shipment(first);self.shipment(second)
        self.c.execute("INSERT INTO delivery_drivers VALUES('TRADE-D','司机',1)")
        b={'business_date':'2026-10-21','source_date':'2026-10-20','driver_id':'TRADE-D','by_order':True,'lines':[{'asset_id':'CR-YELLOW','order_id':first['id'],'qty':3},{'asset_id':'CR-YELLOW','order_id':second['id'],'qty':2},{'asset_id':'CR-WHITE','order_id':first['id'],'qty':4}],'request_key':'return-by-orders'}
        r=assets.save(self.c,'return-batch',b,'管理员',self.erp.now,self.erp.audit)
        self.assertEqual(len(r['lines']),3)
        balances=trade.customer_crates(self.c,'C001','2026-10-21')['rows'];self.assertEqual(next(x['balance_qty'] for x in balances if x['asset_id']=='CR-YELLOW'),3)
        self.assertEqual(next(x['balance_qty'] for x in trade.customer_crates(self.c,'C002','2026-10-21')['rows'] if x['asset_id']=='CR-YELLOW'),4)
        assets.save(self.c,'void',{'request_key':'void-one','id':r['lines'][0]['id'],'version':1,'note':'重复'},'管理员',self.erp.now,self.erp.audit)
        self.assertEqual(next(x['balance_qty'] for x in trade.customer_crates(self.c,'C001','2026-10-21')['rows'] if x['asset_id']=='CR-YELLOW'),6)
        with self.assertRaises(ValueError):trade.return_lines(self.c,[{'asset_id':'CR-CLOTH','qty':1,'order_id':first['id']}])
        with self.assertRaises(ValueError):trade.return_lines(self.c,[{'asset_id':'CR-YELLOW','qty':1}],require_order=True)
    def test_customer_crate_aging_buckets_follow_fifo(self):
        self.save('opening',{'customer_id':'C001','asset_id':'CR-YELLOW','business_date':'2026-08-01','qty':5,'note':'历史签字'})
        o=self.order();self.shipment(o)
        yellow=next(x for x in trade.customer_crates(self.c,'C001','2026-10-21')['rows'] if x['asset_id']=='CR-YELLOW')
        self.assertEqual(yellow['oldest_date'],'2026-08-01')
        self.assertEqual(yellow['buckets']['quarter'],5)
        self.assertEqual(yellow['buckets']['week'],yellow['balance_qty']-5)
        self.assertEqual(yellow['oldest_days'],81)
        # 回框 5 个先进先出抵掉 8 月的旧账，最早欠框日回到本次配送日
        self.c.execute("INSERT INTO delivery_drivers VALUES('TRADE-D','司机',1)")
        assets.save(self.c,'return-batch',{'request_key':'aging-return','driver_id':'TRADE-D','business_date':'2026-10-21','by_order':True,'lines':[{'asset_id':'CR-YELLOW','order_id':o['id'],'qty':5}]},'管理员',self.erp.now,self.erp.audit)
        yellow=next(x for x in trade.customer_crates(self.c,'C001','2026-10-21')['rows'] if x['asset_id']=='CR-YELLOW')
        self.assertEqual(yellow['buckets']['quarter'],0)
        self.assertEqual(yellow['oldest_date'],o['business_date'])
        ledger=trade.crate_ledger(self.c,'2026-10-21')['customers'];self.assertGreaterEqual(ledger['C001']['qty'],1);self.assertEqual(ledger['C001']['older'],0)
    def test_opening_once_and_as_of_statement_tracks_returns(self):
        o=self.order();self.shipment(o);self.save('opening',{'customer_id':'C001','asset_id':'CR-YELLOW','business_date':'2026-10-19','qty':8,'note':'签字盘点'})
        with self.assertRaises(ValueError):self.save('opening',{'customer_id':'C001','asset_id':'CR-YELLOW','business_date':'2026-10-19','qty':8,'note':'重复'})
        before=statements.snapshot(self.c,'C001','2026-10-20',self.erp.now());self.assertEqual(next(x['balance_qty'] for x in before['crates']['rows'] if x['asset_id']=='CR-YELLOW'),14)
        self.assertEqual(trade.customer_crates(self.c,'C001','2026-10-18')['rows'],[])
    def test_feedback_keeps_original_order_and_resolves_once(self):
        o=self.order();original=self.c.execute('SELECT payload FROM orders WHERE id=?',(o['id'],)).fetchone()[0]
        r=self.save('feedback',{'order_id':o['id'],'order_version':o['version'],'product_id':'P001','received_qty':'9','feedback_date':'2026-10-21','note':'客户反馈少到一框'})
        self.assertEqual(r['difference_qty'],'-1');self.assertEqual(self.c.execute('SELECT payload FROM orders WHERE id=?',(o['id'],)).fetchone()[0],original)
        self.save('resolve-feedback',{'id':r['id'],'version':r['version'],'resolution':'补送 SO-TEST 一框，客户已确认'})
        with self.assertRaises(ValueError):self.save('resolve-feedback',{'id':r['id'],'version':r['version'],'resolution':'重复'})
    def test_trip_month_settlement_posts_one_expense_and_is_idempotent(self):
        p={'business_date':'2026-10-20','version':1,'trips':[{'id':'T1','name':'第一趟','driver':'司机','vehicle_name':'测试车'}],'assignments':[{'market_id':'M001','trip_id':'T1'}]}
        self.c.execute('INSERT INTO dispatch_plans VALUES(?,?)',('2026-10-20',json.dumps(p)))
        b={'business_date':'2026-10-20','trip_id':'T1','partner':'测试运输公司','rate':'120.50','note':'已完成配送'}
        trip=self.save('trip',b)
        with self.assertRaises(ValueError):self.save('trip',b)
        report=trade.transport_report(self.c,'2026-10');group=report['groups'][0]
        issue={'month':'2026-10','partner':'测试运输公司','handler':'经办人','source_fingerprint':group['source_fingerprint'],'request_key':'monthly-issue'}
        doc=self.save('transport-issue',issue);again=self.save('transport-issue',issue)
        self.assertEqual(again['id'],doc['id']);self.assertEqual(doc['amount_cents'],12050);self.assertEqual(len(rc.rows(self.c,'indirect_expenses')),1)
        expense=rc.rows(self.c,'indirect_expenses')[0];self.assertEqual(expense['reference'],doc['id']);self.assertEqual(expense['amount_cents'],12050)
        with self.assertRaises(ValueError):self.save('void-trip',{'id':trip['id'],'version':2,'note':'已结算不可撤'})
        self.assertEqual(trade.transport_report(self.c,'2026-10')['groups'][0]['unsettled_count'],0)
    def test_transport_area_rate_fills_trip_without_manual_price(self):
        self.save('transport-rates',{'areas':{'乌鲁木齐':'180'}})
        plan={'business_date':'2026-10-21','version':1,'trips':[{'id':'T2','name':'乌鲁木齐趟','driver':'司机','vehicle_name':'测试车'},{'id':'T3','name':'临时趟','driver':'司机','vehicle_name':'测试车'}],'assignments':[{'market_id':'M001','trip_id':'T2'},{'market_id':'M999','trip_id':'T3'}]}
        self.c.execute('INSERT INTO dispatch_plans VALUES(?,?)',('2026-10-21',json.dumps(plan)))
        trip=self.save('trip',{'business_date':'2026-10-21','trip_id':'T2','partner':'测试运输公司','note':'按区域单价'})
        self.assertEqual(trip['amount_cents'],18000);self.assertEqual(trip['area'],'乌鲁木齐')
        with self.assertRaisesRegex(ValueError,'区域单价'):
            self.save('trip',{'business_date':'2026-10-21','trip_id':'T3','partner':'测试运输公司','note':'临时趟未填价'})

    def test_repack_consumes_source_and_checks_output_mass(self):
        self.product('PACK','包','公斤','1');self.c.execute("INSERT INTO meta VALUES('processing_rules',?)",(json.dumps({'version':1,'rules':[{'source_product_id':'P001','output_product_id':'PACK'}]}),))
        plan={'business_date':'2026-10-20','stock':[{'product_id':'P001','existing_qty':'10','produced_qty':'0','loss_qty':'0'},{'product_id':'PACK','existing_qty':'0','produced_qty':'0','loss_qty':'0'}],'allocations':[]}
        self.c.execute('INSERT INTO warehouse_plans VALUES(?,?)',('2026-10-20',json.dumps(plan)))
        b={'business_date':'2026-10-20','product_id':'P001','process_mode':'repack','input_qty':'2','input_kg':'20','outputs':[{'product_id':'PACK','qty':'20'}],'request_key':'repack-1','inventory_revision':inventory.revision(self.c)}
        r=inventory.Operations(self.c,self.erp.now,self.erp.audit).process(b,'管理员')
        self.assertEqual(r['input_qty'],'2');stock=inventory.stock(self.c,'2026-10-20')['products'];self.assertEqual(next(p['book_qty'] for p in stock if p['product_id']=='P001'),'8');self.assertEqual(next(p['book_qty'] for p in stock if p['product_id']=='PACK'),'20')
        ops=inventory.Operations(self.c,self.erp.now,self.erp.audit)
        with self.assertRaises(ValueError):ops._process_entry({**b,'input_kg':'19'},'管理员')
        with self.assertRaises(ValueError):ops.process({**b,'request_key':'too-many','input_qty':'9','inventory_revision':inventory.revision(self.c)},'管理员')
        self.assertEqual(len(inventory.rows(self.c,'processing_batches')),1)
    def test_independent_gel_system_has_no_invented_bucket_conversion(self):
        cfg=pc.get(self.c);gel=next(s for s in cfg['systems'] if s['id']=='gel-tofu');self.assertTrue(gel['direct_bean_only']);self.assertEqual(gel['soak_kg'],'')
        self.assertNotIn('gel-tofu',{s['id'] for s in pc.get(self.c,'2026-10-20')['systems']})
        validated=pc.validate(self.c,cfg);self.assertTrue(next(s for s in validated['systems'] if s['id']=='gel-tofu')['direct_bean_only'])
    def test_permissions_and_invalid_shipment_do_not_write(self):
        o=self.order()
        with self.assertRaises(ValueError):self.shipment(o,order_version=0)
        with self.assertRaises(ValueError):self.shipment(o,lines=[{'product_id':'P001','asset_id':'CR-YELLOW','qty':9,'tare':1}])
        self.assertEqual(trade.records(self.c,'shipment'),[])
        with self.assertRaises(ValueError):self.save('opening',{'customer_id':'C001','asset_id':'CR-YELLOW','business_date':'2026-10-20','qty':1,'note':'测试'},'司机')
