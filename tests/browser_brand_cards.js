const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'..'),output=path.join(root,'output/名称卡片与图标-v0.54.3/浏览器验收');
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'erp-brand-cards-')),db=path.join(temp,'synthetic.db');let service,browser;const errors=[],audit=[];fs.mkdirSync(output,{recursive:true});
 try{
  cp.execFileSync('python3',['tests/seed_owner_dashboard.py',db],{cwd:root,stdio:'ignore'});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const port=s.address().port;s.close(()=>resolve(port));});}),base=`http://127.0.0.1:${port}`;
  service=cp.spawn('python3',['server.py','--no-browser','--database',db,'--port',String(port)],{cwd:root,stdio:'ignore'});
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
  browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext({viewport:{width:1440,height:1000}}),p=await context.newPage();p.setDefaultTimeout(12000);p.on('pageerror',e=>errors.push(e.message));
  await p.goto(base);await p.locator('#auth-login-form').waitFor();await p.screenshot({path:path.join(output,'登录图标.png'),fullPage:true});
  await p.locator('[name=username]').fill('admin');await p.locator('[name=password]').fill('Dashboard-Test-2026!');await p.locator('#auth-login-form [type=submit]').click();await p.waitForFunction(()=>typeof data!=='undefined'&&data?.auth_user);
  await p.evaluate(()=>{selectedDate='2026-10-28';factoryDay=selectedDate;goto('factory');});await p.waitForFunction(()=>page==='factory'&&!navigationLoading);await p.waitForLoadState('networkidle');
  const names=['豆腐磨浆系统','豆皮磨浆系统','内脂磨浆系统'];
  for(const kind of ['上豆','泡豆']){const panel=p.locator('.resource-panel').filter({has:p.locator('h2',{hasText:new RegExp('^'+kind+'$')})});assert.deepEqual(await panel.locator('.grinding-system-card h3').allTextContents(),names);}
  assert.equal(await p.evaluate(()=>typeof supplySystemShort),'undefined');
  const read=async label=>{const r=await p.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,cards:[...document.querySelectorAll('.panel .grinding-system-card')].map(c=>{const r=c.getBoundingClientRect();return {name:c.querySelector('h3').textContent,width:r.width,height:r.height,overflow:c.scrollWidth>c.clientWidth+1};}),brand:getComputedStyle(document.querySelector('.sidebar .brand-mark')).backgroundImage}));assert(!r.overflow,label);assert(r.cards.length>=6);assert(r.cards.every(c=>c.width<=217&&!c.overflow),label+' 紧凑卡片');assert(r.brand.includes('favicon.svg?v=0.54.3'));audit.push({label,...r});};
  await read('desktop');await p.screenshot({path:path.join(output,'完整名称与紧凑卡片-电脑.png'),fullPage:true});
  await p.locator('[data-factory-act=beans]').click();assert.deepEqual(await p.locator('[data-bean-system-select]').first().locator('option').allTextContents(),names);await p.evaluate(()=>{dialogBaseline='';closeDialog();});
  // Long numbers may wrap to a second row rather than widening the card.
  await p.evaluate(()=>{const grid=document.querySelector('.panel .factory-system-overview');grid.outerHTML=factoryBeanCards({tofu:123456789.123,skin:987654321.123,'gel-tofu':999999999.999});});await read('long-numbers');
  await p.evaluate(()=>render());
  for(const width of [760,390,320]){await p.setViewportSize({width,height:900});await read('width-'+width);await p.screenshot({path:path.join(output,'完整名称与紧凑卡片-'+width+'.png'),fullPage:true});}
  await p.setViewportSize({width:1440,height:1000});
  const assets=await p.evaluate(async()=>{const urls=[...document.querySelectorAll('link[rel*=icon],link[rel=manifest]')].map(e=>e.href);const result=[];for(const url of urls){const r=await fetch(url);result.push({url:new URL(url).pathname,status:r.status,type:r.headers.get('content-type'),bytes:(await r.arrayBuffer()).byteLength});}return result;});assert(assets.every(r=>r.status===200&&r.bytes>100));
  // Display both actual-size favicon assets and application icons in a dedicated proof.
  await p.setContent('<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:48px;background:#f7f8f5;font:16px sans-serif;color:#235d4c}section{display:flex;align-items:center;gap:56px}figure{margin:0;text-align:center}figcaption{margin-top:18px}</style><h2>洋帆 ERP · YF 帆形标识</h2><section>'+[['icon-512.png',300,'应用图标'],['apple-touch-icon.png',180,'手机桌面'],['favicon-32x32.png',32,'32 px'],['favicon-16x16.png',16,'16 px']].map(([file,size,label])=>`<figure><img src="${base}/${file}?v=0.54.3" width="${size}" height="${size}"><figcaption>${label}</figcaption></figure>`).join('')+'</section>');await p.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth));await p.screenshot({path:path.join(output,'正式图标尺寸预览.png')});
  assert.deepEqual(errors,[]);const report={ok:true,version:'0.54.3',audit,assets,errors};fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({ok:true,widths:[1440,760,390,320],systemNames:names,cards:'<=216px',assets:assets.length,errors}));
 }finally{if(browser)await browser.close();if(service){service.kill();await new Promise(resolve=>service.once('exit',resolve));}fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e.stack);process.exit(1);});
