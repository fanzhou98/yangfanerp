'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/cost-allocation.js','utf8');
const code=source.slice(source.indexOf('async function costExpenseDialog('),source.indexOf('async function createExpensePartyInline('));
async function run(){
 let opened=0,recordLoads=0;
 const r={categories:[{id:'stale',manual_entry:true}],expenses:[],revision:42};
 const context={page:'expenses',needPermission:()=>true,resourceData:()=>r,api:async()=>{throw Error('offline');},loadExpenseRecord:async()=>{recordLoads++;},openDialog:()=>{opened++;}};
 vm.createContext(context);vm.runInContext(code,context);
 const before=JSON.stringify(r);
 await assert.rejects(context.costExpenseDialog('E1'),/offline/);
 assert.equal(JSON.stringify(r),before);assert.equal(opened,0);assert.equal(recordLoads,0);
 context.api=async url=>{assert.equal(url,'/api/expense-options');return {categories:[],expense_counterparties:[{id:'NEW'}],expense_counterparty_kinds:{other:'其他'}};};
 await assert.rejects(context.costExpenseDialog(),/没有可用于新费用登记/);
 assert.equal(r.categories.length,0,'removed or disabled categories must not fall back to stale choices');
 assert.equal(r.expense_counterparties[0].id,'NEW');assert.equal(r.revision,42);
 r.categories=[{id:'keep'}];
 context.api=async()=>{context.page='other';return {categories:[]};};
 await context.costExpenseDialog();assert.equal(r.categories[0].id,'keep','navigation during fetch must discard result');
 console.log('expense options freshness, failure and navigation: ok');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
