const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const storage=new Map(),ctx={document:{addEventListener(){}},window:{addEventListener(){}},structuredClone,URLSearchParams,selectedDate:'2026-10-20',today:()=>'2026-10-20',role:'库管',page:'weighing',busy:false,num:String,esc:String,notify(){},$:()=>null,
 localStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},
 data:{business_data_epoch:'0',customers:[{id:'C1',route:'新联',market_id:'M1'},{id:'C2',route:'北园春',market_id:'M2'},{id:'C3',route:'新联',market_id:'M1',delivery_method:'pickup'},{id:'C4',route:'新联',market_id:'M1'}],products:[{id:'P1',name:'豆腐',unit:'筐'}],delivery_markets:[{id:'M1',name:'新联',city:'乌鲁木齐'},{id:'M2',name:'北园春',city:'乌鲁木齐'},{id:'M3',name:'岐峰',city:'昌吉'}],orders:[],warehouse_plans:[],dispatch_plans:[]}};
vm.createContext(ctx);for(const f of ['forms','sheets','dispatch','warehouse'])vm.runInContext(fs.readFileSync(`web/${f}.js`,'utf8'),ctx);
vm.runInContext('this.h={marketSortedCustomers,dispatchActiveMarkets,allocatedQuantity,warehouseWorking,warehouseTotals,applyWarehouseInput,warehouseDirty,persistWarehouseDrafts,restoreWarehouseDrafts,autoFillActual,workingOrder,warehouseDrafts};',ctx);
const make=(cid,id)=>({id,version:1,state:'draft',customer_id:cid,business_date:'2026-10-20',batch:'日常订货',lines:[{product_id:'P1',ordered_qty:'8',actual_qty:'0',price:'3',driver:[],customer:[]}]});
const a=make('C1','A'),b=make('C2','B'),c=make('C3','C'),d=make('C4','D');ctx.data.orders=[a,b,c,d];
assert.deepEqual(Array.from(ctx.h.marketSortedCustomers(ctx.data.customers),c=>c.id),['C2','C1','C3','C4']);
const regionRows=[{id:'C8',region:'乌鲁木齐',market_id:'M1'},{id:'C7',region:'昌吉',market_id:'M1'},{id:'C6',region:'乌鲁木齐',market_id:'M2'},{id:'C5',route:'未设置'}];
assert.deepEqual(Array.from(ctx.h.marketSortedCustomers(regionRows),c=>c.id),['C7','C6','C8','C5']);
assert.deepEqual(Array.from(ctx.h.dispatchActiveMarkets({business_date:'2026-10-20'}),m=>m.id),['M1','M2']);
assert.equal(ctx.h.autoFillActual(),0);assert.equal(ctx.h.allocatedQuantity(a,a.lines[0]),null);
ctx.data.warehouse_plans=[{business_date:'2026-10-20',version:1,stock:[{product_id:'P1',existing_qty:'5',produced_qty:'2'}],customers:[],allocations:[{order_id:'A',product_id:'P1',qty:'6',ordered_qty:'8'},{order_id:'B',product_id:'P1',qty:'0',ordered_qty:'8'},{order_id:'D',product_id:'P1',qty:'1',ordered_qty:'7'}]}];
assert.equal(ctx.h.autoFillActual(),2);assert.equal(ctx.h.workingOrder(a).lines[0].actual_qty,'6');assert.equal(ctx.h.workingOrder(b).lines[0].not_shipped,true);assert.equal(ctx.h.workingOrder(c).lines[0].actual_qty,'0');assert.equal(ctx.h.workingOrder(d).lines[0].actual_qty,'0');assert.equal(a.lines[0].actual_qty,'0');
const plan=ctx.h.warehouseWorking(),t=ctx.h.warehouseTotals(plan,ctx.data.products[0]);assert.equal(t.ordered,32);assert.equal(t.available,7);assert.equal(t.allocated,15);assert.equal(t.adjustment,8);assert.equal(plan.allocations.find(a=>a.order_id==='C').qty,'8');
ctx.h.applyWarehouseInput({dataset:{stock:'P1',field:'existing_qty'},value:''});assert.equal(ctx.h.warehouseTotals(plan,ctx.data.products[0]).available,null);assert.equal(ctx.h.warehouseDirty('2026-10-20'),true);
ctx.h.persistWarehouseDrafts();assert.equal(storage.size,0);ctx.h.warehouseDrafts.clear();ctx.h.restoreWarehouseDrafts();assert.equal(ctx.h.warehouseWorking().stock[0].existing_qty,'5');
ctx.h.warehouseDrafts.clear();ctx.data.business_data_epoch='new';ctx.h.restoreWarehouseDrafts();assert.equal(ctx.h.warehouseDrafts.size,0);
console.log('按市场分组、无订货市场隐藏、按保存分配补实发、零分配、订货变更失效、未知库存与不写浏览器草稿检查通过');
ctx.h.warehouseDrafts.clear();ctx.data.warehouse_plans=[];const automatic=ctx.h.warehouseWorking();assert(automatic.allocations.every(a=>a.qty==='8'));assert.equal(ctx.data.orders[0].lines[0].actual_qty,'0');ctx.h.applyWarehouseInput({dataset:{allocationOrder:'A',productId:'P1'},value:'4'});assert.equal(automatic.allocations.find(a=>a.order_id==='A').mode,'manual');assert.equal(automatic.allocation_state,'draft');ctx.data.warehouse_plans=[{business_date:'2026-10-20',allocation_state:'draft',allocations:[{order_id:'A',product_id:'P1',ordered_qty:'8',qty:'8'}]}];assert.equal(ctx.h.allocatedQuantity(a,a.lines[0]),null);
console.log('默认全量预分配、手工调减保持独立、草稿不补实发检查通过');
