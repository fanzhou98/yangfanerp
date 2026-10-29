'use strict';
function customerRegions(){return [...new Set(['乌鲁木齐','昌吉',...(data.delivery_markets||[]).map(m=>m.city),...data.customers.map(c=>c.region)].filter(Boolean))];}
function customerLocationOptions(region,value=''){
 const points=(data.delivery_markets||[]).filter(m=>m.city===region);
 const group=(kind,label)=>{const rows=points.filter(m=>(m.kind||'market')===kind);return rows.length?`<optgroup label="${label}">${rows.map(m=>`<option value="${esc(m.id)}" ${value===m.id?'selected':''}>${esc(m.name)}</option>`).join('')}</optgroup>`:'';};
 return `<option value="">${region?'请选择市场或独立收货点':'请先选择地区'}</option>`+group('market','固定市场')+group('independent','已登记的独立配送点')+`<optgroup label="其他情况"><option value="__independent__" ${value==='__independent__'?'selected':''}>不在固定市场（单位 / 门店 / 自取所在地）</option><option value="__new_market__" ${value==='__new_market__'?'selected':''}>＋ 新增市场</option></optgroup>`;
}
function salesCustomers(){return data.customers.filter(c=>c.business_kind!=='byproduct');}
function byproductCustomers(){return data.customers.filter(c=>['byproduct','both'].includes(c.business_kind));}
function byproductCustomerOptions(value=''){return '<option value="">请选择豆渣客户</option>'+byproductCustomers().map(c=>`<option value="${esc(c.id)}" ${c.id===value?'selected':''}>${esc(c.id)} · ${esc(c.name)}</option>`).join('');}
function customerForm(cid,businessKind='sales'){
 if(!needPermission('master.customers.write'))return;
 const c=data.customers.find(c=>c.id===cid)||{id:'',name:'',route:'',note:'',business_kind:businessKind,delivery_method:businessKind==='byproduct'?'pickup':'delivery'};
 const point=(data.delivery_markets||[]).find(m=>c.market_id?m.id===c.market_id:m.name===c.route);
 const region=c.region||point?.city||'',location=point?.id||(c.route?'__independent__':'');
 openDialog(cid?'编辑客户档案':'新建客户',`<form id="customer-form"><p class="help-text">${c.business_kind==='byproduct'?'豆渣客户只需维护客户名称、结算名称与联系电话。':'客户编号自动生成。先选地区，再选市场；单独送到单位或门店，选择“不在固定市场”。'}</p>${cid&&!region&&c.business_kind!=='byproduct'?`<div class="callout">原记录“${esc(c.route)}”已保留，请补选地区并确认收货点。</div>`:''}<div class="form-grid"><label class="field">业务类型<select name="business_kind" id="customer-business-kind">${[['sales','产品客户'],['byproduct','豆渣客户'],['both','产品及豆渣客户']].map(([key,label])=>`<option value="${key}" ${(c.business_kind||'sales')===key?'selected':''}>${label}</option>`).join('')}</select></label><label class="field">客户编号<input name="id" readonly value="${esc(cid?c.id:data.next_customer_id||'')}" placeholder="保存后自动生成"></label><label class="field">客户名称<input name="name" required maxlength="80" value="${esc(c.name)}"></label><label class="field">联系电话<input name="phone" type="tel" maxlength="40" value="${esc(c.phone||'')}" placeholder="手机号或固定电话"></label><label class="field wide">营业执照名称 / 姓名（结算用，可选）<input name="legal_name" maxlength="120" value="${esc(c.legal_name||'')}" placeholder="未填写时结算单使用客户登记名称"></label><label class="field">地区<select name="region_choice" id="customer-region" required><option value="">请选择地区</option>${customerRegions().map(r=>`<option value="${esc(r)}" ${r===region?'selected':''}>${esc(r)}</option>`).join('')}<option value="__new_region__">＋ 新增地区</option></select></label><label class="field">提货方式<select name="delivery_method" id="customer-method"><option value="delivery" ${c.delivery_method!=='pickup'?'selected':''}>车辆配送</option><option value="pickup" ${c.delivery_method==='pickup'?'selected':''}>客户自取</option></select></label><label class="field wide" id="customer-new-region-field" hidden>新地区名称<input name="new_region" id="customer-new-region" maxlength="40" placeholder="例如：五彩湾、米东区" disabled></label><label class="field wide">市场 / 收货点<select name="location_choice" id="customer-location" required ${!region?'disabled':''}>${customerLocationOptions(region,location)}</select></label><label class="field wide" id="customer-location-name-field" hidden><span id="customer-location-name-label">具体收货点 / 所在地</span><input name="location_name" id="customer-location-name" maxlength="50" value="${esc(point?'':c.route)}" placeholder="例如：某单位、某门店或五彩湾自取" disabled></label><p class="help-text wide" id="customer-location-help"></p><label class="field">期初应收（元）<input name="opening" inputmode="decimal" value="${esc(c.opening_cents?((c.opening_cents||0)/100).toFixed(2):'')}" placeholder="历史欠款，没有留空"></label><label class="field">期初日期<input name="opening_date" type="date" max="${new Date().toISOString().slice(0,10)}" value="${esc(c.opening_date||'')}"></label><label class="field wide">备注<textarea name="note" maxlength="500" rows="2">${esc(c.note)}</textarea></label></div><input type="hidden" name="existing" value="${cid?'1':''}"></form>`,'客户档案',`<button class="button" data-act="close">取消</button><button class="button primary" data-act="save-customer">保存客户</button>`);
 updateCustomerLocationForm();
}
function selectedCustomerRegion(){return $('#customer-region').value==='__new_region__'?$('#customer-new-region').value.trim():$('#customer-region').value;}
function updateCustomerLocationForm(reset=false){
 const form=$('#customer-form');if(!form)return;
 const bean=form.elements.business_kind.value==='byproduct';
 for(const name of ['region_choice','delivery_method','new_region','location_choice','location_name']){const el=form.elements[name];if(el){el.closest('label').hidden=bean;el.disabled=bean;if(bean)el.required=false;}}
 $('#customer-location-help').hidden=bean;
 if(bean)return;
 form.elements.region_choice.required=true;form.elements.location_choice.required=true;
 const newRegion=$('#customer-region').value==='__new_region__',regionInput=$('#customer-new-region');
 $('#customer-new-region-field').hidden=!newRegion;regionInput.disabled=!newRegion;regionInput.required=newRegion;
 const region=selectedCustomerRegion(),select=$('#customer-location');
 if(reset)select.innerHTML=customerLocationOptions(region);
 select.disabled=!region;
 const custom=select.value==='__independent__'||select.value==='__new_market__',market=select.value==='__new_market__';
 $('#customer-location-name-field').hidden=!custom;
 const name=$('#customer-location-name');name.disabled=!custom;name.required=custom;
 $('#customer-location-name-label').textContent=market?'新市场名称':'具体收货点 / 所在地';
 name.placeholder=market?'填写新市场名称':'例如：某单位、某门店或五彩湾自取';
 $('#customer-location-help').textContent=$('#customer-method').value==='pickup'?'自取客户无需绑定固定市场，也不安排车辆。可选择“不在固定市场”，填写所在地。':market?'保存客户时一并登记新市场，之后可直接下拉选择。':'独立收货点保存后会出现在“配送排车”，可像市场一样选择当天趟次。';
}
function customerFormPayload(){
 const body=formData('#customer-form');
 if(body.business_kind==='byproduct')return {id:body.id,existing:body.existing,name:body.name,legal_name:body.legal_name||'',phone:body.phone||'',note:body.note,business_kind:'byproduct',delivery_method:'pickup',route:data.customers.find(c=>c.id===body.id)?.route||'豆渣自取'};
 const point=(data.delivery_markets||[]).find(m=>m.id===body.location_choice);
 return {business_kind:body.business_kind,id:body.id,existing:body.existing,name:body.name,legal_name:body.legal_name||'',phone:body.phone||'',note:body.note,delivery_method:body.delivery_method,opening:body.opening||'',opening_date:body.opening_date||'',
  region:selectedCustomerRegion(),market_id:point?.id||'',location_kind:point?(point.kind||'market'):body.location_choice==='__new_market__'?'market':'independent',location_name:body.location_name||''};
}
document.addEventListener('change',e=>{if(['customer-region','customer-location','customer-method','customer-business-kind'].includes(e.target.id))updateCustomerLocationForm(e.target.id==='customer-region');});
document.addEventListener('input',e=>{if(e.target.id==='customer-new-region'){const select=$('#customer-location'),value=select.value;select.innerHTML=customerLocationOptions(selectedCustomerRegion(),value);updateCustomerLocationForm();}});
