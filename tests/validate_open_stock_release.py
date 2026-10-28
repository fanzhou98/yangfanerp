"""Synthetic v0.86 -> v0.87 candidate; no production database access."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib,sys,ast
from validate_resource_release import run,unpack,digest
from validate_stock_history_release import SEED,SNAP
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/未日结收发存-v0.87.0'
QUERY='''
from pathlib import Path
import sys,json,server,inventory as inv,open_stock_query as q
server.DB=Path(sys.argv[1])
with server.connect() as c:
 c.execute('BEGIN');first=q.history(c,all_dates=True,page_size=2);rows=list(first['rows'])
 for page in range(2,first['pages']+1):
  chunk=q.history(c,all_dates=True,page_size=2,page=page);assert chunk['summary']==first['summary'];rows+=chunk['rows']
 assert len(rows)==first['total'] and len({(r['business_date'],r['product_id']) for r in rows})==len(rows)
 for row in rows:
  canonical=next(p for p in inv.stock(c,row['business_date'])['products'] if p['product_id']==row['product_id'])
  for key,value in canonical.items():
   if not row['stock_registered'] and key in ('production_qty','loss_qty'):assert row[key] is None
   else:assert row[key]==value,(key,row[key],value)
 assert not any(r['business_date']=='2026-10-21' for r in rows)
 assert any(r['business_date']=='2026-10-22' for r in rows)
 assert any(r['business_date']=='2026-10-24' for r in rows)
 print(json.dumps({'total':first['total'],'days':first['days'],'summary':first['summary']}))
'''
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='erp087-upgrade-') as folder:
  tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.86.0.tar.gz'
  if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.86.0.tar.gz'
  prior=unpack(previous,old);meta=unpack(ROOT/'output/releases/yangfan-erp-0.87.0.tar.gz',new);db=tmp/'synthetic.db'
  # Every pre-existing migration function must remain exactly the same AST.
  old_steps={n.name:ast.dump(n) for n in ast.parse((old/'migration_steps.py').read_text()).body if isinstance(n,ast.FunctionDef)}
  new_steps={n.name:ast.dump(n) for n in ast.parse((new/'migration_steps.py').read_text()).body if isinstance(n,ast.FunctionDef)}
  assert all(new_steps.get(k)==v for k,v in old_steps.items())
  run(['-c',SEED,str(db)],old);baseline=json.loads(run(['-c',SNAP,str(db)],old));before,counts=digest(db)
  run(['ops/initialize_cloud.py','--database',str(db)],new);after,new_counts=digest(db);assert before==after and counts==new_counts
  assert baseline==json.loads(run(['-c',SNAP,str(db)],new))
  result=json.loads(run(['-c',QUERY,str(db)],new));checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
  run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)[0]==before;assert baseline==json.loads(run(['-c',SNAP,str(db)],new));assert result==json.loads(run(['-c',QUERY,str(db)],new))
  with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==69
  evidence={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':68,'schema_after':69,'sha256':hashlib.sha256((ROOT/'output/releases/yangfan-erp-0.87.0.tar.gz').read_bytes()).hexdigest(),'business_digest_before':before,'business_digest_after':after,'stock_fifo_raw_closings_identical':True,'old_migration_functions_unchanged':True,'complete_pages_equal_canonical':True,'closed_day_excluded_and_reopened_included':True,'repeat_upgrade_unchanged':True,'query':result,'check_db':checks,'business_check':business}
  OUT.mkdir(parents=True,exist_ok=True);(OUT/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in evidence.items() if k not in ('query','check_db','business_check')}))
