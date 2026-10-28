"""0.65 -> 0.66 package upgrade and old/new query parity on a synthetic DB."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from validate_resource_release import digest,run,unpack

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/应收资金SQL下推-v0.66.0'

SNAPSHOT="""
from pathlib import Path
import json,sys,server,finance_query,funds
server.DB=Path(sys.argv[1])
with server.connect() as c:
 ar=finance_query.ledger(c,'2026-01-01','2026-12-31',all_dates=True,clearance='all')
 bill_rows=list(ar['rows']);receipt_rows=list(ar['receipts'])
 for page in range(2,ar['pages']+1):bill_rows.extend(finance_query.ledger(c,'2026-01-01','2026-12-31',all_dates=True,clearance='all',page=page)['rows'])
 for page in range(2,ar['receipt_pages']+1):receipt_rows.extend(finance_query.ledger(c,'2026-01-01','2026-12-31',all_dates=True,clearance='all',receipt_page=page)['receipts'])
 ar['rows']=bill_rows;ar['receipts']=receipt_rows
 cash=funds.report(c,'2026-10-31')
 result={'ar':{k:ar[k] for k in ('start','end','rows','summary','customers','markets','receipts','receipt_summary','total','pages','receipt_total','receipt_pages')},'cash':{k:cash[k] for k in ('accounts','movements','totals','flow_totals','movement_total','movement_pages')}}
