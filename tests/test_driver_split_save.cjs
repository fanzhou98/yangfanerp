const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const calls=[],refreshed=[],gross={value:'240',disabled:false},crate={value:'2',dataset:{driverCrate:'SMALL'}};
const box=kind=>({querySelectorAll:selector=>selector==='[data-driver-photo-kind]'?(kind.startsWith('weight')?[{dataset:{driverPhotoKind:'weight-P1'}}]:[]):kind==='crate'?[{getAttribute:()=> 'data:image/jpeg;base64,NEW-CRATE'}]:[]});
const form={reportValidity:()=>true,dataset:{id:'O1',version:'3',weightWarning:'1'},elements:{driver_gross_P1:gross},querySelector:s=>box(s.includes('weight-')?'weight-P1':'crate'),querySelectorAll:s=>s==='[data-driver-crate]'?[crate]:[]};
const ctx=vm.createContext({Blob,document:{addEventListener(){},querySelector:s=>s==='#driver-arrival-form'?form:null,querySelectorAll:()=>[]},$:()=>form,
 erpRequestKey:()=> 'synthetic-key',perform:async fn=>fn(),api:async(path,body,options)=>{calls.push({path,body});options.onUploadProgress(50);options.onUploadProgress(100);return {version:4};},notify(){},today:()=> '2026-11-05'});
vm.runInContext(fs.readFileSync('web/driver.js','utf8'),ctx);
vm.runInContext("driverDay='2026-11-05';driverCache={value:{settings:{crate_photo_required:true},trips:[{orders:[{id:'O1',business_date:'2026-11-04',trip_id:'T1',vehicle_id:'V1',lines:[{product_id:'P1',unit:'筐',actual_qty:'12',default_tare:'1.8'}]}]}]}}",ctx);
ctx.refreshDriverArrivalSection=async(f,mode)=>refreshed.push(mode);
(async()=>{
 await ctx.saveDriverArrival('returns');assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/driver/returns');assert.equal(calls[0].body.lines[0].asset_id,'SMALL');assert.equal(calls[0].body.photos.O1.add.length,1);assert.ok(!('P1' in calls[0].body.photos));
 assert.equal(gross.value,'240');assert.equal(form.dataset.weightWarning,'1');
 form.dataset.weightWarning='';calls.length=0;
 await ctx.saveDriverArrival('weights');assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/driver/weights');assert.equal(calls[0].body.photos.P1.keep[0],'weight-P1');assert.equal(calls[0].body.photos.P1.add.length,0);assert.equal(crate.value,'2');
 assert.deepEqual(refreshed,['returns','weights']);
const scoped=vm.runInContext("driverWeightLines({lines:[{actual_qty:'2',unit:'筐'},{actual_qty:'5',unit:'公斤',billing_unit:'公斤'}]}).map(l=>l.unit)",ctx);assert.equal(scoped.join(','),'筐');
 const missing=vm.runInContext("driverMissingWeights({lines:[{actual_qty:'2',unit:'公斤',billing_unit:'公斤',product_name:'豆腐皮',driver_net:'0'}]}).length",ctx);assert.equal(missing,0);
console.log('Separate saves: returns skip weights/ack, weights skip returns, saved photos use IDs, opposite fields survive.');
})().catch(e=>{console.error(e);process.exitCode=1;});
