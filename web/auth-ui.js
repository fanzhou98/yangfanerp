'use strict';
let authUser=null,authMode='accounts',managedUsers=[];
let authSession=null,authActivityPending=false,authActivitySending=false,authLastHeartbeat=0,authClockOffset=0;
const authNow=()=>Date.now()/1000+authClockOffset;
function authActivityKey(){return authSession?'erp-session-activity:'+authSession.session_id:'';}
function sharedAuthActivity(){let value=authSession?.last_activity||0;try{const stored=localStorage.getItem(authActivityKey());if(stored!==null)value=Number(stored);}catch{}return value;}
function setAuthSession(session){authSession=session;authActivityPending=false;authLastHeartbeat=0;if(!session)return;authClockOffset=session.server_time-Date.now()/1000;try{const previous=localStorage.getItem(authActivityKey());localStorage.setItem(authActivityKey(),String(Math.max(session.last_activity,Number(previous)||0)));}catch{}}
function sessionActive(){
 if(!authSession)return true;
 const now=authNow(),last=sharedAuthActivity();
 if(!last||now>=authSession.expires_at||now>=last+authSession.idle_timeout_seconds){expireAuthSession();return false;}return true;
}
function expireAuthSession(){
 if(!authSession)return;
 const key=authActivityKey();authSession=null;authActivityPending=false;try{localStorage.setItem(key,'0');}catch{}
 authUser=null;pageTrail.length=0;clearWorkingCopies();data=undefined;managedUsers=[];busy=false;
 if(typeof finishLeavePrompt==='function')finishLeavePrompt();
 $('#content').replaceChildren();$('#dialog-body').replaceChildren();$('#auth-actions').hidden=true;
 showAuthScreen(false,'登录已超时或失效，请重新登录。未保存的内容未提交，请登录后核对已保存记录。');
}
const AUTH_IDLE_WARNING=180;
function authIdleLeft(){if(!authSession)return null;const last=sharedAuthActivity();if(!last)return null;return Math.max(0,last+authSession.idle_timeout_seconds-authNow());}
function authIdleWarning(left=authIdleLeft()){
 if(left==null||left>AUTH_IDLE_WARNING)return null;
 return '登录将在 '+Math.max(1,Math.ceil(left/60))+' 分钟后超时，未保存的修改会丢失。';
}
function extendAuthSession(){
 if(!authSession||!sessionActive())return;
 const now=authNow();authSession.last_activity=now;authActivityPending=true;
 try{localStorage.setItem(authActivityKey(),String(now));}catch{}
 flushAuthActivity().catch(()=>{});renderAuthIdleWarning();
}
function renderAuthIdleWarning(){
 const message=authIdleWarning();const el=document.getElementById('auth-idle-warning');
 if(!message){el?.remove();return;}
 if(el){if(el.dataset.text!==message){el.dataset.text=message;el.innerHTML='<span>'+message+'</span><button type="button" class="button" data-auth-idle-extend>继续使用</button>';}return;}
 const box=document.createElement('div');box.id='auth-idle-warning';box.className='auth-idle-warning';box.innerHTML='<span>'+message+'</span><button type="button" class="button" data-auth-idle-extend>继续使用</button>';
 document.body.append(box);
}
document.addEventListener('click',e=>{if(e.target.closest('[data-auth-idle-extend]'))extendAuthSession();});
function noteAuthActivity(event){
 if(!event.isTrusted||!authSession||!sessionActive())return;
 const now=authNow();authSession.last_activity=now;authActivityPending=true;
 try{localStorage.setItem(authActivityKey(),String(now));}catch{}
 flushAuthActivity().catch(()=>{});
}
async function flushAuthActivity(){
 if(!authSession||!sessionActive()||!authActivityPending||authActivitySending||authNow()-authLastHeartbeat<15)return;
 const current=authSession;authActivitySending=true;authActivityPending=false;authLastHeartbeat=authNow();
 try{await authRequest('/api/auth/activity',{});}catch(e){if(authSession===current){if(e.status===401)expireAuthSession();else authActivityPending=true;}}finally{authActivitySending=false;}
}
for(const event of ['pointerdown','keydown','input','scroll'])document.addEventListener(event,noteAuthActivity,{capture:true,passive:true});
window.addEventListener('focus',()=>sessionActive());
document.addEventListener('visibilitychange',()=>{if(!document.hidden)sessionActive();});
window.addEventListener('storage',event=>{if(authSession&&event.key===authActivityKey())sessionActive();});
setInterval(()=>{if(authSession&&sessionActive()){flushAuthActivity().catch(()=>{});renderAuthIdleWarning();}},1000);
function csrfCookie(){return document.cookie.split('; ').find(s=>s.startsWith('erp_csrf='))?.slice(9)||'';}
async function authRequest(path,body){if(path!=='/api/auth/login'&&!sessionActive())throw Object.assign(Error('登录已超时，请重新登录'),{status:401});const r=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json','X-ERP-Client':'local-pilot','X-CSRF-Token':csrfCookie()}:{},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok){if(r.status===401&&path!=='/api/auth/login')expireAuthSession();throw Object.assign(Error(j.error||'请求未完成'),{status:r.status});}return j;}
function showAuthScreen(change=false,message=''){
 if(typeof stopCollaboration==='function')stopCollaboration();
 if(!change&&authSession){const key=authActivityKey();authSession=null;try{localStorage.setItem(key,'0');}catch{}}
 const screen=$('#auth-screen');$('.shell').hidden=true;screen.hidden=false;$('#overlay').hidden=true;document.body.classList.remove('modal-open');
 screen.innerHTML=`<div class="auth-layout"><section class="auth-story" aria-label="洋帆豆制品"><div class="auth-identity"><img class="auth-emblem" src="/favicon.svg?v=0.58.0" alt="洋帆标志"><span>洋帆豆制品<small>YANGFAN · ERP</small></span></div><div class="auth-story-copy"><span class="auth-eyebrow">专注豆制品 · 用心每一天</span><h1>用心做好豆制品，<br>让每一份品质<br>都值得信赖。</h1><p>从一粒好豆，到一份好产品。<br>把品质放在心上，把责任落在每一天。</p></div><div class="auth-story-footer"><span>生产有序</span><i></i><span>配送准时</span><i></i><span>经营有数</span></div><div class="auth-orbit" aria-hidden="true"><span></span><span></span><span></span></div></section><section class="auth-card"><div class="auth-card-heading"><span class="auth-eyebrow">洋帆豆制品 ERP 系统</span><h2>${change?'设置新密码':'欢迎登录'}</h2><p>${change?'初始或重置密码需修改后方可办理业务。':'登录您的工作账号，开始今天的工作。'}</p></div><form id="${change?'auth-password-form':'auth-login-form'}">${change?'':`<label class="field">账号<input name="username" required autocomplete="username" maxlength="32" autofocus></label>`}<label class="field">${change?'当前密码':'密码'}<input name="${change?'current_password':'password'}" type="password" required autocomplete="current-password" maxlength="128"></label>${change?'<label class="field">新密码<input name="new_password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"></label><label class="field">再次输入新密码<input name="confirm_password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"></label>':''}<p class="auth-error" role="alert">${esc(message)}</p><button class="button primary" type="submit">${change?'修改并重新登录':'登录系统'}</button>${change?'<button class="button" type="button" data-auth-logout>退出登录</button>':''}</form><div class="auth-help">账号由管理员统一开通<br>忘记密码请联系管理员重置</div><div class="auth-session-note">30 分钟无操作自动退出 · 登录有效期最长 8 小时</div></section></div>`;
}
async function startAuthenticatedApp(){
 try{const session=await authRequest('/api/auth/session');authMode=session.mode;
 if(!session.authenticated){return startPilotApp();}
 authUser=session.user;setAuthSession(session.session);if(authUser.must_change_password){showAuthScreen(true);return;}
 await enterAuthenticatedApp();
 }catch(e){if(e.status===401){authUser=null;showAuthScreen();}else showAuthScreen(false,e.message);}
}
function startPilotApp(){role=sessionStorage.getItem('erp-role')||'库管';if(!['库管','会计','出纳'].includes(role))role='库管';$('#role').value=role;return loadApp();}
async function loadApp(){if(role==='司机'){driverDay='';driverCache=null;} data=await api('/api/bootstrap');selectedDate=data.today;pageTrail.length=0;page='dashboard';if(data.auth_user&&!data.access_catalog.modules.some(m=>m.page===page&&moduleVisible(m))){const model=navigationModel(data.access_catalog),target=model.overview||model.sections.flatMap(s=>s.modules)[0];page=target?.page||'dashboard';if(target?.view)masterView=target.view;}if(role==='管理员')managedUsers=await api('/api/users');if(data.demo_context){selectedDate=data.demo_context.business_date;factoryDay=selectedDate;page='production-report';const notice=$('.notice');notice.classList.add('demo-notice');notice.hidden=false;notice.querySelector('span').textContent='演示';notice.querySelector('p').textContent='演示数据 · '+selectedDate+' · 考勤、领豆、用浆、发货和盘库均为示例，可自由查看。';$('#guide-button').hidden=true;$('.local-badge').textContent='演示数据';document.title='演示数据 · 生产日报';}$('#auth-screen').hidden=true;$('.shell').hidden=false;render(); }
async function enterAuthenticatedApp(){clearOperationFeedback();resetSaveStatus();lastReadTime='';clearWorkingCopies();role=authUser.role;$('#guide-button').textContent='操作说明 ↗';const picker=$('#role');picker.innerHTML=`<option>${esc(role)}</option>`;picker.value=role;picker.disabled=true;$('.notice').hidden=true;$('#auth-actions').hidden=false;await loadApp();if(typeof initCollaboration==='function')initCollaboration();}
async function refreshManagedUsers(){managedUsers=await api('/api/users');render();}
function renderUsers(){return head('用户管理','账号与岗位由管理员维护。老板为经营查看岗位，可查看经营和业务明细；业务岗位办理单据。',`<button class="button" data-page="system-settings">参数设置</button><button class="button" data-page="access">岗位权限配置</button><button class="button primary" data-user-new>新增用户</button>`,'SYSTEM · 账号管理')+`<section class="panel"><div class="table-wrap"><table><thead><tr><th>账号</th><th>姓名</th><th>岗位</th><th>状态</th><th>密码状态</th><th>操作</th></tr></thead><tbody>${managedUsers.map(u=>`<tr><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td><td>${esc(u.role)}</td><td>${u.active?'启用':'停用'}</td><td>${u.must_change_password?'需修改初始密码':'已设置'}</td><td><button class="text-button" data-user-edit="${esc(u.id)}">编辑</button>${u.id!==authUser.id?`<button class="text-button" data-user-reset="${esc(u.id)}">重置密码</button>`:''}</td></tr>`).join('')}</tbody></table></div></section><div class="callout">管理员拥有全部业务和系统权限；其他岗位按“岗位与权限”配置执行。同一岗位的授权适用于该岗位全部账号。</div>`;}
function editManagedUser(id,reset=false,driverId=''){const u=managedUsers.find(u=>u.id===id)||{id:'',username:'',display_name:'',role:'库管',active:true,version:0};if(driverId&&!id){u.role='司机';u.driver_id=driverId;u.display_name=(data.delivery_drivers||[]).find(d=>d.id===driverId)?.name||'';}openDialog(reset?'重置用户密码':id?'编辑用户':'新增用户',`<form id="managed-user-form" data-id="${esc(u.id)}" data-version="${u.version}" data-reset="${reset?'1':''}"><div class="form-grid">${reset?`<p class="wide">${esc(u.username)} · ${esc(u.display_name)}</p>`:`<label class="field">账号<input name="username" required pattern="[a-zA-Z0-9][a-zA-Z0-9_.-]{2,31}" maxlength="32" value="${esc(u.username)}" autocomplete="off"></label><label class="field">姓名<input name="display_name" required maxlength="80" value="${esc(u.display_name)}"></label><label class="field">岗位<select name="role">${['管理员','库管','会计','出纳','老板','厂长','物流负责人','行政负责人','司机'].map(r=>`<option ${r===u.role?'selected':''}>${r}</option>`).join('')}</select></label><label class="check-line"><input type="checkbox" name="active" ${u.active?'checked':''}>启用</label>`}${!reset?`<label class="field wide" id="managed-driver-link" ${u.role==='司机'?'':'hidden'}>关联司机档案<select name="driver_id"><option value="">自动按姓名创建或关联司机</option>${(data.delivery_drivers||[]).filter(d=>d.active||d.id===u.driver_id).map(d=>`<option value="${esc(d.id)}" ${d.id===u.driver_id?'selected':''}>${esc(d.name)}</option>`).join('')}</select><small>司机账号创建后会自动加入车辆司机档案；已有司机可直接关联。</small></label>`:''}${id?'<p class="callout warning wide">保存后，该用户现有登录会话将失效，需重新登录。</p>':''}${reset||!id?'<label class="field wide">临时密码<input name="password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"></label><p class="help-text wide">用户首次登录必须修改临时密码。请通过当面或可信方式交付。</p>':''}</div></form>`,'USER · 账号与岗位',`<button class="button" data-act="close">取消</button><button class="button primary" data-user-save>保存用户</button>`);}
async function saveManagedUser(){const f=$('#managed-user-form');if(!f.reportValidity())return;const body={...Object.fromEntries(new FormData(f)),active:f.elements.active?.checked??true,version:Number(f.dataset.version)},id=f.dataset.id;await perform(async()=>{await api('/api/users'+(id?'/'+id:'')+(f.dataset.reset==='1'?'/reset-password':''),body);busy=false;closeDialog();await refreshManagedUsers();if(body.role==='司机'&&f.dataset.reset!=='1'){dispatchTab='fleet';goto('dispatch');}notify(f.dataset.reset==='1'?'临时密码已重置，原登录会话已失效；用户首次登录需修改密码':id?'用户资料已保存，原登录会话已失效':'用户已新增，首次登录需修改临时密码');});}
async function signOut(){await requestPageTransition(async()=>{await authRequest('/api/auth/logout',{});clearWorkingCopies();authUser=null;data=undefined;managedUsers=[];showAuthScreen();});}
document.addEventListener('submit',async e=>{const f=e.target;if(!['auth-login-form','auth-password-form'].includes(f.id))return;e.preventDefault();const error=f.querySelector('.auth-error');const b=f.querySelector('[type=submit]');b.disabled=true;try{const values=Object.fromEntries(new FormData(f));if(f.id==='auth-login-form'){const result=await authRequest('/api/auth/login',values);authUser=result.user;setAuthSession(result.session);f.reset();if(authUser.must_change_password)showAuthScreen(true);else await enterAuthenticatedApp();}else{if(values.new_password!==values.confirm_password)throw Error('两次新密码不一致');await authRequest('/api/auth/password',values);f.reset();authUser=null;showAuthScreen(false,'密码已修改，请重新登录');}}catch(err){error.textContent=err.message;}finally{b.disabled=false;}});
document.addEventListener('click',e=>{if(e.target.closest('[data-user-refresh]'))refreshManagedUsers().catch(err);if(e.target.closest('[data-user-new]'))editManagedUser();const edit=e.target.closest('[data-user-edit]'),reset=e.target.closest('[data-user-reset]');if(edit)editManagedUser(edit.dataset.userEdit);if(reset)editManagedUser(reset.dataset.userReset,true);if(e.target.closest('[data-user-save]'))saveManagedUser().catch(err);if(e.target.closest('[data-auth-logout]')){if(!authUser||authUser.must_change_password){authRequest('/api/auth/logout',{}).then(()=>{authUser=null;showAuthScreen();}).catch(err);}else signOut().catch(err);}if(e.target.closest('[data-auth-password]'))requestPageTransition(()=>showAuthScreen(true));});

function renderAuthenticatedAccess(){const c=data.access_catalog;return `<div class="role-policy-cards">${['库管','会计','出纳','老板','厂长','物流负责人','行政负责人','司机'].map(r=>`<article><h3>${esc(r)}</h3><p>${esc(c.role_notes?.[r]||'')}</p></article>`).join('')}</div>`+head('岗位与权限','管理员拥有全部业务和系统权限，可配置其他岗位的查看和操作范围。')+renderRolePermissionEntry()+`<div class="erp-access-status"><div><small>当前身份</small><strong>${esc(authUser.display_name)} · ${esc(role)}</strong></div><div><small>授权方式</small><strong>管理员全权 + 可配置岗位</strong></div><div><small>操作留痕</small><strong>用户、时间、请求编号和变更内容</strong></div></div><section class="panel"><div class="panel-head"><h2>岗位权限矩阵</h2></div><div class="table-wrap"><table><thead><tr><th>操作</th>${c.roles.map(r=>`<th>${esc(r)}</th>`).join('')}</tr></thead><tbody>${c.actions.map(a=>`<tr><td>${esc(a.title)}</td>${c.roles.map(r=>`<td>${a.roles.includes(r)?'●':'—'}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>${renderOperatorUsers()}<div class="callout">管理员拥有全部权限；其他岗位可按查看与具体操作授权。同一工厂按岗位协作。地区、市场或客户级数据范围、审批式临时授权和多工厂隔离仍需后续建设。</div>`;}
function auditRollbackCell(a){if(authUser?.role!=='管理员'||a.action.startsWith('auth.'))return '';return `<td><button class="text-button danger" data-audit-rollback="${a.id}">回滚</button></td>`;}
async function rollbackAudit(auditId){const plan=await api('/api/audit-rollback-plan?id='+encodeURIComponent(auditId));const deps=plan.dependents||[],blockers=plan.blockers||[];openDialog('回滚操作 · '+plan.action,`<form id="audit-rollback-form" data-audit="${plan.audit_id}" data-fingerprint="${esc(plan.fingerprint)}"><div class="callout ${plan.mode==='restore'?'':'warning'}"><b>${esc(plan.entity)}</b> · ${esc(plan.table_label)}<br>${plan.mode==='restore'?`将恢复到操作前：${esc(plan.previous_summary||'原版本')}`:'将删除该操作新建的记录'}。当前：${esc(plan.target_summary)}</div>${plan.changed_since?`<p class="callout warning">该记录在此操作后还有 ${plan.changed_since} 条操作记录；回滚会覆盖之后的变化。</p>`:''}${deps.length?`<h3>同时处理 ${deps.length} 条依赖记录</h3><div class="table-wrap"><table><thead><tr><th>类型</th><th>记录</th><th>摘要</th><th>处理</th></tr></thead><tbody>${deps.slice(0,50).map(d=>`<tr><td>${esc(d.label)}</td><td>${esc(d.id)}</td><td>${esc(d.summary)}</td><td>${d.action==='strip'?'移除其中引用':'删除'}</td></tr>`).join('')}</tbody></table></div>${deps.length>50?'<p class="help-text">仅展示前 50 条，确认后会全部处理。</p>':''}`:''}${blockers.length?`<div class="callout warning"><b>暂时不能回滚：</b><br>${blockers.map(b=>esc(b)).join('<br>')}</div>`:''}<label class="field wide">回滚原因（必填）<textarea name="reason" required maxlength="500" rows="3" placeholder="说明为什么需要回滚这条操作"></textarea></label><p class="help-text">回滚会写一条新的审计记录，不能自动撤销。请先确认依赖记录的处理范围。</p></form>`,'AUDIT · 回滚操作',`<button class="button" data-act="close">取消</button><button class="button danger" data-audit-rollback-confirm ${blockers.length?'disabled':''}>确认回滚</button>`);}
async function confirmAuditRollback(){const f=$('#audit-rollback-form');if(!f||!f.reportValidity())return;const body={audit_id:Number(f.dataset.audit),reason:f.elements.reason.value,fingerprint:f.dataset.fingerprint};await perform(async()=>{const r=await api('/api/audit-rollback',body);busy=false;closeDialog();notify(r.mode==='delete'?`已回滚并删除 ${r.target_id}`:`已恢复到 ${r.target_id} 操作前`);await refresh();});}
document.addEventListener('click',e=>{const b=e.target.closest('[data-audit-rollback]');if(b)rollbackAudit(b.dataset.auditRollback).catch(err);if(e.target.closest('[data-audit-rollback-confirm]'))confirmAuditRollback().catch(err);});
function renderAuthenticatedAudit(){return auditHistoryPage();}
document.addEventListener('click',e=>{if(e.target.closest('[data-auth-backup]'))perform(async()=>{const b=await api('/api/backup',{});notify('备份已生成：'+b.path);await refresh();});});

let rolePermissionCatalog=null;
function renderRolePermissionEntry(){if(authUser?.role!=='管理员')return '';return `<section class="panel role-permissions-panel"><div class="panel-head"><div><h2>配置岗位权限</h2><p>按岗位统一设置功能查看和操作权限。管理员始终全部允许。</p></div></div><div class="head-actions">${['库管','会计','出纳','老板','厂长','物流负责人','行政负责人','司机'].map(r=>`<button class="button" data-act="configure-permissions" data-role="${r}">配置${r}权限</button>`).join('')}</div></section>`+renderFeaturePermissionGuide();}
function renderFeaturePermissionGuide(){const c=data.access_catalog,modules=c.modules,actions=c.actions;return `<section class="panel"><details class="report-disclosure"><summary>近期新增功能 · 权限对应与业务边界</summary><p class="help-text">页面可见、操作授权和敏感金额分别控制。下表是功能所用的权限，并非全部授权给当前岗位；各项操作仍分别检查权限、单据状态和版本。</p>${resourceTable(['功能','查看入口','具体操作权限','边界与联动'],(c.feature_permissions||[]).map(f=>`<tr><th>${esc(f.feature)}</th><td>${f.read.map(k=>esc(modules.find(m=>m.id===k)?.title||k)).join('、')}</td><td>${f.write.map(k=>esc(actions.find(a=>a.id===k)?.title||k)).join('；')||'只读'}</td><td class="long-note">${esc(f.note)}</td></tr>`).join(''))}</details></section>`;}
function permissionActionLinks(){return Object.entries(rolePermissionCatalog?.action_dependencies||{'inventory.dispatch':['inventory.stock'],'finance.settle':['orders.write'],'crates.confirm':['crates.write']}).flatMap(([key,values])=>values.map(v=>[key,v]));}
async function openRolePermissions(targetRole){if(authUser?.role!=='管理员')return;rolePermissionCatalog=await api('/api/role-permissions');const current=rolePermissionCatalog.roles.find(r=>r.role===targetRole);openDialog(targetRole+' · 使用权限',`<form id="role-permissions-form" data-role="${esc(targetRole)}" data-version="${current.version}"><div class="permission-role-summary">${esc(rolePermissionCatalog.role_notes?.[targetRole]||'按岗位职责配置查看和操作。')}</div><p class="help-text">修改适用于全部${esc(targetRole)}账号。保存后须重新登录；管理员始终保留全部权限。</p><h3>敏感信息查看范围</h3><div class="permission-data-scopes">${(rolePermissionCatalog.data_scopes||[]).map(scope=>`<label><input type="checkbox" data-permission-scope="${scope.id}" ${(current.data_scopes||[]).includes(scope.id)?'checked':''}><span><b>${esc(scope.title)}</b><small>${esc(scope.description)}</small></span></label>`).join('')}</div><h3>功能查看与具体操作</h3><div class="permission-quick-actions"><button type="button" class="button" data-permission-all="1">全部授权</button><button type="button" class="button" data-permission-all="0">全部取消</button></div>${(rolePermissionCatalog.groups||data.access_catalog.groups).map(g=>{const modules=rolePermissionCatalog.modules.filter(m=>m.group===g.id&&!['system.users','system.access','system.parameters'].includes(m.id));return modules.length?`<h3 class="permission-group-heading">${esc(g.title)}</h3>${modules.map(m=>`<section class="permission-module"><label class="permission-module-title"><input type="checkbox" data-permission-module="${esc(m.id)}" ${current.modules.includes(m.id)?'checked':''}>查看 · ${esc(m.title)}</label><div class="permission-module-actions">${rolePermissionCatalog.actions.filter(a=>targetRole!=='老板'&&a.module===m.id&&(!a.assignable_roles||a.assignable_roles.includes(targetRole))&&!['system.users','system.permissions','system.parameters'].includes(a.id)).map(a=>`<label><input type="checkbox" data-permission-action="${esc(a.id)}" ${current.actions.includes(a.id)?'checked':''}>${esc(a.title)}</label>`).join('')||'<small>此功能仅设置查看权限</small>'}</div></section>`).join('')}`:'';}).join('')}<p class="callout warning">保存后，${esc(targetRole)}岗位现有登录会话将失效，相关用户需重新登录。同一岗位全部账号受此设置影响。</p><p class="help-text">金额查看与功能菜单分别控制；勾选业务操作会自动勾选必需的查看范围。系统账号及授权管理仍属于管理员。</p></form>`,'ACCESS · 岗位授权',`<button class="button" data-act="close">取消</button><button class="button primary" data-role-permissions-save>保存权限</button>`);}
const permissionScopeActions={'sales-prices':['finance.price-edit','finance.settle','finance.review','finance.receipt','master.pricing.write','master.products.write','master.write','finance.statement-issue','returns.account','returns.review','returns.refund'],'purchase-prices':['purchases.write','purchases.cost','purchases.pay'],'material-costs':['materials.value','costs.close'],'supplier-terms':['suppliers.write']};
function permissionDependencies(action){const m=rolePermissionCatalog.actions.find(a=>a.id===action)?.module;let result=action==='master.write'?['master.customers','master.products','master.pricing']:[m];if(['returns.account','returns.retract','returns.review','returns.refund'].includes(action))result.push('finance.receivables');return result;}
function syncPermissionDependencies(){const form=$('#role-permissions-form');for(const [scope,actions] of Object.entries(permissionScopeActions))if(actions.some(a=>$(`[data-permission-action="${a}"]`,form)?.checked))$(`[data-permission-scope="${scope}"]`,form).checked=true;if($('[data-permission-module="workspace.analytics"]',form)?.checked)for(const input of $$('[data-permission-scope]',form))input.checked=true;for(const [key,dependent] of permissionActionLinks())if($(`[data-permission-action="${key}"]`,form)?.checked){const input=$(`[data-permission-action="${dependent}"]`,form);if(input)input.checked=true;}for(const input of $$('[data-permission-action]:checked',form))for(const m of permissionDependencies(input.dataset.permissionAction)){const module=$(`[data-permission-module="${m}"]`,form);if(module)module.checked=true;}}
async function saveRolePermissions(){const f=$('#role-permissions-form');syncPermissionDependencies();const body={role:f.dataset.role,version:Number(f.dataset.version),data_scopes:$$('[data-permission-scope]:checked',f).map(el=>el.dataset.permissionScope),modules:$$('[data-permission-module]:checked',f).map(el=>el.dataset.permissionModule),actions:$$('[data-permission-action]:checked',f).map(el=>el.dataset.permissionAction)};await perform(async()=>{const result=await api('/api/role-permissions',body);busy=false;closeDialog();await refresh();notify(`${result.role}权限已保存，${result.revoked_sessions} 个已有会话已失效`);});}
document.addEventListener('change',e=>{const f=$('#role-permissions-form');if(!f)return;if(e.target.matches('[data-permission-scope]')&&!e.target.checked){for(const key of permissionScopeActions[e.target.dataset.permissionScope]||[]) {const input=$(`[data-permission-action="${key}"]`,f);if(input)input.checked=false;}const analytics=$('[data-permission-module="workspace.analytics"]',f);if(analytics)analytics.checked=false;}if(e.target.matches('[data-permission-action]')&&e.target.checked)syncPermissionDependencies();if(e.target.matches('[data-permission-action]')&&!e.target.checked){for(const [key,dependent] of permissionActionLinks())if(e.target.dataset.permissionAction===dependent){const control=$(`[data-permission-action="${key}"]`,f);if(control)control.checked=false};}if(e.target.matches('[data-permission-module]')&&e.target.checked&&e.target.dataset.permissionModule==='workspace.analytics')for(const input of $$('[data-permission-scope]',f))input.checked=true;if(e.target.matches('[data-permission-module]')&&!e.target.checked){const key=e.target.dataset.permissionModule;for(const input of $$('[data-permission-action]',f))if(permissionDependencies(input.dataset.permissionAction).includes(key))input.checked=false;for(const [action,dependent] of permissionActionLinks())if(!$(`[data-permission-action="${dependent}"]`,f)?.checked){const control=$(`[data-permission-action="${action}"]`,f);if(control)control.checked=false};}});
document.addEventListener('click',e=>{if(e.target.closest('[data-role-permissions-save]'))saveRolePermissions().catch(err);const all=e.target.closest('[data-permission-all]');if(all)$$('#role-permissions-form input[type=checkbox]').forEach(el=>el.checked=all.dataset.permissionAll==='1');});

document.addEventListener('change',e=>{if(e.target.closest('#managed-user-form')&&e.target.name==='role')$('#managed-driver-link').hidden=e.target.value!=='司机';});

document.addEventListener('click',e=>{const b=e.target.closest('[data-driver-account]');if(!b||authUser?.role!=='管理员')return;const user=managedUsers.find(u=>u.role==='司机'&&u.driver_id===b.dataset.driverAccount);editManagedUser(user?.id||'',false,b.dataset.driverAccount);});

let auditTab='business';
let auditFilters={start:'',end:'',all:false,role:'',search:''};
let auditPageNo=1,auditSecurityPageNo=1;
let auditBusinessState={key:'',loading:false,error:'',data:null};
let auditSecurityState={key:'',loading:false,error:'',data:null};

function auditHistoryPage(){
 if(!auditFilters.start){auditFilters.start=today().slice(0,8)+'01';auditFilters.end=today();}
 auditEnsure(auditTab);
 const roles=(data.access_catalog?.roles||[]).filter(Boolean);
 return head('审计与数据维护','按日期、岗位和关键字查询完整操作记录与安全事件；历史模拟记录没有实名身份，不补造姓名。',`<button class="button" data-auth-backup>备份数据库</button>`)+
  businessResetPanel()+
  (canAction('system.archive')?trialArchivePanel()+archivedOrderPanel():'')+
  `<section class="panel audit-history"><div class="panel-head"><div><h2>操作与安全历史</h2><p>业务操作保留经办人、岗位、对象和请求编号；安全事件记录登录失败、限速、改密及账号变更。回滚仍按单条操作办理。</p></div><div class="audit-tabs"><button class="button ${auditTab==='business'?'primary':''}" data-audit-tab="business">业务操作</button><button class="button ${auditTab==='security'?'primary':''}" data-audit-tab="security">安全事件</button></div></div>
  <div class="sheet-filters"><label>开始日期<input id="audit-start" type="date" value="${esc(auditFilters.start)}" ${auditFilters.all?'disabled':''}></label><label>结束日期<input id="audit-end" type="date" value="${esc(auditFilters.end)}" ${auditFilters.all?'disabled':''}></label>${auditTab==='business'?`<label>岗位<select id="audit-role"><option value="">全部岗位</option>${roles.map(r=>`<option value="${esc(r)}" ${auditFilters.role===r?'selected':''}>${esc(r)}</option>`).join('')}</select></label>`:''}<label class="wide">查找<input id="audit-search" value="${esc(auditFilters.search)}" maxlength="100" placeholder="操作、对象或经办人"></label><button class="button primary" data-audit-apply>查询</button><button class="button" data-audit-all>${auditFilters.all?'按本月':'全部日期'}</button></div>
  ${auditBodyHTML()}</section>
  <div class="callout">业务审计保留实际操作人；安全事件包含登录失败、限速、改密、账号及岗位变更。数据库管理员仍可改动本机文件，审计暂未异地防篡改存储。</div>`;
}

function auditUrl(kind){
 const params=new URLSearchParams({page:String(kind==='business'?auditPageNo:auditSecurityPageNo),page_size:'50'});
 if(auditFilters.all)params.set('all','1');else{params.set('start',auditFilters.start);params.set('end',auditFilters.end);}
 if(auditFilters.search)params.set('search',auditFilters.search);
 if(kind==='business'&&auditFilters.role)params.set('role',auditFilters.role);
 return (kind==='business'?'/api/audit?':'/api/security-events?')+params.toString();
}

function auditEnsure(kind){
 const state=kind==='business'?auditBusinessState:auditSecurityState,url=auditUrl(kind);
 if(state.key===url&&(state.data||state.loading))return;
 state.key=url;state.loading=true;state.error='';
 api(url).then(result=>{state.data=result;if(kind==='business')auditPageNo=result.page;else auditSecurityPageNo=result.page;}).catch(err=>{state.error=err.message||'读取失败';}).finally(()=>{state.loading=false;if(page==='logs')render();});
}

function auditBodyHTML(){
 const kind=auditTab,state=kind==='business'?auditBusinessState:auditSecurityState,d=state.data;
 if(state.error)return `<div class="callout warning"><b>读取失败</b><p>${esc(state.error)}</p><button class="button" data-audit-apply>重新查询</button></div>`;
 if(!d)return `<div class="empty-state">正在读取${kind==='business'?'业务操作':'安全事件'}记录…</div>`;
 if(!d.total)return `<div class="empty-state">当前条件下没有记录。可扩大日期范围或清空关键字后重试。</div>`;
 const latest=kind==='business'?d.summary?.latest:auditTime(d.summary?.latest);
 const table=kind==='business'
  ?`<div class="table-wrap"><table><thead><tr><th>时间</th><th>经办用户</th><th>岗位</th><th>操作</th><th>对象</th><th>请求编号</th>${authUser?.role==='管理员'?'<th>操作</th>':''}</tr></thead><tbody>${d.rows.map(a=>`<tr><td>${esc((a.at||'').replace('T',' '))}</td><td>${esc(a.actor_name||'历史模拟记录')}</td><td>${esc(a.role||'—')}</td><td>${esc(a.action)}</td><td>${esc(a.entity)}</td><td>${esc(a.request_id||'—')}</td>${auditRollbackCell(a)}</tr>`).join('')}</tbody></table></div>`
  :`<div class="table-wrap"><table><thead><tr><th>时间</th><th>事件</th><th>用户编号</th><th>对象</th></tr></thead><tbody>${d.rows.map(e=>`<tr><td>${esc(auditTime(e.at))}</td><td>${esc(e.action)}</td><td>${esc(e.actor_id||'匿名请求')}</td><td>${esc(e.entity)}</td></tr>`).join('')}</tbody></table></div>`;
 return `<div class="audit-summary"><span>共 <b>${d.total}</b> 条</span><span>经办 <b>${d.summary?.actors||0}</b> 人</span><span>最近 ${esc(latest||'—')}</span><span>${d.range?.all_dates?'全部日期':esc((d.range?.start||'')+' 至 '+(d.range?.end||''))}</span></div>${table}${auditPagerHTML(kind,d)}`;
}

function auditPagerHTML(kind,d){
 const current=kind==='business'?auditPageNo:auditSecurityPageNo;
 return `<div class="audit-pager"><button class="button" data-audit-page-kind="${kind}" data-audit-page="${d.page-1}" ${d.page<=1?'disabled':''}>上一页</button><span>第 ${d.page} / ${d.pages} 页 · 每页 ${d.page_size} 条</span><button class="button" data-audit-page-kind="${kind}" data-audit-page="${d.page+1}" ${d.page>=d.pages?'disabled':''}>下一页</button></div>`;
}

function auditTime(value){if(!value)return '—';const n=Number(value);return Number.isFinite(n)&&n>1000000000?new Date(n*1000).toLocaleString('zh-CN',{hour12:false}):String(value);}

function auditApply(){
 auditFilters.start=$('#audit-start')?.value||auditFilters.start;
 auditFilters.end=$('#audit-end')?.value||auditFilters.end;
 if($('#audit-role'))auditFilters.role=$('#audit-role').value;
 auditFilters.search=$('#audit-search')?.value.trim()||'';
 auditPageNo=1;auditSecurityPageNo=1;
 auditBusinessState.key='';auditSecurityState.key='';
 render();
}

document.addEventListener('click',e=>{
 const tab=e.target.closest('[data-audit-tab]');if(tab){auditTab=tab.dataset.auditTab;render();return;}
 if(e.target.closest('[data-audit-apply]')){auditApply();return;}
 if(e.target.closest('[data-audit-all]')){auditFilters.all=!auditFilters.all;if(!auditFilters.all&&(!auditFilters.start||!auditFilters.end)){auditFilters.start=today().slice(0,8)+'01';auditFilters.end=today();}auditPageNo=1;auditSecurityPageNo=1;auditBusinessState.key='';auditSecurityState.key='';render();return;}
 const go=e.target.closest('[data-audit-page]');if(go){const kind=go.dataset.auditPageKind,next=Number(go.dataset.auditPage);if(!Number.isInteger(next)||next<1)return;if(kind==='business')auditPageNo=next;else auditSecurityPageNo=next;render();}
});
