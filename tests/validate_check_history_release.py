"""Synthetic saved evidence/version upgrade, without touching real business data."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib,sys
from validate_resource_release import run,unpack,digest
from validate_stock_history_release import SEED as STOCK_SEED,SNAP as STOCK_SNAP
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/库存核对历史-v0.83.0';sys.path.insert(0,str(ROOT))
SEED=STOCK_SEED+'''
import inventory_reconciliation as check
expected={}
def evidence(day,pre,post):
 with server.connect(True) as c:
  report=check.report(c,day);unit=c.execute("SELECT unit FROM products WHERE id='P001'").fetchone()[0]
  b={'business_date':day,'version':report['version'],'request_key':str(uuid.uuid4()),'source_fingerprint':report['source_fingerprint'],'sources_checked':True,'handler':'合成核对经办','note':'保存时实发快照核查','products':[{'product_id':'P001','unit':unit,'pre_qty':pre,'post_qty':post,'post_in_qty':'0','post_out_qty':'0','post_source':'manual'}]}
  result=check.save(c,b,'管理员',server.now,server.audit);expected[day+'/'+str(result['version'])]=next(p for p in check.report(c,day)['products'] if p['product_id']=='P001')
def shipment(qty):
 with server.connect(True) as c:
  order=server.get_order(c,o['id']);lines=copy.deepcopy(order['lines']);lines[0].update(actual_qty=str(qty),driver=[{'gross':str(qty*15),'count':str(qty),'tare':'0'}])
  b={'action':'shipment','order_id':order['id'],'version':order['version'],'request_key':str(uuid.uuid4()),'reason':'合成来源再核查','evidence_checked':True,'physical_count_confirmed':True,'inventory_revision':inv.revision(c),'lines':lines}
  corr.save(c,b,'会计',server.now,server.audit,server.normalize_order,server.save,server.get_order)
evidence('2026-10-21','20','11');shipment(7);evidence('2026-10-21','20','11');shipment(6);evidence('2026-10-22','11','11')
Path(str(server.DB)+'.expected.json').write_text(json.dumps(expected))
'''
SNAP='''
from pathlib import Path
import sys,json,server,inventory_reconciliation as check,inventory as inv,resources_costs as rc,order_corrections as corr
server.DB=Path(sys.argv[1])
with server.connect() as c:
 print(json.dumps({'reports':{d:check.report(c,d) for d in ('2026-10-21','2026-10-22')},'records':rc.rows(c,'trade_records'),'stocks':{d:inv.stock(c,d) for d in ('2026-10-21','2026-10-22','2026-10-24')},'closings':rc.rows(c,'stock_closings'),'fifo':rc.material_ledger(c,warehouse_details=True)}))
'''
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='erp083-upgrade-') as folder:
  tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.82.0.tar.gz'
  if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.82.0.tar.gz'
  prior=unpack(previous,old);meta=unpack(ROOT/'output/releases/yangfan-erp-0.83.0.tar.gz',new);db=tmp/'synthetic.db'
  run(['-c',SEED,str(db)],old);expected=json.loads(Path(str(db)+'.expected.json').read_text());baseline=json.loads(run(['-c',SNAP,str(db)],old));before,counts=digest(db)
  run(['ops/initialize_cloud.py','--database',str(db)],new);after,new_counts=digest(db);assert before==after and counts==new_counts;assert baseline==json.loads(run(['-c',SNAP,str(db)],new))
  result=json.loads(run(['-c',"""
from pathlib import Path
import sys,json,server,check_history as q
server.DB=Path(sys.argv[1]);r={}
with server.connect() as c:
 c.execute('BEGIN');first=q.history(c,all_dates=True,versions='all',page_size=1);rows=list(first['rows'])
 for page in range(2,first['pages']+1):rows+=q.history(c,all_dates=True,versions='all',page_size=1,page=page)['rows']
 r={'rows':rows,'latest':q.history(c,all_dates=True),'details':{p['business_date']+'/'+str(p['version']):q.record(c,p['business_date'],p['version']) for p in rows}}
 print(json.dumps(r))
""",str(db)],new))
  assert len(result['rows'])==len(expected)==3;assert result['latest']['total']==2
  for row in result['rows']:
   key=row['business_date']+'/'+str(row['version']);old_row=expected[key]
   for k in ('pre_qty','post_qty','post_in_qty','post_out_qty','expected_qty','shipped_qty','difference_qty'):assert row[k]==old_row[k],(key,k,row[k],old_row[k])
   assert result['details'][key]['version']==row['version']
  assert baseline['reports']['2026-10-21']['source_changed'];assert next(p for p in baseline['reports']['2026-10-21']['products'] if p['product_id']=='P001')['difference_qty']=='-3'
  checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
  run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)[0]==before
  with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==65
  evidence={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':64,'schema_after':65,'sha256':hashlib.sha256((ROOT/'output/releases/yangfan-erp-0.83.0.tar.gz').read_bytes()).hexdigest(),'business_digest_before':before,'business_digest_after':after,'saved_sources_and_versions_unchanged':True,'saved_history_matches_original_report_at_save_time':True,'live_change_detection_unchanged':True,'global_stock_and_fifo_identical':True,'original_counts_and_next_opening_identical':True,'repeat_upgrade_unchanged':True,'check_db':checks,'business_check':business}
  OUT.mkdir(parents=True,exist_ok=True);(OUT/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in evidence.items() if k not in ('check_db','business_check')}))
