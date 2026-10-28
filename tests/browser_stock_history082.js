'use strict';
const {chromium}=require('/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'erp082-')),db=path.join(tmp,'test.db'),out=path.join(root,'output/成品日结历史-v0.82.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[];
try{
 cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'pipe'});
 cp.execFileSync('python3',['-c',`import sys,json
from pathlib import Path
from datetime import date,timedelta
import server,resources_costs as rc,order_corrections as correction
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 products=[dict(p) for p in c.execute('SELECT id,name,unit FROM products ORDER BY id LIMIT 2')]
 for i in range(63):
  day=(date(2026,6,1)+timedelta(days=i)).isoformat()
  rows=[{'product_id':p['id'],'product_name':'SH82 '+p['name'],'unit':p['unit'],'opening_qty':'10','production_qty':'5','purchased_qty':'1','return_restock_qty':'0','processing_output_qty':'0','processing_input_qty':'0','loss_qty':'2','shipped_qty':'4','book_qty':'10','counted_qty':'11','variance_qty':'1','variance_reason':'合成盘点原因'} for p in products]
  v={'business_date':day,'state':'reopened' if i==62 else 'closed','version':2 if i==62 else 1,'products':rows,'closed_at':day+'T18:00:00','role':'库管','reopen_reason':'合成撤销测试' if i==62 else ''}
  c.execute('INSERT INTO stock_closings VALUES(?,?)',(day,rc.dump(v)))
 a={'id':'SH82-CORRECTION','kind':'shipment','business_date':'2026-06-01','stock_anchor_date':'2026-06-01','order_id':'SH82-ORDER','reason':'合成实发更正','at':'2026-09-01','quantity_changes':[{'product_id':products[0]['id'],'delta_qty':'-2'}]}
 c.execute('INSERT INTO order_corrections VALUES(?,?)',(a['id'],rc.dump(a)))
 raw=json.loads(c.execute("SELECT payload FROM stock_closings WHERE business_date='2026-06-01'").fetchone()[0]);expected=correction.restated_closing(c,raw)
 Path(sys.argv[2]).write_text(json.dumps({'products':products,'expected':expected}))
`,db,path.join(tmp,'fixture.json')],{cwd:root,stdio:'pipe'});
 const fixture=JSON.parse(fs.readFileSync(path.join(tmp,'fixture.json'))),port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>r(n));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});const base=`http://127.0.0.1:${port}`;
 for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.stack||e.message));
 const login=async(q,user)=>{await q.goto(base);await q.locator('[name=username]').fill(user);await q.locator('[name=password]').fill('Dashboard-Test-2026!');await q.locator('#auth-login-form [type=submit]').click();await q.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);await q.waitForLoadState('networkidle');};
 const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!busy&&!navigationLoading);if(await p.evaluate(()=>page==='allocation'&&stockHistoryOpen))await p.waitForFunction(()=>!!stockHistoryReport().value);};
 const submit=async()=>{await p.locator('#stock-history-form [type=submit]').click();await ready();};
 const shot=async name=>{for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});await p.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' '+width);await p.screenshot({path:path.join(out,name+'-'+width+'.png'),fullPage:false});}await p.setViewportSize({width:1440,height:1000});};

 await login(p,'admin');await p.evaluate(()=>goto('allocation'));await ready();await p.locator('[data-warehouse-tab=closing]').click();const size=await p.evaluate(()=>data.stock_closings.length);await p.locator('[data-stock-history-open]').click();await ready();await p.locator('#stock-history-form [name=all_dates]').check();await p.locator('#stock-history-form [name=search]').fill('SH82');await submit();let r=await p.evaluate(()=>stockHistoryReport().value);assert.equal(r.total,126);assert.equal(r.days,63);let ids=r.rows.map(x=>x.business_date+'|'+x.product_id),summary=r.quantities;
 for(const page of [2,3]){await p.locator('[data-stock-history-page="'+page+'"]').first().click();await ready();const next=await p.evaluate(()=>stockHistoryReport().value);assert.deepEqual(next.quantities,summary);ids.push(...next.rows.map(x=>x.business_date+'|'+x.product_id));}assert.equal(new Set(ids).size,126);assert.equal(await p.evaluate(()=>data.stock_closings.length),size);assert(!Object.hasOwn(summary[0],'counted_qty'));await shot('日结历史完整分页');
 await p.locator('#stock-history-form [name=status]').selectOption('corrected');await submit();r=await p.evaluate(()=>stockHistoryReport().value);assert.equal(r.total,2);const corrected=r.rows.find(x=>x.product_id===fixture.products[0].id),expected=fixture.expected.products.find(x=>x.product_id===fixture.products[0].id);assert.equal(corrected.book_qty,expected.book_qty);assert.equal(corrected.counted_qty,'11');assert.equal(corrected.shipped_qty,'2');assert.equal(corrected.variance_qty,'-1');await shot('历史更正保留原实盘');
 await p.locator('[data-stock-history-detail]').first().click();await p.locator('#dialog').waitFor();assert.match(await p.locator('#dialog').innerText(),/原日结账面/);await p.locator('#dialog-close').click();await p.locator('#overlay').waitFor({state:'hidden'});
 await p.locator('#stock-history-form [name=all_dates]').uncheck();await p.locator('#stock-history-form [name=start]').fill('2026-07-01');await p.locator('#stock-history-form [name=end]').fill('2026-06-01');await p.locator('#stock-history-form [type=submit]').click();assert.match(await p.locator('#stock-history-error').innerText(),/保留原查询/);assert.equal(await p.evaluate(()=>stockHistoryReport().value.total),2);
 await p.locator('#stock-history-form [name=start]').fill('2026-08-02');await p.locator('#stock-history-form [name=end]').fill('2026-08-02');await p.locator('#stock-history-form [name=status]').selectOption('reopened');await submit();r=await p.evaluate(()=>stockHistoryReport().value);assert.equal(r.total,2);assert.deepEqual(r.quantities,[]);await shot('已撤销日结不参与汇总');
 await p.locator('[data-stock-history-back]').click();await ready();assert.equal(await p.evaluate(()=>warehouseTab),'closing');assert.equal(await p.evaluate(()=>data.stock_closings.length),size);
 const wh=await browser.newPage();await login(wh,'warehouse');const response=await wh.request.get(base+'/api/stock-history?all=1');assert.equal(response.status(),200);const text=await response.text();assert(!text.includes('_cents'));assert(!text.includes('price'));await wh.close();
 assert.deepEqual(errors,[]);const result={ok:true,checks:['126项跨月记录50/50/26分页无漏重，完整发生量汇总不变且不累加余额','历史实发更正与原投影一致：实发2、账面12、实盘11、差异-1','撤销日结不参与有效发生量汇总','错误日期保留原结果，只读依据及返回日结作业保留','库管只返回数量，1440/390/320无页面溢出'],errors};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){console.error(e.stack||e);if(browser){const p=browser.contexts()[0]?.pages()[0];if(p){console.error(await p.locator('#page-feedback').textContent());await p.screenshot({path:path.join(out,'失败现场.png'),fullPage:true});}}process.exitCode=1;}finally{await browser?.close();service?.kill();fs.rmSync(tmp,{recursive:true,force:true});}
})();
