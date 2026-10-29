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
    await page.locator('#nav [data-nav-toggle]').first().waitFor({state: 'attached', timeout: 20000});
    await page.evaluate(()=>{selectedDate='2026-10-22';sheetStatus='all';goto('settlements');});
    await page.waitForFunction(()=>!navigationLoading&&!busy&&!!document.querySelector('[data-account-view]'));
    await page.evaluate(()=>{for(const o of data.orders){o.state='dispatched';o.status='待算票';o.weight_confirmation=undefined;for(const l of o.lines){l.actual_qty=l.ordered_qty;l.allocated_qty=l.ordered_qty;if(l.unit==='筐'){l.driver_weight_basis='gross';l.driver=[{gross:'180',count:l.actual_qty,tare:'2'}];l.customer=[{gross:'178',count:l.actual_qty,tare:'2'}];}}}sheetOrders.clear();sheetBaselines.clear();lineChoices.clear();render();});
    await page.waitForFunction(()=>!!document.querySelector('[data-processing-order]'));
    const row=page.locator('[data-processing-order]').first();
    if(await row.locator('.account-detail').count()){
      assert.equal(await row.locator(':scope > td').count(),9);
      const mode=row.locator('[data-field=mode]');await mode.selectOption('agreed');
      const net=row.locator('[data-field=agreed_net]');await net.fill('123');
      await row.locator('[data-field=price]').fill('3');
      await page.waitForFunction(()=>document.querySelector('[data-processing-order] [data-line-amount]').innerText.includes('369'));
      assert.equal(await net.isEnabled(),true);
      await mode.selectOption('driver');assert.equal(await net.isEnabled(),false);
      await row.locator('.account-detail summary').first().click();
      assert(await row.locator('[data-tare-cell]').isVisible());
      await row.locator('.account-detail summary').first().click();
      for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:'/tmp/erp-account-after-'+width+'.png',fullPage:width===1440});}
      await page.setViewportSize({width:1440,height:1000});
      await page.locator('[data-account-view=product]').first().click();
      await page.waitForFunction(()=>!!document.querySelector('.product-account-table'));
      assert.equal(await page.locator('.product-account-table tbody tr').first().locator(':scope >td').count(),9);
      await page.screenshot({path:'/tmp/erp-account-product.png',fullPage:true});
    }else throw Error('new accounting layout missing');
    console.log(JSON.stringify({ok:true,temp}));
  } finally {if(browser)await browser.close();service.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
