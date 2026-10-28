const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let labels=['订货数量 · 1 位客户'],writes=0;const listeners={},timers=[],microtasks=[],status={dataset:{}},compact={dataset:{}},workText={},hint={};
const bar={dataset:{},querySelector:selector=>selector==='[data-work-save]'?workText:selector==='[data-work-next]'?hint:null};
const ctx={Date,console,data:{},page:'orders',role:'库管',lastReadTime:'10:00:00',
 document:{addEventListener:(type,fn)=>listeners[type]=fn},
 $:selector=>selector==='#save-status'?status:selector==='#compact-save-status'?compact:selector==='#work-status-bar'?bar:null,
 setInterval:(fn,ms)=>timers.push(ms),setTimeout:(fn,ms)=>timers.push(ms),queueMicrotask:fn=>microtasks.push(fn),
 unsavedChanges:()=>labels,api:()=>{writes++;throw Error('status must not write')},saveCurrentEdits:()=>{writes++;throw Error('status must not save')}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/autosave.js','utf8')+'\nthis.h={updateSaveStatus,recordServerSave,setSaveIssue,resetSaveStatus};',ctx);
ctx.h.updateSaveStatus();assert.equal(status.dataset.state,'dirty');assert.match(status.textContent,/点击保存按钮/);assert.equal(compact.textContent,'有待保存内容');assert.deepEqual(timers,[]);assert.equal(writes,0);
assert.equal(bar.hidden,false);assert.equal(hint.hidden,true);assert.equal(workText.textContent,'有未保存修改，请点击保存按钮');
for(let i=0;i<100;i++){listeners.input({target:{closest:()=>true}});listeners.change({target:{closest:()=>true}});}microtasks.splice(0).forEach(fn=>fn());assert.deepEqual(timers,[]);assert.equal(writes,0);assert.equal(vm.runInContext('typeof maybeAutosave',ctx),'undefined');
labels=[];ctx.h.recordServerSave();assert.equal(status.dataset.state,'saved');assert.match(status.textContent,/本页改动已保存/);assert.equal(compact.textContent,'改动已保存');
assert.equal(bar.hidden,false); // Saved confirmation remains visible on the current page.
ctx.page='weighing';ctx.h.updateSaveStatus();assert.equal(status.textContent,'当前没有未保存修改');
assert.equal(bar.hidden,true);assert.equal(compact.hidden,true);
labels=['当前窗口的表单'];ctx.h.updateSaveStatus();assert.equal(status.dataset.state,'dirty');assert.match(status.textContent,/点击保存按钮/);
ctx.h.setSaveIssue('记录已被更新，请核对');assert.equal(status.dataset.state,'error');assert.equal(compact.title,'记录已被更新，请核对');listeners.input({target:{closest:()=>true}});microtasks.splice(0).forEach(fn=>fn());assert.equal(status.dataset.state,'error');
assert.equal(bar.hidden,false);assert.equal(compact.hidden,false);
ctx.h.resetSaveStatus();labels=[];ctx.role='老板';ctx.h.updateSaveStatus();assert.equal(status.textContent,'当前为只读查看');assert.equal(compact.textContent,'只读查看');assert.equal(writes,0);
console.log('手动保存状态、输入后不发请求、不创建定时器、冲突提示、跨页状态及老板只读检查通过');
