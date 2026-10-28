"""Synthetic v0.81 -> v0.82 upgrade: preserve immutable counts and restated shipments."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib,sys
from validate_resource_release import run,unpack,digest
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/成品日结历史-v0.82.0'
sys.path.insert(0,str(ROOT))
SEED='''
from pathlib import Path
import sys,json,uuid,copy,server,inventory as inv,order_corrections as corr
server.DB=Path(sys.argv[1]);server.seed_demo=lambda:None;server.init_db(demo=True,convert_billing=True)
def epoch(body):
 with server.connect() as c:body['_data_epoch']=server.business_epoch(c)
 return body
mutate=server.mutate;warehouse=server.save_warehouse
server.mutate=lambda action,body,*args,**kwargs:mutate(action,epoch(body),*args,**kwargs)
server.save_warehouse=lambda body,*args,**kwargs:warehouse(epoch(body),*args,**kwargs)
with server.connect(True) as c:c.execute('DELETE FROM orders');c.execute('DELETE FROM receipts')
def op(method,body):
 with server.connect(True) as c:return getattr(inv.Operations(c,server.now,server.audit),method)(body,'管理员')
day='2026-10-21'
o=server.mutate('order',{'customer_id':'C001','business_date':day,'batch':'候选历史更正','workflow_version':1,'dispatch_required':True,'lines':[{'product_id':'P001','ordered_qty':'10','actual_qty':'0','price':'3','driver':[],'customer':[]}]},'管理员')
d=server.bootstrap();r=server.save_warehouse({'business_date':day,'version':0,'inventory_revision':d['inventory_revision'],'stage':'confirm_dispatch','evidence_checked':True,'stock':[{'product_id':p['id'],'existing_qty':'20','produced_qty':'0'} for p in d['products']],'allocations':[{'order_id':o['id'],'product_id':'P001','qty':'10','ordered_qty':'10','mode':'manual'}],'order_versions':{o['id']:o['version']},'customers':[]},'管理员');o=r['orders'][0]
o['lines'][0]['driver']=[{'gross':'150','count':'10','tare':'0'}];o=server.mutate('order',o,'管理员',o['id']);o=server.mutate('confirm-weight',{'version':o['version'],'evidence_checked':True},'管理员',o['id']);o=server.mutate('settle',{'version':o['version'],'mode':'driver'},'管理员',o['id'])
with server.connect() as c:snapshot=inv.stock(c,day)
d=server.bootstrap();plan=next(p for p in d['warehouse_plans'] if p['business_date']==day)
op('close',{'business_date':day,'version':0,'inventory_revision':d['inventory_revision'],'plan_version':plan['version'],'evidence_checked':True,'counts':[{'product_id':p['product_id'],'counted_qty':'11' if p['product_id']=='P001' else p['book_qty'],'reason':'合成盘点差异'} for p in snapshot['products']]})
lines=copy.deepcopy(o['lines']);lines[0].update(actual_qty='8',driver=[{'gross':'120','count':'8','tare':'0'}])
b={'action':'shipment','order_id':o['id'],'version':o['version'],'request_key':str(uuid.uuid4()),'reason':'合成更正发货','evidence_checked':True,'physical_count_confirmed':True,'inventory_revision':server.bootstrap()['inventory_revision'],'lines':lines}
with server.connect(True) as c:corr.save(c,b,'会计',server.now,server.audit,server.normalize_order,server.save,server.get_order)
d=server.bootstrap();closed=next(x for x in d['stock_closings'] if x['business_date']==day);counts={p['product_id']:p['counted_qty'] for p in closed['products']}
server.save_warehouse({'business_date':'2026-10-22','opening_source_date':day,'opening_close_version':1,'version':0,'inventory_revision':d['inventory_revision'],'stage':'stock','stock':[{'product_id':p['id'],'existing_qty':counts[p['id']],'produced_qty':'0'} for p in d['products']],'allocations':[],'order_versions':{},'customers':[]},'管理员')
d=server.bootstrap();r=server.save_warehouse({'business_date':'2026-10-24','version':0,'inventory_revision':d['inventory_revision'],'stage':'stock','stock':[{'product_id':p['id'],'existing_qty':'20','produced_qty':'0'} for p in d['products']],'allocations':[],'order_versions':{},'customers':[]},'管理员')
d=server.bootstrap();plan=next(p for p in d['warehouse_plans'] if p['business_date']=='2026-10-24')
with server.connect() as c:snapshot=inv.stock(c,'2026-10-24')
r=op('close',{'business_date':'2026-10-24','version':0,'inventory_revision':d['inventory_revision'],'plan_version':plan['version'],'evidence_checked':True,'counts':[{'product_id':p['product_id'],'counted_qty':p['book_qty'],'reason':''} for p in snapshot['products']]});op('close',{'business_date':'2026-10-24','version':r['version'],'action':'reopen','reason':'合成撤销日结'})
'''
SNAP='''
from pathlib import Path
import sys,json,server,inventory as inv,resources_costs as rc,order_corrections as corr
server.DB=Path(sys.argv[1])
with server.connect() as c:
 raw=inv.rows(c,'stock_closings')
 print(json.dumps({'raw':raw,'effective':[corr.restated_closing(c,r) for r in raw],'stocks':{d:inv.stock(c,d) for d in ('2026-10-21','2026-10-22','2026-10-24')},'fifo':rc.material_ledger(c,warehouse_details=True)}))
'''
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='erp082-upgrade-') as folder:
  tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.81.0.tar.gz'
  if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.81.0.tar.gz'
  prior=unpack(previous,old);meta=unpack(ROOT/'output/releases/yangfan-erp-0.82.0.tar.gz',new);db=tmp/'synthetic.db'
  run(['-c',SEED,str(db)],old);baseline=json.loads(run(['-c',SNAP,str(db)],old));before,counts=digest(db)
  run(['ops/initialize_cloud.py','--database',str(db)],new);after,new_counts=digest(db);assert before==after and counts==new_counts
  assert baseline==json.loads(run(['-c',SNAP,str(db)],new))
  result=json.loads(run(['-c',"""
from pathlib import Path
import sys,json,server,stock_history as q
server.DB=Path(sys.argv[1])
with server.connect() as c:
 c.execute('BEGIN');first=q.history(c,all_dates=True,page_size=2);rows=list(first['rows'])
 for page in range(2,first['pages']+1):rows+=q.history(c,all_dates=True,page_size=2,page=page)['rows']
 print(json.dumps({'rows':rows,'summary':first['quantities']}))
""",str(db)],new))
  expected={(r['business_date'],p['product_id']):p for r in baseline['effective'] for p in r['products']};assert len(result['rows'])==len(expected)
  import stock_history as q
  for r in result['rows']:
   p=expected[(r['business_date'],r['product_id'])]
   for field in q.FIELDS:assert r[field]==p.get(field),(r['business_date'],field,r[field],p.get(field))
  assert all(qty['count']==1 for qty in result['summary'])
  checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
  run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)[0]==before
  with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==64
  evidence={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':63,'schema_after':64,'sha256':hashlib.sha256((ROOT/'output/releases/yangfan-erp-0.82.0.tar.gz').read_bytes()).hexdigest(),'business_digest_before':before,'business_digest_after':after,'global_stock_and_fifo_identical':True,'original_counts_and_next_opening_identical':True,'shipment_restatement_identical':True,'complete_pages_equal_canonical':True,'reopened_excluded_from_summary':True,'repeat_upgrade_unchanged':True,'check_db':checks,'business_check':business}
  OUT.mkdir(parents=True,exist_ok=True);(OUT/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in evidence.items() if k not in ('check_db','business_check')}))
