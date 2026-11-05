const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
let parsed=false;
const ctx=vm.createContext({role:'司机',data:{},successfulWrites:0,sessionActive:()=>true,
 fetch:async()=>({status:413,ok:false,json:async()=>{parsed=true;throw Error('nginx HTML response');}})});
vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('function resetPageTabs(')),ctx);
(async()=>{
 await assert.rejects(ctx.api('/api/driver/weights',{order_id:'O1'}),e=>e.message.includes('本次未保存')&&e.outcomeUnknown===false);
 assert.equal(parsed,false);assert.equal(ctx.successfulWrites,0);
 ctx.fetch=async()=>({status:200,ok:true,json:async()=>({ok:true})});
 assert.equal((await ctx.api('/api/driver/weights',{order_id:'O1'})).ok,true);
 assert.equal(ctx.successfulWrites,1);
 console.log('413 HTML returns a clear unsaved error; successful writes remain intact.');
})().catch(e=>{console.error(e);process.exitCode=1;});
