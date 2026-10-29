'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync('/tmp/erp-payroll0951-'),db=path.join(tmp,'navigation-test-payroll.db');let service,browser;const errors=[];
 try{
 cp.execFileSync('python3',['-c',`
import sys,json,time
from pathlib import Path
import server,auth
server.DB=Path(sys.argv[1]);server.init_db()
with server.connect(True) as c:
 a=auth.create_initial_admin(c,'admin','工资历史验收','History-Initial-2026!',int(time.time()))
 auth.change_password(c,a,'History-Initial-2026!','History-Personal-2026!',int(time.time()))
 for username,role in [('accountant','会计'),('cashier','出纳'),('director','厂长')]:
  u=auth.create_user(c,a,{'username':username,'display_name':'验收'+role,'role':role,'password':'History-Initial-2026!'},int(time.time()))
  auth.change_password(c,u,'History-Initial-2026!','History-Personal-2026!',int(time.time()))
 rows=[{'employee_id':'E-%03d'%i,'employee_name':'原姓名%03d'%i,'employee_type':'production','group_name':'原班组','monthly_cents':300000,'salary_mode':'monthly','base_cents':10000,'bonus_cents':0,'deduction_cents':0,'net_cents':10000,'pay_days':'1','reason':'原调整说明','calculation_note':'原核算规则','bank_card':'PRIVATE-CARD','cells':[{'date':'2020-09-01','status':'full','label':'全','group_name':'原班组','note':'原考勤说明'}]} for i in range(126)]
 sheet={'id':'S-HISTORY','kind':'sheet','month':'2020-09','state':'confirmed','rows':rows,'version':2,'updated_at':'2020-10-01T09:00:00+08:00','salary_token':'private-token'}
 c.execute('INSERT INTO payroll_records VALUES(?,?,?)',('S-HISTORY','S-HISTORY',json.dumps(sheet)))
 for i in range(126):
  rid='P-%03d'%i;p={'id':rid,'kind':'payment','month':'2020-09','employee_id':'E-%03d'%i,'employee_name':'原姓名%03d'%i,'business_date':'2021-01-15','amount_cents':5000,'handler':'原出纳','reference':'流水%03d'%i,'method':'bank_transfer','recipient':{'bank_card':'6222000012345678','card_tail':'5678','bank_name':'原银行','account_name':'原户名'},'version':1}
  c.execute('INSERT INTO payroll_records VALUES(?,?,?)',(rid,rid,json.dumps(p)))
`,db],{cwd:root,stdio:'pipe'});
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 service=cp.spawn('python3',['-u','server.py','--database',db,'--port',String(port),'--no-browser'],{cwd:root,stdio:['ignore','pipe','pipe']});
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('临时服务启动超时')),15000);service.stdout.on('data',chunk=>{if(String(chunk).includes('豆制品 ERP')){clearTimeout(timer);resolve();}});service.once('exit',code=>{clearTimeout(timer);reject(Error('临时服务提前退出 '+code));});});
 browser=await chromium.launch({channel:'chrome',headless:true});
 const login=async username=>{const context=await browser.newContext({viewport:{width:1440,height:1000}}),p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto('http://127.0.0.1:'+port);await p.locator('[name=username]').fill(username);await p.locator('[name=password]').fill('History-Personal-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user&&!navigationLoading);return p;};
 const p=await login('accountant');await p.evaluate(()=>goto('payroll'));await p.locator('[data-payroll-history-open]').click();await p.locator('#payroll-history-form [name=all]').check();await p.locator('#payroll-history-form [type=submit]').click();await p.waitForFunction(()=>payrollHistoryState().state.value?.total===126);
 assert.equal(await p.evaluate(()=>payrollHistoryState().state.value.summary.net_cents),1260000);
 assert.equal(await p.evaluate(()=>payrollHistoryState().state.value.summary.paid_cents),630000);
 await p.locator('[data-payroll-history-page="2"]').first().click();await p.waitForFunction(()=>payrollHistoryState().state.value?.page===2);assert.match(await p.locator('#content').innerText(),/第 2 \/ 3 页/);
 await p.locator('#payroll-history-form [name=search]').fill('原姓名125');await p.locator('#payroll-history-form [type=submit]').click();await p.waitForFunction(()=>payrollHistoryState().state.value?.total===1);
 await p.locator('[data-payroll-history-detail]').click();await p.locator('#dialog-title').filter({hasText:'工资原单快照'}).waitFor();assert.match(await p.locator('#dialog').innerText(),/原核算规则/);assert.match(await p.locator('#dialog').innerText(),/原考勤说明/);assert.match(await p.locator('#dialog').innerText(),/单独保存的确认时间 未列/);assert.doesNotMatch(await p.locator('#dialog').innerText(),/PRIVATE-CARD|private-token/);await p.locator('#dialog [data-act=close]').click();
 for(const width of [1440,390,320]){await p.setViewportSize({width,height:1000});await p.evaluate(()=>closeMobileNavigation());if(width<760)await p.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<=1);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'页面溢出 '+width);await p.screenshot({path:path.join(tmp,'payroll-'+width+'.png'),fullPage:true});}
 await p.locator('[data-payroll-history-payments]').click();await p.waitForFunction(()=>payrollHistoryKind==='payment'&&payrollHistoryState().state.value?.total===1);assert.equal(await p.locator('#payroll-history-form [name=salary_month]').inputValue(),'2020-09');assert.match(await p.locator('#content').innerText(),/2021-01-15/);
 await p.locator('[data-payroll-history-detail]').click();await p.locator('#dialog-title').filter({hasText:'原发放记录'}).waitFor();assert.match(await p.locator('#dialog').innerText(),/5678/);assert.doesNotMatch(await p.locator('#dialog').innerText(),/6222000012345678/);await p.locator('#dialog [data-act=close]').click();
 await p.locator('#payroll-history-form [name=all]').uncheck();await p.locator('#payroll-history-form [name=start]').fill('2020-09-01');await p.locator('#payroll-history-form [name=end]').fill('2020-09-30');await p.locator('#payroll-history-form [type=submit]').click();await p.waitForFunction(()=>payrollHistoryState().state.value?.total===0);assert.match(await p.locator('#content').innerText(),/暂无记录/);
 await p.locator('[data-go-back]').click();await p.waitForFunction(()=>!payrollHistoryOpen);assert.equal(await p.evaluate(()=>page),'payroll');
 const cashier=await login('cashier');assert.equal(await cashier.evaluate(async()=>(await fetch('/api/payroll-history?all=1')).status),200);
 const director=await login('director');assert.equal(await director.evaluate(async()=>(await fetch('/api/payroll-history?all=1')).status),403);assert.equal(await director.evaluate(async()=>(await fetch('/api/payroll-history-record?kind=sheet&id=S-HISTORY&employee_id=E-000')).status),403);
 assert.deepEqual(errors,[]);const result={ok:true,checks:['126项三页与完整金额汇总','原工资和考勤快照按需读取','原单跳转员工所属月发放','跨年发放按实际付款日期筛选','银行卡只显示原尾号','会计出纳可读、厂长403','返回关闭历史视图','1440/390/320布局'],errors,evidence:tmp};fs.writeFileSync(path.join(tmp,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser?.close();service?.kill();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
