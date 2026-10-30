'use strict';
// 车间余料：月末盘点车间剩余辅料，按「期初 + 本月领用 − 期末盘点 = 本月实耗」结转成本。
let workshopMonth='';
const workshopCache=new Map();
function workshopMonthValue(){return workshopMonth||today().slice(0,7);}
function workshopReport(month){
  const key='workshop|'+month,state=workshopCache.get(key);
  if(state)return state;
  const next={loading:true};workshopCache.set(key,next);
  api('/api/workshop?month='+encodeURIComponent(month)).then(value=>{workshopCache.set(key,{value});if(page==='workshop')render();}).catch(error=>{workshopCache.set(key,{error:error.message});if(page==='workshop')render();});
  return next;
}
function workshopSummary(r){
  return metrics([['本月领用',amount(r.total_issue_cents||0),'元','车间已领出'],['本月实耗',amount(r.total_actual_cents||0),'元','期初 + 领用 − 盘点'],['已盘点物料',(r.counted||0)+' / '+((r.counted||0)+(r.unclosed||0)),'项',r.unclosed?'未盘点按领用全额计入':'全部已盘点'],['待摊差额',amount((r.total_actual_cents||0)-(r.total_issue_cents||0)),'元','实耗与领用的差额']]);
}
function workshopTable(r){
  if(!(r.rows||[]).length)return resourcePanel('物料盘点',`<p class="empty">本月还没有辅料领用，无需盘点。</p>`);
  const rows=r.rows.map(row=>`<tr>
    <td>${esc(row.material_name)}<small>${esc(row.unit)}</small></td>
    <td><input type="number" min="0" step="0.001" class="workshop-qty" data-workshop-material="${esc(row.material_id)}" data-workshop-version="${row.version}" value="${row.counted?esc(row.qty_close):''}" placeholder="盘点数量"></td>
    <td>${num(row.qty_open)} ${esc(row.unit)}<small>${amount(row.opening_cents)}</small></td>
    <td>${num(row.qty_in)} ${esc(row.unit)}<small>${amount(row.issue_cents)}</small></td>
    <td>${row.counted?num((Number(row.qty_open)+Number(row.qty_in)-Number(row.qty_close)).toFixed(3)):''} ${esc(row.unit)}<small>${row.counted?amount(row.actual_cents):'待盘点'}</small></td>
    <td><input type="text" maxlength="60" class="workshop-note" data-workshop-note="${esc(row.material_id)}" value="${esc(row.note||'')}" placeholder="可选"></td>
    <td>${row.counted?`<span class="badge ${row.over_issue?'orange':'green'}">${row.over_issue?'盘盈待核':'已盘点'}</span>`:'<span class="badge orange">未盘点</span>'}${canAction('materials.issue')||canAction('materials.value')?`<button class="text-button" data-workshop-save="${esc(row.material_id)}">保存</button>`:''}</td>
  </tr>`).join('');
  return resourcePanel('物料盘点',resourceTable(['物料','期末盘点','期初余料','本月领用','本月实耗','说明','状态 / 操作'],rows),'未盘点物料仍按领用全额计入；上月盘点自动转下月期初。')+
    `<p class="help-text issue-split-note">实耗金额按本月 FIFO 领用均价折算；未盘点物料仍按领用全额计入成本。上月盘点数自动转为下月期初，首月按 0 起算会给出提示。</p>`;
}
function workshopPage(){
  const month=workshopMonthValue(),state=workshopReport(month);
  const actions='<button class="button" data-workshop-refresh>重新读取</button>';
  const body=state.value?workshopSummary(state.value)+workshopTable(state.value):readState('车间余料盘点',state.error);
  return head('车间余料','月末盘点车间剩余辅料；按「期初 + 本月领用 − 期末盘点」结转本月实耗成本。',actions)+
    `<div class="sheet-filters"><label>盘点月份<input type="month" id="workshop-month" value="${esc(month)}"></label><span class="help-text">只盘点辅料、耗材与包装；大豆在磨浆系统按日登记上豆与浆缸。</span></div>`+body;
}
async function workshopSave(mid){
  if(!canAction('materials.issue')&&!canAction('materials.value')){notify('当前岗位没有车间盘点权限');return;}
  const qty=document.querySelector(`[data-workshop-material="${mid}"]`),note=document.querySelector(`[data-workshop-note="${mid}"]`);
  if(!qty)return;
  const body={request_key:erpRequestKey(),month:workshopMonthValue(),material_id:mid,qty_close:qty.value,note:note?.value||'',version:qty.dataset.workshopVersion||0};
  await perform(async()=>{await api('/api/resources/workshop-count',body);workshopCache.clear();render();notify('车间余料盘点已保存');});
}
document.addEventListener('change',e=>{if(e.target.id==='workshop-month'){workshopMonth=e.target.value;render();}});
document.addEventListener('click',e=>{
  if(e.target.closest('[data-workshop-refresh]')){workshopMonth=workshopMonthValue();workshopCache.clear();render();return;}
  const save=e.target.closest('[data-workshop-save]');if(save)workshopSave(save.dataset.workshopSave).catch(err);
});
