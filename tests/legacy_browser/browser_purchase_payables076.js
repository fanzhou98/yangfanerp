'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp076-')),db=path.join(temp,'test.db'),out=path.join(root,'output/采购货款应付查询-v0.76.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'pipe'});
  cp.execFileSync('python3',['-c',`import sys,json
from pathlib import Path
sys.path.insert(0,'tests')
import server,resources_costs as rc
server.DB=Path(sys.argv[1])
rows=[]
def add_order(oid,day,supplier='Q076应付供应商',received=1000,paid=400,due='2026-09-20',two=False):
    lines=[{'id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'10','price':'100','amount_cents':1000}]
    rows.append(('purchase_orders',{'id':oid,'version':1,'business_date':day,'expected_date':'2026-10-01','supplier_id':'S-Q076','supplier_name':supplier,'state':'confirmed','total_cents':1000,'lines':lines}))
    parts=[('400',due),('600','2026-10-20')] if two else [(str(received),due)]
    for j,(amount,d) in enumerate(parts):
        rows.append(('purchase_receipts',{'id':oid+'-R'+str(j),'order_id':oid,'business_date':'2026-10-05','supplier_id':'S-Q076','supplier_name':supplier,'due_date':d,'amount_cents':int(amount),'lines':[{'line_id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':str(int(amount)//100),'amount_cents':int(amount),'material_entry_id':oid+'-M'+str(j)}]}))
    if paid:rows.append(('purchase_payments',{'id':oid+'-P','order_id':oid,'supplier_id':'S-Q076','supplier_name':supplier,'business_date':'2026-10-06','amount_cents':paid}))
add_order('Q076A','2026-09-10')
add_order('Q076B','2026-10-05',paid=0,due='2027-01-05',supplier='特殊兑付供应商')
add_order('Q076C','2026-10-15',paid=500,due='2026-10-01',two=True)
add_order('Q076D','2026-10-20',received=800,paid=800,due='2026-10-10')
rows.append(('purchase_orders',{'id':'Q076E','version':1,'business_date':'2026-10-22','expected_date':'2026-10-25','supplier_id':'S-Q076','supplier_name':'Q076应付供应商','state':'confirmed','total_cents':1000,'lines':[{'id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'10','price':'100','amount_cents':1000}]}))
with server.connect(True) as c:
    for table,row in rows:c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(row['id'],row['id'],rc.dump(row)))
`,db],{cwd:root,stdio:'pipe'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});const base=`http://127.0.0.1:${port}`;
  for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.stack||e.message));
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);
  await p.evaluate(()=>goto('payables'));await p.waitForFunction(()=>!!purchasePayableReport().value);await p.waitForLoadState('networkidle');
  const value=async()=>p.evaluate(()=>purchasePayableReport().value);
  let r=await value();assert.equal(r.total,4);assert.deepEqual(r.rows.map(x=>x.id),['Q076D','Q076C','Q076B','Q076A']);assert.equal(r.summary.received_cents,3800);assert.equal(r.summary.paid_cents,1700);assert.equal(r.summary.outstanding_cents,2100);assert.equal(r.summary.overdue_cents,1100);assert.match(await p.locator('body').innerText(),/采购货款应付/);
  const shot=async name=>{for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' '+width);await p.screenshot({path:path.join(out,name+'-'+width+'.png'),fullPage:false});}await p.setViewportSize({width:1440,height:1000});};
  await shot('应付全量');
  await p.locator('#purchase-month').fill('2026-10');await p.locator('#purchase-month').dispatchEvent('change');await p.waitForFunction(()=>purchasePayableReport().value?.month==='2026-10');r=await value();assert.equal(r.total,3);assert.deepEqual(r.rows.map(x=>x.id),['Q076D','Q076C','Q076B']);assert.equal(r.summary.received_cents,2800);assert.equal(r.summary.overdue_cents,500);
  await p.locator('#purchase-month').fill('');await p.locator('#purchase-month').dispatchEvent('change');await p.waitForFunction(()=>purchasePayableReport().value?.total===4);
  await p.locator('#purchase-status').selectOption('已逾期');await p.waitForFunction(()=>purchasePayableReport().value?.summary?.overdue_cents===1100);r=await value();assert.equal(r.total,2);assert.deepEqual(r.rows.map(x=>x.id),['Q076C','Q076A']);
  await p.locator('#purchase-status').selectOption('');await p.waitForFunction(()=>purchasePayableReport().value?.total===4);
  await p.locator('#purchase-search').fill('特殊');await p.locator('#purchase-search').dispatchEvent('change');await p.waitForFunction(()=>purchasePayableReport().value?.total===1);r=await value();assert.equal(r.rows[0].id,'Q076B');assert.equal(r.summary.overdue_cents,0);
  await p.locator('[data-purchase-act=detail]').first().click();await p.locator('#dialog').waitFor();assert.match(await p.locator('#dialog').innerText(),/Q076B/);await p.evaluate(()=>closeDialog());
  await p.locator('#purchase-search').fill('');await p.locator('#purchase-search').dispatchEvent('change');await p.locator('#purchase-status').selectOption('');await p.locator('#purchase-month').fill('');await p.locator('#purchase-month').dispatchEvent('change');await p.waitForFunction(()=>purchasePayableReport().value?.total===4);await shot('应付筛选');
  checks.push('应付首屏4单：应收3800/已付1700/未付2100/逾期1100，逾期按最早到期逐笔抵扣（C单先抵400再抵100）');
  checks.push('下单月份2026-10筛出3单汇总随筛选；已逾期2单；供应商搜索与详情弹窗按需读取；1440/390/320无横向溢出');
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify({ok:true,checks,errors},null,2));console.log(JSON.stringify({ok:true,checks,errors}));
 }catch(e){console.error(e.stack||e);const p=browser?.contexts()[0]?.pages()[0];if(p){await p.screenshot({path:path.join(out,'失败现场.png'),fullPage:true});}process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(temp,{recursive:true,force:true});}
})();
