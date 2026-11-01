function erpRequestKey(){if(typeof crypto.randomUUID==='function')return crypto.randomUUID();const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=Array.from(b,n=>n.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
'use strict';
const $=(q,el=document)=>el.querySelector(q), $$=(q,el=document)=>[...el.querySelectorAll(q)];
function updateVisibleViewport(){const v=window.visualViewport,root=document.documentElement;const height=v?.height||window.innerHeight,top=v?.offsetTop||0;root.style.setProperty('--erp-visible-height',height+'px');root.style.setProperty('--erp-visible-top',top+'px');root.style.setProperty('--erp-covered-bottom',Math.max(0,window.innerHeight-height-top)+'px');}
let visibleViewportFrame=0;
function scheduleVisibleViewport(){if(visibleViewportFrame)return;visibleViewportFrame=requestAnimationFrame(()=>{visibleViewportFrame=0;updateVisibleViewport();});}
window.visualViewport?.addEventListener('resize',scheduleVisibleViewport,{passive:true});
window.visualViewport?.addEventListener('scroll',scheduleVisibleViewport,{passive:true});
window.addEventListener('resize',scheduleVisibleViewport,{passive:true});
window.addEventListener('orientationchange',scheduleVisibleViewport,{passive:true});
updateVisibleViewport();

function updateBackToTop(){
 const button=document.getElementById('back-to-top');if(!button)return;
 button.hidden=window.scrollY<320||!!document.querySelector('#overlay:not([hidden]),#leave-overlay:not([hidden])');
 if(button.hidden)return;
 const rect=button.getBoundingClientRect();let clearance=0;
 for(const dock of document.querySelectorAll('.page-save-dock')){
  const box=dock.getBoundingClientRect();
  if(box.height&&box.top<innerHeight&&box.bottom>0&&box.left<rect.right&&box.right>rect.left&&getComputedStyle(dock).visibility!=='hidden')clearance=Math.max(clearance,innerHeight-box.top+12);
 }
 button.style.setProperty('--erp-save-clearance',clearance+'px');
}
window.addEventListener('scroll',updateBackToTop,{passive:true});
window.addEventListener('resize',updateBackToTop,{passive:true});
document.getElementById('back-to-top')?.addEventListener('click',()=>window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}));
updateBackToTop();

