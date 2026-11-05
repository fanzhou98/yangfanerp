'use strict';
let ownerReportTab='overview';
function ownerNumber(v,suffix=''){return v===null||v===undefined||v===''?'待补数据':num(v)+esc(suffix);}
function ownerDashboard(){
 const day=selectedDate||today(),state=factoryReport('owner',day),top=head('老板经营日报','从变化找到原因，再核对到客户、产品和原始记录。',homeDateControls(day,false));if(!state.value)return top+readState('老板经营日报',state.error);
 const v=state.value,c=v.cost,a=v.accounts,s=v.summary;
 const tabs=`<div class="report-view-tabs" role="tablist" aria-label="经营分析视角">${[['overview','经营总览'],['production','生产与质量'],['accounts','账款与资金安排']].map(([key,label])=>`<button type="button" role="tab" aria-selected="${ownerReportTab===key}" data-owner-report-tab="${key}" class="${ownerReportTab===key?'is-selected':''}">${label}</button>`).join('')}</div>`;
 const costGaps=(c.missing_data||[]).length;const facts=reportFacts([['当日已复核发货',s.reviewed_orders?amount(v.sales_cents):'待补 / 无单据',s.pending_orders+' 笔待复核'],['成本依据',costGaps?costGaps+' 项待补':'已登记',costGaps?'成本未齐，不认定盈利':'仅列已登记成本'],['应收当前余额',amount(a.receivable_cents),'销售与豆渣'],['大豆库存',num(s.soy_kg)+' 公斤',day+' 业务日余额']]);
 let body='';
 if(ownerReportTab==='overview'){
  body=`<div class="report-reading-guide"><p><b>发货趋势与客户分析在销售报表统一查看。</b><span>下方仅核对 ${esc(day)} 当日收入与已登记成本，不认定净利润。</span></p>${reportSalesLink(day.slice(0,7))}</div>`+reportChart(c.bridge);
 }else if(ownerReportTab==='production'){
  body=`<div id="owner-production"><div class="report-reading-guide"><p><b>品种构成与出品率已归位到生产日报。</b><span>实到 / 排班 ${s.actual_people} / ${s.planned_people} 人；${v.previous_day?esc(v.previous_day)+' 为比较基期':'本期没有上次生产记录，不画对比'}。</span></p><button type="button" class="button" data-page="production-report">查看生产日报图表 →</button></div><details class="report-disclosure"><summary>产量、净重与出品率 · 查看产品依据</summary>${resourceTable(['产品','推算产量（原单位）','已复核结算公斤','生产日出品率 kg/kg','同口径变化','依据 / 负责岗位'],v.products.map(p=>`<tr><td>${esc(p.product_name)}</td><td>${ownerNumber(p.derived_qty,' '+p.unit)}</td><td>${ownerNumber(p.settlement_kg,' kg')}<small>${esc(p.settlement_basis)}</small></td><td>${ownerNumber(p.settlement_yield)}</td><td>${p.change_pct==null?'无可比数据':num(p.change_pct)+'%'+(p.change_alert?' · 需核对':'')}</td><td class="long-note">${p.missing_data?.length?p.missing_data.map(m=>esc(m.field)+'：'+esc(m.owner)).join('<br>'):esc(p.calculation_status||'估算')}</td></tr>`).join(''))}</details><details class="report-disclosure"><summary>库房质量与检测覆盖 · 查看批次依据</summary>${resourceTable(['库房','剩余公斤','播种类型 / 余量','加权蛋白 %','加权水分 %','检测覆盖'],v.soy.map(w=>`<tr><td>${esc(w.warehouse_name)}</td><td>${num(w.qty)}</td><td class="long-note">${Object.entries(w.sowing||{}).filter(([,q])=>Number(q)>0).map(([name,q])=>esc(name)+' '+num(q)).join('<br>')||'无库存'}</td><td>${ownerNumber(w.average_protein)}</td><td>${ownerNumber(w.average_moisture)}</td><td>蛋白 ${num(w.protein_coverage_pct)}%<small>水分 ${num(w.moisture_coverage_pct)}%</small></td></tr>`).join(''))}</details><details class="report-disclosure"><summary>排班与实际考勤 · 查看人员</summary>${resourceTable(['员工 / 小组','计划','实际'],v.people.rows.map(p=>`<tr><td>${esc(p.employee_name)}<small>${esc(p.group_name)}</small></td><td>${esc(statusLabel(p.planned_status||'unrecorded'))}<small>${esc(p.planned_start||'时间待登记')}</small></td><td>${esc(statusLabel(p.actual_status||'unrecorded'))}<small>${esc(p.actual_start||'时间待登记')}</small></td></tr>`).join(''))}</details></div>`;
 }else{
  body=`<div id="owner-accounts">${reportFacts([['应付当前余额',amount(a.payable_cents),'采购、工资及已核对费用'],['有账期的逾期应付',amount(a.overdue_payable_cents),'无约定付款日不认定逾期'],['费用待核对',amount(a.expense_pending_cents||0),'未计入已确认应付']])}<p class="report-basis">${esc(a.basis)}</p><h2 class="report-detail-title">应付到期明细</h2>${resourceTable(['收款方','到期日','未付余额','状态'],a.payables.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.due_date||'未登记')}</td><td>${amount(r.cents)}</td><td>${r.overdue===null?'账期待核定':r.overdue?'已逾期':'未逾期'}</td></tr>`).join(''))}<h2 class="report-detail-title">应收催收明细</h2>${resourceTable(['客户','当前未收','最早业务日','最长账龄'],a.receivables.map(r=>`<tr><td>${esc(r.customer_name)}</td><td>${amount(r.outstanding_cents)}</td><td>${esc(r.oldest_date)}</td><td>${r.days} 天</td></tr>`).join(''))}<p class="report-basis">账龄预警不等于合同逾期；客户合同账期尚未登记。</p></div>`;
 }
 return top+`<article class="report-workbench">${reportContext(v.report_context)}${facts}${reportGaps(c.missing_data)}${tabs}${body}</article>`;
}
document.addEventListener('click',e=>{const tab=e.target.closest('[data-owner-report-tab]');if(tab){ownerReportTab=tab.dataset.ownerReportTab;render();}});
async function openProductProfit(){
 const month=(selectedDate||today()).slice(0,7);
 try{const r=await api('/api/product-profit?month='+encodeURIComponent(month));
 const rows=r.rows.map(x=>`<tr><td>${esc(x.product_name)}<small>${reportValue(x.qty_kg,'','公斤')}</small></td><td>${amount(x.revenue_cents)}</td><td>${amount(x.direct_cents)}</td><td>${amount(x.gross_cents)}<small>${x.gross_margin!=null?num(Number(x.gross_margin)*100)+'%':''}</small></td><td>${amount(x.indirect_cents)}</td><td>${reportValue(x.net_cents,'cents')}<small>${x.net_margin!=null?num(Number(x.net_margin)*100)+'%':''}</small></td><td>${x.break_even_price!=null?num(Number(x.break_even_price)/100)+' 元/公斤':'—'}</td></tr>`).join('');
 openDialog('月度产品经营测算 · '+month,`<p class="help-text">${esc(r.basis)}</p>`+resourceTable(['产品','营收','直接成本','毛利润','间接成本','净利润','保本价（元/公斤）'],rows)+`<p>合计：营收 ${amount(r.total.revenue_cents)} · 直接 ${amount(r.total.direct_cents)} · 毛利润 ${amount(r.total.gross_cents)} · 间接 ${amount(r.total.indirect_cents)} · 净利润 ${reportValue(r.total.net_cents,'cents')}</p>`,'经营测算','<button class="button" data-act="close">关闭</button>');
 }catch(e){err(e);}
}
document.addEventListener('click',e=>{if(e.target.closest('[data-product-profit]'))openProductProfit();});

let productProfitMonth='';
const productProfitCache=new Map();
function refreshProductProfitPanel(){
 if(['product-profit','analytics'].includes(page))render();
}
function productProfitPanel(integratedMonth=''){
 const month=integratedMonth||productProfitMonth||today().slice(0,7);
 let r=productProfitCache.get(month);
 if(!r){r={loading:true};productProfitCache.set(month,r);api('/api/product-profit?month='+encodeURIComponent(month)).then(v=>{productProfitCache.set(month,{value:v});refreshProductProfitPanel();}).catch(e=>{productProfitCache.set(month,{error:e.message});refreshProductProfitPanel();});}
 const bar=integratedMonth?'':'<div class="sheet-filters"><label>统计月份<input id="profit-month" type="month" value="'+esc(month)+'"></label></div>';
 if(r.loading)return bar+'<p class="help-text">正在计算…</p>';
 if(r.error)return bar+`<p class="callout">${esc(r.error)}</p>`;
 const v=r.value,t=v.total;
 const rows=v.rows.map(x=>`<tr><td>${esc(x.product_name)}<small>${reportValue(x.qty_kg,'','公斤')} · ${x.orders} 单</small><small>系数 ${num(x.processing_intensity??1)} · 加权 ${x.allocation_weight==null?'待核对':num(x.allocation_weight)}</small></td><td>${amount(x.revenue_cents)}</td><td>${(x.missing_data||[]).some(reason=>reason.includes('来源大豆'))?'待核对':amount(x.soy_cost_cents)}<small>用豆 ${num(x.soy_kg)} 公斤</small></td><td>${amount((x.direct_material_cents||0)+(x.scope_material_cents||0)+(x.amortized_cents||0))}</td><td>${amount(x.direct_cents)}</td><td>${amount(x.gross_cents)}<small>${x.gross_margin!=null?num(Number(x.gross_margin)*100)+'%':''}</small></td><td>${amount(x.indirect_cents)}</td><td>${reportValue(x.net_cents,'cents')}<small>${x.net_margin!=null?num(Number(x.net_margin)*100)+'%':''}</small></td><td>${x.break_even_price!=null?num(Number(x.break_even_price)/100):'待核对'}<small>${(x.missing_data||[]).map(esc).join('；')}</small></td></tr>`).join('')||'<tr><td colspan="9" class="empty">本月还没有已复核订单</td></tr>';
 const st=v.statement;
 const statement=st?('<div class="panel"><table class="data-table statement-table"><tbody>'+
  '<tr><th>营业收入（已复核发货减退货折让）</th><td>'+amount(st.revenue_cents)+'</td></tr>'+
  '<tr><th>直接成本（已分摊：材料、加工、配送、外购）</th><td>'+amount(st.direct_cents)+'</td></tr>'+
  '<tr><th>期间费用（已分摊）</th><td>'+amount(st.period_cents)+'</td></tr>'+
  '<tr><th>净利润（收入−直接成本−期间费用）</th><td>'+(st.gross_cents==null?'<span class="muted">缺项未归集，留空</span>':amount(st.gross_cents)+(st.gross_margin==null?'':' · '+(st.gross_margin*100).toFixed(1)+'%'))+'</td></tr>'+
  '<tr><th>未分摊费用</th><td>'+amount(st.pending_expense_cents)+'</td></tr>'+
  '<tr><th>月报口径成本（全口径）</th><td>'+amount(st.management_cost_cents)+'</td></tr>'+
  '<tr><th>与产品测算口径差额（未分摊部分）</th><td>'+amount(st.caliber_difference_cents)+'</td></tr>'+
  '</tbody></table><p class="help-text">'+esc(st.basis)+' '+(st.cost_caliber?esc(st.cost_caliber):'')+'</p></div>'):'';
 const inv=v.inventory&&v.inventory.rows&&v.inventory.rows.length?v.inventory:null;
 const money=x=>x==null?'<span class="muted">未估值</span>':amount(x);
 const qty=(x,unit)=>num(x)+' '+esc(unit||'');
 const inventory=inv?('<div class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>产品</th><th>期初库存</th><th>本月生产</th><th>本月发出</th><th>期末库存</th><th>单位成本</th></tr></thead><tbody>'+
  inv.rows.map(x=>'<tr><td>'+esc(x.product_name)+'</td>'+
   '<td>'+qty(x.opening_qty,x.unit)+'<small>'+money(x.opening_cents)+'</small></td>'+
   '<td>'+qty(x.produced_qty,x.unit)+'<small>'+money(x.produced_cents)+'</small></td>'+
   '<td>'+qty(x.issued_qty,x.unit)+'<small>'+money(x.issued_cents)+'</small></td>'+
   '<td>'+qty(x.ending_qty,x.unit)+'<small>'+money(x.ending_cents)+'</small></td>'+
   '<td>'+(x.unit_cost==null?'<span class="muted">待核对</span>':num(Number(x.unit_cost)/100)+' 元/'+esc(x.unit||'单位'))+'</td></tr>').join('')+
  '</tbody></table></div><p class="help-text">'+esc(inv.basis||'')+'</p></div>'):'';
 return bar+reportContext(v.report_context||{title:'产品经营测算',start:month,basis:v.basis})+statement+inventory+reportGaps(v.gaps||[])+reportFacts([['本月营收',amount(t.revenue_cents),'已复核订单'],['直接成本',amount(t.direct_cents),'大豆、辅料及外购'],['产品净利润',reportValue(t.net_cents,'cents'),'仅含已分摊成本；成本未齐时可能偏高']])+resourcePanel('按产品盈亏',resourceTable(['产品 / 结算公斤','营收','大豆成本','辅料归集','直接成本','毛利润','分摊费用','净利润','保本价（元/公斤）'],rows),v.basis)+(v.material_allocations&&v.material_allocations.length?'<details class="report-disclosure"><summary>辅料领用分摊依据 · 逐笔</summary>'+resourceTable(['业务日期','物料','覆盖期','金额','分摊去向'],v.material_allocations.map(m=>'<tr><td>'+esc(m.business_date)+'</td><td>'+esc(m.material_name||m.material_id)+'</td><td>'+esc(m.coverage_start)+(m.coverage_start===m.coverage_end?'':' 至 '+esc(m.coverage_end))+'</td><td>'+amount(m.amount_cents)+'</td><td>'+Object.entries(m.allocations||{}).map(([pid,c])=>esc(((v.rows||[]).find(r=>r.product_id===pid)||{}).product_name||pid)+' '+amount(c)).join('<br>')+'</td></tr>').join(''))+'</details>':'')+(typeof costAllocationDetails==='function'?costAllocationDetails(v):'')+(typeof costTransferDetails==='function'?costTransferDetails(v):'');
}
function productProfitPage(){return head('月度产品经营测算','按产品看当月收入、直接成本、分摊费用与毛利润、净利润。','','REPORTS · 月度报表')+productProfitPanel();}
document.addEventListener('change',e=>{if(e.target.id==='profit-month'){productProfitMonth=e.target.value;render();}});
