'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync('/tmp/erp-crate0980-'),db=path.join(tmp,'navigation-test-payroll.db');let service,browser;const errors=[];
 try{
 cp.execFileSync('python3',['-c',`
import sys,json,time
from pathlib import Path
import server,auth,production_management as fm,payroll,uuid
server.DB=Path(sys.argv[1]);server.init_db()
with server.connect(True) as c:
 a=auth.create_initial_admin(c,'admin','工资历史验收','History-Initial-2026!',int(time.time()))
 auth.change_password(c,a,'History-Initial-2026!','History-Personal-2026!',int(time.time()))
 for username,role in [('accountant','会计'),('cashier','出纳'),('director','厂长')]:
  u=auth.create_user(c,a,{'username':username,'display_name':'验收'+role,'role':role,'password':'History-Initial-2026!'},int(time.time()))
  auth.change_password(c,u,'History-Initial-2026!','History-Personal-2026!',int(time.time()))
 server.mutate('order',{'customer_id':'C001','business_date':'2026-10-29','batch':'包装UI验收','lines':[{'product_id':'P001','ordered_qty':'10','actual_qty':'10','price':'3','driver':[],'customer':[{'gross':'100','count':'10','tare':'2'}],'crate_lines':[{'asset_id':'CR-WHITE','qty':10,'tare':'2'}]}]},'管理员',connection=c)
 people=[]
 for name in ('普通人员','个人例外'):
  e=fm.save(c,'employee',{'request_key':str(uuid.uuid4()),'name':name,'group_id':'G-TOFU'},'管理员',server.now,server.audit);people.append(e)
 e=people[1];profile=next(p for p in payroll.records(c) if p['kind']=='profile' and p['employee_id']==e['id'])
 payroll.save(c,'wage-profile',{'request_key':str(uuid.uuid4()),'employee_id':e['id'],'version':profile['version'],'monthly_salary':'3000','social_policy_mode':'override','social_base':'50','social_company_rate':'10','social_personal_rate':'2'},'管理员',server.now,server.audit)
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

 const p=await login('accountant');await p.evaluate(()=>{assetView='settings';goto('crates');});await p.waitForFunction(()=>assetCache?.value&&!assetCache.loading);
 await p.evaluate(()=>assetOpen('asset','CR-WHITE'));await p.locator('#asset-form').waitFor();await p.locator('[data-asset-add-special]').click();await p.locator('[data-special-name]').last().fill('布包');await p.locator('[data-special-tare]').last().fill('2.501');await p.locator('[data-asset-save]').click();await p.waitForFunction(()=>!busy&&document.getElementById('overlay').hidden);await p.waitForFunction(()=>assetCache?.value&&!assetCache.loading);
 await p.evaluate(()=>assetOpen('asset','CR-WHITE'));assert.equal(await p.locator('[data-special-tare]').last().inputValue(),'2.501');await p.evaluate(()=>closeDialog());
 await p.evaluate(()=>openCratePacking(data.orders.find(o=>o.batch==='包装UI验收').id,'P001'));await p.locator('[data-special-qty]').fill('2');assert.equal(await p.locator('[data-ordinary-qty]').innerText(),'8');assert.equal(await p.locator('#order-crate-packing input').count(),1);
 await p.evaluate(()=>hideWorkflowFeedback());
 for(const width of [1440,390,320]){await p.setViewportSize({width,height:1000});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await p.screenshot({path:path.join(tmp,'special-'+width+'.png'),fullPage:true});}
 await p.locator('[data-packing-save-order]').click();const saved=await p.evaluate(async()=>{const o=workingOrder(data.orders.find(o=>o.batch==='包装UI验收'));return api('/api/orders/'+o.id+'/order',o);});assert.equal(saved.lines[0].customer_net,'78.998');assert.deepEqual(saved.lines[0].crate_lines[0].packing_lines.map(r=>r.qty),[8,2]);
 await p.setViewportSize({width:1440,height:1000});await p.evaluate(()=>assetOpen('asset'));await p.locator('#asset-form [name=name]').fill('未使用删除验收框');await p.locator('[data-asset-save]').click();await p.waitForFunction(()=>!busy&&document.getElementById('overlay').hidden);await p.waitForFunction(()=>assetCache?.value?.assets.some(a=>a.name==='未使用删除验收框'));const aid=await p.evaluate(()=>assetCache.value.assets.find(a=>a.name==='未使用删除验收框').id);await p.locator('[data-asset-delete="'+aid+'"]').click();await p.locator('[data-workflow-answer=yes]').click();await p.waitForFunction(id=>assetCache?.value&&!assetCache.value.assets.some(a=>a.id===id)&&!busy,aid);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,checks:['框型编辑一次保存特殊包装并回显','算票只填布包2普通自动8','净重78.998保存','未使用框型真实删除','1440/390/320布局'],errors,evidence:tmp}));
 }finally{await browser?.close();service?.kill();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
