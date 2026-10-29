'use strict';
function byproductCustomersPanel(){
 const rows=byproductCustomers(),{map,state}=byproductCustomerStats(resourceMonth());
 if(!state.value)return resourcePanel('豆渣客户档案',state.error?`<p class="callout warning">读取失败：${esc(state.error)}</p>`:'<p class="empty" role="status">正在读取豆渣销售汇总…</p>','客户档案与基础资料共用编号。月度结算和手工销售均关联客户；累计未收包含所有月份。');
 return resourcePanel('豆渣客户档案',resourceTable(['客户编号','客户名称 / 结算名称','联系电话','本月销售','累计未收','操作'],rows.map(c=>{
  const stats=map.get(c.id)||{};
  return `<tr><td>${esc(c.id)}</td><td>${esc(c.name)}<small>${esc(c.legal_name||c.name)}</small></td><td>${esc(c.phone||'—')}</td><td>${amount(stats.month_cents||0)}</td><td>${amount(stats.outstanding_cents||0)}</td><td><div class="table-action">${canAction('master.customers.write')?`<button class="text-button" data-byproduct-customer-edit="${esc(c.id)}">编辑客户</button>`:''}<button class="text-button" data-byproduct-statement data-cid="${esc(c.id)}" data-month="${esc(resourceMonth())}">结算单</button><button class="text-button" data-byproduct-receivable="${esc(c.id)}">查看应收</button></div></td></tr>`;
 }).join(''),'暂无豆渣客户，请先新增客户档案。'),'客户档案与基础资料共用编号；本月销售与累计未收由服务端按有效记录汇总，不含已作废销售。');
}

function byproductStatementItems(s){
 const items=[],text=(value,type='text')=>items.push({type,text:value}),money=v=>(Number(v||0)/100).toFixed(2);
 const table=(headers,widths,rows)=>{items.push({type:'table-head',cells:headers,widths});for(const cells of rows)items.push({type:'row',cells,widths});};
 items.push(...companyStatementItems(s));text('本月豆渣明细','section');
 if(s.details.length)table(['日期','产品名称','结算数量','单位','单价（元）','金额（元）','说明'],[170,180,140,90,140,140,220],s.details.map(r=>[r.date,r.product_name||'豆渣',r.qty??'—',r.unit,r.price??'—',money(r.amount_cents),r.status||'已入账']));
 else text('所选月份无已入账豆渣销售。');
 if(s.history.length){text('历史未收账款','section');table(['日期','收入单号','销售金额','累计已收','尚欠（元）'],[180,330,190,190,190],s.history.map(r=>[r.business_date,r.id,money(r.amount_cents),money(r.received_cents),money(r.outstanding_cents)]));}
 const t=s.totals;text('结算汇总','section');table(['本月货款','本月账款已收','本月未收','历史未收'],[270,270,270,270],[[money(t.current_sales_cents),money(t.current_paid_cents),money(t.current_remaining_cents),money(t.history_remaining_cents)]]);
 text('尚欠金额：¥ '+money(t.payable_cents),'total-alert');text('大写：'+statementRmbUpper(t.payable_cents),'note');text(s.balance_basis,'note');
 text('无已入账记录的日期仅补齐日期展示，不补算销售数量或金额。','note');
 if(s.note)text('备注：'+s.note,'note');
 text('请核对以上数量、单价、金额及已收款，无误请回复“对”；有异议请于收到后 3 日内提出，逾期视为确认。','note');
 return items;
}

