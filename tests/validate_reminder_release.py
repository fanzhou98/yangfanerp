"""Synthetic v0.93.0 -> v0.93.2, keeping operations and immutable sources unchanged."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib,sys,ast
from validate_resource_release import run,unpack,digest
from validate_stock_history_release import SEED as STOCK_SEED,SNAP as STOCK_SNAP
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/提醒时机与结果弹窗-v0.93.1'
ADD='''
from pathlib import Path
import sys,json,uuid,server,trade,assets,resources_costs as rc
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 day='2026-10-22';plan={'business_date':day,'version':1,'trips':[{'id':'HISTORY-TRIP','name':'原配送趟次','vehicle_name':'原车','driver':'原司机'}],'assignments':[{'market_id':'M001','trip_id':'HISTORY-TRIP'}]};c.execute('INSERT INTO dispatch_plans VALUES(?,?)',(day,rc.dump(plan)))
 def save(kind,body):return trade.save(c,kind,{'request_key':str(uuid.uuid4()),**body},'管理员',server.now,server.audit)
 trip=save('trip',{'business_date':day,'trip_id':'HISTORY-TRIP','partner':'历史运输公司','rate':'120.50','note':'实际配送依据'})
 group=trade.transport_report(c,'2026-10')['groups'][0];save('transport-issue',{'month':'2026-10','partner':'历史运输公司','handler':'经办人','source_fingerprint':group['source_fingerprint']})
 order=json.loads(c.execute('SELECT payload FROM orders LIMIT 1').fetchone()[0]);save('feedback',{'order_id':order['id'],'order_version':order['version'],'product_id':'P001','received_qty':'7','feedback_date':'2026-10-23','note':'客户实际反馈'})
 types=trade.crate_types(c)
 if not types:
  types=[assets.save(c,'asset',{'request_key':'history-type','name':'合成历史框','category':'周转筐'},'管理员',server.now,server.audit)]
 aid=types[0]['id'];assets.save(c,'movement',{'request_key':'history-return','asset_id':aid,'business_date':'2026-10-23','movement':'return','qty':'3','driver':'原司机','note':'历史未关联客户回筐'},'管理员',server.now,server.audit)
 for i,state in enumerate(('pending','confirmed','withdraw_pending','withdrawn','rejected','draft')):
  r={'id':'HISTORY-REQUEST-'+str(i),'version':1,'business_date':'2026-10-23','state':state,'driver':'原司机','lines':[{'asset_id':aid,'asset_name':types[0]['name'],'qty':2}],'note':'合成填报当前状态'};c.execute('INSERT INTO driver_return_requests VALUES(?,?,?)',(r['id'],r['id'],rc.dump(r)))
'''
SNAP='''
from pathlib import Path
import sys,json,server,trade,resources_costs as rc
server.DB=Path(sys.argv[1])
with server.connect() as c:
 report=trade.transport_report(c,'2026-10')
 for group in report['groups']:
  group.pop('pending_count',None);group.pop('ready_count',None);group.pop('group_id',None);group.pop('provider_id',None);group.pop('completed_count',None)
 for document in report['documents']:
  for key in ('paid_cents','outstanding_cents','payment_status','expense_version','can_reopen'):document.pop(key,None)
 for key in ('providers','quotes','exceptions'):report.pop(key,None)
 print(json.dumps({'transport':report,'customer':trade.customer_crates(c,'C001','2026-10-23'),'raw':{t:rc.rows(c,t) for t in ('trade_records','asset_records','driver_return_requests','indirect_expenses')}}))
'''
QUERY='''
from pathlib import Path
import sys,json,server,delivery_query as q,resources_costs as rc
server.DB=Path(sys.argv[1])
result={}
with server.connect() as c:
 c.execute('BEGIN')
 for kind in q.SOURCES:
  first=q.history(c,kind=kind,all_dates=True,page_size=2,financial=True);rows=list(first['rows'])
  for page in range(2,first['pages']+1):
   chunk=q.history(c,kind=kind,all_dates=True,page_size=2,page=page,financial=True);assert chunk['summary']==first['summary'];rows+=chunk['rows']
  assert len(rows)==first['total']==len({r['id'] for r in rows})
  table,record_kind,_=q.SOURCES[kind];original=[r for r in rc.rows(c,table) if (not record_kind or r['kind']==record_kind) and (kind!='requests' or r['state'] in q.STATES['requests'])]
  assert {r['id'] for r in rows}=={r['id'] for r in original}
  for r in original:assert q.detail(c,kind,r['id'],financial=True)['record']==q.safe_record(kind,r,True)
  result[kind]={'total':first['total'],'summary':first['summary']}
 print(json.dumps(result))
'''
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='erp091-upgrade-') as folder:
  tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.93.0.tar.gz'
  if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.93.0.tar.gz'
  candidate=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'output/releases/yangfan-erp-0.93.2.tar.gz'
  prior=unpack(previous,old);meta=unpack(candidate,new);db=tmp/'synthetic.db'
  old_ast={n.name:ast.dump(n) for n in ast.parse((old/'migration_steps.py').read_text()).body if isinstance(n,ast.FunctionDef)};new_ast={n.name:ast.dump(n) for n in ast.parse((new/'migration_steps.py').read_text()).body if isinstance(n,ast.FunctionDef)};assert all(new_ast.get(k)==v for k,v in old_ast.items())
  run(['-c',STOCK_SEED,str(db)],old);run(['-c',ADD,str(db)],old)
  baseline=json.loads(run(['-c',SNAP,str(db)],old));stock=json.loads(run(['-c',STOCK_SNAP,str(db)],old));before,counts=digest(db)
  run(['ops/initialize_cloud.py','--database',str(db)],new);after,new_counts=digest(db);assert before==after and counts==new_counts;assert baseline==json.loads(run(['-c',SNAP,str(db)],new));assert stock==json.loads(run(['-c',STOCK_SNAP,str(db)],new))
  result=json.loads(run(['-c',QUERY,str(db)],new));checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
  run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)[0]==before;assert baseline==json.loads(run(['-c',SNAP,str(db)],new));assert result==json.loads(run(['-c',QUERY,str(db)],new))
  with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==70
  evidence={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':70,'schema_after':70,'sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),'business_digest_before':before,'business_digest_after':after,'stock_fifo_closings_customer_balances_transport_unchanged':True,'old_migrations_unchanged':True,'five_histories_complete_pages_match_sources':True,'repeat_upgrade_unchanged':True,'query':result,'check_db':checks,'business_check':business};OUT.mkdir(parents=True,exist_ok=True);(OUT/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in evidence.items() if k not in ('query','check_db','business_check')}))
