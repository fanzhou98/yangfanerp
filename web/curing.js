'use strict';
// 熏制登记：只登记投入的白干（框），不登记黄干产出；按件扣白干（框）库存，按白干出品率折豆。
function curingRows(){return (typeof data!=='undefined'&&data?.curing)||[];}
// 熏制只取白干（框）：优先“白干（框）”筐装产品；演示库缺这一项时退到第一个筐装白干类产品。
function curingSource(){
  const products=(typeof data!=='undefined'&&data?.products)||[];
  const boxed=products.filter(p=>String(p.unit)==='筐'&&/(白干|白豆干)/.test(String(p.name)));
  return boxed.find(p=>/白干（框）|白干\(框\)/.test(String(p.name)))||boxed[0]||null;
}
let curingDate='';
function curingPage(){
  const todayValue=selectedDate||today();
  const dateValue=curingDate||todayValue;
  const src=curingSource();
  const tare=src&&src.tare!==''&&src.tare!=null?num(src.tare):'1';
  const rows=curingRows().filter(r=>!r.voided).slice().sort((a,b)=>String(b.business_date).localeCompare(String(a.business_date)));
  const totalCents=rows.reduce((n,r)=>n+(r.material_cost_cents==null?0:Number(r.material_cost_cents)),0);
  const unpriced=rows.filter(r=>r.material_cost_cents==null).length;
  const body=rows.length?rows.map(r=>`<tr>
    <td>${esc(r.business_date)}</td>
    <td>${esc(r.source_product_name)}<small>${num(r.qty)} ${esc(r.source_unit)}${r.gross_kg?` · 毛重 ${num(r.gross_kg)} 公斤`:''} · 净 ${num(r.net_kg)} 公斤</small></td>
    <td>${esc(r.target_product_name)}<small>${esc(r.target_product_unit||'')}</small></td>
    <td>${num(r.yield_rate)}<small>${esc(r.yield_source_date?'取 '+r.yield_source_date:'手工填写')}</small></td>
    <td class="amount">${num(r.beans_kg)} 公斤</td>
    <td>${r.source_unit_cost==null?'—':amount(Number(r.source_unit_cost))}</td>
    <td class="amount">${r.material_cost_cents==null?'<span class="badge orange">待计价</span>':amount(r.material_cost_cents)}</td>
    <td data-align="left">${esc(r.note||'')}</td>
    <td><div class="table-action"><span class="badge ${r.voided?'orange':'green'}">${r.voided?'已作废':'已登记'}</span>${canAction('production.curing.write')?`<button class="text-button" data-curing-void="${esc(r.id)}">作废</button>`:''}</div></td>
  </tr>`).join(''):'<tr><td colspan="9" class="empty">还没有熏制登记。用白干熏制黄干时在上方登记投入量即可。</td></tr>';
  const form=canAction('production.curing.write')?`<form id="curing-form" class="panel">
    <div class="panel-head"><div><h2>登记熏制投入 <span class="badge orange">只算昨天结存的白干</span></h2><p>本模块只登记「昨天结存的白干（框）投入熏制」这一种情形；当天新产白干直接熏制黄干的，请在「生产日报 → 各产品浆缸数」按黄干类浆缸登记，不在这里填。黄干产量仍由盘库和发货推算。</p></div></div>
    <div class="form-grid panel-form">
      <input type="hidden" name="source_product_id" value="${esc(src?src.id:'')}">
      <label class="field">业务日期<input type="date" name="business_date" value="${esc(dateValue)}" required></label>
      <label class="field">来源白干<div class="field-static">${esc(src?src.name:'未找到白干（框）产品')}${src?` · 按${esc(src.unit)}`:''}</div><small>熏制只用白干（框），按件扣库存</small></label>
      <label class="field">投入件数<input type="number" name="pieces" min="1" step="1" placeholder="0" required><small>必填，皮重 ${tare} 公斤/件</small></label>
      <label class="field">毛重（可选）<input type="number" name="gross_kg" min="0" step="0.001" placeholder="有准确毛重就填"><small>填了按毛重－皮重合计算净重</small></label>
      <label class="field">出品率<input type="number" name="yield_rate" min="0" step="0.001" placeholder="自动"><small>留空取最近一天</small></label>
      <label class="field wide">备注<input type="text" name="note" maxlength="200" placeholder="例如：昨天剩的白干 3 筐"></label>
    </div>
    <p class="help-text panel-form-note"><strong>不要在这里登记当天新产的浆缸白干：</strong>已按黄干类浆缸登记折豆的白干，再进本模块会重复折豆；本模块只处理昨天结存、未计入当日浆缸的那部分白干。保存后按件扣白干（框）库存；净重优先用毛重扣皮重，未填毛重按每件净重估算；折豆＝净重 ÷ 白干出品率，计入当日黄干用豆。找不到历史出品率时需手工填写。</p>
    <div class="dialog-actions"><button type="submit" class="button primary">保存熏制登记</button></div>
  </form>`:'';
  return form+resourcePanel('熏制登记台账',resourceTable(['日期','投入白干','计入产品','出品率','折豆','白干单价','材料成本','备注','状态'],body),`折豆＝净重 ÷ 白干出品率；材料成本＝投入白干（框）件数 × 白干（框）结存单价（移动加权）；本月材料成本合计 ${amount(totalCents)}${unpriced?`，另有 ${unpriced} 笔待计价`:''}。作废登记后金额同步退出合计。`);
}
document.addEventListener('submit',event=>{
  const form=event.target.closest('#curing-form');
  if(!form)return;
  event.preventDefault();
  const values=Object.fromEntries(new FormData(form).entries());
  curingDate=values.business_date||curingDate;
  if(!values.source_product_id){notify('没有找到白干（框）产品，无法登记熏制投入');return;}
  submit('/api/curing',{...values,action:'save'},result=>`已登记 ${result.record?.id||''}`);
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-curing-void]');
  if(button){
    openDialog('作废熏制登记',`<form id="curing-void-form" data-id="${esc(button.dataset.curingVoid)}"><label class="field">作废原因<textarea name="reason" required maxlength="500" placeholder="例如：重复登记、日期选错"></textarea></label></form>`,'作废后白干库存与折豆会一起回退','<button class="button" data-act="close">取消</button><button class="button danger" data-curing-void-save>确认作废</button>');
    return;
  }
  const save=event.target.closest('[data-curing-void-save]');
  if(!save)return;
  const form=document.getElementById('curing-void-form');
  if(!form||!form.reportValidity())return;
  submit('/api/curing',{id:form.dataset.id,action:'void',reason:form.elements.reason.value.trim()},'已作废');
});
