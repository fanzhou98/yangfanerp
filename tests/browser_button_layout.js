'use strict';
// Visual geometry and real save actions, always against an isolated temporary DB.
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-buttons-')),db=path.join(temp,'navigation-test-buttons.db');
 const baseline=process.env.ERP_BUTTON_BASELINE_DIR,stage=baseline?'before':'after',out=process.env.ERP_BUTTON_OUTPUT_DIR||path.join(root,'docs/ux-v0.39.9');fs.mkdirSync(out,{recursive:true});
 cp.execFileSync('python3',['tests/seed_allocation.py',db],{cwd:root});
 cp.execFileSync('python3',['-c',`import server,auth,time,sys
from pathlib import Path
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 admin=auth.create_initial_admin(c,'admin','界面测试管理员','Button-Test-2026!',int(time.time()))
 u=auth.create_user(c,admin,{'username':'warehouse','display_name':'界面测试库管','role':'库管','password':'Button-Initial-2026!'},int(time.time()))
 auth.change_password(c,u,'Button-Initial-2026!','Button-Test-2026!',int(time.time()))
d=server.bootstrap();server.save_warehouse({'business_date':'2026-10-22','version':0,'inventory_revision':d['inventory_revision'],'stage':'confirm_dispatch','evidence_checked':True,'stock':[{'product_id':p['id'],'existing_qty':'40','produced_qty':'0'} for p in d['products']],'allocations':[{'order_id':o['id'],'product_id':l['product_id'],'ordered_qty':l['ordered_qty'],'qty':l['ordered_qty'],'mode':'manual'} for o in d['orders'] for l in o['lines']],'customers':[],'order_versions':{o['id']:o['version'] for o in d['orders']}},'库管')`,db],{cwd:root});
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 const base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 const result={stage,buttons:[],workflow:[],pageErrors:[]};
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===99)throw Error('test service did not start');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const ctx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),p=await ctx.newPage();p.on('pageerror',e=>result.pageErrors.push(e.message));
  if(baseline)for(const name of ['style.css','sheets.js','daily-work.js'])await p.route('**/'+name,route=>route.fulfill({body:fs.readFileSync(path.join(baseline,name)),contentType:name.endsWith('.css')?'text/css':'text/javascript'}));
  await p.goto(base);await p.locator('[name=username]').fill('warehouse');await p.locator('[name=password]').fill('Button-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);
  await p.evaluate(()=>{goto('weighing');});await p.waitForFunction(()=>page==='weighing'&&!navigationLoading);await p.locator('[data-sheet-action=save-weight-client]').first().waitFor();if(!baseline)await p.locator('[data-client-sheet=C001] [data-customer-toggle]').click();
  const measure=async selector=>p.locator(selector).first().evaluate(button=>{
   const r=button.getBoundingClientRect(),style=getComputedStyle(button),boxes=[];
   for(const node of button.childNodes){if(node.nodeType===Node.TEXT_NODE&&node.textContent.trim()){const range=document.createRange();range.selectNode(node);boxes.push(range.getBoundingClientRect());}else if(node.nodeType===Node.ELEMENT_NODE&&node.textContent.trim()&&getComputedStyle(node).display!=='none'){boxes.push(node.getBoundingClientRect());}}
   const left=Math.min(...boxes.map(r=>r.left)),right=Math.max(...boxes.map(r=>r.right)),top=Math.min(...boxes.map(r=>r.top)),bottom=Math.max(...boxes.map(r=>r.bottom));
   return {text:button.textContent.trim(),height:r.height,width:r.width,centerX:(left+right-r.left-r.right)/2,centerY:(top+bottom-r.top-r.bottom)/2,contentFits:left>=r.left-0.5&&right<=r.right+0.5&&top>=r.top-0.5&&bottom<=r.bottom+0.5,countVisible:[...button.querySelectorAll('.button-count')].some(el=>getComputedStyle(el).display!=='none'),colors:[...button.querySelectorAll('.button-label,.button-count')].filter(el=>el.textContent.trim()).map(el=>getComputedStyle(el).color),buttonColor:style.color};
  });
  const businessWrites=[];p.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname.startsWith('/api/')&&!new URL(r.url()).pathname.startsWith('/api/auth/'))businessWrites.push(r.url());});
  const clientSelector='[data-sheet-action=save-weight-client][data-cid=C001]',saveSelector='.page-head [data-sheet-action=save]';
  for(const state of ['clean','dirty']){
   if(state==='dirty'){await p.locator('[data-client-sheet=C001] [data-pid=P001][data-simple-weight=driver]').fill('60');if(!baseline){await p.clock.install();await p.clock.fastForward(65000);await p.waitForTimeout(150);assert.equal(businessWrites.length,0,'idle time caused a business write');assert.equal(await p.evaluate(()=>typeof maybeAutosave),'undefined');assert.match(await p.locator('#save-status').textContent(),/点击保存按钮/);result.manualSave='65 seconds elapsed after input: zero business POST requests';}}
   for(const width of [1440,1024,768,390,320]){
    await p.setViewportSize({width,height:900});await p.evaluate(()=>{updateSheetTotals();window.scrollTo(0,0);});
    const save=await measure(saveSelector),client=await measure(clientSelector),batch=await measure('[data-sheet-action=confirm-weight-batch]');result.buttons.push({width,state,save,client,batch});
    if(!baseline){
     for(const m of [save,client]){assert(Math.abs(m.centerX)<0.6,`${state}/${width} ${m.text} off-center X ${m.centerX}`);assert(Math.abs(m.centerY)<0.6,`${state}/${width} ${m.text} off-center Y ${m.centerY}`);assert(m.contentFits,`${width}: content clipped`);assert(m.colors.every(c=>c===m.buttonColor),`${width}: save label or count color differs`);assert.equal(m.countVisible,state==='dirty');assert.equal(m.height,width<=760?44:38);}
     assert.equal(save.height,batch.height,`${width}: toolbar button heights differ`);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
    if([1440,768,390].includes(width)){
     await p.locator('.page-head').screenshot({path:path.join(out,`${stage}-${width}-${state}-保存改动.png`)});
     await p.locator('[data-client-sheet=C001] .client-sheet-head').screenshot({path:path.join(out,`${stage}-${width}-${state}-保存本客户.png`)});
    }
   }
  }
  if(!baseline){
   await p.setViewportSize({width:1440,height:1000});await p.locator('[data-client-sheet=C002] [data-customer-toggle]').click();const firstId=await p.locator('[data-client-sheet=C001] [data-simple-weight=driver]').first().getAttribute('data-oid'),second=p.locator('[data-client-sheet=C002] [data-simple-weight=driver]').first(),secondId=await second.getAttribute('data-oid');await second.fill('80');
   const firstCid=await p.evaluate(id=>data.orders.find(o=>o.id===id).customer_id,firstId);await p.locator(`[data-sheet-action=save-weight-client][data-cid="${firstCid}"]`).click();await p.waitForFunction(id=>!busy&&data.orders.find(o=>o.id===id).lines.find(l=>l.product_id==='P001').driver_net==='60',firstId);
   assert(await p.evaluate(id=>orderDirty(sheetOrders.get(id)),secondId));assert(await p.locator('#sheet-dirty').isVisible());
   await p.locator(saveSelector).click();await p.waitForFunction(()=>!busy&&!unsavedChanges().length);assert(await p.locator('#sheet-dirty').isHidden());assert(await p.locator('[data-client-save-count]').first().isHidden());assert(await p.evaluate(()=>data.orders.every(o=>!o.weight_confirmation)));
   assert.equal(businessWrites.length,2);result.saveBehavior='client save preserves other edits; page save saves remaining edits; neither confirms handoff';
  }
  await p.evaluate(()=>{clearWorkingCopies();goto('dashboard');});await p.waitForFunction(()=>page==='dashboard'&&!navigationLoading);
  for(const width of [1440,1024,768,390,320]){
   await p.setViewportSize({width,height:900});
   await p.evaluate(()=>{document.querySelector('.daily-flow-panel').outerHTML=homeWorkflow([{title:'称重交接',description:'核对实发数量与称重后交会计',today:99,carry:888,completed:777,status:'待处理',items:[]}],today());window.scrollTo(0,0);});
   const layout=await p.locator('.home-task').first().evaluate(button=>{const counts=button.querySelector('.flow-task-counts'),r=counts.getBoundingClientRect(),groups=[...counts.querySelectorAll('.flow-task-count')];return {text:counts.textContent,display:getComputedStyle(counts).display,width:r.width,height:r.height,groups:groups.map(el=>{const a=el.getBoundingClientRect(),b=el.querySelector('b').getBoundingClientRect();return {text:el.textContent.trim(),top:a.top,bottom:a.bottom,width:a.width,numberTop:b.top,numberBottom:b.bottom,whiteSpace:getComputedStyle(el).whiteSpace}}),pageWidth:document.documentElement.scrollWidth,viewport:innerWidth};});result.workflow.push({width,...layout});
   if(!baseline){assert.equal(layout.groups.length,3);assert(layout.groups.every(g=>g.whiteSpace==='nowrap'));assert(Math.max(...layout.groups.map(g=>g.top))-Math.min(...layout.groups.map(g=>g.top))<1,'workflow metrics wrap to separate lines');assert(layout.height<25,'workflow label and number wrap');assert(layout.pageWidth<=width+1,'workflow overflows page');assert.equal(await p.locator('.home-task>.flow-open').first().isVisible(),width>760);}
   if([1440,390,320].includes(width))await p.locator('.daily-flow-panel').screenshot({path:path.join(out,`${stage}-${width}-每日流程.png`)});
  }
  assert.deepEqual(result.pageErrors,[]);result.ok=true;fs.writeFileSync(path.join(out,`${stage}-validation.json`),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({ok:true,stage,buttonCases:result.buttons.length,workflowCases:result.workflow.length,saveBehavior:result.saveBehavior,cleanOffsets:result.buttons.filter(r=>r.state==='clean').map(r=>({width:r.width,page:r.save.centerX,client:r.client.centerX}))},null,2));
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
