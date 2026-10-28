// R01: real month-close form, frozen product report and role boundaries.
const {chromium} = require(process.env.ERP_PLAYWRIGHT_MODULE || '/Users/zhoufan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const cp = require('node:child_process');
const net = require('node:net');

(async () => {
  const root = path.resolve(__dirname, '..');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'erp-r01-'));
  const db = path.join(temp, 'test.db');
  const out = path.join(root, 'output/月结状态修复-v0.60.1/浏览器验收');
  fs.mkdirSync(out, {recursive: true});
  let service, browser;
  const errors = [], checks = [];
  try {
    cp.execFileSync('python3', ['tests/seed_owner_dashboard.py', db], {cwd: root, stdio: 'pipe'});
    const port = await new Promise(resolve => {
      const probe = net.createServer();
      probe.listen(0, '127.0.0.1', () => {
        const n = probe.address().port;
        probe.close(() => resolve(n));
      });
    });
    service = cp.spawn('python3', ['server.py', '--no-browser', '--database', db, '--port', String(port)], {cwd: root, stdio: 'ignore'});
    const base = `http://127.0.0.1:${port}`;
    let healthy = false;
    for (let i = 0; i < 100; i++) {
      try { if ((await fetch(base + '/api/health')).ok) { healthy = true; break; } } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert(healthy, '临时测试服务未启动');
    browser = await chromium.launch({channel: 'chrome', headless: true});
    const p = await browser.newPage({viewport: {width: 1440, height: 1000}});
    p.setDefaultTimeout(15000);
    p.on('pageerror', e => errors.push(e.message));
    p.on('console', m => { if (m.text().includes('Content Security Policy')) errors.push(m.text()); });
    const login = async (page, username) => {
      await page.goto(base);
      await page.locator('[name=username]').fill(username);
      await page.locator('[name=password]').fill('Dashboard-Test-2026!');
      await page.locator('#auth-login-form [type=submit]').click();
      await page.waitForFunction(() => typeof data !== 'undefined' && data?.auth_user);
      await page.waitForLoadState('networkidle');
    };
    const go = async target => {
      await p.evaluate(t => { resourcesMonth = '2026-10'; productProfitMonth = '2026-10'; selectedDate = '2026-10-20'; goto(t); }, target);
      await p.waitForLoadState('networkidle');
      await p.waitForFunction(() => !navigationLoading && !busy);
    };
    const report = () => p.evaluate(() => api('/api/product-profit?month=2026-10'));
    const togglePeriod = async note => {
      await go('expenses');
      await p.locator('[data-resource-act=period]').click();
      await p.locator('#resource-form [name=note]').fill(note);
      await p.locator('[data-resource-save]').click();
      await p.waitForFunction(() => document.getElementById('overlay').hidden && !busy);
    };
    await login(p, 'admin');
    const before = await report();
    assert(before.gaps.some(g => g.field === '成本月份未结账，费用可能未录全'));
    await togglePeriod('R01浏览器月结验收');
    const closed = await report();
    assert(!closed.gaps.some(g => g.field === '成本月份未结账，费用可能未录全'));
    assert(closed.gaps.some(g => g.field.includes('不能认定净利润')));
    assert.deepEqual(closed.total, before.total);
    assert.equal(await p.locator('[data-resource-act=period]').innerText(), '重新打开本月');
    checks.push('真实表单结账：提示正确，金额未改变，真实成本缺项保留');

    const period = await p.evaluate(() => data.resources.periods.find(x => x.month === '2026-10'));
    assert(!('report_snapshot' in period));
    const rejected = await p.evaluate(async version => {
      try { await api('/api/resources/period', {month: '2026-10', state: 'open', version, note: '旧版本重放'}); return false; }
      catch { return true; }
    }, period.version - 1);
    assert(rejected, '旧版本不能重开');
    await p.evaluate(async version => api('/api/resources/period', {month: '2026-10', state: 'closed', version, note: '同状态重试'}), period.version);
    assert.deepEqual(await report(), closed);
    checks.push('旧版本拒绝、同状态重试保持冻结报告，普通资源接口不下发报告快照');

    await togglePeriod('R01浏览器重开验收');
    assert((await report()).gaps.some(g => g.field === '成本月份未结账，费用可能未录全'));
    await togglePeriod('R01浏览器重新结账');
    assert.deepEqual(await report(), closed);
    checks.push('重开和再结账状态及金额一致');

    for (const width of [1440, 390, 320]) {
      await p.setViewportSize({width, height: 1000});
      await p.evaluate(() => closeMobileNavigation());
      await go('product-profit');
      await p.waitForFunction(() => !!productProfitCache.get('2026-10')?.value);
      for (const summary of await p.locator('#content details.report-issues:not([open]) > summary').all()) {
        await summary.click();
      }
      const text = await p.locator('#content').innerText();
      assert(!text.includes('成本月份未结账，费用可能未录全'));
      assert(text.includes('不能认定净利润'));
      assert(!(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)), `页面溢出 ${width}`);
      await p.screenshot({path: path.join(out, `已结产品测算-${width}.png`), fullPage: true});
      await go('expenses');
      assert.equal(await p.locator('[data-resource-act=period]').innerText(), '重新打开本月');
      await p.screenshot({path: path.join(out, `已结费用月份-${width}.png`), fullPage: true});
    }
    checks.push('1440/390/320宽度费用及产品测算，无页面溢出');
    const ownerContext = await browser.newContext();
    const owner = await ownerContext.newPage();
    owner.on('pageerror', e => errors.push(e.message));
    await login(owner, 'owner');
    assert.equal(await owner.evaluate(async () => (await fetch('/api/resources/period', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-ERP-Client': 'local-pilot',
        'X-CSRF-Token': document.cookie.split('; ').find(x => x.startsWith('erp_csrf='))?.split('=')[1] || ''},
      body: JSON.stringify({month: '2026-10', state: 'open', version: 3, note: '老板越权测试'})
    })).status), 403);
    checks.push('老板写入月结接口拒绝');
    assert.deepEqual(errors, []);
    const result = {ok: true, checks, errors};
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally {
    if (browser) await browser.close();
    if (service && service.exitCode === null && service.signalCode === null) {
      const stopped = new Promise(resolve => service.once('exit', resolve));
      service.kill('SIGTERM');
      await stopped;
    }
    fs.rmSync(temp, {recursive: true, force: true});
  }
})().catch(error => { console.error(error.stack); process.exit(1); });