const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const yuan=c=>(Number(c||0)/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const num=x=>Number(x||0).toLocaleString('zh-CN',{maximumFractionDigits:3});
const amount=x=>'¥ '+yuan(x);
const pageTrail=[];let returningPage=false,lastPageLocation=null;
let data, page='dashboard', filter='all', search='', selectedDate='', role='库管', draft, activeOrder, voidTarget, lastFocus, busy=false;
let navCollapsed=null;try{const raw=localStorage.getItem('erpStandardNavCollapsed');if(raw)navCollapsed=new Set(JSON.parse(raw));}catch{}
function navGroupCollapsed(id){return navCollapsed===null?true:navCollapsed.has(id);}
function collapseAllNavGroups(){const root=$('#nav'),scroll=root?.scrollTop||0;const sections=navigationModel(data.access_catalog).sections;navCollapsed=sections.every(s=>navGroupCollapsed(s.id))?new Set():new Set(sections.map(s=>s.id));try{localStorage.setItem('erpStandardNavCollapsed',JSON.stringify([...navCollapsed]));}catch{}nav();if(root)root.scrollTop=scroll;$('#collapse-all-navigation')?.focus({preventScroll:true});}
function toggleNavGroup(id){
 const root=$('#nav'),scroll=root?.scrollTop||0,restoreFocus=document.activeElement?.matches('[data-nav-toggle]');
 if(navCollapsed===null)navCollapsed=new Set(navigationModel(data.access_catalog).sections.map(s=>s.id));
 if(navCollapsed.has(id))navCollapsed.delete(id);else navCollapsed.add(id);
 try{localStorage.setItem('erpStandardNavCollapsed',JSON.stringify([...navCollapsed]));}catch{}
 nav();if(root)root.scrollTop=scroll;
 if(restoreFocus)$(`[data-nav-toggle="${CSS.escape(id)}"]`)?.focus({preventScroll:true});
}
let dialogExpected;
const pages=[['dashboard','◫','经营工作台'],['orders','▤','订货总表'],['allocation','▦','库存盘点与发货分配'],['returns','↩','客户退货与扣款'],['dispatch','⇄','配送排车'],['weighing','▧','称重总表'],['settlements','⚖','结算与复核'],['ledger','▥','应收与收款'],['archive','▤','单据查询'],['masters','♧','客户与产品'],['production','▦','生产与成本'],['logs','◷','操作记录'],['directory','▦','功能总览'],['access','◇','岗位与权限']];
const badge=o=>`<span class="badge ${{'待发货':'blue','待算票':'blue','待确认称重':'orange','待重算':'red','待复核':'orange','待收款':'orange','部分收款':'orange','已收清':'green','已抵清':'green','已结清':'green','部分收款 / 抵扣':'orange'}[o.status]}">${esc(o.status)}</span>`;
const today=()=>data?.today||new Date().toLocaleDateString('sv-SE');
const filteredOrders=()=>data.orders.filter(o=>['ledger','settlements'].includes(page)?rangeDateMatches(o):!selectedDate||o.business_date===selectedDate);
let notificationSequence=0;
const notify=(text)=>{notificationSequence++;const t=$('#toast');clearTimeout(notify.timer);if(typeof showWorkflowFeedback==='function'){t.hidden=true;showWorkflowFeedback(text);return;}t.textContent=text;t.hidden=false;notify.timer=setTimeout(()=>t.hidden=true,4500);};
let dialogGeneration=0,dialogCloseTimer;
let successfulWrites=0,lastReadTime='';

function operationError(error){
 const detail=[error.message,...(error.issues||[]).map(i=>[i.customer_name,i.product_name,i.message].filter(Boolean).join(' · '))].filter(Boolean).join('；');
 const conflict=error.conflict||/已被.*修改|已被.*更新|版本.*(?:冲突|不一致|不匹配|过期)|修订.*(?:冲突|不一致)|数据.*变化|数据.*已更新|记录.*已更新|单据已修改/.test(detail);
 let message=detail||'操作未完成，请核对填写内容后重试。';
 if(error.confirmedWrite)message='操作已完成，但最新数据读取失败。请核对服务器记录，不要重复登记。';
 else if(error.outcomeUnknown)message='未收到提交结果，当前无法确认是否已保存。请先核对服务器记录，再决定是否重新提交。';
 else if(conflict)message+=' 当前输入保留，请先核对服务器记录；不要直接用旧内容覆盖最新记录。';
 return {message,check:!!(conflict||error.outcomeUnknown||error.confirmedWrite),conflict};
}
function showOperationError(error,target){
 const priorFeedback=document.getElementById('workflow-feedback');if(priorFeedback){if(typeof hideWorkflowFeedback==='function')hideWorkflowFeedback();else priorFeedback.hidden=true;}const toast=$('#toast');if(toast)toast.hidden=true;
 const info=operationError(error);
 if(info.check&&typeof setSaveIssue==='function')setSaveIssue(info.message);
 const box=target||(!$('#overlay').hidden?$('#dialog-error'):$('#page-feedback'));
 if(!box){notify(info.message);return;}
 box.operationFailure=error;box.classList.add('operation-feedback');box.hidden=false;
 box.innerHTML=`<div class="feedback-message">${esc(info.message)}</div><div class="feedback-actions">${info.check?'<button type="button" class="button" data-check-latest>核对记录</button>':''}<button type="button" class="text-button" data-dismiss-feedback>收起提示</button></div><div class="latest-record-check" aria-live="polite" hidden></div>`;
 box.scrollIntoView({block:'nearest',behavior:'instant'});
 if(typeof showWorkflowFeedback==='function')showWorkflowFeedback(info.message,'error');
}
function clearOperationFeedback(){const box=$('#page-feedback');if(box){box.hidden=true;box.replaceChildren();}}
async function checkLatestRecords(button){
 const box=button.closest('.operation-feedback'),result=box.querySelector('.latest-record-check'),failure=box.operationFailure;
 if(!result)return;button.disabled=true;result.hidden=false;result.textContent='正在读取服务器记录…';
 try{
  // Read separately: never replace data, working copies, forms or their baselines.
  const request=failure?.request,ids=[...(request?.ids||[])];
  let fresh;
  if(request?.path?.startsWith('/api/purchasing/')&&data.auth_user){
   fresh={auth_user:data.auth_user,orders:[],receipts:[],audit:[],purchasing:{orders:[]}};
   if(request.purchaseLookup){
    fresh.purchasing=await api('/api/purchasing?'+new URLSearchParams(request.purchaseLookup));
    for(const order of fresh.purchasing.orders||[])if(!ids.includes(order.id))ids.push(order.id);
   }
  }else fresh=await api('/api/bootstrap',undefined,{snapshot:true});
  const sales=(fresh.orders||[]).filter(o=>ids.includes(o.id));
  const purchases=(fresh.purchasing?.orders||[]).filter(o=>ids.includes(o.id));
  const rows=[...sales.map(o=>[o.customer_name,o.id,o.status||o.state,o.version]),...purchases.map(o=>[o.supplier_name,o.id,o.status||o.state,o.version])];
  const receipts=(fresh.receipts||[]).filter(r=>ids.includes(r.order_id)).slice(-8);
  const relevant=a=>!ids.length||ids.some(id=>String(a.entity).includes(id));
  // 登录后 bootstrap 不再随带审计行：有操作记录权限的岗位单独读取最近200条，再按本次涉及的 id 过滤，保持 v0.96.0 口径。
  const viaAuditApi=!!fresh.auth_user&&canReadAuditTrail();
  let audit=(fresh.audit||[]).filter(relevant).slice(0,8);
  if(viaAuditApi){
   try{const trail=await api('/api/audit?all=1&page_size=200');audit=(trail.rows||[]).filter(relevant).slice(0,8);}
   catch{audit=[];}
  }
  const hint=viaAuditApi||!fresh.auth_user?'请结合对象、金额、时间和经办人核对；版本变化本身不能证明本次提交成功。':'请结合对象、金额、时间和对方确认核对；操作轨迹仅对管理员或具备操作记录权限的岗位显示，如需查看请联系管理员在操作记录页查看。';
  result.innerHTML=`<b>服务器记录 · ${esc(new Date().toLocaleTimeString('zh-CN',{hour12:false}))}</b><p>当前输入未被替换。${hint}</p>${rows.length?`<div class="table-wrap"><table><thead><tr><th>对象</th><th>单号</th><th>当前状态</th><th>版本</th></tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${esc(v??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:''}${receipts.length?`<p>相关收款流水（请核对金额与时间）</p><ul>${receipts.map(r=>`<li>${esc(r.received_date)} · ${esc(r.order_id)} · 实际到账 ${amount(r.amount_cents)} · 抹零 ${amount(r.rounding_cents||0)}</li>`).join('')}</ul>`:''}${audit.length?`<p>最近相关操作</p><ul>${audit.map(a=>`<li>${esc(a.at)} · ${esc(a.actor_name||a.role)} · ${esc(a.action)} · ${esc(a.entity)}</li>`).join('')}</ul>`:''}${!rows.length&&!audit.length&&!receipts.length?'<p>当前查看范围内没有可直接对应的记录。请保留输入，并通过对应业务台账核对；不要据此判断提交失败。</p>':''}`;
 }catch(error){result.textContent='最新记录读取失败：'+error.message+' 请检查厂内网络后再次核对；当前输入保留。';}
 finally{if(button.isConnected)button.disabled=false;}
}
function readState(label,error,scope='reports'){
 if(typeof showReadFailureOnce==='function')showReadFailureOnce(label,error);
 return `<section class="read-state ${error?'read-state-error':''}" role="${error?'alert':'status'}" aria-busy="${!error}"><b>${esc(error?label+'读取失败':'正在读取'+label+'…')}</b>${error?`<p>${esc(error)} 请检查网络后重新加载。</p><button type="button" class="button" data-read-retry="${esc(scope)}">重新加载</button>`:'<p>请稍候，读取完成后自动显示。</p>'}</section>`;
}
function installWorkStatus(){
 const root=$('#content');if(!root)return;
 const editable=!!root.querySelector('input:not([disabled]),[data-sheet-action="save"],[data-warehouse-act="save"],[data-dispatch-act="save"]');
 if(!editable)return;
 const bar=document.createElement('section');bar.id='work-status-bar';bar.className='work-status-bar';bar.hidden=true;bar.setAttribute('aria-label','保存状态');
 bar.innerHTML='<div><b data-work-save role="status"></b><span data-work-next hidden></span></div>';
 const head=root.querySelector(':scope > .page-head');if(head)head.after(bar);else root.prepend(bar);
}
async function api(path,body,{snapshot=false}={}){
 if(typeof sessionActive==='function'&&!sessionActive())throw Error('登录已超时，请重新登录');
 if(body&&path.endsWith('/receipt')&&(Number(body.discount||0)||Number(body.rounding||0))&&!data?.capabilities?.includes('receipt-adjustments-v1'))throw Error('服务尚未支持折扣抹零，请更新并重启 ERP 服务后刷新页面；本次未提交。');
 const request={path,ids:[...new Set([body?.id,body?.order_id,...(body?.operations||[]).map(o=>o.order_id),...(path.match(/^\/api\/orders\/([^/]+)/)||[]).slice(1)].filter(Boolean))]};let r;const roleHeader={'库管':'warehouse','会计':'accountant','出纳':'cashier'}[role]||'accountant';
 if(path.startsWith('/api/purchasing/')){
  const kind=path.slice('/api/purchasing/'.length),key=kind==='charge'?'receipt_id':kind==='charge-payment'?'charge_id':'order_id';
  const id=key==='order_id'?body?.id||body?.order_id:body?.[key];
  if(['order','confirm','close','receipt','payment','warehouse','charge','charge-payment'].includes(kind)&&id){request.purchaseLookup={[key]:id};if(!request.ids.includes(id))request.ids.push(id);}
 }
 try{r=await fetch(path,{method:body?'POST':'GET',headers:{...(body?{'Content-Type':'application/json','X-ERP-Client':'local-pilot','X-ERP-Data-Epoch':data?.business_data_epoch||'0','X-CSRF-Token':typeof csrfCookie==='function'?csrfCookie():''}:path==='/api/bootstrap'?{...(snapshot?{}:{'X-ERP-Expense-History':'deferred'}),'X-ERP-Byproduct-History':'deferred'}:{}),'X-ERP-Role':roleHeader},body:body?JSON.stringify(body):undefined});}
 catch(cause){throw Object.assign(Error(body?'未收到提交结果，请先核对服务器记录。':'无法连接系统服务，请检查厂内网络后重新读取。'),{outcomeUnknown:!!body,readFailure:!body,request,cause});}
 let j;try{j=await r.json();}catch{throw Object.assign(Error('系统响应异常，请检查网络或联系管理员核对服务。'),{outcomeUnknown:!!body,readFailure:!body,request});}
 if(!snapshot&&r.ok&&path==='/api/bootstrap'&&typeof factoryReports!=='undefined'){factoryReports.clear();if(typeof resourceExpenseRecords!=='undefined'){resourceExpenseRecords.clear();resourceExpenseEpoch++;}if(typeof inventoryCheckCache!=='undefined')inventoryCheckCache.clear();if(typeof productProfitCache!=='undefined')productProfitCache.clear();if(typeof assetCache!=='undefined')assetCache=null;if(typeof driverCache!=='undefined')driverCache=null;lastReadTime=new Date().toLocaleTimeString('zh-CN',{hour12:false});}
 if(!snapshot&&r.ok&&path==='/api/bootstrap'&&data&&(data.business_data_epoch||'0')!==(j.business_data_epoch||'0'))resetBusinessDrafts();
 if(!r.ok){
  if(r.status===401&&typeof showAuthScreen==='function'){if(typeof expireAuthSession==='function')expireAuthSession();else showAuthScreen(false,'登录已失效，请重新登录');}
  if(body&&String(j.error||'').includes('试运行业务数据已经清理或恢复')){data=await api('/api/bootstrap');resetBusinessDrafts();busy=false;closeDialog();if(typeof resetSaveStatus==='function')resetSaveStatus();render();throw Object.assign(Error('业务数据已重置，已自动载入最新数据。旧草稿已清除，请重新填写。'),{dataReset:true});}
  throw Object.assign(Error(j.error||'操作未完成，请核对填写内容。'),{issues:j.issues||[],request,readFailure:!body,outcomeUnknown:!!body&&r.status>=500,conflict:r.status===409});
 }
 if(body){successfulWrites++;if(typeof recordServerSave==='function')recordServerSave();}
 return j;
}

async function refresh(){if(typeof finishedCache!=='undefined')finishedCache=null;if(typeof gelCache!=='undefined')gelCache=null;data=await api('/api/bootstrap');if(page==='users')managedUsers=await api('/api/users');render();}
document.addEventListener('click',e=>{const t=e.target.closest('[data-nav-toggle]');if(t){e.preventDefault();toggleNavGroup(t.dataset.navToggle);}if(e.target.closest('#collapse-all-navigation')){e.preventDefault();collapseAllNavGroups();}});
document.addEventListener('click',event=>{
 const check=event.target.closest('[data-check-latest]');if(check){checkLatestRecords(check);return;}
 const dismiss=event.target.closest('[data-dismiss-feedback]');if(dismiss){dismiss.closest('.operation-feedback').hidden=true;return;}
 if(event.target.closest('[data-clear-editor-search]')){if(page==='masters')pricingSearch='';else sheetSearch='';render();return;}
 const retry=event.target.closest('[data-read-retry]');if(retry){
  if(retry.dataset.readRetry==='driver'){driverCache=null;}else if(retry.dataset.readRetry==='assets'){assetCache=null;}else for(const [key,value] of factoryReports)if(value.error)factoryReports.delete(key);
  render();
 }
});
function goto(p){if(document.querySelector('#dialog-body #module-search'))closeDialog();if(data?.auth_user&&!data.access_catalog.modules.some(m=>m.page===p&&moduleVisible(m))){notify('当前账号无权进入此模块');return;}if(typeof requestPageTransition==='function'&&!navigationBypass)return requestPageTransition(()=>goto(p));if(p==='settlements'&&page!==p&&!selectedDate&&!rangeMode){selectedDate=shiftRangeDay(today(),-1);rangeBasis='business_date';}if(p==='fleet')p='dispatch';if(p!==page&&['employees','management-employees'].includes(p)){employeeGroup='';employeeStatus='all';employeeView='employees';employeeSearch='';}if(p!==page&&['attendance','management-attendance'].includes(p)){monthGroup='';monthSearch='';monthStatus='';attendanceSearch='';}if(p==='fund-accounts'&&page!==p)fundsCache=null;if(p!==page&&!returningPage){pageTrail.push({...lastPageLocation,scrollY:window.scrollY});if(pageTrail.length>40)pageTrail.shift();}if(p==='ledger'&&page!==p){clearDateRange();selectedDate='';}if(p==='allocation'&&!selectedDate)selectedDate=today();if(p==='weighing'&&page!==p)sheetStatus='all';if(p==='dispatch'&&!selectedDate)selectedDate=today();if(p!==page&&['suppliers','purchases','purchase-receipts','payables'].includes(p))purchaseStatus='';if(typeof closeMobileNavigation==='function')closeMobileNavigation();page=p;filter='all';search='';render();window.scrollTo(0,0);}
function head(title,subtitle,actions=''){return `<div class="page-head"><div><h1><span class="page-title-icon">${submenuModuleIcon(currentModule()||{})}</span>${title}</h1><p>${subtitle}</p></div><div class="head-actions">${actions}</div></div>`;}
function period(){return `<div class="period"><span>业务日期</span><input id="business-date-filter" type="date" aria-label="筛选业务日期" value="${esc(selectedDate)}"><button class="text-button" data-act="today">今天</button><button class="text-button" data-act="all-dates">全部日期</button><span class="dim">按送货业务日期统计，跨零点不拆单</span></div>`;}
function metrics(items){return `<div class="metrics">${items.map(([label,value,unit,foot,symbol])=>`<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}${unit?`<small>${unit}</small>`:''}</div><div class="metric-foot">${foot}</div></div>`).join('')}</div>`;}
function moduleTarget(m){return m.view?`data-master-tab="${esc(m.view)}"`:m.page==='settlements'?'data-act="pending-settlements"':`data-page="${esc(m.page)}"`;}
function currentModule(){const visible=(data.access_catalog?.modules||[]).filter(m=>m.page===page&&moduleVisible(m)&&(!m.view||m.view===masterView));return page==='allocation'?(visible.find(m=>m.id==='inventory.operations')||visible[0]):visible[0];}

function navButtonHTML(m){return `<button class="nav-item ${currentModule()?.id===m.id?'active':''}" ${moduleTarget(m)} data-module-id="${esc(m.id)}" aria-label="${esc(m.title)}" title="${esc(m.title+' · '+m.description)}" ${currentModule()?.id===m.id?'aria-current="page"':''}><span class="nav-icon">${submenuModuleIcon(m)}</span><span class="nav-item-label">${esc(m.title)}</span>${typeof factoryNavigationCount==='function'?factoryNavigationCount(m.page):''}${typeof collaborationNavigationCount==='function'?collaborationNavigationCount(m.page):''}${m.page==='settlements'?`<span class="nav-count">${data.orders.filter(isSettlementTodo).length}</span>`:''}</button>`;}
function navItemsHTML(modules){return modules.map(navButtonHTML).join('');}
let activeNavigationModule='';
function nav(){
 const catalog=data.access_catalog;
 if(catalog){
  const model=navigationModel(catalog),current=currentModule();
  if(current?.id!==activeNavigationModule){activeNavigationModule=current?.id;const section=model.sections.find(s=>s.modules.some(m=>m.id===current?.id));if(section){if(navCollapsed===null)navCollapsed=new Set(model.sections.map(s=>s.id));navCollapsed.delete(section.id);}}
  $('#nav').innerHTML=model.sections.map(s=>{
   const active=s.modules.some(m=>m.id===current?.id),open=!navGroupCollapsed(s.id);
   return `<section class="erp-nav-group ${active?'is-current':''}" data-nav-section="${esc(s.id)}" data-nav-tone="${s.tone}" aria-label="${esc(s.title)}"><button type="button" class="nav-section nav-group-toggle" data-nav-toggle="${esc(s.id)}" aria-expanded="${open}" aria-controls="nav-items-${s.id}"><span class="nav-section-symbol">${navigationSectionIcon(s.id)}</span><span class="nav-section-copy">${esc(s.title)}</span><span class="nav-group-caret" aria-hidden="true"><svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="${open?'m5 7 5 5 5-5':'m7 5 5 5-5 5'}"/></svg></span></button><div class="nav-group-items" id="nav-items-${s.id}" ${open?'':'hidden'}>${navItemsHTML(s.modules)}</div></section>`;
  }).join('');
  const section=navigationSectionFor(current?.id);
  $('#crumb').innerHTML=(section?`<button type="button" class="crumb-group" data-crumb-section="${esc(section.id)}" title="查看${esc(section.title)}下的功能">${esc(section.title)}</button><span class="crumb-separator" aria-hidden="true">›</span>`:'')+`<button type="button" class="crumb-current" data-crumb-current title="回到${esc(current?.title||'我的工作台')}顶部">${esc(current?.title||'我的工作台')}</button>`;
 }else{
  $('#nav').innerHTML=pages.filter(([p])=>!['directory','access'].includes(p)).map(([p,icon,title])=>`<button class="nav-item ${page===p?'active':''}" data-page="${p}"><span class="nav-icon">${submenuModuleIcon({page:p})}</span><span>${title}</span></button>`).join('');
  $('#crumb').textContent=pages.find(p=>p[0]===page)?.[2]||'我的工作台';
 }
 $('#avatar').textContent=authUser?.display_name?.slice(0,1)||role[0];if(typeof renderWorkspaceChrome==='function')renderWorkspaceChrome();
 syncDocumentTitle();
}
function syncDocumentTitle(){
 const current=document.querySelector('#crumb .crumb-current'),title=(current?.textContent||'').trim();
 document.title=(typeof data!=='undefined'&&data?.demo_context?'演示数据 · ':'')+(title?title+' · ':'')+'洋帆豆制品 ERP';
}
function directory(){return dashboard();}
function accessOverview(){if(data.auth_user)return renderAuthenticatedAccess();const c=data.access_catalog;if(!c)return head('岗位与权限','请同步最新数据后查看。');return head('岗位与权限','统一功能编号、菜单分类和操作授权，作为后续用户与角色管理的基础。','','SYSTEM · 权限基础')+`<div class="erp-access-status"><div><small>当前身份方式</small><strong>本机岗位模拟</strong></div><div><small>功能查看范围</small><strong>三个岗位共享查看</strong></div><div><small>操作控制</small><strong>服务端校验 + 单据状态保护</strong></div></div><section class="panel"><div class="panel-head"><div><h2>岗位操作权限矩阵</h2><p>● 可操作 · — 无操作权限。菜单可见不代表可以修改或确认；具体操作还需满足单据状态与版本校验。</p></div></div><div class="table-wrap"><table class="erp-access-table"><thead><tr><th>业务分类</th><th>操作</th>${c.roles.map(r=>`<th>${esc(r)}</th>`).join('')}</tr></thead><tbody>${c.actions.map(a=>{const m=c.modules.find(m=>m.id===a.module),g=c.groups.find(g=>g.id===m?.group);return `<tr><td>${esc(g?.title)}</td><th scope="row">${esc(a.title)}</th>${c.roles.map(r=>`<td class="${a.roles.includes(r)?'access-allowed':'dim'}" aria-label="${esc(r)}${a.roles.includes(r)?'可操作':'无权限'}">${a.roles.includes(r)?'●':'—'}</td>`).join('')}</tr>`;}).join('')}</tbody></table></div></section>${renderOperatorUsers()}<section class="panel erp-access-roadmap"><h2>正式上线前的权限建设</h2><p>下一阶段接入实名账号和登录会话、用户角色配置、地区 / 市场 / 客户数据范围，以及管理员授权审计。当前页面用于核对既有岗位分工，不提供权限修改。</p><p>目前仍是本机试运行，岗位由界面选择；尚不具备账号身份认证或按用户隔离数据的能力。</p></section>`;}

function orderTable(orders,opts={}){
 const rows=orders.filter(o=>(filter==='all'||o.state===filter||o.status===filter)&&(!search||[o.id,o.customer_id,o.customer_name,o.route,...o.lines.map(l=>l.product_name)].join(' ').toLowerCase().includes(search.toLowerCase())));
 return `<div class="table-wrap"><table><thead><tr><th>客户 / 单号</th><th>业务日期 · 线路</th><th>产品与实发</th><th>结算金额</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.map(o=>`<tr><td><span class="customer-name">${esc(o.customer_name)}</span><small class="mono">${esc(o.id)}</small></td><td>${esc(o.business_date)}<small>${esc(o.route)} · ${esc(o.batch)}</small></td><td>${o.lines.slice(0,2).map(l=>`${esc(l.product_name)} <span class="dim">${num(l.actual_qty)}${esc(l.unit)}</span>`).join('<br>')}${o.lines.length>2?`<small>共${o.lines.length}项产品</small>`:''}</td><td class="amount mono">${['ready','reviewed'].includes(o.state)?amount(o.total_cents):'<span class="dim">待确认</span>'}${o.state==='reviewed'?`<small>未收 ${amount(orderOutstanding(o))}</small>`:''}</td><td>${badge(o)}</td><td><div class="table-action"><button class="text-button" data-act="detail" data-id="${esc(o.id)}">查看 ↗</button>${actionLink(o)}</div></td></tr>`).join('')||'<tr><td colspan="6" class="empty">当前筛选范围内暂无单据，请调整日期或筛选条件。</td></tr>'}</tbody></table></div><div class="table-end"><span>共 ${rows.length} 笔 · ${selectedDate||'全部业务日期'}</span><span>${opts.foot||'单据保留价格、皮重与实际称重记录'}</span></div>`;
}
function actionLink(o){
 let label='';
 if(canAction('finance.review')&&o.state==='ready')label='客户复核';
 else if(canAction('finance.receipt')&&o.state==='reviewed'&&orderOutstanding(o)>0)return `<button class="text-button" data-act="receipt" data-id="${esc(o.id)}">收款</button>`;
 else if(canAction('finance.settle')&&!o.discount_cents&&!o.rounding_cents&&!o.paid_cents&&!o.return_credit_cents&&o.state!=='draft')label='客户算票';
 else if(canAction('orders.write')&&['draft','dispatched'].includes(o.state))label='填重量';
 return label?`<button class="text-button" data-sheet-action="focus-order" data-id="${esc(o.id)}">${label}</button>`:'';
}

function homeTasks(){
 const orders=data.orders||[],returns=(data.sales_returns||[]).filter(r=>!r.voided),day=selectedDate||today();
 const visible=p=>!data.auth_user||(data.access_catalog?.modules||[]).some(m=>m.page===p&&moduleVisible(m));
 const defs=[
 ['orders.write','orders','订货录入','核对当天客户和订货数量',orders.filter(o=>o.state==='draft')],
 ['inventory.stock','allocation','登记库存','登记当天库存和生产数量',[]],
 ['inventory.dispatch','allocation','分配与实发','核对库存、分配数量并确认实发',orders.filter(o=>o.state==='draft')],
 ['delivery.schedule','dispatch','配送排车','按线路安排车辆和司机',orders.filter(o=>o.state==='draft'&&!isPickupOrder(o)&&!(data.dispatch_plans||[]).some(p=>p.business_date===o.business_date&&(p.assignments||[]).some(a=>a.market_id===orderMarketId(o,p))))],
 ['weight.confirm','weighing','称重交接',canAction('weight.write')?'补齐实发与称重，确认后交会计':'核对原始称重，确认后交会计算票',orders.filter(o=>o.state==='dispatched'&&!o.weight_confirmation)],
 ['finance.settle','settlements','客户算票','处理待算票与待重算单据',orders.filter(o=>['draft','dispatched','negotiation'].includes(o.state)&&o.lines.some(l=>Number(l.actual_qty)>0))],
 ['finance.review','settlements','账单复核','对照原始凭据复核，或退回会计',orders.filter(o=>o.state==='ready')],
 ['finance.receipt','ledger','收款核销','登记到账、折扣和抹零',orders.filter(o=>o.state==='reviewed'&&orderOutstanding(o)>0)],
 ['inventory.process','allocation','退货待加工','核对退货原批次，登记实际转加工产出',(data.processing_batches||[]).filter(b=>!b.voided&&b.origin==='customer_return'&&b.state==='pending')],
 ['returns.register','returns','退货登记与实物','登记客户退货，并选择继续发货、转加工或报废',returns.filter(r=>{const left=returnRemaining(r);return r.receipt_mode!=='merchant_disposed'&&(left.qty>0||left.kg>0);})],
 ['returns.account','returns','退货核定','核对原销售价格与扣款数量',returns.filter(r=>!r.finance)],
 ['returns.review','returns','退货复核','复核退货扣款后抵入应收',returns.filter(r=>r.finance&&r.finance.state!=='posted')],
 ['returns.refund','returns','退货待抵与退款','核对尚未抵账或退款的退货余额',returns.filter(r=>returnWallet(r)>0)],
 ['inventory.close','allocation','日终结转','确认当天实盘结存，交接下一日', (data.warehouse_plans||[]).filter(p=>!(data.stock_closings||[]).some(c=>c.business_date===p.business_date&&c.state==='closed')).map(p=>({...p,id:p.business_date}))]
 ];
 const tasks=defs.filter(([key,p])=>canAction(key)&&visible(p)).map(([key,p,title,description,items])=>({key,page:p,title,description,items:items.filter(o=>(o.business_date||o.received_date)<=day),today:items.filter(o=>(o.business_date||o.received_date)===day).length}));return typeof enrichDailyTasks==='function'?enrichDailyTasks(tasks,day):tasks;
}
function dashboard(){
 if(role==='老板'&&data.permissions?.modules?.includes('workspace.analytics'))return ownerDashboard();
 if(role==='司机')return driverDashboard();
 const tasks=homeTasks(),day=selectedDate||today();
 return homeDateControls(day)+dailyWorkReminder(tasks,day)+homeWorkflow(tasks,day)+homePendingList(tasks,day);
}
function openHomeTask(index,id,hint=null){
 const tasks=homeTasks(),task=hint?tasks.find(t=>t.key===hint.key):tasks[index];if(!task)return;if(task.page==='expense-payables'){expensePayStage=task.key==='costs.pay'?'pay':'review';expensePayMonth='';expensePaySupplier='';expensePayCounterparty='';expensePaySearch=id||'';if(typeof resourceLedgerState!=='undefined'){delete resourceLedgerState['expense-payables'];delete resourceLedgerState['expense-payments'];}}
 const item=task.items.find(o=>o.id===id)||(hint?.item?.id===id?hint.item:null);
 selectedDate=item?.business_date||item?.received_date||selectedDate||today();
 if(task.page==='allocation')warehouseTab=({'inventory.stock':'stock','inventory.dispatch':'allocation','inventory.close':'closing','inventory.process':'processing'})[task.key]||'stock';
 if(task.page==='returns')returnStage=({'returns.register':'register','returns.account':'account','returns.review':'review','returns.refund':'completed'})[task.key]||'register';
 if(['attendance','factory'].includes(task.page))factoryDay=selectedDate;if(task.page==='attendance')attendanceView=task.key==='production.schedule'?'schedule':'day';
 if(task.page==='dispatch')dispatchTab=task.key==='inventory.dispatch'?'loads':'schedule';if(task.key==='crates.confirm'){assetView='driver-requests';assetDay=selectedDate;assetSearch='';assetCache=null;}
 if(task.page==='ledger'){ledgerMarket='';ledgerCustomer='';ledgerSearch=id||'';ledgerClearance='open';if(typeof clearDateRange==='function')clearDateRange();}
 if(['weighing','settlements'].includes(task.page)){sheetSearch='';sheetRoute='';sheetTrip='';sheetArchive=false;if(typeof clearDateRange==='function')clearDateRange();}
 if(['purchases','purchase-receipts','payables'].includes(task.page)){purchaseMonth='';purchaseStatus='';purchaseSupplier='';purchaseSearch=item&&!String(item.id).startsWith('DAY:')?item.id:'';}
 if(task.key==='costs.write'&&item){resourcesMonth=item.period||item.business_date.slice(0,7);delete resourceLedgerState.expenses;delete resourceLedgerState['expenses-voided'];}
 goto(task.page);
 if(task.key==='costs.write'&&item)costExpenseDialog(item.id).catch(err);
 if(task.key==='materials.write'){resourcesMonth=selectedDate.slice(0,7);materialView='stock';materialWarehouse='';materialCategory='';materialLedgerFilter='';materialSearch='';materialState='';render();}if(task.key==='materials.issue'){factoryWorkTab='beans';render();}
 if(item&&task.key==='materials.value')openResourceForm('value',item.id).catch(err); // 待办可能早于首页窗口，表单按 id 兜底读历史流水
 if(item&&task.key==='byproducts.receive')openResourceForm('receive',id);
 if(task.page==='settlements')accountingBook=task.key==='purchases.cost'?'purchase':'sales';
 if(task.page==='settlements'){sheetStatus=task.key==='finance.review'?'ready':'pending';render();}
 if(item&&task.key==='finance.receipt')receipt(id);
 else if(item&&['finance.settle','finance.review','weight.confirm'].includes(task.key)){if(typeof clearDateRange==='function')clearDateRange();processingBatch=item.batch;sheetSearch=id;sheetRoute='';sheetTrip='';sheetArchive=false;render();}
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-home-task]');if(b){const i=Number(b.dataset.homeTask),id=b.dataset.homeId,t=homeTasks()[i],hint=t?{key:t.key,item:t.items.find(o=>o.id===id)}:null;const run=()=>openHomeTask(i,id,hint);if(typeof requestPageTransition==='function')requestPageTransition(run);else run();}});
function orderArchive(settlement=false){
 const orders=filteredOrders();const counts=k=>orders.filter(o=>o.state===k).length;
 const tabs=settlement?[['all','全部'],['dispatched','待算票'],['ready','待复核'],['reviewed','已复核']]:[['all','全部单据'],['draft','待发货'],['dispatched','待算票'],['ready','待复核'],['reviewed','已复核']];
 return head(settlement?'结算与复核':'订货与送货',settlement?'两次原始重量、结算依据和复核记录，全程可追溯。':'订货不覆盖实发，司机卸货与客户复称分别记录。',`<button class="button primary" data-act="new">＋ 新建订货</button>`,settlement?'SETTLEMENT · 账单核对':'ORDERS · 业务单据')+period()+
 `<section class="panel"><div class="table-toolbar">${tabs.map(([k,v])=>`<button class="tab ${filter===k?'active':''}" data-filter="${k}">${v}<span>${k==='all'?orders.length:counts(k)}</span></button>`).join('')}<label class="search">⌕<input id="search" placeholder="客户、单号、产品" aria-label="搜索单据" value="${esc(search)}"></label></div><div id="order-table">${orderTable(orders)}</div></section>`;
}
function masters(){return renderMasterData();}

function production(){return resourceProductionPage();}
function logs(){if(data.auth_user)return renderAuthenticatedAudit();return head('操作记录','单据修订、结算、复核、收款和档案维护均保留轨迹。',`<button class="button" data-act="backup">↓ 备份数据库</button>`,'AUDIT TRAIL · 过程追溯')+trialArchivePanel()+archivedOrderPanel()+`<div class="callout">当前显示最近200条操作。记录中的岗位为试运行模拟岗位；完整变更前后数据保存在本地数据库。</div><section class="panel"><div class="panel-head"><h2>最近操作</h2><small>北京时间 · UTC+8</small></div><div class="log-list">${data.audit.map(a=>`<div class="log"><span class="log-dot"></span><div><b>${esc(a.action)}</b> <span class="badge">${esc(a.role)}</span><small>${esc(a.at.replace('T',' '))} · ${esc(a.entity)}</small></div></div>`).join('')}</div></section>`;}
function render(){if(typeof destroyReportCharts==='function')destroyReportCharts();document.body.dataset.currentPage=page;const versionLabel=$('#app-version');if(versionLabel&&typeof data!=='undefined'&&data?.app_version)versionLabel.textContent='V'+data.app_version;const accountVersion=$('#account-app-version');if(accountVersion&&data?.app_version)accountVersion.textContent='V'+data.app_version;nav();$('#content').innerHTML=(page!=='dashboard'?'<button class="page-back" data-go-back><span aria-hidden="true">←</span> 返回上个页面</button>':'')+({'system-settings':systemSettingsPage,'fund-accounts':fundAccountsPage,'driver-work':driverPage,'report-map':reportMapPage,'product-profit':productProfitPage,assets:assetPage,crates:cratePage,payroll:payrollPage,factory:factoryPage,employees:employeePage,'management-employees':employeePage,attendance:attendancePage,'management-attendance':attendancePage,'production-report':productionReportPage,'soy-inventory':soyInventoryPage,'factory-settings':factorySettingsPage,curing:curingPage,'sales-daily':salesReportPage,'sales-monthly':salesReportPage,users:renderUsers,dashboard,directory,suppliers:renderSuppliers,purchases:renderPurchases,'purchase-receipts':renderPurchaseReceipts,payables:renderPayables,'material-issue':materialIssuePage,workshop:workshopPage,materials:resourceMaterialPage,expenses:resourceExpensePage,'expense-payables':resourceExpensePayablePage,byproducts:resourceByproductPage,'transport-settlement':transportSettlementPage,'transport-providers':transportProvidersPage,analytics:resourceAnalyticsPage,access:accessOverview,dispatch:renderDispatch,allocation:renderWarehouse,returns:renderReturns,orders:()=>renderWorkbench('order'),archive:renderOrderArchive,settlements:()=>renderWorkbench('account'),weighing:()=>renderWorkbench('weight'),ledger,masters,production,chat:chatPage,feedback:feedbackPage,logs}[page])();if(typeof renderFactoryWarnings==='function')renderFactoryWarnings();if(typeof setupCustomerDisclosures==='function')setupCustomerDisclosures($('#content'));if(typeof normalizeWorkflowStatuses==='function')normalizeWorkflowStatuses($('#content'));const back=$('#content > .page-back');if(back)$('#content').prepend(back);if(typeof applyPageActionAccess==='function')applyPageActionAccess($('#content'));if(typeof setupPageSwitchbar==='function')setupPageSwitchbar();if(typeof labelWeightCells==='function')labelWeightCells();if(typeof alignBusinessTables==='function')alignBusinessTables($('#content'));if(typeof installTradeControls==='function')installTradeControls();if(typeof normalizeFormLabels==='function')normalizeFormLabels($('#content'));if(typeof filterCascadeApply==='function')document.querySelectorAll('#content form').forEach(f=>{if(f.querySelector('select[name=category]')&&f.querySelector('select[name=material_id]'))filterCascadeApply(f);});installWorkStatus();if(typeof updateSaveStatus==='function')updateSaveStatus();if(typeof refreshWorkflowSignals==='function')refreshWorkflowSignals($('#content'));if(typeof updateWideModeControls==='function')updateWideModeControls();if(typeof mountReportCharts==='function')mountReportCharts($('#content'));lastPageLocation={page,selectedDate,masterView,factoryDay,warehouseTab,dispatchTab,attendanceView,factoryWorkTab};updateBackToTop();if(typeof reportEntryAnchor!=='undefined'&&reportEntryAnchor){const target=document.getElementById(reportEntryAnchor);if(target){target.scrollIntoView({block:'start'});reportEntryAnchor='';}}}
function openDialog(title,html,label='业务操作',actions=''){
 dialogGeneration++;clearTimeout(dialogCloseTimer);
 const toast=$('#toast');if(toast)toast.hidden=true;
 lastFocus=document.activeElement;$('#dialog-title').textContent=title;const dialogLabel=$('#dialog-label');if(dialogLabel){dialogLabel.textContent='';dialogLabel.hidden=true;}
 $('#dialog-body').innerHTML=`<div class="dialog-content"><div id="dialog-error" class="dialog-error" role="alert" hidden></div>${html}${html.includes('<form')?'<p class="dialog-save-note">请使用下方按钮提交；直接关闭不会保存。</p>':''}</div>${actions?`<div class="dialog-actions">${actions}</div>`:''}`;
 if(typeof installFundAccountSelector==='function')installFundAccountSelector($('#dialog-body'));
 dialogExpected=undefined;const masterForm=$('#dialog-body form');if(masterForm?.getAttribute('id')==='customer-form'&&masterForm.elements.existing.value)dialogExpected=structuredClone(data.customers.find(c=>c.id===masterForm.elements.id.value));if(masterForm?.getAttribute('id')==='product-form'&&masterForm.elements.create.value==='0')dialogExpected=structuredClone(data.products.find(p=>p.id===masterForm.elements.id.value));
 if(typeof setupCustomerDisclosures==='function'){customerDialogSequence++;setupCustomerDisclosures($('#dialog-body'));normalizeWorkflowStatuses($('#dialog-body'));}if(typeof labelWeightCells==='function')labelWeightCells();if(typeof alignBusinessTables==='function')alignBusinessTables($('#dialog-body'));if(typeof normalizeFormLabels==='function')normalizeFormLabels($('#dialog-body'));$('#overlay').hidden=false;document.body.classList.add('modal-open');$('#dialog').focus();queueMicrotask(()=>{dialogBaseline=dialogValues();if(typeof updateSaveStatus==='function')updateSaveStatus();});
}
function closeDialog(){if(busy){const generation=dialogGeneration;clearTimeout(dialogCloseTimer);dialogCloseTimer=setTimeout(()=>{if(generation===dialogGeneration)closeDialog();},100);return;}clearTimeout(dialogCloseTimer);dialogBaseline='';dialogExpected=undefined;$('#overlay').hidden=true;document.body.classList.remove('modal-open');activeOrder=null;draft=null;if(document.getElementById('workflow-feedback')?.hidden!==false)lastFocus?.focus();if(typeof updateSaveStatus==='function')updateSaveStatus();}
function err(e){if(e.issues?.length){presentValidation(e.issues);showOperationError(e);return;}const el=$('#dialog-error');if(el&&!$('#overlay').hidden){showOperationError(e,el);}else showOperationError(e);}
async function perform(fn){
 if(busy)return;busy=true;const before=successfulWrites,buttons=$$('button', $('#dialog')),states=buttons.map(b=>[b,b.disabled]);
 const trigger=document.activeElement?.closest('#dialog .dialog-actions button'),label=trigger?.innerHTML,noticeAtStart=notificationSequence,dialogAtStart=dialogGeneration,formAtStart=$('#dialog-body form'),hadForm=!!formAtStart;let completed=false;
 states.forEach(([b])=>b.disabled=true);if(trigger){trigger.textContent=/保存/.test(trigger.textContent)?'正在保存…':'正在提交…';trigger.setAttribute('aria-busy','true');}
 try{await fn();completed=true;}catch(e){if(successfulWrites>before&&e.readFailure)e.confirmedWrite=true;err(e);}finally{busy=false;if(completed&&successfulWrites>before&&trigger&&noticeAtStart===notificationSequence)notify('操作已保存，请核对页面结果');if(completed&&successfulWrites>before&&hadForm&&formAtStart.isConnected!==false&&$('#dialog-body form')===formAtStart&&dialogAtStart===dialogGeneration&&trigger&&!/继续|预览|新增并/.test(label||'')&&!$('#overlay').hidden)closeDialog();states.forEach(([b,disabled])=>b.disabled=disabled);if(trigger?.isConnected){trigger.innerHTML=label;trigger.removeAttribute('aria-busy');}if(typeof updateSaveStatus==='function')updateSaveStatus();}
}
async function submit(path,body,message){const result=await api(path,body);visibleIssues=[];await refresh();persistDrafts();busy=false;closeDialog();if(typeof updateSaveStatus==='function')updateSaveStatus();notify(typeof message==='function'?message(result):message);}
function needRole(r){if(role!==r){notify(`此操作请先将右上角模拟岗位切换为「${r}」`);return false;}return true;}
function ruleFor(cid,pid){const p=data.products.find(p=>p.id===pid);return data.rules.find(r=>r.customer_id===cid&&r.product_id===pid)||p;}
function defaultLine(pid=data.products[0].id,cid=salesCustomers()[0]?.id){const p=data.products.find(p=>p.id===pid),r=ruleFor(cid,pid);return {product_id:pid,ordered_qty:'1',actual_qty:'0',price:r.price,driver:[],customer:[]};}
function editOrder(id){
 if(!canAction('orders.write')){notify('订货和称重录入请切换为库管或会计');return;}
 const old=data.orders.find(o=>o.id===id);
 if(old?.paid_cents||old?.discount_cents||old?.rounding_cents||old?.return_credit_cents){notify('已有收款或退货抵扣的单据已锁定');return;}
 if(old&&!canAction('finance.settle')&&['ready','reviewed','negotiation'].includes(old.state)){notify('该单据已进入结算，请由会计修订');return;}
 draft=old?structuredClone(old):{customer_id:salesCustomers()[0]?.id,business_date:today(),batch:'日常订货',daily_order:true,note:'',lines:[defaultLine()]};
 draft.workflow_version=1;draft.dispatch_required=true;activeOrder=old;
 openDialog(old?'补录 / 修订送货单':'新建订货单',`<form id="order-form"><div class="callout">订货数量与实发数量分别记录。筐装产品可分批追加称重；客户复称可选，已录入的原始重量保留。${old&&['ready','reviewed','negotiation'].includes(old.state)?'<br><strong>保存修订后，原结算与复核失效，需重新算票和复核。</strong>':''}</div><div class="form-grid"><label class="field">客户<select name="customer_id" id="order-customer">${salesCustomers().map(c=>`<option value="${esc(c.id)}" ${draft.customer_id===c.id?'selected':''}>${esc(c.id)} · ${esc(c.name)}</option>`).join('')}</select></label><label class="field">业务日期<input name="business_date" type="date" required value="${esc(draft.business_date)}"></label><input type="hidden" name="batch" value="${esc(draft.batch)}"></div><div id="draft-lines"></div><button type="button" class="text-button" data-act="add-line">＋ 添加产品</button><label class="field">单据备注<textarea name="note" rows="2" maxlength="500">${esc(draft.note)}</textarea></label></form>`,old?old.id:'ORDER ENTRY · 库管 / 会计',`<button class="button" data-act="close">取消</button><button class="button primary" data-act="save-order">保存单据</button>`);
 renderDraftLines();
}
function renderDraftLines(){
 $('#draft-lines').innerHTML=draft.lines.map((l,i)=>{const p=data.products.find(p=>p.id===l.product_id);return `<div class="line-card" data-line="${i}"><div class="line-head"><select aria-label="第${i+1}项产品" data-product="${i}">${data.products.map(p=>`<option value="${esc(p.id)}" ${l.product_id===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select><button type="button" class="text-button" data-act="remove-line" data-index="${i}">移除产品</button></div><div class="line-data"><label class="field">订货数量（${p.unit}）<input type="number" min="${p.fractional?'.001':'1'}" step="${p.fractional?'.001':'1'}" required data-key="ordered_qty" value="${esc(l.ordered_qty)}"></label><label class="field">实际发货（${p.unit}）<input type="number" min="0" step="${p.fractional?'.001':'1'}" required data-key="actual_qty" value="${esc(l.actual_qty)}" ${data.auth_user&&!canAction('weight.write')?'readonly':''}></label>${canSeeData('sales-prices')?`<label class="field">单价（元/${billingUnit(l)}）<input type="number" min="0.001" step="0.001" required data-key="price" value="${esc(l.price)}" ${authUser&&!canAction('finance.price-edit')?'readonly':''}></label>`:'<span class="help-text">单价由系统按已核定价格关联</span>'}</div>${p.unit==='筐'?`<div class="weight-columns">${['driver','customer'].map(type=>weightBox(l,type,i)).join('')}</div><div class="diff-note" data-diff="${i}"></div>`:`<div class="line-standard">按${esc(billingUnit(l))}计价${billingUnit(l)==='公斤'?' · 标准 '+esc(p.standard_kg)+'公斤/'+esc(p.unit):' · 以实发数量结算'}。${billingUnit(l)==='公斤'?`<label class="field">包装实称净重（公斤，可选）<input data-key="package_net_kg" type="number" min="0.001" step="0.001" value="${esc(l.package_net_kg||'')}"></label>`:''}</div>`}</div>`;}).join('');
 if(data.auth_user&&!canAction('weight.write')){for(const input of $$('#draft-lines [data-wkey],#draft-lines [data-driver-direct],#draft-lines [data-key=package_net_kg]'))input.readOnly=true;for(const button of $$('#draft-lines [data-act=add-weight],#draft-lines [data-act=remove-weight]'))button.disabled=true;}updateSummaries();
}
function weightBox(l,type,i){if(type==='driver'){const net=l.driver.length?String(Number(calcWeights(l,'driver').net.toFixed(3))):'';return `<div class="weight-box"><div class="weight-title"><strong>司机净重</strong></div><label class="field">净重（公斤）<input data-driver-direct="${i}" data-initial="${esc(net)}" type="number" min="0.001" step="0.001" value="${esc(net)}"></label></div>`;}return `<div class="weight-box"><div class="weight-title"><strong>${type==='driver'?'司机卸货称重':'客户早晨复称（可选）'}</strong><button type="button" class="text-button" data-act="add-weight" data-index="${i}" data-source="${type}">＋ 分批</button></div><div class="weight-labels"><span>毛重 kg</span><span>合称筐数</span><span>单筐皮重 kg</span><span></span></div>${l[type].map((w,j)=>`<div class="weight-row" data-weight="${j}" data-source="${type}"><input aria-label="毛重（公斤）" type="number" min="0.001" step="0.001" data-wkey="gross" value="${esc(w.gross)}"><input aria-label="合称筐数" type="number" min="1" step="1" data-wkey="count" value="${esc(w.count)}"><input aria-label="单筐皮重（公斤）" type="number" min="0" step="0.001" data-wkey="tare" value="${esc(w.tare)}"><button type="button" class="icon-button" aria-label="移除此称重批次" data-act="remove-weight" data-index="${i}" data-source="${type}" data-weight-index="${j}">×</button></div>`).join('')||'<div class="help-text">暂无记录，点击「＋ 分批」添加</div>'}<div class="weight-summary" data-summary="${i}-${type}"></div></div>`;}
function syncDraft(){
 if(!draft||!$('#order-form'))return;
 const form=$('#order-form');draft.customer_id=form.elements.customer_id.value;draft.business_date=form.elements.business_date.value;draft.batch=form.elements.batch.value;draft.note=form.elements.note.value;
 $$('[data-line]',form).forEach(card=>{const l=draft.lines[Number(card.dataset.line)];const previousActual=l.actual_qty;$$('[data-key]',card).forEach(inp=>l[inp.dataset.key]=inp.value);const net=$('[data-driver-direct]',card);if(net&&(net.value!==net.dataset.initial||Number(previousActual)!==Number(l.actual_qty))){l.driver=net.value===''?[]:[{gross:net.value,count:l.actual_qty,tare:'0',note:'司机净重'}];net.dataset.initial=net.value;}$$('[data-weight]',card).forEach(row=>{const w=l[row.dataset.source][Number(row.dataset.weight)];$$('[data-wkey]',row).forEach(inp=>w[inp.dataset.wkey]=inp.value);});});
}
function calcWeights(l,type){return l[type].reduce((a,w)=>({net:a.net+Number(w.gross||0)-Number(w.count||0)*Number(w.tare||0),count:a.count+Number(w.count||0),complete:a.complete&&w.gross!==''&&Number(w.gross)>Number(w.count)*Number(w.tare)&&Number(w.count)>0}),{net:0,count:0,complete:true});}
function updateSummaries(){draft.lines.forEach((l,i)=>{const d=calcWeights(l,'driver'),c=calcWeights(l,'customer');for(const type of ['driver','customer']){const el=$(`[data-summary="${i}-${type}"]`);const v=type==='driver'?d:c;if(el)el.textContent=v.complete?`合计 ${num(v.count)} 筐 · 净重 ${num(v.net)} 公斤`:'待完整填写毛重、筐数和皮重后计算净重';}const el=$(`[data-diff="${i}"]`);if(el)el.textContent=l.driver.length&&l.customer.length&&d.complete&&c.complete?`司机净重 − 客户净重：${num(d.net-c.net)} 公斤 · 每筐差 ${Number(l.actual_qty)>0?num((d.net-c.net)/Number(l.actual_qty)):'—'} 公斤 · 是否接受由会计判断`:'两次称重均在客户处发生；此处不设自动接受阈值。';});}
function weighDetail(line,o){if(billingUnit(line)!=='公斤')return `<div class="line-standard">实发 ${num(line.actual_qty)} ${esc(line.unit)} · 结算 ${num(line.bill_qty??line.actual_qty)} ${esc(billingUnit(line))}</div>`;if(line.unit!=='筐')return `<div class="line-standard">实发 ${num(line.actual_qty)} ${esc(line.unit)} × ${line.standard_kg} 公斤/${esc(line.unit)}（标准量）；${billingUnit(line)==='公斤'?`结算 ${num(line.bill_qty??packageBillKg(line))} 公斤（${line.package_customer_net_kg?'客户复称':line.package_net_kg?'司机实称':line.factory_net_kg?'出厂称重':'标准包装折算'}）`:'历史按包数结算'}。</div>`;const pickup=o&&isPickupOrder(o),sources=pickup&&!line.driver.length?['customer']:['driver','customer'];return `<div class="weight-columns">${sources.map(type=>`<div class="weight-box"><div class="weight-title"><strong>${type==='driver'?'司机卸货':pickup?'自提确认称重':'客户复称'}</strong><span>净重 ${line[type].length?num(line[type+'_net'])+' kg':'待填写'}</span></div>${line[type].map((w,j)=>`<div class="help-text">第${j+1}批：${type==='driver'?'净重 '+num(Number(w.gross)-Number(w.count)*Number(w.tare))+' 公斤':num(w.gross)+' − '+num(w.count)+'筐 × '+num(w.tare)+' = '+num(Number(w.gross)-Number(w.count)*Number(w.tare))+' kg'}</div>`).join('')||'<div class="help-text">尚未记录</div>'}</div>`).join('')}</div><div class="diff-note">${line.driver.length&&line.customer.length?`两次净重差 ${num(Number(line.driver_net)-Number(line.customer_net))} kg · 每筐差 ${Number(line.actual_qty)?num((Number(line.driver_net)-Number(line.customer_net))/Number(line.actual_qty)):'—'} kg`:pickup?'客户自取，不要求司机卸货称重':'两次称重填写完整后显示净重差'}${line.bill_qty?` · 最终结算 ${num(line.bill_qty)} kg`:''}</div>`;}

function canReadAuditTrail(){const user=data.auth_user;return !user||user.role==='管理员'||(data.permissions?.modules||[]).includes('system.audit');}
function orderAuditMarkup(rows){return rows.length?`<h3 class="section-heading">操作轨迹</h3>${rows.map(a=>`<p class="help-text">${esc(a.at.replace('T',' '))} · ${esc(a.role)} · ${esc(a.action)}</p>`).join('')}`:'';}
function orderAuditTrail(o){
 if(!o||!canReadAuditTrail())return '';
 if(!data.auth_user)return orderAuditMarkup(data.audit.filter(a=>a.entity===o.id));
 setTimeout(()=>loadOrderAuditTrail(o.id),0);
 return `<div data-order-audit="${esc(o.id)}"></div>`;
}
async function loadOrderAuditTrail(id){
 const slot=()=>[...document.querySelectorAll('#dialog-body [data-order-audit]')].find(el=>el.dataset.orderAudit===id);
 try{
  const result=await api('/api/audit?all=1&entity='+encodeURIComponent(id)+'&page_size=200');
  const rows=(result.rows||[]).slice().sort((a,b)=>b.id-a.id);
  const target=slot();if(target)target.outerHTML=orderAuditMarkup(rows);
 }catch(error){const target=slot();if(target)target.outerHTML='';}
}
function detail(id){
 const o=data.orders.find(o=>o.id===id);if(!o)return;activeOrder=o;
 const editable=!o.discount_cents&&!o.rounding_cents&&!o.paid_cents&&!o.return_credit_cents&&canAction('orders.write')&&!(!canAction('finance.settle')&&['ready','reviewed','negotiation'].includes(o.state));
 openDialog(o.customer_name,`<div class="detail-meta">${badge(o)}<span>单号 <b>${esc(o.id)}</b></span><span>业务日期 <b>${o.business_date}</b></span><span>批次 <b>${esc(o.batch)}</b></span><span>修订号 ${o.version}</span></div><p class="help-text">${esc(o.note)||'无单据备注'}</p>${o.lines.map(l=>`<section class="line-card"><div class="line-head"><strong>${esc(l.product_name)}</strong><span class="amount">${l.bill_qty?amount(l.amount_cents):'待结算'}</span></div><div class="client-stats"><span>订货 ${num(l.ordered_qty)}${l.unit}</span><span>实发 ${num(l.actual_qty)}${l.unit}</span>${canSeeData('sales-prices')?`<span>单价 ${num(l.price)}元/${billingUnit(l)}</span>`:''}</div>${weighDetail(l,o)}</section>`).join('')}
 ${o.settlement?`<h3 class="section-heading">结算依据</h3><div class="callout ${o.state==='negotiation'?'warning':''}">${o.state==='negotiation'?'待算票，尚未形成结算账单':o.settlement.mode==='auto'?'按客户复称、司机、出厂、标准重量依次取值':o.settlement.mode==='mixed'?'各产品分别按选定重量依据结算':o.settlement.mode==='factory'?'出厂净重结算':o.settlement.mode==='standard'?'标准重量结算':o.settlement.mode==='driver'?'司机卸货净重结算（客户未复称）':o.settlement.mode==='agreed'?'协商净重结算（包装产品按实称或标准折算公斤）':'人工接受客户复称（包装产品按实称或标准折算公斤）'}<br>${esc(o.settlement.reason)||'无补充说明'}</div>`:''}
 ${o.review?`<p class="help-text">复核：${esc(o.review.role)} · ${esc(o.review.at)} · ${esc(o.review.note)}</p>`:''}
 ${canSeeData('sales-prices')?`<div class="receipt-summary"><div><small>结算金额 ${o.state==='ready'?'（待复核）':''}</small><strong>${amount(o.total_cents)}</strong></div><div><small>退货已抵</small><strong>${amount(o.return_credit_cents||0)}</strong></div><div><small>折扣 / 抹零</small><strong>${amount(o.discount_cents||0)} / ${amount(o.rounding_cents||0)}</strong></div><div><small>已收款</small><strong>${amount(o.paid_cents)}</strong></div><div><small>${o.state==='reviewed'?'未收余额':'尚未计入应收'}</small><strong>${o.state==='reviewed'?amount(orderOutstanding(o)):'—'}</strong></div></div>
 ${reviewHistory(o)}`:''}${orderAuditTrail(o)}`,
 'ORDER DETAIL · 完整记录',`<button class="button" data-act="close">关闭</button>${editable?`<button class="button" data-act="edit" data-id="${esc(o.id)}">修订 / 补录</button>`:''}${canAction('finance.settle')&&!o.discount_cents&&!o.rounding_cents&&!o.paid_cents&&!o.return_credit_cents&&!['draft','reviewed'].includes(o.state)?`<button class="button primary" data-act="settle" data-id="${esc(o.id)}">${o.state==='negotiation'?'确认本单算票':'确认结算'}</button>`:''}${canAction('finance.review')&&o.state==='ready'?`<button class="button primary" data-act="review" data-id="${esc(o.id)}">对照凭据复核</button>`:''}${canAction('finance.receipt')&&o.state==='reviewed'&&orderOutstanding(o)>0?`<button class="button primary" data-act="receipt" data-id="${esc(o.id)}">登记收款</button>`:''}`);
}
function settle(id){
 if(!needPermission('finance.settle'))return;const o=data.orders.find(o=>o.id===id);if(o.paid_cents||o.discount_cents||o.rounding_cents||o.return_credit_cents){notify('已收款单据已锁定');return;}if(o.state==='reviewed'){notify('已复核未收款，须先由出纳退回会计后再重算');return;}if(['draft','dispatched'].includes(o.state)&&!o.weight_confirmation){notify('请先到称重总表确认称重并交会计');return;}activeOrder=o;
 openDialog('确认结算 · '+o.customer_name,`<form id="settle-form"><div class="callout warning">会计人工判断重量差异。不自动接受客户复称；协商结算须填写最终净重及原因。提交后由出纳对照原始凭据复核。</div>${o.lines.map(l=>`<section class="line-card"><div class="line-head"><strong>${esc(l.product_name)}</strong><span class="help-text">${num(l.price)} 元/${billingUnit(l)}</span></div>${weighDetail(l,o)}</section>`).join('')}<h3 class="section-heading">本单结算方式</h3><div class="radio-group"><label class="radio-label"><input type="radio" name="mode" value="auto" ${(o.state!=='negotiation'||o.review_return?.status==='pending')?'checked':''}>自动选择：客户复称 → 司机 → 出厂 → 标准重量</label><label class="radio-label"><input type="radio" name="mode" value="customer">${isPickupOrder(o)?'按自提确认重量':'接受客户复称'}</label><label class="radio-label"><input type="radio" name="mode" value="driver">按司机卸货净重</label><label class="radio-label"><input type="radio" name="mode" value="factory">按出厂净重</label><label class="radio-label"><input type="radio" name="mode" value="standard">按标准重量</label><label class="radio-label"><input type="radio" name="mode" value="agreed" ${(o.state==='negotiation'&&o.review_return?.status!=='pending')?'checked':''}>协商完成，按确认净重</label></div><div id="agreed-fields" ${(o.state==='negotiation'&&o.review_return?.status!=='pending')?'':'hidden'}>${o.lines.filter(l=>l.unit==='筐'&&billingUnit(l)==='公斤').map(l=>`<label class="field">${esc(l.product_name)} · 最终协商净重（公斤）<input name="agreed-${esc(l.product_id)}" type="number" min="0.001" step="0.001" value="${esc(l.agreed_net||(Number(l.customer_net)>0?l.customer_net:l.driver_net))}"></label>`).join('')}</div><label class="field">结算说明 / 协商原因<textarea name="reason" maxlength="500" rows="3" placeholder="使用协商净重时填写确认依据">${esc(o.settlement?.reason||'')}</textarea></label><p class="help-text">按产品计价单位分别计算；公斤计价使用实称净重或标准单重折算，数量计价使用实发数量。最终金额按每项产品四舍五入到分后汇总。</p></form>`,'SETTLEMENT · 会计算票',`<button class="button" data-act="close">取消</button><button class="button primary" data-act="save-settle">确认算票，提交复核</button>`);
}
function reviewHistory(o){const rows=o.review_history||[];if(!rows.length)return '';return `<div class="review-history"><h3>复核处理记录 · 原单 ${esc(o.id)}</h3>${rows.map(r=>`<div><b>${r.status==='approved'?'复核通过':r.status==='resubmitted'?'已退回并重新提交':'退回待重算'}</b><span>${esc(r.at)} · ${esc(r.role)}</span><p>${esc(r.reason||r.note||'已核对原始凭据')} · 当时金额 ${amount(r.total_cents)}</p>${r.resubmitted_at?`<small>会计重新提交：${esc(r.resubmitted_at)} · 修订 ${r.resubmitted_version}</small>`:''}</div>`).join('')}</div>`;}
function reviewComparison(orders){const cid=orders[0]?.customer_id,rs=(data.sales_returns||[]).filter(r=>r.customer_id===cid&&!r.voided),posted=data.orders.filter(o=>o.customer_id===cid&&o.state==='reviewed').reduce((s,o)=>s+orderOutstanding(o),0);return `<div class="callout">请对照订货手机、称重记录与价格约定逐项核对。表中为系统记录，不能代替原始凭据。通过后计入应收；发现问题请退回会计重算。</div><div class="review-summary"><span>本次待复核 <b>${orders.length} 单 · ${amount(orders.reduce((s,o)=>s+o.total_cents,0))}</b></span><span>客户已入账未收 <b>${amount(posted)}</b></span><span>退货待处理 <b>${rs.filter(r=>r.finance?.state!=='posted').length} 批</b></span></div>${orders.map(o=>`<section class="review-order" data-review-order="${esc(o.id)}"><h3>${esc(o.customer_name)} · ${esc(o.business_date)} <small>${esc(o.id)} · 修订 ${o.version}</small></h3><div class="table-wrap"><table class="review-compare-table"><thead><tr><th>产品</th><th>订货 / 实发</th><th>司机净重 kg</th><th>客户净重 kg</th><th>计价来源</th><th>结算量 / 单位</th><th>单价（元）</th><th>金额</th></tr></thead><tbody>${o.lines.map(l=>`<tr><th>${esc(l.product_name)}</th><td>${num(l.ordered_qty)} / ${num(l.actual_qty)}${esc(l.unit)}</td><td>${l.driver?.length?num(l.driver_net):'—'}</td><td>${l.customer?.length?num(l.customer_net):'—'}${l.settlement_tares?.customer!==undefined?`<small>结算皮重 ${num(l.settlement_tares.customer)}，调整后净重 ${num(l.bill_qty)}</small>`:''}</td><td>${esc(({factory:'出厂净重',standard:'标准重量',package_customer:'包装客户复称',driver:'司机净重',customer:isPickupOrder(o)?'自提确认':'客户复称',agreed:'协商净重',package_actual:'包装实称',package_standard:'标准包装折算',package_count:'实发数量',not_shipped:'本次未发'})[l.settlement_mode]||'历史结算')}</td><td>${l.bill_qty===null?'—':num(l.bill_qty)} ${esc(billingUnit(l))}</td><td>${num(l.price)}</td><td>${amount(l.amount_cents)}</td></tr>`).join('')}</tbody></table></div><p>会计算票：${esc(o.settlement?.at||'—')} · ${esc(o.settlement?.reason||'无补充说明')}</p>${reviewHistory(o)}</section>`).join('')}<div class="review-returns"><h3>客户退货扣款对照</h3>${rs.map(r=>`<p>${esc(r.received_date)} · ${esc(r.product_name)} · 实退 ${num(r.net_kg)} 公斤 · ${r.finance?`核定 ${num(r.finance.account_qty)} ${esc(r.finance.billing_unit)} / ${amount(r.finance.amount_cents)} · ${r.finance.state==='posted'?'已复核，待抵余额 '+amount(returnWallet(r)):'待出纳复核，尚未抵账'}`:'待会计核定，尚未抵账'}</p>`).join('')||'<p>暂无退货记录</p>'}<small>销售金额保持原值；退货抵账由独立扣款复核流程处理，避免重复减款。</small></div>`;}
function reviewTargets(form){return JSON.parse(form.dataset.targets||'[]');}
function openReview(orders,batch=false){if(!needPermission('finance.review')||!orders.length)return;activeOrder=orders[0];const id=batch?'review-client-form':'review-form';openDialog('出纳复核对照 · '+orders[0].customer_name,`<form id="${id}" data-targets="${esc(JSON.stringify(orders.map(o=>({id:o.id,version:o.version}))))}">${reviewComparison(orders)}<label class="field">复核备注<textarea name="note" rows="2" maxlength="500"></textarea></label><label class="check-line"><input name="evidence_checked" type="checkbox" required>已对照原始凭据核对客户日期、结算公斤、公斤单价、退货进度和合计金额</label></form>`,'REVIEW · 核对后入账',`<button class="button" data-act="close">继续核对</button><button class="button danger" data-act="return-review">退回会计重算</button><button class="button primary" data-act="${batch?'save-review-batch':'save-review'}">复核通过，应收入账</button>`);}
function review(id){const o=data.orders.find(o=>o.id===id);if(o)openReview([o]);}
function openReturnReview(){const form=$('#dialog-body form'),targets=reviewTargets(form),note=form.elements.note?.value||'';openDialog('退回会计重算',`<form id="return-review-form" data-targets="${esc(JSON.stringify(targets))}"><div class="callout">退回 ${targets.length} 张待复核单据，暂不计入应收。原结算快照和退回原因将留存，会计需重新算票提交，出纳再次核对。订货、实发、库存和称重保持不变。</div><ul>${targets.map(t=>{const o=data.orders.find(o=>o.id===t.id);return `<li>${esc(o?.customer_name)} · ${esc(o?.business_date)} · ${esc(t.id)} · ${amount(o?.total_cents)}</li>`;}).join('')}</ul><label class="field">退回原因<textarea name="reason" required maxlength="500" rows="4" placeholder="请说明具体产品、公斤数、单价或凭据问题">${esc(note)}</textarea></label></form>`,'REVIEW · 退回处理',`<button class="button" data-act="close">取消</button><button class="button danger" data-act="save-return-review">确认退回会计</button>`);}

function voidReceipt(rid,oid){
 if(!needPermission('finance.receipt'))return;const r=(data.receipts||[]).find(x=>x.id===rid);if(!r){notify('找不到这笔收款，请刷新后重试');return;}
 const o=data.orders.find(x=>x.id===(oid||r.order_id));voidTarget={receipt_id:rid,order_id:(o&&o.id)||oid||r.order_id,version:o?o.version:0};
 openDialog('冲销收款 · '+rid,`<form id="void-receipt-form"><div class="callout warning">冲销不删除原流水：该笔收款${amount(r.amount_cents)}标记为已冲销，账单已收金额回退，审计保留原因与操作人。仅用于客户退回转账、重复登记等真实差错。</div><label class="field">冲销原因（必填）<textarea name="reason" required maxlength="200" rows="2" placeholder="例如：客户转账被退回；收款重复登记"></textarea></label></form>`,'VOID RECEIPT',`<button class="button" data-act="close">取消</button><button class="button danger" data-act="save-void-receipt">确认冲销</button>`);
}
function receipt(id){
 if(!needPermission('finance.receipt'))return;const o=data.orders.find(o=>o.id===id);activeOrder=o;
 openDialog('登记收款 · '+o.customer_name,`<form id="receipt-form"><div class="receipt-summary"><div><small>账单金额</small><strong>${amount(o.total_cents)}</strong></div><div><small>本次可收余额</small><strong>${amount(orderOutstanding(o))}</strong></div></div><div class="form-grid"><label class="field">本次到账金额（元）<input name="amount" type="number" min="0" step="0.01" max="${(orderOutstanding(o))/100}" required value="" placeholder="填写实际到账金额"><button type="button" class="text-button" data-act="fill-all-receivable">填入余额</button></label><label class="field">本次折扣（元）<input name="discount" type="number" min="0" step="0.01" required value="0.00"><button type="button" class="text-button" data-act="remaining-discount">填入剩余折扣</button></label><label class="field">本次抹零（元）<input name="rounding" type="number" min="0" step="0.01" required value="0.00"><button type="button" class="text-button" data-act="remaining-rounding">填入剩余抹零</button></label><label class="field">实际到账日期<input name="received_date" type="date" required max="${today()}" value="${today()}"></label><label class="field">收款方式<select name="method"><option>银行转账</option><option selected>微信收款</option><option>支付宝</option><option>现金</option></select></label><label class="field wide">凭据号 / 备注<textarea name="note" maxlength="500" rows="2" placeholder="可记录银行流水号或到账凭据"></textarea></label></div><div id="receipt-balance-preview" class="callout"></div><div class="callout warning">抹零和折扣冲减应收，不计入到账金额；有折扣或抹零时请填写原因。请确认实际到账后再登记。登记后单据锁定；如需冲销，请在对账弹窗对已到账流水执行冲销并填写原因。</div></form>`,'RECEIPT · 收款核销',`<button class="button" data-act="close">取消</button><button class="button primary" data-act="save-receipt">登记收款</button>`);
 updateReceiptPreview();
}
function updateReceiptPreview(fill=''){
 const f=$('#receipt-form');if(!f||!activeOrder)return;
 const cents=name=>Math.round(Number(f.elements[name].value||0)*100),outstanding=orderOutstanding(activeOrder);
 if(fill==='rounding'){
  if(f.elements.amount.value===''){notify('请先填写本次实际到账金额；没有到账请明确填 0');f.elements.amount.focus();return;}
  f.elements.rounding.value=(Math.max(0,outstanding-cents('amount')-cents('discount'))/100).toFixed(2);
 }
 if(fill==='discount'){
  if(f.elements.amount.value===''){notify('请先填写本次实际到账金额；没有到账请明确填 0');f.elements.amount.focus();return;}
  f.elements.discount.value=(Math.max(0,outstanding-cents('amount')-cents('rounding'))/100).toFixed(2);
 }
 if(fill==='amount')f.elements.amount.value=(Math.max(0,outstanding-cents('rounding')-cents('discount'))/100).toFixed(2);
 const remaining=outstanding-cents('amount')-cents('rounding')-cents('discount');
 f.elements.rounding.setCustomValidity(remaining<0?'到账、折扣与抹零合计超过余额':'');
 $('#receipt-balance-preview').textContent=remaining<0?'到账、折扣与抹零合计超过未收余额，请调减后登记。':f.elements.amount.value===''?'请填写本次实际到账金额，或点击“填入余额”。':'登记后剩余未收：'+amount(remaining);
}
document.addEventListener('input',e=>{if(e.target.closest('#receipt-form'))updateReceiptPreview();});
async function statement(cid){const c=data.customers.find(c=>c.id===cid);if(!c)return;let orders,beanOrders=[];
 if(page==='ledger'){
  if(ledgerSource!=='sales')beanOrders=((await api('/api/byproduct-sales?customer_id='+encodeURIComponent(cid))).rows||[]).map(byproductOrderShape).filter(o=>ledgerOrderMatches(o));
  orders=[...receivableOrders(),...beanOrders].filter(o=>o.customer_id===cid).sort((a,b)=>a.business_date.localeCompare(b.business_date)||a.id.localeCompare(b.id));
 }else orders=data.orders.filter(o=>o.state==='reviewed'&&rangeDateMatches(o)).filter(o=>o.customer_id===cid);
 const rs=(page==='ledger'?receivableReceipts(orders,beanOrders):data.receipts.filter(r=>rangeMode?inDateRange(r.received_date):!selectedDate||r.received_date===selectedDate)).filter(r=>r.customer_id===cid);activeOrder=null;
 const openRc=(data.receipts||[]).filter(r=>!r.order_id&&r.kind==='opening'&&r.customer_id===cid);
 const rsAll=[...rs,...openRc].sort((a,b)=>(b.received_date||'').localeCompare(a.received_date||''));
 const openingPaid=(data.receipts||[]).filter(r=>!r.voided&&!r.order_id&&r.customer_id===cid&&(r.received_date||'')<=today()).reduce((n,r)=>n+(r.amount_cents||0)+(r.discount_cents||0)+(r.rounding_cents||0),0);
 const openingLeft=Math.max(0,(c.opening_cents||0)-openingPaid);
 openDialog('客户对账 · '+c.name,`<div class="callout">账单范围：${esc(rangeLabel())}，仅含已复核单据。${c.opening_cents?`期初应收 ${amount(c.opening_cents)}（${esc(c.opening_date||'日期未填')}）${openingPaid?`，已收 ${amount(openingPaid)}，未收 ${amount(openingLeft)}`:''}，账龄从期初日期起算；`:''}到账流水另按实际到账日期筛选。${openingLeft>0&&canAction('finance.receipt')?`<button class="text-button" data-act="opening-receipt" data-id="${esc(c.id)}">登记期初收款</button>`:''}</div><div class="detail-meta"><span>客户编号 <b>${esc(c.id)}</b></span><span>线路 <b>${esc(c.route)}</b></span></div><div class="table-wrap"><table><thead><tr><th>业务日期</th><th>账单</th><th>销售金额</th><th>退货已抵</th><th>已收</th><th>折扣 / 抹零</th><th>未收</th></tr></thead><tbody>${orders.map(o=>`<tr><td>${o.business_date}</td><td>${o.is_byproduct?`<button class="text-button" data-byproduct-statement data-cid="${esc(o.customer_id)}" data-month="${esc(o.business_date.slice(0,7))}">${esc(o.id)}</button>`:`<button class="text-button" data-act="detail" data-id="${esc(o.id)}">${esc(o.id)}</button>`}</td><td>${amount(o.total_cents)}</td><td>${amount(o.return_credit_cents||0)}</td><td>${amount(o.paid_cents)}</td><td>${amount(o.discount_cents||0)} / ${amount(o.rounding_cents||0)}</td><td class="amount">${amount(orderOutstanding(o))} ${orderOutstanding(o)>0?o.is_byproduct?(canAction('byproducts.receive')?`<button class="text-button" data-resource-act="receive" data-id="${esc(o.id)}">收款</button>`:''):(canAction('finance.receipt')?`<button class="text-button" data-act="receipt" data-id="${esc(o.id)}">收款</button>`:''):''}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">暂无已复核账单</td></tr>'}</tbody></table></div>${returnFinanceHistory(cid)}<h3 class="section-heading">到账流水</h3>${rsAll.map(r=>`<p class="help-text">${r.received_date} · ${esc(r.method)} · ${amount(r.amount_cents)} · 折扣 ${amount(r.discount_cents||0)} · 抹零 ${amount(r.rounding_cents||0)} · ${esc(r.note)} ${r.voided?'（已冲销）':''} ${!r.voided&&canAction('finance.receipt')&&(String(r.id||'').startsWith('RC-')||String(r.id||'').startsWith('OR-'))?`<button class="text-button" data-act="${String(r.id||'').startsWith('OR-')?'void-opening-receipt':'void-receipt'}" data-rid="${esc(r.id)}" data-oid="${esc(r.order_id||'')}">冲销</button>`:''}</p>`).join('')||'<p class="help-text">暂无收款记录</p>'}`,'CUSTOMER STATEMENT',`<button class="button" data-act="close">关闭</button>`);}
function ruleForm(){if(!needPermission('master.pricing.write'))return;openDialog('客户价格与扣皮规则',`<form id="rule-form"><div class="callout">仅作为新单据的默认规则。历史单据不随档案修改；已有草稿需在单据内核对单价及每批皮重。</div><div class="form-grid"><label class="field">客户<select name="customer_id">${salesCustomers().map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></label><label class="field">产品<select name="product_id">${data.products.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}（元/${billingUnit(p)}）</option>`).join('')}</select></label><label class="field">专属单价<input name="price" type="number" required min="0.001" step="0.001" value="3.60"></label><label class="field">单筐皮重（公斤，按包为0）<input name="tare" type="number" required min="0" step="0.001" value="1.8"></label></div></form>`,'CUSTOMER PRICING',`<button class="button" data-act="close">取消</button><button class="button primary" data-act="save-rule">保存规则</button>`);syncRuleForm();}
function syncRuleForm(){const f=$('#rule-form');if(!f)return;const r=ruleFor(f.elements.customer_id.value,f.elements.product_id.value);f.elements.price.value=r.price;f.elements.tare.value=r.tare;}
function guide(){openDialog('每日业务流程',`<ol class="help-text"><li>订货：按客户和产品录入需求，保存当天总表。</li><li>库存与发货分配：核对库存和生产，分配后确认实发。</li><li>配送：发货分配后先安排车辆与司机，再按趟打印客户 × 产品数量配送总表，每页最多 26 个客户；产品较多时续页打印。</li><li>称重：保存司机卸货及客户复称，确认交会计。</li><li>算票与复核：待算票提交出纳；退回单进入待重算；复核后计入应收。</li><li>收款：实际到账、退货抵扣、折扣和抹零分别核销。</li><li>原辅料：登记采购、领用、退回、盘点和库存预警。</li><li>成本与收入：按所属月归集费用，豆渣收入单列，月底核对后结账。</li></ol><p class="help-text">订货单、配送单和客户结算单用途独立。客户结算单按对账周期出具，不需要随每日配送逐户打印。已有到账的单据锁定，操作均校验版本并保留记录。</p>`,'OPERATING GUIDE · 业务说明','<button class="button primary" data-act="close">开始作业</button>');}

const formData=id=>Object.fromEntries(new FormData($(id)));
function validForm(id){return $(id).reportValidity();}
async function action(act,el){
 const id=el?.dataset.id;let form,body;
 switch(act){
 case 'edit-operator-user':editOperatorUser(id);break;
 case 'save-operator-user':await saveOperatorUser();break;
 case 'batch-statements':await openBatchStatements();break;
 case 'export-statement':await openCustomerStatement(id);break;
 case 'pending-settlements':openSettlementTodos();break;
 case 'new':sheetArchive=false;goto('orders');break;
 case 'edit':editOrder(id);break;
 case 'detail':detail(id);break;
 case 'settle':settle(id);break;
 case 'review':review(id);break;
 case 'receipt':receipt(id);break;
 case 'opening-receipt':openingReceiptDialog(id||'');break;
 case 'void-opening-receipt':voidOpeningReceipt(el.dataset.rid);break;
 case 'save-opening-receipt':await saveOpeningReceipt();break;
 case 'save-void-opening':await saveVoidOpening();break;
 case 'void-receipt':voidReceipt(target.dataset.rid,target.dataset.oid);break;
 case 'save-void-receipt':{const f=$('#void-receipt-form');if(!f||!f.reportValidity())break;const reason=f.elements.reason.value.trim();if(!reason){notify('请填写冲销原因');break;}const saved=voidTarget;await perform(()=>submit(`/api/orders/${saved.order_id}/void-receipt`,{receipt_id:saved.receipt_id,reason,version:saved.version},'收款已冲销，账单余额已恢复'));break;}
 case 'statement':await statement(id);break;
 case 'customer':customerForm(id);break;
 case 'rule':masterView='pricing';goto('masters');break;
 case 'close':closeDialog();break;
 case 'yesterday':clearDateRange();selectedDate=previousDay(today());render();break;
 case 'today':clearDateRange();selectedDate=today();render();break;
 case 'all-dates':clearDateRange();selectedDate='';render();break;
 case 'todo':page=el.dataset.state==='draft'?'orders':'settlements';filter=el.dataset.state;search='';render();break;
 case 'add-line':syncDraft();draft.lines.push(defaultLine(data.products[0].id,draft.customer_id));renderDraftLines();break;
 case 'remove-line':syncDraft();if(draft.lines.length===1){notify('至少保留一项产品');break;}draft.lines.splice(Number(el.dataset.index),1);renderDraftLines();break;
 case 'add-weight':syncDraft();{const l=draft.lines[Number(el.dataset.index)],r=ruleFor(draft.customer_id,l.product_id),source=el.dataset.source;const used=l[source].reduce((n,w)=>n+Number(w.count||0),0);l[source].push({gross:'',count:String(Math.max(1,Number(l.actual_qty)-used)),tare:r.tare,note:''});renderDraftLines();}break;
 case 'remove-weight':syncDraft();draft.lines[Number(el.dataset.index)][el.dataset.source].splice(Number(el.dataset.weightIndex),1);renderDraftLines();break;
 case 'save-order':if(!validForm('#order-form'))break;syncDraft();await perform(()=>submit(draft.id?`/api/orders/${draft.id}/order`:'/api/orders',draft,'单据已保存，原始订货与实发分别保留'));break;
 case 'negotiate':body=formData('#settle-form');await perform(()=>submit(`/api/orders/${activeOrder.id}/negotiate`,{version:activeOrder.version,reason:body.reason},'已标记待协商，尚未计入应收'));break;
 case 'configure-permissions':await openRolePermissions(el.dataset.role);break;
 case 'save-settle':body=formData('#settle-form');body.agreed=Object.fromEntries(Object.entries(body).filter(([k])=>k.startsWith('agreed-')).map(([k,v])=>[k.slice(7),v]));if(['auto','customer'].includes(body.mode))body.tare_overrides=Object.fromEntries((activeOrder.lines||[]).filter(l=>l.settlement_tares&&Object.keys(l.settlement_tares).length).map(l=>[l.product_id,l.settlement_tares]));body.version=activeOrder.version;await perform(()=>submit(`/api/orders/${activeOrder.id}/settle`,body,'账单已提交出纳复核'));break;
 case 'return-review':if(needPermission('finance.review-return'))openReturnReview();break;
 case 'save-return-review':if(!validForm('#return-review-form'))break;form=$('#return-review-form');body=formData('#return-review-form');await perform(()=>submit('/api/batch',{operations:reviewTargets(form).map(t=>({action:'return-review',order_id:t.id,body:{version:t.version,reason:body.reason}}))},'已退回会计重算，尚未计入应收'));break;
 case 'save-review-batch':if(!validForm('#review-client-form'))break;form=$('#review-client-form');body=formData('#review-client-form');await perform(()=>submit('/api/batch',{operations:reviewTargets(form).map(t=>({action:'review',order_id:t.id,body:{version:t.version,note:body.note,evidence_checked:form.elements.evidence_checked.checked}}))},'复核通过，已计入客户应收'));break;
 case 'save-review':if(!validForm('#review-form'))break;body=formData('#review-form');body.evidence_checked=$('#review-form').elements.evidence_checked.checked;body.version=activeOrder.version;await perform(()=>submit(`/api/orders/${activeOrder.id}/review`,body,'复核通过，已计入客户应收'));break;
 case 'remaining-discount':updateReceiptPreview('discount');break;
 case 'remaining-rounding':updateReceiptPreview('rounding');break;
 case 'fill-all-receivable':updateReceiptPreview('amount');break;
 case 'save-receipt':updateReceiptPreview();if(!validForm('#receipt-form'))break;body=formData('#receipt-form');body.version=activeOrder.version;await perform(()=>submit(`/api/orders/${activeOrder.id}/receipt`,body,'收款已登记，余额已更新'));break;
 case 'save-customer':if(!validForm('#customer-form'))break;body=customerFormPayload();if(dialogExpected)body.expected=dialogExpected;body.create=!body.existing;if(body.create)delete body.id;await perform(()=>submit('/api/master',{...body,kind:'customer'},r=>body.create?'客户已添加 · '+r.id:'客户档案已保存'));break;
 case 'save-rule':if(!validForm('#rule-form'))break;body=formData('#rule-form');const existingRule=data.rules.find(r=>r.customer_id===body.customer_id&&r.product_id===body.product_id);body.expected=existingRule?{price:existingRule.price,tare:existingRule.tare}:null;await perform(()=>submit('/api/master',{...body,kind:'rule'},'规则已保存，历史单据保持原快照'));break;
 case 'backup':if(!needPermission('system.backup'))break;try{const b=await api('/api/backup',{});notify('备份已保存：'+b.path);await refresh();}catch(e){err(e);}break;
 }
}
document.addEventListener('click',e=>{
 const target=e.target.closest('[data-act],[data-page],[data-filter]');if(!target)return;
 if(target.dataset.page){goto(target.dataset.page);return;}
 if(target.dataset.filter){filter=target.dataset.filter;render();return;}
 if(target.dataset.act){e.preventDefault();action(target.dataset.act,target).catch(err);}
});
document.addEventListener('change',e=>{
 if(e.target.id==='role'){if(authUser||busy)return;role=e.target.value;sessionStorage.setItem('erp-role',role);closeDialog();render();notify('已切换模拟岗位：'+role);}
 if(e.target.id==='business-date-filter'){clearDateRange();selectedDate=e.target.value;render();}
 if(e.target.id==='order-customer'){syncDraft();if(!draft.id){draft.lines.forEach(l=>l.price=ruleFor(draft.customer_id,l.product_id).price);renderDraftLines();notify('已应用该客户单价；已录入称重的皮重保留原值，请核对');}else{notify('客户已更换，请核对单价与扣皮；历史单据数值保持原样');}}
 if(e.target.dataset.product!==undefined){syncDraft();const i=Number(e.target.dataset.product);draft.lines[i]=defaultLine(e.target.value,draft.customer_id);renderDraftLines();}
 if(e.target.name==='mode'&&$('#agreed-fields'))$('#agreed-fields').hidden=e.target.value!=='agreed';
 if(e.target.closest('#rule-form')&&['customer_id','product_id'].includes(e.target.name))syncRuleForm();
});
document.addEventListener('input',e=>{
 if(e.target.id==='search'){search=e.target.value;$('#order-table').innerHTML=orderTable(filteredOrders());}
 if(e.target.closest('#draft-lines')){syncDraft();updateSummaries();}
});
document.addEventListener('submit',e=>{e.preventDefault();});
$('#dialog-close').addEventListener('click',closeDialog);$('#guide-button').addEventListener('click',guide);
$('#overlay').addEventListener('click',e=>{if(e.target.id==='overlay')closeDialog();});
document.addEventListener('keydown',e=>{if(isTextComposing(e))return;
 if($('#overlay').hidden)return;
 if(e.key==='Escape'){e.preventDefault();closeDialog();}
 if(e.key==='Tab'){const els=$$('button:not([disabled]),input:not([disabled]):not([type=hidden]),select,textarea,[tabindex="0"]',$('#dialog')).filter(x=>x.getClientRects().length);if(!els.length)return;const first=els[0],last=els.at(-1);if(e.shiftKey&&(document.activeElement===first||document.activeElement===$('#dialog'))){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}
});

function markScrollableTables(){
 document.querySelectorAll('.table-wrap').forEach(function(el){
  if(!el.querySelector('table'))return;
  el.classList.toggle('is-scrollable',el.scrollWidth>el.clientWidth+2);
 });
}
let scrollablePending=false;
function scheduleMarkScrollable(){
 if(scrollablePending)return;scrollablePending=true;
 requestAnimationFrame(function(){scrollablePending=false;markScrollableTables();});
}
document.addEventListener('DOMContentLoaded',function(){
 const root=document.getElementById('content');
 if(root&&typeof MutationObserver!=='undefined'){
  new MutationObserver(scheduleMarkScrollable).observe(root,{childList:true,subtree:true});
 }
 window.addEventListener('resize',scheduleMarkScrollable);
 const overlay=document.getElementById('overlay');
 if(overlay&&typeof MutationObserver!=='undefined')new MutationObserver(scheduleMarkScrollable).observe(overlay,{childList:true,subtree:true});
 scheduleMarkScrollable();
});

startAuthenticatedApp();
