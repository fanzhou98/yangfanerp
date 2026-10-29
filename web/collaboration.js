'use strict';
// Internal chat, notification inbox and administrator feedback.
let notificationData=null,notificationTimer=null,notificationInitialized=false,notificationSeen=new Set();
let chatThreads=[],chatUsers=[],chatThreadId='',chatMessages=[],chatSeq=0,chatLoaded=false,chatLoading=false,chatError='',chatDraft='',chatLoadToken=0;
let feedbackData=null,feedbackLoaded=false,feedbackLoading=false,feedbackError='',feedbackFilter='all',feedbackSearch='',feedbackStart='',feedbackEnd='',feedbackAll=false,feedbackPageNo=1;
let collaborationTimer=null;

function collaborationTime(value){if(!value)return '';const text=String(value).replace('T',' ');return text.length>=16?text.slice(5,16):text;}
function collaborationTitle(t){return t?.title||'会话';}
function collaborationInitial(t){return t?.kind==='direct'?(collaborationTitle(t).slice(0,1)||'聊'):'#';}
function collaborationNavCount(pageName){
 if(pageName==='chat'){const n=notificationData?.counts?.chat_unread||0;return `<span class="nav-count" data-nav-count="chat" ${n?'':'hidden'}>${n>99?'99+':n}</span>`;}
 if(pageName==='feedback'){const n=feedbackData?.counts?.feedback_open??notificationData?.counts?.feedback_open??0;return `<span class="nav-count" data-nav-count="feedback" ${n?'':'hidden'}>${n>99?'99+':n}</span>`;}
 return '';
}
function collaborationNavigationCount(pageName){
 if(pageName==='feedback'&&data?.auth_user?.role!=='管理员')return '';
 return collaborationNavCount(pageName);
}
function updateCollaborationBadges(){
 const chatCount=notificationData?.counts?.chat_unread||0,feedbackCount=feedbackData?.counts?.feedback_open??notificationData?.counts?.feedback_open??0;
 for(const [key,value] of [['chat',chatCount],['feedback',feedbackCount]]){const el=$(`[data-nav-count="${key}"]`);if(el){el.textContent=value>99?'99+':String(value);el.hidden=!value;}}
 const badge=$('#notification-count');if(badge){const value=notificationData?.unread_count||0;badge.textContent=value>99?'99+':String(value);badge.hidden=!value;}
}

function initCollaboration(){
 if(!data?.auth_user)return;
 stopCollaboration();
 notificationData=null;notificationInitialized=false;notificationSeen=new Set();
 chatThreads=[];chatUsers=[];chatThreadId='';chatMessages=[];chatSeq=0;chatLoaded=false;chatLoading=false;chatError='';chatDraft='';chatLoadToken=0;
 feedbackData=null;feedbackLoaded=false;feedbackLoading=false;feedbackError='';feedbackFilter='all';feedbackSearch='';feedbackStart='';feedbackEnd='';feedbackAll=false;feedbackPageNo=1;
 loadNotifications(true).catch(()=>{});
 notificationTimer=setInterval(()=>{if(data?.auth_user)loadNotifications(false).catch(()=>{});},25000);
 collaborationTimer=setInterval(()=>{if(page==='chat'&&chatLoaded&&!chatLoading)pollChat().catch(()=>{});},8000);
}
function stopCollaboration(){
 if(notificationTimer){clearInterval(notificationTimer);notificationTimer=null;}
 if(collaborationTimer){clearInterval(collaborationTimer);collaborationTimer=null;}
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
 panel.innerHTML=`<div class="notification-head"><div><b>消息通知</b><small>${notificationData?.unread_count?notificationData.unread_count+' 条未读':'全部已读'}</small></div><button class="text-button" data-notification-read-all ${notificationData?.unread_count?'':'disabled'}>全部已读</button></div><div class="notification-list">${items.slice(0,30).map(item=>`<button type="button" class="notification-item ${item.read?'read':''}" data-notification-item="${esc(item.id)}" data-notification-thread="${esc(item.thread_id||'')}" data-notification-page="${esc(item.page||'')}"><span class="notification-kind ${esc(item.kind)}">${item.kind==='chat'?'聊':'反'}</span><span class="notification-copy"><b>${esc(item.title||'通知')}</b><p>${esc(item.body||'')}</p><small>${esc(collaborationTime(item.created_at))}${item.actor_name?' · '+esc(item.actor_name):''}</small></span></button>`).join('')||'<p class="empty">暂无通知</p>'}</div><div class="notification-foot"><button class="text-button" data-page="chat">打开内部聊天 ↗</button><button class="text-button" data-page="feedback">问题反馈 ↗</button></div>`;
}
function toggleNotificationPanel(){
 const panel=$('#notification-panel'),button=$('#notification-button');if(!panel)return;
 const open=panel.hidden;panel.hidden=!open;button?.setAttribute('aria-expanded',String(open));
 if(open){renderNotificationPanel();loadNotifications(false,{silent:true}).catch(()=>{});}
}
async function openNotification(button){
 const id=button.dataset.notificationItem,thread=button.dataset.notificationThread,target=button.dataset.notificationPage;
 button.classList.add('read');
 if(notificationData){const item=notificationData.items.find(value=>value.id===id);if(item&&!item.read){item.read=true;notificationData.unread_count=Math.max(0,(notificationData.unread_count||0)-1);}}
 updateCollaborationBadges();
 try{await api('/api/notifications/read',{ids:[id]});}catch{}
 const panel=$('#notification-panel');if(panel){panel.hidden=true;$('#notification-button')?.setAttribute('aria-expanded','false');}
 if(thread){openChatThread(thread);return;}
 if(target&&typeof goto==='function')goto(target);
}
async function markAllNotificationsRead(){
 try{const result=await api('/api/notifications/read',{all:true});if(notificationData){notificationData.items.forEach(item=>item.read=true);notificationData.unread_count=result.unread_count||0;}updateCollaborationBadges();renderNotificationPanel();notify('通知已全部标记为已读');}catch(error){notify(error.message);}
}

