'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const listeners={},requests=[];
const ctx={URLSearchParams,document:{addEventListener(name,fn){listeners[name]=fn;}},
 head:()=>'',esc:value=>String(value??''),render(){},today:()=> '2026-10-28',
 updateCollaborationBadges(){},notify(message){throw Error(message);},
 api:async url=>{requests.push(url);const page=Number(new URLSearchParams(url.split('?')[1]).get('page'));return {tickets:[],page,pages:3,total:45};}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('web/collaboration.js','utf8'),ctx);
const run=code=>vm.runInContext(code,ctx);
async function clickPage(page){
 listeners.click({target:{closest:selector=>selector==='[data-feedback-page]'?{dataset:{feedbackPage:String(page)}}:null}});
 await new Promise(resolve=>setImmediate(resolve));
}
(async()=>{
 run("page='feedback';feedbackLoaded=true;feedbackData={tickets:[],total:45,pages:3,page:1};feedbackAll=true;feedbackSearch='库存';feedbackFilter='open'");
 let html=run('feedbackPage()');
 assert.match(html,/data-feedback-page="0" disabled/);
 assert.match(html,/data-feedback-page="2" >下一页/);
 await clickPage(2);
 const query=new URLSearchParams(requests.at(-1).split('?')[1]);
 assert.equal(query.get('page'),'2');assert.equal(query.get('all'),'1');
 assert.equal(query.get('search'),'库存');assert.equal(query.get('status'),'open');
 html=run('feedbackPage()');assert.match(html,/第 2 \/ 3 页/);
 await clickPage(3);
 assert.match(run('feedbackPage()'),/data-feedback-page="4" disabled/);
 run("feedbackAll=false;feedbackStart='2026-09-01';feedbackEnd='2026-09-30'");
 await clickPage(2);
 const dated=new URLSearchParams(requests.at(-1).split('?')[1]);
 assert.equal(dated.get('start'),'2026-09-01');assert.equal(dated.get('end'),'2026-09-30');
 assert.equal(dated.has('all'),false);assert.equal(dated.get('status'),'open');
 run('feedbackData={tickets:[],total:0,pages:1,page:1}');
 assert.doesNotMatch(run('feedbackPage()'),/data-feedback-page/);
 console.log('Feedback pages remain reachable with filters and endpoint buttons disable.');
})().catch(error=>{console.error(error);process.exitCode=1;});
