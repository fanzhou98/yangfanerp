const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function fixture() {
  const nodes = {}, clicks = [], store = {};
  const document = {
    addEventListener(type, handler) { if (type === 'click') clicks.push(handler); },
    get cookie() { return ''; },
    getElementById(id) { return nodes[id] || null; },
    createElement() {
      const el = { id: '', className: '', innerHTML: '', dataset: {}, remove() { delete nodes[el.id]; } };
      return el;
    },
    body: { append(el) { nodes[el.id] = el; } },
  };
  const ctx = {
    window: { addEventListener() {} },
    document,
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
    setInterval() {}, console, setTimeout,
    $: () => null, pageTrail: [], clearWorkingCopies() {}, busy: false, managedUsers: [], data: undefined,
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('web/auth-ui.js', 'utf8'), ctx);
  return { ctx, nodes, clicks, store, run: code => vm.runInContext(code, ctx) };
}

function sessionAt(leftSeconds, idle = 1800) {
  return `setAuthSession({session_id:'S1',server_time:1000000,last_activity:${1000000 - (idle - leftSeconds)},expires_at:2000000,idle_timeout_seconds:${idle},user:{id:'U1'}})`;
}

// 1. 剩余 5 分钟：提前 180 秒才提醒，此时不出提示
let f = fixture();
f.run(sessionAt(300));
assert.equal(f.run('authIdleWarning()'), null);

// 2. 剩余 50 秒：出提示，分钟取上整
f = fixture();
f.run(sessionAt(50));
assert.match(f.run('authIdleWarning()'), /登录将在 1 分钟后超时，未保存的修改会丢失。/);

// 3. 剩余 121 秒：提示 3 分钟
f = fixture();
f.run(sessionAt(121));
assert.match(f.run('authIdleWarning()'), /3 分钟/);

// 4. 渲染：生成浮条且不重复插入；点击“继续使用”刷新活动时间后浮条消失
f = fixture();
f.run(sessionAt(50));
f.run('renderAuthIdleWarning()');
assert.ok(f.nodes['auth-idle-warning'], '应渲染 #auth-idle-warning');
assert.match(f.nodes['auth-idle-warning'].innerHTML, /data-auth-idle-extend/);
const first = f.nodes['auth-idle-warning'];
f.run('renderAuthIdleWarning()');
assert.equal(f.nodes['auth-idle-warning'], first, '重复渲染不应插入第二个浮条');
assert.ok(f.clicks.length >= 1, '应注册点击委托');
for (const handler of f.clicks) handler({ target: { closest: sel => (sel === '[data-auth-idle-extend]' ? {} : null) } });
assert.equal(f.run('authIdleWarning()'), null, '继续使用后剩余时间应回到完整空闲期');
f.run('renderAuthIdleWarning()');
assert.equal(f.nodes['auth-idle-warning'], undefined, '浮条应被移除');

// 5. 未登录不提示
f = fixture();
assert.equal(f.run('authIdleWarning()'), null);
f.run('renderAuthIdleWarning()');
assert.equal(f.nodes['auth-idle-warning'], undefined);

console.log('auth idle warning ok');
