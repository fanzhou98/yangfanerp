'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-finance-sql-')),db=path.join(temp,'test.db'),out=process.env.ERP_BROWSER_OUTPUT||path.join(root,'output/应收资金SQL下推-v'+fs.readFileSync(path.join(root,'VERSION'),'utf8').trim()+'/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[],responses=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  cp.execFileSync('python3',['-c',`
import json,sqlite3,sys
c=sqlite3.connect(sys.argv[1])
for t in ('orders','receipts','byproduct_sales','fund_accounts','fund_assignments','fund_transfers','purchase_payments','expense_payments','payroll_records','finished_goods_records','sales_returns'):c.execute('DELETE FROM '+t)
def put(t,r):
 cols=[x[1] for x in c.execute('PRAGMA table_info('+t+')')]
 if 'request_key' in cols:c.execute('INSERT INTO '+t+'(id,request_key,payload) VALUES(?,?,?)',(r['id'],r['id'],json.dumps(r)))
 else:c.execute('INSERT INTO '+t+' VALUES(?,?)',(r['id'],json.dumps(r)))
for i in range(2):put('fund_accounts',dict(id=f'FA-SQL{i}',name=f'SQL测试账户{i}',kind='银行账户',active=True,opening_date='2026-08-01',opening_balance_cents=100000 if i==0 else 0,version=1))
for i in range(125):
 day='2026-08-31' if i<50 else '2026-09-30' if i<100 else '2026-10-01'
 put('orders',dict(id=f'SQL-O{i:03d}',version=2,state='reviewed',business_date=day,customer_id='C001',customer_name='SQL测试客户',total_cents=10000,paid_cents=2000,return_credit_cents=0,discount_cents=0,rounding_cents=0,settlement={'at':'2026-10-20T00:00:00+08:00'},lines=[dict(product_id='P001',product_name='测试豆腐',unit='公斤',billing_unit='公斤',price='1',ordered_qty='100',actual_qty='100',bill_qty='100',amount_cents=10000)]))
 put('receipts',dict(id=f'SQL-R{i:03d}',order_id=f'SQL-O{i:03d}',received_date=day,amount_cents=2000,account_id='FA-SQL0',customer_name='SQL测试客户',method='银行转账',note='测试到账'))
put('byproduct_sales',dict(id='SQL-BQ',version=1,business_date='2026-07-31',created_at='2026-10-20T00:00:00+08:00',customer_id='C001',buyer='豆渣测试客户',qty='100',unit='公斤',price='1',amount_cents=10000,received_cents=3000,account_id='FA-SQL0',receipts=[dict(business_date='2026-10-02',amount_cents=2000,account_id='FA-SQL0',note='跨月豆渣到账')]))
put('expense_payments',dict(id='SQL-EQ',expense_id='SQL-EXPENSE',business_date='2026-10-02',amount_cents=500,payee='测试费用对象',note='待关联测试'))
put('fund_transfers',dict(id='SQL-TQ',business_date='2026-10-02',from_account_id='FA-SQL0',to_account_id='FA-SQL1',amount_cents=200,note='内部转账测试'))
c.commit();c.close()
`,db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===119)throw Error('测试服务未启动');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
  p.on('response',async r=>{if(r.url().includes('/api/receivables?')||r.url().includes('/api/fund-accounts?')){try{const v=await r.json();responses.push({url:r.url(),count:(v.rows||v.movements||[]).length});}catch{}}});
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const go=async target=>{await p.evaluate(x=>goto(x),target);await ready();};
  const cashCount=async n=>{await p.waitForFunction(n=>fundsCache?.value?.movement_total===n&&!fundsCache.loading,n);await ready();};
  const billCount=async n=>{await p.waitForFunction(n=>ledgerCache?.value?.total===n&&!ledgerCache.loading,n);await ready();};
  const range=async(start,end)=>{await p.locator('#funds-range-form [name=start]').fill(start);await p.locator('#funds-range-form [name=end]').fill(end);await p.locator('#funds-range-form button').click();await ready();};
  await p.evaluate(()=>fundsDate='2026-10-31');await go('fund-accounts');await cashCount(29);
  const baseline=await p.evaluate(()=>fundsCache.value.totals);assert.equal(baseline.balance_cents,352000);assert.equal(baseline.monthly_income_cents,52000);assert.equal(baseline.monthly_expense_cents,500);
  await p.locator('#funds-period').selectOption('custom');await range('2026-09-30','2026-10-01');await cashCount(75);
  assert.equal(await p.locator('[data-fund-action=assign]').count(),50);assert.equal(await p.evaluate(()=>fundsCache.value.flow_totals.income_cents),150000);assert.deepEqual(await p.evaluate(()=>fundsCache.value.totals),baseline);
  const first=await p.evaluate(()=>fundsCache.value.movements.map(r=>r.id));await p.locator('[data-funds-page="1"]').click();await p.waitForFunction(()=>fundsCache?.value?.movement_page===2);await ready();assert.equal(await p.locator('[data-fund-action=assign]').count(),25);const last=await p.evaluate(()=>fundsCache.value.movements.map(r=>r.id));assert.equal(new Set([...first,...last]).size,75);
  checks.push('资金跨月日期包含边界，75笔按50/25分页，范围汇总1500元且余额保持3520元');
  await p.locator('#funds-date').fill('2026-09-30');await cashCount(50);assert.equal(await p.evaluate(()=>fundsCache.value.totals.balance_cents),300000);
  await p.locator('#funds-date').fill('2026-10-31');await cashCount(75);
  await range('2026-10-02','2026-10-01');assert.equal(await p.evaluate(()=>fundsCache.value.movement_total),75);checks.push('统计截至日期独立于流水范围；错误起止日期保留上一份结果');
  await p.locator('#funds-direction').selectOption('out');await cashCount(0);assert.deepEqual(await p.evaluate(()=>fundsCache.value.totals),baseline);
  await p.locator('#funds-direction').selectOption('');await cashCount(75);
  await p.locator('[data-funds-pending]').click();await cashCount(1);await p.locator('[data-fund-action=assign]').click();await p.locator('#funds-form [name=account_id]').selectOption('FA-SQL1');await p.locator('#funds-form [name=note]').fill('核对临时合成流水');await p.locator('[data-funds-save]').click();await p.locator('#overlay').waitFor({state:'hidden'});await cashCount(0);assert.equal(await p.evaluate(()=>fundsCache.value.totals.balance_cents),351500);
  checks.push('空范围不改余额；SQL返回的流水指纹可用于原有账户关联写入，原款项金额不变');
  await go('ledger');await billCount(126);assert.equal(await p.locator('[data-receivable-order]').count(),50);
  const ids=[];for(let pageNumber=1;pageNumber<=3;pageNumber++){if(pageNumber>1){await p.locator(`[data-ledger-page=orders][data-ledger-target="${pageNumber}"]`).click();await p.waitForFunction(n=>ledgerCache?.value?.page===n,pageNumber);await ready();}ids.push(...await p.evaluate(()=>ledgerCache.value.rows.map(r=>r.id)));}assert.equal(new Set(ids).size,126);
  await p.evaluate(()=>{rangeMode=true;rangeStart='2026-10-20';rangeEnd='2026-10-20';rangeBasis='business_date';selectedDate='';render();});await billCount(0);
  await p.locator('#range-basis').selectOption('settled_date');await billCount(126);assert.equal(await p.evaluate(()=>ledgerCache.value.page),1);assert.match(await p.locator('#content').innerText(),/按算票确认日/);
  checks.push('应收SQL分页126笔无重复漏项；业务日期与算票确认日期分别筛选并重置页码');
  await go('fund-accounts');await p.locator('#funds-account').selectOption('');await p.locator('#funds-period').selectOption('custom');await range('2026-09-30','2026-10-01');await cashCount(75);
  for(const width of [1440,390,320]){await p.setViewportSize({width,height:900});await p.evaluate(()=>{scrollTo(0,0);const toast=document.querySelector('#toast');if(toast){toast.hidden=true;toast.classList.remove('show');}});await p.waitForTimeout(100);assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`资金页面横向溢出 ${width}`);await p.screenshot({path:path.join(out,`资金自定义日期-${width}.png`),fullPage:true});}
  checks.push('资金日期控件、范围汇总、分页在1440/390/320无整体横向溢出');
  assert(responses.length>10);assert(responses.every(r=>r.count<=50));assert.deepEqual(errors,[]);const result={ok:true,checks,errors,pagedResponses:responses};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){console.error(e.stack||e);console.error(JSON.stringify({errors}));process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(temp,{recursive:true,force:true});}
})();
