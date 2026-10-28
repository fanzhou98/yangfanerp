const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const granted=new Set(['orders.write','weight.write','finance.settle']);
const ctx={document:{addEventListener(){}},window:{addEventListener(){}},structuredClone,
 esc:x=>String(x??''),num:x=>String(x),canAction:x=>granted.has(x),allocatedQuantity:()=>null,data:{stock_closings:[]}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/sheets.js','utf8')+'\n'+fs.readFileSync('web/order-corrections.js','utf8'),ctx);
const c={name:'客户甲'},l={product_id:'P001',product_name:'大豆腐',actual_qty:'8'},o={id:'O1',state:'dispatched',business_date:'2026-10-22',review_return:{status:'pending'}};
const cell=()=>ctx.shipmentQuantityCell(c,o,l,0);
assert(cell().includes('data-order-correction="shipment"'));assert(!cell().includes('disabled'));assert(!cell().includes('先在发货分配'));
ctx.data.stock_closings=[{state:'closed',business_date:'2026-10-23'}];assert(cell().includes('已日结'));assert(!cell().includes('disabled'));
for(const state of ['draft','dispatched','negotiation']){o.state=state;assert.equal(ctx.orderStageKey(o),'rework');assert(cell().includes('data-focus-product="P001"'));}
for(const state of ['ready','reviewed']){o.state=state;assert(!cell().includes('data-order-correction'));}
o.state='dispatched';o.paid_cents=100;assert(!cell().includes('data-order-correction'));o.paid_cents=0;
granted.delete('finance.settle');assert(!cell().includes('data-order-correction'));granted.add('finance.settle');
o.review_return=null;ctx.data.stock_closings=[];assert(!cell().includes('data-order-correction'));assert(cell().includes('先在发货分配'));
ctx.allocatedQuantity=()=>8;assert(!cell().includes('disabled'));assert.equal(ctx.orderStageKey({state:'draft'}),'shipping');
console.log('退回实发入口覆盖旧新状态、零实发、日结和分配限制，并保留复核与收款权限');