let byproductStatementState=null,byproductStatementSequence=0;
async function openByproductStatement(cid='',month=resourceMonth()){
 const allowed=!data.auth_user||['finance.byproducts','finance.receivables','workspace.analytics'].some(m=>data.permissions?.modules?.includes(m));
 if(!allowed){notify('当前账号无豆渣账款查看权限');return;}
 const clients=data.customers.filter(c=>['byproduct','both'].includes(c.business_kind));
 const value=clients.some(c=>c.id===cid)?cid:'';
 byproductStatementState=null;++byproductStatementSequence;
 openDialog('豆渣客户结算单',`<form id="byproduct-statement-form"><div class="sheet-filters"><label>客户<select id="byproduct-statement-customer" name="customer_id" required><option value="">请选择客户</option>${clients.map(c=>`<option value="${esc(c.id)}" ${c.id===value?'selected':''}>${esc(c.id)} · ${esc(c.name)}</option>`).join('')}</select></label><label>结算期间（按月）<input id="byproduct-statement-month" type="month" name="month" required value="${esc(month)}"></label><button type="button" class="button" data-byproduct-statement-refresh>读取最新账款</button></div><div class="callout"><span id="byproduct-statement-period"></span>仅含已入账豆渣货款，历史未收单独列示。核对后出具并归档，可下载图片、导出表格或复制对账文字；出具不代表已收款或客户已确认。</div><fieldset id="byproduct-statement-fields" class="statement-parties"><div class="form-grid"><label class="field">供货方正式名称<input id="statement-seller" name="seller_name" required maxlength="120"></label><label class="field">供货方联系电话<input id="statement-phone" name="seller_phone" maxlength="40"></label><label class="field">客户结算名称<input id="statement-buyer" name="buyer_name" required maxlength="120"></label><label class="field">经办人<select id="statement-operator" name="operator_user_id" required>${statementOperatorOptions()}</select></label><label class="field wide">结算单备注<textarea name="note" maxlength="500" rows="2"></textarea></label></div><label class="check-line"><input type="checkbox" name="identity_checked" required>已核对客户、月份、数量、金额和已收款，确认出具</label></fieldset></form><label class="field">已归档结算单<select id="byproduct-statement-archive"><option value="">选择原始出具版本</option></select></label><div id="statement-image-preview"></div>`,'豆渣结算与客户对账','<button class="button" data-act="close">关闭</button><button class="button primary" id="byproduct-statement-issue" data-byproduct-statement-issue disabled>出具并归档</button>');
 await loadByproductStatement(true);
}
async function loadByproductStatement(initial=false){
 if(busy||!$('#byproduct-statement-form'))return;
 const seq=++byproductStatementSequence,cid=$('#byproduct-statement-customer').value,month=$('#byproduct-statement-month').value;
 byproductStatementState=null;statementShownDocument='';statementImages=[];$('#byproduct-statement-issue').disabled=true;$('#byproduct-statement-fields').disabled=false;
 if(!cid||!month){$('#statement-image-preview').textContent='请选择客户和结算月份。';return;}
 $('#statement-image-preview').textContent='正在读取豆渣账款…';
 try{
  const s=await api('/api/byproduct-statement?'+new URLSearchParams({customer_id:cid,month})),docs=await api('/api/byproduct-documents?'+new URLSearchParams({customer_id:cid}));
  await document.fonts.ready;
  if(seq!==byproductStatementSequence||!$('#byproduct-statement-form'))return;
  byproductStatementState={draft:s,key:erpRequestKey()};$('#byproduct-statement-period').textContent='结算期间：'+s.period_start+' 至 '+s.period_end+'。';$('#statement-operator').innerHTML=statementOperatorOptions();
  if(s.company?.version||!$('#statement-seller').value)$('#statement-seller').value=s.issuer_profile?.name||'';
  if(s.company?.version||!$('#statement-phone').value)$('#statement-phone').value=s.issuer_profile?.phone||'';$('#statement-seller').readOnly=!!s.company?.version;$('#statement-phone').readOnly=!!s.company?.version;
  $('#statement-buyer').value=s.customer.legal_name||s.customer.name;
  $('#byproduct-statement-form').elements.identity_checked.checked=false;
  $('#byproduct-statement-issue').disabled=!canAction('finance.statement-issue')||!s.source_sale_ids.length;
  $('#byproduct-statement-archive').innerHTML='<option value="">选择原始出具版本</option>'+docs.map(d=>`<option value="${esc(d.id)}">${d.voided?'已作废 · ':''}${esc(d.month)} · ${esc(d.id)} · ${esc(d.issued_at)}</option>`).join('');
  showStatementImages(s);if(initial)dialogBaseline=dialogValues();
 }catch(e){if(seq===byproductStatementSequence&&$('#statement-image-preview'))$('#statement-image-preview').textContent=e.message;}
}
async function issueByproductStatement(){
 const f=$('#byproduct-statement-form'),state=byproductStatementState;if(busy||!f||!state||!f.reportValidity()||!needPermission('finance.statement-issue'))return;
 const operator=$('#statement-operator').selectedOptions[0],body={...Object.fromEntries(new FormData(f)),operator_version:Number(operator.dataset.version),identity_checked:f.elements.identity_checked.checked,request_key:state.key,source_fingerprint:state.draft.source_fingerprint};
 busy=true;$('#byproduct-statement-issue').disabled=true;for(const el of f.elements)el.disabled=true;
 try{
  const s=await api('/api/byproduct-statements/issue',body);byproductStatementState=null;
  showStatementImages(s);const option=new Option(s.month+' · '+s.document_id,s.document_id);$('#byproduct-statement-archive').add(option,1);$('#byproduct-statement-archive').value=s.document_id;dialogBaseline=dialogValues();notify('豆渣结算单已归档，可下载图片或导出表格');
 }catch(e){err(e);for(const el of f.elements)el.disabled=false;$('#byproduct-statement-issue').disabled=false;}
 finally{busy=false;$('#byproduct-statement-customer').disabled=false;$('#byproduct-statement-month').disabled=false;if(!byproductStatementState)dialogBaseline=dialogValues();}
}
async function loadByproductArchive(id){
 if(busy||!id)return;const seq=++byproductStatementSequence;byproductStatementState=null;$('#byproduct-statement-issue').disabled=true;
 try{const s=await api('/api/byproduct-documents/'+encodeURIComponent(id));if(seq!==byproductStatementSequence||!$('#byproduct-statement-form'))return;$('#byproduct-statement-fields').disabled=true;$('#byproduct-statement-month').value=s.month;$('#byproduct-statement-period').textContent='结算期间：'+s.period_start+' 至 '+s.period_end+'；出具日期：'+s.generated_at.slice(0,10)+'。';$('#statement-seller').value=s.parties.seller_name;$('#statement-phone').value=s.parties.seller_phone;$('#statement-buyer').value=s.parties.buyer_name;$('#byproduct-statement-form').elements.note.value=s.note||'';const operator=new Option(s.parties.operator+'（归档）','archived');operator.dataset.name=s.parties.operator;$('#statement-operator').replaceChildren(operator);showStatementImages(s);dialogBaseline=dialogValues();}catch(e){err(e);}
}
document.addEventListener('click',e=>{
 if(e.target.closest('[data-byproduct-customer-new]'))requestPageTransition(()=>customerForm('','byproduct'),{dialogOnly:true});
 const edit=e.target.closest('[data-byproduct-customer-edit]');if(edit)requestPageTransition(()=>customerForm(edit.dataset.byproductCustomerEdit,'byproduct'),{dialogOnly:true});
  const ar=e.target.closest('[data-byproduct-receivable]');if(ar){if(!data.auth_user||data.permissions.modules.includes('finance.receivables')){ledgerCustomer=ar.dataset.byproductReceivable;ledgerSource='byproduct';ledgerMarket='';ledgerClearance='all';ledgerSearch='';goto('ledger');}else notify('当前账号无应收管理查看权限');}
 const button=e.target.closest('[data-byproduct-statement]');if(button)requestPageTransition(()=>openByproductStatement(button.dataset.cid,button.dataset.month),{dialogOnly:true});
 if(e.target.closest('[data-byproduct-statement-refresh]'))loadByproductStatement();
 if(e.target.closest('[data-byproduct-statement-issue]'))issueByproductStatement();
});
document.addEventListener('change',e=>{
 if(['byproduct-statement-customer','byproduct-statement-month'].includes(e.target.id))loadByproductStatement();
 if(e.target.id==='byproduct-statement-archive'){if(e.target.value)loadByproductArchive(e.target.value);else loadByproductStatement();}
});
document.addEventListener('input',e=>{if(e.target.closest('#byproduct-statement-fields')&&byproductStatementState)showStatementImages({...byproductStatementState.draft,note:$('#byproduct-statement-form').elements.note.value});});
