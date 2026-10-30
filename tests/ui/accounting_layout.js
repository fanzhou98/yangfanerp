// Customer accounting: visible bill quantity, pricing switches, cache and responsive layout.
'use strict';
// 当前版本浏览器冒烟：登录后逐个进入导航模块，断言无脚本错误、无加载失败提示。
// 与历史 browser_*.js（绑定当年的业务规则）分开维护，发版看门狗只跑本脚本。
const {chromium} = require(process.env.ERP_PLAYWRIGHT_MODULE || '/tmp/erp-playwright/node_modules/playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const cp = require('node:child_process'), net = require('node:net');

(async () => {
  const root = process.cwd();
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'erp-smoke-'));
  const db = path.join(temp, 'navigation-test-smoke.db');
  const py = process.env.ERP_PYTHON || 'python3';
  cp.execFileSync(py, [path.join(root, 'tests/seed_allocation.py'), db], {cwd: root});
  cp.execFileSync(py, ['-c', `import auth,server,time,sys\nfrom pathlib import Path\nserver.DB=Path(sys.argv[1])\nwith server.connect(True) as c: auth.create_initial_admin(c,'admin','冒烟管理员','Smoke-Admin-2026!',int(time.time()))`, db], {cwd: root});

  const port = await new Promise(resolve => {
    const probe = net.createServer();
    probe.listen(0, '127.0.0.1', () => { const p = probe.address().port; probe.close(() => resolve(p)); });
  });
  const base = `http://127.0.0.1:${port}`;
  const service = cp.spawn(py, [path.join(root, 'server.py'), '--no-browser', '--database', db, '--port', String(port)], {cwd: root, stdio: 'pipe'});
  let logs = '';
  service.stderr.on('data', buf => logs += buf);
  let browser;
  try {
    for (let i = 0; i < 200; i++) {
      try { if ((await fetch(base + '/api/health')).ok) break; } catch {}
      if (i === 199) throw Error('service not started ' + logs);
      await new Promise(r => setTimeout(r, 50));
    }
    browser = await chromium.launch({channel: 'chrome', headless: true});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base);
    await page.locator('#auth-login-form [name=username]').fill('admin');
    await page.locator('#auth-login-form [name=password]').fill('Smoke-Admin-2026!');
    await page.locator('#auth-login-form [type=submit]').click();
    await page.locator('#nav [data-nav-toggle]').first().waitFor({state: 'attached', timeout: 40000});
    await page.evaluate(()=>{selectedDate='2026-10-22';sheetStatus='all';goto('settlements');});
    await page.waitForFunction(()=>!navigationLoading&&!busy&&!!document.querySelector('[data-account-view]'));
    await page.evaluate(()=>{for(const p of document.querySelectorAll('.client-sheet'))setCustomerDetails(p,true);});
    const savedId=await page.locator('[data-processing-order]').first().getAttribute('data-processing-order');
    await page.locator('[data-processing-order]').first().locator('[data-field=price]').fill('3.1');
    const savedResponse=page.waitForResponse(r=>r.url().endsWith('/api/batch')&&r.request().method()==='POST');
    await page.locator('[data-sheet-action=save]').first().click();
    assert.equal((await savedResponse).status(),200,'real save must succeed');
    await page.waitForFunction(()=>!busy);
    await page.reload();
    await page.waitForFunction(()=>typeof data!=='undefined'&&!!data?.orders);
    assert(await page.evaluate(id=>data.orders.find(o=>o.id===id)?.lines.some(l=>Number(l.price)===3.1),savedId),'saved price survives refresh');
    await page.evaluate(()=>{selectedDate='2026-10-22';sheetStatus='all';goto('settlements');});
    await page.waitForFunction(()=>!navigationLoading&&!busy&&!!document.querySelector('[data-account-view]'));
    await page.evaluate(()=>{for(const o of data.orders){o.state='dispatched';o.status='待算票';o.weight_confirmation=undefined;for(const l of o.lines){l.actual_qty=l.ordered_qty;l.allocated_qty=l.ordered_qty;if(l.unit==='筐'){l.driver_weight_basis='gross';const variants=crateAttributes(l.product_id);if(variants.length)l.crate_lines=variants.slice(0,2).map((v,i)=>({product_id:l.product_id,asset_id:v.id,asset_name:v.name,qty:variants.length>1?(i===0?Math.floor(Number(l.actual_qty)/2):Number(l.actual_qty)-Math.floor(Number(l.actual_qty)/2)):l.actual_qty,tare:'2'}));l.driver=[{gross:'180',count:l.actual_qty,tare:'2'}];l.customer=[{gross:'178',count:l.actual_qty,tare:'2'}];}}}sheetOrders.clear();sheetBaselines.clear();lineChoices.clear();render();});
    await page.waitForFunction(()=>!!document.querySelector('[data-processing-order]'));
    const row=page.locator('[data-processing-order]').first();
    assert.equal(await row.locator(':scope > td').count(),15);
    assert.equal(await row.locator('details').count(),0,'row must expose original separate columns without nested disclosure cards');
    const mode=row.locator('[data-field=mode]');await mode.selectOption('agreed');
    const net=row.locator('[data-field=agreed_net]');await net.fill('123');
    await row.locator('[data-field=price]').fill('3');
    await page.waitForFunction(()=>document.querySelector('[data-processing-order] [data-line-amount]').innerText.includes('369'));
    assert.equal(await net.isEnabled(),true);await mode.selectOption('driver');assert.equal(await net.isEnabled(),false);
    for(const view of ['customer','product']){
      await page.locator('[data-account-view='+view+']').first().click();
      await page.waitForFunction(()=>!busy&&!navigationLoading);
      if(view==='customer')await page.evaluate(()=>{for(const p of document.querySelectorAll('.client-sheet'))setCustomerDetails(p,true);});
      assert.equal(await page.locator('[data-processing-order]').first().locator(':scope > td').count(),15);
      const checks=await page.locator('[data-processing-order]').first().evaluate(row=>({font:getComputedStyle(row.cells[2]).fontSize,align:getComputedStyle(row.cells[2]).textAlign,tare:row.querySelector('[data-tare-cell]').innerText}));assert.equal(checks.font,'13px');assert.equal(checks.align,'center');assert(checks.tare.includes('公斤/个'));console.log(view,JSON.stringify(checks));
      for(const width of [1920,1440,390,320]){await page.setViewportSize({width,height:1000});await page.evaluate(()=>{closeMobileNavigation();document.documentElement.style.scrollBehavior='auto';document.querySelector('[data-processing-order]').scrollIntoView({behavior:'instant',block:'center'});});await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow '+view+' '+width);await page.screenshot({path:'/tmp/erp-ui-final-'+view+'-'+width+'.png',fullPage:false});}await page.setViewportSize({width:1920,height:1080});
    }
    assert(await page.locator('[data-processing-order]').first().locator('[data-simple-weight=driver]').evaluate(e=>e.getBoundingClientRect().width<=90));
    await page.locator('.product-account-table').screenshot({path:'/tmp/erp-ui-final-product-detail.png'});
    const link=page.locator('.product-account-table button.text-button').first();assert(await link.evaluate(e=>getComputedStyle(e).textDecorationLine.includes('underline')));
    await page.evaluate(()=>{for(const o of data.orders){o.status='待重算';o.review_return={status:'pending'};}sheetOrders.clear();sheetBaselines.clear();sheetStatus='rework';accountView='product';render();});
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});await page.evaluate(()=>closeMobileNavigation());
      const layout=await page.locator('[data-processing-order]').first().evaluate(row=>{const button=row.querySelector('.shipment-quantity-edit'),number=button.querySelector('strong').getBoundingClientRect(),label=button.querySelector('span').getBoundingClientRect();return {below:label.top>=number.bottom,underline:getComputedStyle(button.querySelector('span')).textDecorationLine,status:row.querySelector('.account-order-status .workflow-status')?.textContent,overflow:document.documentElement.scrollWidth>innerWidth+1};});
      assert(layout.below);assert(layout.underline.includes('underline'));assert.equal(layout.status,'待重算');assert(!layout.overflow);
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({ok:true,temp}));
  } catch(e) {if(browser){const pages=browser.contexts().flatMap(c=>c.pages());if(pages[0]){await pages[0].screenshot({path:'/tmp/erp-ui-final-error.png'});console.log((await pages[0].locator('body').innerText()).slice(-1500));}}throw e;} finally {if(browser)await browser.close();service.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
