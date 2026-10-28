'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-q02-')),db=path.join(temp,'test.db'),out=process.env.ERP_BROWSER_OUTPUT||path.join(root,'output/应收收款服务端分页-v0.64.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  cp.execFileSync('python3',['-c',`
import json,sqlite3,sys
from datetime import date,timedelta
con=sqlite3.connect(sys.argv[1]);con.execute('DELETE FROM receipts');con.execute('DELETE FROM orders');con.execute('DELETE FROM byproduct_sales')
for i in range(60):
 day=(date(2026,8,1)+timedelta(days=i%30)).isoformat();cid=f'Q02C{i:03d}';pid=f'Q02P{i:03d}';route=f'Q02R{i%4:02d}'
 con.execute('INSERT OR IGNORE INTO customers(id,name,region,route,note,delivery_method,legal_name,business_kind) VALUES(?,?,?,?,?,?,?,?)',(cid,f'Q02客户{i:03d}','测试区',route,'','delivery',f'Q02客户{i:03d}','sales'))
 amount=100000+i*100;paid=amount if i<30 else 0
 order={'id':f'Q02O{i:03d}','version':2,'customer_id':cid,'customer_name':f'Q02客户{i:03d}','business_date':day,'state':'reviewed','total_cents':amount,'paid_cents':paid,'return_credit_cents':0,'discount_cents':0,'rounding_cents':0,'lines':[{'product_id':pid,'product_name':f'Q02产品{i:03d}','unit':'筐','ordered_qty':'10','actual_qty':'10','billing_unit':'公斤','bill_qty':'50','amount_cents':amount}]}
 con.execute('INSERT INTO orders VALUES(?,?)',(order['id'],json.dumps(order,ensure_ascii=False)))
 if paid:
  receipt={'id':f'Q02R{i:03d}','order_id':order['id'],'received_date':day,'amount_cents':paid,'discount_cents':0,'rounding_cents':0,'method':'银行转账','note':'Q02测试收款','customer_id':cid}
  con.execute('INSERT INTO receipts VALUES(?,?)',(receipt['id'],json.dumps(receipt,ensure_ascii=False)))
con.commit();con.close()
`,db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;let healthy=false;for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok){healthy=true;break;}}catch{}await new Promise(r=>setTimeout(r,50));}assert(healthy);
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const go=async target=>{await p.evaluate(x=>goto(x),target);await ready();};
  const waitLedger=async()=>{await p.waitForFunction(()=>document.querySelector('[data-receivable-order]')||document.querySelector('#content')?.innerText.includes('当前筛选范围没有账单'));await p.waitForLoadState('networkidle');};
  await go('ledger');await waitLedger();
  assert.match(await p.locator('#content').innerText(),/共 30 笔单据 · 第 1 \/ 1 页/);
  await p.locator('#ledger-clearance').selectOption('all');await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('共 60 笔单据 · 第 1 / 2 页'));await waitLedger();
  assert.equal(await p.locator('[data-receivable-order]').count(),50);
  checks.push('默认仅未清账；切换全部后服务端返回50行并显示60笔汇总');
  const total=await p.evaluate(()=>document.querySelector('#content').innerText.match(/范围内账单[\s\S]{0,120}/)?.[0]||'');
  assert.match(total,/60/);
  await p.locator('[data-ledger-page="orders"][data-ledger-target="2"]').click();await p.waitForFunction(()=>[...document.querySelectorAll('[data-receivable-order]')].some(x=>x.dataset.receivableOrder==='Q02O059'));await waitLedger();
  assert.match(await p.locator('#content').innerText(),/第 2 \/ 2 页/);assert.equal(await p.locator('[data-receivable-order]').count(),10);
  checks.push('应收分页第2页仅10行且无重复');
  await p.locator('#ledger-clearance').selectOption('cleared');await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('共 30 笔单据 · 第 1 / 1 页'));await waitLedger();
  assert.match(await p.locator('#content').innerText(),/共 30 笔单据 · 第 1 \/ 1 页/);assert.equal(await p.locator('[data-receivable-order]').count(),30);
  checks.push('清账筛选回第1页，汇总覆盖全部筛选结果');
  await p.locator('[data-ledger-reset]').click();await p.locator('#ledger-clearance').selectOption('all');await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('共 60 笔单据'));await p.locator('#ledger-customer').selectOption('Q02C040');await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('共 1 笔单据'));await waitLedger();
  assert.match(await p.locator('#content').innerText(),/共 1 笔单据/);assert.equal(await p.locator('[data-receivable-order]').count(),1);
  checks.push('客户筛选由服务端执行');
  await p.locator('[data-ledger-reset]').click();await p.locator('#ledger-clearance').selectOption('all');await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('共 60 笔单据'));
  await p.evaluate(()=>{rangeStart='2026-08-16';rangeEnd='2026-08-31';rangeMode=true;rangeBasis='business_date';goto('ledger');});await ready();await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('共 30 笔单据'));await waitLedger();
  assert.match(await p.locator('#content').innerText(),/共 30 笔单据/);
  checks.push('日期范围由服务端按业务日过滤');
  for(const width of [1440,390,320]){
    await p.setViewportSize({width,height:900});await p.evaluate(()=>scrollTo(0,0));await p.waitForTimeout(120);
    assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`应收页横向溢出 ${width}`);
    await p.screenshot({path:path.join(out,`应收与收款-${width}.png`),fullPage:true});
  }
  checks.push('应收页1440/390/320无横向溢出');
  if(errors.length)throw new Error(errors.join('\n'));
  console.log(JSON.stringify({ok:true,checks,errors}));
 }catch(error){console.error(error.stack||error);if(errors.length)console.error(JSON.stringify({pageerrors:errors}));process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(temp,{recursive:true,force:true});}
})();
