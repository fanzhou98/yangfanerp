"""v0.85 -> v0.86 candidate upgrade using synthetic bills and frozen month."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib
from validate_resource_release import run,unpack
from validate_expense_coverage_release import digest,SNAP
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/不定期费用月结-v0.86.0'
SEED='''
from pathlib import Path
import sys,uuid,server,resources_costs as rc,expense_estimates as es
server.DB=Path(sys.argv[1]);server.seed_demo=lambda:None;server.init_db(demo=True,convert_billing=True)
with server.connect(True) as c:
 op=rc.Operations(c,server.now,server.audit)
 op.expense({'request_key':str(uuid.uuid4()),'business_date':'2026-01-01','period':'2026-01','spread_months':12,'category':'rent','amount':'12000.01','handler':'合成会计','note':'原全年租金','partner':'合成房东'},'管理员')
 op.period({'month':'2026-01','version':0,'state':'closed','note':'原月份冻结快照'},'管理员')
 b={'request_key':str(uuid.uuid4()),'business_date':'2026-09-26','category':'water','amount':'260','handler':'会计','note':'合成抄表账单','partner':'水务公司','service_account':'水表A','accrual_method':'service_days','service_start':'2026-08-31','service_end':'2026-09-26'}
 op.expense(b,'管理员')
 es.save(c,{**b,'request_key':str(uuid.uuid4()),'amount':'40','service_start':'2026-09-26','service_end':'2026-09-30'},'管理员',server.now,server.audit)
 op.period({'month':'2026-09','version':0,'state':'closed','note':'原版本手工暂估已确认'},'管理员')
'''
SCENARIO='''
from pathlib import Path
import sys,json,uuid,server,resources_costs as rc,expense_estimates as es,expense_coverage as coverage,expense_close as close,cost_allocation as ca,reporting
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 op=rc.Operations(c,server.now,server.audit)
 assert next(p for p in ca.categories(c) if p['id']=='water')['irregular_periodic']
 frozen=c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0]
 estimates=[r[0] for r in c.execute('SELECT payload FROM expense_estimates ORDER BY id')]
 b={'request_key':str(uuid.uuid4()),'business_date':'2026-10-24','category':'water','amount':'336','handler':'会计','note':'实际账单到单核实','partner':'水务公司','service_account':'水表A','accrual_method':'service_days','service_start':'2026-09-26','service_end':'2026-10-24'}
 p=coverage.preview(c,b);assert p['registration_adjustment_cents']==800 and not p['blocked_months']
 b['estimate_versions']=[{'id':r['id'],'version':r['version']} for r in p['estimate_candidates']]
 bill=op.expense(b,'管理员');assert bill['amount_cents']==33600 and bill['registration_adjustment_cents']==800
 assert reporting.expense_summary(c,'2026-09')['total_cents']==130000
 assert reporting.expense_summary(c,'2026-10')['total_cents']==129600
 assert frozen==c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0]
 assert estimates==[r[0] for r in c.execute('SELECT payload FROM expense_estimates ORDER BY id')]
 p=close.preview(c,'2026-10');r=next(r for r in p['rows'] if r['category']=='water');assert r['supplement_cents']==8400 and r['mean_numerator_cents']==28800
 op.period({'month':'2026-10','version':0,'state':'closed','note':'新版本按对应费用补齐','close_fingerprint':p['fingerprint']},'管理员')
 assert reporting.expense_summary(c,'2026-10')['total_cents']==138000
 assert len(rc.expense_projection(c))==3
 op.expense_review({'id':bill['id'],'version':1,'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
 op.expense_payment({'id':bill['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-11-05','amount':'336','method':'银行转账','payee':'水务公司','handler':'出纳','reference':'合成回单','note':'整笔实际账单付款'},'管理员')
 assert next(e for e in rc.expense_projection(c) if e['id']==bill['id'])['outstanding_cents']==0
 assert reporting.expense_summary(c,'2026-10')['total_cents']==138000
 print(json.dumps({'closed_prior_month_unchanged':True,'prior_manual_estimate_compatible':True,'actual_payable_cents':33600,'registration_month_adjustment_cents':800,'next_month_supplement_cents':8400,'full_actual_payment_no_duplicate_cost':True}))
'''
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='erp086-upgrade-') as folder:
  tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.85.0.tar.gz'
  if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.85.0.tar.gz'
  prior=unpack(previous,old);archive=ROOT/'output/releases/yangfan-erp-0.86.0.tar.gz';meta=unpack(archive,new);db=tmp/'synthetic.db'
  run(['-c',SEED,str(db)],old);snapshot=json.loads(run(['-c',SNAP,str(db)],old));before=digest(db)
  run(['ops/initialize_cloud.py','--database',str(db)],new);after=digest(db);assert before==after;assert snapshot==json.loads(run(['-c',SNAP,str(db)],new))
  scenario=json.loads(run(['-c',SCENARIO,str(db)],new));post=digest(db)
  checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
  run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)==post
  with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==68
  result={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':67,'schema_after':68,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'original_business_digest_before':before,'original_business_digest_after':after,'original_bills_frozen_months_estimates_and_fifo_unchanged':True,'repeat_upgrade_unchanged':True,'scenario':scenario,'check_db':checks,'business_check':business}
  OUT.mkdir(parents=True,exist_ok=True);(OUT/'release-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('check_db','business_check')}))
