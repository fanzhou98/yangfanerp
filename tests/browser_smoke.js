'use strict';
// 当前版本浏览器冒烟：登录后逐个进入导航模块，断言无脚本错误、无加载失败提示。
// 与历史 browser_*.js（绑定当年的业务规则）分开维护，发版看门狗只跑本脚本。
const {chromium} = require(process.env.ERP_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const cp = require('node:child_process'), net = require('node:net');

(async () => {
  const root = path.resolve(__dirname, '..');
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
    for (const id of await page.locator('#nav [data-nav-toggle]').evaluateAll(nodes => nodes.map(n => n.dataset.navToggle))) {
      const toggle = page.locator(`#nav [data-nav-toggle="${id}"]`);
      if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
    }
    await page.locator('#nav [data-page]').first().waitFor({state: 'visible', timeout: 20000});

    const pages = await page.locator('#nav [data-page]').evaluateAll(nodes =>
      nodes.map(n => ({page: n.dataset.page, label: (n.getAttribute('aria-label') || n.textContent || '').trim()})));
    assert.ok(pages.length >= 30, '导航模块数异常：' + pages.length);

    const failed = [];
    for (const item of pages) {
      const before = errors.length;
      await page.locator(`#nav [data-page="${item.page}"]`).click();
      await page.waitForTimeout(220);
      const bad = await page.evaluate(() => {
        const text = document.body.innerText || '';
        const hit = text.match(/(加载失败|服务器错误|无法加载|Uncaught)/);
        return hit ? hit[0] : '';
      });
      if (bad || errors.length > before) failed.push({page: item.page, label: item.label, bad, errors: errors.slice(before)});
    }
    if (failed.length) console.log(JSON.stringify(failed, null, 2));
    assert.deepEqual(failed, []);
    assert.deepEqual(errors, []);
    console.log(`smoke ok: ${pages.length} modules`);
  } catch (err) {
    if (browser) {
      try { fs.mkdirSync(path.join(os.tmpdir(), 'erp-smoke-shots'), {recursive: true}); } catch {}
    }
    console.error(String(err && err.stack || err));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    service.kill();
  }
})();
