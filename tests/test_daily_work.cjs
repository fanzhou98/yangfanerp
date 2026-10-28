const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const day='2026-10-20',data={auth_user:null,products:[{id:'P1'}],orders:[{id:'today-order',business_date:day,state:'draft'},{id:'old-order',business_date:'2026-10-18',state:'ready'},{id:'future',business_date:'2026-10-22',state:'draft'}],warehouse_plans:[],stock_closings:[]},purchase={orders:[],receipts:[],charges:[],payments:[]},resources={entries:[],byproducts:[]},actions=new Set();
const ctx=vm.createContext({data,window:{addEventListener(){}},document:{getElementById(){return null;},addEventListener(){}},today:()=>day,purchaseData:()=>purchase,resourceData:()=>resources,canAction:key=>actions.has(key),moduleVisible:()=>true,orderOutstanding:o=>o.balance||0,esc:String,byproductSummary:()=>({value:{month_cents:0,outstanding:[]}})});resources.production_configs=[{version:0,effective_date:'0001-01-01',systems:[{id:'tofu',name:'豆腐磨浆系统',active:true},{id:'skin',name:'豆皮磨浆系统',active:true}],warehouses:[],processes:[],products:{}}];vm.runInContext(fs.readFileSync('web/production-config.js','utf8'),ctx);vm.runInContext(fs.readFileSync('web/daily-work.js','utf8'),ctx);
const run=(rows,date=day)=>ctx.enrichDailyTasks(rows.map(r=>({items:[],...r})),date);
let tasks=run([{key:'orders.write'},{key:'inventory.stock'},{key:'inventory.close'}]);assert.equal(tasks[0].status,'已完成');assert.equal(tasks[1].today,1);assert.equal(tasks[1].carry,1);assert.equal(tasks[2].items.length,2);assert(!tasks[1].items.some(x=>x.business_date>day));assert(ctx.dailyWorkReminder(tasks,day).includes('历史遗留'));
data.warehouse_plans=[{business_date:day,stock:[{product_id:'P1',existing_qty:'0',produced_qty:'0'}]}];data.stock_closings=[{business_date:'2026-10-18',state:'closed'}];tasks=run([{key:'inventory.stock'},{key:'inventory.close'}]);assert.equal(tasks[0].status,'已完成');assert.equal(tasks[0].items.length,0);assert.equal(tasks[1].today,1);assert.equal(tasks[1].carry,0);assert.equal(tasks[1].status,'待处理');
tasks=run([{key:'finance.settle'},{key:'finance.review'}]);assert.equal(tasks[0].status,'等待称重');assert.equal(tasks[1].status,'等待算票');assert.equal(tasks[0].completed,0);
data.orders=[];tasks=run([{key:'orders.write'}]);assert.equal(tasks[0].status,'未开始');assert.equal(tasks[0].items.length,1);
actions.add('purchases.receive');purchase.orders=[{id:'PO-1',supplier_name:'供货方',state:'confirmed',business_date:'2026-10-15',expected_date:'2026-10-19',lines:[{remaining_qty:'10'}]},{id:'PO-FUTURE',state:'confirmed',business_date:'2026-10-15',expected_date:'2026-10-22',lines:[{remaining_qty:'10'}]}];tasks=run([]);assert.equal(tasks[0].key,'purchases.receive');assert.equal(tasks[0].carry,1);assert.equal(tasks[0].items[0].business_date,'2026-10-19');assert.equal(tasks[0].items.length,1);
actions.clear();actions.add('materials.value');resources.entries=[{id:'M1',business_date:'2026-10-18',kind:'receipt',amount_cents:0},{id:'M2',business_date:'2026-10-18',kind:'receipt',amount_cents:0,voided:true},{id:'M3',business_date:day,kind:'receipt',amount_cents:100}];tasks=run([]);assert.equal(tasks[0].items.length,1);assert.equal(tasks[0].carry,1);
console.log('Daily workflow completion, missing work, carryovers, future filtering and purchase/material reminders passed');

