'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-q01-')),db=path.join(temp,'test.db'),out=path.join(root,'output/销售日期查询与分页-v0.63.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  cp.execFileSync('python3',['-c',`
import json,sqlite3,sys
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
con=sqlite3.connect(sys.argv[1]);today=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
for i in range(63):
 day=(date(2026,8,1)+timedelta(days=i)).isoformat() if i<60 else today
 cid=f'Q01C{i:03d}';pid=f'Q01P{i:03d}';region=f'Q01R{i:02d}';market=f'Q01M{i:02d}'
 con.execute('INSERT OR IGNORE INTO customers(id,name,region,route,note,delivery_method,legal_name,business_kind) VALUES(?,?,?,?,?,?,?,?)',(cid,f'Q01客户{i:02d}',region,market,'','delivery',f'Q01客户{i:02d}','sales'))
 amount=100000+(i%5)*1000
 order={'id':f'Q01O{i:03d}','version':2,'customer_id':cid,'customer_name':f'Q01客户{i:02d}','business_date':day,'state':'reviewed','total_cents':amount,'paid_cents':0,'return_credit_cents':0,'discount_cents':0,'rounding_cents':0,'lines':[{'product_id':pid,'product_name':f'Q01产品{i:02d}','unit':'筐','ordered_qty':'10','actual_qty':'10','billing_unit':'公斤','bill_qty':'50','amount_cents':amount}]}
 con.execute('INSERT INTO orders VALUES(?,?)',(order['id'],json.dumps(order,ensure_ascii=False)))
con.commit();con.close()
`,db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;let healthy=false;for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok){healthy=true;break;}}catch{}await new Promise(r=>setTimeout(r,50));}assert(healthy);
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const go=async target=>{await p.evaluate(x=>goto(x),target);await ready();};
  const waitReport=async()=>{await p.waitForFunction(()=>document.querySelector('[data-sales-page]')||salesChainActive);await p.waitForLoadState('networkidle');};
  const waits=async predicate=>p.waitForFunction(predicate);
  await go('sales-daily');await waitReport();
  const today=await p.evaluate(()=>today());assert.equal(await p.locator('#sales-range-current').innerText(),today);assert.equal(await p.evaluate(()=>salesRange.choice),'today');assert(await p.locator('[data-sales-page]').count()>=1);
  checks.push('首次进入默认今日，日期范围由独立销售状态保存');
  await p.locator('[data-sales-range-act=quick][data-sales-range-value=last-month]').click();await waits(()=>salesRange.choice==='last-month');await waitReport();assert.equal(await p.evaluate(()=>salesRange.start),'2026-09-01');assert.equal(await p.evaluate(()=>salesRange.end),'2026-09-30');assert.match(await p.locator('#content').innerText(),/共 29 行/);
  checks.push('上月快捷范围按北京时间月末计算，切换后重新查询');
  await p.locator('[data-sales-range-act=edit][data-sales-range-value=custom]').click();await p.locator('#sales-range-start').fill('2026-08-01');await p.locator('#sales-range-end').fill('2026-09-29');await p.locator('[data-sales-range-form=custom] button[type=submit]').click();await waits(()=>salesRange.start==='2026-08-01'&&salesRange.end==='2026-09-29');await waitReport();
  assert.match(await p.locator('#content').innerText(),/共 60 行/);assert.match(await p.locator('#content').innerText(),/第 1 \/ 2 页/);assert.equal(await p.evaluate(()=>document.querySelectorAll('#content .resource-panel .table-wrap tbody tr').length),50);
  await p.evaluate(()=>{rangeStart='2026-01-01';rangeEnd='2026-01-31';rangeMode=true;rangeBasis='business_date';});await go('ledger');await go('sales-daily');await waitReport();assert.equal(await p.evaluate(()=>salesRange.start),'2026-08-01');assert.equal(await p.evaluate(()=>salesRange.end),'2026-09-29');
  checks.push('销售范围与其他页面状态隔离，往返应收页不覆盖销售日期');
  await p.locator('[data-sales-page="2"]').click();await waits(()=>document.querySelector('#content .report-table-summary')?.textContent.includes('第 2 / 2 页'));assert.equal(await p.evaluate(()=>document.querySelectorAll('#content .resource-panel .table-wrap tbody tr').length),10);
  await p.locator('#sales-state').selectOption('unpaid');await waits(()=>document.querySelector('#content .report-table-summary')?.textContent.includes('第 1 / 2 页'));assert.equal(await p.evaluate(()=>salesPage),1);
  checks.push('自定义跨月范围汇总覆盖全部60行，服务端分页50/10，切筛选回第1页');
  const summaryTotal=await p.evaluate(()=>document.querySelector('#content .report-table-summary').textContent);
  assert.match(summaryTotal,/60 位客户/);
  for(const view of ['products','markets','regions','alerts']){
   await p.locator(`[data-sales-view=${view}]`).click();await p.waitForFunction(v=>salesTableView===v,view);await waitReport();assert.equal(await p.evaluate(()=>salesTableView),view);assert.equal(await p.evaluate(()=>salesPage),1);const expected=view==='alerts'?54:60;assert.match(await p.locator('#content').innerText(),new RegExp('共 '+expected+' 行|'+expected+' 位客户'));assert(await p.locator('[data-sales-page]').count()>=1);
  }
  checks.push('产品、市场、地区、欠款提醒四页签均使用同一范围和服务端分页');
  await p.locator('[data-sales-view=fulfillment]').click();await p.waitForFunction(()=>salesChainActive?.summary.orders===60);assert.equal(await p.locator('[data-sales-chain-page="2"]').count(),1);await p.locator('[data-sales-chain-page="2"]').click();await p.waitForFunction(()=>salesChainActive?.page===2);assert.equal(await p.evaluate(()=>salesChainActive.rows.length),10);
  checks.push('订货与实发核对沿用同一跨月范围，第二页10行');
  await p.locator('[data-sales-range-act=quick][data-sales-range-value=all]').click();await waits(()=>salesRange.all===true);await p.waitForFunction(()=>salesChainActive?.summary.orders>=63);assert(await p.evaluate(()=>salesChainActive.start)<='2026-08-01');assert(await p.evaluate(()=>salesChainActive.end)>=today);
  checks.push('全部日期仍分页并返回有效起止边界，不无界下发全部行');
  for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});await p.evaluate(()=>closeMobileNavigation());await p.waitForTimeout(200);await p.evaluate(()=>scrollTo(0,0));assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),'销售页横向溢出 '+width);await p.locator('[data-sales-view=customers]').click().catch(()=>{});await waitReport();await p.screenshot({path:path.join(out,`销售日期与分页-${width}.png`),fullPage:true});checks.push(`销售日期控制与分页 ${width}px 无页面横向溢出`);}
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({ok:true,checks,errors},null,2)+'\n');console.log(JSON.stringify({ok:true,checks,errors}));
 }finally{if(browser)await browser.close();if(service){service.kill();if(service.exitCode===null&&service.signalCode===null)await new Promise(r=>service.once('exit',r));}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack);process.exit(1);});
