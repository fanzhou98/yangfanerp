"""Validate candidate upgrade, expense query parity and real writes using synthetic data."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from validate_resource_release import run,unpack

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/费用状态SQL与按需原单-v0.67.0'


def business_digest(path):
    values={}
    with sqlite3.connect(path) as c:
        for table, in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if table.startswith(('sqlite_','auth_')) or table in ('audit','security_events','schema_migrations','meta','expense_accrual_lookup'):continue
            rows=sorted([list(r) for r in c.execute('SELECT * FROM "'+table+'"')],key=repr)
            if table=='employee_bank_accounts' and not rows:continue
            values[table]=rows
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),{t:len(v) for t,v in values.items()}


SNAPSHOT="""
from pathlib import Path
import sys,json,server,resource_query as q,resources_costs as rc
server.DB=Path(sys.argv[1]);result={}
with server.connect() as c:
 for kind in ('expenses','payables'):
  for period in ('','2026-09','2026-10','2026-11'):
   for stage in ('all','review','pay','returned','paid','voided','payroll','noncash'):
    args={'kind':kind,'period':period,'stage':stage,'all_dates':True}
    first=q.ledger(c,**args);rows=list(first['rows'])
    for page in range(2,first['pages']+1):rows.extend(q.ledger(c,**args,page=page)['rows'])
    first['rows']=rows;result[kind+'|'+period+'|'+stage]=first
 result['payments']=q.ledger(c,kind='payments',all_dates=True,period='2026-10',payment_start='2026-11-01',payment_end='2026-11-01')
 data=rc.snapshot(c);result['revision']=data['revision'];result['records']=rc.expense_projection(c);result['categories']=data['categories'];result['periods']=data['periods']
