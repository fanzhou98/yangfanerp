const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const ctx={document:{addEventListener(){}},window:{addEventListener(){}}};vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/inventory.js','utf8'),ctx);
const r={qty:'2',net_kg:'20',disposals:[],finance:null};
assert.equal(ctx.returnClosure(r).done,false);
r.finance={state:'posted',amount_cents:1000,allocations:[{amount_cents:1000}],refunds:[]};assert.equal(ctx.returnClosure(r).label,'待实物处理');
r.disposals=[{qty:'1',net_kg:'10'}];assert.equal(ctx.returnClosure(r).done,false);
r.disposals.push({qty:'1',net_kg:'10'});assert.equal(ctx.returnClosure(r).done,true);
r.finance.allocations=[];assert.equal(ctx.returnClosure(r).label,'待抵账 / 退款');
r.receipt_mode='merchant_disposed';assert.equal(ctx.returnClosure(r).done,false);r.finance.refunds=[{amount_cents:1000}];assert.equal(ctx.returnClosure(r).done,true);
r.voided=true;assert.equal(ctx.returnClosure(r).done,false);
console.log('实物、财务和待抵退款均核对后才标全部办结');

const pending={qty:'1',net_kg:'10',disposals:[{qty:'1',net_kg:'10',kind:'reprocess',processing_completed:false}],finance:{state:'posted',amount_cents:0}};assert.equal(ctx.returnClosure(pending).label,'待转加工完成');pending.disposals[0].processing_completed=true;assert.equal(ctx.returnClosure(pending).done,true);
