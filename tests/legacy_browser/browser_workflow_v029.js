const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-v029-')),db=path.join(temp,'navigation-test-v029.db');
 cp.execFileSync('python3',[path.join(root,'tests/seed_allocation.py'),db]);
 cp.execFileSync('python3',['-c',`import server,auth,time,sys\nfrom pathlib import Path\nserver.DB=Path(sys.argv[1])\nwith server.connect(True) as c:auth.create_initial_admin(c,'admin','测试管理员','Test-Only-Password-2026!',int(time.time()))`,db],{cwd:root});
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});});
 const base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const login=async()=>{await page.locator('#auth-login-form [name=username]').fill('admin');await page.locator('#auth-login-form [name=password]').fill('Test-Only-Password-2026!');await page.locator('#auth-login-form [type=submit]').click();await page.waitForFunction(()=>!!data?.auth_user);};
  await page.goto(base);await login();await page.locator('#nav [data-page=orders]').click();await page.waitForFunction(()=>page==='orders'&&!navigationLoading);
  assert.equal(await page.locator('.head-menu > summary').innerText(),'打印');assert.equal(await page.locator('.head-menu-list [data-print-orders]').count(),2);assert.equal(await page.locator('.page-head [data-sheet-action=save]').innerText(),'保存订货');
  const next=page.locator('.sheet-table-caption .workflow-next');assert.equal(await next.innerText(),'库存分配 ↗');assert.equal(await page.locator('.sheet-table-caption [data-sheet-action=save]').count(),0);
  await page.locator('.order-matrix input').first().fill('9');await next.click();await page.locator('#leave-overlay').waitFor({state:'visible'});await page.locator('[data-leave-choice=stay]').click();assert.equal(await page.evaluate(()=>page),'orders');
  await page.screenshot({path:path.join(root,'docs/v0.29订货流程按钮.png'),fullPage:true});
  await next.click();await page.locator('[data-leave-choice=discard]').click();await page.waitForFunction(()=>page==='allocation'&&!navigationLoading);
  await page.locator('[data-warehouse-tab=allocation]').click();await page.waitForFunction(()=>warehouseTab==='allocation'&&!navigationLoading);
  await page.getByRole('button',{name:'下一步：车辆排班 ↗',exact:true}).click();await page.waitForFunction(()=>page==='dispatch'&&!navigationLoading);
  await page.getByRole('button',{name:'下一步：装货与配送明细 ↗',exact:true}).click();await page.waitForFunction(()=>dispatchTab==='loads'&&!navigationLoading);assert(await page.locator('[data-print-orders=trip]').count());
  await page.locator('#nav [data-page=orders]').click();await page.waitForFunction(()=>page==='orders'&&!navigationLoading);
  await page.locator('.order-matrix input').first().fill('9');
  const sid=await page.evaluate(()=>authSession.session_id);await page.evaluate(()=>{authLastHeartbeat=0;});await page.locator('.order-matrix input').first().press('ArrowRight');await page.waitForFunction(()=>!authActivitySending);
  const second=await context.newPage();await second.goto(base);await second.waitForFunction(()=>!!data?.auth_user);
  // Inactivity must block a pending save, hide business data, and notify other tabs.
  await page.evaluate(()=>{localStorage.setItem(authActivityKey(),String(authNow()-1801));});
  await page.waitForFunction(()=>!authUser&&!authSession);await second.waitForFunction(()=>!authUser&&!authSession);
  assert.equal(await page.locator('#content').innerText(),'');assert(await page.locator('#auth-login-form').isVisible());
  // Real server timeout remains enforced even without the page timer.
  cp.execFileSync('python3',['-c',`import sqlite3,sys,time\nc=sqlite3.connect(sys.argv[1]);c.execute('UPDATE auth_session_activity SET last_activity=? WHERE session_id=?',(int(time.time())-1801,sys.argv[2]));c.commit()`,db,sid]);
  assert.equal(await page.evaluate(async()=> (await fetch('/api/bootstrap')).status),401);
  await second.close();await login();
  // Produce 30 customers and 14 columns including products with zero actual quantity.
  const html=cp.execFileSync('python3',['-c',`import printing,json\nproducts=[{'id':str(i),'name':'产品'+str(i+1),'unit':'筐'} for i in range(14)]\ncustomers=[{'id':'C'+str(i),'name':'打印验证客户'+str(i+1),'route':'新联市场'} for i in range(30)]\norders=[{'id':'O'+c['id'],'version':1,'business_date':'2026-10-22','customer_id':c['id'],'customer_name':c['name'],'lines':[{'product_id':'0','ordered_qty':'2','actual_qty':'2'}]} for c in customers]\nprint(printing.order_print_html({'products':products,'customers':customers,'orders':orders},{'date':['2026-10-22'],'mode':['total']},'2026-10-20T12:00:00'))`],{cwd:root,encoding:'utf8'});
  const print=await context.newPage();await print.goto(base);await print.setContent(html);assert.equal(await print.locator('#print-button').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(166, 75, 18)');await print.emulateMedia({media:'print'});
  assert.equal(await print.locator('.print-page').count(),4);
  const layout=await print.locator('.print-page').evaluateAll(es=>es.map(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,overflow:e.scrollWidth-e.clientWidth,remark:e.querySelector('tbody td.handwritten').getBoundingClientRect().width,row:e.querySelector('tbody tr').getBoundingClientRect().height})));
  assert(layout.every(r=>r.overflow<2&&r.height<748&&r.remark>130&&r.row>20),JSON.stringify(layout));
  for(let i=1;i<=14;i++)assert((await print.locator('thead').allInnerTexts()).join(' ').includes('产品'+i));
  await print.screenshot({path:path.join(root,'docs/v0.29配送单打印.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({nextButtonPosition:true,distinctColor:true,allPrintButtonsSameOrange:true,unsavedGuard:true,allocationToVehicleSchedule:true,scheduleToLoads:true,idleLogout:true,multipleTabs:true,serverTimeout:true,all14Products:true,printPages:4,layout,browserErrors:errors}));
 }finally{if(browser)await browser.close();service.kill('SIGTERM');if(service.exitCode===null&&service.signalCode===null)await new Promise(r=>service.once('exit',r));fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1);});
