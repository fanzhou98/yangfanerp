'use strict';
// Uses an isolated database; never opens or mutates the factory's business database.
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-ux-')),db=path.join(temp,'navigation-test-ux.db');
 cp.execFileSync('python3',[path.join(root,'tests/seed_allocation.py'),db]);
 cp.execFileSync('python3',['-c',`import server,auth,time,sys\nfrom pathlib import Path\nserver.DB=Path(sys.argv[1])\nwith server.connect(True) as c:\n admin=auth.create_initial_admin(c,'admin','测试管理员','UX-Initial-2026!',int(time.time()))\n auth.change_password(c,admin,'UX-Initial-2026!','UX-Permanent-2026!',int(time.time()))\n for name,role in [('warehouse','库管'),('accountant','会计'),('cashier','出纳'),('director','厂长'),('logistics','物流负责人'),('driver','司机'),('owner','老板')]:\n  u=auth.create_user(c,admin,{'username':name,'display_name':'测试'+role,'role':role,'password':'UX-Initial-2026!'},int(time.time()))\n  auth.change_password(c,u,'UX-Initial-2026!','UX-Permanent-2026!',int(time.time()))`,db],{cwd:root});
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 const base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',[path.join(root,'server.py'),'--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
 const out=process.env.ERP_UX_OUTPUT_DIR||path.join(root,'docs/ux-v0.39.9/collaboration');fs.mkdirSync(out,{recursive:true});let browser;
 const results=[],errors=[];
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===99)throw Error('test service unavailable');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const login=async name=>{const c=await browser.newContext({viewport:{width:1440,height:1000}}),p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.dismiss());await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill('UX-Permanent-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);return p;};
  const go=async(p,name)=>{await p.evaluate(name=>goto(name),name);await p.waitForFunction(name=>page===name&&!navigationLoading,name);};
  const sessions={};for(const name of ['admin','warehouse','accountant','cashier','director','logistics','driver','owner'])sessions[name]=await login(name);
  const wh=sessions.warehouse,accountant=sessions.accountant,admin=sessions.admin;
  await go(wh,'orders');await go(accountant,'orders');
  const id=await wh.evaluate(()=>data.orders.find(o=>o.customer_id==='C001').id),selector=`[data-matrix-key="${id}"][data-product-id="P001"]`;
  await accountant.locator(selector).fill('10');await wh.locator(selector).fill('9');
  await wh.locator('[data-sheet-action=save]').click();await wh.waitForFunction(()=>!busy&&!unsavedChanges().length);
  assert.equal(await wh.locator('#work-status-bar').isVisible(),false);assert.match(await wh.locator('#compact-save-status').innerText(),/已保存/);
  await accountant.locator('[data-sheet-action=save]').click();await accountant.waitForFunction(()=>!busy&&!document.querySelector('#sheet-error').hidden);
  assert.match(await accountant.locator('#sheet-error').innerText(),/输入保留/);assert.equal(await accountant.locator(selector).inputValue(),'10');
  const copies=await accountant.evaluate(()=>({data:JSON.stringify(data),drafts:JSON.stringify([...matrixRows])}));
  await accountant.locator('#sheet-error [data-check-latest]').click();await accountant.locator('.latest-record-check b').waitFor();
  assert.deepEqual(await accountant.evaluate(()=>({data:JSON.stringify(data),drafts:JSON.stringify([...matrixRows])})),copies);
  assert.equal(await accountant.locator(selector).inputValue(),'10');
  await accountant.evaluate(()=>window.scrollTo(0,0));await accountant.screenshot({path:path.join(out,'电脑-版本冲突与只读核对.png'),fullPage:true});results.push('two-user version conflict preserves draft; checking latest records leaves data and baselines untouched');
  // Same-page search preserves drafts even when their rows are hidden.
  await accountant.locator('#sheet-search').fill('不存在的客户');assert.equal(await accountant.locator('#leave-overlay:visible').count(),0);
  assert.equal(await accountant.evaluate(id=>matrixRows.get(id).values.P001,id),'10');assert.match(await accountant.locator('#work-status-bar').innerText(),/未保存修改仍保留/);
  await accountant.locator('[data-clear-editor-search]').click();assert.equal(await accountant.locator(selector).inputValue(),'10');
  await accountant.evaluate(()=>goto('dashboard'));await accountant.locator('#leave-overlay').waitFor({state:'visible'});await accountant.locator('[data-leave-choice=stay]').click();assert.equal(await accountant.locator(selector).inputValue(),'10');
  results.push('search does not prompt or discard hidden drafts; actual navigation still protects unsaved edits');
  // Commit on the server, drop only the response: UI must not claim failure or resend.
  let posts=0;await wh.route('**/api/batch',async route=>{posts++;await route.fetch();await route.abort('failed');});
  await wh.locator(selector).fill('11');await wh.locator('[data-sheet-action=save]').click();await wh.waitForFunction(()=>!busy&&!document.querySelector('#sheet-error').hidden);
  assert.match(await wh.locator('#sheet-error').innerText(),/无法确认是否已保存/);assert.equal(posts,1);
  assert.equal(await wh.evaluate(()=>typeof maybeAutosave),'undefined');assert.equal(posts,1);
  const whCopies=await wh.evaluate(()=>({data:JSON.stringify(data),drafts:JSON.stringify([...matrixRows])}));
  await wh.locator('#sheet-error [data-check-latest]').click();await wh.locator('.latest-record-check b').waitFor();
  assert.deepEqual(await wh.evaluate(()=>({data:JSON.stringify(data),drafts:JSON.stringify([...matrixRows])})),whCopies);assert.equal(posts,1);
  const saved=await wh.evaluate(async id=>(await api('/api/bootstrap',undefined,{snapshot:true})).orders.find(o=>o.id===id).lines.find(l=>l.product_id==='P001').ordered_qty,id);assert.equal(saved,'11');await wh.unroute('**/api/batch');
  results.push('write response lost after commit: persistent unknown-outcome feedback, one explicit POST, read-only verification');
  // A confirmed write followed by a failed refresh must not be reported as a failed write.
  await go(admin,'suppliers');await admin.evaluate(()=>openPurchaseForm('supplier'));
  await admin.locator('#purchase-form [name=name]').fill('界面验收供应商');
  await admin.route('**/api/bootstrap',route=>route.abort('failed'));
  await admin.locator('#dialog [data-purchase-act=save]').click();await admin.locator('#dialog-error').waitFor({state:'visible'});
  assert.match(await admin.locator('#dialog-error').innerText(),/操作已完成/);assert.equal(await admin.locator('#purchase-form [name=name]').inputValue(),'界面验收供应商');
  await admin.unroute('**/api/bootstrap');await admin.locator('#dialog-error [data-check-latest]').click();await admin.locator('.latest-record-check b').waitFor();
  const suppliers=await admin.evaluate(async()=> (await api('/api/bootstrap',undefined,{snapshot:true})).purchasing.suppliers.filter(s=>s.name==='界面验收供应商'));assert.equal(suppliers.length,1);
  await admin.evaluate(()=>{busy=false;closeDialog();clearWorkingCopies();});results.push('successful write plus refresh failure explicitly reports committed operation without duplicating supplier');
  // Read failures have an explicit GET-only retry.
  await admin.route('**/api/factory/report?*',route=>route.abort('failed'));await go(admin,'payroll');await admin.locator('[data-read-retry]').waitFor();assert.match(await admin.locator('.read-state').innerText(),/工资读取失败/);
  await admin.unroute('**/api/factory/report?*');await admin.locator('[data-read-retry]').click();await admin.waitForFunction(()=>!!document.querySelector('[data-wage-open]'));results.push('report read failure has a working read retry');
  // Full handoff uses the existing actions and real role sessions.
  await wh.evaluate(()=>clearWorkingCopies());await go(wh,'allocation');
  for(const input of await wh.locator('[data-stock][data-field=existing_qty]').all())await input.fill(['P001','P004'].includes(await input.getAttribute('data-stock'))?'40':'0');
  await wh.locator('[data-warehouse-act=save]').click();await wh.waitForFunction(()=>!busy&&!warehouseDirty(sheetDate()));
  await wh.locator('[data-warehouse-tab=allocation]').click();await wh.waitForFunction(()=>warehouseTab==='allocation'&&!navigationLoading);
  await wh.locator('[data-warehouse-act=confirm]').click();await wh.locator('[name=evidence_checked]').check();await wh.locator('[data-warehouse-act=commit-dispatch]').click();await wh.locator('#overlay').waitFor({state:'hidden'});
  await go(wh,'weighing');await wh.locator('[data-client-sheet=C001] [data-customer-toggle]').click();await wh.locator(`[data-oid="${id}"][data-pid="P001"][data-simple-weight=driver]`).fill('180');
  await wh.locator('[data-weight-evidence=C001]').check();await wh.locator('[data-sheet-action=confirm-weight-client][data-cid=C001]').click();await wh.waitForFunction(id=>!busy&&!!data.orders.find(o=>o.id===id).weight_confirmation,id);
  await accountant.evaluate(()=>clearWorkingCopies());await go(accountant,'settlements');await accountant.locator('[data-settlement-stage=pending]').click();await accountant.waitForFunction(()=>sheetStatus==='pending'&&!navigationLoading);
  await accountant.locator('[data-client-sheet=C001] [data-customer-toggle]').click();await accountant.locator('[data-sheet-action=settle-client][data-cid=C001]').click();await accountant.waitForFunction(id=>!busy&&data.orders.find(o=>o.id===id).state==='ready',id);
  const cashier=sessions.cashier;await go(cashier,'settlements');await cashier.locator('[data-settlement-stage=ready]').click();await cashier.waitForFunction(()=>sheetStatus==='ready'&&!navigationLoading);
  await cashier.locator('[data-client-sheet=C001] [data-customer-toggle]').click();await cashier.locator('[data-sheet-action=review-client][data-cid=C001]').click();await cashier.locator('#review-client-form [name=evidence_checked]').check();await cashier.locator('[data-act=save-review-batch]').click();await cashier.locator('#overlay').waitFor({state:'hidden'});
  await go(cashier,'ledger');await cashier.evaluate(id=>receipt(id),id);assert.match(await cashier.locator('#receipt-form').innerText(),/不支持收款冲销/);assert.equal(await cashier.locator('[data-act=save-receipt]').innerText(),'登记收款');
  await cashier.locator('#receipt-form [name=amount]').fill('5.00');await cashier.locator('[data-act=save-receipt]').click();await cashier.locator('#overlay').waitFor({state:'hidden'});
  assert.equal(await cashier.evaluate(id=>data.orders.find(o=>o.id===id).paid_cents,id),500);
  results.push('warehouse confirms dispatch and weight; accountant settles; cashier reviews and registers actual receipt under unchanged workflow rules');
  // Cover every role and representative desktop/tablet/mobile widths without overflow.
  for(const [name,p] of Object.entries(sessions)){
   if(['warehouse','accountant'].includes(name))await p.evaluate(()=>{clearWorkingCopies();});
   await go(p,'dashboard');
   for(const width of [1440,768,390,320]){await p.setViewportSize({width,height:900});await p.waitForTimeout(80);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${name} home overflow at ${width}`);}
  }
  await wh.setViewportSize({width:1440,height:1000});await go(wh,'weighing');await wh.evaluate(()=>window.scrollTo(0,0));await wh.screenshot({path:path.join(out,'电脑-称重与保存交接.png'),fullPage:true});
  await wh.setViewportSize({width:390,height:844});await wh.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<=1);await wh.evaluate(()=>window.scrollTo(0,0));await wh.screenshot({path:path.join(out,'手机-称重与保存交接.png'),fullPage:false});
  const director=sessions.director;await director.setViewportSize({width:390,height:844});await go(director,'factory');await director.evaluate(()=>factoryOpenForm('beans'));await director.locator('#factory-form').waitFor();
  const boxes=await director.evaluate(()=>{const a=document.querySelector('#dialog .dialog-actions').getBoundingClientRect(),d=document.querySelector('#dialog').getBoundingClientRect();return {bottom:a.bottom,top:a.top,dialog:d.bottom,height:innerHeight};});assert(boxes.bottom<=boxes.height+1&&boxes.top>=0);await director.screenshot({path:path.join(out,'手机-上豆登记表单-v0.44.0.png')});
  await director.emulateMedia({reducedMotion:'reduce'});assert.equal(await director.locator('#dialog-close').evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
  await admin.setViewportSize({width:390,height:844});await go(admin,'users');await admin.evaluate(()=>editManagedUser('',false));await admin.locator('#managed-user-form [name=username]').fill('uxnewuser');await admin.locator('#managed-user-form [name=display_name]').fill('验收用户');await admin.locator('#managed-user-form [name=password]').fill('UX-Initial-2026!');await admin.locator('[data-user-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});assert.match(await admin.locator('#toast').innerText(),/用户已新增/);
  await admin.evaluate(()=>openDialog('删除档案','<p>将档案移出日常选择列表，历史记录保留。</p>','业务操作','<button class="button" data-act="close">取消</button><button class="button danger">删除档案</button>'));
  assert(await admin.locator('#dialog').evaluate(el=>el.getBoundingClientRect().height<innerHeight*.7));await admin.locator('#dialog-close').click();
  results.push('all eight role homepages at 1440/768/390/320; mobile dialog actions visible; reduced motion; new-user feedback');
  await admin.evaluate(async()=>{await api('/api/factory/employee',{request_key:erpRequestKey(),name:'界面验收员工',group_id:'G-TOFU',active:true});await refresh();});
  await go(admin,'attendance');await admin.evaluate(()=>{attendanceView='month';render();});await admin.locator('[data-attendance-detail]').first().waitFor();await admin.locator('[data-attendance-detail]').first().click();assert.match(await admin.locator('.attendance-cell-note').innerText(),/界面验收员工/);
  const owner=sessions.owner;await owner.setViewportSize({width:390,height:844});await owner.locator('#owner-trend-start').waitFor();await owner.locator('#owner-trend-start').fill('2026-10-25');await owner.locator('#owner-trend-start').press('Tab');await owner.locator('#owner-trend-end').fill('2026-10-20');await owner.locator('#owner-trend-end').press('Tab');await owner.locator('#owner-range-error').waitFor({state:'visible'});assert.match(await owner.locator('#owner-range-error').innerText(),/开始日期晚于结束日期/);
  results.push('touch-accessible monthly attendance details and persistent owner date-range errors');
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'validation.json'),JSON.stringify({ok:true,results,pageErrors:errors},null,2));console.log(JSON.stringify({ok:true,results},null,2));
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
