'use strict';
const {chromium}=require('/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'erp083-')),db=path.join(tmp,'test.db'),out=path.join(root,'output/库存核对历史-v0.83.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[];
try{
 cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'pipe'});
 cp.execFileSync('python3',['-c',`import sys,json,copy
from pathlib import Path
from datetime import date,timedelta
import server,resources_costs as rc
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 products=[dict(p) for p in c.execute('SELECT id,name,unit FROM products ORDER BY id LIMIT 2')]
 customer=dict(c.execute("SELECT id,name FROM customers WHERE business_kind!='byproduct' ORDER BY id LIMIT 1").fetchone())
 for i in range(63):
  day=(date(2026,6,1)+timedelta(days=i)).isoformat();pid='CH83-'+day
  rows=[{'product_id':p['id'],'unit':p['unit'],'pre_qty':'10','post_qty':'8','post_in_qty':'0','post_out_qty':'0','movement_note':'','post_source':'manual'} for p in products]
  source=[{'order_id':pid,'customer_id':customer['id'],'customer_name':customer['name'],'product_id':p['id'],'unit':p['unit'],'actual_qty':'2','ordered_qty':'3'} for p in products]
  v={'id':'IC-'+day,'kind':'inventory-check','business_date':day,'version':2,'products':rows,'source_snapshot':source,'source_fingerprint':__import__('inventory_reconciliation').digest(source),'sources_checked':i!=62,'handler':'CH83经办','note':'CH83 原保存依据','updated_at':day+'T18:00:00','role':'库管'}
  old=copy.deepcopy(v);old['version']=1
  for l in old['source_snapshot']:l['actual_qty']='3'
  old['sources_checked']=True;v['history']=[old]
  c.execute('INSERT INTO trade_records VALUES(?,?)',(v['id'],rc.dump(v)))
  if i==0:
   order=server.normalize_order(c,{'customer_id':customer['id'],'business_date':day,'batch':'CH83','lines':[{'product_id':p['id'],'actual_qty':'0','ordered_qty':'3','price':'3','driver':[],'customer':[]} for p in products]});order['id']=pid
   for line in order['lines']:line['actual_qty']='1'
   c.execute('INSERT INTO orders VALUES(?,?)',(pid,rc.dump(order)))
 Path(sys.argv[2]).write_text(json.dumps({'products':products}))
`,db,path.join(tmp,'fixture.json')],{cwd:root,stdio:'pipe'});
 const fixture=JSON.parse(fs.readFileSync(path.join(tmp,'fixture.json'))),port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>r(n));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});const base=`http://127.0.0.1:${port}`;
 for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.stack||e.message));
 const login=async(q,user)=>{await q.goto(base);await q.locator('[name=username]').fill(user);await q.locator('[name=password]').fill('Dashboard-Test-2026!');await q.locator('#auth-login-form [type=submit]').click();await q.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);await q.waitForLoadState('networkidle');};
 const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!busy&&!navigationLoading);if(await p.evaluate(()=>page==='allocation'&&checkHistoryOpen))await p.waitForFunction(()=>!!checkHistoryReport().value);};
 const submit=async()=>{await p.locator('#check-history-form [type=submit]').click();await ready();};
 const shot=async name=>{for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});await p.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' '+width);await p.screenshot({path:path.join(out,name+'-'+width+'.png'),fullPage:false});}await p.setViewportSize({width:1440,height:1000});};

 await login(p,'admin');await p.evaluate(()=>goto('purchases'));await ready();assert.equal(await p.locator('#content h1').textContent(),'原辅料采购登记');assert(await p.evaluate(()=>{const h=document.querySelector('#content h1'),t=document.querySelector('[aria-label="采购品类"]');return h.getBoundingClientRect().bottom<=t.getBoundingClientRect().top;}));await shot('原辅料采购标题在子标签上方');await p.locator('[data-goods-view=finished]').click();await ready();assert.equal(await p.locator('#content h1').textContent(),'外购成品');await p.locator('[data-goods-view=raw]').click();await ready();assert.equal(await p.locator('#content h1').textContent(),'原辅料采购登记');
 await p.evaluate(()=>goto('allocation'));await ready();await p.locator('[data-warehouse-tab=reconciliation]').click();await ready();const size=await p.evaluate(()=>data.orders.length);await p.locator('[data-check-history-open]').click();await ready();await p.locator('#check-history-form [name=all_dates]').check();await p.locator('#check-history-form [name=search]').fill('CH83');await submit();let r=await p.evaluate(()=>checkHistoryReport().value);assert.equal(r.total,126);assert.equal(r.days,63);let ids=r.rows.map(x=>x.business_date+'|'+x.version+'|'+x.product_id),summary=r.summary;
 for(const page of [2,3]){await p.locator('[data-check-history-page="'+page+'"]').first().click();await ready();const next=await p.evaluate(()=>checkHistoryReport().value);assert.deepEqual(next.summary,summary);ids.push(...next.rows.map(x=>x.business_date+'|'+x.version+'|'+x.product_id));}assert.equal(new Set(ids).size,126);assert.equal(await p.evaluate(()=>data.orders.length),size);assert(!Object.hasOwn(summary[0],'shipped_qty'));assert.equal(summary[0].unit,fixture.products.find(p=>p.id===summary[0].product_id).unit);await shot('保存时核对历史完整分页');
 await p.locator('#check-history-form [name=versions]').selectOption('all');await submit();r=await p.evaluate(()=>checkHistoryReport().value);assert.equal(r.total,252);ids=[];const allSummary=r.summary;
 for(let page=1;page<=r.pages;page++){if(page>1){await p.locator('[data-check-history-page="'+page+'"]').first().click();await ready();}const next=await p.evaluate(()=>checkHistoryReport().value);assert.deepEqual(next.summary,allSummary);ids.push(...next.rows.map(x=>x.business_date+'|'+x.version+'|'+x.product_id));}assert.equal(new Set(ids).size,252);
 await p.locator('#check-history-form [name=all_dates]').uncheck();await p.locator('#check-history-form [name=start]').fill('2026-06-01');await p.locator('#check-history-form [name=end]').fill('2026-06-01');await submit();r=await p.evaluate(()=>checkHistoryReport().value);assert.equal(r.total,4);assert.deepEqual(r.rows.map(x=>x.difference_qty),['0','0','1','1']);await shot('历史版本按原实发快照核对');
 await p.locator('[data-check-history-detail="2"]').click();await p.locator('#dialog').waitFor();assert.match(await p.locator('#dialog').innerText(),/版本 1/);assert.match(await p.locator('#dialog').innerText(),/CH83-2026-06-01/);assert.equal(await p.locator('#dialog [data-check-save]').count(),0);await p.locator('#dialog-close').click();await p.locator('#overlay').waitFor({state:'hidden'});
 await p.locator('#check-history-form [name=start]').fill('2026-07-01');await p.locator('#check-history-form [type=submit]').click();assert.match(await p.locator('#check-history-error').innerText(),/保留原查询/);assert.equal(await p.evaluate(()=>checkHistoryReport().value.total),4);
 await p.locator('[data-check-history-live]').first().click();await ready();await p.waitForFunction(()=>!!inventoryCheckState('2026-06-01').value);assert.equal(await p.evaluate(()=>selectedDate),'2026-06-01');assert(await p.evaluate(()=>inventoryCheckState('2026-06-01').value.source_changed));assert.equal(await p.evaluate(()=>inventoryCheckState('2026-06-01').value.products.find(x=>x.product_id===data.products[0].id).difference_qty),'-1');await shot('当前来源变化单独核验');
 const acc=await browser.newPage();await login(acc,'accountant');await acc.evaluate(()=>{goto('allocation');warehouseTab='reconciliation';render();});await acc.waitForLoadState('networkidle');await acc.locator('[data-check-history-open]').click();await acc.waitForFunction(()=>!!checkHistoryReport().value);assert.equal(await acc.locator('[data-check-edit]').count(),0);const response=await acc.request.get(base+'/api/inventory-check-record?date=2026-06-01&version=1');assert.equal(response.status(),200);const text=await response.text();assert(!text.includes('_cents'));assert(!text.includes('price'));await acc.close();
 assert.deepEqual(errors,[]);const result={ok:true,checks:['原辅料采购登记标题在子标签上方，切换外购成品保留标题与功能','最新126项50/50/26、全部版本252项分页无漏重，完整项数汇总不变','同日旧版实发3差异1、最新版实发2差异0，当前实发1差异-1单独核验','只读原保存依据、错误日期保留结果、当前来源变化提示正确','会计仅核对权限可查看不可编辑，无金额价格，1440/390/320无页面溢出'],errors};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){console.error(e.stack||e);if(browser){const p=browser.contexts()[0]?.pages()[0];if(p){console.error(await p.locator('#page-feedback').textContent());await p.screenshot({path:path.join(out,'失败现场.png'),fullPage:true});}}process.exitCode=1;}finally{await browser?.close();service?.kill();fs.rmSync(tmp,{recursive:true,force:true});}
})();
