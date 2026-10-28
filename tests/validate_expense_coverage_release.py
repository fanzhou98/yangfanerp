"""Upgrade and irregular-bill/estimate drills on an isolated synthetic database."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib,sys
from validate_resource_release import run,unpack
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/跨月费用与暂估-v0.85.0'
SEED='''
from pathlib import Path
import sys,uuid,server,resources_costs as rc
server.DB=Path(sys.argv[1]);server.seed_demo=lambda:None;server.init_db(demo=True,convert_billing=True)
with server.connect(True) as c:
 op=rc.Operations(c,server.now,server.audit)
 op.expense({'request_key':str(uuid.uuid4()),'business_date':'2026-01-01','period':'2026-01','spread_months':12,'category':'rent','amount':'12000.01','handler':'合成会计','note':'原全年租金','partner':'合成房东'},'管理员')
 op.period({'month':'2026-01','version':0,'state':'closed','note':'原月份冻结快照'},'管理员')
'''
SNAP='''
from pathlib import Path
import sys,json,server,resources_costs as rc
server.DB=Path(sys.argv[1])
with server.connect() as c:print(json.dumps({'expenses':rc.rows(c,'indirect_expenses'),'periods':rc.rows(c,'resource_periods'),'fifo':rc.material_ledger(c,warehouse_details=True),'payments':rc.rows(c,'expense_payments')}))
'''
SCENARIO='''
from pathlib import Path
import sys,json,uuid,server,resources_costs as rc,expense_estimates as es,expense_coverage as coverage,expense_parties as ep,reporting
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 op=rc.Operations(c,server.now,server.audit);party=ep.save(c,{'request_key':str(uuid.uuid4()),'kind':'energy','name':'合成水务公司','version':0,'active':True},'管理员',server.now,server.audit)
 base={m:reporting.expense_summary(c,m)['total_cents'] for m in ('2026-08','2026-09','2026-10')}
 def body(start,end,amount):return {'request_key':str(uuid.uuid4()),'business_date':'2026-10-27','accrual_method':'service_days','service_start':start,'service_end':end,'service_account':'水表A','category':'water','amount':amount,'counterparty_mode':'expense-ledger-v1','counterparty_id':party['id'],'department':'共用','handler':'合成会计','note':'抄表及暂估核查'}
 for start,end,amount in [('2026-08-25','2026-08-31','60'),('2026-08-31','2026-09-30','300'),('2026-09-30','2026-10-31','310')]:es.save(c,body(start,end,amount),'管理员',server.now,server.audit)
 assert es.report(c,'2026-09')['estimated_cents']==30000
 def actual(start,end,amount):
  b=body(start,end,amount);p=coverage.preview(c,b);b['estimate_versions']=[{'id':e['id'],'version':e['version']} for e in p['estimate_candidates']];return op.expense(b,'管理员')
 first=actual('2026-08-25','2026-09-26','300');assert first['estimate_offset_cents']==32000 and first['estimate_difference_cents']==-2000
 assert reporting.expense_summary(c,'2026-08')['total_cents']==base['2026-08']+5625
 assert reporting.expense_summary(c,'2026-09')['total_cents']==base['2026-09']+28375
 assert es.report(c,'2026-09')['estimated_cents']==4000
 second=actual('2026-09-26','2026-10-24','280');assert second['coverage_days']==28 and second['estimate_offset_cents']==28000
 assert es.report(c,'2026-10')['estimated_cents']==7000
 original_estimates=[r[0] for r in c.execute('SELECT payload FROM expense_estimates ORDER BY id')]
 op.expense_review({'id':first['id'],'version':1,'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
 op.expense_payment({'id':first['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-27','amount':'300','method':'银行转账','payee':'合成水务公司','handler':'出纳','reference':'合成回单','note':'整笔实际账单付款'},'管理员')
 assert next(e for e in rc.expense_projection(c) if e['id']==first['id'])['outstanding_cents']==0
 op.void({'id':second['id'],'version':1,'ledger':'expense','reason':'账单撤回核查'},'管理员');assert es.report(c,'2026-10')['estimated_cents']==31000
 op.restore({'id':second['id'],'version':2,'ledger':'expense','reason':'核查后恢复'},'管理员');assert es.report(c,'2026-10')['estimated_cents']==7000
 assert original_estimates==[r[0] for r in c.execute('SELECT payload FROM expense_estimates ORDER BY id')]
 op.period({'month':'2026-08','version':0,'state':'closed','note':'冻结已核实8月成本'},'管理员')
 count=c.execute('SELECT COUNT(*) FROM expense_estimates').fetchone()[0]
 try:es.save(c,body('2026-08-25','2026-08-31','70'),'管理员',server.now,server.audit);raise AssertionError('closed month accepted')
 except ValueError as error:assert '结账' in str(error)
 assert c.execute('SELECT COUNT(*) FROM expense_estimates').fetchone()[0]==count
 print(json.dumps({'actual_bills':2,'estimate_records':3,'first_offset_cents':first['estimate_offset_cents'],'first_difference_cents':first['estimate_difference_cents'],'september_estimate_after_first':4000,'october_estimate_remaining':7000,'original_estimates_unchanged':True,'one_payment_no_duplicate_cost':True,'void_restore_reversible':True,'closed_month_blocked':True}))
'''

def digest(db,skip_new=False):
 with sqlite3.connect(db) as c:
  data={}
  for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
   if table.startswith(('sqlite_','auth_')) or table in ('audit','security_events','schema_migrations','meta') or skip_new and table=='expense_estimates':continue
   data[table]=sorted([list(r) for r in c.execute('SELECT * FROM "'+table+'"')],key=repr)
 return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='erp085-upgrade-') as folder:
  tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.84.0.tar.gz'
  if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.84.0.tar.gz'
  prior=unpack(previous,old);meta=unpack(ROOT/'output/releases/yangfan-erp-0.85.0.tar.gz',new);db=tmp/'synthetic.db'
  run(['-c',SEED,str(db)],old);snapshot=json.loads(run(['-c',SNAP,str(db)],old));before=digest(db,True)
  run(['ops/initialize_cloud.py','--database',str(db)],new);after=digest(db,True);assert before==after;assert snapshot==json.loads(run(['-c',SNAP,str(db)],new))
  scenario=json.loads(run(['-c',SCENARIO,str(db)],new));post=digest(db)
  checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
  run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)==post
  with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==67
  result={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':66,'schema_after':67,'sha256':hashlib.sha256((ROOT/'output/releases/yangfan-erp-0.85.0.tar.gz').read_bytes()).hexdigest(),'original_business_digest_before':before,'original_business_digest_after':after,'original_annual_bill_frozen_month_and_fifo_unchanged':True,'repeat_upgrade_unchanged':True,'scenario':scenario,'check_db':checks,'business_check':business}
  OUT.mkdir(parents=True,exist_ok=True);(OUT/'release-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('check_db','business_check')}))
