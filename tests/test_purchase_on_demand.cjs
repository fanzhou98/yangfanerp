'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/purchasing.js','utf8');
const code=source.slice(source.indexOf('async function openPurchaseForm('),source.indexOf('async function savePurchaseForm('));
async function run(){
 const prior={suppliers:[],orders:[{id:'OTHER',version:1},{id:'OLD',version:1}],receipts:[{id:'STALE',order_id:'OLD'},{id:'KEEP',order_id:'OTHER'}],payments:[],charges:[]};
 let shown=null;
 const context={URLSearchParams,data:{purchasing:structuredClone(prior)},page:'payables',purchaseData:()=>context.data.purchasing,resourceField:()=>'',openPurchaseDetail:o=>{shown=o;},notify:()=>assert.fail('unexpected missing order')};
 context.api=async url=>{
  assert.equal(url,'/api/purchasing?order_id=OLD');
  return {suppliers:[],orders:[{id:'OLD',version:2}],receipts:[{id:'NEW',order_id:'OLD'}],payments:[],charges:[]};
 };
 vm.createContext(context);vm.runInContext(code,context);
 await context.openPurchaseForm('detail','OLD');
 assert.equal(shown.version,2,'detail must use server version');
 assert.deepEqual(Array.from(context.data.purchasing.orders,o=>o.id),['OTHER','OLD']);
 assert.deepEqual(Array.from(context.data.purchasing.receipts,r=>r.id),['KEEP','NEW'],'replace selected order history while preserving unrelated rows');
 const before=JSON.stringify(context.data);shown=null;
 context.api=async()=>{throw Error('network failed');};
 await assert.rejects(context.openPurchaseForm('detail','MISSING'),/network failed/);
 assert.equal(shown,null,'failed fetch must not open a stale form');
 assert.equal(JSON.stringify(context.data),before,'failed fetch must preserve cached data');
 console.log('purchase on-demand detail and failure handling: ok');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
