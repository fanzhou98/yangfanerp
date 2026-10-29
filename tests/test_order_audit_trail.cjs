// 订单操作轨迹与“核对记录”读取方式的前端回归（v0.97.0）：
// 1) 订单详情：匿名直接读 bootstrap.audit；登录后管理员/具备 system.audit 的岗位按对象异步读 /api/audit；
//    无操作记录权限的岗位不渲染、不发请求。
// 2) 保存失败后的“核对记录”：登录且有权限时单独读 /api/audit?all=1&page_size=200，再按本次 ids 过滤
//    slice(0,8)，保持 v0.96.0“最近 200 条内的相关行”口径；无权限的账号给出“联系管理员”的指引，不静默消失。
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const start = src.indexOf('function canReadAuditTrail');
const end = src.indexOf('function detail(id){');
const checkStart = src.indexOf('async function checkLatestRecords');
const checkEnd = src.indexOf('function readState(');
if (start < 0 || end < 0 || checkStart < 0 || checkEnd < 0) { console.log('EXTRACT FAILED'); process.exit(1); }
const trailBody = src.slice(start, end);
const checkBody = src.slice(checkStart, checkEnd);

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
}
function amount(cents) { return '¥' + (Number(cents || 0) / 100).toFixed(2); }

const results = [];
function check(name, ok, detail) { results.push([name, !!ok, detail]); }

// ---- 订单详情操作轨迹：从 app.js 抽取 canReadAuditTrail/orderAuditMarkup/orderAuditTrail/loadOrderAuditTrail ----
function buildTrail(data, opts = {}) {
  const timers = [];
  const calls = [];
  const elements = opts.elements || [];
  const document = { querySelectorAll() { return elements; } };
  const api = async (p) => { calls.push(p); if (opts.apiThrows) throw new Error('boom'); return opts.apiResult || {rows: []}; };
  const setTimeout = (fn, ms) => { timers.push([fn, ms]); return timers.length; };
  const factory = new Function('data', 'esc', 'api', 'document', 'setTimeout',
    trailBody + '\nreturn {canReadAuditTrail, orderAuditMarkup, orderAuditTrail, loadOrderAuditTrail};');
  return { api: factory(data, esc, api, document, setTimeout), timers, calls };
}

