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
  const login=async(name,password)=>{const c=await browser.newContext({viewport:process.env.ERP_INPUT_MOBILE?{width:390,height:844}:{width:1512,height:1000}}),p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill(password);await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>!!data?.auth_user);return p;};
  const director=await login('director','Factory-Director-2026!');assert.equal(await director.evaluate(()=>page),'dashboard');await director.evaluate(()=>goto('factory'));await director.waitForFunction(()=>page==='factory'&&!navigationLoading);
  const go=async(p,name)=>{await p.evaluate(name=>goto(name),name);await p.waitForFunction(n=>page===n&&!navigationLoading,name,{timeout:10000});};
  const save=async(p)=>{await p.locator('[data-factory-save]').click();await p.locator('#overlay').waitFor({state:'hidden'});};
  const date=async p=>{await p.locator('#factory-date').fill('2026-10-20');await p.locator('#factory-date').press('Tab');};



 const admin=await login('admin','Factory-Test-Admin-2026!');
 await admin.evaluate(async()=>{await api('/api/factory/employee',{request_key:erpRequestKey(),name:'输入测试员工',group_id:'G-TOFU',active:true});await refresh();});
 async function checkInput(p,id){
  await p.locator('#'+id).waitFor();
  const result=await p.evaluate(id=>{
   const el=document.getElementById(id);el.focus();el.value='';el.dispatchEvent(new Event('input',{bubbles:true}));
   const original=document.getElementById(id);original.focus();original.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:''}));
   for(const value of ['s','shu','输入']){original.value=value;original.setSelectionRange(value.length,value.length);original.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,inputType:'insertCompositionText',data:value}));if(!original.isConnected||document.activeElement!==original)throw Error(id+' composition interrupted');}
   const enter=new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Enter',isComposing:true,keyCode:229});original.dispatchEvent(enter);if(enter.defaultPrevented)throw Error(id+' IME Enter intercepted');
   const escape=new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Escape',isComposing:true,keyCode:229});original.dispatchEvent(escape);if(escape.defaultPrevented)throw Error(id+' IME Escape intercepted');
   original.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'输入'}));
   if(document.getElementById(id)!==original||document.activeElement!==original||original.value!=='输入')throw Error(id+' committed text lost');
   original.value='甲乙丙丁';original.setSelectionRange(1,3,'backward');original.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'甲乙丙丁'}));
   if(document.getElementById(id)!==original||original.selectionStart!==1||original.selectionEnd!==3||original.selectionDirection!=='backward')throw Error(id+' selection changed');
   original.value='';original.dispatchEvent(new Event('input',{bubbles:true}));return true;
  },id);assert(result);console.log('输入与光标通过',id);
 }
 for(const [pageName,id,setup] of [
 ['employees','factory-employee-search'],['attendance','factory-attendance-search',()=>{attendanceView='day';render();}],
 ['attendance','month-search',()=>{attendanceView='month';render();}],['payroll','wage-search'],
 ['sales-daily','sales-table-search'],['sales-monthly','sales-table-search'],['ledger','ledger-search'],
 ['materials','material-search'],['masters','pricing-search',()=>{masterView='pricing';render();}],
 ['dispatch','fleet-search',()=>{dispatchTab='fleet';render();}],['orders','sheet-search'],['weighing','sheet-search'],['settlements','sheet-search']]){
  await go(admin,pageName);if(setup)await admin.evaluate(setup);
  await admin.waitForTimeout(300);await checkInput(admin,id);
 }
 await go(director,'attendance');await director.evaluate(()=>{attendanceView='day';render();});await director.locator('[data-factory-act=attendance]').first().click();await director.locator('#factory-form').waitFor();
 const note=director.locator('[data-attendance-field=note]').first();await note.fill('保留的排班备注');
 await checkInput(director,'factory-attendance-editor-search');assert.equal(await director.locator('[data-attendance-field=note]').first().inputValue(),'保留的排班备注');
 // Use Chromium's IME implementation too, rather than relying only on synthetic DOM events.
 const cdp=await director.context().newCDPSession(director);await director.locator('#factory-attendance-editor-search').focus();
 await cdp.send('Input.imeSetComposition',{text:'shu',selectionStart:3,selectionEnd:3});await cdp.send('Input.imeSetComposition',{text:'输入',selectionStart:2,selectionEnd:2});await cdp.send('Input.insertText',{text:'输入'});
 assert.equal(await director.locator('#factory-attendance-editor-search').inputValue(),'输入');assert.equal(await director.evaluate(()=>attendanceEditSearch),'输入');
 await director.locator('#factory-attendance-editor-search').fill('');await director.locator('[data-factory-save]').click();await director.locator('#overlay').waitFor({state:'hidden'});
 assert((await director.locator('#content').innerText()).includes('保留的排班备注'));
 assert.deepEqual(errors,[]);console.log('排班中文输入、搜索与备注保存，以及所有即时搜索、选区和IME按键保护通过');
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
