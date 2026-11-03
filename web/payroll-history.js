'use strict';
let payrollHistoryOpen=false,payrollHistoryKind='sheet';
const payrollHistoryScopes={};
const payrollHistoryStatuses={draft:'草稿',conflict:'同月多份待核查',unknown:'历史金额待核查',unpaid:'未发放',partial:'部分发放',paid:'已发清',overpaid:'超额发放待核查'};
const payrollHistoryMoney=value=>value==null?'历史未列':amount(value);
function payrollHistoryState(){
 const kind=payrollHistoryKind,filter=payrollHistoryScopes[kind]||(payrollHistoryScopes[kind]={start:today().slice(0,4)+'-01-01',end:today(),all:false,salary_month:'',employee_id:'',status:'',search:'',page:1});
 const q=new URLSearchParams({kind,salary_month:filter.salary_month,employee_id:filter.employee_id,search:filter.search,page:filter.page,page_size:pageSizeDefault()});
 if(kind==='sheet'&&filter.status)q.set('status',filter.status);
 if(filter.all)q.set('all','1');else{q.set('start',filter.start);q.set('end',filter.end);}
 const key='payroll-history|'+q;let state=factoryReports.get(key);
 if(!state){state={loading:true};factoryReports.set(key,state);api('/api/payroll-history?'+q).then(value=>{if(factoryReports.get(key)!==state)return;factoryReports.set(key,{value});if(page==='payroll'&&payrollHistoryOpen&&payrollHistoryKind===kind)render();}).catch(error=>{if(factoryReports.get(key)!==state)return;factoryReports.set(key,{error:error.message});if(page==='payroll'&&payrollHistoryOpen&&payrollHistoryKind===kind)render();});}
 return {filter,state};
}
function payrollHistoryPage(){
 const {filter:f,state}=payrollHistoryState(),sheet=payrollHistoryKind==='sheet';
 const tabs=`<div class="workflow-tabs" aria-label="工资历史类型">${[['sheet','工资单历史'],['payment','实际发放']].map(([k,t])=>`<button class="${payrollHistoryKind===k?'active':''}" data-payroll-history-kind="${k}">${t}</button>`).join('')}</div>`;
 const form=`<form id="payroll-history-form" class="sheet-filters"><label class="check-line"><input type="checkbox" name="all" ${f.all?'checked':''}>全部日期</label><label>${sheet?'所属月末':'实际发放'}开始日期<input type="date" name="start" value="${esc(f.start)}" ${f.all?'disabled':''} required></label><label>结束日期<input type="date" name="end" value="${esc(f.end)}" ${f.all?'disabled':''} required></label><label>工资所属月份<input type="month" name="salary_month" value="${esc(f.salary_month)}"></label><label>员工编号（可选）<input name="employee_id" maxlength="100" value="${esc(f.employee_id)}"></label>${sheet?`<label>当前状态<select name="status"><option value="">全部状态</option>${Object.entries(payrollHistoryStatuses).map(([k,t])=>`<option value="${k}" ${f.status===k?'selected':''}>${t}</option>`).join('')}</select></label>`:''}<label>查找<input type="search" name="search" maxlength="100" value="${esc(f.search)}" placeholder="${sheet?'姓名、部门、调整说明':'姓名、经办人、发放凭据'}"></label><button class="button primary" type="submit">查询</button></form>`;
 const top=head('工资与发放历史','工资单保留原核算依据；实际发放按付款日期单独查询。','<button class="button" data-payroll-history-back>返回工资办理</button>')+tabs+form;
 if(!state.value)return top+readState('工资历史',state.error);
 const r=state.value,s=r.summary;
 const summary=sheet?`<p>共 ${r.total} 个人员项 · ${s.sheets} 张工资单 · ${s.months} 个月。已确认且无冲突的已列金额：应发 ${amount(s.net_cents)} · 当前累计已发 ${amount(s.paid_cents)} · 当前未发 ${amount(s.outstanding_cents)}</p><p>草稿 ${s.draft} 项 · 冲突 ${s.conflict} 项 · 历史金额待核查 ${s.unknown} 项 · 超额发放待核查 ${s.overpaid} 项。未列金额不按零处理。</p>`:`<p>共 ${r.total} 次发放 · ${s.employees} 人 · 已列实际发放 ${amount(s.amount_cents)} · 金额未列 ${s.unknown} 条</p>`;
 const pager=`<div class="table-end"><span>共 ${r.total} 项 · 第 ${r.page} / ${r.pages} 页</span><div class="head-actions"><button class="button" data-payroll-history-page="${r.page-1}" ${r.page<=1?'disabled':''}>上一页</button><button class="button" data-payroll-history-page="${r.page+1}" ${r.page>=r.pages?'disabled':''}>下一页</button></div></div>`;
 const headers=sheet?['所属月份 / 月末日期','原单人员','原班组 / 部门','原单应发','当前累计已发','当前未发','当前状态','记录更新时间','查看']:['实际发放日期','工资所属月','人员','发放金额','实际方式','经办人 / 凭据','查看'];
 const body=r.rows.map((row,i)=>sheet?`<tr><td>${esc(row.month)}<small>${esc(row.business_date)}</small></td><td>${esc(row.employee_name)}</td><td>${esc(row.group_name||'未列')}<small>${esc(row.department||'')}</small></td><td>${payrollHistoryMoney(row.net_cents)}</td><td>${payrollHistoryMoney(row.paid_cents)}</td><td>${payrollHistoryMoney(row.outstanding_cents)}</td><td>${esc(row.status_label)}</td><td>${esc(row.updated_at||'未列')}</td><td><button class="text-button" data-payroll-history-detail="${i}">原单快照</button><button class="text-button" data-payroll-history-payments="${i}">查看发放</button></td></tr>`:`<tr><td>${esc(row.business_date||'未列')}</td><td>${esc(row.month||'未列')}</td><td>${esc(row.employee_name)}</td><td>${payrollHistoryMoney(row.amount_cents)}</td><td>${esc(row.method_label)}</td><td class="long-note">${esc(row.handler||'未列')}<small>${esc(row.reference||'未列')}</small></td><td><button class="text-button" data-payroll-history-detail="${i}">原发放记录</button></td></tr>`).join('');
 return top+`<p class="panel-explanation">${esc(r.basis)}</p><section class="panel"><div class="panel-head"><div><h2>完整范围汇总</h2>${summary}</div></div></section>`+pager+resourcePanel(sheet?'原工资单人员明细':'实际发放流水',resourceTable(headers,body))+pager;
}
async function payrollHistoryDetail(index){
 const row=payrollHistoryState().state.value?.rows[index];if(!row)return;
 const r=await api('/api/payroll-history-record?'+new URLSearchParams({kind:payrollHistoryKind,id:row.id,employee_id:row.employee_id||''}));
 let body=`<p>原记录 ${esc(r.id)} · 工资所属月 ${esc(r.month)} · 版本 ${esc(r.version)} · 记录更新时间 ${esc(r.updated_at||'未列')}</p>`;
 if(r.kind==='sheet'){
  const v=r.row,fields=[['基本工资','base_cents'],['公司社保补偿款','social_company_cents'],['个人社保补偿款','social_personal_cents'],['加项','bonus_cents'],['扣项','deduction_cents'],['原单应发','net_cents']];
  body+=`<p>${esc(v.employee_name||'未列')} · 原计薪天数 ${esc(v.pay_days??'未列')} · 单独保存的确认时间 ${esc(r.confirmed_at||'未列')}</p><p>原核算标准：${v.salary_mode==='annual'?'固定年薪':v.salary_mode==='monthly'?'月工资':'历史未列'}；月标准 ${payrollHistoryMoney(v.monthly_cents)}，年标准 ${payrollHistoryMoney(v.annual_cents)}</p>`+resourceTable(fields.map(([t])=>t),'<tr>'+fields.map(([,k])=>`<td>${payrollHistoryMoney(v[k])}</td>`).join('')+'</tr>')+`<p class="long-note">原核算说明：${esc(v.calculation_note||'未列')}<br>调整说明：${esc(v.reason||'未列')}</p>`+resourceTable(['原考勤日期','原考勤状态','原班组','原备注'],r.cells.map(cell=>`<tr><td>${esc(cell.date)}</td><td>${esc(cell.label||cell.status||'未列')}</td><td>${esc(cell.group_name||'未列')}</td><td class="long-note">${esc(cell.note||'—')}</td></tr>`).join(''),'原单未保存考勤明细；不按当前考勤重建');
 }else body+=`<p>${esc(r.employee_name||'未列')} · 实际发放日期 ${esc(r.business_date||'未列')} · 金额 ${payrollHistoryMoney(r.amount_cents)}</p><p>方式 ${esc(wagePaymentMethod(r.method))} · 经办人 ${esc(r.handler||'未列')}</p><p class="long-note">凭据：${esc(r.reference||'未列')}</p><p>原收款银行 ${esc(r.recipient.bank_name||'未列')} · 户名 ${esc(r.recipient.account_name||'未列')} · 尾号 ${esc(r.recipient.card_tail||'未列')}</p>`;
 openDialog(r.kind==='sheet'?'工资原单快照':'原发放记录',body,'只读原保存依据','<button class="button" data-act="close">关闭</button>');
}
document.addEventListener('click',event=>{
 if(event.target.closest('[data-payroll-history-open]')){requestPageTransition(()=>{payrollHistoryOpen=true;render();});return;}
 if(event.target.closest('[data-payroll-history-back]')){requestPageTransition(()=>{payrollHistoryOpen=false;render();});return;}
 const tab=event.target.closest('[data-payroll-history-kind]'),pager=event.target.closest('[data-payroll-history-page]'),detail=event.target.closest('[data-payroll-history-detail]'),payments=event.target.closest('[data-payroll-history-payments]');
 if(tab){payrollHistoryKind=tab.dataset.payrollHistoryKind;render();}
 if(pager&&!pager.disabled){payrollHistoryScopes[payrollHistoryKind].page=Number(pager.dataset.payrollHistoryPage);render();}
 if(detail)requestPageTransition(()=>payrollHistoryDetail(Number(detail.dataset.payrollHistoryDetail)),{dialogOnly:true});
 if(payments){const row=payrollHistoryState().state.value?.rows[Number(payments.dataset.payrollHistoryPayments)];if(!row)return;payrollHistoryKind='payment';payrollHistoryState();Object.assign(payrollHistoryScopes.payment,{all:true,salary_month:row.month,employee_id:row.employee_id,search:'',page:1});render();}
});
document.addEventListener('change',event=>{if(event.target.closest('#payroll-history-form')&&event.target.name==='all')for(const input of event.target.form.querySelectorAll('input[type=date]'))input.disabled=event.target.checked;});
document.addEventListener('submit',event=>{
 if(event.target.id!=='payroll-history-form')return;event.preventDefault();const v=Object.fromEntries(new FormData(event.target)),all=v.all==='on';
 if(!all&&(!validISODate(v.start)||!validISODate(v.end)||v.start>v.end||(Date.parse(v.end)-Date.parse(v.start))/86400000>3652)){notify('请选择正序且最多3652天的有效日期');return;}
 Object.assign(payrollHistoryScopes[payrollHistoryKind],v,{all,page:1});render();
});
