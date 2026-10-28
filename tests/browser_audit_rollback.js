const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'output/审计操作回滚-v0.73.0/浏览器验收'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-rollback-')),db=path.join(temp,'rollback.db');
 fs.mkdirSync(out,{recursive:true});
 cp.execFileSync('python3',['-c',`import sys,time
from pathlib import Path
import server,auth
server.DB=Path(sys.argv[1]);server.init_db()
with server.connect(True) as c:
 auth.create_initial_admin(c,'admin','测试管理员','Rollback-Admin-2026!',int(time.time()))
 rec={'id':'C-WEBROLL','name':'回滚测试客户','route':'测试线路','note':'浏览器验收','delivery_method':'pickup'}
 c.execute("INSERT INTO customers(id,name,route,note,delivery_method) VALUES(?,?,?,?,?)",(rec['id'],rec['name'],rec['route'],rec['note'],rec['delivery_method']))
 server.audit(c,'管理员','新增客户',rec['id'],None,rec)
`,db],{cwd:root});
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});}),base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const errors=[],context=await browser.newContext({viewport:{width:1512,height:1000}}),p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Rollback-Admin-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>!!data?.auth_user);
  await p.evaluate(()=>goto('logs'));await p.waitForFunction(()=>page==='logs'&&!navigationLoading);
  await p.waitForFunction(()=>!!document.querySelector('[data-audit-rollback]'));
  assert((await p.evaluate(()=>Object.fromEntries(data.customers.map(c=>[c.id,c.name]))['C-WEBROLL']))==='回滚测试客户','种子客户应存在');
  await p.setViewportSize({width:390,height:844});await p.evaluate(()=>render());
  assert.equal(await p.locator('[data-audit-rollback]').count()>=1,true);
  assert((await p.evaluate(()=>document.documentElement.scrollWidth))<=391,'390宽度不应横向溢出');
  await p.screenshot({path:path.join(out,'回滚入口-390.png'),fullPage:true});
  await p.setViewportSize({width:1440,height:1000});await p.evaluate(()=>render());
  const trigger=p.locator('[data-audit-rollback]').first();await trigger.click();
  await p.locator('#audit-rollback-form').waitFor();
  const text=await p.locator('#audit-rollback-form').innerText();assert(text.includes('将删除该操作新建的记录'),text);assert(text.includes('C-WEBROLL'),text);
  await p.locator('#audit-rollback-form [name=reason]').fill('浏览器验收：回滚新增客户');
  await p.screenshot({path:path.join(out,'回滚确认-1440.png'),fullPage:true});
  await p.locator('[data-audit-rollback-confirm]').click();
  await p.locator('#overlay').waitFor({state:'hidden'});
  await p.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('已回滚'));
  await p.waitForFunction(()=>!data.customers.some(c=>c.id==='C-WEBROLL'));
  assert.equal(await p.evaluate(()=>data.customers.some(c=>c.id==='C-WEBROLL')),false,'客户应已删除');
  assert.deepEqual(errors,[]);
  await p.screenshot({path:path.join(out,'回滚完成-1440.png'),fullPage:true});
  fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify({ok:true,checks:5,viewport:['1440','390'],rollbackCreatedCustomer:true,errors},null,2));
  console.log('审计回滚入口、确认弹窗与删除结果通过');
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
