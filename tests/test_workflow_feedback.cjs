const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8'),perform=source.slice(source.indexOf('async function perform('),source.indexOf('async function submit('));
async function check(kind){const overlay={hidden:false},form={},trigger={innerHTML:'保存',textContent:'保存',disabled:false,isConnected:true,setAttribute(){},removeAttribute(){}},events=[];const ctx={busy:false,successfulWrites:0,notificationSequence:0,dialogGeneration:1,document:{activeElement:{closest:()=>trigger}},$$:()=>[trigger],$:s=>s==='#overlay'?overlay:s==='#dialog-body form'?form:{},notify:s=>{events.push(s);ctx.notificationSequence++},closeDialog:()=>{assert.equal(ctx.busy,false);overlay.hidden=true;events.push('closed')},err:e=>events.push(e.message),updateSaveStatus(){}};vm.createContext(ctx);vm.runInContext(perform,ctx);
await ctx.perform(async()=>{if(kind==='failed')throw Error('版本冲突');ctx.successfulWrites++;if(kind==='preview'){ctx.dialogGeneration++;events.push('readonly-result')}if(kind==='inline-preview'){form.isConnected=false;events.push('readonly-result')}if(kind==='refresh-failed'){const e=Error('同步失败');e.readFailure=true;throw e;}});
assert.equal(ctx.busy,false);assert.equal(trigger.disabled,false);
if(kind==='saved'){assert.equal(overlay.hidden,true);assert(events.includes('操作已保存，请核对页面结果'));}
if(kind==='failed'){assert.equal(overlay.hidden,false);assert(!events.includes('closed'));assert(events.includes('版本冲突'));}
if(kind==='preview'||kind==='inline-preview'){assert.equal(overlay.hidden,false);assert(events.includes('readonly-result'));}
if(kind==='refresh-failed'){assert.equal(overlay.hidden,false);assert(!events.includes('操作已保存，请核对页面结果'));}
}
(async()=>{for(const kind of ['saved','failed','preview','inline-preview','refresh-failed'])await check(kind);console.log('Final modal saves close with persistent success; failed writes preserve input, readonly results stay, failed refresh never claims success.');})().catch(e=>{console.error(e);process.exitCode=1;});
