#!/usr/bin/env node
/* 只读 UI 居中巡检：用真实渲染测量文字墨迹中心与元素盒中心的偏差。
 *
 * 用法（先在 /tmp 副本库上起免登录服务）：
 *   python3 server.py --database /tmp/erp-live-copy.db --test-pilot --port 8797
 *   node ops/ui_center_check.js --url http://127.0.0.1:8797 --pages workbench,inventory,dispatch
 *
 * 判定：|dy| > tolerance 像素即列出；只检查有居中语义的容器（按钮、导航行、状态块、卡片指标）。
 * 退出码：有偏差 1，无偏差 0。只读，不改数据，不替代截图自查。
 */
'use strict';
const path = require('path');

function loadPlaywright() {
  const candidates = [
    process.env.ERP_PLAYWRIGHT_MODULE,
    '/tmp/erp-playwright/node_modules/playwright-core',
    '/tmp/erp-playwright/node_modules/playwright',
    'playwright-core',
    'playwright',
  ].filter(Boolean);
  for (const c of candidates) {
    try { return require(c.startsWith('/') ? c : c); } catch (e) { /* next */ }
  }
  console.error('skip: 未找到 playwright，可运行 bash ops/browser_check.sh 先安装');
  process.exit(0);
}

const SCAN = () => {
  const CENTER = 'button,.button,.nav-item,.nav-section,.workspace-shortcut,.workflow-status,.metric,.grinding-system-card dd,.switch-label-full,.trip-flags>*,.status-chip,.tag,.badge';
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('#content *, #nav *, .sidebar *, #dialog-body *')) {
    if (!(el instanceof HTMLElement) || seen.has(el)) continue;
    // 表格单元格由表格布局按 vertical-align 居中，Range 会带上相邻空行；残留 1~2px 是字形度量，不是留白设置。
    if (el.tagName === 'TD' || el.tagName === 'TH') continue;
    seen.add(el);
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) continue;
    const box = el.getBoundingClientRect();
    if (box.width < 8 || box.height < 12 || box.height > 160) continue;
    const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!ownText) continue;
    const centered = cs.textAlign === 'center'
      || (cs.display.includes('flex') && (cs.alignItems === 'center' || cs.justifyContent === 'center'))
      || el.matches(CENTER);
    if (!centered) continue;
    const range = document.createRange();
    range.selectNodeContents(el);
    const ink = range.getBoundingClientRect();
    if (!ink.width || !ink.height) continue;
    const dy = (ink.top + ink.height / 2) - (box.top + box.height / 2);
    const dx = (ink.left + ink.width / 2) - (box.left + box.width / 2);
    if (Math.abs(dy) <= window.__tolerance) continue;
    const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    out.push({
      element: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (cls ? '.' + cls : ''),
      text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30),
      dy: Math.round(dy * 10) / 10,
      dx: Math.round(dx * 10) / 10,
      box: [Math.round(box.width), Math.round(box.height)],
      padding: cs.padding, margin: cs.margin, display: cs.display,
      align: cs.alignItems, justify: cs.justifyContent, lineHeight: cs.lineHeight,
    });
  }
  return out.sort((a, b) => Math.abs(b.dy) - Math.abs(a.dy)).slice(0, 40);
};

async function main() {
  const args = process.argv.slice(2);
  const opt = (name, def) => {
    const i = args.indexOf('--' + name);
    return i >= 0 && args[i + 1] ? args[i + 1] : def;
  };
  const url = opt('url', 'http://127.0.0.1:8797');
  const role = opt('role', '管理员');
  const tolerance = Number(opt('tolerance', '1.5'));
  const pages = (opt('pages', 'dashboard,orders,allocation,dispatch,production,factory,materials,transport-providers,settlements,ledger,archive,access')).split(',').filter(Boolean);
  const asJson = args.includes('--json');
  const dialogs = args.includes('--dialogs');
  const width = Number(opt('width', '1440'));
  const height = Number(opt('height', '900'));
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage({ viewport: { width, height } });
  const findings = {};
  let bad = 0;
  for (const name of pages) {
    await page.goto(url + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(600);
    try {
      await page.evaluate(({ r, p }) => { role = r; page = p; render(); }, { r: role, p: name });
    } catch (e) {
      findings[name] = { error: String(e.message || e).slice(0, 200) };
      bad += 1;
      continue;
    }
    await page.waitForTimeout(900);
    await page.evaluate(t => { window.__tolerance = t; }, tolerance);
    const rows = await page.evaluate(SCAN);
    findings[name] = rows;
    bad += rows.length;
    if (dialogs) {
      const labels = await page.evaluate(() => [...document.querySelectorAll('#content button')].filter(b => {
        const t = (b.textContent || '').trim();
        return /登记|新增|添加|修改|设置/.test(t) && !/删除|作废|保存|提交|确认/.test(t) && b.offsetParent !== null;
      }).slice(0, 3).map(b => (b.textContent || '').trim().slice(0, 20)));
      for (const label of labels) {
        const opened = await page.evaluate((text) => {
          const b = [...document.querySelectorAll('#content button')].find(x => (x.textContent || '').trim().startsWith(text));
          if (!b) return false;
          b.click();
          return true;
        }, label).catch(() => false);
        if (!opened) continue;
        await page.waitForTimeout(700);
        const has = await page.evaluate(() => !!document.querySelector('#dialog-body'));
        if (!has) continue;
        const drows = await page.evaluate(SCAN);
        findings[name + '/弹窗:' + label] = drows;
        bad += drows.length;
        await page.evaluate(() => {
          const close = document.querySelector('#dialog-body button[data-dialog-close],#dialog-body [data-dialog-close],#dialog-body .dialog-close,.dialog-close');
          if (close) close.click();
          else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        });
        await page.waitForTimeout(400);
        await page.evaluate(() => { const b = [...document.querySelectorAll('#dialog-body button')].find(x => (x.textContent || '').trim() === '取消'); b && b.click(); });
      }
    }
  }
  await browser.close();
  if (asJson) {
    console.log(JSON.stringify(findings, null, 2));
  } else {
    for (const [name, rows] of Object.entries(findings)) {
      console.log('== ' + name + ' ==');
      if (!Array.isArray(rows)) { console.log('  error:', rows.error); continue; }
      if (!rows.length) { console.log('  ok'); continue; }
      for (const r of rows) {
        console.log(`  dy=${String(r.dy).padStart(5)} dx=${String(r.dx).padStart(5)} ${r.element} [${r.box[0]}x${r.box[1]}] pad=${r.padding} align=${r.align}/${r.justify} lh=${r.lineHeight} «${r.text}»`);
      }
    }
  }
  process.exit(bad ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
