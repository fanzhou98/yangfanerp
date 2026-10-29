'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'erp087-')),db=path.join(tmp,'test.db'),out=path.join(root,'output/未日结收发存-v0.87.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[];
try{
 cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'pipe'});
 cp.execFileSync('python3',['-c',`import sys,json
from pathlib import Path
from datetime import date,timedelta
import server,inventory as inv
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 for i in range(126):
  day=(date(2025,1,1)+timedelta(days=i)).isoformat()
  inv.put(c,'warehouse_plans',{'business_date':day,'version':1,'allocation_state':'draft','stock':[{'product_id':'P001','existing_qty':'10','produced_qty':'0.1','loss_qty':'0.01','variance_reason':'合成未日结查询'}],'allocations':[]},'business_date')
 inv.put(c,'stock_closings',{'business_date':'2025-05-07','version':1,'state':'closed','products':[]},'business_date')
`,db],{cwd:root,stdio:'pipe'});
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>r(n));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});const base=`http://127.0.0.1:${port}`;
 for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.stack||e.message));
 const login=async(q,user)=>{await q.goto(base);await q.locator('[name=username]').fill(user);await q.locator('[name=password]').fill('Dashboard-Test-2026!');await q.locator('#auth-login-form [type=submit]').click();await q.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);await q.waitForLoadState('networkidle');};
 const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!busy&&!navigationLoading);if(await p.evaluate(()=>page==='allocation'&&openStockHistoryOpen))await p.waitForFunction(()=>!!openStockHistoryReport().value);};
 const submit=async()=>{await p.locator('#open-stock-history-form [type=submit]').click();await ready();};
 const shot=async name=>{for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});await p.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1);await p.screenshot({path:path.join(out,name+'-'+width+'.png'),fullPage:false});}await p.setViewportSize({width:1440,height:1000});};
 await login(p,'admin');await p.evaluate(()=>goto('allocation'));await ready();await p.locator('[data-warehouse-tab=closing]').click();const size=await p.evaluate(()=>data.warehouse_plans.length);await p.locator('[data-open-stock-history-open]').click();await ready();
 await p.locator('#open-stock-history-form [name=start]').fill('2025-01-01');await p.locator('#open-stock-history-form [name=end]').fill('2025-05-06');await p.locator('#open-stock-history-form [name=product_id]').selectOption('P001');await submit();let r=await p.evaluate(()=>openStockHistoryReport().value);assert.equal(r.total,126);assert.equal(r.days,126);assert.equal(r.summary[0].production_qty,'12.6');let ids=r.rows.map(x=>x.business_date+'|'+x.product_id),summary=r.summary;
 for(const page of [2,3]){await p.locator('[data-open-stock-history-page="'+page+'"]').first().click();await ready();const next=await p.evaluate(()=>openStockHistoryReport().value);assert.deepEqual(next.summary,summary);ids.push(...next.rows.map(x=>x.business_date+'|'+x.product_id));}assert.equal(new Set(ids).size,126);assert.equal(await p.evaluate(()=>data.warehouse_plans.length),size);assert(!Object.hasOwn(summary[0],'book_qty'));await shot('完整分页与锁定');
 await p.locator('[data-open-stock-history-detail]').first().click();assert.match(await p.locator('#dialog').innerText(),/当前登记来源重算/);assert.equal(await p.locator('#dialog input').count(),0);await shot('只读依据');await p.locator('[data-open-stock-history-source]').click();await ready();assert.equal(await p.evaluate(()=>selectedDate),'2025-01-26');assert.equal(await p.evaluate(()=>openStockHistoryOpen),false);assert.match(await p.locator('#content').innerText(),/已日结锁定/);
 await p.locator('[data-open-stock-history-open]').click();await ready();await p.locator('#open-stock-history-form [name=product_id]').selectOption('P002');await submit();r=await p.evaluate(()=>openStockHistoryReport().value);assert.equal(r.total,126);assert.equal(r.unknown_rows,126);assert.equal(r.unregistered_rows,126);assert.equal(r.summary[0].production_qty,null);assert.match(await p.locator('#content').innerText(),/未登记/);await shot('未知不当零');
 await p.locator('#open-stock-history-form [name=start]').fill('2025-07-01');await p.locator('#open-stock-history-form [name=end]').fill('2025-06-01');await p.locator('#open-stock-history-form [type=submit]').click();assert.match(await p.locator('#open-stock-history-error').innerText(),/保留原查询/);assert.equal(await p.evaluate(()=>openStockHistoryReport().value.total),126);
 await p.locator('#open-stock-history-form [name=start]').fill('2025-01-01');await p.locator('#open-stock-history-form [name=end]').fill('2025-01-01');await submit();assert.equal(await p.evaluate(()=>openStockHistoryReport().value.total),1);
 await p.locator('#open-stock-history-form [name=search]').fill('无此产品');await submit();assert.equal(await p.evaluate(()=>openStockHistoryReport().value.total),0);
 await p.locator('#open-stock-history-form [name=all_dates]').check();await p.locator('#open-stock-history-form [name=search]').fill('');await p.locator('#open-stock-history-form [name=status]').selectOption('unregistered');await submit();assert((await p.evaluate(()=>openStockHistoryReport().value.total))>=126);
 await p.locator('[data-open-stock-history-back]').click();await ready();assert.equal(await p.evaluate(()=>warehouseTab),'stock');assert.equal(await p.evaluate(()=>data.warehouse_plans.length),size);
 const wh=await browser.newPage();await login(wh,'warehouse');const response=await wh.request.get(base+'/api/open-stock-history?all=1');assert.equal(response.status(),200);const text=await response.text();assert(!text.includes('_cents'));assert(!text.includes('price'));await wh.close();
 assert.deepEqual(errors,[]);const result={ok:true,checks:['126项跨月记录50/50/26分页无漏重，完整发生量汇总不变且不累加余额','未登记生产和报损不当0，期初未知不猜测','后续日结锁定日期保留只读状态','错误日期保留结果，单日/空结果/全部日期/筛选通过','只读依据与同步进入原业务日，返回原库存页签','库管仅数量，1440/390/320无页面溢出'],errors};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){console.error(e.stack||e);if(browser){const p=browser.contexts()[0]?.pages()[0];if(p)await p.screenshot({path:path.join(out,'失败现场.png'),fullPage:true});}process.exitCode=1;}finally{await browser?.close();service?.kill();fs.rmSync(tmp,{recursive:true,force:true});}
})();
