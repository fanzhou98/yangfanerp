"""Synthetic upgrade parity for full FIFO, transfers, repricing and frozen cost month."""
from pathlib import Path
import tempfile,json,sqlite3,hashlib
from validate_resource_release import run,unpack,digest
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/原辅料库存历史-v0.81.0'
SEED='''
from pathlib import Path
import sys,uuid,server,resources_costs as rc
server.DB=Path(sys.argv[1]);server.init_db(demo=False,convert_billing=True)
with server.connect(True) as c:
 op=rc.Operations(c,server.now,server.audit)
 def put(kind,qty,amount='0',day='2026-09-01',wh='WH-TOFU',**extra):
  return op.material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':'RM-SOY','warehouse_id':wh,'business_date':day,'kind':kind,'qty':qty,'amount':amount,'handler':'合成经办','note':'候选FIFO来源',**extra},'会计')
 first=put('opening','100','400');put('receipt','100','1000',day='2026-09-02');put('consume','150',day='2026-09-03');put('transfer','10',day='2026-09-04',target_warehouse_id='WH-SKIN');put('receipt','10','50',day='2026-09-05',wh='WH-SKIN');put('consume','2',day='2026-09-06',wh='WH-SKIN')
 op.value({'id':first['id'],'version':first['version'],'amount':'600','note':'更正合成入库金额'},'会计')
 op.period({'month':'2026-09','version':0,'state':'closed','note':'保留冻结计价月'},'管理员')
 put('receipt','5','60',day='2026-10-01');void=put('receipt','1','5',day='2026-10-02');op.void({'ledger':'material','id':void['id'],'version':void['version'],'reason':'候选作废演练'},'会计')
'''
SNAP='''
from pathlib import Path
import sys,json,server,resources_costs as rc
server.DB=Path(sys.argv[1]);r={}
with server.connect() as c:
 for day in ('2026-09-02','2026-09-06','2026-09-30','2026-10-31'):r[day]=rc.material_ledger(c,until=day,warehouse_details=True)
 r['all']=rc.material_ledger(c,warehouse_details=True);r['frozen']=[list(x) for x in c.execute('SELECT * FROM resource_periods')]
 r['raw']=[rc_row for rc_row in rc.rows(c,'material_entries')]
print(json.dumps(r))
'''
with tempfile.TemporaryDirectory(prefix='erp081-upgrade-') as folder:
 tmp=Path(folder);old=tmp/'old';new=tmp/'new';previous=ROOT/'output/releases/yangfan-erp-0.80.0.tar.gz'
 if not previous.exists():previous=Path.home()/'Documents/ERP历史归档/yangfan-erp-0.80.0.tar.gz'
 prior=unpack(previous,old);meta=unpack(ROOT/'output/releases/yangfan-erp-0.81.0.tar.gz',new);db=tmp/'synthetic.db'
 run(['-c',SEED,str(db)],old);baseline=json.loads(run(['-c',SNAP,str(db)],old));before,counts=digest(db)
 run(['ops/initialize_cloud.py','--database',str(db)],new);after,new_counts=digest(db);assert before==after and counts==new_counts
 assert baseline==json.loads(run(['-c',SNAP,str(db)],new))
 result=json.loads(run(['-c',"""
from pathlib import Path
import sys,json,server,material_query as q
server.DB=Path(sys.argv[1]);r={}
with server.connect() as c:
 c.execute('BEGIN')
 first=q.query(c,all_dates=True,status='valid',page_size=2);values=list(first['rows'])
 for page in range(2,first['pages']+1):values+=q.query(c,all_dates=True,status='valid',page_size=2,page=page)['rows']
 r['ledger']=values
 for day in ('2026-09-02','2026-09-06','2026-09-30','2026-10-31'):r[day]=q.query(c,view='stock',as_of=day,material_id='RM-SOY')['rows']
 r['voided']=q.query(c,all_dates=True,status='voided')['total']
print(json.dumps(r))
""",str(db)],new))
 assert result['ledger']==sorted(baseline['all'][1],key=lambda e:(e['business_date'],e['sequence'],e['id']),reverse=True)
 for day in ('2026-09-02','2026-09-06','2026-09-30','2026-10-31'):
  expected=sorted([e for e in baseline[day][2] if e['id']=='RM-SOY'],key=lambda r:(r['id'],r['warehouse_id']))
  actual=result[day]
  assert len(actual)==len(expected)
  for a,b in zip(actual,expected):assert {k:v for k,v in a.items() if k!='has_entries'}=={k:v for k,v in b.items() if k!='lots'}
 assert result['voided']==1
 checks=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],new));business=json.loads(run(['ops/business_check.py','--database',str(db)],new));assert checks['ok'] and business['ok'],business
 run(['ops/initialize_cloud.py','--database',str(db)],new);assert digest(db)[0]==before
 with sqlite3.connect(db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==63
 evidence={'ok':True,'from':prior['version'],'to':meta['version'],'schema_before':62,'schema_after':63,'sha256':hashlib.sha256((ROOT/'output/releases/yangfan-erp-0.81.0.tar.gz').read_bytes()).hexdigest(),'business_digest_before':before,'business_digest_after':after,'global_fifo_and_balances_identical':True,'four_asof_dates_identical':True,'frozen_cost_month_identical':True,'complete_ledger_pages_identical':True,'voided_excluded_from_stock':True,'repeat_upgrade_unchanged':True,'check_db':checks,'business_check':business}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in evidence.items() if k not in ('check_db','business_check')}))