print(json.dumps(result,ensure_ascii=False,sort_keys=True))
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',type=Path,default=ROOT/'output/releases/yangfan-erp-0.67.0.tar.gz');parser.add_argument('--output',type=Path,default=OUT);parser.add_argument('--previous-archive',type=Path,default=ROOT/'output/releases/yangfan-erp-0.66.0.tar.gz');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='erp-v067-candidate-') as folder:
        tmp=Path(folder);prior=tmp/'old';candidate=tmp/'candidate';old_manifest=unpack(args.previous_archive,prior);manifest=unpack(args.archive,candidate);db=tmp/'synthetic.db'
        run(['-c',"""
from pathlib import Path
import sys,json,server,resources_costs as rc
server.DB=Path(sys.argv[1]);server.init_db(demo=False,convert_billing=True)
with server.connect(True) as c:
 def put(t,r):c.execute('INSERT INTO '+t+' VALUES(?,?,?)',(r['id'],r['id'],json.dumps(r)))
 for i in range(125):
  eid=f'CVEX{i:03d}';phase=i%5
  row={'id':eid,'version':1 if phase==0 else 2 if phase in (1,2) else 3,'business_date':'2026-10-20','period':'2026-10','category':'office','payment_mode':'payable','partner':'候选费用方','amount_cents':10000,'handler':'测试','department':'管理','note':'候选费用'};put('indirect_expenses',row)
  if phase:put('expense_reviews',{'id':f'CVER{i:03d}','expense_id':eid,'expense_version':1,'decision':'return' if phase==2 else 'approve','handler':'测试','created_at':'2026-10-21T12:00:00+08:00','note':'核对记录'})
  if phase in (3,4):put('expense_payments',{'id':f'CVEP{i:03d}','expense_id':eid,'expense_version':2,'business_date':'2026-11-01','amount_cents':2000 if phase==3 else 10000,'payee':'候选费用方','method':'现金','handler':'测试','note':'候选付款'})
 put('indirect_expenses',{'id':'SPREAD','version':1,'business_date':'2026-09-01','period':'2026-09','category':'rent','amount_cents':10001,'partner':'房东','handler':'测试','note':'三月分摊','accruals':[{'period':'2026-09','amount_cents':3334},{'period':'2026-10','amount_cents':3334},{'period':'2026-11','amount_cents':3333}]})
 put('indirect_expenses',{'id':'VOID','version':2,'business_date':'2026-10-20','period':'2026-10','category':'office','amount_cents':1111,'partner':'费用方','voided':True,'handler':'测试','note':'保留作废历史'})
 put('payroll_records',{'id':'SHEET','kind':'sheet','rows':[{'employee_id':'P1'},{'employee_id':'P2','salary_category':'wages-management'}]})
 for key,category,amount,emp,paid in [('WAGE-P','wages-production',6000,'P1',3000),('WAGE-M','wages-management',4000,'P2',1500)]:
  put('indirect_expenses',{'id':key,'version':1,'business_date':'2026-10-20','period':'2026-10','category':category,'amount_cents':amount,'payment_mode':'payroll','payroll_sheet_id':'SHEET','partner':'','note':'工资成本','handler':'测试'})
  put('payroll_records',{'id':'PAY-'+key,'kind':'payment','employee_id':emp,'month':'2026-10','business_date':'2026-11-01','amount_cents':paid})
 rc.Operations(c,server.now,server.audit).period({'month':'2026-09','version':0,'state':'closed','note':'保留真实冻结快照'},'管理员')
""",str(db)],prior)
        before,counts=business_digest(db);baseline=json.loads(run(['-c',SNAPSHOT,str(db)],prior))
        with sqlite3.connect(db) as c:old_schema=c.execute('PRAGMA user_version').fetchone()[0];frozen=c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0]
        run(['ops/initialize_cloud.py','--database',str(db)],candidate)
        after,new_counts=business_digest(db);assert before==after and counts==new_counts
        actual=json.loads(run(['-c',SNAPSHOT,str(db)],candidate));assert actual==baseline,'费用SQL与旧版完整状态/月份/分页/详情结果不一致'
        with sqlite3.connect(db) as c:
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not c.execute('PRAGMA foreign_key_check').fetchall()
            assert c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0]==frozen
            schema=c.execute('PRAGMA user_version').fetchone()[0];steps=c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0];lookup=c.execute('SELECT COUNT(*) FROM expense_accrual_lookup').fetchone()[0]
            expected=[]
            for key,payload in c.execute('SELECT id,payload FROM indirect_expenses'):
                e=json.loads(payload)
                for position,part in enumerate(e.get('accruals') or [{'period':e['period'],'amount_cents':e['amount_cents']}]):expected.append((key,position,part['period'],part['amount_cents']))
            assert sorted(expected)==sorted(c.execute('SELECT * FROM expense_accrual_lookup').fetchall())
        check=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],candidate));business=json.loads(run(['ops/business_check.py','--database',str(db)],candidate));assert check['ok'] and business['ok'],business
        run(['ops/initialize_cloud.py','--database',str(db)],candidate);again,_=business_digest(db);assert again==before
        with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]==steps
        writable=tmp/'write-drill.db'
        with sqlite3.connect(db) as source,sqlite3.connect(writable) as dest:source.backup(dest)
        drill=json.loads(run(['-c',"""
from pathlib import Path
import sys,json,uuid,server,resources_costs as rc,expense_query as q
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 op=rc.Operations(c,server.now,server.audit)
 before=q.record(c,'CVEX000');edited=op.expense_edit({'id':before['id'],'version':before['version'],'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','period':'2026-10','category':'office','amount':'120.01','partner':'候选费用方','department':'管理','handler':'测试','note':'更正原单验证'},'管理员')
 assert q.record(c,'CVEX000')['amount_cents']==12001
 op.expense_review({'id':'CVEX000','version':edited['version'],'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'测试','note':'核对通过'},'管理员')
 current=q.record(c,'CVEX000');op.expense_payment({'id':'CVEX000','version':current['version'],'request_key':str(uuid.uuid4()),'business_date':'2026-11-01','amount':'20','payee':'候选费用方','method':'现金','handler':'测试','note':'部分付款验证'},'管理员')
 current=q.record(c,'CVEX000');assert (current['paid_cents'],current['outstanding_cents'])==(2000,10001)
 assert c.execute("SELECT SUM(amount_cents) FROM expense_accrual_lookup WHERE expense_id='CVEX000'").fetchone()[0]==12001
 voided=op.void({'ledger':'expense','id':'CVEX005','version':1,'reason':'作废验证'},'管理员');op.restore({'ledger':'expense','id':'CVEX005','version':voided['version'],'reason':'恢复验证'},'管理员')
print(json.dumps({'edit_review_partial_payment_ok':True,'void_restore_ok':True,'derived_lookup_updated':True}))
""",str(writable)],candidate))
        evidence={'version':manifest['version'],'from':old_manifest['version'],'sha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(),'files':len(manifest['files']),'data_included':False,'old_schema':old_schema,'new_schema':schema,'migration':None if old_schema==schema else f'schema-{old_schema}-to-{schema}','business_digest_before':before,'business_digest_after':after,'business_records_unchanged':True,'frozen_snapshot_unchanged':True,'repeat_upgrade_unchanged':True,'old_new_query_results_identical':True,'query_scope_variants':len(actual)-4,'source_expenses':counts['indirect_expenses'],'derived_accrual_rows':lookup,'derived_lookup_consistent':True,'row_counts':counts,'check_db':check,'business_check':business,'write_drill':drill}
        args.output.mkdir(parents=True,exist_ok=True);(args.output/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:evidence[k] for k in ('version','sha256','old_schema','new_schema','source_expenses','derived_accrual_rows','business_records_unchanged','frozen_snapshot_unchanged','old_new_query_results_identical','write_drill')}))


if __name__=='__main__':main()
