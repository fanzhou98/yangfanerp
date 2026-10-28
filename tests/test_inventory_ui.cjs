const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const ctx=vm.createContext({document:{addEventListener(){}},data:{stock_closings:[],processing_batches:[],sales_returns:[]},sheetDate:()=> '2026-10-21'});
vm.runInContext(fs.readFileSync('web/inventory.js','utf8'),ctx);
const run=x=>vm.runInContext(x,ctx);
assert.equal(run('orderOutstanding({total_cents:10000,paid_cents:2000,return_credit_cents:3000})'),5000);
assert.equal(run('returnWallet({finance:{state:"posted",amount_cents:4000,allocations:[{amount_cents:1000}],refunds:[{amount_cents:500}]}})'),2500);
assert.equal(run('returnWallet({finance:{state:"pending_review",amount_cents:4000}})'),0);
assert.equal(run('previousDay("2028-03-01")'),'2028-02-29');assert.equal(run('previousDay("2026-01-01")'),'2025-12-31');
assert.equal(run('returnRemaining({qty:"2",net_kg:"20",disposals:[{qty:"1",net_kg:"8"}]}).kg'),12);
console.log('应收减退货抵扣、待抵退款余额、部分隔离处置与跨月结转日期检查通过');

ctx.customerLocation=c=>({region:c.region||'',market:c.route||''});ctx.data.customers=[{id:'C1',region:'昌吉',route:'亚中'},{id:'C2',region:'乌鲁木齐',route:'新联'}];ctx.data.orders=[{id:'A',customer_id:'C1',business_date:'2026-10-20',lines:[{actual_qty:'1'}]},{id:'B',customer_id:'C1',business_date:'2026-10-20',lines:[{actual_qty:'2'}]},{id:'C',customer_id:'C2',business_date:'2026-10-20',lines:[{actual_qty:'1'}]},{id:'D',customer_id:'C1',business_date:'2026-10-21',lines:[{actual_qty:'0'}]}];
assert.equal(run('returnOrderCandidates("2026-10-20",JSON.stringify(["昌吉","亚中"]),"C1").length'),2);assert.equal(run('returnOrderCandidates("2026-10-21","","C1").length'),0);assert.equal(run('returnOrderCandidates("2026-10-20","","C2")[0].id'),'C');
console.log('日期、市场和客户筛选原单，排除未实发单与多单匹配检查通过');
