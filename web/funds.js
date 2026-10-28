'use strict';
let fundsDate='',fundsCache=null,fundsAccountFilter='',fundsFlowPeriod='month',fundsFlowDirection='',fundsFlowPage=0,fundsFlowStart='',fundsFlowEnd='';
function fundAccountOptions(value='',empty='请选择资金账户'){
 return `<option value="">${esc(empty)}</option>`+(data.fund_accounts||[]).filter(a=>a.active).map(a=>`<option value="${esc(a.id)}" ${a.id===value?'selected':''}>${esc(a.name)} · ${esc(a.kind)}</option>`).join('');
}
function installFundAccountSelector(root){
 const f=root.querySelector('form');if(!f||f.elements.account_id)return;
 const cash=f.id==='expense-action-form'&&f.dataset.kind==='payment'||f.id==='receipt-form'||f.id==='return-refund-form'||f.id==='resource-form'&&['receive','byproduct'].includes(f.dataset.kind)||f.id==='purchase-form'&&['payment','charge-payment'].includes(f.dataset.kind)||f.id==='finished-form'&&f.dataset.kind==='payment'||f.id==='goods-stock-form'&&f.dataset.kind==='refund'||f.id==='payroll-form'&&f.dataset.kind==='pay';
 if(!cash)return;
 const field=document.createElement('label');field.className='field wide';field.innerHTML='资金账户<select name="account_id" data-fund-account-selector>'+fundAccountOptions('','待关联账户')+'</select><small>实际收付款归入所选账户；未选账户的流水在资金账户页列为待关联。</small>';
 (f.querySelector('.form-grid')||f).append(field);
 const update=()=>{const amount=f.elements.amount||f.elements.received;field.querySelector('select').required=(data.fund_accounts||[]).some(a=>a.active)&&Number(amount?.value||0)>0;};
 f.addEventListener('input',update);update();
}
function fundAccountsReport(){
 const day=fundsDate||today(),month=fundsFlowPeriod==='month'?day.slice(0,7):'',key=[day,month,fundsFlowPeriod,fundsFlowStart,fundsFlowEnd,fundsAccountFilter,fundsFlowDirection,fundsFlowPage,data.auth_user?.id||role,successfulWrites].join('|');
 if(!fundsCache||fundsCache.key!==key){const cache=fundsCache={key,day,loading:true},params=new URLSearchParams({date:day,page:String(fundsFlowPage+1)});if(month)params.set('month',month);if(fundsFlowPeriod==='custom'){params.set('start',fundsFlowStart);params.set('end',fundsFlowEnd);}if(fundsAccountFilter)params.set('account',fundsAccountFilter);if(fundsFlowDirection)params.set('direction',fundsFlowDirection);api('/api/fund-accounts?'+params).then(value=>{if(fundsCache!==cache)return;cache.value=value;fundsFlowPage=Math.max(0,(value.movement_page||1)-1);cache.loading=false;if(page==='fund-accounts')render();}).catch(e=>{if(fundsCache!==cache)return;cache.loading=false;cache.error=e.message;if(page==='fund-accounts')render();});}
 return fundsCache;
}
function fundAccountsPage(){
 const cache=fundAccountsReport(),r=cache.value,editable=canAction('funds.manage');
 const actions=editable?'<button class="button" data-fund-action="transfer">账户间转账</button><button class="button primary" data-fund-action="account">新增账户</button>':'';
 const top=head('资金账户','查看银行、现金等账户的账面余额；应收与实际资金分别统计。',actions)+`<div class="sheet-filters"><label>统计截至日期<input id="funds-date" type="date" value="${esc(cache.day)}"></label><button class="button" data-funds-refresh>刷新账户与流水</button></div>`;
 if(cache.loading)return top+resourcePanel('账户统计','<p class="empty">正在读取资金账户…</p>');
 if(cache.error)return top+resourcePanel('账户统计',`<p class="callout">${esc(cache.error)}</p>`);
 const t=r.totals,accountName=id=>r.accounts.find(a=>a.id===id)?.name||'待关联账户';
 const metricsHTML=metrics([['账户账面余额',yuan(t.balance_cents),'元','各账户期初余额加实际收支；含停用账户'],['本月实际收入',yuan(t.monthly_income_cents),'元','实际收款，不含应收入账和内部转账'],['本月实际支出',yuan(t.monthly_expense_cents),'元','采购、费用、工资、外购成品及退款'],['客户当前未收',yuan(t.receivable_cents),'元','产品与豆渣应收，未计入资金余额']]);
 const pending=t.unassigned_count?`<div class="callout warning">有 ${t.unassigned_count} 笔历史收付款待关联账户：收入 ${amount(t.unassigned_income_cents)}，支出 ${amount(t.unassigned_expense_cents)}，尚未计入具体账户余额。<button class="text-button" data-funds-pending>查看待关联流水</button></div>`:'';
 const accountsHTML=resourcePanel('账户余额与管理',resourceTable(['账户名称 / 类型','账号 / 尾号','期初日期','期初余额','累计收入','累计支出','账面余额','状态','操作'],r.accounts.map(a=>`<tr><td><strong>${esc(a.name)}</strong><small>${esc(a.kind)}</small></td><td>${esc(a.account_no||'—')}</td><td>${esc(a.opening_date)}</td><td>${amount(a.opening_balance_cents)}</td><td>${amount(a.income_cents)}</td><td>${amount(a.expense_cents)}</td><td>${a.balance_cents===null?'期初日期未到':amount(a.balance_cents)}</td><td><span class="badge ${a.active?'green':'gray'}">${a.active?'使用中':'已停用'}</span></td><td><div class="table-action"><button class="text-button" data-fund-account-flows="${esc(a.id)}">流水</button>${editable?`<button class="text-button" data-fund-action="account" data-id="${esc(a.id)}">编辑 / ${a.active?'停用':'启用'}</button>${!a.movement_count&&!a.opening_balance_cents?`<button class="text-button" data-fund-action="delete" data-id="${esc(a.id)}">删除</button>`:''}`:''}</div></td></tr>`).join(''),'尚无资金账户，请新增账户并填写实际期初余额。'),'累计收支从各账户期初日期当天开始计算；期初前流水不重复计入余额。');
 const rows=r.movements,pages=Math.max(1,r.movement_pages||1),total=r.movement_total??rows.length,current=Math.max(1,r.movement_page||1);
 const controls=`<div class="sheet-filters fund-flow-controls"><label>资金账户<select id="funds-account"><option value="">全部账户</option><option value="__pending__" ${fundsAccountFilter==='__pending__'?'selected':''}>待关联账户</option>${r.accounts.map(a=>`<option value="${esc(a.id)}" ${a.id===fundsAccountFilter?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label><label>流水范围<select id="funds-period"><option value="month" ${fundsFlowPeriod==='month'?'selected':''}>统计日期所在月</option><option value="all" ${fundsFlowPeriod==='all'?'selected':''}>截至统计日期的全部流水</option><option value="custom" ${fundsFlowPeriod==='custom'?'selected':''}>自定义起止日期</option></select></label><label>收支方向<select id="funds-direction"><option value="">全部收支</option><option value="in" ${fundsFlowDirection==='in'?'selected':''}>收入</option><option value="out" ${fundsFlowDirection==='out'?'selected':''}>支出</option></select></label></div>`;
 const dateControls=fundsFlowPeriod==='custom'?`<form id="funds-range-form" class="sheet-filters"><label>实际发生日起<input type="date" name="start" required value="${esc(fundsFlowStart)}"></label><label>实际发生日止<input type="date" name="end" required value="${esc(fundsFlowEnd)}"></label><button class="button" type="submit">查询流水</button><span class="help-text">包含起止日；仅查询截至统计日期的流水，账户余额保持截至日期口径。</span></form>`:'';
 const flowRange=r.flow_start&&r.flow_start>r.flow_end?'所选范围晚于统计截至日期':`${r.flow_start?esc(r.flow_start):'全部历史'} 至 ${esc(r.flow_end||r.as_of)}`;
 const flowSummary=`<p class="report-basis" id="funds-flow-summary">${flowRange} · 全部筛选结果 ${r.flow_totals.count} 笔 · 实际收入 ${amount(r.flow_totals.income_cents)} · 实际支出 ${amount(r.flow_totals.expense_cents)}；内部转账在流水中显示，不计经营收支。</p>`;
 const table=resourceTable(['日期','资金账户','业务来源','客户 / 收款方','实际收入','实际支出','凭据 / 备注','操作'],rows.map(m=>`<tr><td>${esc(m.business_date)}</td><td>${esc(accountName(m.account_id))}${m.account_id&&m.business_date<(r.accounts.find(a=>a.id===m.account_id)?.opening_date||'')?'<small>期初前，不重复计入余额</small>':''}</td><td>${esc(m.source)}</td><td>${esc(m.source==='内部转账'?accountName(m.partner):m.partner||'—')}</td><td>${m.direction==='in'?amount(m.amount_cents):'—'}</td><td>${m.direction==='out'?amount(m.amount_cents):'—'}</td><td>${esc(m.note||'—')}</td><td>${editable&&m.source!=='内部转账'?`<button class="text-button" data-fund-action="assign" data-id="${esc(m.id)}">${m.account_id?'更正归属':'关联账户'}</button>`:'—'}</td></tr>`).join(''),'当前范围暂无资金流水。');
 const paging=`<div class="table-end"><span>共 ${total} 笔 · 第 ${current} / ${pages} 页</span><div class="head-actions"><button class="button" data-funds-page="${current-2}" ${current<=1?'disabled':''}>上一页</button><button class="button" data-funds-page="${current}" ${current>=pages?'disabled':''}>下一页</button></div></div>`;
 return top+metricsHTML+pending+accountsHTML+controls+dateControls+resourcePanel('实际资金流水',flowSummary+table+paging,r.basis);
}
function openFundAction(action,id=''){
 if(!needPermission('funds.manage'))return;const report=fundAccountsReport().value;if(!report)return;
 let title='',body='',reference={};
 if(action==='account'){
  const a=report.accounts.find(a=>a.id===id)||{id:'',name:'',kind:'银行账户',active:true,opening_date:today(),opening_balance_cents:0,version:0};
  title=a.id?'编辑资金账户':'新增资金账户';reference={id:a.id,version:a.version};
  body=`<label class="field">账户名称<input name="name" required maxlength="80" value="${esc(a.name)}" placeholder="例如：公司基本户、现金、微信经营收款"></label><label class="field">账户类型<select name="kind">${['银行账户','现金','微信','支付宝','其他'].map(k=>`<option ${a.kind===k?'selected':''}>${k}</option>`).join('')}</select></label><label class="field">账号 / 尾号<input name="account_no" maxlength="80" value="${esc(a.account_no||'')}"></label><label class="field">期初日期<input name="opening_date" type="date" required ${a.movement_count?'readonly':''} value="${esc(a.opening_date)}"></label><label class="field">期初余额（元）<input name="opening_balance" inputmode="decimal" required ${a.movement_count?'readonly':''} value="${a.id?(a.opening_balance_cents/100).toFixed(2):''}" placeholder="填写当天开始时的实际余额"></label><label class="field">状态<select name="active"><option value="true" ${a.active?'selected':''}>启用</option><option value="false" ${!a.active?'selected':''}>停用，保留历史流水及余额</option></select></label><label class="field wide">账户备注<textarea name="note" maxlength="500" rows="2">${esc(a.note||'')}</textarea></label><p class="help-text wide">期初余额为该日期当天开始时余额；之后收付款自动累计。已有流水的账户保留期初，可编辑名称、备注或停用。</p>`;
 }
 if(action==='delete'){
  const a=report.accounts.find(a=>a.id===id);if(!a)return;title='删除未使用账户';reference={id:a.id,version:a.version};body=`<p class="callout wide">确认删除账户“${esc(a.name)}”。已有期初余额或历史流水的账户不能删除，可在编辑中停用。</p>`;
 }
 if(action==='assign'){
  const m=report.movements.find(m=>m.id===id);if(!m)return;title='关联收付款账户';reference={movement_id:m.id,fingerprint:m.fingerprint,version:m.assignment_version||0};
  body=`<p class="callout wide">${esc(m.business_date)} · ${esc(m.source)} · ${esc(m.partner)} · ${m.direction==='in'?'收入':'支出'} ${amount(m.amount_cents)}。只调整资金账户归属，原应收、应付和实际收付金额保持一致。</p><label class="field wide">资金账户<select name="account_id" required>${fundAccountOptions(m.account_id)}</select></label><label class="field wide">关联依据 / 更正原因<textarea name="note" required maxlength="500" rows="2"></textarea></label>`;
 }
 if(action==='transfer'){
  title='账户间转账';body=`<label class="field">转出账户<select name="from_account_id" required>${fundAccountOptions()}</select></label><label class="field">转入账户<select name="to_account_id" required>${fundAccountOptions()}</select></label><label class="field">实际转账日期<input name="business_date" type="date" required value="${today()}"></label><label class="field">转账金额（元）<input name="amount" inputmode="decimal" required></label><label class="field wide">转账凭据 / 说明<textarea name="note" required maxlength="500" rows="2"></textarea></label><p class="help-text wide">内部转账同时减少转出账户、增加转入账户，不计作经营收入或费用。手续费应另行登记实际费用付款。</p>`;
 }
 if(!title)return;
 openDialog(title,`<form id="funds-form" class="form-grid" data-action="${action}" data-reference="${esc(JSON.stringify(reference))}" data-key="${erpRequestKey()}">${body}</form>`,'资金账户管理','<button class="button" data-act="close">取消</button><button class="button '+(action==='delete'?'danger':'primary')+'" data-funds-save>'+({delete:'确认删除',assign:'确认关联',transfer:'确认已转账',account:'保存账户'})[action]+'</button>');
}
async function saveFundAction(){
 const f=$('#funds-form');if(!f||!f.reportValidity())return;const action=f.dataset.action,body={...Object.fromEntries(new FormData(f)),...JSON.parse(f.dataset.reference),action,request_key:f.dataset.key};if(action==='account')body.active=body.active==='true';
 await perform(async()=>{await api('/api/fund-accounts',body);data=await api('/api/bootstrap');fundsCache=null;busy=false;closeDialog();render();notify(({account:'资金账户已保存',delete:'未使用账户已删除',assign:'流水账户归属已更新',transfer:'内部转账已登记'})[action]);});
}
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-fund-action]');if(button)requestPageTransition(()=>openFundAction(button.dataset.fundAction,button.dataset.id),{dialogOnly:true});
 if(e.target.closest('[data-funds-save]'))saveFundAction();
 if(e.target.closest('[data-funds-refresh]')){fundsCache=null;render();}
 if(e.target.closest('[data-funds-pending]')){fundsAccountFilter='__pending__';fundsFlowPeriod='all';fundsFlowPage=0;render();}
 const flows=e.target.closest('[data-fund-account-flows]');if(flows){fundsAccountFilter=flows.dataset.fundAccountFlows;fundsFlowPeriod='all';fundsFlowPage=0;render();}
 const pager=e.target.closest('[data-funds-page]');if(pager){fundsFlowPage=Number(pager.dataset.fundsPage);render();}
});
document.addEventListener('change',e=>{
 if(e.target.id==='funds-date'){fundsDate=e.target.value;fundsFlowPage=0;render();}
 if(e.target.id==='funds-account'){fundsAccountFilter=e.target.value;fundsFlowPage=0;render();}
 if(e.target.id==='funds-period'){fundsFlowPeriod=e.target.value;if(fundsFlowPeriod==='custom'&&(!fundsFlowStart||!fundsFlowEnd)){const day=fundsDate||today();fundsFlowStart=day.slice(0,7)+'-01';fundsFlowEnd=day;}fundsFlowPage=0;render();}
 if(e.target.id==='funds-direction'){fundsFlowDirection=e.target.value;fundsFlowPage=0;render();}
});

document.addEventListener('submit',e=>{const f=e.target.closest('#funds-range-form');if(!f)return;e.preventDefault();const values=Object.fromEntries(new FormData(f));if(!f.reportValidity())return;if(values.start>values.end||(Date.parse(values.end)-Date.parse(values.start))/86400000>3651){err(Error('请填写正序且不超过3652天的流水日期；原查询结果已保留'));return;}fundsFlowStart=values.start;fundsFlowEnd=values.end;fundsFlowPage=0;fundsCache=null;render();});
