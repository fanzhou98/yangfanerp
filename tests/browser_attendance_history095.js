'use strict';
// Synthetic factory data only. Evidence lives in /tmp, outside the project.
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync('/tmp/erp-attendance095-'),db=path.join(tmp,'navigation-test-attendance.db');
 let service,browser;const errors=[];
 try{
 cp.execFileSync('python3',['-c',`
import sys,json,time
from pathlib import Path
from datetime import date,timedelta
import server,auth
server.DB=Path(sys.argv[1]);server.init_db()
with server.connect(True) as c:
 a=auth.create_initial_admin(c,'admin','历史验收管理员','History-Initial-2026!',int(time.time()))
 auth.change_password(c,a,'History-Initial-2026!','History-Personal-2026!',int(time.time()))
 for username,role in [('director','厂长'),('manager','行政负责人')]:
  u=auth.create_user(c,a,{'username':username,'display_name':'验收'+role,'role':role,'password':'History-Initial-2026!'},int(time.time()))
  auth.change_password(c,u,'History-Initial-2026!','History-Personal-2026!',int(time.time()))
 for eid,name,kind in [('H-P','生产甲','production'),('H-M','管理秘密','management')]:
  e={'id':eid,'name':name,'employee_type':kind,'group_id':'G-TOFU' if kind=='production' else '','group_name':'豆腐组' if kind=='production' else '','department':'生产' if kind=='production' else '行政','active':True}
  c.execute('INSERT INTO factory_employees VALUES(?,?,?)',(eid,eid,json.dumps(e)))
 for i in range(126):
  day=(date(2020,1,1)+timedelta(days=i)).isoformat();rid='AH-%03d'%i
  r={'id':rid,'business_date':day,'state':'confirmed','version':1,'groups':[],'entries':[{'employee_id':eid,'employee_name':name,'employee_type':kind,'group_id':'G-TOFU' if kind=='production' else '','group_name':'豆腐组' if kind=='production' else '','status':'half' if i==0 else 'full','note':'首条核验' if i==0 else ''} for eid,name,kind in [('H-P','生产甲','production'),('H-M','管理秘密','management')]]}
  c.execute('INSERT INTO factory_attendance VALUES(?,?,?)',(rid,rid,json.dumps(r)))
`,db],{cwd:root,stdio:'pipe'});
 const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const p=socket.address().port;socket.close(()=>resolve(p));});});
 service=cp.spawn('python3',['-u','server.py','--database',db,'--port',String(port),'--no-browser'],{cwd:root,stdio:['ignore','pipe','pipe']});
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('临时服务启动超时')),15000);service.stdout.on('data',chunk=>{if(String(chunk).includes('豆制品 ERP')){clearTimeout(timer);resolve();}});service.once('exit',code=>{clearTimeout(timer);reject(Error('临时服务提前退出 '+code));});});
 browser=await chromium.launch({channel:'chrome',headless:true});
 const login=async username=>{const context=await browser.newContext({viewport:{width:1440,height:1000}}),p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto('http://127.0.0.1:'+port);await p.locator('[name=username]').fill(username);await p.locator('[name=password]').fill('History-Personal-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user&&!navigationLoading);return p;};
 const p=await login('director');assert.equal(await p.evaluate(()=>factoryData().attendance_deferred),true);assert.equal(await p.evaluate(()=>factoryData().attendance.length+factoryData().schedules.length),0);assert.equal(await p.evaluate(()=>factoryData().attendance_activity.length),126);
 await p.evaluate(()=>goto('attendance'));await p.locator('[data-attendance-view=history]').click();
 await p.locator('#attendance-history-form [name=all]').check();await p.locator('#attendance-history-form [type=submit]').click();
 await p.waitForFunction(()=>attendanceHistoryState().state.value?.total===126);
 assert.match(await p.locator('#content').innerText(),/125.5 天/);
 assert.doesNotMatch(await p.locator('#content').innerText(),/管理秘密/);
 await p.locator('[data-attendance-history-page="2"]').first().click();await p.waitForFunction(()=>attendanceHistoryState().state.value?.page===2);
 assert.match(await p.locator('#content').innerText(),/第 2 \/ 3 页/);
 await p.locator('#attendance-history-form [name=search]').fill('首条核验');await p.locator('#attendance-history-form [type=submit]').click();
 await p.waitForFunction(()=>attendanceHistoryState().state.value?.total===1);
 assert.match(await p.locator('#content').innerText(),/0.5 天/);
 assert.equal(await p.locator('#attendance-history-form [name=all]').isChecked(),true);
 for(const width of [1440,390,320]){await p.setViewportSize({width,height:1000});await p.evaluate(()=>closeMobileNavigation());if(width<760)await p.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<=1);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'页面溢出 '+width);assert(await p.evaluate(()=>[...document.querySelectorAll('.attendance-mode-tabs > button')].every(b=>b.scrollWidth<=b.clientWidth+1)),'页签文字重叠 '+width);await p.screenshot({path:path.join(tmp,'attendance-'+width+'.png'),fullPage:true});}
 await p.locator('[data-go-back]').click();await p.waitForFunction(()=>attendanceView==='day');assert.equal(await p.evaluate(()=>page),'attendance');
 await p.evaluate(()=>{factoryData().attendance=[];factoryData().schedules=[];factoryReports.clear();factoryDay='2020-01-01';selectedDate=factoryDay;attendanceView='day';render();});
 await p.waitForFunction(()=>cachedAttendanceDay()?.attendance?.business_date==='2020-01-01');assert.match(await p.locator('#content').innerText(),/生产甲/);assert.doesNotMatch(await p.locator('#content').innerText(),/管理秘密/);
 await p.locator('[data-factory-act=attendance]').first().click();await p.locator('[data-attendance-person="H-P"] [data-attendance-field=status]').selectOption('leave');await p.locator('[data-factory-confirm]').click();await p.waitForFunction(()=>!busy&&document.getElementById('overlay').hidden);await p.waitForFunction(()=>cachedAttendanceDay()?.attendance?.entries?.some(e=>e.employee_id==='H-P'&&e.status==='leave'));
 await p.evaluate(()=>{factoryDay='2020-01-02';selectedDate=factoryDay;attendanceView='schedule';render();});await p.locator('[data-factory-act=copy-attendance]').waitFor();await p.locator('[data-factory-act=copy-attendance]').click();assert.equal(await p.locator('[data-attendance-person="H-P"] [data-attendance-field=status]').inputValue(),'full');assert.equal(await p.evaluate(()=>cachedAttendanceDay('2020-01-01').attendance.entries.find(e=>e.employee_id==='H-P').status),'leave');await p.locator('#dialog [data-act=close]').click();
 await p.route('**/api/attendance-day?*',route=>route.request().url().includes('date=2020-01-04')?route.abort():route.continue());await p.evaluate(()=>{factoryReports.clear();factoryDay='2020-01-05';selectedDate=factoryDay;attendanceView='schedule';render();});await p.waitForFunction(()=>!!factoryReports.get('attendance-day|production|2020-01-04')?.error);assert(await p.locator('[data-factory-act=copy-attendance]').isDisabled());await p.locator('[data-factory-act=schedule]').first().click();await p.locator('#dialog').waitFor({state:'visible'});await p.locator('#dialog [data-act=close]').click();await p.unroute('**/api/attendance-day?*');
 await p.route('**/api/attendance-day?*',route=>route.abort());await p.evaluate(()=>{factoryReports.clear();factoryDay='2020-01-03';selectedDate=factoryDay;attendanceView='day';render();});await p.waitForFunction(()=>!!factoryReports.get('attendance-day|production|2020-01-03')?.error);assert.equal(await p.locator('[data-factory-act=attendance]').count(),0);await p.unroute('**/api/attendance-day?*');await p.evaluate(()=>{factoryReports.clear();render();});await p.waitForFunction(()=>cachedAttendanceDay()?.attendance?.business_date==='2020-01-03');
 await p.evaluate(()=>{factoryReports.clear();factoryDay='2020-01-04';selectedDate=factoryDay;goto('factory');});await p.waitForFunction(()=>page==='factory'&&!navigationLoading);await p.evaluate(()=>factoryOpenForm('attendance',''));await p.locator('[data-attendance-person="H-P"]').waitFor();assert.equal(await p.locator('[data-attendance-person="H-P"] [data-attendance-field=status]').inputValue(),'full');await p.locator('#dialog [data-act=close]').click();
 await p.evaluate(async()=>{await api('/api/factory/schedule',{request_key:erpRequestKey(),business_date:'2020-01-07',format:'group-plan-v1',state:'confirmed',groups:[{group_id:'G-TOFU',start_time:'08:00',end_time:'17:00'}],entries:[{employee_id:'H-P',group_id:'G-TOFU',status:'full'}]});await refresh();factoryDay='2020-01-07';selectedDate=factoryDay;attendanceView='schedule';goto('attendance');});await p.locator('[data-factory-act=notice]').click();await p.locator('#factory-notice-text').waitFor();assert.match(await p.locator('#factory-notice-text').inputValue(),/生产甲/);await p.locator('#dialog [data-act=close]').click();
 const administrator=await login('admin');await administrator.evaluate(()=>{factoryDay='2020-01-01';attendanceMonth='2020-01';goto('attendance');});await administrator.waitForFunction(()=>page==='attendance'&&!navigationLoading);await administrator.evaluate(()=>factoryDeleteRecord('attendance-month',{employeeId:'H-P',month:'2020-01',name:'生产甲'}));await administrator.locator('#factory-delete-form').waitFor();assert.match(await administrator.locator('#factory-delete-form').innerText(),/已有 31 天记录/);await administrator.locator('#dialog [data-act=close]').click();
 await administrator.route('**/api/attendance-month-count?*',route=>route.abort());const priorNotice=await administrator.evaluate(()=>notificationSequence);await administrator.evaluate(()=>factoryDeleteRecord('attendance-month',{employeeId:'H-P',month:'2020-01',name:'生产甲'}));await administrator.waitForFunction(prior=>notificationSequence>prior,priorNotice);assert.equal(await administrator.locator('#overlay:not([hidden]) [data-factory-delete-confirm]').count(),0);await administrator.unroute('**/api/attendance-month-count?*');
 const manager=await login('manager');await manager.evaluate(()=>goto('management-attendance'));await manager.locator('[data-attendance-view=history]').click();await manager.locator('#attendance-history-form [name=all]').check();await manager.locator('#attendance-history-form [type=submit]').click();await manager.waitForFunction(()=>attendanceHistoryState().state.value?.total===126);
 assert.match(await manager.locator('#content').innerText(),/管理秘密/);assert.doesNotMatch(await manager.locator('#content').innerText(),/生产甲/);
 assert.equal(await manager.evaluate(async()=>(await fetch('/api/attendance-history?scope=production&all=1')).status),403);
 assert.deepEqual(errors,[]);
 const result={ok:true,checks:['126条三页及完整出勤汇总','翻页后搜索返回第一页并保留全部日期','生产与管理记录及汇总隔离','跨类读取403','返回键关闭历史子视图','1440/390/320布局','移除本地完整明细后按日读取、修改保存与复制昨日成功','读取失败不显示空白新建入口','真实bootstrap无考勤排班明细且保留完整日期状态','生产页直开表单和原排班通知按需读取','整月删除确认完整31条，计数失败不弹确认'],errors,evidence:tmp};fs.writeFileSync(path.join(tmp,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser?.close();service?.kill();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