print(json.dumps(result,ensure_ascii=False,sort_keys=True))
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=ROOT/'output/releases/yangfan-erp-0.66.0.tar.gz')
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args();out=args.output
    old=ROOT/'output/releases/yangfan-erp-0.65.0.tar.gz';new=args.archive
    with tempfile.TemporaryDirectory(prefix='erp-v066-candidate-') as folder:
        temp=Path(folder);prior=temp/'prior';candidate=temp/'candidate';unpack(old,prior);manifest=unpack(new,candidate);db=temp/'synthetic.db'
        run(['-c',"""
from pathlib import Path
import sys,json,server
server.DB=Path(sys.argv[1]);server.init_db(demo=False,convert_billing=True)
with server.connect(True) as c:
 for cid,name,kind in [('CV-C','候选产品客户','sales'),('CV-B','候选豆渣客户','byproduct')]:
  c.execute('INSERT INTO customers(id,name,route,note,business_kind,legal_name) VALUES(?,?,?,?,?,?)',(cid,name,'候选线路','',kind,name))
 c.execute('INSERT INTO products(id,name,unit,price,tare) VALUES(?,?,?,?,?)',('CV-P','候选豆腐','公斤','1','0'))
 def put(table,b):
  cols=[r[1] for r in c.execute('PRAGMA table_info('+table+')')]
  if 'request_key' in cols:c.execute('INSERT INTO '+table+'(id,request_key,payload) VALUES(?,?,?)',(b['id'],b['id'],json.dumps(b)))
  else:c.execute('INSERT INTO '+table+' VALUES(?,?)',(b['id'],json.dumps(b)))
 for i in range(2):put('fund_accounts',{'id':f'CV-FA{i}','name':f'候选账户{i}','kind':'银行账户','active':True,'version':1,'opening_date':'2026-09-01','opening_balance_cents':100000 if i==0 else 0})
 for i in range(125):
  eid=f'CVEX{i:03d}';oid=f'CVO{i:03d}'
  put('orders',{'id':oid,'version':2,'state':'reviewed','business_date':'2026-09-15','customer_id':'CV-C','customer_name':'候选产品客户','total_cents':10000,'paid_cents':2000,'return_credit_cents':0,'discount_cents':0,'rounding_cents':0,'settlement':{'at':'2026-10-20T12:00:00+08:00'},'lines':[{'product_id':'CV-P','product_name':'候选豆腐','unit':'公斤','billing_unit':'公斤','bill_qty':'100','actual_qty':'100','ordered_qty':'100','price':'1','amount_cents':10000}]})
  put('receipts',{'id':f'CVR{i:03d}','order_id':oid,'customer_id':'CV-C','customer_name':'候选产品客户','received_date':'2026-10-21','amount_cents':2000,'method':'银行转账','note':'候选收款','account_id':'CV-FA0'})
  put('indirect_expenses',{'id':eid,'version':3,'business_date':'2026-09-15','period':'2026-09','category':'office','payment_mode':'payable','partner':'候选费用对象','amount_cents':10000,'handler':'测试','note':'候选费用'})
  put('expense_reviews',{'id':f'CVER{i:03d}','expense_id':eid,'expense_version':1,'decision':'approve','handler':'测试','note':'已核对'})
  put('expense_payments',{'id':f'CVEP{i:03d}','expense_id':eid,'expense_version':2,'business_date':'2026-10-21','amount_cents':2000,'payee':'候选费用对象','method':'现金','note':'测试付款','handler':'测试','account_id':'CV-FA0'})
  put('byproduct_sales',{'id':f'CVB{i:03d}','version':1,'business_date':'2026-09-15','created_at':'2026-10-20T12:00:00+08:00','buyer':'候选豆渣客户','customer_id':'CV-B','qty':'100','unit':'公斤','price':'1','amount_cents':10000,'received_cents':3000,'receipts':[{'business_date':'2026-10-22','amount_cents':2000,'account_id':'CV-FA0'}],'handler':'测试','note':'测试销售','account_id':'CV-FA0'})
 for tid,when in [('CVT','2026-10-22'),('CVT-FUTURE','2026-12-01')]:put('fund_transfers',{'id':tid,'business_date':when,'amount_cents':400,'from_account_id':'CV-FA0','to_account_id':'CV-FA1','note':'候选转账'})
""",str(db)],prior)
        before,counts=digest(db);baseline=json.loads(run(['-c',SNAPSHOT,str(db)],prior))
        with sqlite3.connect(db) as c:old_schema=c.execute('PRAGMA user_version').fetchone()[0]
        run(['ops/initialize_cloud.py','--database',str(db)],candidate)
        after,after_counts=digest(db);assert before==after and counts==after_counts
        actual=json.loads(run(['-c',SNAPSHOT,str(db)],candidate));assert actual==baseline,'旧版投影与SQL读取不一致'
        with sqlite3.connect(db) as c:
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not c.execute('PRAGMA foreign_key_check').fetchall()
            schema=c.execute('PRAGMA user_version').fetchone()[0];steps=c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]
            assert c.execute("SELECT COUNT(*) FROM schema_migrations WHERE id='068-finance-cash-query-indexes'").fetchone()[0]==1
        check=json.loads(run(['ops/erp_ops.py','check-db','--database',str(db),'--full'],candidate));business=json.loads(run(['ops/business_check.py','--database',str(db)],candidate))
        assert check['ok'] and business['ok'],business
        run(['ops/initialize_cloud.py','--database',str(db)],candidate)
        again,_=digest(db);assert again==before
        with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]==steps
        evidence={'version':'0.66.0','from':'0.65.0','sha256':hashlib.sha256(new.read_bytes()).hexdigest(),'files':len(manifest['files']),'data_included':False,'old_schema':old_schema,'new_schema':schema,'migration':'068-finance-cash-query-indexes','migration_count':steps,'integrity_ok':True,'foreign_keys_ok':True,'business_digest_before':before,'business_digest_after':after,'business_records_unchanged':True,'repeat_upgrade_unchanged':True,'old_and_new_query_results_identical':True,'query_snapshot_sha256':hashlib.sha256(json.dumps(actual,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'receivable_bill_count':actual['ar']['total'],'compared_bill_rows':len(actual['ar']['rows']),'compared_receipt_rows':len(actual['ar']['receipts']),'cash_movement_count':actual['cash']['movement_total'],'cash_balance_cents':actual['cash']['totals']['balance_cents'],'row_counts':counts,'check_db':check,'business_check':business}
        out.mkdir(exist_ok=True,parents=True);(out/'release-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:evidence[k] for k in ('version','sha256','old_schema','new_schema','business_records_unchanged','old_and_new_query_results_identical','repeat_upgrade_unchanged','receivable_bill_count','cash_movement_count','cash_balance_cents')}))


if __name__=='__main__':main()
