const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-factory-')),db=path.join(temp,'navigation-test-factory.db');
 cp.execFileSync('python3',[path.join(root,'tests/seed_allocation.py'),db]);
 cp.execFileSync('python3',['-c',`import server,auth,time,sys,uuid,resources_costs as rc,purchasing as purchasing\nfrom pathlib import Path\nserver.DB=Path(sys.argv[1]);server.init_db()\nwith server.connect(True) as c:\n admin=auth.create_initial_admin(c,'admin','测试管理员','Factory-Test-Admin-2026!',int(time.time()))\n director=auth.create_user(c,admin,{'username':'director','display_name':'测试厂长','role':'厂长','password':'Factory-Temporary-2026!'},int(time.time()))\n auth.change_password(c,director,'Factory-Temporary-2026!','Factory-Director-2026!',int(time.time()))\n ops=purchasing.Operations(c,server.now,server.audit)\n supplier=ops.supplier({'name':'测试黄豆供应商','payment_days':0},'管理员')\n po=ops.order({'supplier_id':supplier['id'],'business_date':'2026-10-20','expected_date':'2026-10-20','handler':'测试','request_key':str(uuid.uuid4()),'lines':[{'material_id':'RM-SOY','warehouse_id':'WH-MAIN','qty':'10','price':'4'}]},'管理员')\n ops.confirm({'id':po['id'],'version':po['version']},'管理员')\n rc.Operations(c,server.now,server.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':'RM-SOY','business_date':'2026-10-20','kind':'receipt','qty':'1000','amount':'4000','warehouse_id':'WH-TOFU','note':'测试到货','handler':'测试','quality':{'protein_pct':'42','soluble_protein_pct':'8','moisture_pct':'12','batch_no':'TEST-BATCH'}},'管理员')`,db],{cwd:root});
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});}),base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const errors=[];
  const login=async(name,password)=>{const c=await browser.newContext({viewport:{width:390,height:844}}),p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill(password);await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>!!data?.auth_user);return p;};
  const director=await login('director','Factory-Director-2026!');assert.equal(await director.evaluate(()=>page),'dashboard');await director.evaluate(()=>goto('factory'));await director.waitForFunction(()=>page==='factory'&&!navigationLoading);
  const go=async(p,name)=>{await p.evaluate(name=>goto(name),name);await p.waitForFunction(n=>page===n&&!navigationLoading,name,{timeout:10000});};
  const save=async(p)=>{await p.locator('[data-factory-save]').click();await p.locator('#overlay').waitFor({state:'hidden'});};
  const date=async p=>{await p.locator('#factory-date').fill('2026-10-20');await p.locator('#factory-date').press('Tab');};



 const emp=await director.evaluate(async()=>{const e=await api('/api/factory/employee',{request_key:erpRequestKey(),name:'手机排班测试员工',group_id:'G-TOFU',active:true});await refresh();return e;});
 await go(director,'attendance');assert.equal(await director.evaluate(()=>attendanceView),'schedule');await date(director);
 const planButton=director.locator('.attendance-page-actions [data-factory-act=schedule]');await planButton.waitFor();assert((await planButton.boundingBox()).height>=36);assert(await director.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await director.screenshot({path:path.join(root,'docs/分组排班-手机-v0.36.png'),fullPage:true});await planButton.click();await director.locator('#factory-form[data-kind=schedule]').waitFor();
 await director.locator('#attendance-default-start').fill('21:00');await director.locator('[data-attendance-fill-start]').click();
 const row=director.locator('[data-attendance-person="'+emp.id+'"]');await row.locator('[data-attendance-field=group_id]').selectOption('G-SKIN');await row.locator('[data-attendance-field=note]').fill('临时调到豆皮组');
 assert(await row.locator('[data-attendance-field=group_id]').isVisible());assert((await row.locator('[data-attendance-field=group_id]').boundingBox()).height>=34);
 assert(await director.locator('#dialog-body').evaluate(el=>el.scrollWidth<=el.clientWidth+1));assert.equal(await director.locator('.attendance-editor-table tbody tr').first().evaluate(el=>getComputedStyle(el).display),'table-row');await director.screenshot({path:path.join(root,'docs/编辑排班-手机-v0.36.png'),fullPage:true});
 await director.locator('[data-factory-confirm]').click();await director.locator('#factory-notice-text').waitFor();assert((await director.locator('#factory-notice-text').inputValue()).includes('手机排班测试员工'));assert((await director.locator('#factory-notice-text').inputValue()).includes('21:00'));await director.locator('#dialog-close').click();
 assert.equal(await director.evaluate(()=>factoryData().attendance.length),0);assert.equal(await director.evaluate(()=>daySchedule().state),'confirmed');
 await director.locator('[data-attendance-view=day]').click();await director.locator('.attendance-page-actions [data-factory-act=attendance]').click();await director.locator('#factory-form[data-kind=attendance]').waitFor();
 assert.equal(await director.locator('[data-attendance-field=group_id]').count(),0);assert((await director.locator('[data-attendance-person="'+emp.id+'"] td[data-label="当天作业组"]').innerText()).includes('豆皮组'));
 await director.locator('[data-attendance-person="'+emp.id+'"] [data-attendance-field=status]').selectOption('half');await director.locator('[data-attendance-person="'+emp.id+'"] [data-attendance-field=note]').fill('实际只上半天班');
 await director.locator('[data-factory-confirm]').click();await director.locator('#overlay').waitFor({state:'hidden'});assert.equal(await director.evaluate(()=>dayAttendance().entries[0].status),'half');assert.equal(await director.evaluate(()=>daySchedule().entries[0].status),'full');
 assert((await director.locator('#content').innerText()).includes('半天'));await director.screenshot({path:path.join(root,'docs/考勤登记-手机-v0.36.png'),fullPage:true});
 // Change the plan later: actual attendance remains a separate snapshot.
 await director.locator('[data-attendance-view=schedule]').click();await director.locator('.attendance-page-actions [data-factory-act=schedule]').click();await director.locator('[data-attendance-person="'+emp.id+'"] [data-attendance-field=group_id]').selectOption('G-DRY');await director.locator('[data-factory-confirm]').click();await director.locator('#factory-notice-text').waitFor();await director.locator('#dialog-close').click();
 assert.equal(await director.evaluate(()=>dayAttendance().entries[0].group_id),'G-SKIN');assert.equal(await director.evaluate(()=>dayAttendance().entries[0].status),'half');assert.equal(await director.evaluate(()=>daySchedule().entries[0].group_id),'G-DRY');
 // Date navigation and yesterday's grouping copy preserve the new day's actual attendance as empty.
 await director.locator('#factory-date').fill('2026-10-21');await director.locator('#factory-date').press('Tab');await director.locator('[data-factory-act=copy-attendance]').click();await director.locator('#factory-form[data-kind=schedule]').waitFor();assert.equal(await director.locator('[data-attendance-person="'+emp.id+'"] [data-attendance-field=group_id]').inputValue(),'G-DRY');await director.locator('[data-factory-save]').click();await director.locator('#overlay').waitFor({state:'hidden'});
 assert.equal(await director.evaluate(()=>daySchedule().state),'draft');assert.equal(await director.evaluate(()=>dayAttendance()),undefined);
 assert.deepEqual(errors,[]);console.log('手机排班紧凑入口、表格编辑、调组和通知、独立确认考勤、排班不计薪、历史考勤不被覆盖、沿用昨天分组通过');
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
