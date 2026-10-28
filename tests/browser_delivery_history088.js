'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'erp088-')),db=path.join(tmp,'test.db'),out=path.join(root,'output/配送周转筐历史-v0.88.1/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[];
try{
 cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'pipe'});
 cp.execFileSync('python3',['-c',`import sys,json
from pathlib import Path
from datetime import date,timedelta
import server,delivery_query as q,resources_costs as rc
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 for kind,(table,record_kind,_) in q.SOURCES.items():
  for i in range(126):
   day=(date(2025,1,1)+timedelta(days=i//2)).isoformat()
   line={'asset_id':'CR-YELLOW','asset_name':'原黄框','qty':2,'order_id':'H88-ORDER','customer_name':'原客户','customer_id':'C001'}
   trip={'id':'H88-SOURCE','kind':'trip','business_date':day,'trip_name':'归档原趟次','vehicle_name':'原车','driver':'原司机','amount_cents':101}
   r={'id':'H88-'+kind+str(i).zfill(4),'kind':record_kind,'version':1,'business_date':day,'feedback_date':day,'month':day[:7],'trip_count':1,'trip_name':'原趟次','vehicle_id':'V-A','vehicle_name':'原车辆','driver':'原司机','driver_ids':['D-A'],'driver_id':'D-A','partner':'H88运输','amount_cents':101,'asset_id':'CR-YELLOW','asset_name':'原黄框','qty':2,'customer_id':'C001','customer_name':'原客户','product_id':'P001','product_name':'原豆腐','actual_qty':'0.3','received_qty':'0.2','difference_qty':'-0.1','unit':'筐','order_id':'H88-ORDER','source_date':'2024-12-31','state':'confirmed' if i%2 else 'pending','movement':'return','submitted_at':day+'T12:00:00','note':'H88 合成历史 % _','lines':[trip] if kind=='documents' else [line],'document_id':'H88-DOCUMENT','private_key':'hidden','voided':i%10==0 if kind in ('trips','movements') else False}
   if kind=='feedback':r['state']='resolved' if i%2 else 'pending'
   if table=='trade_records':c.execute('INSERT INTO trade_records VALUES(?,?)',(r['id'],rc.dump(r)))
   else:c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(r['id'],r['id'],rc.dump(r)))
`,db],{cwd:root,stdio:'pipe'});
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>r(n));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});const base=`http://127.0.0.1:${port}`;
 for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.stack||e.message));
 const login=async(q,user)=>{await q.goto(base);await q.locator('[name=username]').fill(user);await q.locator('[name=password]').fill('Dashboard-Test-2026!');await q.locator('#auth-login-form [type=submit]').click();await q.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);await q.waitForLoadState('networkidle');};
 const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!busy&&!navigationLoading);if(await p.evaluate(()=>!!deliveryHistoryActive()))await p.waitForFunction(()=>!!deliveryHistoryReport().value);};
 const submit=async()=>{await p.locator('#delivery-history-form [type=submit]').click();await ready();};
 const shot=async name=>{for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});await p.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth+1);await p.screenshot({path:path.join(out,name+'-'+width+'.png'),fullPage:false});}await p.setViewportSize({width:1440,height:1000});};
 await login(p,'admin');await p.evaluate(()=>goto('dispatch'));await ready();await p.locator('[data-dispatch-tab=transport]').click();await p.locator('[data-delivery-history-open=trips]').click();await ready();
 for(const kind of ['trips','feedback','movements','requests','documents']){
  if(kind!=='trips'){await p.locator('[data-delivery-history-kind="'+kind+'"]').click();await ready();}
  await p.locator('#delivery-history-form [name=all_dates]').check();await p.locator('#delivery-history-form [name=search]').fill('H88');await submit();let r=await p.evaluate(()=>deliveryHistoryReport().value);assert.equal(r.total,126,kind);const summary=r.summary,ids=r.rows.map(x=>x.id);
  for(const target of [2,3]){await p.locator('[data-delivery-history-page="'+target+'"]').first().click();await ready();r=await p.evaluate(()=>deliveryHistoryReport().value);assert.deepEqual(r.summary,summary);ids.push(...r.rows.map(x=>x.id));}assert.equal(new Set(ids).size,126);assert.equal(r.rows.length,26);assert(r.rows.every(x=>!Object.hasOwn(x,'lines')));
  if(kind==='trips')assert.equal(summary[0].amount_cents,11413);
  if(kind==='feedback')assert.equal(summary[0].difference_qty,'-12.6');
  if(kind==='movements')assert.equal(summary[0].qty,'226');
  await shot(kind+'完整分页');await p.locator('[data-delivery-history-detail]').first().click();await p.locator('#overlay').waitFor({state:'visible'});await p.waitForFunction(()=>document.getElementById('dialog').innerText.includes(deliveryHistoryTitles[deliveryHistoryKind]));assert.equal(await p.locator('#dialog input').count(),0);assert(!((await p.locator('#dialog').innerText()).includes('hidden')));if(['requests','documents'].includes(kind))assert.match(await p.locator('#dialog').innerText(),/原记录完整明细/);await shot(kind+'只读原记录');await p.locator('#dialog-close').click();await p.locator('#overlay').waitFor({state:'hidden'});
 }
 await p.locator('#delivery-history-form [name=all_dates]').uncheck();await p.locator('#delivery-history-form [name=start]').fill('2025-07-01');await p.locator('#delivery-history-form [name=end]').fill('2025-06-01');await p.locator('#delivery-history-form [type=submit]').click();assert.match(await p.locator('#delivery-history-error').innerText(),/保留原查询/);assert.equal(await p.evaluate(()=>deliveryHistoryReport().value.total),126);
 await p.locator('[data-delivery-history-back]').click();await ready();assert.equal(await p.evaluate(()=>dispatchTab),'transport');
 await p.evaluate(()=>goto('crates'));await ready();await p.locator('[data-delivery-history-open=movements]').click();await ready();await p.locator('#delivery-history-form [name=all_dates]').uncheck();await p.locator('#delivery-history-form [name=start]').fill('2025-01-01');await p.locator('#delivery-history-form [name=end]').fill('2025-01-01');await p.locator('#delivery-history-form [name=search]').fill('H88');await submit();assert.equal(await p.evaluate(()=>deliveryHistoryReport().value.total),2);await p.locator('#delivery-history-form [name=search]').fill('完全空结果');await submit();assert.equal(await p.evaluate(()=>deliveryHistoryReport().value.total),0);await p.locator('[data-delivery-history-back]').click();await ready();
 for(const [target,kind] of [['weighing','feedback'],['settlements','feedback'],['expenses','documents'],['expense-payables','documents']]){await p.evaluate(t=>goto(t),target);await ready();await p.locator('[data-delivery-history-open="'+kind+'"]').click();await ready();assert.equal(await p.evaluate(()=>deliveryHistoryKind),kind);await p.locator('[data-delivery-history-back]').click();await ready();}
 const wh=await browser.newPage();await login(wh,'warehouse');await wh.evaluate(()=>goto('dispatch'));await wh.waitForLoadState('networkidle');await wh.locator('[data-delivery-history-open=trips]').click();await wh.waitForFunction(()=>!!deliveryHistoryReport().value);assert.equal(await wh.locator('[data-delivery-history-kind=documents]').count(),0);const response=await wh.request.get(base+'/api/delivery-history?kind=trips&all=1');assert.equal(response.status(),200);const text=await response.text();assert(!text.includes('_cents'));assert(!text.includes('document_id'));assert.equal((await wh.request.get(base+'/api/delivery-history?kind=trips&all=1&status=settled')).status(),403);await wh.close();
 assert.deepEqual(errors,[]);const result={ok:true,kinds:5,rows_each:126,checks:['五类记录各126项50/50/26无漏重，完整汇总不随分页改变','作废不计有效量、反馈按反馈日期及原单位、填报与实物流分开','完整原记录按需读取且只读，归档明细与填报明细保留','单日/空结果/非法日期保留/全部日期通过','配送、筐子、称重、算票、成本与付款入口及返回通过','库管金额和结算状态裁剪，1440/390/320无溢出'],errors};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){console.error(e.stack||e);if(browser){const p=browser.contexts()[0]?.pages()[0];if(p)await p.screenshot({path:path.join(out,'失败现场.png'),fullPage:true});}process.exitCode=1;}finally{await browser?.close();service?.kill();fs.rmSync(tmp,{recursive:true,force:true});}
})();
