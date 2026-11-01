import unittest,tempfile,uuid,json
from pathlib import Path
from unittest.mock import patch
import test_workflow as fixture
import assets,erp_access as access
class AssetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(fixture.erp,'DB',Path(self.tmp.name)/'assets.db');self.patch.start();fixture.erp.init_db();self.ctx=fixture.erp.connect(True);self.c=self.ctx.__enter__()
 def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);self.patch.stop();self.tmp.cleanup()
 def save(self,kind,b,role='管理员'):return assets.save(self.c,kind,{'request_key':str(uuid.uuid4()),**b},role,fixture.erp.now,fixture.erp.audit)
 def test_daily_unknown_and_returns_not_double_counted(self):
  day='2020-01-01';r=assets.report(self.c,day);large=next(a for a in r['crates'] if a['id']=='P-LARGE');self.assertIsNone(large['empty_qty']);self.assertIsNone(large['total_qty'])
  self.save('count',dict(asset_id='P-LONG',business_date=day,empty_qty=20,damaged_qty=2))
  b=dict(asset_id='P-LONG',business_date=day,movement='return',qty=5,driver='测试司机');event=self.save('movement',b,'库管');r=assets.report(self.c,day);long=next(a for a in r['crates'] if a['id']=='P-LONG');self.assertEqual(long['total_qty'],'22');self.assertEqual(long['returned_qty'],5)
  self.save('void',dict(id=event['id'],version=1,note='重复登记'),'库管');self.assertEqual(next(a for a in assets.report(self.c,day)['crates'] if a['id']=='P-LONG')['returned_qty'],0)
 def test_permissions_and_integer(self):
  with self.assertRaises(ValueError):self.save('asset',dict(name='机器',category='设备',unit='台',quantity=1),'厂长')
  with self.assertRaises(ValueError):self.save('movement',dict(asset_id='P-LONG',business_date='2020-01-01',movement='return',qty='1.5',driver='司机'))
  with self.assertRaises(ValueError):self.save('movement',dict(asset_id='P-LONG',business_date='2020-01-01',movement='return',qty=1,driver=''))
 def test_optimistic_count_and_idempotency(self):
  b=dict(request_key=str(uuid.uuid4()),asset_id='P-LONG',business_date='2020-01-01',empty_qty=12,damaged_qty=0);first=self.save('count',b);self.assertEqual(self.save('count',b)['id'],first['id'])
  with self.assertRaises(ValueError):self.save('count',{**b,'empty_qty':13})
  with self.assertRaises(ValueError):self.save('count',{**b,'request_key':str(uuid.uuid4()),'empty_qty':13})
  self.save('count',{**b,'request_key':str(uuid.uuid4()),'version':1,'empty_qty':14});self.assertEqual(self.save('count',b)['empty_qty'],12)
 def test_crate_unit_cost_and_safety_stock(self):
  r=self.save('asset',dict(name='测试框型',category='周转筐',unit_cost='48.5',safety_stock=100))
  saved=next(a for a in assets.report(self.c,'2020-01-01')['crates'] if a['id']==r['id'])
  self.assertEqual(saved['unit_cost_cents'],4850);self.assertEqual(saved['safety_stock'],100)
  self.save('movement',dict(asset_id=r['id'],business_date='2020-01-01',movement='receipt',qty=10,unit_cost='47.2'))
  saved=next(a for a in assets.report(self.c,'2020-01-01')['crates'] if a['id']==r['id']);self.assertEqual(saved['unit_cost_cents'],4720)
  with self.assertRaises(ValueError):self.save('asset',dict(name='坏成本',category='周转筐',unit_cost='-1'))
  with self.assertRaises(ValueError):self.save('asset',dict(name='坏库存',category='周转筐',safety_stock='1.5'))
 def test_migration_preserves_history(self):
  self.assertEqual(self.c.execute("SELECT active FROM material_items WHERE id='P-LARGE'").fetchone()[0],0)
  self.assertTrue(access.defaults('库管')['modules'].count('asset.crates')==1)
  self.assertNotIn('asset.crates',access.defaults('厂长')['modules'])

 def test_occupied_crates_follow_inventory_counts(self):
  products=[{'product_id':'test-product','product_name':'测试筐装产品','unit':'筐','counted_qty':'7','shipped_qty':'12'}]
  self.c.execute("INSERT INTO products VALUES('test-product','测试筐装产品','筐','0','0',NULL)")
  self.save('mapping',dict(asset_id='P-LONG',product_id='test-product'))
  self.save('count',dict(asset_id='P-LONG',business_date='2020-01-01',empty_qty=20,damaged_qty=2))
  with patch.object(assets.inventory,'stock',return_value={'products':products}):
   r=next(a for a in assets.report(self.c,'2020-01-01')['crates'] if a['id']=='P-LONG');self.assertEqual(r['occupied_qty'],'7');self.assertEqual(r['total_qty'],'29');self.assertEqual(r['shipped_qty'],'12')
  products[0]['counted_qty']=''
  with patch.object(assets.inventory,'stock',return_value={'products':products}):self.assertIsNone(next(a for a in assets.report(self.c,'2020-01-01')['crates'] if a['id']=='P-LONG')['total_qty'])

 def batch(self,**extra):
  self.c.execute("INSERT OR IGNORE INTO delivery_drivers VALUES('TEST-DRIVER','测试司机',1)")
  self.c.execute("INSERT OR IGNORE INTO delivery_vehicles(id,name) VALUES('TEST-VEHICLE','测试车辆')")
  return {'business_date':'2020-01-01','driver_id':'TEST-DRIVER','vehicle_id':'TEST-VEHICLE','trip':'第一趟','lines':[{'asset_id':'P-LARGE','qty':3},{'asset_id':'P-LONG','qty':8}],**extra}
 def test_return_batch_saved_once_with_authoritative_driver_vehicle(self):
  b=self.batch(request_key=str(uuid.uuid4()),driver='伪造姓名',vehicle_name='伪造车牌');r=self.save('return-batch',b,'库管');self.assertEqual(len(r['lines']),2);self.assertEqual(r['lines'][0]['driver'],'测试司机');self.assertEqual(r['lines'][0]['vehicle_name'],'测试车辆');self.assertEqual(self.save('return-batch',b,'库管'),r)
  v=assets.report(self.c,'2020-01-01');self.assertEqual(sum(e['qty'] for e in v['events']),11);self.assertEqual(len({e['batch_id'] for e in v['events']}),1)
 def test_invalid_batch_writes_no_partial_records(self):
  before=len(assets.rows(self.c));b=self.batch(lines=[{'asset_id':'P-LARGE','qty':3},{'asset_id':'P-LONG','qty':'1.2'}])
  with self.assertRaises(ValueError):self.save('return-batch',b)
  self.assertEqual(len(assets.rows(self.c)),before)
  for changes in [{'driver_id':'missing'},{'vehicle_id':'missing'},{'lines':[]},{'lines':[{'asset_id':'P-LONG','qty':1},{'asset_id':'P-LONG','qty':2}]}]:
   with self.assertRaises(ValueError):self.save('return-batch',self.batch(**changes))
 def compare(self,returns,orders=None,plan=None,mapping=None):
  orders=orders if orders is not None else [{'id':'ORDER-1','business_date':'2020-01-01','delivery_method':'delivery','lines':[{'product_id':'PRODUCT','product_name':'大豆腐','unit':'筐','actual_qty':'10'}]}]
  plan=plan if plan is not None else {'business_date':'2020-01-01','order_markets':{'ORDER-1':'MARKET'},'assignments':[{'market_id':'MARKET','trip_id':'TRIP'}],'trips':[{'id':'TRIP','vehicle_id':'VEHICLE','vehicle_name':'测试车','driver_ids':['DRIVER'],'driver':'测试司机'}]}
  with patch.object(assets.rc,'rows',side_effect=lambda c,t:orders if t=='orders' else [plan] if plan else []):
   return assets.return_comparison(self.c,'2020-01-02',returns,mapping or {'PRODUCT':'P-LARGE'},[{'id':'P-LARGE','name':'大豆腐框'}])
 def returned(self,qty,**extra):return {'id':str(uuid.uuid4()),'kind':'movement','movement':'return','asset_id':'P-LARGE','business_date':'2020-01-02','qty':qty,'vehicle_id':'VEHICLE','driver_id':'DRIVER','driver':'测试司机',**extra}
 def test_yesterday_vs_today_cumulative_and_voids(self):
  r=self.compare([self.returned(8)]);self.assertEqual(r['yesterday'],'2020-01-01');self.assertEqual(r['summary'][0]['difference_qty'],'-2');self.assertEqual(r['details'][0]['status'],'mismatch')
  r=self.compare([self.returned(8),self.returned(2),self.returned(20,voided=True)]);self.assertEqual(r['summary'][0]['status'],'matched');self.assertEqual(r['details'][0]['status'],'matched')
  r=self.compare([self.returned(11)]);self.assertEqual(r['details'][0]['difference_qty'],'1')
 def test_missing_assignment_or_return_vehicle_needs_check(self):
  plan={'business_date':'2020-01-01'};r=self.compare([self.returned(8)],plan=plan);self.assertTrue(any(x['status']=='pending' for x in r['details']))
  r=self.compare([self.returned(8,vehicle_id='')]);self.assertTrue(all(x['status']=='pending' for x in r['details']))
  r=self.compare([self.returned(8)],orders=[],plan={});self.assertEqual(r['summary'][0]['status'],'pending')
 def test_customer_pickup_is_excluded_and_unmapped_product_is_pending(self):
  order={'id':'ORDER-1','business_date':'2020-01-01','delivery_method':'pickup','lines':[{'product_id':'PRODUCT','product_name':'大豆腐','unit':'筐','actual_qty':'10'}]}
  self.assertEqual(self.compare([],orders=[order])['summary'][0]['yesterday_qty'],'0')
  order['delivery_method']='delivery';order['lines'][0]['product_id']='UNKNOWN';self.assertEqual(self.compare([],orders=[order])['summary'][0]['status'],'pending')
 def test_crate_book_reconciles_inside_and_customer_balance(self):
  day='2020-01-01'
  self.save('movement',dict(asset_id='P-LONG',business_date=day,movement='receipt',qty=10))
  self.save('count',dict(asset_id='P-LONG',business_date=day,empty_qty=7,damaged_qty=3))
  row=next(x for x in assets.report(self.c,day)['reconcile'] if x['asset_id']=='P-LONG')
  self.assertEqual((row['book_qty'],row['inside_qty'],row['owed_qty'],row['diff_qty']),('10','10','0','0'))
  self.save('count',{**dict(asset_id='P-LONG',business_date=day,empty_qty=6,damaged_qty=3),'request_key':str(uuid.uuid4()),'version':1})
  row=next(x for x in assets.report(self.c,day)['reconcile'] if x['asset_id']=='P-LONG')
  self.assertEqual(row['diff_qty'],'1')
  self.save('movement',dict(asset_id='P-LONG',business_date=day,movement='scrap',qty=2))
  row=next(x for x in assets.report(self.c,day)['reconcile'] if x['asset_id']=='P-LONG')
  self.assertEqual((row['book_qty'],row['diff_qty']),('8','-1'))
