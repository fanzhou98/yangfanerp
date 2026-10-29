'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const apiCode=source.slice(source.indexOf('async function api('),source.indexOf('\nasync function ',source.indexOf('async function api(')+1));
const checkCode=source.slice(source.indexOf('async function checkLatestRecords('),source.indexOf('function readState('));
async function run(){
 for(const [kind,body,key,id] of [
  ['order',{id:'PO-1'},'order_id','PO-1'],['receipt',{id:'PO-1'},'order_id','PO-1'],
  ['payment',{id:'PO-1'},'order_id','PO-1'],['charge',{receipt_id:'RC-1'},'receipt_id','RC-1'],
  ['charge-payment',{id:'PO-1',charge_id:'CH-1'},'charge_id','CH-1']
 ]){
  const data={auth_user:{role:'会计'},purchasing:{orders:[{id:'PO-1',version:1}]},resources:{revision:19}};
  const context={data,role:'会计',URLSearchParams,fetch:async()=>{throw Error('offline');},esc:String,amount:String,canReadAuditTrail:()=>false};
  vm.createContext(context);vm.runInContext(apiCode+'\n'+checkCode,context);
  let failure;try{await context.api('/api/purchasing/'+kind,body);}catch(error){failure=error;}
  assert(failure?.outcomeUnknown);assert.equal(failure.request.purchaseLookup[key],id);
  const result={hidden:true,textContent:'',innerHTML:''},box={operationFailure:failure,querySelector:()=>result};
  const button={isConnected:true,closest:()=>box},calls=[],before=JSON.stringify(data);
  context.api=async path=>{calls.push(path);return {orders:[{id:'PO-1',supplier_name:'最新供应商',status:'已入库',version:3}]};};
  await context.checkLatestRecords(button);
  assert.deepEqual(calls,['/api/purchasing?'+new URLSearchParams({[key]:id})]);
  assert(result.innerHTML.includes('最新供应商'));assert(result.innerHTML.includes('<td>3</td>'));
  assert.equal(JSON.stringify(data),before,'checking must not replace caches or revisions');
  context.api=async()=>{throw Error('原单不可读取');};
  await context.checkLatestRecords(button);assert(result.textContent.includes('原单不可读取'));
  assert.equal(JSON.stringify(data),before);assert.equal(button.disabled,false);
 }
 // New records have no known original id: do not fetch every purchase as a fallback.
 const context={data:{auth_user:{role:'管理员'}},esc:String,amount:String,canReadAuditTrail:()=>true,api:async p=>{assert.equal(p,'/api/audit?all=1&page_size=200');return {rows:[]};}};
 vm.createContext(context);vm.runInContext(checkCode,context);
 const result={innerHTML:''};await context.checkLatestRecords({isConnected:true,closest:()=>({querySelector:()=>result,operationFailure:{request:{path:'/api/purchasing/order',ids:[]}}})});
 assert(result.innerHTML.includes('不要据此判断提交失败'));
 console.log('purchase conflict lookup, parent order, failures and cache preservation: ok');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
