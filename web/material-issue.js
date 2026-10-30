'use strict';
// 原辅料领用：独立高频登记页。领用只登记数量，成本按 FIFO 计价；
// 登记了多个承担产品时，月报按覆盖期内各产品实际供浆用豆量分摊。
let materialIssueMonth='',materialIssueDraft=[],materialIssueDates={start:'',end:''};
const materialIssueData=()=>data.resources||{items:[],entries:[]};
function materialIssueMonthValue(){return materialIssueMonth||today().slice(0,7);}
function materialIssueItems(){return materialIssueData().items.filter(i=>i.active&&!['RM-SOY'].includes(i.id)&&!reusableCrateIds.includes(i.id)).sort((a,b)=>String(a.category+a.name).localeCompare(String(b.category+b.name),'zh'));}
function materialIssueReport(month){const key='material-issue|'+month;let state=factoryReports.get(key);if(!state){state={loading:true};factoryReports.set(key,state);api('/api/material-issue?month='+encodeURIComponent(month)).then(value=>{if(factoryReports.get(key)!==state)return;factoryReports.set(key,{value});if(page==='material-issue')render();}).catch(error=>{if(factoryReports.get(key)!==state)return;factoryReports.set(key,{error:error.message});if(page==='material-issue')render();});}return state;}
function materialIssueProductNames(ids){return (ids||[]).map(id=>data.products.find(p=>p.id===id)?.name||id).join('、');}
function materialIssueDraftTotal(){return materialIssueDraft.reduce((n,r)=>n+(r.qty||0),0);}
function materialIssueResetDates(){const d=today();materialIssueDates={start:d,end:d};}
function materialIssueTodayStart(){const d=today();if(!materialIssueDates.start)materialIssueDates={start:d,end:d};return materialIssueDates;}
function materialIssueOptions(selected){const items=materialIssueItems();const groups=new Map();for(const i of items){const list=groups.get(i.category)||groups.set(i.category,[]).get(i.category);list.push(i);}return [...groups.entries()].map(([category,list])=>`<optgroup label="${esc(category)}">${list.map(i=>`<option value="${esc(i.id)}" ${i.id===selected?'selected':''}>${esc(i.name)}（${esc(i.unit)}）</option>`).join('')}</optgroup>`).join('');}
const MATERIAL_ISSUE_QUICK=['A-GYPSUM','A-DEFOAMER','A-ALKALI','A-SALT','P-BAG','P-CLOTH'];
function materialIssuePrefs(){try{const v=JSON.parse(localStorage.getItem('erp.materialIssue.preference')||'{}');return v&&typeof v==='object'?v:{};}catch{return {};}}
function materialIssueRemember(){const f=$('#material-issue-form');if(!f)return;try{localStorage.setItem('erp.materialIssue.preference',JSON.stringify({material_id:f.elements.material_id.value,warehouse_id:f.elements.warehouse_id.value}));}catch{}}
function materialIssueMaterialValue(){const items=materialIssueItems(),pref=materialIssuePrefs().material_id;return items.some(i=>i.id===pref)?pref:(items.find(i=>i.id==='A-GYPSUM')||items[0]||{}).id||'';}
function materialIssueStockRow(mid,wid){return (materialIssueData().warehouse_stocks||[]).find(r=>r.id===mid&&r.warehouse_id===wid);}
function materialIssueWarehouseValue(mid){const pref=materialIssuePrefs().warehouse_id,row=(materialIssueData().warehouse_stocks||[]).find(r=>r.id===mid&&r.warehouse_id===pref);if(row)return pref;const own=(materialIssueData().warehouse_stocks||[]).find(r=>r.id===mid&&Number(r.qty)>0);return own?.warehouse_id||'WH-COMMON';}
function materialIssuePreviewHtml(mid,wid,qty){const item=materialIssueData().items.find(i=>i.id===mid)||{},row=materialIssueStockRow(mid,wid)||{};const price=Number(row.average_price??item.average_price??0),n=Number(qty)||0,stock=Number(row.qty??item.qty??0),unit=item.unit||'',reorder=Number(item.reorder_qty||0),low=(row.low_stock??item.low_stock)||(reorder>0&&stock<=reorder);return `<span>当前结存 <b>${num(stock)} ${esc(unit)}</b>${low?' <span class="badge orange">低库存</span>':''}</span><span>本单约 <b>${amount(Math.round(n*price*100))}</b><small>按平均单价 ${num(price)} 元/${esc(unit||'单位')}</small></span><span>领用后结存 <b>${num(stock-n)} ${esc(unit)}</b></span>`;}
function materialIssueRefreshPreview(){const f=$('#material-issue-form');if(!f)return;const box=f.querySelector('#material-issue-preview');if(box)box.innerHTML=materialIssuePreviewHtml(f.elements.material_id.value,f.elements.warehouse_id.value,f.elements.qty.value);}
function materialIssueQuickPicks(mid){const items=materialIssueItems();return `<div class="field wide"><span class="field-label">常用物料</span><div class="issue-quick">${MATERIAL_ISSUE_QUICK.map(id=>items.find(i=>i.id===id)).filter(Boolean).map(i=>`<button type="button" class="issue-quick-item ${i.id===mid?'active':''}" data-material-issue-pick="${esc(i.id)}">${esc(i.name)}</button>`).join('')}</div></div>`;}
function materialIssueProductChecks(){return `<div class="field wide"><span class="field-label">承担产品（可多选；不勾选＝保留共用待分摊）</span><div class="issue-products">${data.products.map(p=>`<label class="issue-product"><input type="checkbox" name="product_ids" value="${esc(p.id)}">${esc(p.name)}</label>`).join('')}</div><p class="help-text">勾选多个产品时，按覆盖期内各产品实际供浆用豆量分摊；只勾一个则直接归属该产品。石膏、消泡剂等共用辅料可同时勾选豆腐、豆干等产品。</p></div>`;}
function materialIssueFormCard(){
 const dates=materialIssueTodayStart(),mid=materialIssueMaterialValue(),wid=materialIssueWarehouseValue(mid);
 return resourcePanel('快速领用登记',`<form id="material-issue-form" class="material-issue-form" data-request-key="${erpRequestKey()}">
  <div class="form-grid">
   <label class="field">业务日期<input name="business_date" type="date" value="${esc(today())}" required></label>
   <label class="field">领用物料<select name="material_id" required>${materialIssueOptions(mid)}</select></label>
   <label class="field">领用库房<select name="warehouse_id">${resourceWarehouses().map(w=>`<option value="${esc(w.id)}" ${w.id===wid?'selected':''}>${esc(w.name)}</option>`).join('')}</select></label>
   <label class="field">数量<input name="qty" type="number" min="0.001" step="0.001" required placeholder="按物料计量单位"></label>
   <label class="field">覆盖开始<input name="coverage_start" type="date" value="${esc(dates.start)}" required></label>
   <label class="field">覆盖结束<input name="coverage_end" type="date" value="${esc(dates.end)}" required></label>
   ${materialIssueQuickPicks(mid)}
   ${materialIssueProductChecks()}
   <div class="field wide"><span class="field-label">本单预览</span><div id="material-issue-preview" class="issue-preview">${materialIssuePreviewHtml(mid,wid,'')}</div></div>
   <label class="field wide">用途 / 说明<input name="note" type="text" maxlength="120" value="生产领用" required></label>
  </div>
  <div class="form-actions"><button class="button primary" type="submit" data-material-issue-add>＋ 加入本单</button><span class="help-text">覆盖期须与业务日期在同一个月；跨月请分月登记。提交时整单一次写入并重新计价。</span></div>
 </form>`,'登记当天或最近几天的辅料、包装领用；常用物料可连续加入本单再一起提交。','material-issue-entry');
}
function materialIssueDraftCard(){
 if(!materialIssueDraft.length)return resourcePanel('本单待提交',`<p class="empty">还没有待提交的行。先在上方选择物料和承担产品，再加入本单。</p>`,'同一业务日期的一单多行一次提交。');
 const rows=materialIssueDraft.map((r,index)=>`<tr><td>${esc(materialIssueData().items.find(i=>i.id===r.material_id)?.name||r.material_id)}<small>${esc(r.warehouse_name||'')}</small></td><td>${num(r.qty)} ${esc(r.unit||'')}</td><td>${esc(materialIssueProductNames(r.product_ids)||'共用待分摊')}</td><td>${esc(r.coverage_start)}${r.coverage_start===r.coverage_end?'':' 至 '+esc(r.coverage_end)}</td><td>${esc(r.note||'')}</td><td><button class="text-button" data-material-issue-remove="${index}">移除</button></td></tr>`).join('');
 return resourcePanel('本单待提交',resourceTable(['物料 / 库房','数量','承担产品','覆盖期','说明','操作'],rows)+`<div class="form-actions"><button class="button primary" data-material-issue-submit ${canAction('materials.issue')?'':'disabled'}>提交本单（${materialIssueDraft.length} 行）</button><button class="button" data-material-issue-clear>清空</button><span class="help-text">提交人：${esc(resourceHandler())}</span></div>`,'整单一次提交，任一行失败则本单不保存。');
}
function materialIssueSummary(){
 const state=materialIssueReport(materialIssueMonthValue());
 if(!state.value)return readState('本月领用分摊',state.error);
 const r=state.value,products=r.products||[];
 return metrics([['本月领用',amount(r.total_cents||0),'元','不含大豆'],[`已分摊到产品`,amount(r.allocated_cents||0),'元',products.length?products.map(p=>p.product_name).join('、'):'暂无'],[`待分摊`,amount(r.unallocated_cents||0),'元',r.unallocated_cents?'未登记承担产品，保留共用成本':'已全部归属'],['领用笔数',(r.entries||[]).length,'笔','含退回与报损']]);
}
function materialIssueProductTable(){
 const state=materialIssueReport(materialIssueMonthValue());
 if(!state.value)return resourcePanel('按产品分摊',readState('按产品分摊',state.error));
 const rows=state.value.products||[];
 return resourcePanel('按产品分摊',resourceTable(['承担产品','分摊金额','占比'],rows.map(p=>`<tr><td>${esc(p.product_name)}</td><td>${amount(p.amount_cents)}</td><td>${state.value.allocated_cents?num(p.amount_cents*100/state.value.allocated_cents)+'%':'—'}</td></tr>`).join(''),'本月还没有登记承担产品的领用。')+`<p class="help-text">${esc(state.value.basis)}</p>`,'多产品领用按覆盖期实际供浆用豆量分摊，精确到分。','material-issue-split');
}
function materialIssueDetailTable(){
 const state=materialIssueReport(materialIssueMonthValue());
 if(!state.value)return resourcePanel('本月领用明细',readState('本月领用明细',state.error));
 const basis={direct:'直接归属产品','coverage-bean':'按覆盖期用豆量分摊','coverage-equal':'缺少用豆依据，按产品均分',unallocated:'未登记承担产品'};
 const rows=(state.value.entries||[]).map(e=>`<tr><td>${esc(e.business_date)}<small>${esc(e.entry_id)}</small></td><td>${esc(e.material_name||e.material_id)}</td><td>${amount(e.amount_cents)}</td><td>${esc(e.coverage_start)}${e.coverage_start===e.coverage_end?'':' 至 '+esc(e.coverage_end)}<small>${e.days} 天</small></td><td>${e.product_rows?.length?e.product_rows.map(p=>esc(p.product_name)+' '+amount(p.amount_cents)).join('<br>'):'<span class="badge orange">共用待分摊</span>'}</td><td>${esc(basis[e.basis]||e.basis)}</td></tr>`).join('');
 return resourcePanel('本月领用明细',resourceTable(['日期 / 单号','物料','金额','覆盖期','分摊去向','依据'],rows,`本月还没有辅料领用。`),'已作废流水不计入。','material-issue-detail');
}
function materialIssueRecentTable(){
 const month=materialIssueMonthValue(),rows=materialIssueData().entries.filter(e=>!e.voided&&e.business_date.startsWith(month)&&e.material_id!=='RM-SOY'&&['consume','return','loss'].includes(e.kind)).slice(-12).reverse();
 return resourcePanel('最近登记',resourceTable(['日期 / 单号','物料','数量','承担产品','操作'],rows.map(e=>`<tr><td>${esc(e.business_date)}<small>${esc(e.id)}</small></td><td>${esc(e.material_name)}</td><td>${num(Number(e.kind==='return'?-e.qty:e.qty))} ${esc(e.unit)}</td><td>${esc(materialIssueProductNames(e.product_ids)||e.cost_target||'共用待分摊')}</td><td>${canAction('materials.value')?`<button class="text-button" data-resource-act="attribute" data-id="${esc(e.id)}">更正归集</button>`:'只读'}</td></tr>`).join(''),'最近 12 笔领用、退回或报损。'));
}
function materialIssuePage(){
 if(!materialIssueDates.start)materialIssueResetDates();
 const actions='<button class="button" data-material-issue-refresh>重新读取</button>';
 return head('原辅料领用','按天登记辅料与包装领用；登记承担产品后，月末按覆盖期用豆量分到对应产品。',actions)+
  `<div class="sheet-filters"><label>统计月份<input type="month" id="material-issue-month" value="${esc(materialIssueMonthValue())}"></label><span class="help-text">领用只影响库存与成本；大豆仍在上豆与浆缸按每日供浆登记。</span></div>`+
  materialIssueSummary()+materialIssueFormCard()+materialIssueDraftCard()+materialIssueProductTable()+materialIssueDetailTable()+materialIssueRecentTable();
}
function materialIssueAddFromForm(form){
 if(!form.reportValidity())return;
 const f=new FormData(form),item=materialIssueData().items.find(i=>i.id===f.get('material_id'));
 const start=f.get('coverage_start'),end=f.get('coverage_end'),day=f.get('business_date');
 if(end<start){notify('覆盖结束日期不能早于开始日期');return;}
 if(start.slice(0,7)!==day.slice(0,7)||end.slice(0,7)!==day.slice(0,7)){notify('覆盖期须与业务日期在同一个月；跨月请分月登记');return;}
 const qty=Number(f.get('qty'));if(!(qty>0)){notify('请填写大于 0 的领用数量');return;}
 materialIssueDraft.push({material_id:f.get('material_id'),unit:item?.unit||'',warehouse_id:f.get('warehouse_id'),warehouse_name:resourceWarehouseName(f.get('warehouse_id')),qty,product_ids:[...form.querySelectorAll('[name=product_ids]:checked')].map(x=>x.value),coverage_start:start,coverage_end:end,note:String(f.get('note')||'').trim()||'生产领用'});
 form.elements.qty.value='';form.querySelectorAll('[name=product_ids]').forEach(x=>x.checked=false);
 render();notify('已加入本单，可继续登记下一行');
}
function materialIssueRemove(index){materialIssueDraft.splice(index,1);render();}
async function materialIssueSubmit(){
 if(!materialIssueDraft.length)return;
 if(!canAction('materials.issue')){err(Error('当前岗位没有原辅料领用权限'));return;}
 const form=$('#material-issue-form'),businessDate=form?.elements.business_date.value||today(),requestKey=form?.dataset.requestKey||erpRequestKey();
 const body={business_date:businessDate,handler:resourceHandler(),note:'原辅料领用登记',request_key:requestKey,revision:resourceData().revision,lines:materialIssueDraft.map(r=>({material_id:r.material_id,kind:'consume',qty:r.qty,warehouse_id:r.warehouse_id,product_ids:r.product_ids,coverage_start:r.coverage_start,coverage_end:r.coverage_end,note:r.note}))};
 await perform(async()=>{const result=await api('/api/resources/material-batch',body);materialIssueDraft=[];data=await api('/api/bootstrap');factoryReports.clear();render();notify('领用已登记 '+(result.count||body.lines.length)+' 行');});
}
document.addEventListener('change',e=>{
 if(e.target.id==='material-issue-month'){materialIssueMonth=e.target.value;render();return;}
 if(!e.target.closest('#material-issue-form'))return;
 if(e.target.name==='material_id'){const f=e.target.form,mid=e.target.value,row=(materialIssueData().warehouse_stocks||[]).find(r=>r.id===mid&&Number(r.qty)>0);if(row)f.elements.warehouse_id.value=row.warehouse_id;}
 if(['material_id','warehouse_id'].includes(e.target.name)){materialIssueRefreshPreview();materialIssueRemember();}
});
document.addEventListener('input',e=>{if(e.target.closest('#material-issue-form')&&e.target.name==='qty')materialIssueRefreshPreview();});
document.addEventListener('submit',e=>{const f=e.target.closest('#material-issue-form');if(!f)return;e.preventDefault();materialIssueAddFromForm(f);});
document.addEventListener('click',e=>{
 const pick=e.target.closest('[data-material-issue-pick]');
 if(pick){const f=$('#material-issue-form');if(f){const mid=pick.dataset.materialIssuePick;f.elements.material_id.value=mid;const row=(materialIssueData().warehouse_stocks||[]).find(r=>r.id===mid&&Number(r.qty)>0);if(row)f.elements.warehouse_id.value=row.warehouse_id;materialIssueRefreshPreview();materialIssueRemember();f.elements.qty.focus();}}
 if(e.target.closest('[data-material-issue-refresh]')){materialIssueMonth=materialIssueMonthValue();factoryReports.clear();render();}
 const remove=e.target.closest('[data-material-issue-remove]');if(remove)materialIssueRemove(Number(remove.dataset.materialIssueRemove));
 if(e.target.closest('[data-material-issue-clear]')){materialIssueDraft=[];render();}
 if(e.target.closest('[data-material-issue-submit]'))materialIssueSubmit().catch(err);
});
