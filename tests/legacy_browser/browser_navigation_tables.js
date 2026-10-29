const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'..'),output=process.env.ERP_BROWSER_OUTPUT||path.join(root,'output/供应商品类与外购库存链-v0.54.0/全页面核对'),quick=process.env.ERP_BROWSER_QUICK==='1';
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-nav-tables-')),db=path.join(temp,'synthetic.db');let service,browser;
 fs.mkdirSync(output,{recursive:true});
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const port=s.address().port;s.close(()=>resolve(port));});}),base=`http://127.0.0.1:${port}`;
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(i===99)throw Error('测试服务未就绪');await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const errors=[],roles=[],audit=[];
  const login=async username=>{
   const context=await browser.newContext({viewport:{width:1440,height:1000}}),p=await context.newPage();
   p.setDefaultTimeout(12000);p.on('pageerror',e=>{errors.push(username+': '+e.message);console.error('Browser error: '+e.message);});
   await p.goto(base);await p.locator('[name=username]').fill(username);await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();
   await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user&&page==='dashboard'&&document.querySelector('.sidebar [data-module-id]'));
   return p;
  };
  const go=async(p,m)=>{await p.evaluate(m=>{selectedDate='2026-10-20';factoryDay=selectedDate;if(m.view)masterView=m.view;goto(m.page);},m);await p.waitForFunction(m=>page===m.page&&!navigationLoading,m);await p.waitForLoadState('networkidle');await p.waitForFunction(()=>{const text=document.querySelector('#content')?.innerText||'';if(/正在读取|正在加载/.test(text))return false;if(typeof factoryReports!=='undefined'&&[...factoryReports.values()].some(r=>r.loading))return false;if(page==='fund-accounts'&&(!fundsCache?.value||fundsCache.loading))return false;if(page==='ledger'&&(!ledgerCache?.value||ledgerCache.loading))return false;return true;});assert.equal(await p.locator('#content [data-read-retry]').count(),0,m.page+' 查询无读取错误 '+await p.locator('.read-state-error').allTextContents());};
  const inspect=async(p,label,scope='#content')=>{
   const result=await p.evaluate(scope=>{
    const issues=[];let tables=0,cells=0,notes=0;
    for(const table of document.querySelectorAll(scope+' table')){
     if(!table.getClientRects().length)continue;tables++;
     for(const cell of table.querySelectorAll('th,td')){
      if(!cell.getClientRects().length||getComputedStyle(cell).display==='none')continue;
      cells++;const expected=cell.tagName==='TH'?'center':cell.dataset.align||'center',style=getComputedStyle(cell);
      if(expected==='left')notes++;
      if(style.textAlign!==expected||style.verticalAlign!=='middle')issues.push({text:cell.textContent.trim().slice(0,35),expected,actual:style.textAlign,vertical:style.verticalAlign});
      for(const input of cell.querySelectorAll('input:not([type=checkbox]):not([type=radio]),select'))if(input.getClientRects().length&&getComputedStyle(input).textAlign!==expected)issues.push({input:input.name||input.getAttribute('aria-label'),expected,actual:getComputedStyle(input).textAlign});
     }
    }
    for(const label of document.querySelectorAll(scope+' .sheet-filters label:has(input[type=checkbox])')){
     if(!label.getClientRects().length)continue;
     const input=label.querySelector('input'),style=getComputedStyle(label);
     if(style.flexDirection!=='row'||input.getBoundingClientRect().height>22)issues.push({filter:label.textContent.trim(),direction:style.flexDirection,inputHeight:input.getBoundingClientRect().height});
    }
    for(const actions of document.querySelectorAll(scope+' .head-actions')){
     if(!actions.getClientRects().length)continue;
     const buttons=[...actions.querySelectorAll(':scope>button.button')].filter(b=>b.getClientRects().length);
     for(let i=0;i<buttons.length;i++)for(let j=i+1;j<buttons.length;j++){
      const a=buttons[i].getBoundingClientRect(),b=buttons[j].getBoundingClientRect();
      if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)issues.push({buttonsOverlap:[buttons[i].textContent,buttons[j].textContent]});
     }
    }
    return {tables,cells,notes,issues,overflow:document.documentElement.scrollWidth>innerWidth+1};
   },scope);
   audit.push({label,...result});assert.deepEqual(result.issues,[],label+' alignment');assert.equal(result.overflow,false,label+' 页面整体横向溢出');
  };
  const admin=await login('admin');
  for(const username of quick?['admin']:['admin','warehouse','accountant','cashier','owner','director','logistics','driver']){
   if(process.env.ERP_BROWSER_PROGRESS)console.log('检查岗位 '+username);
   const p=username==='admin'?admin:await login(username);
   const state=await p.evaluate(()=>{
    const expected=navigationModel(data.access_catalog),buttons=[...document.querySelectorAll('.sidebar [data-module-id]')],ids=buttons.map(b=>b.dataset.moduleId);
    return {ids,expected:[expected.overview,expected.reportMap,...expected.shortcuts,...expected.sections.flatMap(s=>s.modules)].filter(Boolean).map(m=>m.id),overview:expected.overview?.id,top:document.querySelector('#workspace-shortcuts [data-module-id]')?.dataset.moduleId,duplicates:ids.filter((id,i)=>ids.indexOf(id)!==i),sections:expected.sections.map(s=>s.id),text:document.querySelector('.sidebar').innerText};
   });
   assert.deepEqual(state.duplicates,[],username);assert.deepEqual([...state.ids].sort(),[...state.expected].sort(),username+' 入口完整');
   assert.equal(state.top,'workspace.dashboard',username+' 工作台紧凑置顶');
   assert(!state.text.includes('功能总览')&&!state.text.includes('功能导航'),username+' 移除功能总览入口');
   roles.push({username,entries:state.ids.length,sections:state.sections});
   if(username!=='admin')await p.context().close();
  }
  await admin.locator('[data-nav-toggle=sales]').click();
  assert.equal(await admin.locator('[data-nav-toggle][aria-expanded=true]').count(),1,'首次展开不影响其他组');
  await admin.locator('#nav [data-page=orders]').click();await admin.waitForFunction(()=>page==='orders'&&!navigationLoading);
  await admin.locator('[data-nav-toggle=sales]').click();assert.equal(await admin.locator('[data-nav-toggle=sales]').getAttribute('aria-expanded'),'false','当前组也可主动折叠');
  await admin.locator('[data-nav-toggle=sales]').click();
  await admin.screenshot({path:path.join(output,'导航-电脑.png'),fullPage:true});
  await admin.locator('#sidebar-toggle').click();
  assert.equal(await admin.locator('.sidebar').evaluate(el=>el.getBoundingClientRect().width),76);
  const compact=await admin.locator('.sidebar [data-module-id]').evaluateAll(elements=>elements.every(el=>{const box=el.getBoundingClientRect(),icon=el.querySelector('svg').getBoundingClientRect();return icon.left>=box.left-1&&icon.right<=box.right+1;}));assert(compact,'紧凑导航图标不越界');
  await admin.locator('#nav [data-page=orders]').hover();await admin.locator('#navigation-flyout').waitFor({state:'visible'});assert.equal(await admin.locator('#navigation-flyout').innerText(),'订货管理');
  await admin.screenshot({path:path.join(output,'导航-收起.png'),fullPage:true});await admin.locator('#sidebar-toggle').click();
  const modules=await admin.evaluate(()=>data.access_catalog.modules.filter(moduleVisible).filter(m=>!['workspace.dashboard','workspace.directory','workspace.product-profit','delivery.driver'].includes(m.id)));
  for(const m of quick?[]:modules){if(process.env.ERP_BROWSER_PROGRESS)console.log('检查页面 '+m.id);await go(admin,m);await inspect(admin,m.id);}
  assert.equal(await admin.locator('.sidebar [data-page=directory]').count(),0);
  const topHeight=await admin.locator('#workspace-shortcuts [data-module-id]').first().evaluate(el=>el.getBoundingClientRect().height);assert(topHeight<=44,'工作台不使用放大卡片');
  assert.equal(await admin.locator('.sidebar').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 255)');
  await go(admin,{page:'masters',view:'pricing'});
  await admin.evaluate(async()=>{
   const c=data.customers[0],p=data.products[0],rule=data.rules.find(r=>r.customer_id===c.id&&r.product_id===p.id);
   await api('/api/master',{kind:'rule',customer_id:c.id,product_id:p.id,price:String(Number(p.price)+1),tare:p.tare,expected:rule?{price:rule.price,tare:rule.tare}:null});
   data=await api('/api/bootstrap');pricingDrafts.clear();render();
  });
  assert(await admin.locator('.pricing-matrix .pricing-reset').count()>0,'同时检查专属价和默认价单元格');
  const priceGeometry=await admin.locator('.pricing-matrix .grid-input').evaluateAll(inputs=>inputs.map(input=>{const cell=input.closest('td').getBoundingClientRect(),box=input.getBoundingClientRect();return {x:Math.abs(box.left+box.width/2-cell.left-cell.width/2),y:Math.abs(box.top+box.height/2-cell.top-cell.height/2)};}));
  await admin.screenshot({path:path.join(output,'客户专属价格-电脑.png'),fullPage:true});
  assert(priceGeometry.length>0);assert(priceGeometry.every(g=>g.x<=1&&g.y<=1),'专属价格输入框水平垂直居中 '+JSON.stringify(priceGeometry));
  const resetCenter=await admin.locator('.pricing-reset').first().evaluate(button=>{const a=button.getBoundingClientRect(),b=button.closest('td').getBoundingClientRect();return Math.abs(a.left+a.width/2-b.left-b.width/2);});assert(resetCenter<=1,'恢复默认按钮也应居中');
  await inspect(admin,'pricing-price');
  await admin.locator('[data-price-mode=tare]').click();await admin.waitForFunction(()=>pricingMode==='tare'&&!navigationLoading);await inspect(admin,'pricing-tare');
  await admin.locator('[data-price-mode=price]').click();await admin.waitForFunction(()=>pricingMode==='price'&&!navigationLoading);
  const input=admin.locator('.pricing-matrix .grid-input:not(:disabled)').first(),original=await input.inputValue();await input.fill(String(Number(original)+1));
  await admin.locator('.workspace-shortcut[data-page=analytics]').click();await admin.locator('#leave-overlay').waitFor({state:'visible'});await admin.locator('[data-leave-choice=stay]').click();assert.equal(await input.inputValue(),String(Number(original)+1),'导航保留未保存保护');
  await admin.locator('.workspace-shortcut[data-page=analytics]').click();await admin.locator('[data-leave-choice=discard]').click();await admin.waitForFunction(()=>page==='analytics'&&!navigationLoading);
  await admin.evaluate(()=>openDialog('表格对齐验收','<table id="qa-table"><thead><tr><th rowspan="2">客户</th><th colspan="2">业务</th></tr><tr><th>金额</th><th>备注与说明</th></tr></thead><tbody><tr><td rowspan="2">客户甲</td><td><input value="100"></td><td>需要左对齐的较长备注<table><thead><tr><th>数量</th><th>备注</th></tr></thead><tbody><tr><td>5</td><td>内嵌表说明</td></tr></tbody></table></td></tr><tr><td>200</td><td>第二条说明</td></tr></tbody></table>'));
  await inspect(admin,'dialog-multi-header','#dialog-body');
  await admin.evaluate(()=>document.querySelector('#qa-table tbody').insertAdjacentHTML('beforeend','<tr><td>客户乙</td><td>300</td><td id="dynamic-note">动态追加的备注</td></tr>'));
  await admin.waitForFunction(()=>document.querySelector('#dynamic-note').dataset.align==='left');await inspect(admin,'dialog-dynamic-row','#dialog-body');await admin.evaluate(()=>closeDialog());
  await go(admin,{page:'byproducts'});
  await admin.locator('[data-byproduct-customer-new]').click();
  await admin.locator('#customer-form [name=name]').fill('豆渣验收购货方');
  await admin.locator('#customer-form [name=phone]').fill('123456789');
  await admin.locator('#customer-form [name=legal_name]').fill('豆渣验收养殖场');
  await admin.locator('[data-act=save-customer]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!busy);
  const beanCid=await admin.evaluate(()=>byproductCustomers().find(c=>c.name==='豆渣验收购货方').id);
  await go(admin,{page:'system-settings'});
  await admin.locator('[data-parameter-tab=byproducts]').click();
  await admin.locator('[data-byproduct-settings-edit]').click();
  await admin.locator('#byproduct-settings-form [name=customer_id]').selectOption(beanCid);
  await admin.locator('#byproduct-settings-form [name=basis]').selectOption('converted');await admin.locator('#byproduct-settings-form [name=yield_ratio]').fill('1');
  await admin.locator('#byproduct-settings-form [name=add_kg]').fill('10');
  await admin.locator('[data-byproduct-settings-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!busy);
  await go(admin,{page:'byproducts'});
  await admin.locator('[data-byproduct-price-open]').waitFor();
  assert(!(await admin.locator('#content').innerText()).includes('加量'));
  const business=await admin.evaluate(()=>api('/api/byproduct-settlement?month=2026-10'));assert(!JSON.stringify(business).includes('add_kg'));assert(!JSON.stringify(business).includes('bean_kg'));
  await admin.locator('[data-byproduct-price-open]').click();await admin.locator('#byproduct-price').fill('0.5');await admin.locator('[data-byproduct-price-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});
  await admin.waitForFunction(()=>byproductSettleCache?.value?.price==='0.5'&&!busy);
  await admin.locator('[data-byproduct-settle]').click();await admin.waitForFunction(()=>!!byproductSettleCache?.value?.settlement&&!busy);
  await inspect(admin,'byproduct-daily');await admin.locator('#toast').evaluate(el=>{el.hidden=true;el.classList.remove('show');});await admin.screenshot({path:path.join(output,'豆渣每日结算-电脑.png'),fullPage:true,animations:'disabled'});
  await admin.locator('[data-byproduct-view=ledger]').click();await admin.waitForFunction(()=>byproductView==='ledger'&&!navigationLoading);await inspect(admin,'byproduct-ledger');assert(!(await admin.locator('#content').innerText()).includes('加量'));
  const beanSale=await admin.evaluate(async cid=>(await api('/api/byproduct-sales?'+new URLSearchParams({customer_id:cid}))).rows.find(r=>!r.voided),beanCid);
  assert(beanSale&&beanSale.amount_cents>1000);
  await admin.locator('[data-byproduct-view=customers]').click();await admin.waitForFunction(()=>byproductView==='customers'&&!navigationLoading);
  await inspect(admin,'byproduct-customers');await admin.screenshot({path:path.join(output,'豆渣客户档案-电脑.png'),fullPage:true});
  await admin.locator(`[data-byproduct-statement][data-cid="${beanCid}"]`).click();
  await admin.waitForFunction(()=>!!byproductStatementState?.draft);
  assert.equal(await admin.locator('#statement-seller').inputValue(),await admin.evaluate(()=>data.company.name));
  await admin.locator('#byproduct-statement-form [name=identity_checked]').check();
  await admin.locator('[data-byproduct-statement-issue]').click();await admin.waitForFunction(()=>statementShownDocument.startsWith('BZ-')&&!busy);
  const beanDocId=await admin.evaluate(()=>statementShownDocument);
  const imageCount=await admin.locator('[data-statement-download]').count();assert(imageCount>=2,'每日完整展示时正确分页');
  for(let i=0;i<imageCount;i++){const pngDownload=admin.waitForEvent('download');await admin.locator('[data-statement-download]').nth(i).click();await (await pngDownload).saveAs(path.join(output,`豆渣客户结算单-第${i+1}页.png`));}
  const csvDownload=admin.waitForEvent('download');await admin.locator('a[download][href$=".csv"]').click();await (await csvDownload).saveAs(path.join(output,'豆渣客户结算单.csv'));
  assert(!fs.readFileSync(path.join(output,'豆渣客户结算单.csv'),'utf8').includes('加量'));
  await admin.screenshot({path:path.join(output,'豆渣结算单导出-电脑.png'),fullPage:true});
  await admin.locator('#dialog-close').click();await admin.locator('#overlay').waitFor({state:'hidden'});
  await admin.locator(`[data-byproduct-receivable="${beanCid}"]`).click();await admin.waitForFunction(()=>page==='ledger'&&!navigationLoading);
  await admin.waitForFunction(id=>ledgerCache?.value?.rows.some(r=>r.id===id),beanSale.id);
  const arBefore=await admin.evaluate(()=>({ids:ledgerCache.value.rows.map(r=>r.id),remaining:ledgerCache.value.summary.outstanding_cents}));
  assert.deepEqual(arBefore.ids,[beanSale.id]);assert.equal(arBefore.remaining,beanSale.amount_cents);
  await admin.locator(`[data-resource-act=receive][data-id="${beanSale.id}"]`).click();
  await admin.locator('#resource-form [name=business_date]').fill('2026-10-31');await admin.locator('#resource-form [name=amount]').fill('10');await admin.locator('#resource-form [name=note]').fill('演示转账收款');
  await admin.locator('[data-resource-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!busy);
  await admin.waitForFunction(expected=>ledgerCache?.value?.summary.outstanding_cents===expected,beanSale.amount_cents-1000);
  assert.equal(await admin.evaluate(()=>ledgerCache.value.summary.outstanding_cents),beanSale.amount_cents-1000);
  await inspect(admin,'byproduct-receivables');await admin.screenshot({path:path.join(output,'豆渣纳入应收-电脑.png'),fullPage:true});
  const archived=await admin.evaluate(id=>api('/api/byproduct-documents/'+id),beanDocId);assert.equal(archived.totals.payable_cents,beanSale.amount_cents,'收款不改写原结算单');
  await admin.locator(`[data-byproduct-statement][data-cid="${beanCid}"]`).first().click();await admin.waitForFunction(()=>!!byproductStatementState?.draft);
  assert.equal(await admin.evaluate(()=>byproductStatementState.draft.totals.payable_cents),beanSale.amount_cents-1000);
  await admin.locator('#byproduct-statement-archive').selectOption(beanDocId);await admin.waitForFunction(id=>statementShownDocument===id,beanDocId);
  assert.equal(await admin.locator('#statement-seller').isDisabled(),true);
  await admin.locator('#dialog-close').click();await admin.locator('#overlay').waitFor({state:'hidden'});
  await admin.evaluate(()=>{ledgerSource='all';ledgerCustomer='';ledgerClearance='open';byproductView='ledger';});
  await go(admin,{page:'fund-accounts'});await admin.waitForFunction(()=>!!fundsCache?.value);
  await admin.locator('#funds-date').fill('2026-10-31');await admin.waitForFunction(()=>fundsCache?.value?.as_of==='2026-10-31');
  const newAccount=async(name,balance,kind='银行账户')=>{
   await admin.locator('.page-head [data-fund-action=account]').click();
   await admin.locator('#funds-form [name=name]').fill(name);await admin.locator('#funds-form [name=kind]').selectOption(kind);await admin.locator('#funds-form [name=opening_date]').fill('2026-10-01');await admin.locator('#funds-form [name=opening_balance]').fill(balance);
   await admin.locator('[data-funds-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!!fundsCache?.value&&!busy);
   return admin.evaluate(name=>fundsCache.value.accounts.find(a=>a.name===name).id,name);
  };
  const bank=await newAccount('演示基本户','1000'),cash=await newAccount('演示现金','100','现金'),unused=await newAccount('演示待删账户','0');
  await admin.locator(`[data-fund-action=delete][data-id="${unused}"]`).click();await admin.locator('[data-funds-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(id=>!!fundsCache?.value&&!fundsCache.value.accounts.some(a=>a.id===id),unused);
  const beanMovement=await admin.evaluate(id=>fundsCache.value.movements.find(m=>m.id.startsWith('byproduct:'+id)&&m.amount_cents===1000),beanSale.id);assert(beanMovement);
  await admin.locator(`[data-fund-action=assign][data-id="${beanMovement.id}"]`).click();await admin.locator('#funds-form [name=account_id]').selectOption(bank);await admin.locator('#funds-form [name=note]').fill('核对演示收款凭据');await admin.locator('[data-funds-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!!fundsCache?.value&&!busy);
  const beforeTransfer=await admin.evaluate(()=>fundsCache.value.totals);assert.equal(beforeTransfer.balance_cents,111000);
  await admin.locator('[data-fund-action=transfer]').click();await admin.locator('#funds-form [name=from_account_id]').selectOption(bank);await admin.locator('#funds-form [name=to_account_id]').selectOption(cash);await admin.locator('#funds-form [name=business_date]').fill('2026-10-31');await admin.locator('#funds-form [name=amount]').fill('100');await admin.locator('#funds-form [name=note]').fill('演示提现');await admin.locator('[data-funds-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!!fundsCache?.value&&!busy);
  const afterTransfer=await admin.evaluate(()=>fundsCache.value);assert.equal(afterTransfer.totals.balance_cents,beforeTransfer.balance_cents);assert.equal(afterTransfer.totals.monthly_income_cents,beforeTransfer.monthly_income_cents);assert.equal(afterTransfer.accounts.find(a=>a.id===bank).balance_cents,91000);
  await go(admin,{page:'ledger'});await admin.evaluate(cid=>{ledgerCustomer=cid;ledgerSource='byproduct';ledgerClearance='all';render();},beanCid);
  await admin.locator(`[data-resource-act=receive][data-id="${beanSale.id}"]`).click();await admin.locator('#resource-form [name=account_id]').waitFor();assert(await admin.locator('#resource-form [name=account_id]').count());await admin.locator('#resource-form [name=business_date]').fill('2026-10-31');await admin.locator('#resource-form [name=amount]').fill('5');await admin.locator('#resource-form [name=account_id]').selectOption(cash);await admin.locator('#resource-form [name=note]').fill('演示现金到账');await admin.locator('[data-resource-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!busy);
  await go(admin,{page:'fund-accounts'});await admin.waitForFunction(()=>!!fundsCache?.value);const afterCash=await admin.evaluate(()=>fundsCache.value);assert.equal(afterCash.totals.balance_cents,111500);assert.equal(afterCash.accounts.find(a=>a.id===cash).balance_cents,20500);
  await admin.locator(`[data-fund-action=account][data-id="${bank}"]`).click();assert(await admin.locator('#funds-form [name=opening_balance]').getAttribute('readonly')!==null);await admin.locator('#funds-form [name=active]').selectOption('false');await admin.locator('[data-funds-save]').click();await admin.locator('#overlay').waitFor({state:'hidden'});await admin.waitForFunction(()=>!!fundsCache?.value&&!busy);
  assert.equal(await admin.locator(`[data-fund-action=delete][data-id="${bank}"]`).count(),0,'已有余额和流水的账户保留原账，只能停用');
  await inspect(admin,'fund-accounts-desktop');await admin.locator('#toast').evaluate(el=>el.hidden=true);await admin.screenshot({path:path.join(output,'资金账户统计-电脑.png'),fullPage:true});
  await admin.evaluate(()=>{ledgerSource='all';ledgerCustomer='';ledgerClearance='open';});
  const accountant=await login('accountant');await go(accountant,{page:'system-settings'});assert.equal(await accountant.locator('[data-parameter-tab=byproducts]').count(),0);await go(accountant,{page:'byproducts'});await accountant.locator('[data-byproduct-price-open]').waitFor();assert(!(await accountant.locator('#content').innerText()).includes('加量'));await accountant.context().close();
  await admin.evaluate(()=>{dispatchTab='fleet';});await go(admin,{page:'dispatch'});
  assert.equal(await admin.locator('#dispatch-date').count(),0,'档案查询不展示业务日期');
  assert.equal(await admin.locator('.page-head [data-fleet-act=new].primary').count(),2,'新增按钮明确放在页面标题栏');
  await admin.evaluate(async()=>{
   await api('/api/fleet',{kind:'driver',action:'create',name:'归档验收司机'});data=await api('/api/bootstrap');
   const driver=data.delivery_drivers.find(r=>r.name==='归档验收司机');
   await api('/api/fleet',{kind:'driver',id:driver.id,action:'delete',expected:{name:driver.name,active:driver.active}});data=await api('/api/bootstrap');render();
  });
  assert(!(await admin.locator('.fleet-page').innerText()).includes('归档验收司机'));
  await admin.locator('#fleet-deleted').check();await admin.waitForFunction(()=>fleetShowDeleted);assert((await admin.locator('.fleet-page').innerText()).includes('归档验收司机'));
  await admin.locator('#fleet-search').fill('归档验收司机');await admin.waitForFunction(()=>fleetSearch==='归档验收司机'&&fleetVisible('driver').length===1);
  await admin.locator('#fleet-deleted').uncheck();await admin.waitForFunction(()=>!fleetShowDeleted);assert.equal(await admin.locator('.fleet-table').first().locator('tbody tr:has([data-fleet-act])').count(),0);
  await admin.locator('#fleet-deleted').check();await admin.locator('#fleet-search').fill('');await admin.waitForFunction(()=>fleetSearch==='');
  await inspect(admin,'fleet-desktop');
  const checkLayout=await admin.locator('label:has(#fleet-deleted)').evaluate(el=>({direction:getComputedStyle(el).flexDirection,height:el.getBoundingClientRect().height,input:getComputedStyle(el.querySelector('input')).height}));assert.equal(checkLayout.direction,'row');assert(checkLayout.height<=40);assert(parseFloat(checkLayout.input)<=20);
  await admin.screenshot({path:path.join(output,'司机车辆档案-电脑.png'),fullPage:true,animations:'disabled'});
  for(const width of [760,390,320]){
   await admin.setViewportSize({width,height:900});await admin.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<=1);
   await admin.locator('#mobile-nav-toggle').click();await admin.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().left)<1);
   const toggle=admin.locator('[data-nav-toggle=purchase]');await toggle.click();assert(await admin.locator('body').evaluate(el=>el.classList.contains('mobile-nav-open')),'展开手机分组不关闭抽屉');if(await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
   if(width===390)await admin.screenshot({path:path.join(output,'导航-手机.png')});
   await admin.locator('#nav [data-page=purchases]').click();await admin.waitForFunction(()=>page==='purchases'&&!navigationLoading&&!document.body.classList.contains('mobile-nav-open'));
   await go(admin,{page:'masters',view:'pricing'});await admin.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<=1);await inspect(admin,'pricing-mobile-'+width);
   const wrap=admin.locator('.pricing-matrix').locator('..');await wrap.evaluate(el=>{el.scrollLeft=180;});
   const key=await wrap.evaluate(w=>{const cell=w.querySelector('.freeze-client'),a=cell.getBoundingClientRect(),b=w.getBoundingClientRect();return {wide:w.scrollWidth>w.clientWidth+2,position:getComputedStyle(cell).position,offset:Math.abs(a.left-b.left)};});
   if(key.wide){assert.equal(key.position,'sticky');assert(key.offset<=2,'横向滑动时客户列保持固定');}
   if(width===390)await admin.screenshot({path:path.join(output,'客户专属价格-手机.png'),fullPage:true,animations:'disabled'});
   await admin.evaluate(()=>{dispatchTab='fleet';});await go(admin,{page:'dispatch'});await inspect(admin,'fleet-mobile-'+width);assert.equal(await admin.locator('.page-head [data-fleet-act=new].primary').count(),2);
   if(width===390)await admin.screenshot({path:path.join(output,'司机车辆档案-手机.png'),fullPage:true,animations:'disabled'});
   await go(admin,{page:'fund-accounts'});await admin.waitForFunction(()=>!!fundsCache?.value);await inspect(admin,'fund-accounts-mobile-'+width);if(width===390)await admin.screenshot({path:path.join(output,'资金账户统计-手机.png'),fullPage:true});
   await go(admin,{page:'byproducts'});await inspect(admin,'byproduct-mobile-'+width);assert(!(await admin.locator('#content').innerText()).includes('加量'));
   if(width===390){
    await admin.screenshot({path:path.join(output,'豆渣收款-手机.png'),fullPage:true,animations:'disabled'});
    await admin.locator(`[data-byproduct-statement][data-cid="${beanCid}"]`).first().click();await admin.waitForFunction(()=>!!byproductStatementState?.draft);
    assert.equal(await admin.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'手机结算单窗口无页面溢出');
    await admin.screenshot({path:path.join(output,'豆渣结算单-手机.png'),fullPage:true});
    await admin.locator('#dialog-close').click();await admin.locator('#overlay').waitFor({state:'hidden'});
   }

  }
  assert.deepEqual(errors,[]);
  const result={ok:true,quick,roles,modulesAudited:quick?0:modules.length,tableViews:audit.length,tables:audit.reduce((n,r)=>n+r.tables,0),cells:audit.reduce((n,r)=>n+r.cells,0),noteCells:audit.reduce((n,r)=>n+r.notes,0),priceInputs:priceGeometry.length,maxPriceCenterOffset:Math.max(...priceGeometry.flatMap(g=>[g.x,g.y])),widths:[1440,760,390,320],browserErrors:errors,audit};
  fs.writeFileSync(path.join(output,'浏览器验收.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,audit:undefined}));
 }catch(error){console.error(error);throw error;}finally{if(browser)await browser.close();if(service&&service.exitCode===null&&service.signalCode===null){service.kill('SIGTERM');await new Promise(r=>service.once('exit',r));}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
