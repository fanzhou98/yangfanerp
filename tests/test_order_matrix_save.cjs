const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={document:{addEventListener(){}},window:{addEventListener(){}},console,structuredClone,num:String,selectedDate:'2026-10-20',today:()=>'2026-10-19',role:'会计',localStorage:{setItem(){}},notify(){},setTimeout:()=>0,clearTimeout(){},esc:s=>String(s??''),badge:()=>'',
 data:{customers:[{id:'C1',name:'客户1',route:'市场'},{id:'C2',name:'客户2',route:'市场'}],products:[{id:'P1',name:'大豆腐',unit:'筐',price:'3.6',tare:'1'}],orders:[],rules:[]},
 defaultLine:pid=>({product_id:pid,ordered_qty:'1',actual_qty:'0',price:'3.6',driver:[],customer:[]})};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/forms.js','utf8')+'\n'+fs.readFileSync('web/sheets.js','utf8')+'\nthis.h={getMatrixRow,matrixRows,matrixOperations,matrixDirty,dailyMatrixGroups,matrixVisibleRows,renderOrderMatrix,sheetControls};',ctx);
let row=ctx.h.getMatrixRow(ctx.data.customers[0],null);row.values.P1='1';ctx.data.products.push({id:'P9',name:'魔芋',unit:'筐',price:'4',tare:'1'});
let batch=ctx.h.matrixOperations();assert.equal(batch.operations.length,1);assert.equal(batch.operations[0].body.lines.length,1);assert.equal(batch.operations[0].body.daily_order,true);assert.equal(row.values.P9,'');assert.equal(row.initial.P9,'');
row.values.P9='bad';assert.throws(()=>ctx.h.matrixOperations(),e=>e.issues?.some(i=>i.product_id==='P9'&&i.field==='ordered_qty'));row.values.P9='   ';assert.equal(ctx.h.matrixOperations().operations[0].body.lines.length,1);
// No batch input is needed; one customer's historical orders are grouped for the day.
assert.ok(!ctx.h.sheetControls('order').includes('sheet-batch'));assert.ok(!ctx.h.sheetControls('weight').includes('sheet-processing-batch'));
const base={customer_id:'C1',customer_name:'客户1',business_date:'2026-10-20',version:1,state:'draft',paid_cents:0,lines:[{product_id:'P1',ordered_qty:'2',actual_qty:'0',price:'3.6',driver:[],customer:[]}]};
ctx.data.orders=[{...base,id:'A',batch:'历史甲'},{...base,id:'B',batch:'历史乙',lines:[{...base.lines[0],ordered_qty:'3'}]},{...base,id:'OLD',business_date:'2026-10-19',batch:'历史甲'}];
ctx.h.matrixRows.clear();let groups=ctx.h.dailyMatrixGroups();assert.equal(groups[0].items.length,2);assert.equal(groups[0].items.reduce((n,i)=>n+Number(i.row.values.P1),0),5);
let html=ctx.h.renderOrderMatrix();assert.match(html,/展开原单修改/);assert.match(html,/>5<\/td>/);assert.equal(ctx.h.matrixOperations().operations.length,0);
vm.runInContext("matrixExpanded.add('C1');",ctx);html=ctx.h.renderOrderMatrix();assert.match(html,/data-matrix-key="A"/);assert.match(html,/data-matrix-key="B"/);
ctx.h.getMatrixRow(ctx.data.customers[0],ctx.data.orders[1]).values.P1='4';batch=ctx.h.matrixOperations();assert.equal(batch.operations.length,1);assert.equal(batch.operations[0].order_id,'B');assert.equal(batch.operations[0].body.batch,'历史乙');assert.equal(batch.operations[0].body.lines[0].ordered_qty,'4');
console.log('按天客户汇总、展开原单修改、无批次录入、新增产品兼容和防重复新增标识检查通过');
ctx.page='orders';ctx.URLSearchParams=URLSearchParams;vm.runInContext(fs.readFileSync('web/operations.js','utf8')+'\nthis.h.printOrderLink=printOrderLink;',ctx);
let query=new URLSearchParams(ctx.h.printOrderLink('total').split('?')[1]);assert.equal(query.get('scope'),'sheet');assert.deepEqual(query.getAll('order_id'),['A','B']);
vm.runInContext("sheetSearch='客户2';",ctx);query=new URLSearchParams(ctx.h.printOrderLink('total').split('?')[1]);assert.equal(query.getAll('order_id').length,0);
