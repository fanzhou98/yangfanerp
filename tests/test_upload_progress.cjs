const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let mode='ok',sent;
class XHR{
 constructor(){this.upload={};this.headers={};}
 open(method,path){this.method=method;this.path=path;}
 setRequestHeader(k,v){this.headers[k]=v;}
 send(body){sent=this;this.body=body;this.upload.onprogress({lengthComputable:true,loaded:50,total:100});this.upload.onprogress({lengthComputable:true,loaded:100,total:100});if(mode==='error'){this.onerror();return;}this.status=mode==='oversize'?413:200;this.responseText=mode==='oversize'?'<h1>413</h1>':'{"ok":true}';this.onload();}
}
const ctx=vm.createContext({XMLHttpRequest:XHR,role:'司机',data:{business_data_epoch:'7'},successfulWrites:0,sessionActive:()=>true,csrfCookie:()=> 'synthetic-csrf'});
const source=fs.readFileSync('web/app.js','utf8');vm.runInContext(source.slice(source.indexOf('function apiUpload('),source.indexOf('function resetPageTabs(')),ctx);
(async()=>{
 const progress=[];assert.equal((await ctx.api('/api/driver/weights',{order_id:'O1'},{onUploadProgress:p=>progress.push(p)})).ok,true);
 assert.deepEqual(progress,[0,50,100]);assert.equal(sent.headers['X-CSRF-Token'],'synthetic-csrf');assert.equal(sent.headers['X-ERP-Data-Epoch'],'7');assert.equal(JSON.parse(sent.body).order_id,'O1');assert.equal(ctx.successfulWrites,1);
 mode='oversize';await assert.rejects(ctx.api('/api/driver/returns',{}, {onUploadProgress(){}}),e=>e.outcomeUnknown===false&&e.message.includes('本次未保存'));
 mode='error';await assert.rejects(ctx.api('/api/driver/weights',{}, {onUploadProgress(){}}),e=>e.outcomeUnknown===true);
 let status={};const ui=vm.createContext({document:{addEventListener(){},querySelector:()=>status}});vm.runInContext(fs.readFileSync('web/driver.js','utf8'),ui);
 ui.driverUploadProgress(35);assert.equal(status.textContent,'上传进度 35%');assert.equal(status.hidden,false);
 ui.driverUploadProgress(100);assert.match(status.textContent,/正在保存/);ui.driverUploadProgress(null);assert.equal(status.hidden,true);
 console.log('Upload progress: actual bytes, CSRF/epoch headers, errors and waiting-for-save status passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
