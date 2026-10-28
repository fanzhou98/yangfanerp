const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function scenario(failure){
 const day='2026-10-20',events=[],form={reportValidity:()=>true},old={id:'O1',version:1,business_date:day,lines:[]};
 const ctx={document:{addEventListener(){}},window:{addEventListener(){}},busy:false,selectedDate:day,today:()=>day,canAction:()=>true,$:()=>form,data:{warehouse_plans:[{business_date:day,version:1,inventory_revision:1}],orders:[old]},closeDialog(){assert.equal(ctx.busy,false);events.push('close');},render(){events.push('render');},notify(msg){events.push(msg);},showOperationError(e){events.push(e.message);},async api(path){if(path==='/api/warehouse'){if(failure==='write')throw Error('库存已变化');return {plan:{business_date:day,version:2,inventory_revision:2},orders:[{...old,version:2}]};}if(failure==='refresh')throw Error('网络失败');return ctx.data;}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/dispatch.js','utf8'),ctx);
 if(failure==='write'){await assert.rejects(vm.runInContext('commitLoading()',ctx),/库存已变化/);assert(!events.includes('close'));}
 else{await vm.runInContext('commitLoading()',ctx);assert.deepEqual(events.slice(0,2),['close','render']);assert.equal(ctx.data.orders[0].version,2);if(failure==='refresh')assert(events.some(x=>x.includes('实发已写入')&&x.includes('不要重复提交')));else assert(events.some(x=>x.includes('实发已确认')&&x.includes('配送明细与运费记录已生成')));}
 assert.equal(ctx.busy,false);
}
(async()=>{await scenario();await scenario('refresh');await scenario('write');console.log('Loading confirmation: success closes before feedback; failed refresh preserves saved result; failed write stays open.');})().catch(e=>{console.error(e);process.exitCode=1;});
