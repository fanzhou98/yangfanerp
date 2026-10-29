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
  const login=async(name,password)=>{const c=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true}),p=await c.newPage();p.on('pageerror',e=>errors.push(e.stack||e.message));await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill(password);await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>!!data?.auth_user);return p;};
  const director=await login('director','Factory-Director-2026!');assert.equal(await director.evaluate(()=>page),'dashboard');await director.evaluate(()=>goto('factory'));await director.waitForFunction(()=>page==='factory'&&!navigationLoading);
  const go=async(p,name)=>{await p.evaluate(name=>goto(name),name);await p.waitForFunction(n=>page===n&&!navigationLoading,name,{timeout:10000});};
  const save=async(p)=>{await p.locator('[data-factory-save]').click();await p.locator('#overlay').waitFor({state:'hidden'});};
  const date=async p=>{await p.locator('#factory-date').fill('2026-10-20');await p.locator('#factory-date').press('Tab');};



 await date(director);await director.locator('[data-factory-act=daily]').first().click();await director.locator('#factory-form[data-kind=daily]').waitFor();
 assert.equal(await director.locator('[data-daily-field=skin_tanks]').count(),0);assert.equal(await director.locator('.factory-slurry-form thead th').count(),3);assert(!(await director.locator('.factory-slurry-form').innerText()).includes('豆皮'));assert(!(await director.locator('.factory-slurry-form').innerText()).includes('熏干'));assert.equal(await director.evaluate(()=>data.products.find(p=>p.name==='熏干').main_material),'白干');
 await director.locator('[data-production-system=tofu] [data-system-soak]').fill('0.6');await director.locator('[data-production-system=skin] [data-system-soak]').fill('1');
 const input=director.locator('[data-daily-field=large_tanks]').first();await input.scrollIntoViewIfNeeded();
 assert(await director.locator('.production-slurry-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth+1));assert(await director.locator('#dialog-body').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
 // Start a real touch swipe over a number input without clicking/focusing it first.
 await director.evaluate(()=>document.activeElement.blur());const cdp=await director.context().newCDPSession(director);const rect=await input.boundingBox(),before=await director.locator('.dialog-content').evaluate(el=>el.scrollTop);
 await cdp.send('Input.synthesizeScrollGesture',{x:Math.round(rect.x+rect.width/2),y:Math.round(rect.y+rect.height/2),yDistance:-100,gestureSourceType:'touch',speed:350});
 await director.waitForTimeout(200);const after=await director.locator('.dialog-content').evaluate(el=>el.scrollTop);assert(after>before,'首次滑动应直接滚动，不能依赖点击输入框');
 await input.fill('10');await director.locator('[data-daily-field=small_tanks]').first().fill('0');await director.screenshot({path:path.join(root,'docs/生产登记-手机-v0.36.1.png'),fullPage:true});await save(director);
 assert.equal(await director.evaluate(()=>dayProduction().systems.skin.soak_tanks),'1');assert.equal(await director.evaluate(()=>dayProduction().products[0].skin_tanks),'0');
 await director.locator('[data-factory-act=daily]').first().click();assert.equal(await director.locator('[data-daily-field=large_tanks]').first().inputValue(),'10');await director.locator('#dialog-close').click();
 await go(director,'factory-settings');assert(!(await director.locator('#content').innerText()).includes('豆皮浆缸'));await director.locator('[data-factory-act=settings]').click();assert.equal(await director.locator('[name=skin_slurry_kg]').count(),0);await director.locator('#dialog-close').click();
 // A narrow phone also shows both count columns without horizontal scrolling.
 await director.setViewportSize({width:320,height:740});await go(director,'factory');await director.locator('[data-factory-act=daily]').first().click();assert(await director.locator('.production-slurry-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth+1));await director.locator('#dialog-close').click();
 // Desktop retains the same compact three-column table.
 await director.setViewportSize({width:1440,height:1000});await go(director,'factory');await director.locator('[data-factory-act=daily]').first().click();assert.equal(await director.locator('.factory-slurry-form thead th').count(),3);
 assert.deepEqual(errors,[]);console.log('生产登记删除豆皮浆缸、手机三列表格、输入框上首次触摸直接滑动、数值保存恢复及生产参数页面通过');
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
