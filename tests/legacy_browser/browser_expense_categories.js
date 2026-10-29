'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-outsource-')),db=path.join(temp,'test.db'),out=path.join(root,'output/外包配送费用清理-v0.62.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  cp.execFileSync('python3',['-c',`
import sqlite3,json,sys
con=sqlite3.connect(sys.argv[1])
base={'business_date':'2026-10-20','period':'2026-10','department':'配送','product_ids':[],'product_id':'','product_name':'','spread_months':1,'version':1,'voided':False,'created_at':'2026-10-20T10:00:00+08:00','role':'系统迁移','request_key':'history'}
wage={**base,'id':'EX-HIST-WAGE','category':'wages-delivery','amount_cents':500000,'partner':'厂内员工','reference':'HIST-WAGE','note':'历史配送工资，新入口已停用','handler':'测试','payment_mode':'payroll','counterparty_kind':'none','category_snapshot':{'id':'wages-delivery','name':'配送工资','payment_mode':'payroll','active':True},'accruals':[{'period':'2026-10','amount_cents':500000}]}
transport={**base,'id':'EX-HIST-TRANSPORT','category':'transport','amount_cents':62000,'partner':'旧运输方','reference':'YS-202610-OLD','source_document_id':'YS-202610-OLD','note':'历史运输月结自动生成','handler':'测试','payment_mode':'payable','counterparty_kind':'logistics','system_source':'transport-settlement','system_source_label':'运输月结','category_snapshot':{'id':'transport','name':'运输配送（油费+车损）','payment_mode':'payable','active':True},'accruals':[{'period':'2026-10','amount_cents':62000}]}
for key,row in [('hist-wage',wage),('hist-transport',transport)]:con.execute('INSERT INTO indirect_expenses VALUES(?,?,?)',(row['id'],key,json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'))))
con.commit();con.close()
`,db],{cwd:root});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;
  for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const go=async target=>{await p.evaluate(x=>goto(x),target);await ready();};
  const openCatalog=async()=>{const d=p.locator('details.report-disclosure').filter({hasText:'费用项目与属性维护'});if(!(await d.evaluate(e=>e.open)))await d.locator('summary').click();await p.waitForFunction(()=>document.querySelector('[data-cost-category-row]')?.closest('details').open);};
  await go('expenses');await p.evaluate(()=>{resourcesMonth='2026-10';render();});await ready();await openCatalog();
  assert.match(await p.locator('#content').innerText(),/配送已外包/);assert.equal(await p.locator('[data-cost-category-row="wages-delivery"]').locator('.badge').innerText(),'历史 / 停用');assert.match(await p.locator('[data-cost-category-row="wages-delivery"]').innerText(),/已有\s*1 笔费用引用/);assert.equal(await p.locator('[data-cost-category-row="transport"]').locator('.badge').innerText(),'系统自动');assert.match(await p.locator('[data-cost-category-row="transport"]').innerText(),/由运输月结生成/);assert.equal(await p.locator('[data-cost-category-row="transport"] [data-cost-delete]').count(),0);assert(await p.locator('[data-cost-delete="electricity"]').isDisabled());assert.match(await p.locator('[data-cost-category-row="electricity"]').innerText(),/不能删除/);
  checks.push('维护目录分开展示可新增、历史配送工资和系统外包配送费；有引用项目不能删除');
  await p.locator('[data-resource-act=expense]').first().click();const groups=await p.locator('#cost-expense-form [name=expense_group] option').evaluateAll(os=>os.map(o=>o.value)),seen=[];for(const g of groups){await p.locator('#cost-expense-form [name=expense_group]').selectOption(g);seen.push(...await p.locator('#cost-expense-form [name=category] option').evaluateAll(os=>os.map(o=>o.value)));}assert(!seen.includes('wages-delivery'));assert(!seen.includes('transport'));assert(seen.includes('electricity'));await p.locator('[data-act=close]').click();if(await p.locator('#leave-overlay').isVisible().catch(()=>false))await p.locator('[data-leave-choice=discard]').click();await p.waitForFunction(()=>document.getElementById('overlay').hidden);
  checks.push('普通新建只列可新增项目，配送工资与外包配送费均不出现');
  await p.locator('[data-cost-category=""]').click();await p.locator('#cost-category-form [name=name]').fill('浏览器待删项目');await p.locator('#cost-category-form [name=group]').fill('其他');await p.locator('[data-cost-save=category]').click();await p.waitForFunction(()=>document.getElementById('overlay').hidden);const custom=await p.evaluate(()=>resourceData().categories.find(c=>c.name==='浏览器待删项目'));assert(custom);
  await openCatalog();await p.locator(`[data-cost-delete="${custom.id}"]`).click();await p.locator(`[data-cost-delete-confirm="${custom.id}"]`).click();await p.waitForFunction(()=>document.getElementById('overlay').hidden);assert.equal(await p.evaluate(id=>resourceData().categories.some(c=>c.id===id),custom.id),false);
  await p.reload();await ready();await go('expenses');assert.equal(await p.evaluate(id=>resourceData().categories.some(c=>c.id===id),custom.id),false);
  checks.push('未引用自建项目可删除，刷新后不再出现');
  await p.evaluate(()=>{resourcesMonth='2026-10';render();});await ready();const text=await p.locator('#content').innerText();assert.match(text,/运输月结自动生成/);assert(text.includes('原单项目：运输配送'));assert.match(text,/历史配送工资/);assert.match(text,/生产 \/ 管理/);assert.match(text,/历史配送 5,000\.00/);
  checks.push('费用明细标明运输月结来源、原单项目快照和历史配送工资');
  for(const width of [1440,390,320]){await p.setViewportSize({width,height:950});await p.evaluate(()=>scrollTo(0,0));await p.waitForTimeout(180);assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),'页面横向溢出 '+width);await openCatalog();await p.screenshot({path:path.join(out,`费用项目维护-${width}.png`),fullPage:true});checks.push(`费用项目维护 ${width}px 无页面横向溢出`);}
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({ok:true,checks,errors},null,2)+'\n');console.log(JSON.stringify({ok:true,checks,errors}));
 }finally{if(browser)await browser.close();if(service){service.kill();if(service.exitCode===null&&service.signalCode===null)await new Promise(r=>service.once('exit',r));}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack);process.exit(1);});
