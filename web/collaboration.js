'use strict';
// Notification inbox and administrator feedback.
let notificationData=null,notificationTimer=null,notificationInitialized=false,notificationSeen=new Set();
let feedbackData=null,feedbackLoaded=false,feedbackLoading=false,feedbackError='',feedbackFilter='all',feedbackSearch='',feedbackStart='',feedbackEnd='',feedbackAll=false,feedbackPageNo=1;

function collaborationTime(value){if(!value)return '';const text=String(value).replace('T',' ');return text.length>=16?text.slice(5,16):text;}
function collaborationNavCount(pageName){
 if(pageName==='feedback'){const n=feedbackData?.counts?.feedback_open??notificationData?.counts?.feedback_open??0;return `<span class="nav-count" data-nav-count="feedback" ${n?'':'hidden'}>${n>99?'99+':n}</span>`;}
 return '';
}
function collaborationNavigationCount(pageName){
 if(pageName==='feedback'&&data?.auth_user?.role!=='管理员')return '';
 return collaborationNavCount(pageName);
}
function updateCollaborationBadges(){
 const feedbackCount=feedbackData?.counts?.feedback_open??notificationData?.counts?.feedback_open??0;
 const el=$('[data-nav-count="feedback"]');if(el){el.textContent=feedbackCount>99?'99+':String(feedbackCount);el.hidden=!feedbackCount;}
 const badge=$('#notification-count');if(badge){const value=notificationData?.unread_count||0;badge.textContent=value>99?'99+':String(value);badge.hidden=!value;}
}

function initCollaboration(){
 if(!data?.auth_user)return;
 stopCollaboration();
 notificationData=null;notificationInitialized=false;notificationSeen=new Set();
 feedbackData=null;feedbackLoaded=false;feedbackLoading=false;feedbackError='';feedbackFilter='all';feedbackSearch='';feedbackStart='';feedbackEnd='';feedbackAll=false;feedbackPageNo=1;
 loadNotifications(true).catch(()=>{});
 notificationTimer=setInterval(()=>{if(data?.auth_user)loadNotifications(false).catch(()=>{});},25000);
}
function stopCollaboration(){
 if(notificationTimer){clearInterval(notificationTimer);notificationTimer=null;}
 const panel=$('#notification-panel');if(panel)panel.hidden=true;
 const button=$('#notification-button');if(button)button.setAttribute('aria-expanded','false');
}
async function loadNotifications(initial=false,{silent=false}={}){
 if(!data?.auth_user)return;
 const result=await api('/api/notifications');
 notificationData=result;
 const fresh=result.items.filter(item=>!item.read&&!notificationSeen.has(item.id));
 for(const item of result.items)notificationSeen.add(item.id);
 if(!notificationInitialized){notificationInitialized=true;}
 else if(fresh.length){if(!silent)notify('新通知：'+fresh[0].title);}
 updateCollaborationBadges();
 const panel=$('#notification-panel');if(panel&&!panel.hidden)renderNotificationPanel();
}
function renderNotificationPanel(){
 const panel=$('#notification-panel');if(!panel)return;
 const items=notificationData?.items||[];
 panel.innerHTML=`<div class="notification-head"><div><b>消息通知</b><small>${notificationData?.unread_count?notificationData.unread_count+' 条未读':'全部已读'}</small></div><button class="text-button" data-notification-read-all ${notificationData?.unread_count?'':'disabled'}>全部已读</button></div><div class="notification-list">${items.slice(0,30).map(item=>`<button type="button" class="notification-item ${item.read?'read':''}" data-notification-item="${esc(item.id)}" data-notification-page="${esc(item.page||'')}"><span class="notification-kind ${esc(item.kind)}">反</span><span class="notification-copy"><b>${esc(item.title||'通知')}</b><p>${esc(item.body||'')}</p><small>${esc(collaborationTime(item.created_at))}${item.actor_name?' · '+esc(item.actor_name):''}</small></span></button>`).join('')||'<p class="empty">暂无通知</p>'}</div><div class="notification-foot"><button class="text-button" data-page="feedback">问题反馈 ↗</button></div>`;
}
function toggleNotificationPanel(){
 const panel=$('#notification-panel'),button=$('#notification-button');if(!panel)return;
 const open=panel.hidden;panel.hidden=!open;button?.setAttribute('aria-expanded',String(open));
 if(open){renderNotificationPanel();loadNotifications(false,{silent:true}).catch(()=>{});}
}
async function openNotification(button){
 const id=button.dataset.notificationItem,target=button.dataset.notificationPage;
 button.classList.add('read');
 if(notificationData){const item=notificationData.items.find(value=>value.id===id);if(item&&!item.read){item.read=true;notificationData.unread_count=Math.max(0,(notificationData.unread_count||0)-1);}}
 updateCollaborationBadges();
 try{await api('/api/notifications/read',{ids:[id]});}catch{}
 const panel=$('#notification-panel');if(panel){panel.hidden=true;$('#notification-button')?.setAttribute('aria-expanded','false');}
 if(target&&typeof goto==='function')goto(target);
}
async function markAllNotificationsRead(){
 try{const result=await api('/api/notifications/read',{all:true});if(notificationData){notificationData.items.forEach(item=>item.read=true);notificationData.unread_count=result.unread_count||0;}updateCollaborationBadges();renderNotificationPanel();notify('通知已全部标记为已读');}catch(error){notify(error.message);}
}

