const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const storage=new Map();const ctx={document:{addEventListener(){}},window:{addEventListener(){}},structuredClone,console,selectedDate:'2026-10-19',today:()=>'2026-10-19',role:'会计',busy:false,num:String,esc:x=>String(x??''),badge:o=>o.state||'',notify(){},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
 data:{delivery_vehicles:[{id:'V001',name:'车 A'},{id:'V002',name:'车 B'}],delivery_markets:[{id:'M1',name:'新联',city:'乌鲁木齐'},{id:'M2',name:'北园春',city:'乌鲁木齐'},{id:'M3',name:'岐峰',city:'昌吉'}],dispatch_plans:[],orders:[],customers:[{id:'C1',name:'甲',route:'新联'}],products:[]}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/forms.js','utf8')+'\n'+fs.readFileSync('web/dispatch.js','utf8')+'\nthis.h={dispatchWorking,dispatchDirty,dispatchPayload,persistDispatchDrafts,restoreDispatchDrafts,orderTripId,customerTripId,isPickupOrder,renderDispatchSummary};',ctx);
const plan=ctx.h.dispatchWorking();assert.equal(plan.trips.length,3);assert.equal(plan.trips[0].vehicle_id,plan.trips[1].vehicle_id);assert.notEqual(plan.trips[1].vehicle_id,plan.trips[2].vehicle_id);
assert.equal(plan.assignments[2].trip_id,'CJ-PM');assert.equal(plan.assignments[2].sequence,1);
plan.trips[0].driver='下午司机';plan.trips[1].driver='晚班司机';plan.assignments[0].trip_id='WLMQ-N1';assert.equal(ctx.h.dispatchDirty('2026-10-19'),true);
ctx.h.persistDispatchDrafts();assert.equal(storage.size,0);ctx.h.restoreDispatchDrafts();assert.equal(ctx.h.dispatchWorking().trips[1].driver,'晚班司机');
const saved=JSON.parse(JSON.stringify(ctx.h.dispatchWorking()));saved.order_markets={O1:'M1'};ctx.data.dispatch_plans=[saved];
const o={id:'O1',customer_id:'C1',business_date:'2026-10-19'};
assert.equal(ctx.h.orderTripId(o),'WLMQ-N1');ctx.data.customers[0].route='北园春';assert.equal(ctx.h.orderTripId(o),'WLMQ-N1');
assert.equal(ctx.h.orderTripId({...o,business_date:'2026-10-20'}),'');
ctx.data.delivery_markets.push({id:'M4',name:'临时监狱配送点',city:'其他'});assert.equal(ctx.h.dispatchWorking().assignments.length,4);
assert.equal(ctx.h.dispatchWorking().trips[0].driver,'下午司机');
ctx.data.customers[0].market_id='M1';assert.equal(ctx.h.customerTripId(ctx.data.customers[0],'2026-10-19'),'WLMQ-N1');
ctx.data.customers[0].delivery_method='pickup';
assert.equal(ctx.h.orderTripId(o),'pickup');assert.equal(ctx.h.customerTripId(ctx.data.customers[0],'2026-10-19'),'pickup');
assert.equal(ctx.h.orderTripId({...o,delivery_method:'delivery'}),'WLMQ-N1');
ctx.data.orders=[{...o,customer_name:'自取客户',route:'五彩湾',state:'draft',lines:[{product_id:'P1',product_name:'大豆腐',unit:'筐',ordered_qty:'8',actual_qty:'0'}]}];
const html=ctx.h.renderDispatchSummary(saved);assert.ok(html.includes('客户自取 · 1 张订单'));assert.ok(!html.includes('待分配 · 1'));assert.ok(!html.includes('1 张订单尚未记录市场归属'));
console.log('两车三趟、分趟司机、市场拓展、自取分流及排车编辑不写浏览器缓存校验通过');
