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
  const login=async(name,password)=>{const c=await browser.newContext({viewport:{width:1512,height:1000}}),p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill(password);await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>!!data?.auth_user);return p;};
  const director=await login('director','Factory-Director-2026!');assert.equal(await director.evaluate(()=>page),'dashboard');await director.evaluate(()=>goto('factory'));await director.waitForFunction(()=>page==='factory'&&!navigationLoading);
  const go=async(p,name)=>{await p.locator(`#nav [data-page="${name}"]`).click();await p.waitForFunction(n=>page===n&&!navigationLoading,name,{timeout:10000});};
  const save=async(p)=>{await p.locator('[data-factory-save]').click();await p.locator('#overlay').waitFor({state:'hidden'});};
  const date=async p=>{await p.locator('#factory-date').fill('2026-10-20');await p.locator('#factory-date').press('Tab');};

 await go(director,'attendance');await director.locator('[data-factory-act=attendance][data-id=""]').first().click();
 await director.locator('#attendance-default-start').fill('21:30');await director.locator('[data-attendance-fill-start]').click();
 assert((await director.locator('[data-group-time=start_time]').first().inputValue())==='21:30');
 assert(await director.locator('[data-group-time=start_time]').evaluateAll(ns=>ns.length>1&&ns.every(n=>n.value==='21:30')));
 await director.locator('[data-group-time=start_time]').first().fill('22:00');await director.locator('#factory-attendance-editor-search').fill('测试');
 assert.equal(await director.locator('[data-group-time=start_time]').first().inputValue(),'22:00');
 assert(!(await director.locator('#dialog-body').innerText()).includes('人天'));
 await director.locator('#dialog-close').click();await director.locator('[data-leave-choice=discard]').click();await director.locator('#overlay').waitFor({state:'hidden'});
 const chart=await director.evaluate(()=>quantityCharts('库存',[{id:'RM-SOY',name:'大豆',qty:100000,unit:'公斤'},{id:'A-SALT',name:'食用盐',qty:20,unit:'公斤'}],'name'));
 assert(chart.includes('100吨'));assert(chart.includes('20公斤'));assert(chart.includes('大豆'));
 const items=await director.evaluate(()=>resourceData().items);assert.equal(items.find(i=>i.id==='P-CLOTH').unit,'公斤');assert.equal(items.find(i=>i.id==='P-BAG').unit,'包');assert.equal(items.filter(i=>['大豆腐框','中豆腐框','熏干框','魔芋框','长框'].includes(i.name)).length,5);
 assert.deepEqual(errors,[]);console.log('默认时间一键填入、逐组修改与筛选保留、吨数分图及辅料档案验证通过');
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
