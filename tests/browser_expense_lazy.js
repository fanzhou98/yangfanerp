'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-expense-lazy-')),db=path.join(tmp,'test.db'),out=path.join(root,'output/费用状态SQL与按需原单-v0.67.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[],bootstraps=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  cp.execFileSync('python3',['-c',`
import json,sqlite3,sys
c=sqlite3.connect(sys.argv[1])
for t in ('indirect_expenses','expense_reviews','expense_payments'):c.execute('DELETE FROM '+t)
def put(t,r):c.execute('INSERT INTO '+t+' VALUES(?,?,?)',(r['id'],r['id'],json.dumps(r)))
def fee(key,**more):return dict(id=key,version=1,business_date='2026-10-20',period='2026-10',category='office',amount_cents=10000,partner='费用方',department='管理',handler='测试',note='按需原单测试',payment_mode='payable',**more)
for i in range(125):
 r=fee(f'LZ{i:03d}');r['business_date']='2026-10-19' if i<100 else '2026-10-20';put('indirect_expenses',r)
r=fee('SPREAD');r.update(business_date='2026-09-01',period='2026-09',category='rent',amount_cents=10001,spread_months=3,accruals=[{'period':'2026-09','amount_cents':3334},{'period':'2026-10','amount_cents':3334},{'period':'2026-11','amount_cents':3333}]);put('indirect_expenses',r)
r=fee('FRET');r.update(business_date='2026-09-15',period='2026-09',amount_cents=5000,version=2);put('indirect_expenses',r)
put('expense_reviews',dict(id='FRET-REVIEW',expense_id='FRET',expense_version=1,decision='return',handler='测试',created_at='2026-10-20T00:00:00+08:00',note='请更正凭据'))
c.commit();c.close()
`,db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===99)throw Error('服务未启动');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
  p.on('response',async r=>{if(new URL(r.url()).pathname==='/api/bootstrap'&&r.ok()){try{const v=await r.json(),mode=r.request().headers()['x-erp-expense-history']||'full';bootstraps.push({mode,expenses:v.resources.expenses.length,payables:v.resources.expense_payables.length,payments:v.resources.expense_payments.length,deferred:v.resources.expense_history_deferred});}catch{}}});
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const go=async target=>{await p.evaluate(x=>goto(x),target);await ready();};
  const count=async n=>{await p.waitForFunction(n=>document.querySelector('#content')?.innerText.includes(`共 ${n} 笔记录`),n);await ready();};
  const home=async()=>{await go('dashboard');await p.evaluate(()=>{selectedDate='2026-10-20';render();});await p.waitForFunction(()=>factoryReports.get('expense-workflow|2026-10-20')?.value);await ready();};
  await home();assert.equal(await p.evaluate(()=>data.resources.expense_history_deferred),true);assert.equal(await p.evaluate(()=>data.resources.expenses.length),0);
  const work=await p.evaluate(()=>{const t=homeTasks().find(t=>t.key==='costs.review');return {today:t.today,carry:t.carry,samples:t.items.length};});assert.deepEqual(work,{today:25,carry:101,samples:20});assert.match(await p.locator('#content').innerText(),/每个费用环节显示前20项/);checks.push('初始化不下发费用/应付/付款历史，首页完整显示126笔待核对并仅列20例');
  await p.locator('[data-home-id="LZ000"]').click();await count(1);assert.equal(await p.locator('[data-expense-act=history]').count(),1);
  await p.locator('[data-expense-act=history]').click();await p.locator('#dialog-body').waitFor({state:'visible'});assert.match(await p.locator('#dialog-body').innerText(),/LZ000/);await p.evaluate(()=>closeDialog());checks.push('首页历史待办可下钻，指定原单通过独立接口读取');
  await home();await p.locator('[data-home-id="FRET"]').click();await p.locator('#cost-expense-form').waitFor({state:'visible'});assert.equal(await p.locator('#cost-expense-form [name=amount]').inputValue(),'50');
  await p.locator('#cost-expense-form [name=note]').fill('退回原单更正，输入必须保留');await p.evaluate(()=>api('/api/bootstrap'));await p.locator('#cost-expense-form [name=category]').selectOption('office');assert.equal(await p.locator('#cost-expense-form [name=counterparty_id]').inputValue(),'legacy:FRET');assert.equal(await p.locator('#cost-expense-form [name=note]').inputValue(),'退回原单更正，输入必须保留');
  await p.locator('#cost-expense-form [name=amount]').fill('60.01');await p.locator('[data-cost-save=expense]').click();await p.locator('#overlay').waitFor({state:'hidden'});await ready();const changed=await p.evaluate(()=>api('/api/expense-record?id=FRET'));assert.equal(changed.amount_cents,6001);assert.equal(changed.payment_state,'pending');checks.push('退回历史原单按所属月打开；刷新清缓存不丢编辑上下文，更正后重新核对');
  await go('expense-payables');await p.locator('[data-expense-clear]').click();await p.locator('#expense-pay-search').fill('LZ124');await count(1);await p.locator('[data-expense-act=review]').click();await p.locator('#expense-action-form [name=evidence_checked]').check();await p.locator('[data-expense-save=approve]').click();await p.locator('#overlay').waitFor({state:'hidden'});await ready();
  await p.locator('[data-expense-stage=pay]').click();await count(1);await p.locator('[data-expense-act=payment]').click();await p.locator('#expense-action-form [name=business_date]').fill('2026-10-21');await p.locator('#expense-action-form [name=amount]').fill('10');await p.locator('#expense-action-form [name=note]').fill('按需原单部分付款');await p.locator('[data-expense-save=payment]').click();await p.locator('#overlay').waitFor({state:'hidden'});await ready();await count(1);
  const paid=await p.evaluate(()=>api('/api/expense-record?id=LZ124'));assert.equal(paid.payment_state,'partial');assert.equal(paid.paid_cents,1000);assert.equal(paid.outstanding_cents,9000);checks.push('核对→部分付款使用新鲜版本和原付款链路，SQL状态与余额同步');
  await p.evaluate(()=>{resourcesMonth='2026-10';delete resourceLedgerState.expenses;});await go('expenses');await count(126);assert.equal(await p.locator('[data-expense-act=history]').count(),50);assert.match(await p.locator('#content').innerText(),/12,533.34/);
  const ids=[];for(const page of [1,2,3]){if(page>1){await p.locator(`[data-resource-pager=expenses][data-target="${page}"]`).click();await p.waitForFunction(n=>document.querySelector('#content')?.innerText.includes(`第 ${n} / 3 页`),page);await ready();}ids.push(...await p.locator('[data-expense-act=history]').evaluateAll(xs=>xs.map(x=>x.dataset.id)));}assert.equal(ids.length,126);assert.equal(new Set(ids).size,126);checks.push('跨月费用在所属月只计3334分，126笔按50/50/26稳定分页，汇总不随页变化');
  for(const target of ['expenses','expense-payables','dashboard']){if(target==='dashboard')await home();else {await go(target);await ready();}for(const width of [1440,390,320]){await p.setViewportSize({width,height:900});await p.evaluate(()=>{scrollTo(0,0);const t=document.querySelector('#toast');if(t){t.hidden=true;t.classList.remove('show');}});await p.waitForTimeout(100);assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`${target} overflow ${width}`);await p.screenshot({path:path.join(out,`${target}-${width}.png`),fullPage:true});}}
  checks.push('费用、核销付款和首页在1440/390/320无整体横向溢出');
  assert(bootstraps.length>4);assert(bootstraps.every(r=>r.mode==='deferred'&&r.deferred&&r.expenses===0&&r.payables===0&&r.payments===0));assert.deepEqual(errors,[]);const result={ok:true,checks,errors,bootstraps};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){console.error(e.stack||e);console.error(JSON.stringify({errors}));process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(tmp,{recursive:true,force:true});}
})();
