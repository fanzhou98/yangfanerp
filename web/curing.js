'use strict';
// 熏制登记：只登记投入的白干（筐/公斤），不登记黄干产出；扣白干库存并按白干出品率折豆。
function curingRows(){return (typeof data!=='undefined'&&data?.curing)||[];}
function curingSourceOptions(){
  const options=curingRows().length?'':'';return '';
}
let curingDate='';
function curingPage(){
  const todayValue=selectedDate||today();
  const dateValue=curingDate||todayValue;
  const rows=curingRows().filter(r=>!r.voided).slice().sort((a,b)=>String(b.business_date).localeCompare(String(a.business_date)));
  const body=rows.length?rows.map(r=>`<tr>
    <td>${esc(r.business_date)}</td>
    <td>${esc(r.source_product_name)}<small>${num(r.qty)} ${esc(r.source_unit)} · ${num(r.net_kg)} 公斤</small></td>
    <td>${esc(r.target_product_name)}<small>${esc(r.target_product_unit||'')}</small></td>
    <td>${num(r.yield_rate)}<small>${esc(r.yield_source_date?'取 '+r.yield_source_date:'手工填写')}</small></td>
    <td class="amount">${num(r.beans_kg)} 公斤</td>
    <td style="text-align:left">${esc(r.note||'')}</td>
    <td><div class="table-action"><span class="badge ${r.voided?'orange':'green'}">${r.voided?'已作废':'已登记'}</span>${canAction('production.curing.write')?`<button class="text-button" data-curing-void="${esc(r.id)}">作废</button>`:''}</div></td>
  </tr>`).join(''):'<tr><td colspan="7" class="empty">还没有熏制登记。用白干熏制黄干时在上方登记投入量即可。</td></tr>';
  const form=canAction('production.curing.write')?`<form id="curing-form" class="panel">
    <div class="panel-head"><div><h2>登记熏制投入</h2><p>只填投入的白干，不填黄干产出：黄干产量仍由盘库和发货推算</p></div></div>
    <div class="form-grid" style="padding:0 22px 18px">
      <label class="field">业务日期<input type="date" name="business_date" value="${esc(dateValue)}" required></label>
      <label class="field">来源白干<select name="source_product_id" id="curing-source" required>
        <option value="">请选择</option>
        <option value="P011">白干（框）· 按筐</option>
        <option value="P005">白干 · 按公斤</option>
      </select><small>公斤来源按投入净重扣减；筐装按件数扣减</small></label>
      <label class="field">投入件数 / 公斤<input type="number" name="qty" min="0" step="0.001" placeholder="0" required></label>
      <label class="field">出品率<input type="number" name="yield_rate" min="0" step="0.001" placeholder="自动"><small>留空取最近一天</small></label>
      <label class="field wide">备注<input type="text" name="note" maxlength="200" placeholder="例如：昨天剩的白干 3 筐"></label>
    </div>
    <p class="help-text" style="padding:0 22px 12px;margin:0">保存后自动扣白干库存，并按白干最后一天的出品率折豆计入当日黄干用豆；找不到历史出品率时需手工填写。</p>
    <div class="dialog-actions"><button type="submit" class="button primary">保存熏制登记</button></div>
  </form>`:'';
  return form+resourcePanel('熏制登记台账',resourceTable(['日期','投入白干','计入产品','出品率','折豆','备注','状态'],body),'折豆＝投入重量 ÷ 白干出品率；黄干出品率＝黄干产量 ÷（黄干浆缸投豆＋熏制折豆）。');
}
document.addEventListener('submit',event=>{
  const form=event.target.closest('#curing-form');
  if(!form)return;
  event.preventDefault();
  const values=Object.fromEntries(new FormData(form).entries());
  curingDate=values.business_date||curingDate;
  if(!values.source_product_id){notify('请选择来源白干');return;}
  submit('/api/curing',{...values,action:'save'},result=>`已登记 ${result.record?.id||''}`);
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-curing-void]');
  if(!button)return;
  if(!confirm('作废这条熏制登记？作废后白干库存与折豆会一起回退。'))return;
  submit('/api/curing',{id:button.dataset.curingVoid,action:'void'},'已作废');
});
