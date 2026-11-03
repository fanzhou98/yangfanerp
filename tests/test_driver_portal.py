import unittest,tempfile,uuid,json,time
from pathlib import Path
from unittest.mock import patch
import test_workflow as fixture
import auth,driver_portal as dp,assets,erp_access as access
class DriverPortalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(fixture.erp,'DB',Path(self.tmp.name)/'driver.db');self.p.start();fixture.erp.init_db();self.ctx=fixture.erp.connect(True);self.c=self.ctx.__enter__();now=int(time.time())
  self.admin=auth.create_initial_admin(self.c,'admin','管理员','Test-Admin-Password-2026!',now)
  self.a=auth.create_user(self.c,self.admin,{'username':'drivera','display_name':'司机甲','role':'司机','password':'Driver-A-Password-2026!'},now);self.b=auth.create_user(self.c,self.admin,{'username':'driverb','display_name':'司机乙','role':'司机','password':'Driver-B-Password-2026!'},now)
  base=json.loads(self.c.execute('SELECT payload FROM orders LIMIT 1').fetchone()[0]);orders=[]
  for index,cid in enumerate(['C001','C002']):
   o={**base,'id':'DRIVER-ORDER-'+str(index),'business_date':'2020-01-02','customer_id':cid,'customer_name':'独占客户'+str(index),'delivery_method':'delivery'};o['lines']=[{**l,'actual_qty':l['ordered_qty']} for l in o['lines']];self.c.execute('INSERT INTO orders VALUES(?,?)',(o['id'],json.dumps(o)));orders.append(o)
  plan={'business_date':'2020-01-02','trips':[{'id':'TA','name':'甲趟','period':'上午','driver_ids':[self.a['driver_id']],'driver':'司机甲','vehicle_id':'V001','vehicle_name':'车甲'},{'id':'TB','name':'乙趟','period':'下午','driver_ids':[self.b['driver_id']],'driver':'司机乙','vehicle_id':'V002','vehicle_name':'车乙'}],'assignments':[{'market_id':'M001','trip_id':'TA','sequence':1},{'market_id':'M002','trip_id':'TB','sequence':1}],'order_markets':{orders[0]['id']:'M001',orders[1]['id']:'M002'}};self.c.execute('INSERT OR REPLACE INTO dispatch_plans VALUES(?,?)',(plan['business_date'],json.dumps(plan)))
 def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);self.p.stop();self.tmp.cleanup()
 def body(self,**kw):return {'request_key':str(uuid.uuid4()),'business_date':'2020-01-02','vehicle_id':'V001','trip':'甲趟','lines':[{'asset_id':'P-LARGE','qty':3},{'asset_id':'P-LONG','qty':2}],**kw}
 def test_account_archive_scope_and_print_ownership(self):
  self.assertEqual(self.c.execute('SELECT name FROM delivery_drivers WHERE id=?',(self.a['driver_id'],)).fetchone()[0],'司机甲');r=dp.report(self.c,self.a,'2020-01-02');self.assertEqual([t['id'] for t in r['trips']],['TA']);self.assertNotIn('独占客户1',json.dumps(r,ensure_ascii=False));self.assertNotIn('price',json.dumps(r));self.assertNotIn('total_cents',json.dumps(r))
  self.assertIn('配送单',dp.print_delivery(self.c,self.a,'2020-01-02','TA',fixture.erp.now))
  with self.assertRaises(auth.AuthError):dp.print_delivery(self.c,self.a,'2020-01-02','TB',fixture.erp.now)
  with self.assertRaises(ValueError):dp.submit(self.c,self.a,self.body(vehicle_id='V-NOT-EXIST'),fixture.erp.now,fixture.erp.audit)
 def test_pending_confirmation_atomic_idempotent_and_status(self):
  b=self.body();r=dp.submit(self.c,self.a,b,fixture.erp.now,fixture.erp.audit);self.assertEqual(dp.submit(self.c,self.a,b,fixture.erp.now,fixture.erp.audit),r);self.assertEqual(len(dp.pending(self.c)),1);self.assertFalse(assets.report(self.c,'2020-01-02')['events'])
  review={'id':r['id'],'version':r['version'],'request_key':str(uuid.uuid4())}
  with self.assertRaises(ValueError):dp.review(self.c,'driver-confirm',review,'司机',fixture.erp.now,fixture.erp.audit)
  accepted=dp.review(self.c,'driver-confirm',review,'库管',fixture.erp.now,fixture.erp.audit);self.assertEqual(accepted['state'],'confirmed');self.assertEqual(dp.review(self.c,'driver-confirm',review,'库管',fixture.erp.now,fixture.erp.audit),accepted);self.assertEqual(sum(e['qty'] for e in assets.report(self.c,'2020-01-02')['events']),5);self.assertEqual(dp.report(self.c,self.a,'2020-01-02')['requests'][0]['state'],'confirmed');self.assertFalse(dp.report(self.c,self.b,'2020-01-02')['requests'])
 def test_rejection_does_not_count_and_role_gates(self):
  r=dp.submit(self.c,self.a,self.body(),fixture.erp.now,fixture.erp.audit);dp.review(self.c,'driver-reject',{'id':r['id'],'version':1,'request_key':str(uuid.uuid4()),'note':'数量需核对'},'库管',fixture.erp.now,fixture.erp.audit);self.assertFalse(assets.report(self.c,'2020-01-02')['events']);self.assertEqual(dp.report(self.c,self.a,'2020-01-02')['requests'][0]['review_note'],'数量需核对')
  self.assertIn('delivery.schedule',access.defaults('物流负责人')['actions']);self.assertNotIn('finance.receivables',access.defaults('物流负责人')['modules'])
  for path in ['/api/assets','/api/factory/report','/api/inventory','/print/orders']:
   with self.assertRaises(auth.AuthError):access.authorize_read(path,{'role':'司机','permissions':access.defaults('管理员')})
  with self.assertRaises(auth.AuthError):access.authorize_authenticated('/api/assets/return-batch',{},'司机')

 def test_no_delivery_stays_on_selected_date_and_draft_lifecycle(self):
  r=dp.report(self.c,self.a,'2020-01-04',True);self.assertEqual(r['business_date'],'2020-01-04');self.assertEqual(r['trips'],[]);self.assertFalse(r['display_notice'])
  b=self.body(state='draft',lines=[],business_date='2020-01-04');draft=dp.submit(self.c,self.a,b,fixture.erp.now,fixture.erp.audit);self.assertEqual(draft['state'],'draft');self.assertFalse(dp.pending(self.c))
  options=dp.return_options(self.c,self.a,'2020-01-02');self.assertEqual({t['id'] for t in options['trips']},{'TA','TB'});self.assertNotIn('orders',options['trips'][0])
  b=self.body(id=draft['id'],version=draft['version'],state='pending',business_date='2020-01-04',source_date='2020-01-02',source_trip_id='TB',vehicle_id='V002');r=dp.submit(self.c,self.a,b,fixture.erp.now,fixture.erp.audit);self.assertEqual(r['trip'],'乙趟');self.assertEqual(r['driver'],'司机甲');self.assertEqual(r['source_vehicle_id'],'V002')
  back=dp.return_action(self.c,self.a,{'id':r['id'],'version':r['version'],'request_key':str(uuid.uuid4()),'action':'withdraw'},fixture.erp.now,fixture.erp.audit);self.assertEqual(back['state'],'draft');self.assertFalse(dp.pending(self.c))
  dp.return_action(self.c,self.a,{'id':back['id'],'version':back['version'],'request_key':str(uuid.uuid4()),'action':'delete'},fixture.erp.now,fixture.erp.audit);self.assertFalse(dp.report(self.c,self.a,'2020-01-04')['requests'])
 def test_confirmed_return_withdrawal_needs_warehouse(self):
  r=dp.submit(self.c,self.a,self.body(),fixture.erp.now,fixture.erp.audit);r=dp.review(self.c,'driver-confirm',{'id':r['id'],'version':r['version'],'request_key':str(uuid.uuid4())},'库管',fixture.erp.now,fixture.erp.audit)
  r=dp.return_action(self.c,self.a,{'id':r['id'],'version':r['version'],'request_key':str(uuid.uuid4()),'action':'withdraw','reason':'数量填错'},fixture.erp.now,fixture.erp.audit);self.assertEqual(r['state'],'withdraw_pending');self.assertEqual(len(assets.report(self.c,'2020-01-02')['events']),2)
  r=dp.review(self.c,'driver-confirm',{'id':r['id'],'version':r['version'],'request_key':str(uuid.uuid4())},'库管',fixture.erp.now,fixture.erp.audit);self.assertEqual(r['state'],'withdrawn');self.assertFalse(assets.report(self.c,'2020-01-02')['events'])
 def test_driver_weights_save_only_owned_original_weight_fields(self):
  o=json.loads(self.c.execute("SELECT payload FROM orders WHERE id='DRIVER-ORDER-0'").fetchone()[0]);o.update(state='dispatched',weight_confirmation=None,paid_cents=0,discount_cents=0,rounding_cents=0,return_credit_cents=0);self.c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),o['id']));l=next(l for l in o['lines'] if l['unit']=='筐');qty=l['actual_qty']
  b={'request_key':str(uuid.uuid4()),'order_id':o['id'],'version':o['version'],'lines':[{'product_id':l['product_id'],'driver':[{'count':qty,'gross':str(float(qty)*20),'tare':'1','note':'司机实称'}],'price':'0','actual_qty':'999'}]}
  result=dp.save_weights(self.c,self.a,b,fixture.erp.now,fixture.erp.audit,fixture.erp.weights,fixture.erp.save);self.assertEqual(dp.save_weights(self.c,self.a,b,fixture.erp.now,fixture.erp.audit,fixture.erp.weights,fixture.erp.save),result)
  saved=json.loads(self.c.execute('SELECT payload FROM orders WHERE id=?',(o['id'],)).fetchone()[0]);line=next(x for x in saved['lines'] if x['product_id']==l['product_id']);self.assertEqual(line['price'],l['price']);self.assertEqual(line['actual_qty'],l['actual_qty']);self.assertEqual(line['driver'][0]['note'],'司机实称');self.assertFalse(saved.get('weight_confirmation'))
  with self.assertRaises(auth.AuthError):dp.save_weights(self.c,self.b,{**b,'request_key':str(uuid.uuid4()),'version':result['version']},fixture.erp.now,fixture.erp.audit,fixture.erp.weights,fixture.erp.save)

 def test_driver_photo_save_and_owner_read(self):
  with patch.object(dp,'PHOTO_ROOT',Path(self.tmp.name)/'photos'):
   rel=dp.save_photo(self.c,self.a,'DRIVER-ORDER-0','weight',b'\xff\xd8test','image/jpeg','2020-01-02')
   self.assertTrue(Path(rel).exists())
   self.assertEqual(dp.photo(self.c,self.a,'DRIVER-ORDER-0','weight'),{'data':b'\xff\xd8test','mime':'image/jpeg'})
   self.assertEqual(dp.photo(self.c,self.admin,'DRIVER-ORDER-0','weight')['data'],b'\xff\xd8test')
   with self.assertRaises(auth.AuthError):dp.photo(self.c,self.b,'DRIVER-ORDER-0','weight')

 def test_half_basket_driver_weight_uses_one_whole_crate(self):
  o=json.loads(self.c.execute("SELECT payload FROM orders WHERE id='DRIVER-ORDER-0'").fetchone()[0]);o.update(state='dispatched',weight_confirmation=None,paid_cents=0,discount_cents=0,rounding_cents=0,return_credit_cents=0)
  line=next(l for l in o['lines'] if l['unit']=='筐');line.update(actual_qty='0.5',ordered_qty='0.5',driver=[])
  self.c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),o['id']))
  result=dp.save_weights(self.c,self.a,{'request_key':str(uuid.uuid4()),'order_id':o['id'],'version':o['version'],'lines':[{'product_id':line['product_id'],'driver':[{'count':'1','gross':'10','tare':'0'}]}]},fixture.erp.now,fixture.erp.audit,fixture.erp.weights,fixture.erp.save)
  saved=json.loads(self.c.execute('SELECT payload FROM orders WHERE id=?',(o['id'],)).fetchone()[0]);got=next(l for l in saved['lines'] if l['product_id']==line['product_id'])
  self.assertEqual(got['actual_qty'],'0.5');self.assertEqual(got['driver_count'],'1');self.assertEqual(got['driver_net'],'10')
