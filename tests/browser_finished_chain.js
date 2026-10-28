const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'..'),out=path.join(root,'output/供应商品类与外购库存链-v0.54.0/浏览器验收');
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-finished-chain-')),db=path.join(temp,'synthetic.db');let service,browser;
 fs.mkdirSync(out,{recursive:true});const checks=[],errors=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});}),base=`http://127.0.0.1:${port}`;
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const login=async name=>{const ctx=await browser.newContext({viewport:{width:1440,height:1000}}),p=await ctx.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>errors.push(name+': '+e.message));p.on('response',async r=>{if(r.status()>=400&&r.url().includes('/api/'))console.error('API ERROR',r.url(),await r.text());});p.on('dialog',d=>d.accept());await p.goto(base);await p.locator('[name=username]').fill(name);await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&!!data?.auth_user);return p;};
  const go=async(p,page)=>{await p.evaluate(page=>{selectedDate='2026-10-28';goto(page);},page);await p.waitForFunction(target=>page===target&&!navigationLoading,page);await p.waitForLoadState('networkidle');};
  const api=async(p,endpoint,body)=>p.evaluate(({endpoint,body})=>api(endpoint,body),{endpoint,body});
  const close=async p=>{await p.evaluate(()=>{dialogBaseline='';closeDialog();});};
  const admin=await login('admin');
  // Set up categories through the actual category editor.
  await go(admin,'suppliers');await admin.locator('[data-purchase-act=categories]').click();await admin.locator('[data-category-edit=""]').click();await admin.locator('#supplier-category-form [name=name]').fill('配送成品');await admin.locator('#supplier-category-form [name=kind]').selectOption('finished');await admin.locator('[data-category-save]').click();await admin.locator('#supplier-category-search').waitFor();await close(admin);
  const cats=(await api(admin,'/api/bootstrap')).purchasing.categories,custom=cats.find(c=>c.name==='配送成品');assert(custom);
  await api(admin,'/api/purchasing/supplier',{name:'测试纯原料商',category_ids:['SC-RAW']});
  await admin.locator('[data-purchase-act=supplier]').click();await admin.locator('#purchase-form [name=name]').fill('成品综合供货商');await admin.locator('#purchase-form [name=category_ids][value="'+custom.id+'"]').check();await admin.locator('[data-purchase-act=save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});
  const s=(await api(admin,'/api/bootstrap')).purchasing.suppliers.find(s=>s.name==='成品综合供货商');
  await api(admin,'/api/master',{kind:'product',create:true,id:'EXT','name':'外购验收产品','unit':'盒','billing_unit':'盒',price:'3',tare:'0',supply_kind:'purchased',supplier_ids:[s.id]});
  await api(admin,'/api/master',{kind:'product',create:true,id:'MIX','name':'自产外购产品','unit':'盒','billing_unit':'盒',price:'3',tare:'0',main_material:'黄豆',supply_kind:'mixed',supplier_ids:[s.id]});
  const customer=(await api(admin,'/api/bootstrap')).customers.find(c=>c.business_kind!=='byproduct');
  await api(admin,'/api/orders',{customer_id:customer.id,workflow_version:1,business_date:'2026-10-28',batch:'日常',lines:[{product_id:'EXT',ordered_qty:'10',actual_qty:'0',price:'3',driver:[],customer:[]}]});
  await api(admin,'/api/fund-accounts',{action:'account',name:'采购付款银行户',kind:'银行账户',opening_date:'2026-10-28',opening_balance:'100',note:'测试期初',request_key:'browser-bank'});
  checks.push('供货品类新增、多选供应商与产品自产＋外购配置');
  const warehouse=await login('warehouse');await go(warehouse,'allocation');
  assert(await warehouse.locator('[data-stock=EXT][data-field=produced_qty]').isDisabled());assert(await warehouse.locator('[data-stock=MIX][data-field=produced_qty]').isEnabled());
  // Keep an unsaved ordinary stock cell while posting the external receipt.
  await warehouse.locator('[data-stock=MIX][data-field=produced_qty]').fill('2');
  await warehouse.locator('[data-stock-goods=EXT]').click();await warehouse.locator('[data-goods-new=EXT]').click();
  assert.deepEqual(await warehouse.locator('#goods-stock-form [name=supplier_id] option').allTextContents(),['成品综合供货商']);
  await warehouse.locator('[data-goods-fill]').click();assert.equal(await warehouse.locator('[name=expected_qty]').inputValue(),'10');assert.equal(await warehouse.locator('#goods-stock-form [name=qty]').inputValue(),'10');
  await warehouse.locator('#goods-stock-form [name=qty]').fill('8');await warehouse.locator('#goods-stock-form [name=note]').fill('订10实收8，余2待补');await warehouse.locator('#goods-stock-form [name=handler]').fill('测试库管');await warehouse.locator('[data-goods-stock-save]').click();await warehouse.locator('#overlay').waitFor({state:'hidden'}).catch(async e=>{console.error(await warehouse.locator('#dialog').innerText());console.error(await warehouse.locator('#goods-stock-form').evaluate(f=>[...f.elements].filter(e=>e.willValidate&&!e.validity.valid).map(e=>({name:e.name,value:e.value,error:e.validationMessage}))));throw e;});
  assert.equal(await warehouse.locator('[data-stock=MIX][data-field=produced_qty]').inputValue(),'2');
  const safe=await api(warehouse,'/api/bootstrap'),r=safe.finished_goods_inventory.receipts[0],o=safe.finished_goods_inventory.orders[0];assert.equal(o.remaining_qty,'2');assert(!JSON.stringify(safe.finished_goods_inventory).includes('amount_cents'));
  assert.equal(await warehouse.locator('[data-stock-total=EXT]').textContent(),'待盘点');
  await warehouse.screenshot({path:path.join(out,'库存独立外购列.png'),fullPage:true});
  await warehouse.locator('[data-stock-goods=EXT]').click();await warehouse.locator('[data-goods-continue="'+o.id+'"]').click();await warehouse.locator('#goods-stock-form [name=qty]').fill('2');await warehouse.locator('#goods-stock-form [name=note]').fill('漏发2盒补到');await warehouse.locator('#goods-stock-form [name=handler]').fill('测试库管');await warehouse.locator('[data-goods-stock-save]').click();await warehouse.locator('#overlay').waitFor({state:'hidden'}).catch(async e=>{console.error(await warehouse.locator('#dialog').innerText());console.error(await warehouse.locator('#goods-stock-form').evaluate(f=>[...f.elements].filter(e=>e.willValidate&&!e.validity.valid).map(e=>({name:e.name,value:e.value,error:e.validationMessage}))));throw e;});
  assert.equal((await api(warehouse,'/api/bootstrap')).finished_goods_inventory.orders[0].remaining_qty,'0');checks.push('库管无金额权限登记、一键填订货量、漏发补到及未保存盘点保留');
  const accountant=await login('accountant');await go(accountant,'settlements');await accountant.locator('[data-accounting-book=purchase]').click();await accountant.locator('[data-goods-price="'+r.id+'"]').waitFor();
  await accountant.locator('[data-goods-price="'+r.id+'"]').click();await accountant.locator('#goods-stock-form [name=price]').fill('2');await accountant.locator('#goods-stock-form [name=evidence_checked]').check();await accountant.locator('#goods-stock-form [name=note]').fill('核对本笔订单单价2元');await accountant.locator('[data-goods-stock-save]').click();await accountant.locator('#overlay').waitFor({state:'hidden'});
  await accountant.locator('#goods-accounting-status').selectOption('all');await accountant.locator('[data-goods-reprice="'+r.id+'"]').waitFor();
  const second=(await api(accountant,'/api/finished-goods?month=2026-10')).receipts.find(x=>x.id!==r.id);
  await accountant.locator('[data-goods-price="'+second.id+'"]').click();await accountant.locator('#goods-stock-form [name=price]').fill('3');await accountant.locator('#goods-stock-form [name=evidence_checked]').check();await accountant.locator('#goods-stock-form [name=note]').fill('本笔补到按3元确认');await accountant.locator('[data-goods-stock-save]').click();await accountant.locator('#overlay').waitFor({state:'hidden'});
  await accountant.screenshot({path:path.join(out,'外购逐笔每日算票.png'),fullPage:true});
  const cashier=await login('cashier');await go(cashier,'payables');await cashier.locator('[data-goods-view=finished]').click();await cashier.locator('[data-finished-open=payment][data-id="'+r.id+'"]').click();await cashier.locator('#finished-form [name=business_date]').fill('2026-10-28');await cashier.locator('#finished-form [name=account_id]').selectOption({label:'采购付款银行户 · 银行账户'});await cashier.locator('#finished-form [name=note]').fill('付款16元账户核对');await cashier.locator('[data-finished-save]').click();await cashier.locator('#overlay').waitFor({state:'hidden'});
  let report=await api(admin,'/api/fund-accounts?date=2026-10-28');assert.equal(report.accounts.find(a=>a.name==='采购付款银行户').balance_cents,8400);checks.push('每日订单分别定价并确认、付款对应资金账户');
  await accountant.evaluate(async()=>{data=await api('/api/bootstrap');finishedCache=null;render();});await accountant.locator('[data-goods-reprice="'+r.id+'"]').click();await accountant.locator('#goods-stock-form [name=note]').fill('供应商确认本笔应1.5元');await accountant.locator('[data-goods-stock-save]').click();await accountant.locator('#overlay').waitFor({state:'hidden'});
  await accountant.locator('[data-goods-price="'+r.id+'"]').click();await accountant.locator('#goods-stock-form [name=price]').fill('1.5');assert((await accountant.locator('#goods-price-preview').textContent()).includes('-4'));await accountant.locator('#goods-stock-form [name=evidence_checked]').check();await accountant.locator('#goods-stock-form [name=note]').fill('重算减少4元保留原付款');await accountant.locator('[data-goods-stock-save]').click();await accountant.locator('#overlay').waitFor({state:'hidden'});
  await cashier.evaluate(async()=>{finishedCache=null;await refresh();});await cashier.locator('[data-goods-refund="'+r.id+'"]').click();await cashier.locator('#goods-stock-form [name=business_date]').fill('2026-10-28');await cashier.locator('#goods-stock-form [name=account_id]').selectOption({label:'采购付款银行户 · 银行账户'});await cashier.locator('#goods-stock-form [name=note]').fill('供应商退回多付4元');await cashier.locator('[data-goods-stock-save]').click();await cashier.locator('#overlay').waitFor({state:'hidden'});
  report=await api(admin,'/api/fund-accounts?date=2026-10-28');assert.equal(report.accounts.find(a=>a.name==='采购付款银行户').balance_cents,8800);checks.push('已付款订单退回重算、差额预览、供应商退款入账');
  await go(admin,'factory');await admin.waitForLoadState('networkidle');
  const cards=await admin.locator('.panel .factory-system-overview').evaluateAll(grids=>grids.map(g=>{const r=g.getBoundingClientRect(),p=g.closest('.panel').getBoundingClientRect();return {left:r.left-p.left,padding:getComputedStyle(g).paddingLeft,width:g.querySelector('.grinding-system-card')?.getBoundingClientRect().width};}));assert(cards.length);assert(cards.every(c=>Number.parseFloat(c.padding)>=16&&c.width<=311));
  await admin.screenshot({path:path.join(out,'上豆浆缸紧凑留白.png'),fullPage:true});
  await accountant.setViewportSize({width:390,height:844});await accountant.screenshot({path:path.join(out,'外购算票手机.png'),fullPage:true});assert(await accountant.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await admin.setViewportSize({width:390,height:844});await admin.screenshot({path:path.join(out,'上豆手机留白.png'),fullPage:true});assert(await admin.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  checks.push('上豆卡片左右留白、紧凑宽度与手机版无整体溢出');assert.deepEqual(errors,[]);
  const result={ok:true,checks,roles:['管理员','库管','会计','出纳'],browser_errors:errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{if(browser)await browser.close();if(service){service.kill();await new Promise(resolve=>service.once('exit',resolve));}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack);process.exit(1);});
