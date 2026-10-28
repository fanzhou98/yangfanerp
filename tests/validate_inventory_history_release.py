"""Synthetic previous-release upgrade: preserve stock, return credit and frozen closing."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib
from validate_resource_release import run,unpack,digest
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/库存退货加工历史-v0.80.0'
SEED='''
import sys,uuid,json
from datetime import date,timedelta
from pathlib import Path
import server,inventory as inv
server.DB=Path(sys.argv[1]);server.seed_demo=lambda:None;server.init_db(demo=True,convert_billing=True)
with server.connect(True) as c:c.execute('DELETE FROM orders');c.execute('DELETE FROM receipts')
def op(method,body,role='库管'):
 with server.connect(True) as c:
  if method in ('process','process_update'):body.setdefault('inventory_revision',inv.revision(c))
  return getattr(inv.Operations(c,server.now,server.audit),method)(body,role)
def plan(day):
 data=server.bootstrap();old=next((p for p in data['warehouse_plans'] if p['business_date']==day),{})
 previous=(date.fromisoformat(day)-timedelta(days=1)).isoformat();closing=next((r for r in data['stock_closings'] if r['business_date']==previous and r['state']=='closed'),None)
 counts={p['product_id']:p['counted_qty'] for p in closing['products']} if closing else {}
 body={'business_date':day,'version':old.get('version',0),'inventory_revision':data['inventory_revision'],'stock':[{'product_id':p['id'],'existing_qty':counts.get(p['id'],'10'),'produced_qty':'5'} for p in data['products']],'allocations':[],'customers':[],'order_versions':{}}
 with server.connect() as c:body['_data_epoch']=server.business_epoch(c)
 if closing:body.update(opening_source_date=previous,opening_close_version=closing['version'])
 return server.save_warehouse(body,'库管')
def ret(**extra):return op('create_return',{'received_date':'2026-10-21','customer_id':'C001','product_id':'P001','qty':'1','net_kg':'10','condition':'spoiled','reason':'候选退货','source_note':'合成来源凭据','request_key':str(uuid.uuid4()),'received_checked':True,**extra})
def action(r,act,role='库管',**extra):return op('return_action',{'id':r['id'],'version':r['version'],'action':act,**extra},role)
plan('2026-10-21');ret()
r=ret();r=action(r,'account','会计',account_date='2026-10-21',account_qty='1',price='1',note='合成核价凭据',price_checked=True);r=action(r,'review','出纳',evidence_checked=True,note='核对合成凭据');r=action(r,'refund','出纳',refund_date='2026-10-21',amount='0.40',evidence_checked=True,method='现金',note='部分退款合成凭据')
r=ret(product_id='P004',qty='2',net_kg='20');r=action(r,'dispose',business_date='2026-10-21',kind='reprocess',qty='2',net_kg='20',handler='合成库管',note='检验后转加工',inspection_checked=True,inspection_note='合成检验记录')
bid=r['disposals'][0]['processing_batch_id']
with server.connect() as c:snapshot=inv.stock(c,'2026-10-21')
data=server.bootstrap();p=next(p for p in data['warehouse_plans'] if p['business_date']=='2026-10-21')
op('close',{'business_date':'2026-10-21','version':0,'inventory_revision':data['inventory_revision'],'plan_version':p['version'],'evidence_checked':True,'counts':[{'product_id':p['product_id'],'counted_qty':p['book_qty'],'reason':''} for p in snapshot['products']]})
plan('2026-10-22')
op('process_update',{'id':bid,'version':1,'business_date':'2026-10-22','product_id':'P004','input_kg':'20','outputs':[{'product_id':'P005','qty':'3','net_kg':'18'}]})
r=ret(received_date='2026-10-22');action(r,'void',reason='误登作废合成凭据')
op('process',{'request_key':str(uuid.uuid4()),'business_date':'2026-10-22','product_id':'P004','input_kg':'5','outputs':[{'product_id':'P005','qty':'1','net_kg':'4'}]})
'''
SNAP='''
from pathlib import Path
import sys,json,server,inventory as i
server.DB=Path(sys.argv[1])
with server.connect() as c:
 print(json.dumps({'returns':i.rows(c,'sales_returns'),'processing':i.rows(c,'processing_batches'),'stock21':i.stock(c,'2026-10-21'),'stock22':i.stock(c,'2026-10-22'),'frozen':i.rows(c,'stock_closings')}))
'''
with tempfile.TemporaryDirectory(prefix='erp080-upgrade-') as folder:
 tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.79.0.tar.gz'
 if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.79.0.tar.gz'
 prior=unpack(previous,old);meta=unpack(ROOT/'output/releases/yangfan-erp-0.80.0.tar.gz',new);db=tmp/'synthetic.db'
 run(['-c',SEED,str(db)],old);baseline=json.loads(run(['-c',SNAP,str(db)],old));before,counts=digest(db)
 run(['ops/initialize_cloud.py','--database',str(db)],new);after,after_counts=digest(db);assert before==after and counts==after_counts
 assert baseline==json.loads(run(['-c',SNAP,str(db)],new))
 result=json.loads(run(['-c',"""
from pathlib import Path
import sys,json,server,inventory_query as q
server.DB=Path(sys.argv[1]);values={}
with server.connect() as c:
 c.execute('BEGIN')
 for kind in ('returns','processing'):
  r=q.history(c,kind=kind,all_dates=True,page_size=2);rows=list(r['rows'])
  for page in range(2,r['pages']+1):rows+=q.history(c,kind=kind,all_dates=True,page_size=2,page=page)['rows']
  values[kind]=rows
print(json.dumps(values))
""",str(db)],new))
 for kind,field in [('returns','received_date'),('processing','business_date')]:assert result[kind]==sorted(baseline[kind],key=lambda r:(r[field],r['id']),reverse=True)
 checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
 run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)[0]==before
 with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==62
 evidence={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':61,'schema_after':62,'sha256':hashlib.sha256((ROOT/'output/releases/yangfan-erp-0.80.0.tar.gz').read_bytes()).hexdigest(),'business_digest_before':before,'business_digest_after':after,'global_stock_identical':True,'frozen_closing_identical':True,'return_finance_and_processing_identical':True,'new_query_complete_pages_identical':True,'repeat_upgrade_unchanged':True,'check_db':checks,'business_check':business}
 OUT.mkdir(exist_ok=True,parents=True);(OUT/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in evidence.items() if k not in ('check_db','business_check')}))
