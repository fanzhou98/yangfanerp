'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-resource-q02-')),db=path.join(temp,'test.db'),out=process.env.ERP_BROWSER_OUTPUT||path.join(root,'output/费用豆渣服务端查询-v0.65.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  cp.execFileSync('python3',['-c',`
import json,sqlite3,sys
c=sqlite3.connect(sys.argv[1])
for t in ('indirect_expenses','expense_reviews','expense_payments','byproduct_sales'):c.execute('DELETE FROM '+t)
def put(t,r):c.execute('INSERT INTO '+t+' VALUES(?,?,?)',(r['id'],'test-'+r['id'],json.dumps(r)))
for i in range(125):
 eid=f'EXQ{i:03d}';day='2026-09-15' if i<65 else '2026-10-15';period=day[:7]
 put('indirect_expenses',dict(id=eid,version=1,business_date=day,period=period,category='office',amount_cents=10000,partner='测试收款方',handler='测试人',note='跨月费用',reference='REF',payment_mode='payable',department='管理'))
 put('expense_reviews',dict(id=f'ERQ{i:03d}',expense_id=eid,expense_version=1,decision='approve',handler='测试人',created_at='2026-09-15',note='已核对'))
 put('expense_payments',dict(id=f'EPQ{i:03d}',expense_id=eid,business_date='2026-10-20',amount_cents=2000,payee='测试收款方',handler='测试人',method='银行转账',reference='PAY',note='次月付款'))
 put('byproduct_sales',dict(id=f'BPQ{i:03d}',version=1,business_date=day,customer_id='BY-Q02',buyer='豆渣客户',qty='10',unit='公斤',price='10',amount_cents=10000,received_cents=3000,receipts=[dict(business_date='2026-10-21',amount_cents=2000,note='次月到账')],handler='测试人',reference='BP',note='合成数据'))
c.commit();c.close()
`,db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===119)throw Error('测试服务未启动');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  const go=async target=>{await p.evaluate(x=>{resourcesMonth='2026-09';goto(x);},target);await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const count=async n=>{await p.waitForFunction(n=>document.querySelector('#content')?.innerText.includes(`共 ${n} 笔记录`),n);await p.waitForLoadState('networkidle');};
  const range=async(target,start,end)=>{const form=p.locator(`[data-resource-range="${target}"]`);await form.locator('[name=start]').fill(start);await form.locator('[name=end]').fill(end);await form.locator('button').click();await p.waitForLoadState('networkidle');};
  await go('expenses');await count(65);assert.equal(await p.locator('[data-expense-act=history]').count(),50);
  assert.match(await p.locator('#content').innerText(),/6,500/);await p.locator('[data-resource-pager=expenses][data-target="2"]').click();await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('第 2 / 2 页'));assert.equal(await p.locator('[data-expense-act=history]').count(),15);
  checks.push('费用所属月65笔，完整汇总6500元，50/15分页');
  await p.locator('[data-expense-act=history]').first().click();await p.locator('#dialog-body').waitFor({state:'visible'});assert.match(await p.locator('#dialog-body').innerText(),/2026-10-20/);await p.evaluate(()=>closeDialog());
  await range('expenses','2026-10-01','2026-10-31');await count(0);checks.push('费用业务日期与所属月叠加筛选；历史原单与付款记录可查看');
  await go('expense-payables');await p.locator('[data-expense-stage=payments]').click();await count(125);
  await range('expense-payments','2026-09-01','2026-09-30');await count(0);
  await range('expense-payments','2026-10-20','2026-10-20');await count(125);
  assert.match(await p.locator('#content').innerText(),/2,500/);await p.locator('#expense-pay-month').fill('2026-09');await count(65);
  await p.locator('[data-expense-stage=all]').click();await count(65);assert.equal(await p.locator('[data-resource-range=expense-payables] [name=start]').inputValue(),'');await p.locator('[data-expense-stage=payments]').click();await count(65);assert.equal(await p.locator('[data-resource-range=expense-payments] [name=start]').inputValue(),'2026-10-20');
  checks.push('实际付款日独立查询125笔，费用所属月可进一步缩小至65笔；原单日期与付款日期状态独立');
  await go('byproducts');await p.locator('[data-byproduct-view=ledger]').click();await count(65);await p.locator('[data-resource-pager=byproducts][data-target="2"]').click();await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('第 2 / 2 页'));
  await p.locator('[data-resource-act=receive]').first().click();await p.locator('#resource-form').waitFor({state:'visible'});assert.match(await p.locator('#dialog').innerText(),/豆渣收款/);await p.evaluate(()=>closeDialog());checks.push('豆渣销售分页与原单登记到账入口有效');
  await p.locator('[data-byproduct-view=receipts]').click();await count(65);
  await range('byproduct-receipts','2026-10-21','2026-10-21');await count(125);assert.match(await p.locator('#content').innerText(),/2,500/);
  checks.push('实际到账日包含历史销售跨月收款；原销售已收金额单独保留');
  for(const target of ['expenses','expense-payables','byproducts']){
   await p.evaluate(()=>{delete resourceLedgerState.expenses;delete resourceLedgerState.byproducts;});await go(target);if(target==='expenses')await count(65);if(target==='byproducts'){await p.locator('[data-byproduct-view=ledger]').click();await count(65);}await p.waitForLoadState('networkidle');
   for(const width of [1440,390,320]){await p.setViewportSize({width,height:900});await p.waitForTimeout(100);assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`${target} 横向溢出 ${width}`);await p.screenshot({path:path.join(out,`${target}-${width}.png`),fullPage:true});}
  }
  checks.push('三页1440/390/320无整体横向溢出');assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks,errors}));
 }catch(e){console.error(e.stack||e);console.error(JSON.stringify({errors}));process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(temp,{recursive:true,force:true});}
})();
