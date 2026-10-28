const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let opened=[],dialogs=[],navigation=[],dispatchChanged=false;
const ctx={document:{addEventListener(){}},window:{addEventListener(){},open:(...args)=>opened.push(args)},structuredClone,URLSearchParams,selectedDate:'2026-10-19',today:()=>'2026-10-19',role:'会计',page:'dispatch',busy:false,
 esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
 data:{customers:[{id:'C1',name:'测试客户<&>'}],products:[{id:'P1',name:'豆腐'}],orders:[]},
 dispatchDirty:()=>dispatchChanged,openDialog:(...args)=>dialogs.push(args),closeDialog(){},goto:p=>navigation.push(p),notify(){}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/forms.js','utf8')+'\n'+fs.readFileSync('web/sheets.js','utf8')+'\n'+fs.readFileSync('web/operations.js','utf8')+'\nthis.h={openWarehousePrint,warehousePrintChanges,openPrintDraft,workingOrder,sheetOrders,matrixRows};',ctx);
const row={key:'NEW|today|C1',cid:'C1',date:'2026-10-19',batch:'夜间',values:{P1:'2'},initial:{P1:''}};
ctx.h.matrixRows.set(row.key,row);
ctx.h.matrixRows.set('other',{...row,key:'other',date:'2026-10-18'});
const order={id:'O1',version:1,customer_id:'C1',business_date:'2026-10-19',batch:'夜间',lines:[{product_id:'P1',ordered_qty:'2',actual_qty:'0',price:'3',driver:[],customer:[]}]};
ctx.data.orders=[order];ctx.h.workingOrder(order).lines[0].actual_qty='1';
assert.equal(ctx.h.warehousePrintChanges('total').length,2);
const before=JSON.stringify([...ctx.h.sheetOrders]);
ctx.h.openWarehousePrint('total');assert.equal(opened.length,0);assert.equal(dialogs.length,1);
assert.match(dialogs[0][1],/测试客户&lt;&amp;&gt;/);assert.match(dialogs[0][1],/O1/);assert.match(dialogs[0][3],/打印已保存版本/);assert.match(dialogs[0][3],/mode=total/);
assert.equal(JSON.stringify([...ctx.h.sheetOrders]),before);assert.equal(ctx.h.matrixRows.size,2);
ctx.h.openPrintDraft('matrix',row.key);assert.equal(navigation.pop(),'orders');assert.equal(ctx.selectedDate,'2026-10-19');
ctx.h.openPrintDraft('weight','O1');assert.equal(navigation.pop(),'settlements');
ctx.h.sheetOrders.clear();ctx.h.matrixRows.delete(row.key);dispatchChanged=true;
ctx.h.openWarehousePrint('total');assert.equal(opened.length,1);assert.match(opened[0][0],/date=2026-10-19&mode=total/);
ctx.h.openWarehousePrint('trip','TRIP1');assert.equal(opened.length,1);assert.match(dialogs.at(-1)[1],/配送安排/);assert.match(dialogs.at(-1)[3],/trip=TRIP1/);
ctx.h.openPrintDraft('dispatch','2026-10-19');assert.equal(navigation.pop(),'dispatch');
ctx.busy=true;ctx.h.openWarehousePrint('total');assert.equal(opened.length,1);
console.log('打印草稿明细、已保存版本入口、不丢弃输入、草稿定位和总单不依赖排车检查通过');
