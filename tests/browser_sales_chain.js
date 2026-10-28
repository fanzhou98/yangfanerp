const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-r02-')),db=path.join(temp,'test.db');
 const out=process.env.ERP_BROWSER_OUTPUT||path.join(root,'output/订单满足与回款联查-v0.61.0/浏览器验收');fs.mkdirSync(out,{recursive:true});
 let service,browser;const errors=[],checks=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'pipe'});
  cp.execFileSync('python3',['-c',`
import copy,json,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);base=json.loads(c.execute('SELECT payload FROM orders LIMIT 1').fetchone()[0])
for key,actual,state in [('R02-SHORT','580','reviewed'),('R02-EXCESS','620','reviewed'),('R02-PENDING','0','draft')]:
 o=copy.deepcopy(base);line=copy.deepcopy(o['lines'][0]);line.update(ordered_qty='600',actual_qty=actual,not_shipped=False,amount_cents=100000,bill_qty='550',billing_unit='公斤');o.update(id=key,version=2,business_date='2026-10-22',state=state,lines=[line],total_cents=100000 if state=='reviewed' else 0,paid_cents=30000 if key=='R02-SHORT' else 0,return_credit_cents=0,discount_cents=5000 if key=='R02-SHORT' else 0,rounding_cents=0,weight_confirmation=None,review_return=None,dispatch_required=False)
 c.execute('INSERT INTO orders VALUES(?,?)',(key,json.dumps(o)))
 if key=='R02-SHORT':
  c.execute('INSERT INTO receipts VALUES(?,?)',('R02-RECEIPT',json.dumps({'id':'R02-RECEIPT','order_id':key,'customer_id':o['customer_id'],'received_date':'2026-11-01','amount_cents':30000,'discount_cents':5000,'rounding_cents':0,'method':'测试银行','note':'跨月合成流水'})))
  correction={'id':'R02-CORR','order_id':key,'kind':'shipment','business_date':'2026-10-22','stock_anchor_date':None,'after':copy.deepcopy(o),'quantity_changes':[{'product_id':line['product_id'],'before_qty':'600','after_qty':'580','delta_qty':'-20'}],'reason':'R02合成少送核查','at':'2026-10-23T10:00:00+08:00'}
  c.execute('INSERT INTO order_corrections VALUES(?,?)',('R02-CORR',json.dumps(correction)))
  c.execute('INSERT INTO trade_records VALUES(?,?)',('R02-FB',json.dumps({'id':'R02-FB','kind':'feedback','order_id':key,'customer_id':o['customer_id'],'business_date':'2026-10-22','feedback_date':'2026-10-23','product_id':line['product_id'],'product_name':line['product_name'],'unit':line['unit'],'actual_qty':'600','received_qty':'580','difference_qty':'-20','source_order_version':1,'state':'pending','note':'R02次日反馈'})))
c.commit()
`,db],{cwd:root,stdio:'pipe'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;let healthy=false;
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok){healthy=true;break;}}catch{}await new Promise(r=>setTimeout(r,50));}assert(healthy);
  browser=await chromium.launch({channel:'chrome',headless:true});const p=await browser.newPage({viewport:{width:1440,height:1000}});p.setDefaultTimeout(15000);
  p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(m.text().includes('Content Security Policy'))errors.push(m.text());});
  const login=async(q,name)=>{await q.goto(base);await q.locator('[name=username]').fill(name);await q.locator('[name=password]').fill('Dashboard-Test-2026!');await q.locator('#auth-login-form [type=submit]').click();await q.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);await q.waitForLoadState('networkidle');};
  const ready=async(view='')=>{await p.waitForLoadState('networkidle');await p.waitForFunction(expected=>!!salesChainActive&&(!expected||salesTableView===expected)&&salesChainActive.view===salesTableView&&['customer_id','product_id','query','status'].every(k=>salesChainActive.filters[k]===salesChainFilters[k]),view);};
 const readyNonChain=async(view)=>{await p.waitForLoadState('networkidle');await p.waitForFunction(target=>salesTableView===target&&!!document.querySelector('[data-sales-page]'),view);};
  await login(p,'admin');await p.evaluate(()=>{factoryDay='2026-10-22';factoryMonth='2026-10';setSalesRange('2026-10-22','2026-10-22','day');salesTableView='fulfillment';goto('sales-daily');});await ready();
  await p.locator('[data-sales-chain-filter=query]').fill('R02-');await p.locator('[data-sales-chain-filter=query]').press('Tab');await ready();
  await p.waitForFunction(()=>salesChainActive?.summary.orders===3);
  assert.equal(await p.evaluate(()=>salesChainActive.summary.short_orders),1);assert.equal(await p.evaluate(()=>salesChainActive.summary.excess_orders),1);assert.equal(await p.evaluate(()=>salesChainActive.summary.pending_orders),1);
  checks.push('三张订单：少送、多送分别统计，草稿不计少送，分页汇总与行数一致');
  await p.locator('[data-sales-chain-order=R02-SHORT]').click();await p.waitForSelector('#dialog');let text=await p.locator('#dialog').innerText();assert(text.includes('600'));assert(text.includes('580'));assert(text.includes('2026-10-23'));assert(text.includes('2026-11-01'));assert(text.includes('R02-CORR'));
  await p.locator('#dialog [data-act=close]').click();checks.push('原单可查看订货与实发、次日反馈原快照、更正及跨月收款流水');
  await p.locator('[data-sales-chain-filter=status]').selectOption('short');await ready();await p.waitForFunction(()=>salesChainActive?.summary.orders===1);
  await p.locator('[data-sales-view=collection]').click();await ready('collection');assert.equal(await p.evaluate(()=>salesChainActive.summary.orders),3);
  assert.equal(await p.evaluate(()=>salesChainActive.rows.find(r=>r.order_id==='R02-SHORT').outstanding_cents),65000);
  checks.push('切换页签重置状态筛选；当前账款650元，待复核与未算不虚增应收');
  const product=await p.evaluate(()=>salesChainActive.rows.find(r=>r.order_id==='R02-SHORT').lines[0].product_id);
  await p.locator('[data-sales-chain-filter=product_id]').selectOption(product);await p.waitForFunction(id=>salesChainActive?.filters.product_id===id,product);await ready();assert((await p.locator('#content').innerText()).includes('金额仍是符合条件的整张订单'));
  const expectedTabs=[['fulfillment','订货与实发核对'],['collection','算票与收款进度'],['customers','客户销售与欠款'],['alerts','客户欠款提醒'],['products','产品销量汇总'],['markets','市场销量汇总'],['regions','地区销售汇总']];
  assert.deepEqual(await p.locator('[data-sales-view]').evaluateAll(buttons=>buttons.map(b=>[b.dataset.salesView,b.getAttribute('aria-label')])),expectedTabs);
  for(const width of [1440,390,320]){
   await p.setViewportSize({width,height:1000});await p.evaluate(()=>closeMobileNavigation());
   for(const [view,label] of expectedTabs){
    await p.locator(`[data-sales-view=${view}]`).click();
    if(['fulfillment','collection'].includes(view))await ready(view);
    else{await readyNonChain(view);}
    assert((await p.locator(`[data-sales-purpose=${view}]`).innerText()).includes(label));
    assert(!(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),`${view} ${width} 页面溢出`);
    const badLabels=await p.locator('.sales-report-tabs > button').evaluateAll(buttons=>buttons.filter(b=>{
      const box=b.getBoundingClientRect(),label=[...b.children].find(x=>getComputedStyle(x).display!=='none')||b;
      const range=document.createRange();range.selectNodeContents(label);const text=range.getBoundingClientRect();
      return text.left<box.left-1||text.right>box.right+1;
    }).map(b=>b.getAttribute('aria-label')||b.textContent));
    assert.deepEqual(badLabels,[],`页签文字不得挤出按钮 ${width}`);
    await p.screenshot({path:path.join(out,`${view}-${width}.png`),fullPage:true});
   }
   await p.locator('[data-sales-view=collection]').click();await ready('collection');
   await p.locator('[data-sales-chain-order=R02-SHORT]').click();await p.waitForSelector('#dialog');
   assert((await p.locator('#dialog').innerText()).includes('R02-RECEIPT'));
   await p.screenshot({path:path.join(out,`原单依据-${width}.png`),fullPage:true});await p.locator('#dialog [data-act=close]').click();
  }
  checks.push('七个页签名称、顺序及用途说明；1440/390/320宽度全部页签及原单弹窗通过，无页面或标签溢出');
  await p.setViewportSize({width:1440,height:1000});await p.emulateMedia({media:'print'});
  assert((await p.locator('#content').innerText()).includes('算票与收款进度明细'));
  assert.equal(await p.locator('[data-sales-chain-order]').count(),3);
  await p.screenshot({path:path.join(out,'打印当前筛选页.png'),fullPage:true});await p.emulateMedia({media:'screen'});
  checks.push('打印保留当前筛选页明细与整单金额口径');
  for(const name of ['warehouse','driver']){const ctx=await browser.newContext(),q=await ctx.newPage();await login(q,name);assert.equal(await q.evaluate(async()=>(await fetch('/api/factory/report?kind=sales-chain&date=2026-10-22')).status),403);await ctx.close();}
  checks.push('库管和司机不可绕过现有销售金额权限读取接口');assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({ok:true,checks,errors},null,2));console.log(JSON.stringify({ok:true,checks,errors}));
 }finally{if(browser)await browser.close();if(service&&service.exitCode===null&&service.signalCode===null){const done=new Promise(r=>service.once('exit',r));service.kill('SIGTERM');await done;}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack);process.exit(1);});
