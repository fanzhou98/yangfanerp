const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={document:{addEventListener(){}},window:{addEventListener(){}},structuredClone,console,
 page:'settlements',busy:false,selectedDate:'2026-10-19',today:()=>'2026-10-19',role:'会计',
 esc:x=>String(x??''),badge:o=>o.state,goto:p=>ctx.destination=p,render:()=>{},
 accountingDateContext:()=>'',data:{customers:[{id:'C1',name:'客户甲',route:'线路甲'},{id:'C2',name:'客户乙',route:'线路乙'}],products:[],orders:[]}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('web/operations.js','utf8')+'\n'+fs.readFileSync('web/forms.js','utf8')+'\n'+fs.readFileSync('web/sheets.js','utf8')+'\nthis.h={openSettlementTodos,processingGroups,settlementStages,sheetAction,sheetControls,workingOrder,orderDirty,isSettlementTodo};',ctx);
const base={version:1,customer_id:'C1',customer_name:'客户甲',route:'线路甲',batch:'夜间',note:'',lines:[]};
ctx.data.orders=[
 {...base,id:'O-OLD',business_date:'2026-10-18',state:'negotiation'},
 {...base,id:'O-NEW',business_date:'2026-10-19',state:'ready'},
 {...base,id:'O-DRAFT',business_date:'2026-10-19',state:'dispatched'},
 {...base,id:'O-DONE',business_date:'2026-10-17',state:'reviewed'},
 {...base,id:'O-OTHER',customer_id:'C2',customer_name:'客户乙',route:'线路乙',business_date:'2026-10-16',state:'ready'}];
const ids=()=>JSON.parse(JSON.stringify(ctx.h.processingGroups().flatMap(g=>g.orders).map(o=>o.id)));
assert.deepEqual(ids(),['O-NEW','O-DRAFT']);
// The sidebar count and overview must find the same orders despite stale page filters.
vm.runInContext("sheetRoute='不存在';sheetSearch='无结果';processingBatch='旧批次';sheetStatus='reviewed'",ctx);
const draft=ctx.h.workingOrder(ctx.data.orders[0]);draft.note='未保存的协商输入';
ctx.selectedDate='';ctx.h.openSettlementTodos();
assert.equal(ctx.selectedDate,'2026-10-18');assert.equal(ctx.destination,'settlements');
assert.deepEqual(ids(),['O-OLD']);
assert.equal(ctx.h.workingOrder(ctx.data.orders[0]).note,'未保存的协商输入');
assert.equal(ctx.h.orderDirty(draft),true);
assert(!ctx.h.settlementStages().some(([key])=>key==='todo'),'取消重复待处理总览页签');
assert.ok(ctx.h.sheetControls('account').includes('2026-10-18'));
ctx.selectedDate='2026-10-17';ctx.h.openSettlementTodos();assert.equal(ctx.selectedDate,'2026-10-17','再次打开保留用户选定日期');
(async()=>{
 await ctx.h.sheetAction('open-pending-order',{dataset:{id:'O-OLD'}});
 assert.equal(ctx.selectedDate,'2026-10-18');assert.deepEqual(ids(),['O-OLD']);
 await ctx.h.sheetAction('today',{});assert.equal(ids().length,0); // exact order search remains active
 ctx.h.openSettlementTodos();await ctx.h.sheetAction('today',{});assert.deepEqual(ids(),['O-DRAFT']);
 await ctx.h.sheetAction('all-dates',{});assert.equal(ids().length,2);
 assert.equal(ctx.h.workingOrder(ctx.data.orders[0]).note,'未保存的协商输入');
 console.log('跨日期待处理数量一致、逐单定位、日期切换及草稿保留校验通过');
})().catch(e=>{console.error(e);process.exitCode=1;});
