'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 const errors=[],form={dataset:{kind:'item'},elements:{cost_mode:{value:'count'}},reportValidity:()=>true};
 const c={document:{addEventListener(){}},window:{addEventListener(){}},data:{capabilities:['material-warehouses-v1']},$:()=>form,err:e=>errors.push(e.message),syncMaterialCostChoice:()=>{throw Error('must reject before preparing mutation')},perform:()=>{throw Error('must not submit')}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('web/resources.js','utf8'),c);
 await c.saveResourceForm();assert.equal(errors.length,1);assert(errors[0].includes('本次未提交'));assert.equal(form.elements.cost_mode.value,'count');
 // A capable service proceeds beyond the guard and retains the original validation path.
 c.data.capabilities.push('material-consumption-v1');let reached=false;c.syncMaterialCostChoice=()=>{reached=true;throw Error('reached actual form validation')};
 await assert.rejects(c.saveResourceForm(),/reached actual/);assert(reached);
 console.log('旧服务拒绝新成本设置、不发请求、保留表单；新服务进入原保存路径');
})().catch(e=>{console.error(e);process.exitCode=1});
