'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');

(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-prelaunch-production-'));
 const db=path.join(temp,'test.db'),out=path.join(root,'docs/prelaunch-2026-10-23/browser-production');fs.mkdirSync(out,{recursive:true});
 cp.execFileSync('python3',['-c',`import server,auth,time,sys
from pathlib import Path
server.DB=Path(sys.argv[1]);server.init_db(demo=True)
with server.connect(True) as c:
 admin=auth.create_initial_admin(c,'admin','上线验收管理员','Production-Test-2026!',int(time.time()))
 user=auth.create_user(c,admin,{'username':'director','display_name':'上线验收厂长','role':'厂长','password':'Production-Initial-2026!'},int(time.time()))
 auth.change_password(c,user,'Production-Initial-2026!','Production-Test-2026!',int(time.time()))
`,db],{cwd:root});
 const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const port=socket.address().port;socket.close(()=>resolve(port));});});
 const base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
 let browser,currentPage;const errors=[],checks=[],evidence={};
 const writeResult=(ok,error)=>fs.writeFileSync(path.join(out,'validation.json'),JSON.stringify({ok,version:fs.readFileSync(path.join(root,'VERSION'),'utf8').trim(),checks,evidence,errors,...(error?{failure:String(error.stack||error)}:{})},null,2));
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===99)throw Error('Temporary service did not start');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  async function login(name){const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),p=await context.newPage();p.setDefaultTimeout(12000);p.on('pageerror',error=>errors.push(error.message));currentPage=p;await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill('Production-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>!!data?.auth_user&&!document.querySelector('.shell').hidden);assert.equal(await p.evaluate(()=>data.auth_user.username),name);return p;}
  async function go(p,target){await p.evaluate(target=>goto(target),target);await p.waitForFunction(target=>page===target&&!navigationLoading,target);}
  async function postForm(p,endpoint,button,ok=true){const before=await p.evaluate(()=>JSON.stringify(data)),pending=p.waitForResponse(r=>r.url()===base+endpoint&&r.request().method()==='POST');await p.locator(button).click();const response=await pending,payload=await response.json();assert.equal(response.ok(),ok,JSON.stringify(payload));if(ok){await p.locator('#overlay').waitFor({state:'hidden'});await p.waitForFunction(before=>!busy&&JSON.stringify(data)!==before,before);}return payload;}
  async function dayRecord(p,day){return p.evaluate(day=>factoryData().daily.find(r=>r.business_date===day),day);}
  async function openBeans(p){await p.locator('.page-head [data-factory-act=beans]').click();await p.locator('#factory-form[data-kind=beans]').waitFor();}
  async function beanRow(p,index,system,warehouse,qty){let row=p.locator(`[data-bean-row="${index}"]`);await row.locator('[data-bean-system-select]').selectOption(system);row=p.locator(`[data-bean-row="${index}"]`);await row.locator('[data-bean-warehouse-select]').selectOption(warehouse);await row.locator('[data-bean-qty]').fill(qty);}
  async function closeForm(p){await p.locator('#dialog-close').click();if(await p.locator('[data-leave-choice=discard]').isVisible())await p.locator('[data-leave-choice=discard]').click();await p.locator('#overlay').waitFor({state:'hidden'});}

  const admin=await login('admin');await go(admin,'system-settings');await admin.locator('[data-production-config-open]').click();
  const config=admin.locator('#production-config-form');await config.waitFor();await config.locator('[data-config-add=systems]').click();
  const system=config.locator('[data-config-kind=systems]').last(),systemId=await system.getAttribute('data-config-id');
  await system.locator('[data-config-field=name]').fill('上线验收第三磨浆系统');await system.locator('[data-config-field=soak_kg]').fill('500');await system.locator('[data-config-list=warehouse_ids][value=WH-MAIN]').check();
  await config.locator('[data-config-tab=processes]').click();await config.locator('[data-config-add=processes]').click();
  const process=config.locator('[data-config-kind=processes]').last(),processId=await process.getAttribute('data-config-id');
  await process.locator('[data-config-field=name]').fill('上线验收压力浆缸');await process.locator('[data-config-field=dry_kg]').fill('25');await process.locator('[data-config-field=output_qty]').fill('5');
  await config.locator('[data-config-tab=products]').click();const relation=config.locator('[data-config-kind=products][data-config-id=P001]');await relation.locator('summary').click();
  await relation.locator(`[data-config-list=system_ids][value="${systemId}"]`).check();await relation.locator(`[data-config-list=process_ids][value="${processId}"]`).check();
  const day=await config.locator('[name=effective_date]').inputValue();await config.locator('[name=note]').fill('上线前浏览器验收：第三磨浆系统、共用两库及独立浆缸');
  await postForm(admin,'/api/factory/production-config','[data-config-publish]');
  checks.push('管理员通过实际配置表单发布第三系统、共享库房及独立工艺');
  await admin.evaluate(async({day})=>{for(const [warehouse,qty,amount] of [['WH-TOFU','1000','4000'],['WH-MAIN','500','2500']]){await api('/api/resources/material',{material_id:'RM-SOY',warehouse_id:warehouse,kind:'receipt',qty,amount,business_date:day,handler:'上线验收管理员',note:'浏览器验收原料入库',revision:resourceData().revision,request_key:erpRequestKey()});await refresh();}},{day});

  const director=await login('director');await go(director,'factory');await director.locator('#factory-date').fill(day);await director.locator('#factory-date').dispatchEvent('change');
  assert.equal(await director.locator('.factory-beans-panel').count(),1);
  await openBeans(director);assert.equal(await director.locator('[data-bean-soak]').count(),3);
  await beanRow(director,0,systemId,'WH-TOFU','100');await director.locator(`[data-bean-soak="${systemId}"]`).fill('0.25');
  assert.equal(await director.locator('[data-bean-soak=tofu]').inputValue(),'');assert.equal(await director.locator('[data-bean-soak=skin]').inputValue(),'');
  await postForm(director,'/api/factory/beans','[data-factory-save]');
  let record=await dayRecord(director,day);assert.equal(record.config_snapshot.version,1);assert.deepEqual(record.systems.tofu,{state:'pending',soak_tanks:''});assert.deepEqual(record.systems.skin,{state:'pending',soak_tanks:''});assert.deepEqual(record.systems[systemId],{state:'pending',soak_tanks:'0.25'});
  assert.equal(await director.evaluate(id=>issuedBeans()[id],systemId),100);evidence.partial_registration={systems:record.systems,issued_kg:100};
  await director.screenshot({path:path.join(out,'01-部分泡豆与待登记系统-电脑.png'),fullPage:true});checks.push('首次分次上豆只填第三系统泡豆数即可保存，其他系统空值及待确认状态完整保留');

  await director.locator('.page-head [data-factory-act=daily]').click();assert.deepEqual(await director.locator('[data-system-state]').evaluateAll(rows=>rows.map(r=>r.value)),['pending','pending','pending']);
  for(const width of [1440,390,320]){await director.setViewportSize({width,height:1000});assert(await director.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));if(width===390)await director.screenshot({path:path.join(out,'02-浆缸开机状态待确认-手机.png')});}
  await director.setViewportSize({width:1440,height:1000});await postForm(director,'/api/factory/daily','[data-factory-save]');
  record=await dayRecord(director,day);assert.deepEqual(Object.values(record.systems).map(s=>s.state),['pending','pending','pending']);assert.equal(record.systems.tofu.soak_tanks,'');
  checks.push('打开登记浆缸及直接保存均不会把待确认自动改成开机，手机及窄屏无页面横向溢出');

  await openBeans(director);await beanRow(director,0,systemId,'WH-TOFU','25');await director.locator('[data-bean-add]').click();await beanRow(director,1,systemId,'WH-MAIN','50');await director.locator(`[data-bean-soak="${systemId}"]`).fill('0.3');
  await director.screenshot({path:path.join(out,'03-同系统跨库分次登记-电脑.png')});await postForm(director,'/api/factory/beans','[data-factory-save]');
  const entries=await director.evaluate(id=>beanRegistrations().filter(r=>r.production_system_id===id),systemId);assert.equal(entries.length,3);assert.deepEqual(entries.map(e=>e.qty).sort(),['100','25','50']);assert.equal(await director.evaluate(id=>issuedBeans()[id],systemId),175);
  checks.push('再次上豆可一次分别登记两个库房，保留三笔独立流水并汇总175公斤');
  const first=entries.find(e=>e.qty==='100');await director.locator(`[data-bean-registration="${first.id}"] [data-bean-action=void]`).click();await director.locator('#bean-change-form [name=reason]').fill('上线验收删除并恢复记录');await postForm(director,'/api/factory/bean-void','[data-bean-change-confirm=void]');
  assert.equal(await director.evaluate(id=>issuedBeans()[id],systemId),75);await director.locator('[data-bean-toggle-deleted]').click();
  await director.locator(`[data-bean-registration="${first.id}"] [data-bean-action=restore]`).click();await director.locator('#bean-change-form [name=reason]').fill('上线验收确认恢复原登记');await postForm(director,'/api/factory/bean-restore','[data-bean-change-confirm=restore]');
  assert.equal(await director.evaluate(id=>issuedBeans()[id],systemId),175);assert.equal(await director.evaluate(id=>beanRegistrations().find(e=>e.id===id).voided,first.id),false);
  checks.push('上豆明细通过实际删除和恢复按钮正确重算75→175公斤，原流水身份不变');

  await director.locator('.page-head [data-factory-act=daily]').click();
  for(const id of ['tofu','skin'])await director.locator(`[data-production-system="${id}"] [data-system-state]`).selectOption('stopped');
  await director.locator(`[data-production-system="${systemId}"] [data-system-state]`).selectOption('running');
  const special=director.locator('.daily-special-supply');if(!await special.evaluate(el=>el.open))await special.locator('summary').click();
  const row=director.locator(`[data-daily-product=P001]:has([data-daily-field=system][value="${systemId}"])`);await row.locator(`[data-daily-tank="${processId}"]`).fill('7');
  await director.screenshot({path:path.join(out,'04-人工确认开机并登记自定义工艺-电脑.png')});await postForm(director,'/api/factory/daily','[data-factory-save]');
  record=await dayRecord(director,day);assert.equal(record.systems.tofu.state,'stopped');assert.equal(record.systems.skin.state,'stopped');assert.equal(record.systems[systemId].state,'running');assert.equal(record.systems[systemId].soak_tanks,'0.3');assert.equal(record.products.find(r=>r.product_id==='P001'&&r.system===systemId).tanks[processId],'7');
  const daily=await director.evaluate(async day=>api('/api/factory/report?kind=daily&date='+day),day),product=daily.products.find(p=>p.product_id==='P001');assert.equal(product.slurry_bean_kg,'175');assert.equal(product.bean_kg,'175');
  const allocations=await admin.evaluate(async day=>api('/api/factory/report?kind=material-costs&date='+day+'&start='+day+'&end='+day),day);assert.equal(allocations.total_cents,75000);assert.equal(allocations.allocated_cents,75000);assert.equal(allocations.unallocated_cents,0);
  evidence.final={business_date:day,config_version:record.config_snapshot.version,systems:record.systems,slurry_bean_kg:product.slurry_bean_kg,bean_kg:product.bean_kg,total_cents:allocations.total_cents,allocated_cents:allocations.allocated_cents};
  checks.push('人工确认开机后第三系统7缸×25公斤正确计量175公斤，跨库FIFO成本750元完整分摊');

  await openBeans(director);await beanRow(director,0,'tofu','WH-TOFU','1');const rejected=await postForm(director,'/api/factory/beans','[data-factory-save]',false);assert.match(JSON.stringify(rejected),/确认开机状态/);assert.equal(await director.evaluate(()=>issuedBeans().tofu),0);assert.equal(await director.evaluate(id=>issuedBeans()[id],systemId),175);await closeForm(director);
  await director.screenshot({path:path.join(out,'05-三系统最终登记与明细-电脑.png'),fullPage:true});checks.push('已明确未开机的系统通过实际表单拒绝上豆，数量与已保存流水保持不变');
  assert.deepEqual(errors,[]);fs.rmSync(path.join(out,'failure.png'),{force:true});writeResult(true);console.log(JSON.stringify({ok:true,checks,evidence}));
 }catch(error){if(currentPage)await currentPage.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});writeResult(false,error);throw error;}
 finally{if(browser)await browser.close();service.kill('SIGTERM');if(service.exitCode===null&&service.signalCode===null)await new Promise(resolve=>service.once('exit',resolve));fs.rmSync(temp,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exit(1);});
