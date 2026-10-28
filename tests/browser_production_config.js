'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-directory-')),db=path.join(temp,'navigation-test-allocation.db'),out=process.env.ERP_BROWSER_OUTPUT?path.resolve(process.env.ERP_BROWSER_OUTPUT):path.join(root,'docs/ux-v0.42.1/production-flow');fs.mkdirSync(out,{recursive:true});
 cp.execFileSync('python3',['-c',`import server,auth,time,sys,uuid,resources_costs as rc
from pathlib import Path
server.DB=Path(sys.argv[1]);server.init_db(demo=True)
with server.connect(True) as c:
 a=auth.create_initial_admin(c,'admin','归集验收管理员','Allocation-Test-2026!',int(time.time()))
 for name,role in [('accountant','会计'),('director','厂长')]:
  u=auth.create_user(c,a,{'username':name,'display_name':'验收'+role,'role':role,'password':'Allocation-Initial-2026!'},int(time.time()))
  auth.change_password(c,u,'Allocation-Initial-2026!','Allocation-Test-2026!',int(time.time()))
 for wid,qty,amount in [('WH-TOFU','100','400'),('WH-SKIN','200','1000')]:
  for kind in ['receipt','consume']:
   rc.Operations(c,server.now,server.audit).material({'business_date':'2026-10-20','material_id':'RM-SOY','kind':kind,'warehouse_id':wid,'qty':qty,'amount':amount if kind=='receipt' else '0','revision':rc.revision(c),'handler':'验收','note':'分摊验收','request_key':str(uuid.uuid4())},'管理员')
 for kind in ['receipt','consume']:
  rc.Operations(c,server.now,server.audit).material({'business_date':'2026-10-20','material_id':'A-SALT','kind':kind,'warehouse_id':'WH-COMMON','product_id':'P001','qty':'1','amount':'10' if kind=='receipt' else '0','revision':rc.revision(c),'handler':'验收','note':'辅料归集验收','request_key':str(uuid.uuid4())},'管理员')
`,db],{cwd:root});
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});}),base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});let browser;const errors=[],checks=[];
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===99)throw Error('service not started');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const login=async name=>{const c=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),p=await c.newPage();p.setDefaultTimeout(10000);p.on('pageerror',e=>errors.push(e.message));await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill('Allocation-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user&&!document.querySelector('.shell').hidden);return p;};
  const go=async(p,target)=>{await p.evaluate(target=>goto(target),target);await p.waitForFunction(target=>page===target&&!navigationLoading,target);};
  const admin=await login('admin');await go(admin,'system-settings');await admin.locator('[data-production-config-open]').click();
  const config=admin.locator('#production-config-form');await config.waitFor({state:'visible'});
  await admin.locator('[data-config-add=systems]').click();const newSystem=admin.locator('[data-config-kind=systems]').last(),systemId=await newSystem.getAttribute('data-config-id');
  await newSystem.locator('[data-config-field=name]').fill('第三磨浆系统');
  await newSystem.locator('[data-config-list=warehouse_ids][value=WH-MAIN]').check();
  await admin.locator('[data-config-tab=processes]').click();await admin.locator('[data-config-add=processes]').click();const newProcess=admin.locator('[data-config-kind=processes]').last(),processId=await newProcess.getAttribute('data-config-id');
  await newProcess.locator('[data-config-field=name]').fill('压力浆缸');await newProcess.locator('[data-config-field=dry_kg]').fill('25');await newProcess.locator('[data-config-field=output_qty]').fill('5');
  await admin.locator('[data-config-tab=products]').click();const relation=admin.locator('[data-config-kind=products][data-config-id=P001]');await relation.locator('summary').click();await relation.locator(`[data-config-list=system_ids][value="${systemId}"]`).check();await relation.locator(`[data-config-list=process_ids][value="${processId}"]`).check();
  const future=await config.locator('[name=effective_date]').inputValue();await config.locator('[name=note]').fill('模块化验收：新增第三系统，共用两个库房及新工艺');
  for(const width of [1440,768,390,320]){await admin.setViewportSize({width,height:1000});assert(await admin.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  await admin.screenshot({path:path.join(out,'生产配置-手机.png')});await admin.setViewportSize({width:1440,height:1000});await admin.locator('[data-config-publish]').click();await admin.locator('#overlay').waitFor({state:'hidden'});
  await admin.waitForFunction(()=>resourceData().production_configs.length===2);assert.equal(await admin.evaluate(()=>resourceData().production_configs.length),2);checks.push('administrator publishes third system and custom vat via structured fields, without changing source code');
  await admin.evaluate(async({future})=>{const before=resourceData().revision;await api('/api/resources/material',{material_id:'RM-SOY',warehouse_id:'WH-TOFU',kind:'receipt',qty:'1000',amount:'4000',business_date:future,handler:'验收',note:'测试入库',revision:before,request_key:erpRequestKey()});await refresh();}, {future});
  const director=await login('director');await director.evaluate(day=>factoryDay=day,future);await go(director,'factory');await director.evaluate(()=>factoryWorkTab='beans');await director.evaluate(()=>render());assert.equal(await director.locator('[data-grinding-system]').count(),3);
  await director.locator('[data-factory-act=beans]').click();const beans=director.locator('#factory-form');await beans.locator(`[data-bean-system="${systemId}"]`).fill('100');await beans.locator('[name=note]').fill('第三系统累计领豆验收');await director.locator('[data-factory-save]').click();await director.locator('#overlay').waitFor({state:'hidden'});
  await director.waitForFunction(id=>resourceData().entries.some(e=>e.production_system_id===id),systemId);const issue=await director.evaluate(id=>resourceData().entries.find(e=>e.production_system_id===id),systemId);assert.equal(issue.qty,'100');assert.equal(issue.warehouse_id,'WH-TOFU');checks.push('director sees three systems and cumulative correction posts explicit source against shared warehouse');
  await director.evaluate(()=>factoryWorkTab='daily');await director.evaluate(()=>render());await director.locator('.page-head [data-factory-act=daily]').click();
  const f=director.locator('#factory-form');assert.equal(await f.locator('[data-production-system]').count(),3);await f.locator('[data-production-system=tofu] [data-system-state]').selectOption('stopped');await f.locator('[data-production-system=skin] [data-system-state]').selectOption('stopped');await f.locator(`[data-production-system="${systemId}"] [data-system-soak]`).fill('0.2');
  await f.locator('.daily-special-supply summary').click();await f.locator(`[data-daily-product=P001]:has([data-daily-field=system][value="${systemId}"]) [data-daily-tank="${processId}"]`).fill('4');
  for(const width of [1440,390,320]){await director.setViewportSize({width,height:1000});assert(await director.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  await director.screenshot({path:path.join(out,'第三系统用浆-手机.png')});await director.locator('[data-factory-save]').click();await director.locator('#overlay').waitFor({state:'hidden'});
  await director.waitForFunction(day=>factoryData().daily.some(r=>r.business_date===day),future);const saved=await director.evaluate(day=>factoryData().daily.find(r=>r.business_date===day),future);assert.equal(saved.config_snapshot.version,1);assert.equal(saved.products.find(r=>r.system===systemId).tanks[processId],'4');checks.push('custom process saved with third source; stopped systems recorded explicitly; configuration snapshot retained');
  await go(director,'system-settings');await director.waitForFunction(()=>!!factoryReports.get('system-settings|'+today()+'|'+today())?.value);
  const key='systems.'+systemId+'.soak_kg';await director.locator(`[data-parameter-request="${key}"]`).click();await director.locator('#parameter-request-form [name=value]').fill('480');await director.locator('#parameter-request-form [name=reason]').fill('独立系统换算核定');await director.locator('[data-parameter-submit]').click();await director.locator('#overlay').waitFor({state:'hidden'});
  const accountant=await login('accountant');await accountant.evaluate(month=>resourcesMonth=month,future.slice(0,7));await go(accountant,'production');await accountant.waitForFunction(()=>[...factoryReports.values()].some(r=>r.value?.allocations));const allocated=await accountant.evaluate(()=>[...factoryReports.values()].find(r=>r.value?.allocations).value);assert.equal(allocated.total_cents,180000);assert.equal(allocated.allocations.find(a=>a.system===systemId).allocated_kg,'100');checks.push('accounting report dynamically includes third pool and reconciles actual stock cost; source-specific parameter request is pending approval');
  const r=await admin.evaluate(async()=>api('/api/factory/report?kind=system-settings'));const request=r.requests.find(q=>q.key===key&&q.status==='pending');assert(request);await admin.evaluate(async request=>api('/api/factory/parameter-review',{id:request.id,version:request.version,decision:'approve',reason:'核定通过'}),request);
  await director.evaluate(()=>refresh());assert.equal(await director.evaluate(day=>productionSystems(day).length,future),3);assert.equal(await director.evaluate(day=>factoryData().daily.find(r=>r.business_date===day).config_snapshot.version,future),1);checks.push('administrator approval schedules a new conversion revision without altering previously saved production');
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'validation.json'),JSON.stringify({ok:true,checks,errors},null,2));console.log(JSON.stringify({ok:true,checks}));
 }finally{if(browser)await browser.close();service.kill('SIGTERM');if(service.exitCode===null&&service.signalCode===null)await new Promise(r=>service.once('exit',r));fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
