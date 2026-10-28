const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const storage=new Map();const ctx={document:{addEventListener(){}},window:{addEventListener(){}},console,structuredClone,role:'会计',busy:false,needRole:()=>true,render(){},num:String,setTimeout:()=>0,clearTimeout(){},notify(){},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
 data:{customers:[{id:'C1',name:'测试客户'}],products:[{id:'P1',name:'筐装产品',unit:'筐',price:'3.6',tare:'1.8'},{id:'P2',name:'包装产品',unit:'包',price:'75',tare:'0'}],rules:[],orders:[]}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/forms.js','utf8')+'\n'+fs.readFileSync('web/sheets.js','utf8')+'\nthis.h={operationIssues,pricingRow,pricingDirty,persistDrafts,restoreInputDrafts,workingOrder,orderDirty,moveProduct,productDisplayList,productOrderDirty};',ctx);
const body={customer_id:'C1',business_date:'2026-10-19',batch:'试验',lines:[{product_id:'P1',ordered_qty:'2',actual_qty:'2',price:'3.6',driver:[],customer:[]},{product_id:'P2',ordered_qty:'5',actual_qty:'0',price:'75',driver:[],customer:[]}]};
const o={...body,id:'O1',version:1,state:'dispatched',paid_cents:0,note:''};ctx.data.orders=[o];
let issues=ctx.h.operationIssues([{action:'settle',order_id:'O1',body:{version:1,mode:'customer'},update:body}]);
assert.ok(!issues.some(i=>i.product_id==='P1'&&i.source==='driver'&&i.field==='gross'));
assert.ok(issues.some(i=>i.product_id==='P1'&&i.source==='customer'&&i.field==='gross'));
assert.ok(issues.some(i=>i.product_id==='P2'&&i.field==='not_shipped'));
body.lines[0].driver=[{gross:'23.6',count:'2',tare:'1.8'}];body.lines[0].customer=[{gross:'22.6',count:'2',tare:'1.8'}];body.lines[1].not_shipped=true;
issues=ctx.h.operationIssues([{action:'settle',order_id:'O1',body:{version:1,mode:'customer'},update:body}]);assert.equal(issues.length,0);
body.lines[0].customer[0].count='3';issues=ctx.h.operationIssues([{action:'order',order_id:'O1',body}]);assert.ok(issues.some(i=>i.source==='customer'&&i.index===0&&i.field==='count'));
body.lines[0].customer[0].count='2';const working=ctx.h.workingOrder(o);working.lines[0].price='尚未填好';const rule=ctx.h.pricingRow('C1','P1');rule.price='8';assert.equal(ctx.h.pricingDirty(rule),true);
ctx.h.persistDrafts();assert.equal(storage.size,0);
ctx.h.restoreInputDrafts();
assert.equal(ctx.h.workingOrder(o).lines[0].price,'尚未填好');assert.equal(ctx.h.orderDirty(ctx.h.workingOrder(o)),true);assert.equal(ctx.h.pricingRow('C1','P1').price,'8');
ctx.h.moveProduct('P2',0);
assert.deepEqual(JSON.parse(JSON.stringify(ctx.h.productDisplayList().map(p=>p.id))),['P2','P1']);
assert.deepEqual(ctx.data.products.map(p=>p.id),['P1','P2']);
assert.equal(ctx.h.productOrderDirty(),true);
assert.equal(ctx.h.workingOrder(o).lines[0].price,'尚未填好');
ctx.h.moveProduct('P2',1);assert.equal(ctx.h.productOrderDirty(),false);vm.runInContext('productOrderDraft=null;',ctx);ctx.h.restoreInputDrafts();assert.deepEqual(JSON.parse(JSON.stringify(ctx.h.productDisplayList().map(p=>p.id))),['P1','P2']);
console.log('字段定位、未发货确认、产品排序、编辑内存保留且不写浏览器草稿校验通过');

body.lines[0].driver=[];o.delivery_method='pickup';
issues=ctx.h.operationIssues([{action:'settle',order_id:'O1',body:{version:1,mode:'customer'},update:{...body,delivery_method:'pickup'}}]);
assert.equal(issues.filter(i=>i.source==='driver').length,0);
