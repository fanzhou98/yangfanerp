'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp074-')),db=path.join(temp,'test.db'),out=path.join(root,'output/人员档案银行卡与采购查询-v0.74.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[];
 try{
 cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'pipe'});
 cp.execFileSync('python3',['-c',`import sys,uuid,json,copy
from pathlib import Path
import server,purchasing as p,production_management as f
server.DB=Path(sys.argv[1])
with server.connect(True) as c:
 op=p.Operations(c,server.now,server.audit)
 s=op.supplier({'name':'Q074合成供应商','payment_days':30},'管理员')
 template=op.order({'request_key':str(uuid.uuid4()),'business_date':'2026-09-01','expected_date':'2026-12-01','supplier_id':s['id'],'handler':'测试','note':'Q074','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'10','price':'1'}]},'管理员')
 for i in range(1,121):
  r=copy.deepcopy(template);r.update(id='Q074-'+str(i).zfill(3),business_date='2026-'+str(9+i%3).zfill(2)+'-01',request_fingerprint='',note='Q074')
  c.execute('INSERT INTO purchase_orders VALUES(?,?,?)',(r['id'],str(uuid.uuid4()),server.dumps(r)))
 f.save(c,'employee',{'request_key':str(uuid.uuid4()),'name':'Q074管理人员','employee_type':'management','department':'行政','group_id':'','active':True},'管理员',server.now,server.audit)
`,db],{cwd:root,stdio:'pipe'});
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});const base=`http://127.0.0.1:${port}`;
 for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.stack||e.message));
 const login=async(q,user)=>{await q.goto(base);await q.locator('[name=username]').fill(user);await q.locator('[name=password]').fill('Dashboard-Test-2026!');await q.locator('#auth-login-form [type=submit]').click();await q.waitForFunction(()=>typeof data!=='undefined'&&!!data.auth_user);await q.waitForLoadState('networkidle');};
 const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!busy&&!navigationLoading);if(await p.evaluate(()=>page==='purchases'&&goodsView!=='finished'))await p.waitForFunction(()=>!!purchaseHistoryReport().value);};const go=async v=>{await p.evaluate(x=>goto(x),v);await ready();};
 const shot=async name=>{for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});await ready();if(name==='银行卡并入人员档案')await p.locator('[data-personnel-bank]').scrollIntoViewIfNeeded();assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' '+width);await p.screenshot({path:path.join(out,name+'-'+width+'.png'),fullPage:true});}await p.setViewportSize({width:1440,height:1000});};
 await login(p,'admin');await go('employees');
 assert.equal(await p.locator('#content [data-employee-banks]').count(),0);assert((await p.locator('#content [data-factory-act=employee][data-id]').count())>0);
 const employee=await p.evaluate(()=>factoryData().employees.find(e=>(e.employee_type||'production')==='production'&&e.active));
 await p.locator(`[data-factory-act=employee][data-id="${employee.id}"]`).click();await p.locator('[data-personnel-bank]').waitFor();await shot('银行卡并入人员档案');
 const phone=await p.locator('#factory-form [name=phone]').inputValue();await p.locator('#factory-form [name=phone]').fill('未保存电话');await p.locator('[data-personnel-bank]').click();await p.locator('#leave-overlay').waitFor({state:'visible'});await p.locator('[data-leave-choice=stay]').click();assert.equal(await p.locator('#factory-form [name=phone]').inputValue(),'未保存电话');
 await p.locator('[data-personnel-bank]').click();await p.locator('[data-leave-choice=discard]').click();await p.locator('#employee-bank-form').waitFor();
 await p.locator('#employee-bank-form [name=bank_name]').fill('Q074测试银行');await p.locator('#employee-bank-form [name=bank_card]').fill('0012345678901234567');await p.locator('[data-employee-bank-save]').click();await p.locator('#factory-form').waitFor();assert.equal(await p.locator('#factory-form').getAttribute('data-id'),employee.id);assert.equal(await p.locator('#factory-form [name=phone]').inputValue(),phone);
 await p.locator('[data-personnel-bank]').click();await p.locator('#employee-bank-form').waitFor();assert.equal(await p.locator('[name=bank_card]').inputValue(),'0012345678901234567');await p.locator('[data-employee-bank-personnel]').click();await p.locator('#factory-form').waitFor();
 await p.locator('#factory-form [name=phone]').fill('074已保存');await p.locator('[data-personnel-bank]').click();await p.locator('[data-leave-choice=save]').click();await p.locator('#employee-bank-form').waitFor();await p.locator('[data-employee-bank-personnel]').click();await p.locator('#factory-form').waitFor();assert.equal(await p.locator('[name=phone]').inputValue(),'074已保存');await p.evaluate(()=>closeDialog());
 checks.push('首页仅移除银行卡按钮，编辑人员保留；档案内维护银行卡、保留前导零、保存返回原档案；未保存修改可继续编辑/放弃/保存后进入');
 await go('management-employees');assert.equal(await p.locator('#content [data-employee-banks]').count(),0);await p.locator('#content [data-factory-act=employee][data-id]').first().click();await p.locator('[data-personnel-bank]').waitFor();await p.evaluate(()=>closeDialog());
 await p.locator('#content [data-factory-act=employee][data-person-type]').click();assert.equal(await p.locator('[data-personnel-bank]').count(),0);assert.match(await p.locator('#factory-form').innerText(),/先保存人员档案/);await p.evaluate(()=>closeDialog());
 await go('payroll');await p.locator('[data-employee-banks]').click();await p.locator('#employee-bank-import-form').waitFor();assert.equal(await p.locator('a[download="employee-bank-template.xlsx"]').count(),1);await p.locator(`[data-employee-bank-edit="${employee.id}"]`).click();await p.locator('#employee-bank-form').waitFor();assert.equal(await p.locator('[data-employee-bank-personnel]').count(),0);await p.evaluate(()=>closeDialog());
 checks.push('管理/生产档案一致，新建先保存；工资页批量维护、下载模板和Excel导入入口保留');
 await p.evaluate(()=>{goodsView='raw';});await go('purchases');await ready();assert.equal(await p.evaluate(()=>purchaseHistoryRange.choice),'today');assert.equal(await p.evaluate(()=>purchaseHistoryRange.start===today()),true);
 await p.locator('[data-purchase-history-range-value=all]').click();await ready();await p.locator('#purchase-history-search').fill('Q074');await p.locator('#purchase-history-search').dispatchEvent('change');await ready();
 let result=await p.evaluate(()=>purchaseHistoryReport().value);assert.equal(result.total,121);assert.equal(result.rows.length,50);assert.equal(result.summary.total_cents,121000);const first=result.rows.map(r=>r.id);
 await p.locator('[data-purchase-history-page="2"]').first().click();await ready();result=await p.evaluate(()=>purchaseHistoryReport().value);assert.equal(result.page,2);assert.equal(result.summary.total_cents,121000);assert(!result.rows.some(r=>first.includes(r.id)));
 await p.locator('[data-purchase-history-page="3"]').first().click();await ready();const last=await p.evaluate(()=>purchaseHistoryReport().value);assert.equal(last.rows.length,21);const second=result.rows.map(r=>r.id);assert.equal(new Set([...first,...second,...last.rows.map(r=>r.id)]).size,121);
 await p.locator('[data-purchase-act=detail]').first().click();await p.locator('#dialog').waitFor();assert.match(await p.locator('#dialog').innerText(),/Q074合成供应商/);await p.evaluate(()=>closeDialog());
 await p.locator('#purchase-history-status').selectOption('草稿');await ready();assert.equal(await p.evaluate(()=>purchaseHistoryReport().value.page),1);await shot('采购日期与分页');
 const before=await p.evaluate(()=>purchaseHistoryReport().value.rows.map(r=>r.id));await p.locator('[data-purchase-history-range-act=edit][data-purchase-history-range-value=custom]').click();await p.locator('#purchase-history-range-start').fill('2026-11-01');await p.locator('#purchase-history-range-end').fill('2026-09-01');await p.locator('[data-purchase-history-range-form=custom] [type=submit]').click();assert.match(await p.locator('#purchase-history-range-error').innerText(),/开始日期不能晚于结束日期/);assert.deepEqual(await p.evaluate(()=>purchaseHistoryReport().value.rows.map(r=>r.id)),before);
 await p.locator('#purchase-history-range-start').fill('2026-10-01');await p.locator('#purchase-history-range-end').fill('2026-10-01');await p.locator('[data-purchase-history-range-form=custom] [type=submit]').click();await ready();assert.equal(await p.evaluate(()=>purchaseHistoryReport().value.total),40);assert.equal(await p.evaluate(()=>purchaseHistoryReport().value.summary.total_cents),40000);
 checks.push('默认今日；全部日期121单分50/50/21，跨页无重复且汇总1210元；状态重置页码，原单可打开；错误日期保留原结果，自定义日期40单400元');
 for(const username of ['director','warehouse','cashier']){const q=await browser.newPage();await login(q,username);if(username==='director'){await q.evaluate(()=>goto('employees'));await q.waitForLoadState('networkidle');await q.locator('#content [data-factory-act=employee][data-id]').first().click();assert.equal(await q.locator('.personnel-bank-section').count(),0);assert.equal((await q.request.get(base+'/api/employee-banks')).status(),403);}if(username==='warehouse'){const response=await q.request.get(base+'/api/purchase-orders?all=1');assert.equal(response.status(),200);const text=await response.text();assert(!text.includes('_cents'));assert(!text.includes('"price"'));}if(username==='cashier'){await q.evaluate(()=>goto('payroll'));await q.waitForLoadState('networkidle');await q.locator('[data-employee-banks]').click();await q.locator('[data-employee-bank-edit]').first().click();assert.equal(await q.locator('[data-employee-bank-save]').count(),0);assert.equal(await q.locator('#employee-bank-form input:not([readonly])').count(),0);}await q.close();}
 checks.push('厂长无银行卡入口且接口403；出纳银行卡只读；库管采购查询不返回价格、金额与账期');
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify({ok:true,checks,errors},null,2));console.log(JSON.stringify({ok:true,checks,errors}));
 }catch(e){console.error(e.stack||e);const p=browser?.contexts()[0]?.pages()[0];if(p){console.error(await p.locator('#dialog-error').textContent());await p.screenshot({path:path.join(out,'失败现场.png'),fullPage:true});}process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(temp,{recursive:true,force:true});}
})();
