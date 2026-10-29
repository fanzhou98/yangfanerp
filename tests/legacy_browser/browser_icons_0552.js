const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-icons-0552-')),db=path.join(temp,'test.db'),out=path.join(root,'output/彩色系统图标-v0.55.2/浏览器验收');fs.mkdirSync(out,{recursive:true});let service,browser;const errors=[],audit=[];
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});const base=`http://127.0.0.1:${port}`;
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  async function login(user,width=1440){const p=await browser.newPage({viewport:{width,height:1000},hasTouch:true});p.on('pageerror',e=>errors.push(user+': '+e.message));p.on('console',m=>{if(m.text().includes('Content Security Policy'))errors.push(m.text());});await p.goto(base);await p.locator('[name=username]').fill(user);await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);return p;}
  const p=await login('admin');
  const modules=await p.evaluate(()=>data.access_catalog.modules.filter(moduleVisible).filter(m=>m.page!=='directory').map(m=>({id:m.id,page:m.page,view:m.view,title:m.title})));
  for(const module of modules){
   await p.evaluate(async m=>{if(m.view)masterView=m.view;selectedDate='2026-10-20';factoryDay='2026-10-20';await goto(m.page);if(navigationPending)await choosePageTransition('discard');},module);
   await p.waitForLoadState('networkidle');await p.waitForFunction(()=>!navigationLoading&&!busy);assert.equal(await p.evaluate(()=>page),module.page,module.id);
   const feedback=await p.locator('#page-feedback').innerText();assert(!feedback||await p.locator('#page-feedback').isHidden(),module.id+': '+feedback);
   const text=await p.locator('#content').innerText();assert(!text.includes('读取失败'),module.id);
   const check=await p.locator('#content .page-title-icon .erp-business-icon,#content .home-date-bar .erp-business-icon').evaluateAll(icons=>icons.map(icon=>({source:icon.dataset.iconSource,key:icon.dataset.iconKey,box:icon.getBoundingClientRect().toJSON()})));
   for(const icon of check){assert.equal(icon.source,'48797');assert.notEqual(icon.key,'generic');assert(icon.box.width>=20&&icon.box.width<=32);}
   audit.push({module:module.id,page:module.page,icons:check.length});
  }
  await p.evaluate(async()=>{await goto('allocation');if(navigationPending)await choosePageTransition('discard');for(const group of document.querySelectorAll('.erp-nav-group')){const toggle=group.querySelector('.nav-group-toggle');if(toggle?.getAttribute('aria-expanded')!=='true')toggle.click();}window.scrollTo(0,0);});await p.waitForLoadState('networkidle');
  assert(await p.locator('.nav-section-symbol .erp-business-icon').count()>=8);
  for(const selector of ['.nav-section-symbol .erp-business-icon','.nav-icon .erp-business-icon']){const source=await p.locator(selector).evaluateAll(icons=>icons.map(i=>i.dataset.iconSource));assert(source.every(s=>s==='48797'));}
  const originalColors=await p.evaluate(()=>{const s=document.createElement('div');s.innerHTML=submenuIcon('stock');document.body.append(s);const colors=[...s.querySelectorAll('path')].map(el=>getComputedStyle(el).fill);s.remove();return colors;});assert.deepEqual(originalColors,['rgb(66, 180, 250)','rgb(146, 219, 255)']);
  await p.screenshot({path:path.join(out,'彩色导航与页面-desktop.png'),fullPage:true});
  await p.evaluate(()=>openModuleSearch());await p.locator('#module-search').fill('库存');assert(await p.locator('.module-search-result:not([hidden]) .erp-business-icon').count());await p.screenshot({path:path.join(out,'功能查找图标.png'),fullPage:true});await p.evaluate(()=>{dialogBaseline='';closeDialog();});
  await p.locator('#sidebar-toggle').click();await p.waitForTimeout(100);assert(await p.evaluate(()=>document.body.classList.contains('sheet-wide')));assert.equal(await p.locator('.nav-group-toggle:visible').count(),0,'收起导航保持图标模式');await p.screenshot({path:path.join(out,'收起导航-desktop.png'),fullPage:true});await p.locator('#sidebar-toggle').click();
  for(const width of [320,390,430]){
   await p.setViewportSize({width,height:900});await p.evaluate(()=>{closeMobileNavigation();window.scrollTo(0,0);});await p.waitForTimeout(250);
   for(const target of ['dashboard','factory','orders','settlements','assets','crates','driver-work']){
    if(!modules.some(m=>m.page===target))continue;await p.evaluate(t=>goto(t),target);await p.waitForLoadState('networkidle');assert.equal(await p.evaluate(()=>page),target);const overflow=await p.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,bad:[...document.querySelectorAll('body *')].map(el=>({tag:el.tagName,cls:el.className?.baseVal??el.className,rect:el.getBoundingClientRect().toJSON()})).filter(e=>e.rect.width>0&&e.rect.right>innerWidth+1).slice(0,12)}));if(overflow.scroll>width+1)await p.screenshot({path:path.join(out,'溢出-'+target+'-'+width+'.png'),fullPage:true});assert(overflow.scroll<=width+1,target+' '+width+' 页面无横向溢出 '+JSON.stringify(overflow));
    const bad=await p.locator('.erp-business-icon').evaluateAll(icons=>icons.filter(i=>{const r=i.getBoundingClientRect();return r.width&&i.closest('#content')&&(r.left<0||r.right>innerWidth+1);} ).map(i=>i.dataset.iconKey));assert.deepEqual(bad,[],target+' '+width+' 图标不越界');
   }
   await p.evaluate(()=>{openMobileNavigation();document.querySelector('#nav').scrollTo(0,0);});await p.waitForTimeout(250);await p.screenshot({path:path.join(out,'彩色手机导航-'+width+'.png'),fullPage:true});await p.evaluate(()=>closeMobileNavigation());
  }
  for(const user of ['warehouse','accountant','cashier','director','logistics','driver','owner']){const q=await login(user,390);await q.evaluate(()=>{selectedDate='2026-10-20';render();});await q.waitForLoadState('networkidle');assert(!(await q.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),user+' 工作台');const shown=await q.locator('[data-module-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.moduleId));const allowed=await q.evaluate(()=>data.access_catalog.modules.filter(moduleVisible).map(m=>m.id));assert(shown.every(id=>allowed.includes(id)),user+' 不增加权限入口');await q.screenshot({path:path.join(out,'工作台-'+user+'-390.png'),fullPage:true});await q.close();}
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({ok:true,moduleCount:modules.length,audit,phoneWidths:[320,390,430],roles:7,errors},null,2));console.log(JSON.stringify({ok:true,modules:modules.length,roles:7,errors}));
 }finally{if(browser)await browser.close();if(service){service.kill();await new Promise(r=>service.once('exit',r));}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack);process.exit(1);});
