'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync('/tmp/erp-config0960-'),db=path.join(tmp,'navigation-test-payroll.db');let service,browser;const errors=[];
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

 const p=await login('accountant');await p.evaluate(()=>{wageMonth='2099-01';goto('payroll');});await p.locator('[data-social-policy-open]').click();await p.locator('#social-policy-form').waitFor();await p.locator('#social-policy-form [name=effective_month]').fill('2099-01');await p.locator('#social-policy-form [name=social_base]').fill('100');await p.locator('#social-policy-form [name=social_company_rate]').fill('10');await p.locator('#social-policy-form [name=social_personal_rate]').fill('2');await p.locator('[data-social-policy-save]').click();await p.waitForFunction(()=>!busy&&document.getElementById('overlay').hidden);
 const amounts=await p.evaluate(async()=>{const r=await api('/api/factory/report?kind=payroll&month=2099-01');return r.rows.map(x=>({name:x.employee_name,company:x.social_company_cents}));});assert.equal(amounts.find(x=>x.name==='普通人员').company,1000);assert.equal(amounts.find(x=>x.name==='个人例外').company,500);
 await p.evaluate(()=>openCratePackagingSettings());await p.locator('#crate-packaging-form').waitFor();for(const name of ['自定义轻包材','可复用厚包材']){await p.locator('[data-packing-add-method]').click();await p.locator('[name=method_name]').last().fill(name);await p.locator('[name=method_name]').last().press('Tab');}
 const ids=await p.locator('[data-packing-method]').evaluateAll(rows=>rows.map(r=>r.dataset.packingMethod));await p.locator('#crate-packaging-form [name=default_method_id]').selectOption(ids[0]);for(let i=0;i<2;i++){await p.locator('[data-packing-add-rule]').click();const row=p.locator('[data-packing-rule]').last();await row.locator('[name=product_id]').selectOption('P001');await row.locator('[name=asset_id]').selectOption('CR-WHITE');await row.locator('[name=method_id]').selectOption(ids[i]);await row.locator('[name=tare]').fill(i?'2.501':'2');}await p.locator('[data-packing-save-config]').click();await p.waitForFunction(()=>!busy&&document.getElementById('overlay').hidden);await p.evaluate(()=>openCratePackagingSettings());await p.locator('#crate-packaging-form').waitFor();assert.equal(await p.locator('#crate-packaging-form [name=default_method_id]').inputValue(),ids[0]);assert.equal(await p.locator('[data-packing-rule] [name=method_id]').first().inputValue(),ids[0]);assert.equal(await p.locator('[data-packing-rule] [name=tare]').last().inputValue(),'2.501');
 await p.evaluate(()=>{closeDialog();return openCratePacking(data.orders.find(o=>o.batch==='包装UI验收').id,'P001');});await p.locator('#order-crate-packing').waitFor();await p.locator('[data-packing-add-entry]').click();const entry=p.locator('[data-packing-entry]').last();await entry.locator('[name=method_id]').selectOption(ids[1]);assert.equal(await entry.locator('[name=tare]').inputValue(),'2.501');await entry.locator('[name=qty]').fill('2');assert.equal(await p.locator('[data-packing-entry] [name=qty]').first().inputValue(),'8');
 for(const width of [1440,390,320]){await p.setViewportSize({width,height:1000});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'页面溢出 '+width);await p.screenshot({path:path.join(tmp,'config-'+width+'.png'),fullPage:true});}
 await p.locator('[data-packing-save-order]').click();const savedPacking=await p.evaluate(async()=>{const o=workingOrder(data.orders.find(o=>o.batch==='包装UI验收'));return api('/api/orders/'+o.id+'/order',o);});assert.equal(savedPacking.lines[0].customer_net,'78.998');assert.deepEqual(savedPacking.lines[0].crate_lines[0].packing_lines.map(r=>r.qty),[8,2]);
 assert.deepEqual(errors,[]);const result={ok:true,checks:['统一补偿款设置实际保存','普通人员跟随、个人例外保留','任意包法名称与组合皮重实际保存','再次打开正确回显默认包法与规则','混包录入自动补足默认数量并实际保存、客户净重78.998','1440/390/320布局'],errors,evidence:tmp};fs.writeFileSync(path.join(tmp,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser?.close();service?.kill();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
