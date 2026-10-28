"""Old release -> candidate purchasing parity/stock checks using synthetic DB only."""
import json,sqlite3,tempfile,uuid,sys
from pathlib import Path
from validate_resource_release import run,unpack,digest

ROOT=Path(__file__).resolve().parents[1]
CURRENT=(ROOT/'VERSION').read_text().strip()
PREVIOUS=sys.argv[1] if len(sys.argv)>1 else '0.74.0'
OUT=ROOT/('output/采购验收付款与附加费查询-v'+CURRENT)
SEED='''
import sys,uuid
from pathlib import Path
import server,purchasing as p,resources_costs as rc
server.DB=Path(sys.argv[1]);server.init_db(demo=False,convert_billing=True)
with server.connect(True) as c:
 op=p.Operations(c,server.now,server.audit)
 supplier=op.supplier({'name':'候选采购供应商','payment_days':30},'管理员')
 for i in range(3):
  order=op.order({'request_key':str(uuid.uuid4()),'business_date':'2026-10-01','expected_date':'2026-10-03','supplier_id':supplier['id'],'handler':'合成测试','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'0.3','price':'1'}]},'管理员')
  if i==0:continue
  order=op.confirm({'id':order['id'],'version':order['version']},'管理员')
  for qty in (['0.1','0.2'] if i==1 else ['0.1']):
   receipt=op.receipt({'id':order['id'],'version':order['version'],'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'business_date':'2026-10-03','lines':[{'line_id':'L1','qty':qty}],'handler':'合成测试','note':'分批验收'},'管理员')
   order=next(o for o in p.projection(c)['orders'] if o['id']==order['id'])
  charge=op.charge({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'receipt_id':receipt['id'],'business_date':'2026-10-03','kind':'freight','billing_unit':'公斤','billing_qty':'0.1','rate':'1','allocation_basis':'weight','payee_type':'supplier','payee_id':supplier['id'],'handler':'合成测试','note':'采购运费'},'管理员')
  op.charge_payment({'request_key':str(uuid.uuid4()),'charge_id':charge['id'],'business_date':'2026-10-04','amount':'0.05','method':'现金','handler':'合成测试','note':'采购运费部分付款'},'管理员')
  order=next(o for o in p.projection(c)['orders'] if o['id']==order['id'])
  op.payment({'id':order['id'],'version':order['version'],'request_key':str(uuid.uuid4()),'business_date':'2026-10-04','amount':'0.05','method':'现金','handler':'合成测试','note':'分次付款'},'管理员')
  if i==2:
   order=next(o for o in p.projection(c)['orders'] if o['id']==order['id'])
   op.close({'id':order['id'],'version':order['version'],'note':'关闭余量'},'管理员')
'''
SNAPSHOT='''
import sys,json
from pathlib import Path
import server,purchasing as p,resources_costs as rc
server.DB=Path(sys.argv[1])
with server.connect() as c:print(json.dumps({'projection':p.projection(c),'stock':rc.material_ledger(c,warehouse_details=True)},ensure_ascii=False))
'''
with tempfile.TemporaryDirectory(prefix='erp-purchase074-') as folder:
 tmp=Path(folder);old=tmp/'old';candidate=tmp/'candidate';old_meta=unpack(ROOT/('output/releases/yangfan-erp-'+PREVIOUS+'.tar.gz'),old);meta=unpack(ROOT/('output/releases/yangfan-erp-'+CURRENT+'.tar.gz'),candidate);db=tmp/'synthetic.db'
 run(['-c',SEED,str(db)],old);before,counts=digest(db);baseline=json.loads(run(['-c',SNAPSHOT,str(db)],old))
 with sqlite3.connect(db) as c:old_schema=c.execute('PRAGMA user_version').fetchone()[0]
 run(['ops/initialize_cloud.py','--database',str(db)],candidate);after,new_counts=digest(db);assert before==after and counts==new_counts
 assert json.loads(run(['-c',SNAPSHOT,str(db)],candidate))==baseline
 check=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],candidate));business=json.loads(run(['ops/business_check.py','--database',str(db)],candidate));assert check['ok'] and business['ok'],business
 result=json.loads(run(['-c',"""
import json,sys,purchase_query as q,server
from pathlib import Path
server.DB=Path(sys.argv[1])
with server.connect() as c:
 c.execute('BEGIN')
 r=q.orders(c,all_dates=True,page_size=2);rows=r['rows']+q.orders(c,all_dates=True,page_size=2,page=2)['rows']
 ledgers={}
 for kind in ('receipts','payments','charges'):
  first=q.ledger(c,kind=kind,all_dates=True,page_size=2);values=list(first['rows'])
  for number in range(2,first['pages']+1):values+=q.ledger(c,kind=kind,all_dates=True,page_size=2,page=number)['rows']
  ledgers[kind]={'rows':values,'summary':first['summary']}
 print(json.dumps({'rows':rows,'summary':r['summary'],'ledgers':ledgers}))
""",str(db)],candidate))
 expected=sorted(baseline['projection']['orders'],key=lambda o:(o['business_date'],o['id']),reverse=True);assert result['rows']==expected
 assert result['summary']['orders']==3 and result['summary']['total_cents']==90
 for kind,ledger in result['ledgers'].items():
  expected=sorted(baseline['projection'][kind],key=lambda r:(r['business_date'],r['id']),reverse=True)
  if kind!='receipts':
   orders={o['id']:o for o in baseline['projection']['orders']}
   expected=[{**r,'order_supplier_id':orders[r['order_id']]['supplier_id'],'order_supplier_name':orders[r['order_id']]['supplier_name']} for r in expected]
  assert ledger['rows']==expected,kind
  assert ledger['summary']['amount_cents']==sum(r['amount_cents'] for r in expected),kind
 run(['ops/initialize_cloud.py','--database',str(db)],candidate);assert digest(db)[0]==before
 with sqlite3.connect(db) as c:
  new_schema=c.execute('PRAGMA user_version').fetchone()[0];assert new_schema==61
  assert c.execute("SELECT COUNT(*) FROM schema_migrations WHERE id='072-purchase-ledger-indexes'").fetchone()[0]==1
 evidence={'ok':True,'from':old_meta['version'],'to':meta['version'],'old_schema':old_schema,'new_schema':new_schema,'business_digest_before':before,'business_digest_after':after,'business_rows_unchanged':True,'procurement_projection_identical':True,'global_stock_identical':True,'new_query_all_pages_identical':True,'repeat_upgrade_unchanged':True,'synthetic_orders':3,'split_receipts':3,'freight_charges':2,'partial_payments':4,'receipt_fee_payment_pages_identical':True,'check_db':check,'business_check':business}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/('采购候选升级.json' if PREVIOUS=='0.74.0' else '采购候选升级-来自'+PREVIOUS+'.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in evidence.items() if k not in ('check_db','business_check')}))
