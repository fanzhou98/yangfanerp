const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
(async()=>{
 const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-nav-0553-')),out=path.join(root,'output/导航与手机返回-v0.55.3/浏览器验收');fs.mkdirSync(out,{recursive:true});
 let service,browser,p;const errors=[],checks=[];
 try{
  const db=path.join(temp,'test.db');cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const port=s.address().port;s.close(()=>resolve(port));});});
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});p=await context.newPage();
  p.on('pageerror',e=>errors.push(e.stack||e.message));p.on('console',m=>{if(m.text().includes('Content Security Policy'))errors.push(m.text());});p.on('response',r=>{if(r.status()>=500)errors.push(r.url()+': '+r.status());});p.setDefaultTimeout(12000);
  await p.goto(base);await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  async function ready(){await p.waitForFunction(()=>!navigationLoading&&!busy);await p.waitForLoadState('networkidle');}
  async function go(target){await p.evaluate(async target=>{selectedDate=factoryDay='2026-10-20';await goto(target);if(navigationPending)await choosePageTransition('discard');window.scrollTo(0,0);},target);await ready();await p.waitForTimeout(400);}
  await p.evaluate(()=>{window.__touchTrace=[];for(const kind of ['touchstart','touchmove','touchend','touchcancel'])document.addEventListener(kind,e=>window.__touchTrace.push({kind,target:e.target.tagName,cls:e.target.className,blocked:mobileBackBlocked(e.target),prevented:e.defaultPrevented,cancelable:e.cancelable,gesture:mobileBackGesture&&{...mobileBackGesture},page,loading:navigationLoading,trail:pageTrail.map(r=>r.page)}));});
  const touch=await context.newCDPSession(p);
  async function swipe(x,y,dx,dy=0){await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});for(let step=1;step<=8;step++){await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+dx*step/8,y:y+dy*step/8}]});await p.waitForTimeout(20);}await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await p.waitForTimeout(150);}
  for(const width of [320,390,430]){
   await p.setViewportSize({width,height:844});await go('factory');await go('production-report');
   const title=await p.locator('#content h1').boundingBox();await swipe(width-30,title.y+title.height/2,-width*.6,35);await p.waitForFunction(()=>page==='factory');await ready();
   checks.push({width,leftSwipe:true});
   await go('production-report');await swipe(width-35,350,-8,-160);assert.equal(await p.evaluate(()=>page),'production-report','纵向滚动不返回');
   await p.evaluate(()=>window.scrollTo(0,Math.max(400,document.documentElement.scrollHeight-innerHeight)));await p.waitForTimeout(100);
   assert(await p.locator('#back-to-top').isVisible());const button=await p.locator('#back-to-top').boundingBox();assert(button.y+button.height<=844-100,'回顶按钮上移');
   await p.screenshot({path:path.join(out,`生产日报-${width}.png`),fullPage:true});await p.waitForTimeout(800);
  }
  await go('factory');await go('production-report');await p.evaluate(()=>{const table=document.createElement('div');table.className='table-wrap';table.id='touch-table';table.innerHTML='<table><tbody><tr><td>普通表格也能左滑返回</td></tr></tbody></table>';document.querySelector('#content').prepend(table);});const cell=await p.locator('#touch-table td').boundingBox();await swipe(380,cell.y+cell.height/2,-220,20);await p.waitForFunction(()=>page==='factory');await ready();checks.push({ordinaryTableSwipe:true});
  await go('allocation');await p.evaluate(()=>{selectedDate='2026-10-25';render();});await ready();
  const qty=p.locator('[data-stock="P001"][data-field="existing_qty"]');await qty.fill('10');await p.evaluate(()=>window.scrollTo(0,0));const heading=await p.locator('#content h1').boundingBox();await swipe(380,heading.y+heading.height/2,-220,30);await p.locator('#leave-overlay').waitFor({state:'visible'});assert.equal(await p.evaluate(()=>page),'allocation');await p.locator('[data-leave-choice=stay]').click();assert.equal(await qty.inputValue(),'10');
  await p.evaluate(()=>{for(const d of warehouseDrafts.values())d.initial=JSON.stringify(d.plan);});
  await go('orders');await p.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));await p.waitForTimeout(150);
  const dock=await p.locator('.page-save-dock').boundingBox();if(dock){const back=await p.locator('#back-to-top').boundingBox();assert(back.y+back.height+10<=dock.y,'回顶避开真实保存栏');checks.push({saveDockClear:true});}
  // An unusually tall save bar must still leave the floating control above it.
  await p.evaluate(()=>{const bar=document.createElement('div');bar.className='page-save-dock';bar.id='test-save-dock';document.querySelector('#content').append(bar);const sheet=new CSSStyleSheet();sheet.replaceSync('#test-save-dock{position:fixed;bottom:0;right:0;width:100%;height:150px}');document.adoptedStyleSheets=[...document.adoptedStyleSheets,sheet];updateBackToTop();});
  const back=await p.locator('#back-to-top').boundingBox(),bar=await p.locator('#test-save-dock').boundingBox();assert(back.y+back.height+10<=bar.y);await p.screenshot({path:path.join(out,'回顶避开保存栏.png')});await p.evaluate(()=>document.querySelector('#test-save-dock').remove());
  await p.setViewportSize({width:1440,height:900});await p.evaluate(()=>{document.body.classList.remove('sheet-wide');nav();for(const group of document.querySelectorAll('.erp-nav-group')){if(group.querySelector('.nav-group-toggle')?.getAttribute('aria-expanded')!=='true')group.querySelector('.nav-group-toggle').click();}});
  const styles=await p.locator('.nav-group-toggle').evaluateAll(items=>items.map(e=>getComputedStyle(e).position));assert(styles.length);assert(styles.every(s=>s==='static'),'导航组随内容滚动');
  await p.screenshot({path:path.join(out,'导航无吸顶.png')});assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({ok:true,checks,errors},null,2));console.log(JSON.stringify({ok:true,checks,errors}));
 }catch(error){if(p){console.error(JSON.stringify(await p.evaluate(()=>({page,trace:window.__touchTrace?.slice(-4),errors:document.querySelector('#page-feedback')?.textContent})))) ;await p.screenshot({path:path.join(out,'failure.png'),fullPage:true});}throw error;
 }finally{if(browser)await browser.close();if(service){service.kill();await new Promise(r=>service.once('exit',r));}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack);process.exit(1);});