function feedbackStatusBadge(status){const row={open:['orange','待处理'],replied:['blue','已回复'],closed:['green','已关闭']}[status]||['','状态'];return `<span class="badge ${row[0]}">${row[1]}</span>`;}
async function loadFeedback(){
 if(feedbackLoading)return;feedbackLoading=true;feedbackError='';
 if(!feedbackAll&&!feedbackStart){const d=today();feedbackStart=d.slice(0,8)+'01';feedbackEnd=d;}
 const query=new URLSearchParams({page:String(feedbackPageNo),page_size:'20'});
 if(feedbackAll)query.set('all','1');else{query.set('start',feedbackStart);query.set('end',feedbackEnd);}
 if(feedbackFilter!=='all')query.set('status',feedbackFilter);
 if(feedbackSearch.trim())query.set('search',feedbackSearch.trim());
 try{feedbackData=await api('/api/feedback?'+query.toString());feedbackPageNo=feedbackData.page||1;feedbackLoaded=true;updateCollaborationBadges();}
 catch(error){feedbackError=error.message;feedbackLoaded=true;}
 finally{feedbackLoading=false;if(page==='feedback')render();}
}
function feedbackBody(value){return esc(value).replace(/\n/g,'<br>');}
function feedbackPage(){
 if(!feedbackLoaded){if(!feedbackLoading)loadFeedback().catch(()=>{});return head('问题反馈','把使用中的问题、改进建议提交给管理员，并在这里跟踪回复。','','COLLABORATION · 管理员反馈')+readState('问题反馈',feedbackError);}
 const canManage=!!feedbackData?.can_manage,categories=feedbackData?.categories||['功能异常','使用问题','改进建议','其他'];
 const tickets=feedbackData?.tickets||[];
 const filters=[['all','全部'],['open','待处理'],['replied','已回复'],['closed','已关闭']];
 const counts=feedbackData?.summary||{},pages=feedbackData?.pages||1;
 const form=`<section class="panel feedback-form-panel"><div class="panel-head"><div><h2>提交反馈</h2><p>描述越具体越容易处理；可附上发生时间、模块和看到的现象。</p></div></div><form id="feedback-form"><div class="form-grid"><label class="field">问题类型<select name="category">${categories.map(category=>`<option>${esc(category)}</option>`).join('')}</select></label><label class="field wide">标题<input name="title" required maxlength="120" placeholder="例如：上豆登记保存后看不到记录"></label><label class="field wide">详细描述<textarea name="body" required rows="5" maxlength="4000" placeholder="请说明操作步骤、发生时间和期望结果"></textarea></label></div><div class="feedback-form-actions"><span>提交后会通知管理员，回复后本页和消息通知会提醒您。</span><button type="button" class="button primary" data-feedback-submit>提交反馈</button></div></form></section>`;
 const list=`<section class="panel feedback-list-panel"><div class="panel-head"><div><h2>${canManage?'全部反馈':'我的反馈'}</h2><p>${canManage?'按更新时间排列，可回复并更新处理状态。':'共 '+(feedbackData?.total||0)+' 条，管理员回复后可继续补充说明。'}</p></div><div class="workflow-tabs feedback-filters">${filters.map(([key,label])=>`<button type="button" class="${feedbackFilter===key?'active':''}" data-feedback-filter="${key}">${label}${counts[key]!=null?' '+counts[key]:''}</button>`).join('')}</div></div><div class="sheet-filters"><label>开始日期<input id="feedback-start" type="date" value="${esc(feedbackStart)}"></label><label>结束日期<input id="feedback-end" type="date" value="${esc(feedbackEnd)}"></label><label>查找<input id="feedback-search" value="${esc(feedbackSearch)}" placeholder="标题、描述或提交人"></label><button type="button" class="button primary" data-feedback-apply>查询</button><button type="button" class="button" data-feedback-all>全部日期</button></div><div class="audit-summary">共 ${feedbackData?.total||0} 条${feedbackAll?'（全部日期）':`（${esc(feedbackData?.range?.start||'')} 至 ${esc(feedbackData?.range?.end||'')}）`}</div>${tickets.map(ticket=>`<article class="feedback-ticket status-${esc(ticket.status)}"><header><div><span class="feedback-category">${esc(ticket.category)}</span><b>${esc(ticket.title)}</b><small>${esc(ticket.user_name)} · ${esc(ticket.user_role)} · ${esc(collaborationTime(ticket.created_at))}${ticket.updated_at?` · 更新 ${esc(collaborationTime(ticket.updated_at))}`:''}</small></div>${feedbackStatusBadge(ticket.status)}</header><p class="feedback-body">${feedbackBody(ticket.body)}</p>${(ticket.replies||[]).length?`<div class="feedback-replies">${ticket.replies.map(reply=>`<div class="feedback-reply ${reply.role==='管理员'?'admin':''}"><div><b>${esc(reply.user_name)}</b><span>${esc(reply.role)} · ${esc(collaborationTime(reply.at))}</span></div><p>${feedbackBody(reply.body)}</p></div>`).join('')}</div>`:''}<form class="feedback-reply-form" data-feedback-reply-form="${esc(ticket.id)}" data-version="${ticket.version}"><textarea name="body" rows="2" maxlength="2000" placeholder="${canManage?'回复反馈人，可只更新状态':'补充说明；提交后会重新进入待处理'}"></textarea><div class="feedback-reply-actions">${canManage?`<select name="status"><option value="open" ${ticket.status==='open'?'selected':''}>待处理</option><option value="replied" ${ticket.status==='replied'?'selected':''}>已回复</option><option value="closed" ${ticket.status==='closed'?'selected':''}>已关闭</option></select>`:''}<button type="button" class="button ${canManage?'primary':''}" data-feedback-reply="${esc(ticket.id)}">${canManage?'回复 / 更新状态':'补充说明'}</button></div></form></article>`).join('')||'<div class="empty">当前筛选下暂无反馈。可切换“全部”或点上方“提交反馈”。</div>'}${pages>1?`<div class="audit-pager"><button type="button" class="button" data-feedback-page="${feedbackData.page-1}" ${feedbackData.page<=1?'disabled':''}>上一页</button><span>第 ${feedbackData.page} / ${pages} 页</span><button type="button" class="button" data-feedback-page="${feedbackData.page+1}" ${feedbackData.page>=pages?'disabled':''}>下一页</button></div>`:''}</section>`;
 return head('问题反馈','把使用中的问题、改进建议提交给管理员，并在这里跟踪回复。')+form+list;
}
async function submitFeedback(){
 const form=$('#feedback-form');if(!form||!form.reportValidity())return;
 const button=$('[data-feedback-submit]',form);if(button)button.disabled=true;
 try{const result=await api('/api/feedback',{category:form.elements.category?.value||'其他',title:form.elements.title.value,body:form.elements.body.value,request_key:erpRequestKey()});form.reset();await loadFeedback();loadNotifications(false,{silent:true}).catch(()=>{});notify('已提交，编号 '+(result.id||'')+'；管理员回复后会通知您');}
 catch(error){notify(error.message);}finally{if(button?.isConnected)button.disabled=false;}
}
async function replyFeedback(id){
 const form=$(`[data-feedback-reply-form="${CSS.escape(id)}"]`);if(!form)return;
 const message=form.elements.body.value.trim(),status=form.elements.status?.value;
 if(!message&&!(feedbackData?.can_manage&&status)){notify('请填写回复内容');return;}
 const button=$('[data-feedback-reply]',form);if(button)button.disabled=true;
 try{await api('/api/feedback/reply',{id,version:Number(form.dataset.version),body:message,status,request_key:erpRequestKey()});await loadFeedback();loadNotifications(false,{silent:true}).catch(()=>{});notify('反馈已更新');}
 catch(error){notify(error.message);}finally{if(button?.isConnected)button.disabled=false;}
}