async function openChatThread(id){
 chatThreadId=id;chatMessages=[];chatSeq=0;chatLoaded=false;chatError='';
 const run=()=>{if(page!=='chat')goto('chat');else loadChat().catch(()=>{});};
 if(typeof requestPageTransition==='function')requestPageTransition(run);else run();
}
async function loadChat(){
 const token=++chatLoadToken;chatLoading=true;chatError='';
 try{
  const result=await api('/api/chat');
  if(token!==chatLoadToken)return;
  chatThreads=result.threads||[];chatUsers=result.users||[];
  if(!chatThreadId||!chatThreads.some(t=>t.id===chatThreadId))chatThreadId=chatThreads[0]?.id||'';
  chatLoaded=true;
  if(chatThreadId)await loadChatMessages(chatThreadId,{replace:true});
  if(token!==chatLoadToken)return;
  if(notificationData){notificationData.counts={...(notificationData.counts||{}),chat_unread:chatThreads.reduce((n,t)=>n+(t.unread_count||0),0)};updateCollaborationBadges();}
 }catch(error){if(token===chatLoadToken){chatError=error.message;chatLoaded=true;}}
 finally{if(token===chatLoadToken){if(page==='chat'){render();requestAnimationFrame(()=>{const box=$('#chat-messages');if(box)box.scrollTop=box.scrollHeight;});}chatLoading=false;}}
}
async function loadChatMessages(id,{replace=false}={}){
 const after=replace?0:chatSeq;
 const result=await api('/api/chat/messages?thread_id='+encodeURIComponent(id)+(after?'&after='+after:''));
 if(id!==chatThreadId)return false;
 const incoming=result.messages||[];
 if(replace||!after)chatMessages=incoming;
 else{const known=new Set(chatMessages.map(message=>message.id));chatMessages=chatMessages.concat(incoming.filter(message=>!known.has(message.id)));}
 chatSeq=Math.max(chatSeq,...incoming.map(message=>Number(message.seq)||0),Number(result.last_seq)||0);
 if(result.thread){const index=chatThreads.findIndex(t=>t.id===id);if(index>=0)chatThreads[index]={...chatThreads[index],...result.thread,unread_count:0};}
 if(incoming.length){try{await api('/api/chat/read',{thread_id:id,last_seq:chatSeq});loadNotifications(false,{silent:true}).catch(()=>{});}catch{}}
 if(notificationData){notificationData.counts={...(notificationData.counts||{}),chat_unread:chatThreads.reduce((n,t)=>n+(t.unread_count||0),0)};updateCollaborationBadges();}
 return incoming.length>0;
}
async function pollChat(){
 if(!chatThreadId)return;
 const result=await api('/api/chat');chatThreads=result.threads||[];chatUsers=result.users||[];
 if(!chatThreads.some(t=>t.id===chatThreadId)){chatThreadId=chatThreads[0]?.id||'';chatMessages=[];chatSeq=0;}
 const changed=await loadChatMessages(chatThreadId,{replace:false});
 if(notificationData){notificationData.counts={...(notificationData.counts||{}),chat_unread:chatThreads.reduce((n,t)=>n+(t.unread_count||0),0)};updateCollaborationBadges();}
 if(changed&&page==='chat')render();
}
function chatMessageMarkup(message){const mine=message.sender_id===data?.auth_user?.id;return `<article class="chat-message ${mine?'mine':''}" data-chat-message="${esc(message.id)}"><div class="chat-message-meta"><b>${esc(mine?'我':message.sender_name||'同事')}</b><time>${esc(collaborationTime(message.created_at))}</time></div><p>${esc(message.body).replace(/\n/g,'<br>')}</p></article>`;}
function chatPage(){
 if(!chatLoaded){if(!chatLoading)loadChat().catch(()=>{});return head('内部聊天','同事之间直接沟通，消息与未读提醒保留在本系统。','','COLLABORATION · 内部沟通')+readState('聊天',chatError);}
 if(chatError&&!chatThreads.length)return head('内部聊天','同事之间直接沟通，消息与未读提醒保留在本系统。','','COLLABORATION · 内部沟通')+`<section class="panel"><div class="empty">${esc(chatError)}</div></section>`;
 const current=chatThreads.find(t=>t.id===chatThreadId)||chatThreads[0];
 if(!current)return head('内部聊天','同事之间直接沟通。','','COLLABORATION · 内部沟通')+`<section class="panel"><div class="empty">暂无会话。点击“发起聊天”开始。</div></section>`;
 if(current.id!==chatThreadId)chatThreadId=current.id;
 const threads=chatThreads.map(t=>`<button type="button" class="chat-thread ${t.id===chatThreadId?'active':''}" data-chat-thread="${esc(t.id)}"><span class="chat-avatar">${esc(collaborationInitial(t))}</span><span class="chat-thread-copy"><b>${esc(collaborationTitle(t))}</b><small>${esc(t.last_message?.body||'暂无消息')}</small></span>${t.unread_count?`<span class="chat-unread">${t.unread_count>99?'99+':t.unread_count}</span>`:''}</button>`).join('');
 const messages=chatMessages.map(chatMessageMarkup).join('');
 return head('内部聊天','同事之间直接沟通，消息与未读提醒保留在本系统。',`<button class="button primary" data-chat-new>＋ 发起聊天</button>`,'COLLABORATION · 内部沟通')+
 `<section class="panel chat-shell"><aside class="chat-thread-list" aria-label="会话列表"><div class="chat-list-head"><b>会话</b><span>${chatThreads.length}</span></div>${threads}</aside><section class="chat-conversation"><header class="chat-conversation-head"><div><h2>${esc(collaborationTitle(current))}</h2><p>${current.kind==='direct'?'私聊':'群聊'} · ${current.member_count} 人${current.members?.length?' · '+current.members.map(member=>esc(member.display_name)).join('、'):''}</p></div><span class="chat-online-note">消息保存在本系统</span></header><div class="chat-messages" id="chat-messages">${messages||'<div class="chat-empty">还没有消息，发一条开始沟通。</div>'}</div><form class="chat-compose" id="chat-form"><label class="sr-only" for="chat-input">输入消息</label><textarea id="chat-input" name="body" rows="2" maxlength="4000" placeholder="输入消息，Enter 发送，Shift + Enter 换行">${esc(chatDraft)}</textarea><button class="button primary" type="button" data-chat-send>发送</button></form></section></section>`;
}
function openChatThreadDialog(){
 const users=chatUsers.filter(user=>user.id!==data?.auth_user?.id);
 if(!users.length){notify('当前没有其他可聊天的账号');return;}
 openDialog('发起聊天',`<form id="chat-thread-form"><div class="form-grid"><label class="field">会话类型<select name="kind" id="chat-thread-kind"><option value="direct">私聊</option><option value="group">群聊</option></select></label><div class="field wide" id="chat-direct-field"><label>选择同事<select name="user_id">${users.map(user=>`<option value="${esc(user.id)}">${esc(user.display_name)}（${esc(user.role)}）</option>`).join('')}</select></label></div><div class="wide" id="chat-group-fields" hidden><label class="field">群聊名称<input name="title" maxlength="60" placeholder="例如：夜班交接"></label><fieldset class="chat-member-picker"><legend>选择群聊成员</legend>${users.map(user=>`<label><input type="checkbox" name="user_ids" value="${esc(user.id)}"><span>${esc(user.display_name)}<small>${esc(user.role)}</small></span></label>`).join('')}</fieldset></div></div></form>`,'COLLABORATION · 新会话',`<button class="button" data-act="close">取消</button><button class="button primary" data-chat-thread-create>开始聊天</button>`);
}
async function createChatThread(){
 const form=$('#chat-thread-form');if(!form||!form.reportValidity())return;
 const kind=form.elements.kind.value;
 const body=kind==='direct'?{kind,user_id:form.elements.user_id.value,request_key:erpRequestKey()}:{kind,title:form.elements.title.value,user_ids:$$('input[name=user_ids]:checked',form).map(input=>input.value),request_key:erpRequestKey()};
 if(kind==='group'&&!body.user_ids.length){notify('请至少选择一位群聊成员');return;}
 const button=$('[data-chat-thread-create]');if(button)button.disabled=true;
 try{const result=await api('/api/chat/thread',body);closeDialog();chatThreadId=result.id;chatMessages=[];chatSeq=0;chatLoaded=false;notify(kind==='direct'?'已进入私聊':'群聊已创建');if(page!=='chat')goto('chat');else loadChat().catch(()=>{});}catch(error){notify(error.message);}finally{if(button?.isConnected)button.disabled=false;}
}
async function sendChatMessage(){
 if(!chatThreadId)return;
 const input=$('#chat-input');if(!input)return;
 const message=input.value.trim();if(!message){input.focus();return;}
 const button=$('[data-chat-send]');if(button)button.disabled=true;
 try{
  const result=await api('/api/chat/send',{thread_id:chatThreadId,body:message,request_key:erpRequestKey()});
  chatDraft='';input.value='';
  if(result.message&&!chatMessages.some(item=>item.id===result.message.id))chatMessages.push(result.message);
  chatSeq=Math.max(chatSeq,Number(result.message?.seq)||0);
  if(result.thread){const index=chatThreads.findIndex(t=>t.id===chatThreadId);if(index>=0)chatThreads[index]={...chatThreads[index],...result.thread};}
  try{await api('/api/chat/read',{thread_id:chatThreadId,last_seq:chatSeq});}catch{}
  loadNotifications(false,{silent:true}).catch(()=>{});
  if(page==='chat'){render();requestAnimationFrame(()=>{const box=$('#chat-messages');if(box)box.scrollTop=box.scrollHeight;$('#chat-input')?.focus();});}
 }catch(error){notify(error.message);}finally{if(button?.isConnected)button.disabled=false;}
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
 if(event.target.closest('[data-chat-new]')){openChatThreadDialog();return;}
 if(event.target.closest('[data-chat-thread-create]')){createChatThread().catch(error=>notify(error.message));return;}
 const thread=event.target.closest('[data-chat-thread]');if(thread){if(thread.dataset.chatThread!==chatThreadId){openChatThread(thread.dataset.chatThread);}return;}
 if(event.target.closest('[data-chat-send]')){sendChatMessage().catch(error=>notify(error.message));return;}
 if(event.target.closest('[data-feedback-submit]')){submitFeedback().catch(error=>notify(error.message));return;}
 const reply=event.target.closest('[data-feedback-reply]');if(reply){replyFeedback(reply.dataset.feedbackReply).catch(error=>notify(error.message));return;}
 const filter=event.target.closest('[data-feedback-filter]');if(filter){feedbackFilter=filter.dataset.feedbackFilter;feedbackPageNo=1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 if(event.target.closest('[data-feedback-apply]')){feedbackStart=$('#feedback-start')?.value||'';feedbackEnd=$('#feedback-end')?.value||'';feedbackSearch=$('#feedback-search')?.value||'';feedbackAll=false;feedbackPageNo=1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 if(event.target.closest('[data-feedback-all]')){feedbackAll=true;feedbackPageNo=1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 const fp=event.target.closest('[data-feedback-page]');if(fp){feedbackPageNo=Number(fp.dataset.feedbackPage)||1;feedbackLoaded=false;feedbackData=null;loadFeedback().catch(error=>notify(error.message));return;}
 if(!event.target.closest('#notification-panel')){const panel=$('#notification-panel');if(panel&&!panel.hidden){panel.hidden=true;$('#notification-button')?.setAttribute('aria-expanded','false');}}
});
document.addEventListener('change',event=>{
 if(event.target.id==='chat-thread-kind'){const group=event.target.value==='group';const direct=$('#chat-direct-field'),fields=$('#chat-group-fields');if(direct)direct.hidden=group;if(fields)fields.hidden=!group;}
});
document.addEventListener('input',event=>{
 if(event.target.id==='chat-input')chatDraft=event.target.value;
});
document.addEventListener('keydown',event=>{
 if(isTextComposing(event))return;
 if(event.key==='Escape'&&!$('#notification-panel')?.hidden){$('#notification-panel').hidden=true;$('#notification-button')?.setAttribute('aria-expanded','false');}
 if(event.target.id==='chat-input'&&event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendChatMessage().catch(error=>notify(error.message));}
});
document.addEventListener('submit',event=>{if(event.target.id==='chat-form'){event.preventDefault();sendChatMessage().catch(error=>notify(error.message));}});
