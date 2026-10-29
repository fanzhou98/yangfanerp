'use strict';
const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-byproduct-lazy-')),db=path.join(tmp,'test.db'),out=path.join(root,'output/豆渣历史裁剪-v0.71.0/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],checks=[],bootstraps=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  cp.execFileSync('python3',['-c',`
import json,sqlite3,sys
from datetime import date,timedelta
c=sqlite3.connect(sys.argv[1]);now=date.today();today=now.isoformat();prev=(now.replace(day=1)-timedelta(days=1)).isoformat()
c.execute("INSERT INTO customers(id,name,route,note,business_kind,delivery_method) VALUES(?,?,?,?,?,?)",('C-BP1','豆渣·测试客户','豆渣自取','按需历史验收','byproduct','pickup'))
def put(r):c.execute('INSERT INTO byproduct_sales(id,request_key,payload) VALUES(?,?,?)',(r['id'],r['id'],json.dumps(r)))
def sale(key,day,qty,amount,received):
 r=dict(id=key,version=1,business_date=day,customer_id='C-BP1',qty=qty,unit='公斤',price='0.5',amount_cents=amount,received_cents=received,buyer='豆渣·测试客户',reference='',note='按需历史验收',handler='测试',created_at=day+'T09:00:00+08:00',role='会计',receipts=[])
 if received:r['receipts'].append(dict(business_date=day,amount_cents=received,note='测试到账',at=day+'T10:00:00+08:00',role='会计'))
 put(r)
sale('BP-CURRENT',today,'100',5000,1000);sale('BP-PREVIOUS',prev,'120',6000,0)
c.commit();c.close()
`,db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;for(let i=0;i<120;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===119)throw Error('服务未启动');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(e.message));
    p.on('response',async r=>{if(new URL(r.url()).pathname==='/api/bootstrap'&&r.ok()){try{const v=await r.json(),mode=r.request().headers()['x-erp-byproduct-history']||'full';bootstraps.push({mode,byproducts:v.resources.byproducts.length,deferred:v.resources.byproduct_history_deferred});}catch{}}});
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  const ready=async()=>{await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);};
  const go=async target=>{await p.evaluate(x=>goto(x),target);await ready();};
  const day=await p.evaluate(()=>today()),month=day.slice(0,7),homeDay=await p.evaluate(()=>selectedDate||today());
  assert.equal(await p.evaluate(()=>data.resources.byproduct_history_deferred),true);assert.equal(await p.evaluate(()=>data.resources.byproducts.length),0);
  await go('byproducts');await p.waitForFunction(m=>factoryReports.get('byproduct-summary|'+m)?.value,month);await ready();
  await p.locator('[data-byproduct-view="customers"]').click();await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('累计未收'));await ready();const customerText=await p.locator('#content').innerText();
  assert.match(customerText,/本月销售/);assert.match(customerText,/¥\s*50\.00/);assert.match(customerText,/¥\s*100\.00/);checks.push('初始化不下发豆渣历史，客户档案本月销售与累计未收改由服务端汇总');
  await p.locator('[data-byproduct-view="ledger"]').click();await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('BP-CURRENT'));await ready();
  assert.match(await p.locator('#content').innerText(),/¥\s*50\.00/);assert.equal(await p.locator('[data-resource-act="receive"]').count(),1);
  await p.evaluate(()=>document.querySelector('[data-resource-act="receive"]').click());await p.locator('#resource-form').waitFor({state:'visible'});assert.equal(await p.locator('#resource-form [name=amount]').inputValue(),'40.00');await p.evaluate(()=>closeDialog());checks.push('豆渣台账按需分页，收款弹窗通过原单接口取到未收金额');
  await go('dashboard');await p.evaluate(d=>{selectedDate=d;render();},homeDay);await p.waitForFunction(m=>factoryReports.get('byproduct-summary|'+m)?.value,month);await ready();
  const work=await p.evaluate(async d=>{const t=homeTasks().find(t=>t.key==='byproducts.receive');return {today:t.today,carry:t.carry,samples:t.items.length,status:t.status};},homeDay);assert.equal(work.carry,1);assert.equal(work.today,1);assert.equal(work.status,'待处理');assert.equal(work.samples,2);checks.push('首页豆渣待收款提醒改用服务端汇总，历史欠款与当日到账分开计数');
  await go('ledger');await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('C-BP1'));await ready();
  await p.locator('[data-act="statement"][data-id="C-BP1"]').click();await p.locator('#dialog-body').waitFor({state:'visible'});await p.waitForFunction(()=>document.querySelector('#dialog-body')?.innerText.includes('BP-CURRENT'));assert.match(await p.locator('#dialog-body').innerText(),/豆渣/);await p.evaluate(()=>closeDialog());checks.push('应收台账客户对账按需读取豆渣销售并可打开原单');
  for(const width of [1440,390,320]){await p.setViewportSize({width,height:900});await go('byproducts');await p.locator('[data-byproduct-view="ledger"]').click();await p.waitForFunction(()=>document.querySelector('#content')?.innerText.includes('BP-CURRENT'));await p.evaluate(()=>{scrollTo(0,0);const t=document.querySelector('#toast');if(t){t.hidden=true;t.classList.remove('show');}});await p.waitForTimeout(100);assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`byproducts overflow ${width}`);await p.screenshot({path:path.join(out,`byproducts-${width}.png`),fullPage:true});}
  checks.push('豆渣收入在1440/390/320无整体横向溢出');
  assert(bootstraps.length>2);assert(bootstraps.every(r=>r.mode==='deferred'&&r.deferred&&r.byproducts===0));assert.deepEqual(errors,[]);const result={ok:true,checks,errors,bootstraps};fs.writeFileSync(path.join(out,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){console.error(e.stack||e);console.error(JSON.stringify({errors,bootstraps}));process.exitCode=1;}
 finally{await browser?.close();service?.kill();fs.rmSync(tmp,{recursive:true,force:true});}
})();