document.addEventListener('click',event=>{
 if(event.target.closest('#notification-button')){toggleNotificationPanel();return;}
 if(event.target.closest('[data-notification-read-all]')){markAllNotificationsRead().catch(error=>notify(error.message));return;}
 const notification=event.target.closest('[data-notification-item]');if(notification){openNotification(notification).catch(()=>{});return;}
 if(event.target.closest('[data-feedback-submit]')){submitFeedback().catch(error=>notify(error.message));return;}
 const reply=event.target.closest('[data-feedback-reply]');if(reply){replyFeedback(reply.dataset.feedbackReply).catch(error=>notify(error.message));return;}
 const filter=event.target.closest('[data-feedback-filter]');if(filter){feedbackFilter=filter.dataset.feedbackFilter;feedbackPageNo=1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 if(event.target.closest('[data-feedback-apply]')){feedbackStart=$('#feedback-start')?.value||'';feedbackEnd=$('#feedback-end')?.value||'';feedbackSearch=$('#feedback-search')?.value||'';feedbackAll=false;feedbackPageNo=1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 if(event.target.closest('[data-feedback-all]')){feedbackAll=true;feedbackPageNo=1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 const fp=event.target.closest('[data-feedback-page]');if(fp){feedbackPageNo=Number(fp.dataset.feedbackPage)||1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 if(!event.target.closest('#notification-panel')){const panel=$('#notification-panel');if(panel&&!panel.hidden){panel.hidden=true;$('#notification-button')?.setAttribute('aria-expanded','false');}}
});
document.addEventListener('keydown',event=>{
 if(isTextComposing(event))return;
 if(event.key==='Escape'&&!$('#notification-panel')?.hidden){$('#notification-panel').hidden=true;$('#notification-button')?.setAttribute('aria-expanded','false');}
});