// Director work uses the same pending/carryover counts; completion clears reminders.
actions.clear();['production.attendance','production.record','materials.issue'].forEach(k=>actions.add(k));
const factory={daily:[{business_date:'2026-10-18'}],attendance:[{business_date:'2026-10-18',state:'draft'}]};ctx.factoryData=()=>factory;
resources.entries=[];tasks=run([]);assert.equal(tasks.length,4);assert.equal(tasks.find(t=>t.key==='production.schedule').carry,1);assert.equal(tasks.find(t=>t.key==='production.attendance').carry,1);assert.equal(tasks.find(t=>t.key==='production.record').today,1);assert.equal(tasks.find(t=>t.key==='materials.issue').items.length,2);
factory.attendance=[{business_date:'2026-10-18',state:'confirmed',entries:[{employee_id:'P1',status:'full'}]},{business_date:day,state:'confirmed',entries:[{employee_id:'P1',status:'full'}]}];factory.daily.push({business_date:day});
for(const d of ['2026-10-18',day])for(const warehouse_id of ['WH-TOFU','WH-SKIN'])resources.entries.push({business_date:d,material_id:'RM-SOY',kind:'consume',qty:'100',warehouse_id});
tasks=run([]);assert(tasks.every(t=>t.status==='已完成'&&t.items.length===0));
resources.entries.push({business_date:day,material_id:'RM-SOY',kind:'return',qty:'100',warehouse_id:'WH-SKIN'});assert.equal(run([]).find(t=>t.key==='materials.issue').today,1);
factory.daily.push({business_date:'2026-10-22'});assert(!run([]).some(t=>t.items.some(i=>i.business_date>day)));
console.log('Director missing attendance, production, two-line bean records, historical carryovers and completion clearing passed');

factory.attendance.forEach(r=>r.workflow='separate-v1');assert.equal(run([]).find(t=>t.key==='production.schedule').items.length,2);factory.schedules=factory.attendance.map(r=>({business_date:r.business_date,state:'confirmed'}));assert.equal(run([]).find(t=>t.key==='production.schedule').items.length,0);

// Management drafts cannot undo confirmed production attendance.
factory.employees=[{id:'P1',employee_type:'production'},{id:'M1',employee_type:'management'}];factory.attendance.forEach(r=>{r.state='draft';r.entries=[{employee_id:'P1',status:'full',entry_state:'confirmed'},{employee_id:'M1',status:'half',entry_state:'draft'}];});assert.equal(run([]).find(t=>t.key==='production.attendance').items.length,0);

// Deferred expenses retain full counts while rendering only bounded examples.
actions.clear();actions.add('costs.review');resources.expense_history_deferred=true;
ctx.resourceExpenseWorkflow=()=>({value:{groups:{'costs.review':{today:2,carry:65,completed:3,items:[{id:'SAMPLE',business_date:'2026-10-18',customer_name:'费用方'}]}}}});
tasks=run([]);const fee=tasks.find(t=>t.key==='costs.review');assert.equal(fee.items.length,1);assert.equal(fee.today,2);assert.equal(fee.carry,65);assert.equal(fee.completed,3);assert.equal(fee.status,'待处理');
console.log('Deferred fee reminders preserve complete today/carry counts with bounded samples');

// Deferred byproduct receivables summarize on demand, keeping loading and bounded items distinct.
actions.clear();actions.add('byproducts.receive');
ctx.byproductSummary=()=>({loading:true});tasks=run([]);let bean=tasks.find(t=>t.key==='byproducts.receive');assert.equal(bean.status,'读取中');assert.equal(bean.items.length,0);
ctx.byproductSummary=()=>({value:{outstanding:[{id:'B1',business_date:'2026-10-18',customer_name:'豆渣客户',amount_cents:5000,received_cents:0},{id:'B2',business_date:day,customer_name:'豆渣客户二',amount_cents:1000,received_cents:0}]}});
tasks=run([]);bean=tasks.find(t=>t.key==='byproducts.receive');assert.equal(bean.carry,1);assert.equal(bean.today,1);assert.equal(bean.status,'待处理');
console.log('Deferred byproduct receivables summarize on demand with bounded items');