(async () => {
  const rows = [
    {id: 12, at: '2026-10-29T10:20:30+08:00', role: '库管', action: '创建订货单', entity: 'SO-1'},
    {id: 11, at: '2026-10-29T10:19:00+08:00', role: '管理员', action: '复核 <script>', entity: 'SO-1'},
  ];
  const v096 = list => `<h3 class="section-heading">操作轨迹</h3>` +
    list.map(a => `<p class="help-text">${esc(a.at.replace('T', ' '))} · ${esc(a.role)} · ${esc(a.action)}</p>`).join('');

  // 1 anonymous: markup must equal v0.96.0 template byte-for-byte
  {
    const data = {auth_user: null, permissions: {modules: []}, audit: rows};
    const env = buildTrail(data);
    const got = env.api.orderAuditTrail({id: 'SO-1'});
    check('anonymous_markup_equals_v096_template', got === v096(rows), got.slice(0, 60));
    check('anonymous_no_placeholder', !got.includes('data-order-audit'), got.slice(-40));
    check('anonymous_no_request', env.calls.length === 0, String(env.calls.length));
  }
  // 2 anonymous zero rows: v0.96.0 rendered a bare heading, v0.97.0 renders nothing
  {
    const env = buildTrail({auth_user: null, permissions: {modules: []}, audit: []});
    check('anonymous_zero_rows_empty', env.api.orderAuditTrail({id: 'SO-0'}) === '', '');
  }
  // 3 non-admin (库管 without system.audit): '' and no request/timer
  {
    const env = buildTrail({auth_user: {role: '库管'}, permissions: {modules: ['production.manage']}, audit: []});
    const got = env.api.orderAuditTrail({id: 'SO-1'});
    check('non_admin_empty', got === '', got);
    check('non_admin_no_timer', env.timers.length === 0, String(env.timers.length));
    check('non_admin_no_request', env.calls.length === 0, String(env.calls.length));
  }
  // 4 non-admin role but system.audit module: placeholder + request
  {
    const env = buildTrail({auth_user: {role: '会计'}, permissions: {modules: ['system.audit']}, audit: []});
    const got = env.api.orderAuditTrail({id: 'SO-1'});
    check('audit_module_placeholder', got === '<div data-order-audit="SO-1"></div>', got);
    check('audit_module_schedules', env.timers.length === 1, String(env.timers.length));
  }
  // 5 admin: placeholder, then loader replaces slot with rows sorted id desc
  {
    const slot = {dataset: {orderAudit: 'SO-1'}, outerHTML: 'PLACEHOLDER'};
    const env = buildTrail({auth_user: {role: '管理员'}, permissions: {modules: []}, audit: []},
      {apiResult: {rows: [rows[1], rows[0]]}, elements: [slot]});
    const got = env.api.orderAuditTrail({id: 'SO-1'});
    await env.timers[0][0]();
    check('admin_placeholder', got === '<div data-order-audit="SO-1"></div>', got);
    check('admin_request_url', env.calls[0] === '/api/audit?all=1&entity=SO-1&page_size=200', env.calls[0]);
    check('admin_rows_sorted_id_desc', slot.outerHTML === v096([rows[0], rows[1]]), slot.outerHTML.slice(0, 80));
  }
  // 6 entity id needing encoding + escaping
  {
    const env = buildTrail({auth_user: {role: '管理员'}, permissions: {modules: []}, audit: []},
      {apiResult: {rows: []}, elements: []});
    const id = 'SO-1&x=2';
    const got = env.api.orderAuditTrail({id});
    await env.timers[0][0]();
    check('entity_encoded_in_url', env.calls[0] === '/api/audit?all=1&entity=SO-1%26x%3D2&page_size=200', env.calls[0]);
    check('entity_escaped_in_markup', got === '<div data-order-audit="SO-1&amp;x=2"></div>', got);
  }
  // 7 zero-row loader clears the placeholder without leaving a heading
  {
    const slot = {dataset: {orderAudit: 'SO-0'}, outerHTML: 'PLACEHOLDER'};
    const env = buildTrail({auth_user: {role: '管理员'}, permissions: {modules: []}, audit: []},
      {apiResult: {rows: []}, elements: [slot]});
    env.api.orderAuditTrail({id: 'SO-0'});
    await env.timers[0][0]();
    check('zero_rows_clears_placeholder', slot.outerHTML === '', JSON.stringify(slot.outerHTML));
  }
  // 8 request failure clears the placeholder
  {
    const slot = {dataset: {orderAudit: 'SO-1'}, outerHTML: 'PLACEHOLDER'};
    const env = buildTrail({auth_user: {role: '管理员'}, permissions: {modules: []}, audit: []},
      {apiThrows: true, elements: [slot]});
    env.api.orderAuditTrail({id: 'SO-1'});
    await env.timers[0][0]();
    check('request_failure_clears', slot.outerHTML === '', JSON.stringify(slot.outerHTML));
  }

  // ---- 保存失败后的“核对记录”：从 app.js 抽取 checkLatestRecords ----
  function buildCheck(opts = {}) {
    const calls = [];
    const api = async (p) => {
      calls.push(p);
      if (p === '/api/bootstrap') return opts.fresh;
      if (p.startsWith('/api/audit')) { if (opts.trailThrows) throw new Error('read fail'); return {rows: opts.trail || [], total: (opts.trail || []).length}; }
      throw new Error('unexpected ' + p);
    };
    const result = {hidden: true, textContent: '', innerHTML: ''};
    const box = {querySelector: () => result, operationFailure: {request: {ids: opts.ids ?? ['SO-1']}}};
    const button = {disabled: false, isConnected: true, closest: () => box};
    const factory = new Function('api', 'esc', 'amount', 'canReadAuditTrail', 'setTimeout',
      checkBody + '\nreturn checkLatestRecords;');
    const fn = factory(api, esc, amount, () => opts.canAudit !== false, () => {});
    return {run: async () => { await fn(button); return result; }, calls, result};
  }
  const freshAdmin = {
    auth_user: {role: '管理员'},
    orders: [{id: 'SO-1', customer_name: '客户甲', status: '已复核', version: 3}],
    purchasing: {orders: []},
    receipts: [],
    audit: [],
  };
  const trailRows = Array.from({length: 10}, (_, i) => (
    {id: 100 - i, at: '2026-10-29T10:0' + (i % 10) + ':00+08:00', role: i === 0 ? '管理员' : '库管',
      action: '提交第' + i + '次', entity: 'SO-1'}));
  trailRows.push({id: 3, at: '2026-10-29T09:00:00+08:00', role: '库管', action: '另一张单', entity: 'PO-9'});

  // 9 管理员：bootstrap 不再带 audit，核对记录改为单独读 /api/audit?all=1&page_size=200，再按 ids 过滤 slice(0,8)
  {
    const env = buildCheck({fresh: freshAdmin, trail: trailRows});
    const out = await env.run();
    const expected = trailRows.filter(a => String(a.entity).includes('SO-1')).slice(0, 8);
    check('check_admin_requests_audit_once', env.calls.join(',') === '/api/bootstrap,/api/audit?all=1&page_size=200', env.calls.join(','));
    check('check_admin_renders_recent_related', out.innerHTML.includes('最近相关操作'), out.innerHTML.slice(0, 80));
    check('check_admin_slice_0_8', (out.innerHTML.match(/<li>/g) || []).length === 8, String((out.innerHTML.match(/<li>/g) || []).length));
    check('check_admin_matches_v096_semantics', expected.every(a => out.innerHTML.includes(`${esc(a.at)} · ${esc(a.actor_name || a.role)} · ${esc(a.action)} · ${esc(a.entity)}`)), '');
    check('check_admin_excludes_other_entities', !out.innerHTML.includes('PO-9'), '');
    check('check_admin_keeps_old_hint', out.innerHTML.includes('经办人核对'), '');
  }
  // 10 有 system.audit 的非管理员岗位同样按权限读取
  {
    const env = buildCheck({fresh: {...freshAdmin, auth_user: {role: '会计'}}, trail: trailRows, canAudit: true});
    const out = await env.run();
    check('check_audit_module_reads', env.calls.length === 2 && out.innerHTML.includes('最近相关操作'), env.calls.join(','));
  }
  // 11 无 system.audit：不发请求、不静默消失，改为“联系管理员”的指引且不再提“经办人”
  {
    const env = buildCheck({fresh: {...freshAdmin, auth_user: {role: '库管'}}, trail: trailRows, canAudit: false});
    const out = await env.run();
    check('check_non_admin_no_audit_request', env.calls.join(',') === '/api/bootstrap', env.calls.join(','));
    check('check_non_admin_no_blank_audit', !out.innerHTML.includes('最近相关操作') && !out.innerHTML.includes('<ul><li>'), '');
    check('check_non_admin_guidance', out.innerHTML.includes('操作记录页查看') && out.innerHTML.includes('联系管理员'), '');
    check('check_non_admin_drops_operator_wording', !out.innerHTML.includes('经办人'), '');
  }
  // 12 匿名/演示态仍直接用 bootstrap.audit，不请求 /api/audit
  {
    const env = buildCheck({fresh: {auth_user: null, orders: [], purchasing: {orders: []}, receipts: [], audit: [rows[0]]}});
    const out = await env.run();
    check('check_anonymous_uses_bootstrap_audit', env.calls.join(',') === '/api/bootstrap' && out.innerHTML.includes('最近相关操作'), env.calls.join(','));
    check('check_anonymous_keeps_old_hint', out.innerHTML.includes('经办人核对'), '');
  }
  // 13 /api/audit 失败不拖垮核对：表格照常显示，轨迹省略
  {
    const env = buildCheck({fresh: freshAdmin, trail: trailRows, trailThrows: true});
    const out = await env.run();
    check('check_audit_failure_keeps_table', env.calls.length === 2 && out.innerHTML.includes('<table') && !out.innerHTML.includes('最近相关操作'), out.innerHTML.slice(0, 60));
    check('check_audit_failure_no_error_state', !out.textContent.startsWith('最新记录读取失败'), out.textContent);
  }
  // 14 无 ids 时保持 v0.96.0 的“取最近 8 条相关行”行为
  {
    const env = buildCheck({fresh: freshAdmin, trail: trailRows, ids: []});
    const out = await env.run();
    check('check_empty_ids_keeps_latest_8', (out.innerHTML.match(/<li>/g) || []).length === 8, String((out.innerHTML.match(/<li>/g) || []).length));
  }

  for (const [name, ok, detail] of results) console.log((ok ? 'PASS ' : 'FAIL ') + name + ' :: ' + detail);
  if (results.some(r => !r[1])) process.exit(2);
})();
