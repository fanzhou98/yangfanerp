const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function fixture(page = 'analytics', analyticsTab = 'profit') {
  let resolve, reject, renders = 0, requests = 0;
  const listeners = {};
  const response = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  const ctx = {
    page, analyticsTab, window:{addEventListener(){}},
    document: { addEventListener(type, handler) { (listeners[type] ||= []).push(handler); } },
    today: () => '2026-10-24', esc: String, num: String, yuan: String, amount: String,
    metrics: () => '汇总',reportFacts:()=> '汇总', reportValue: value => value==null?'待核对':String(value),reportContext:()=>'',reportGaps:()=>'', resourceTable: () => '产品明细',
    resourcePanel: (title, body) => title + body,
    api(url) { assert.equal(url, '/api/product-profit?month=2026-10'); requests++; return response; },
    render() { renders++; },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('web/owner.js', 'utf8'), ctx);
  return { ctx, listeners, resolve, reject, renders: () => renders, requests: () => requests };
}

const report = { total: {}, rows: [], basis: '测试口径' };
const flush = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const success = fixture();
  assert.match(success.ctx.productProfitPanel(), /正在计算/);
  success.ctx.productProfitPanel();
  assert.equal(success.requests(), 1);
  success.resolve(report);
  await flush();
  assert.equal(success.renders(), 1, '经营看板盈利页签完成请求后应刷新');
  assert.match(success.ctx.productProfitPanel(), /按产品盈亏/);
  assert.doesNotMatch(success.ctx.productProfitPanel(), /正在计算/);

  const failure = fixture();
  failure.ctx.productProfitPanel();
  failure.reject(new Error('报表读取失败'));
  await flush();
  assert.equal(failure.renders(), 1, '请求失败时应显示错误');
  assert.match(failure.ctx.productProfitPanel(), /报表读取失败/);

  const legacy = fixture('product-profit');
  legacy.ctx.productProfitPanel();
  legacy.resolve(report);
  await flush();
  assert.equal(legacy.renders(), 1, '原独立页面仍应刷新');

  const priced = fixture();
  priced.ctx.resourceTable = (headers, body) => body;
  priced.ctx.productProfitPanel();
  priced.resolve({ ...report, rows: [{ product_name: '测试产品', break_even_price: '640' }] });
  await flush();
  assert.match(priced.ctx.productProfitPanel(), /<td>6\.4<small>/, '640 分/公斤应显示为 6.4 元/公斤');
  let modal = '';
  Object.assign(priced.ctx, {
    selectedDate: '2026-10-24',
    openDialog: (title, body) => { modal = body; },
    err: error => { throw error; },
  });
  await priced.ctx.openProductProfit();
  assert.match(modal, /6\.4 元\/公斤/, '原弹窗应使用相同的元/公斤显示');

  for (const [page, tab] of [['orders', 'profit']]) {
    const away = fixture();
    away.ctx.productProfitPanel();
    away.ctx.page = page;
    away.ctx.analyticsTab = tab;
    away.resolve(report);
    await flush();
    assert.equal(away.renders(), 0, '离开盈利面板后不应重绘当前页面');
    assert.match(away.ctx.productProfitPanel(), /按产品盈亏/, '结果应保留供再次进入');
  }
  const integrated = fixture();
  Object.assign(integrated.ctx, {
    role: '管理员',
    data: { orders: [], customers: [], auth_user: { role: '管理员' } },
    head: (title, subtitle, actions) => actions || '',
    financeReadable: () => true, factoryReport:()=>({loading:true}),readState:()=>'',
  });
  vm.runInContext(fs.readFileSync('web/resources.js', 'utf8')+'\n'+fs.readFileSync('web/reports.js','utf8'), integrated.ctx);
  Object.assign(integrated.ctx,{reportContext:()=>'',reportGaps:()=>''});
  Object.assign(integrated.ctx, {
    resourcePanel: (title, body) => title + body,
    resourceTable: () => '产品明细', resourceTrend: () => '', moneyBars: () => '',
  });
  Object.assign(integrated.ctx, {
    factoryReport:()=>({value:{gross_cents:0,reviewed_orders:0,gaps:[],cost_cents:0}}),
    reportChart:()=>'',reportReturns:()=>'',
  });
  const overview = integrated.ctx.resourceAnalyticsPage();
  assert.doesNotMatch(overview, /data-analytics-tab=/, '经营看板不再显示重复页签');
  assert.match(overview, /id="product-estimate"/, '产品测算直接并入经营看板');
  assert.match(overview, /正在计算/);
  integrated.resolve(report);
  await flush();
  assert.equal(integrated.renders(), 1, '经营看板正文测算完成后刷新');
  assert.match(integrated.ctx.resourceAnalyticsPage(), /按产品盈亏/);
  console.log('产品测算并入经营看板、成功与失败刷新、请求去重及离开页面检查通过');
})().catch(error => { console.error(error); process.exitCode = 1; });
