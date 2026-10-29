const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-delete-')),db=path.join(temp,'factory-delete.db');
 cp.execFileSync('python3',['-c',`import sys,uuid,datetime,time
from pathlib import Path
import server,auth,production_management as fm
server.DB=Path(sys.argv[1]);server.init_db()
with server.connect(True) as c:
 auth.create_initial_admin(c,'admin','测试管理员','Delete-Admin-2026!',int(time.time()))
 e=fm.save(c,'employee',{'request_key':str(uuid.uuid4()),'name':'删除测试员工','employee_type':'production','group_id':'G-TOFU'},'管理员',server.now,server.audit)
 day=datetime.date.today().isoformat()
 fm.save(c,'schedule',{'request_key':str(uuid.uuid4()),'business_date':day,'format':'group-plan-v1','state':'confirmed','groups':[{'group_id':'G-TOFU','group_name':'豆腐组','start_time':'08:00','end_time':'17:00'}],'entries':[{'employee_id':e['id'],'group_id':'G-TOFU','status':'full'}]},'管理员',server.now,server.audit)
 fm.save(c,'production-attendance',{'request_key':str(uuid.uuid4()),'business_date':day,'format':'person-day-v1','workflow':'separate-v1','state':'confirmed','groups':[],'entries':[{'employee_id':e['id'],'group_id':'G-TOFU','status':'full'}]},'管理员',server.now,server.audit)
`,db],{cwd:root});
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});}),base=`http://127.0.0.1:${port}`,service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const errors=[],context=await browser.newContext({viewport:{width:1512,height:1000}}),p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Delete-Admin-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>!!data?.auth_user);
  await p.evaluate(()=>goto('attendance'));await p.waitForFunction(()=>page==='attendance'&&!navigationLoading);
  await p.setViewportSize({width:390,height:844});await p.evaluate(()=>render());
  assert.equal(await p.locator('[data-factory-delete="attendance"]').count(),1);
  assert((await p.evaluate(()=>document.documentElement.scrollWidth))<=391,'390宽度不应横向溢出');
  await p.screenshot({path:path.join(root,'output/管理员删除排班与考勤-v0.72.0/浏览器验收/删除入口-390.png'),fullPage:true});
  await p.setViewportSize({width:1440,height:1000});await p.evaluate(()=>render());
  const remove=async(kind,reason)=>{
   const button=p.locator(`[data-factory-delete="${kind}"]`);assert.equal(await button.count(),1,kind+' 删除按钮应唯一');
   await button.click();await p.locator('#factory-delete-form').waitFor();await p.locator('#factory-delete-form [name=reason]').fill(reason);
   await p.screenshot({path:path.join(root,'output/管理员删除排班与考勤-v0.72.0/浏览器验收/删除确认-1440.png'),fullPage:true});
   await p.locator('[data-factory-delete-confirm]').click();await p.locator('#overlay').waitFor({state:'hidden'});
   await p.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('已删除'));
   await p.waitForFunction(k=>!document.querySelector(`[data-factory-delete="${k}"]`),kind,{timeout:10000});
  };
  await remove('attendance','浏览器验收：删除当天考勤');
  assert.equal(await p.locator('[data-factory-delete="attendance"]').count(),0);
  await p.evaluate(()=>{attendanceView='schedule';render();});await p.waitForFunction(()=>attendanceView==='schedule');
  await remove('schedule','浏览器验收：删除排班');
  assert.equal(await p.locator('[data-factory-delete="schedule"]').count(),0);
  assert.deepEqual(errors,[]);
  await p.screenshot({path:path.join(root,'output/管理员删除排班与考勤-v0.72.0/浏览器验收/删除完成-1440.png'),fullPage:true});
  fs.writeFileSync(path.join(root,'output/管理员删除排班与考勤-v0.72.0/浏览器验收/浏览器验收.json'),JSON.stringify({ok:true,checks:5,viewport:['1440','390'],deleteAttendance:true,deleteSchedule:true,errors},null,2));
  console.log('管理员删除考勤、排班入口与弹窗通过');
 }finally{if(browser)await browser.close();service.kill();fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
