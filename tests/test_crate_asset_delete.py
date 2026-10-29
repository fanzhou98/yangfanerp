import json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import assets,resources_costs as rc
import test_workflow as fixture


class AssetDeleteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(fixture.erp,'DB',Path(self.tmp.name)/'assets.db');self.patch.start();fixture.erp.init_db();self.ctx=fixture.erp.connect(True);self.c=self.ctx.__enter__()
 def tearDown(self):
  self.c.rollback();self.ctx.__exit__(None,None,None);self.patch.stop();self.tmp.cleanup()
 def save(self,kind,body,role='管理员'):
  return assets.save(self.c,kind,{'request_key':str(uuid.uuid4()),**body},role,fixture.erp.now,fixture.erp.audit)
 def asset(self,**extra):return self.save('asset',{'name':'可删除的测试框','category':'周转筐',**extra})
 def delete(self,a,**extra):return self.save('delete-asset',{'id':a['id'],'version':a['version'],**extra})
 def payload(self,table,value):
  # Synthetic rows only; every relevant table keeps its actual migration schema.
  columns=list(self.c.execute('PRAGMA table_info('+table+')'));keys=[];values=[]
  for col in columns:
   name=col[1]
   if name=='payload':item=rc.dump(value)
   elif col[5] or col[3] and col[4] is None:item=1 if 'INT' in col[2] else 'fixture-'+uuid.uuid4().hex
   else:continue
   keys.append(name);values.append(item)
  self.c.execute('INSERT INTO '+table+'('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',values)
 def test_unused_delete_permission_version_and_idempotency(self):
  a=self.asset();self.assertTrue(assets.deletion_status(self.c,a['id'])['can_delete'])
  with self.assertRaisesRegex(ValueError,'权限|允许'):self.save('delete-asset',{'id':a['id'],'version':1},'库管')
  with self.assertRaisesRegex(ValueError,'已更新'):self.delete(a,version=0)
  key='delete-fixture';body={'id':a['id'],'version':1,'request_key':key};deleted=self.save('delete-asset',body)
  self.assertTrue(deleted['deleted']);self.assertIsNone(self.c.execute('SELECT id FROM asset_records WHERE id=?',(a['id'],)).fetchone())
  self.assertEqual(deleted,self.save('delete-asset',body))
  with self.assertRaisesRegex(ValueError,'提交编号已使用'):self.save('delete-asset',{**body,'version':2})
 def test_references_are_exact_identifiers(self):
  a=self.asset();self.payload('driver_return_requests',{'note':a['id'],'asset_id':a['id']+'-different','asset_ids':[a['id']+'-different']})
  self.assertTrue(assets.deletion_status(self.c,a['id'])['can_delete']);self.delete(a)
 def test_old_configuration_receipts_do_not_block_after_unlinking(self):
  a=self.asset();old_mapping={'id':'old-map','kind':'mapping','product_id':'P-LARGE','asset_id':a['id']}
  self.payload('asset_submissions',old_mapping)
  fixture.erp.audit(self.c,'管理员','资产登记','old-map',old_mapping,{**old_mapping,'asset_id':'P-LONG'})
  child={'id':'old-child','kind':'asset','category':'周转筐','parent_asset_id':a['id']}
  self.payload('asset_submissions',child)
  fixture.erp.audit(self.c,'管理员','资产登记','old-child',child,None)
  for entity in ('crate_packaging_catalog_v1','product_crate_attributes','product_crate_tares'):
   fixture.erp.audit(self.c,'管理员','维护配置',entity,{'rules':[{'asset_id':a['id']}]},{'rules':[]})
  self.assertTrue(assets.deletion_status(self.c,a['id'])['can_delete']);self.delete(a)
 def test_parent_and_configuration_references(self):
  parent=self.asset();self.asset(name='子属性',parent_asset_id=parent['id'])
  self.assertIn('所属框型下仍有属性',assets.deletion_status(self.c,parent['id'])['configuration_reasons'])
  with self.assertRaisesRegex(ValueError,'解除'):self.delete(parent)
  a=self.asset()
  for key,value in [('product_crate_attributes',{'P-LARGE':[a['id']]}),('product_crate_tares',{'P-LARGE':{a['id']:'1.2'}}),('crate_packaging_catalog_v1',{'rules':[{'asset_id':a['id']}]})]:
   with self.subTest(key=key):
    self.c.execute('SAVEPOINT config_case');self.c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,rc.dump(value)))
    self.assertFalse(assets.deletion_status(self.c,a['id'])['can_delete'])
    with self.assertRaisesRegex(ValueError,'解除'):self.delete(a)
    self.c.execute('ROLLBACK TO config_case');self.c.execute('RELEASE config_case')
  self.assertTrue(assets.deletion_status(self.c,a['id'])['can_delete'])
  self.c.execute('INSERT INTO customer_crate_tares VALUES(?,?,?,?,?)',('customer','P-LARGE',a['id'],'1',1))
  self.assertIn('客户框型皮重设置',assets.deletion_status(self.c,a['id'])['configuration_reasons'])
 def test_history_and_nested_archive_payload_block_delete(self):
  a=self.asset()
  for table in ('orders','trade_records','trade_submissions','archived_orders','driver_return_requests','driver_return_submissions','driver_weight_submissions','order_corrections','order_correction_submissions','statement_documents','trial_archives'):
   with self.subTest(table=table):
    self.c.execute('SAVEPOINT history_case');value={'lines':[{'asset_id':a['id'],'qty':1}]}
    if table=='trial_archives':value={'format':'day-reset-v1','tables':{'orders':[{'id':'old-order','payload':rc.dump(value)}]}}
    self.payload(table,value);self.assertTrue(assets.deletion_status(self.c,a['id'])['history_reasons'])
    with self.assertRaisesRegex(ValueError,'只能停用'):self.delete(a)
    self.c.execute('ROLLBACK TO history_case');self.c.execute('RELEASE history_case')
  event=self.save('movement',{'asset_id':a['id'],'business_date':'2020-01-01','movement':'receipt','qty':1})
  self.save('void',{'id':event['id'],'version':1,'note':'测试作废'})
  with self.assertRaisesRegex(ValueError,'只能停用'):self.delete(a)
 def test_report_projection_is_read_only(self):
  a=self.asset();before=self.c.total_changes;queries=[];self.c.set_trace_callback(queries.append)
  try:r=assets.report(self.c,'2020-01-01')
  finally:self.c.set_trace_callback(None)
  self.assertEqual(before,self.c.total_changes)
  self.assertFalse(any(q.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE')) for q in queries))
  for key in ('assets','crates'):
   row=next(x for x in r[key] if x['id']==a['id']);self.assertTrue(row['can_delete']);self.assertEqual(row['delete_reason'],'')


if __name__=='__main__':unittest.main()
