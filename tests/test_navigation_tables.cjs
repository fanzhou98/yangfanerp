const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={document:{addEventListener(){}},window:{addEventListener(){}},localStorage:{getItem(){return null;}},moduleVisible:m=>m.allowed!==false};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('web/workspace.js','utf8'),ctx);
const ids=['workspace.analytics','workspace.dashboard','workspace.directory','workspace.product-profit','sales.orders','purchase.orders','production.attendance','inventory.operations','delivery.dispatch','finance.settlement','master.customers' ,'future.module'];
const catalog={modules:ids.map(id=>({id,page:id,title:id}))};
const model=ctx.navigationModel(catalog);
assert.equal(model.overview.id,'workspace.analytics');
const withMap=ctx.navigationModel({modules:[...catalog.modules,{id:'workspace.report-map',page:'report-map',title:'报表地图'}]});assert.equal(withMap.reportMap.page,'report-map');assert(!withMap.sections.some(s=>s.modules.some(m=>m.id==='workspace.report-map')));

ctx.page='product-profit';assert(ctx.navigationOverviewActive(model.overview),'原独立月报也归属置顶经营分析');
assert.deepEqual(Array.from(model.shortcuts,m=>m.id),['workspace.dashboard']);
assert.deepEqual(Array.from(model.sections,s=>s.id),['finance','sales','purchase','inventory','delivery','hr','master','other']);
const shown=[model.overview,...model.shortcuts,...model.sections.flatMap(s=>s.modules)].map(m=>m.id);
assert.equal(new Set(shown).size,shown.length);
assert.equal(shown.length,ids.length-2);
assert(!shown.includes('workspace.chat'),'内部聊天已移除，不再展示');
assert(!shown.includes('workspace.directory'),'不再展示功能总览');
ctx.data={auth_user:{role:'库管'}};assert.equal(ctx.navigationModel(catalog).sections[0].id,'inventory','库管优先库存管理');
ctx.data={auth_user:{role:'厂长'}};assert.equal(ctx.navigationModel(catalog).sections.find(s=>s.id==='hr').title,'人力资源');
ctx.data={auth_user:{role:'管理员'}};
catalog.modules.find(m=>m.id==='workspace.analytics').allowed=false;
assert.equal(ctx.navigationModel(catalog).overview.id,'workspace.product-profit','仅有月报权限时保留入口');
catalog.modules.find(m=>m.id==='purchase.orders').allowed=false;
assert(!ctx.navigationModel(catalog).sections.some(s=>s.id==='purchase'),'无授权时不显示空分组');

vm.runInContext(fs.readFileSync('web/forms.js','utf8'),ctx);
const cell=(text,colSpan=1,rowSpan=1)=>({textContent:text,colSpan,rowSpan,dataset:{}});
const customer=cell('客户',1,2),amount=cell('金额'),note=cell('备注与说明');
const table={tHead:{rows:[{cells:[customer,cell('业务',2)]},{cells:[amount,note]}]},tBodies:[{rows:[
 {cells:[cell('张三',1,2),cell('100'),cell('较长的业务说明')]},
 {cells:[cell('200'),cell('另一条备注')]},
]}],tFoot:{rows:[{cells:[cell('合计',2),cell('汇总说明')]}]},matches:()=>false};
ctx.alignBusinessTable(table);
assert.equal(customer.dataset.align,'center');assert.equal(note.dataset.align,'center');
assert.deepEqual(Array.from(table.tBodies[0].rows[0].cells,c=>c.dataset.align),['center','center','left']);
assert.deepEqual(Array.from(table.tBodies[0].rows[1].cells,c=>c.dataset.align),['center','left']);
assert.deepEqual(Array.from(table.tFoot.rows[0].cells,c=>c.dataset.align),['center','left']);
const first=cell('跨行',1,0),rows=[{cells:[first,cell('1')]},{cells:[cell('2')]}];
assert.equal(ctx.businessTableGrid(rows)[1][0],first,'rowspan=0 延伸至所在区段末行');
assert.equal(ctx.businessTableGrid(rows)[1][1].textContent,'2');
const matrix={...table,matches:()=>true};ctx.alignBusinessTable(matrix);
assert(table.tBodies[0].rows.every(r=>r.cells.every(c=>c.dataset.align==='center')),'价格矩阵按产品列展示，不把产品名误判为备注列');
console.log('导航顺序、入口去重、岗位授权、未来模块兜底，以及多层表头、跨行跨列和备注对齐检查通过');
