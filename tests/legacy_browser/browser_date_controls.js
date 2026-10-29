'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-date-controls-')),db=path.join(temp,'test.db'),out=process.env.ERP_BROWSER_OUTPUT||path.join(root,'output/日期筛选重复入口清理-v'+fs.readFileSync(path.join(root,'VERSION'),'utf8').trim()+'/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===119)throw Error('测试服务未启动');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
  p.on('response',async r=>{if(r.url().includes('/api/receivables?')||r.url().includes('/api/fund-accounts?')){try{const v=await r.json();responses.push({url:r.url(),count:(v.rows||v.movements||[]).length});}catch{}}});
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);

  const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const go=async target=>{await p.evaluate(x=>goto(x),target);await ready();};
  const shot=async label=>{for(const width of [1440,390,320]){await p.setViewportSize({width,height:900});await ready();assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`${label} 横向溢出 ${width}`);await p.screenshot({path:path.join(out,`${label}-${width}.png`),fullPage:true});}await p.setViewportSize({width:1440,height:1000});};
  await go('settlements');
  assert.equal(await p.locator('#range-basis').count(),1);assert.equal(await p.locator('[data-account-day],.accounting-business-date,#sheet-date').count(),0);
  await p.locator('#range-basis').selectOption('settled_date');await ready();
  for(const choice of ['yesterday','today','tomorrow','this-month','all']){await p.locator(`[data-range-act=quick][data-range-value="${choice}"]`).click();await ready();assert.equal(await p.locator('#range-basis').inputValue(),'settled_date');}
  await p.locator('[data-range-act=edit][data-range-value=custom]').click();await p.locator('#range-start').fill('2026-10-01');await p.locator('#range-end').fill('2026-10-20');await p.locator('[data-range-form=custom] [type=submit]').click();await ready();
  assert.deepEqual(await p.evaluate(()=>({start:rangeStart,end:rangeEnd,basis:rangeBasis})),{start:'2026-10-01',end:'2026-10-20',basis:'settled_date'});
  const order={business_date:'2026-09-30',settlement:{at:'2026-10-20T10:00:00+08:00'}};
  assert.equal(await p.evaluate(o=>processingDateMatches(o),order),true);
  await p.locator('#range-basis').selectOption('business_date');await ready();assert.equal(await p.evaluate(o=>processingDateMatches(o),order),false);
  await shot('销售算票');checks.push('销售算票仅一套日期筛选；快捷范围保留算票确认口径，跨月原单按所选口径匹配');
  await p.evaluate(()=>{accountingBook='purchase';render();});await ready();assert.equal(await p.locator('#goods-accounting-date').count(),1);assert.equal(await p.locator('#range-basis,[data-account-day],.accounting-business-date').count(),0);
  await p.locator('#goods-accounting-date').fill('2026-10-19');await ready();assert.equal(await p.evaluate(()=>selectedDate),'2026-10-19');await shot('外购算票');checks.push('外购算票只保留到货日期，仍按日筛选');
  await go('byproducts');await p.locator('[data-byproduct-view=ledger]').click();await ready();assert.equal(await p.locator('#resource-month').count(),0);assert.equal(await p.locator('[data-resource-range=byproducts]').count(),1);
  const range=async(target,start,end)=>{const f=p.locator(`[data-resource-range="${target}"]`);await f.locator('[name=start]').fill(start);await f.locator('[name=end]').fill(end);await f.locator('button').click();await ready();};
  await range('byproducts','2026-09-01','2026-10-20');await shot('豆渣销售范围');
  await p.locator('[data-byproduct-view=receipts]').click();await ready();assert.equal(await p.locator('#resource-month').count(),0);await range('byproduct-receipts','2026-10-01','2026-10-21');await shot('豆渣到账范围');
  await p.locator('[data-byproduct-view=ledger]').click();await ready();assert.equal(await p.locator('[data-resource-range=byproducts] [name=start]').inputValue(),'2026-09-01');
  await p.locator('[data-byproduct-view=daily]').click();await ready();assert.equal(await p.locator('#resource-month').count(),1);assert.equal(await p.locator('[data-resource-range]').count(),0);
  const monthly=await p.evaluate(()=>resourceLedgerDates('byproduct-month',true));assert.match(monthly.start,/-01$/);checks.push('豆渣销售和到账分别保留独立范围；每日结算保留月份，月汇总不受台账自定义日期影响');
  let unblock;const gate=new Promise(r=>unblock=r);await p.route('**/api/product-profit?**',async route=>{await gate;await route.continue();});
  const profitRequest=p.waitForRequest('**/api/product-profit?**');await p.evaluate(()=>goto('analytics'));await p.waitForFunction(()=>page==='analytics'&&!navigationLoading&&document.querySelector('#resource-month'));await profitRequest;assert.equal(await p.locator('#resource-month').count(),1);assert.equal(await p.locator('#profit-month').count(),0);unblock();await ready();await p.unroute('**/api/product-profit?**');
  assert.equal(await p.locator('#profit-month').count(),0);await shot('经营看板');
  await go('product-profit');assert.equal(await p.locator('#profit-month').count(),1);checks.push('经营看板在加载与完成状态均复用顶部月份；独立产品测算仍可选月份');
  assert.deepEqual(errors,[]);const result={ok:true,checks,errors};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){console.error(e.stack||e);console.error(JSON.stringify({errors}));process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(temp,{recursive:true,force:true});}
})();
