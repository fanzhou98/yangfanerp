"""Validate old->candidate->repeat upgrade using only a temporary synthetic DB."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/费用豆渣服务端查询-v0.65.0'


def digest(path):
    result={}
    with sqlite3.connect(path) as c:
        for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if table.startswith(('sqlite_','auth_')) or table in ('audit','security_events','schema_migrations','meta'):continue
            result[table]=sorted([list(row) for row in c.execute('SELECT * FROM "'+table+'"')],key=repr)
    return hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),{k:len(v) for k,v in result.items()}


def run(args,cwd):
    env=os.environ.copy()
    # Bundled test-only dependency, if present, is never included in releases.
    deps=Path('/private/tmp/erp-r01-cloud-deps')
    if deps.is_dir():env['PYTHONPATH']=str(deps)
    return subprocess.check_output([sys.executable,*args],cwd=cwd,env=env,text=True)


def unpack(archive,target):
    target.mkdir()
    with tarfile.open(archive) as tf:
        for item in tf.getmembers():
            assert not item.issym() and not item.islnk()
            assert not Path(item.name).is_absolute() and '..' not in Path(item.name).parts
        tf.extractall(target)
    manifest=json.loads((target/'release.json').read_text())
    assert manifest['data_included'] is False
    for name,expected in manifest['files'].items():
        assert hashlib.sha256((target/name).read_bytes()).hexdigest()==expected,name
    return manifest


def main():
    old=ROOT/'output/releases/yangfan-erp-0.64.0.tar.gz';new=ROOT/'output/releases/yangfan-erp-0.65.0.tar.gz'
    with tempfile.TemporaryDirectory(prefix='erp-v065-candidate-') as folder:
        tmp=Path(folder);prior=tmp/'old';candidate=tmp/'candidate';unpack(old,prior);manifest=unpack(new,candidate);db=tmp/'synthetic.db'
        run(['-c',"""
from pathlib import Path
import sys,json,server
server.DB=Path(sys.argv[1]);server.init_db(demo=False,convert_billing=True)
with server.connect(True) as c:
 for i in range(125):
  eid=f'CVEX{i:03d}';b={'id':eid,'version':3,'business_date':'2026-09-15','period':'2026-09','category':'office','payment_mode':'payable','partner':'候选合成对象','amount_cents':10000,'handler':'测试','note':'候选费用'}
  c.execute('INSERT INTO indirect_expenses VALUES(?,?,?)',(eid,eid,json.dumps(b)))
  review={'id':f'CVER{i:03d}','expense_id':eid,'expense_version':1,'decision':'approve','handler':'测试','note':'已核对'}
  c.execute('INSERT INTO expense_reviews VALUES(?,?,?)',(review['id'],review['id'],json.dumps(review)))
  b={'id':f'CVEP{i:03d}','expense_id':eid,'expense_version':2,'business_date':'2026-10-20','amount_cents':2000,'payee':'候选合成对象','method':'现金','note':'测试付款','handler':'测试'}
  c.execute('INSERT INTO expense_payments VALUES(?,?,?)',(b['id'],b['id'],json.dumps(b)))
  b={'id':f'CVBP{i:03d}','version':1,'business_date':'2026-09-15','buyer':'候选豆渣客户','customer_id':'','qty':'10','unit':'公斤','price':'10','amount_cents':10000,'received_cents':2000,'receipts':[{'business_date':'2026-10-21','amount_cents':2000}],'handler':'测试','note':'测试销售'}
  c.execute('INSERT INTO byproduct_sales VALUES(?,?,?)',(b['id'],b['id'],json.dumps(b)))
""",str(db)],prior)
        before,counts=digest(db)
        with sqlite3.connect(db) as c:old_schema=c.execute('PRAGMA user_version').fetchone()[0]
        run(['ops/initialize_cloud.py','--database',str(db)],candidate)
        after,after_counts=digest(db);assert before==after and counts==after_counts
        with sqlite3.connect(db) as c:
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
            schema=c.execute('PRAGMA user_version').fetchone()[0]
            steps=c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]
        check=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],candidate))
        business=json.loads(run(['ops/business_check.py','--database',str(db)],candidate))
        assert check['ok'] and business['ok'],business
        run(['ops/initialize_cloud.py','--database',str(db)],candidate)
        again,_=digest(db);assert again==before
        with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]==steps
        smoke=json.loads(run(['-c',"""
import json,sqlite3,sys,resource_query
with sqlite3.connect(sys.argv[1]) as c:
 c.execute('BEGIN')
 result={k:resource_query.ledger(c,kind=k,all_dates=True)['total'] for k in resource_query.KINDS}
print(json.dumps(result))
""",str(db)],candidate))
        evidence={'version':'0.65.0','from':'0.64.0','sha256':hashlib.sha256(new.read_bytes()).hexdigest(),'files':len(manifest['files']),'data_included':False,'old_schema':old_schema,'new_schema':schema,'migration':'067-resource-query-indexes','migration_count':steps,'integrity_ok':True,'foreign_keys_ok':True,'business_digest_before':before,'business_digest_after':after,'business_records_unchanged':True,'repeat_upgrade_unchanged':True,'row_counts':counts,'packaged_query_totals':smoke,'check_db':check,'business_check':business}
        OUT.mkdir(exist_ok=True,parents=True);(OUT/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:evidence[k] for k in ('version','sha256','old_schema','new_schema','business_records_unchanged','repeat_upgrade_unchanged','packaged_query_totals')}))


if __name__=='__main__':main()
