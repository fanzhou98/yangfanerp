'use strict';
function isFractionalUnit(unit){return (data.trade_units||[]).find(u=>u.id===unit)?.fractional||unit==='公斤';}
// Keep IME candidate entry intact; live filters run only after text is committed.
const composingTextFields=new WeakSet(),liveSearchFields=new WeakSet();
function isTextComposing(event){return !!(event.isComposing||event.keyCode===229||composingTextFields.has(event.target));}
document.addEventListener('compositionstart',event=>composingTextFields.add(event.target),true);
document.addEventListener('compositionend',event=>{const field=event.target;composingTextFields.delete(field);if(liveSearchFields.has(field)&&field.isConnected)field.dispatchEvent(new Event('input',{bubbles:true}));},true);
function updateLiveSearch(event,update,paint=render){
 const field=event.target;liveSearchFields.add(field);if(isTextComposing(event))return;
 const start=field.selectionStart,end=field.selectionEnd,direction=field.selectionDirection,focused=document.activeElement===field;
 update(field.value);paint();
 // Reuse the original control so repeated typing, selection and mobile keyboards stay stable.
 const replacement=document.getElementById(field.id);if(replacement&&replacement!==field)replacement.replaceWith(field);
 if(focused&&field.isConnected){field.focus({preventScroll:true});if(start!==null)field.setSelectionRange(start,end,direction||'none');}
}

const legacyPermissionRoles={ 'materials.write':['库管','会计'],'materials.value':['会计'],'costs.write':['会计','出纳'],'costs.close':['会计'],'costs.review':['出纳'],'costs.pay':['出纳'],'byproducts.write':['会计','出纳'], 'orders.write':['库管','会计'],'weight.confirm':['库管','会计'],'inventory.stock':['库管','会计'],'inventory.dispatch':['库管','会计'],'inventory.process':['库管','会计'],'inventory.close':['库管','会计'],'delivery.schedule':['库管','会计'],'returns.register':['库管','会计'],'returns.account':['会计'],'returns.retract':['会计','出纳'],'returns.review':['出纳'],'returns.refund':['出纳'],'finance.settle':['会计'],'finance.review':['出纳'],'finance.review-return':['出纳'],'finance.receipt':['出纳'],'finance.statement-issue':['会计','出纳'],'finance.price-edit':['会计'],'master.write':['会计'],'system.archive':['会计'],'system.operator-users':['会计'],'system.backup':['会计']};
function canAction(key){if((typeof data==='undefined'||!data?.auth_user)&&({'master.customers.write':'master.write','master.products.write':'master.write','master.pricing.write':'master.write','weight.write':'orders.write','materials.catalog':'materials.write','materials.void':'materials.write','costs.void':'costs.write','byproducts.receive':'byproducts.write','byproducts.void':'byproducts.write'})[key])key=({'master.customers.write':'master.write','master.products.write':'master.write','master.pricing.write':'master.write','weight.write':'orders.write','materials.catalog':'materials.write','materials.void':'materials.write','costs.void':'costs.write','byproducts.receive':'byproducts.write','byproducts.void':'byproducts.write'})[key];if(typeof data!=='undefined'&&data?.auth_user)return data.auth_user.role==='管理员'||!!data.permissions?.actions?.includes(key);return (legacyPermissionRoles[key]||[]).includes(role);}
function canSeeData(key){return !data?.auth_user||data.auth_user.role==='管理员'||(data.permissions?.data_scopes||[]).includes(key);}
function masterPermission(view=masterView){return ({customers:'master.customers.write',products:'master.products.write',pricing:'master.pricing.write'})[view]||'master.write';}
function needPermission(key){if(canAction(key))return true;notify('当前账号无此操作权限，请联系管理员授权');return false;}
function moduleVisible(m){if(m.id==='delivery.driver'&&(data.auth_user?.role||role)!=='司机')return false;return m.read_roles.includes(data.auth_user?.role||role);}

// Page visibility and action permission are checked separately. A read-only
// module is not a grant to perform the next person's task.
function canOpenWorkflow(target,permission=''){if(permission&&!canAction(permission))return false;if(typeof data==='undefined'||!data?.auth_user)return true;return (data.access_catalog?.modules||[]).some(m=>m.page===target&&moduleVisible(m));}
function applyPageActionAccess(root){for(const button of root.querySelectorAll('[data-page]'))if(!canOpenWorkflow(button.dataset.page))button.remove();for(const button of root.querySelectorAll('[data-required-action]'))if(!canAction(button.dataset.requiredAction))button.remove();}

// Structured field errors are shared by the daily worksheets and master-data forms.
let visibleIssues=[];
function billingUnit(l){const p=data?.products?.find(p=>p.id===(l.product_id||l.id));return l.billing_unit||p?.billing_unit||(l.unit==='筐'||p?.unit==='筐'||data?.settlement_unit==='公斤'?'公斤':l.unit||p?.unit||'包');}
function packageBillKg(l){if(l.unit==='公斤')return Number(l.actual_qty||0);if(l.package_customer_net_kg)return Number(l.package_customer_net_kg);return l.package_net_kg!==undefined&&l.package_net_kg!==null&&l.package_net_kg!==''?Number(l.package_net_kg):l.factory_net_kg?Number(l.factory_net_kg):Number((Number(l.actual_qty)*Number(l.standard_kg||0)).toFixed(3));}
function standardUnitWeight(l){if(l.unit==='公斤')return 1;return l.unit!=='筐'?Number(l.standard_kg||0):Number(Object.hasOwn(l,'standard_unit_kg')?(l.standard_unit_kg||0):(data.products?.find(p=>p.id===l.product_id)?.default_average_kg||0));}
function standardLineWeight(l){return Number((Number(l.actual_qty||0)*standardUnitWeight(l)).toFixed(3));}
function settlementNet(l,mode){return mode==='factory'?(l.factory_net_kg?Number(l.factory_net_kg):null):mode==='standard'?(standardLineWeight(l)>0?standardLineWeight(l):null):sourceNet(l,mode);}
const FIELD_NAMES={ordered_qty:'订货数量',actual_qty:'实发数量',not_shipped:'未发货确认',gross:'毛重',count:'筐数',tare:'皮重',price:'单价',agreed_net:'协商净重',reason:'协商原因',business_date:'业务日期',batch:'发货批次',name:'产品名称',id:'编号',unit:'计量单位',standard_kg:'标准包装量',default_average_kg:'默认平均重量'};
function isPickupOrder(o){return (o.delivery_method||data.customers?.find(c=>c.id===o.customer_id)?.delivery_method)==='pickup';}
function cellIssue(o,l,field,message,source,index){return {order_id:o.id,customer_id:o.customer_id,customer_name:o.customer_name||data?.customers.find(c=>c.id===o.customer_id)?.name||'',product_id:l?.product_id,product_name:l?.product_name||data?.products.find(p=>p.id===l?.product_id)?.name||'',field,message,...(source?{source,index}:{} )};}
function numericProblem(value,label,max=100000,positive=false,integer=false){
 const s=String(value??'').trim();if(!s)return '请填写'+label;
 if(!/^(?:\d+(?:\.\d{0,3})?|\.\d{1,3})$/.test(s)||!Number.isFinite(Number(s))||Number(s)>max)return `${label}须为0至${num(max)}之间的数，最多3位小数`;
 if(positive&&Number(s)<=0)return label+'必须大于0';if(integer&&!Number.isInteger(Number(s)))return label+'须为整数';return '';
}
function weightEntries(o,l,source){
 const prior=o.id?originalOrder(o.id)?.lines.find(x=>x.product_id===l.product_id)?.[source]||[]:[];
 const tare=(data.rules||[]).find(r=>r.customer_id===o.customer_id&&r.product_id===l.product_id)?.tare??(data.products||[]).find(p=>p.id===l.product_id)?.tare;
 return (l[source]||[]).map((w,index)=>({w,index})).filter(({w,index})=>{
  if(prior[index])return true;
  const blank=x=>String(x??'').trim()==='';
  const unused=blank(w.gross)&&blank(w.note)&&(blank(w.count)||Number(w.count)===Number(l.actual_qty))&&(blank(w.tare)||Number(w.tare)===Number(tare));
  return !unused;
 });
}
function activeWeightRows(o,l,source){return weightEntries(o,l,source).map(r=>r.w);}
function weightSourceReady(o,l,source){const rows=activeWeightRows(o,l,source);return rows.length>0&&rows.every(w=>!numericProblem(w.gross,'毛重',100000000,true)&&!numericProblem(w.count,'筐数',100000,true,true)&&!numericProblem(w.tare,'皮重',100)&&Number(w.gross)>Number(w.count)*Number(w.tare))&&rows.reduce((n,w)=>n+Number(w.count),0)===Number(l.actual_qty);}
function defaultSettlementMode(o,l){return l.settlement_mode&&l.settlement_mode!=='not_shipped'?l.settlement_mode:l.agreed_net?'agreed':(!isPickupOrder(o)&&l.driver_weight_basis==='gross')?'driver':activeWeightRows(o,l,'customer').length?'customer':activeWeightRows(o,l,'driver').length?'driver':l.factory_net_kg?'factory':standardLineWeight(l)>0?'standard':isPickupOrder(o)?'customer':'driver';}

function orderInputIssues(o,settling=false,body={}){
 const issues=[];let shipped=false;
 for(const raw of o.lines){const product=data.products?.find(p=>p.id===raw.product_id);const prior=o.id?originalOrder(o.id)?.lines.find(l=>l.product_id===raw.product_id):null;const l={unit:product?.unit,product_name:product?.name,...prior,...raw};
  if(raw.package_customer_net_kg){const m=numericProblem(raw.package_customer_net_kg,'客户复称净重',100000000,true);if(m)issues.push(cellIssue(o,l,'package_customer_net_kg',m));if(l.unit==='筐'||Number(l.actual_qty)<=0)issues.push(cellIssue(o,l,'package_customer_net_kg','仅已实发包装产品可填写包装客户复称'));}
  if(raw.factory_net_kg){const m=numericProblem(raw.factory_net_kg,'出厂净重',100000000,true);if(m)issues.push(cellIssue(o,l,'factory_net_kg',m));if(Number(l.actual_qty)<=0)issues.push(cellIssue(o,l,'factory_net_kg','出厂称重须先填写实发数量'));}
  if(raw.package_net_kg!==undefined&&raw.package_net_kg!==''){const m=numericProblem(raw.package_net_kg,'包装实称净重',100000000,true);if(m)issues.push(cellIssue(o,l,'package_net_kg',m));}
  for(const [f,label,max,pos,integer] of [['ordered_qty','订货数量',100000,true,true],['actual_qty','实发数量',100000,false,true],['price','单价',100000,true,false]]){
   if(f==='price'&&typeof data!=='undefined'&&data?.auth_user&&!canSeeData('sales-prices'))continue;
   const m=numericProblem(l[f],label,max,pos,integer&&!isFractionalUnit(l.unit));if(m)issues.push(cellIssue(o,l,f,m));
  }
  if(l.not_shipped&&Number(l.actual_qty)>0)issues.push(cellIssue(o,l,'not_shipped','勾选本次未发时，实发数量必须为0'));
  for(const [source,label] of [['driver','司机卸货'],['customer',isPickupOrder(o)?'自提确认':'客户复称']]){
   const entries=weightEntries(o,l,source),rows=entries.map(r=>r.w);let count=0,validCounts=true;
   entries.forEach(({w,index:i})=>{
    const ok={};for(const [f,name,max,pos,integer] of [['gross','毛重',100000000,true,false],['count','筐数',100000,true,true],['tare','单筐皮重',100,false,false]]){
     const m=numericProblem(w[f],name,max,pos,integer);ok[f]=!m;if(m)issues.push(cellIssue(o,l,f,`${label}第${i+1}批：${m}`,source,i));
    }
    if(ok.count)count+=Number(w.count);else validCounts=false;
    if(ok.gross&&ok.count&&ok.tare&&Number(w.gross)<=Number(w.count)*Number(w.tare))issues.push(cellIssue(o,l,'gross',`${label}第${i+1}批：毛重必须大于总皮重 ${num(Number(w.count)*Number(w.tare))} 公斤`,source,i));
   });
   if(l.not_shipped&&rows.length)issues.push(cellIssue(o,l,'not_shipped','本次未发产品仍有称重记录，请核对'));
   if(validCounts&&count>Number(l.actual_qty))entries.forEach(({index:i})=>issues.push(cellIssue(o,l,'count',`${label}共${count}筐，超过实发${l.actual_qty}筐`,source,i)));

  }
  if(Object.hasOwn(raw,'crate_lines')){let total=0;for(const r of raw.crate_lines||[]){const m=numericProblem(r.qty,'框数',100000,false,true);if(m)issues.push(cellIssue(o,l,'crate_qty',m));else total+=Number(r.qty);}if(total>0&&total!==Number(l.actual_qty))issues.push(cellIssue(o,l,'crate_qty','白框、黄框等属性数量合计须等于实发数量'));}
  if(settling){
   if(l.not_shipped&&Number(l.actual_qty)===0)continue;
   if(Number(l.actual_qty)===0){issues.push(cellIssue(o,l,'not_shipped','实发为0：请填数量，或勾选“本次未发”，保留订货记录'));continue;}
   shipped=true;const requested=body.line_modes?.[l.product_id]||body.mode,mode=!requested||requested==='auto'?defaultSettlementMode(o,l):requested;
   if(l.unit!=='筐'&&billingUnit(l)==='公斤'&&packageBillKg(l)<=0)issues.push(cellIssue(o,l,'package_net_kg','请填写包装实称公斤数或有效标准包装重量'));
   if(l.unit==='筐'&&billingUnit(l)==='公斤'){
    const overrides=body.tare_overrides?.[l.product_id]||{};for(const [source,tare] of Object.entries(overrides)){const problem=numericProblem(tare,'结算皮重',100);if(problem)issues.push(cellIssue(o,l,'settlement_tare',problem,source,0));else if(source!=='customer'||!l[source]?.length||l[source].reduce((n,w)=>n+Number(w.gross),0)-Number(l.actual_qty)*Number(tare)<=0)issues.push(cellIssue(o,l,'settlement_tare','调整后的净重须大于0，且须保留原始称重',source,0));}
    const sources=mode==='agreed'?['driver','customer','factory']:[mode];
    if(!sources.some(source=>source==='factory'?Number(l.factory_net_kg)>0:source==='standard'?standardLineWeight(l)>0:['driver','customer'].includes(source)&&weightSourceReady(o,l,source)))issues.push(cellIssue(o,l,'gross',mode==='agreed'?'请先录入至少一次覆盖实发数量的有效称重':`请填写用于算票的${mode==='driver'?'司机卸货':'客户复称 / 自提确认'}完整称重，筐数须等于实发数量`,mode==='driver'?'driver':'customer',0));
   }
   if(l.unit==='筐'&&billingUnit(l)==='公斤'&&mode==='agreed'){
    const m=numericProblem(body.agreed?.[l.product_id],'协商净重',100000000,true);if(m)issues.push(cellIssue(o,l,'agreed_net',m));
    if(!body.reason?.trim())issues.push(cellIssue(o,l,'reason','请填写本客户的协商原因'));
   }
  }
 }
 if(settling&&!shipped&&!issues.length)issues.push(cellIssue(o,null,'actual_qty','整单均未发货，请保存草稿，不形成应收'));
 return issues;
}
function operationIssues(operations){const issues=[];for(const op of operations){
 const old=op.order_id&&originalOrder(op.order_id);const raw=op.action==='order'?op.body:op.update;
 if(raw)issues.push(...orderInputIssues({...old,...raw,id:op.order_id}));
 if(op.action==='settle')issues.push(...orderInputIssues({...old,...(op.update||{}),id:op.order_id},true,op.body));
 }return dedupeIssues(issues);}
function dedupeIssues(issues){const seen=new Set();return issues.filter(i=>{const k=JSON.stringify([i.order_id,i.customer_id,i.product_id,i.field,i.source,i.index,i.message]);if(seen.has(k))return false;seen.add(k);return true;});}
function issueTargets(i){
 const all=$$('input,select,textarea');return all.filter(el=>{
  const d=el.dataset;
  if(i.field==='business_date')return el.id==='sheet-date'||el.name==='business_date';
  if(i.field==='batch')return el.id==='sheet-batch'||el.name==='batch';
  if(d.ruleCid)return !i.order_id&&d.ruleCid===i.customer_id&&d.rulePid===i.product_id&&d.field===i.field;
  if(el.closest('#product-form'))return !i.customer_id&&el.name===i.field&&(!i.product_id||$('#product-form').elements.id.value===i.product_id);
  if(i.field==='reason'&&d.clientReason)return d.clientReason===i.customer_id;
  if(d.matrixKey)return (i.order_id?d.matrixKey===i.order_id:d.customerId===i.customer_id)&&d.productId===i.product_id&&i.field==='ordered_qty';
  return d.oid===i.order_id&&d.pid===i.product_id&&d.field===i.field&&(!i.source||d.source===i.source)&&(i.index===undefined||Number(d.windex)===i.index);
 });
}
function issueLabel(i){return [i.customer_name||i.customer_id,i.product_name,i.source?`${i.source==='driver'?'卸货':'复称'}第${Number(i.index||0)+1}批`:'',FIELD_NAMES[i.field]||'单据'].filter(Boolean).join(' · ');}
function clearValidationDecorations(){
 $$('.invalid-cell').forEach(el=>{el.classList.remove('invalid-cell');el.removeAttribute('aria-invalid');el.removeAttribute('aria-describedby');});
 $$('.field-error,.row-error-hint').forEach(el=>el.remove());$$('.invalid-row').forEach(el=>el.classList.remove('invalid-row'));
}
function decorateIssues(){clearValidationDecorations();visibleIssues.forEach((i,index)=>{
 const targets=issueTargets(i);for(const el of targets){
  el.classList.add('invalid-cell');el.setAttribute('aria-invalid','true');
  const tip=document.createElement('span');tip.className='field-error';tip.id='field-error-'+index;tip.textContent=i.message;
  el.setAttribute('aria-describedby',tip.id);el.parentElement.append(tip);
 }
 if(!targets.length&&i.order_id){const row=$$('[data-processing-order]').find(r=>r.dataset.processingOrder===i.order_id&&(!i.product_id||r.dataset.processingProduct===i.product_id));if(row){row.classList.add('invalid-row');const hint=document.createElement('button');hint.className='row-error-hint';hint.textContent=(i.source==='driver'?'卸货称重：':'')+i.message;hint.dataset.validationJump=String(index);$('td',row).append(hint);}}
 });}
function validationBanner(){return `<b>${visibleIssues.length} 处填写问题，尚未保存；已填写内容保留</b><ol>${visibleIssues.map((i,n)=>`<li><button type="button" data-validation-jump="${n}">${esc(issueLabel(i))}：${esc(i.message)}</button></li>`).join('')}</ol>`;}
function presentValidation(issues,focus=true,message=''){
 visibleIssues=dedupeIssues(issues);decorateIssues();let box=!$('#overlay').hidden?$('#dialog-error'):$('#sheet-error')||$('#master-error');
 if(box){box.hidden=false;box.innerHTML=visibleIssues.length?validationBanner():esc(message||'操作未完成，请重试');}
 else notify(message||visibleIssues[0]?.message||'请核对输入');
 if(focus&&visibleIssues.length)focusValidationIssue(0);
 if(focus&&box&&typeof showWorkflowFeedback==='function')showWorkflowFeedback(message||(visibleIssues.length>1?'有 '+visibleIssues.length+' 项填写需要核对：':'')+(visibleIssues[0]?.message||'请核对输入'),'error');
}
function focusValidationIssue(index){const i=visibleIssues[index];if(!i)return;let target=issueTargets(i)[0];
 if(!target&&i.source==='driver'&&page==='settlements'){page='weighing';render();target=issueTargets(i)[0];}
 if(!target&&i.order_id&&page==='masters'){const order=originalOrder(i.order_id);if(order){selectedDate=order.business_date;processingBatch=order.batch;sheetSearch=order.customer_id;page=i.source==='driver'?'weighing':'settlements';render();target=issueTargets(i)[0];}}
 if(!target&&page==='masters'&&!i.order_id&&i.customer_id&&i.product_id){masterView='pricing';pricingMode=i.field==='tare'?'tare':'price';render();target=issueTargets(i)[0];}
 if(!target)target=$$('[data-processing-order]').find(r=>r.dataset.processingOrder===i.order_id&&(!i.product_id||r.dataset.processingProduct===i.product_id));
 if(target){if(typeof openCustomerDetailsFor==='function')openCustomerDetailsFor(target);target.scrollIntoView({block:'center',inline:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});if(!target.disabled)target.focus({preventScroll:true});}
}
function clearEditedIssue(el){const before=visibleIssues.length;visibleIssues=visibleIssues.filter(i=>!issueTargets(i).includes(el));if(before!==visibleIssues.length){decorateIssues();const box=!$('#overlay').hidden?$('#dialog-error'):$('#sheet-error')||$('#master-error');if(box){box.hidden=!visibleIssues.length;box.innerHTML=visibleIssues.length?validationBanner():'';}}}
function restoreValidation(){if(visibleIssues.length)presentValidation(visibleIssues,false);}
document.addEventListener('click',e=>{const b=e.target.closest('[data-validation-jump]');if(b){e.preventDefault();focusValidationIssue(Number(b.dataset.validationJump));}});
document.addEventListener('input',e=>{if(e.target.matches('input,select,textarea'))clearEditedIssue(e.target);});

let productMainFilter='';
function productMainMaterial(p){if(p.supply_kind==='purchased')return '外购成品';return p.main_material|| (p.name.includes('素鸡')?'豆皮':p.name.includes('熏干')?'白干':p.name.includes('魔芋')?'魔芋':p.name.includes('凉粉')?'淀粉':'黄豆');}
function productUsesSlurry(p){if(p.supply_kind==='purchased')return false;return ['黄豆','大豆'].includes(productMainMaterial(p));}
let masterView='products',pricingMode='price',pricingSearch='',pricingRoute='';
const pricingDrafts=new Map();
let productOrderDraft=null;
function productOrderDirty(){return !!productOrderDraft&&JSON.stringify(productOrderDraft.ids)!==JSON.stringify(productOrderDraft.expected);}
function productDisplayList(){if(!productOrderDraft)return data.products;const positions=new Map(productOrderDraft.ids.map((id,i)=>[id,i]));return [...data.products].sort((a,b)=>(positions.get(a.id)??positions.size)-(positions.get(b.id)??positions.size));}
function moveProduct(id,position){if(!needPermission(masterPermission())||busy)return;const products=productDisplayList(),ids=products.map(p=>p.id),index=ids.indexOf(id);if(index<0||!Number.isInteger(position)||position<0||position>=ids.length)return;if(!productOrderDraft)productOrderDraft={ids:[...ids],expected:[...ids]};ids.splice(index,1);ids.splice(position,0,id);productOrderDraft.ids=ids;persistDrafts();render();}

function pricingRow(cid,pid,variant=''){const key=cid+'|'+pid+(variant?'|'+variant:''),p=data.products.find(p=>p.id===pid),current=variant?(data.crate_tare_rules||[]).find(r=>r.customer_id===cid&&r.product_id===pid&&r.variant_id===variant):data.rules.find(r=>r.customer_id===cid&&r.product_id===pid)||null;
 const tare=variant?customerVariantTare(cid,pid,variant):current?.tare??p.tare;
 if(!pricingDrafts.has(key))pricingDrafts.set(key,{cid,pid,variant_id:variant,price:current?.price??p.price,tare,initialPrice:current?.price??p.price,initialTare:tare,expected:current?(variant?{tare:current.tare,version:current.version}:{price:current.price,tare:current.tare}):null});return pricingDrafts.get(key);}

function pricingValueEqual(a,b){const x=String(a??'').trim(),y=String(b??'').trim();return x===y||(x!==''&&y!==''&&Number.isFinite(Number(x))&&Number.isFinite(Number(y))&&Number(x)===Number(y));}
function pricingFieldDirty(r,field){return !pricingValueEqual(r[field],r[field==='price'?'initialPrice':'initialTare']);}
function pricingOverride(r,field){const p=data.products.find(p=>p.id===r.pid),base=field==='price'?p.price:r.variant_id?(p.crate_tares?.[r.variant_id]??crateTypeTare(r.variant_id)??p.tare):p.tare;return !pricingValueEqual(r[field==='price'?'initialPrice':'initialTare'],base);}
function pricingDirty(r){return pricingFieldDirty(r,'price')||pricingFieldDirty(r,'tare');}
function filteredPricingCustomers(){return data.customers.filter(c=>c.business_kind!=='byproduct').filter(c=>(!pricingRoute||c.route===pricingRoute)&&(!pricingSearch||[c.id,c.name,c.route].join(' ').toLowerCase().includes(pricingSearch.toLowerCase())));}
function renderMasterData(){const pending=[...pricingDrafts.values()].filter(pricingDirty).length;

 const actions=''+ (masterView==='products'?`<button class="button" data-master-action="new-product">＋ 新增产品</button><button class="button" data-new-trade-unit>新增发货单位</button><button class="button primary" data-master-action="save-product-order" ${!productOrderDirty()||!canAction(masterPermission())?'disabled':''}>保存产品顺序${productOrderDirty()?'（有改动）':''}</button>`:masterView==='customers'?'<button class="button primary" data-act="customer">＋ 新建客户</button>':`<button class="button primary" data-master-action="save-pricing">保存价格改动 <span id="pricing-dirty">${pending?'('+pending+')':''}</span></button>`);
 setTimeout(restoreValidation,0);
 return head(({products:'产品维护',customers:'客户档案',pricing:'客户专属价格总表'})[masterView],masterView==='pricing'?'客户一行、产品一列；整表改价，只保存有改动的规则。':'维护产品、客户及价格规则。历史单据保留原有名称、单价和皮重快照。',actions,'MASTER DATA · 基础档案')+'<div id="master-error" class="sheet-error" role="alert" hidden></div>'+(masterView==='products'?productTable():masterView==='customers'?customerTable():pricingTable());
}
function productTable(){const all=productDisplayList(),products=all.filter(p=>!productMainFilter||productMainMaterial(p)===productMainFilter);return `<div class="sheet-filters"><label>主要原料<select id="product-main-filter"><option value="">全部原料</option>${[...new Set(all.map(productMainMaterial))].map(m=>`<option value="${esc(m)}" ${productMainFilter===m?'selected':''}>${esc(m)}</option>`).join('')}</select></label><span>显示 ${products.length} / ${all.length} 个产品；仅黄豆类产品进入浆缸登记。筛选时暂停调整顺序。</span></div><section class="panel"><div class="panel-head"><h2>产品列表 · ${products.length} 项${productOrderDirty()?' · 顺序未保存':''}</h2><small>选择序号可直接移动，也可上移、下移或置顶；调整后点击「保存产品顺序」</small></div><div class="table-wrap"><table class="product-sort-table"><thead><tr><th>顺序</th><th>产品 / 编号</th><th>主要原料</th><th>发货单位</th><th>计价方式</th>${canSeeData('sales-prices')?'<th>默认单价</th>':''}<th>单筐皮重</th><th>标准包装</th><th>默认平均重量</th><th>操作</th></tr></thead><tbody>${products.map((p,i)=>`<tr><td><select data-product-position="${esc(p.id)}" aria-label="${esc(p.name)}显示顺序" ${!canAction(masterPermission())||!!productMainFilter?'disabled':''}>${all.map((_,j)=>`<option value="${j}" ${all.indexOf(p)===j?'selected':''}>第 ${j+1} 位</option>`).join('')}</select></td><td><span class="customer-name">${esc(p.name)}</span><small>${esc(p.id)}</small></td><td>${esc(productMainMaterial(p))}${['purchased','mixed'].includes(p.supply_kind)?`<small>${p.supply_kind==='mixed'?'自产＋外购 · ':''}${(p.supplier_ids||[]).map(id=>data.purchasing?.suppliers?.find(s=>s.id===id)?.name).filter(Boolean).map(esc).join('、')||((p.supplier_ids||[]).length?'已关联供应商':'供应商待关联')}</small>`:''}</td><td>${p.unit}</td><td>按${esc(billingUnit(p))}计价</td>${canSeeData('sales-prices')?`<td>${num(p.price)} 元/${billingUnit(p)}</td>`:''}<td>${p.unit==='筐'?num(p.tare)+' 公斤':'—'}</td><td>${p.standard_kg?num(p.standard_kg)+'公斤/'+esc(p.unit):'—'}</td><td>${p.default_average_kg?num(p.default_average_kg)+' 公斤/'+esc(p.unit):'未设置'}</td><td><div class="product-sort-actions"><button class="text-button" data-master-action="move-product" data-id="${esc(p.id)}" data-position="${all.indexOf(p)-1}" aria-label="${esc(p.name)}上移" ${i===0||!canAction(masterPermission())||!!productMainFilter?'disabled':''}>↑ 上移</button><button class="text-button" data-master-action="move-product" data-id="${esc(p.id)}" data-position="${all.indexOf(p)+1}" aria-label="${esc(p.name)}下移" ${i===products.length-1||!canAction(masterPermission())||!!productMainFilter?'disabled':''}>↓ 下移</button><button class="text-button" data-master-action="move-product" data-id="${esc(p.id)}" data-position="0" aria-label="${esc(p.name)}置顶" ${i===0||!canAction(masterPermission())||!!productMainFilter?'disabled':''}>置顶</button>${canAction('master.products.write')?`<button class="text-button" data-master-action="edit-product" data-id="${esc(p.id)}">编辑产品</button>`:''}</div></td></tr>`).join('')}</tbody></table></div><div class="table-end"><span>保存后订货总表与客户专属价格表使用相同产品顺序</span><span>新增产品自动排在最后</span></div></section>`;}

function customerTable(){return `<section class="panel"><div class="table-wrap"><table><thead><tr><th>客户编号</th><th>名称</th><th>业务类型</th><th>电话</th><th>地区</th><th>市场 / 独立收货点</th><th>提货方式</th><th>备注</th><th>操作</th></tr></thead><tbody>${data.customers.map(c=>`<tr><td>${esc(c.id)}</td><td><span class="customer-name">${esc(c.name)}</span>${c.legal_name?`<small>营业执照：${esc(c.legal_name)}</small>`:''}</td><td>${esc(({sales:'产品',byproduct:'豆渣',both:'产品及豆渣'})[c.business_kind||'sales'])}</td><td>${esc(c.phone||'—')}</td><td>${esc(c.region)||'待确认'}</td><td>${esc(c.route)}${!c.region?'<small>原记录 · 归属待确认</small>':c.location_kind==='independent'?'<small>不属于固定市场</small>':''}</td><td>${c.delivery_method==='pickup'?'客户自取':'车辆配送'}</td><td>${esc(c.note)}</td><td><button class="text-button" data-act="customer" data-id="${esc(c.id)}">编辑客户</button>${c.business_kind!=='byproduct'?`<button class="text-button" data-customer-crates="${esc(c.id)}">框子管理</button>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;}
function pricingTable(){const customers=filteredPricingCustomers(),columns=pricingColumns();return `<div class="sheet-filters"><label>配送线路<select id="pricing-route"><option value="">全部线路</option>${[...new Set(data.customers.filter(c=>c.business_kind!=='byproduct').map(c=>c.route))].map(r=>`<option ${pricingRoute===r?'selected':''}>${esc(r)}</option>`).join('')}</select></label><label>查找客户<input id="pricing-search" value="${esc(pricingSearch)}" placeholder="客户编号、名称、线路"></label><div class="pricing-mode"><button class="button ${pricingMode==='price'?'primary':''}" data-price-mode="price">批量改单价</button><button class="button ${pricingMode==='tare'?'primary':''}" data-price-mode="tare">批量改客户皮重</button></div></div><div class="callout">大豆腐框按固有属性分白框、黄框、布分别设置客户皮重；会计算票时填颜色数量即可自动扣皮。价格和皮重只影响新录入的单据。<span class="pricing-legend"><span class="pricing-legend-saved">紫色：已保存且不同于默认值</span><span class="pricing-legend-pending">蓝色：本次修改未保存</span></span></div><section class="panel worksheet-panel"><div class="table-wrap sheet-scroll"><table class="worksheet matrix pricing-matrix" data-sheet-grid="pricing"><thead><tr><th class="freeze-client">客户 / 线路</th>${columns.map(({p,title})=>`<th>${esc(title)}<small>${pricingMode==='price'?'元/'+billingUnit(p):'皮重 · 公斤/个'}</small></th>`).join('')}</tr></thead><tbody>${customers.map((c,r)=>`<tr><td class="freeze-client"><strong>${esc(c.name)}</strong><small>${esc(c.id)} · ${esc(c.route)}</small></td>${columns.map(({p,variant},col)=>{const row=pricingRow(c.id,p.id,variant),disabled=!canAction(masterPermission())||(pricingMode==='tare'&&p.unit!=='筐');return `<td class="${pricingOverride(row,pricingMode)?'override-rule':'inherited-rule'}${pricingFieldDirty(row,pricingMode)?' pricing-pending':''}">${sheetInput(row[pricingMode],`data-rule-cid="${esc(c.id)}" data-rule-pid="${esc(p.id)}" data-rule-variant="${esc(variant)}" data-field="${pricingMode}" data-grid-row="${r}" data-grid-col="${col}" aria-label="${esc(c.name+' '+p.name+' '+(crateAttributes(p.id).find(v=>v.id===variant)?.name||'')+' '+(pricingMode==='tare'?'皮重':'单价'))}"`,disabled)}${row.expected&&!variant&&pricingMode==='price'?`<button type="button" class="text-button pricing-reset" data-pricing-reset data-cid="${esc(c.id)}" data-pid="${esc(p.id)}">恢复默认</button>`:''}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div></section>`;}

async function masterAction(action,el){
 if(action==='move-product'){moveProduct(el.dataset.id,Number(el.dataset.position));return;}
 if(action==='reload-product-order'){if(busy)return;if(productOrderDirty()&&!await confirmWorkflowAction('同步产品列表会放弃尚未保存的排序，继续吗？'))return;data=await api('/api/bootstrap');productOrderDraft=null;persistDrafts();render();notify('已同步产品列表');return;}
 if(action==='save-product-order'){
  if(!needPermission(masterPermission())||busy||!productOrderDirty())return;busy=true;$('#content').setAttribute('inert','');
  try{const result=await api('/api/master/product-order',{product_ids:productOrderDraft.ids,expected:productOrderDraft.expected});const positions=new Map(result.product_ids.map((id,i)=>[id,i]));data.products.sort((a,b)=>(positions.get(a.id)??positions.size)-(positions.get(b.id)??positions.size));productOrderDraft=null;persistDrafts();render();notify('产品顺序已保存，订货总表已同步');}
  catch(e){const target=$('#master-error');target.textContent=e.message;target.hidden=false;target.scrollIntoView({block:'nearest'});}
  finally{busy=false;$('#content').removeAttribute('inert');}return;
 }
 if(action==='new-product'){productForm();return;}if(action==='edit-product'){productForm(el.dataset.id);return;}
 if(action==='save-product'){
  if(!$('#product-form').reportValidity())return;const f=$('#product-form'),body=formData('#product-form');body.unit=f.elements.unit.value;body.create=body.create==='1';body.supplier_ids=[...f.querySelectorAll('[name=supplier_ids]:checked')].map(e=>e.value);body.crate_type_ids=[...f.querySelectorAll('[name=crate_type_ids]:checked:not(:disabled)')].map(e=>e.value);body.crate_tares=Object.fromEntries([...f.querySelectorAll('[data-crate-tare]')].filter(e=>!e.disabled&&e.value.trim()!=='').map(e=>[e.dataset.crateTare,e.value.trim()]));if(body.supply_kind==='purchased'){body.main_material='';body.grinding_system='';}if(dialogExpected)body.expected=dialogExpected;
  const issues=[];for(const [field,label] of [['id','产品编号'],['name','产品名称']])if(!body[field]?.trim())issues.push({product_id:body.id,product_name:body.name,field,message:'请填写'+label});if(!/^[A-Za-z0-9_-]{1,30}$/.test(body.id||''))issues.push({product_id:body.id,product_name:body.name,field:'id',message:'产品编号请使用字母、数字、横线或下划线'});for(const [field,label,max,pos] of [['price','默认单价',100000,true],['tare','默认皮重',100,false],...((body.unit!=='筐'&&body.billing_unit==='公斤')?[['standard_kg','标准包装公斤数',100000,true]]:[])]){const m=numericProblem(body[field],label,max,pos);if(m)issues.push({product_id:body.id,product_name:body.name,field,message:m});}for(const [variant,tare] of Object.entries(body.crate_tares||{})){const m=numericProblem(tare,'框型皮重',100,false);if(m)issues.push({product_id:body.id,product_name:body.name,field:'crate_tare:'+variant,message:m});}
  if(issues.length){presentValidation(issues);return;}
  await perform(()=>submit('/api/master',{...body,kind:'product'},'产品已保存，订货表已更新'));return;
 }
 if(action==='save-pricing'){
  if(!needPermission(masterPermission())||busy)return;const rows=[...pricingDrafts.values()].filter(pricingDirty);
  if(!rows.length){notify('没有改动的价格规则');return;}
  const issues=[];for(const r of rows){const c=data.customers.find(c=>c.id===r.cid),p=data.products.find(p=>p.id===r.pid);for(const [f,label,max,pos] of [['price','专属单价',100000,true],['tare','专属皮重',100,false]]){const m=numericProblem(r[f],label,max,pos);if(m)issues.push({customer_id:c.id,customer_name:c.name,product_id:p.id,product_name:p.name,field:f,message:m});}}
  if(issues.length){presentValidation(issues);return;}
  busy=true;$('#content').setAttribute('inert','');
  try{const result=await api('/api/master/batch-rules',{rules:rows.filter(r=>!r.variant_id).map(r=>({customer_id:r.cid,product_id:r.pid,price:r.price.trim(),tare:r.tare.trim(),expected:r.expected})),crate_rules:rows.filter(r=>r.variant_id).map(r=>({customer_id:r.cid,product_id:r.pid,variant_id:r.variant_id,tare:r.tare.trim(),expected:r.expected}))});
   data=await api('/api/bootstrap');for(const r of rows)pricingDrafts.delete(r.cid+'|'+r.pid+(r.variant_id?'|'+r.variant_id:''));visibleIssues=[];persistDrafts();render();notify(`已保存${result.count}项客户专属规则`);
  }catch(e){if(e.issues?.length)presentValidation(e.issues);else showOperationError(e,$('#master-error'));}finally{busy=false;$('#content').removeAttribute('inert');}
 }
}
document.addEventListener('click',e=>{
 const tab=e.target.closest('[data-master-tab]');if(tab){masterView=tab.dataset.masterTab;visibleIssues=[];goto('masters');return;}
 const mode=e.target.closest('[data-price-mode]');if(mode){pricingMode=mode.dataset.priceMode;render();return;}
 const action=e.target.closest('[data-master-action]');if(action){e.preventDefault();masterAction(action.dataset.masterAction,action).catch(err);}
});
function applyPricingInput(el){const row=pricingRow(el.dataset.ruleCid,el.dataset.rulePid,el.dataset.ruleVariant||'');row[el.dataset.field]=el.value;el.classList.toggle('cell-changed',pricingFieldDirty(row,el.dataset.field));const count=[...pricingDrafts.values()].filter(pricingDirty).length;$('#pricing-dirty').textContent=count?'('+count+')':'';const cell=el.closest('td');cell?.classList.toggle('override-rule',pricingOverride(row,el.dataset.field));cell?.classList.toggle('inherited-rule',!pricingOverride(row,el.dataset.field));cell?.classList.toggle('pricing-pending',pricingFieldDirty(row,el.dataset.field));scheduleDraftSave();}
document.addEventListener('input',e=>{
 if(e.target.dataset.ruleCid)applyPricingInput(e.target);
 if(e.target.id==='pricing-search'){updateLiveSearch(e,value=>pricingSearch=value);}
});
document.addEventListener('change',e=>{
 if(e.target.dataset.productPosition){moveProduct(e.target.dataset.productPosition,Number(e.target.value));return;}
 if(e.target.id==='pricing-route'){pricingRoute=e.target.value;render();}
 if(e.target.closest('#product-form')&&['unit','billing_unit'].includes(e.target.name)){
  const f=$('#product-form'),unit=f.elements.unit.value,pack=unit!=='筐',bill=f.elements.billing_unit;
  if(e.target.name==='unit'){bill.innerHTML='<option value="公斤">公斤（kg）</option>'+(unit==='公斤'?'':`<option value="${esc(unit)}">${esc(unit)}（按实发数量）</option>`);}
  $('#product-price-unit').textContent=bill.value;$('#product-pack-field').hidden=!pack||bill.value!=='公斤';f.elements.tare.readOnly=pack;if(pack)f.elements.tare.value='0';if(unit==='公斤')f.elements.standard_kg.value='1';
 }
});

// Editing state stays in memory until an explicit or timed server save.
function scheduleDraftSave(){}
function persistDrafts(){}
function restoreInputDrafts(){}
function businessColumnAlignment(label){return /备注|说明|原因|用途|描述|处理意见|反馈内容|操作内容/.test(label)?'left':'center';}
function businessTableGrid(rows){
 const grid=[];
 for(let r=0;r<rows.length;r++){
  grid[r]||=[];let column=0;
  for(const cell of rows[r].cells){
   while(grid[r][column])column++;
   const width=Math.max(1,cell.colSpan||1),height=cell.rowSpan===0?rows.length-r:Math.max(1,cell.rowSpan||1);
   for(let y=r;y<Math.min(rows.length,r+height);y++){grid[y]||=[];for(let x=column;x<column+width;x++)grid[y][x]=cell;}
   column+=width;
  }
 }
 return grid;
}
function alignBusinessTable(table){
 const headers=table.tHead?businessTableGrid(table.tHead.rows).at(-1)||[]:[];
 if(table.tHead)for(const row of table.tHead.rows)for(const cell of row.cells)cell.dataset.align='center';
 for(const section of [...table.tBodies,...(table.tFoot?[table.tFoot]:[])]){
  const grid=businessTableGrid(section.rows);
  for(let r=0;r<section.rows.length;r++)for(const cell of section.rows[r].cells){
   const column=grid[r].indexOf(cell),label=headers[column]?.textContent||'';
   cell.dataset.align=cell.colSpan>1||table.matches('.matrix')?'center':businessColumnAlignment(label);
  }
 }
}
function alignBusinessTables(root){for(const table of [...(root.matches?.('table')?[root]:[]),...root.querySelectorAll('table')])alignBusinessTable(table);watchMobileTables(root);}

document.addEventListener('change',e=>{if(e.target.id==='product-main-filter'){productMainFilter=e.target.value;render();}});

// Adapt only genuinely wide/long tables; preserve the existing mobile card forms.
// Only structural/width changes schedule work. Scrolling and browser chrome
// height changes never remeasure every table or rewrite its cells.
let mobileTableFrame=0,mobileTableObserver=null,mobileTableMutation=null,mobileTableWidth=typeof window!=='undefined'?window.innerWidth:0;
const mobileTableQueue=new Set(),mobileTableWatched=new Set(),mobileTableStates=new WeakMap();
function scheduleMobileTables(wrap){if(wrap?.matches?.('.table-wrap'))mobileTableQueue.add(wrap);else for(const w of mobileTableWatched)mobileTableQueue.add(w);if(mobileTableFrame||!mobileTableQueue.size||typeof requestAnimationFrame!=='function')return;mobileTableFrame=requestAnimationFrame(()=>{mobileTableFrame=0;updateMobileTables();});}
function watchMobileTables(root=document){
 if(typeof ResizeObserver==='function'&&!mobileTableObserver)mobileTableObserver=new ResizeObserver(entries=>{for(const entry of entries){const state=mobileTableStates.get(entry.target),width=entry.contentRect.width;if(state&&state.width!==width){state.width=width;scheduleMobileTables(entry.target);}}});
 if(typeof MutationObserver==='function'&&!mobileTableMutation){mobileTableMutation=new MutationObserver(records=>{const changedTables=new Set();for(const r of records){const table=r.target.closest?.('table');if(table)changedTables.add(table);for(const node of r.addedNodes)if(node.nodeType===1){if(node.matches('table'))changedTables.add(node);for(const added of node.querySelectorAll('table'))changedTables.add(added);}if(table&&(r.target.matches?.('table,thead,tbody,tfoot,tr')||r.target.closest?.('thead')))scheduleMobileTables(table.closest('.table-wrap'));for(const node of r.addedNodes)if(node.nodeType===1&&(node.matches('.table-wrap,table')||node.querySelector('.table-wrap')))watchMobileTables(node.matches('table')?node.parentElement:node);}for(const table of changedTables)alignBusinessTable(table);});for(const scope of document.querySelectorAll('#content,#dialog-body'))mobileTableMutation.observe(scope,{childList:true,subtree:true});}
 for(const wrap of mobileTableWatched)if(!wrap.isConnected){mobileTableObserver?.unobserve(wrap);mobileTableWatched.delete(wrap);mobileTableQueue.delete(wrap);}
 const wraps=[...(root.matches?.('.table-wrap')?[root]:[]),...root.querySelectorAll('.table-wrap')];for(const wrap of wraps){if(!wrap.querySelector(':scope > table'))continue;if(!mobileTableWatched.has(wrap)){mobileTableWatched.add(wrap);mobileTableStates.set(wrap,{width:undefined,keys:new Set(),heads:new Set(),toggle:null});mobileTableObserver?.observe(wrap);}scheduleMobileTables(wrap);}
}
function updateMobileTables(){const mobile=matchMedia('(max-width:760px)').matches,wraps=[...mobileTableQueue].filter(w=>w.isConnected);mobileTableQueue.clear();const plans=[];
 // Set responsive column widths first, then read geometry in one phase.
 for(const wrap of wraps){const table=wrap.querySelector(':scope > table'),state=mobileTableStates.get(wrap);if(!table||!state)continue;const head=table.tHead,displayed=!!head&&getComputedStyle(table).display==='table'&&getComputedStyle(head).display!=='none',shown=mobile&&displayed,headers=shown?[...head.rows[0].cells].filter(c=>getComputedStyle(c).display!=='none'):[];
 let pageHead=false;if(!mobile&&displayed&&wrap.closest('#content')&&[...head.querySelectorAll('th,td')].some(c=>{const style=getComputedStyle(c);return style.position==='sticky'&&style.top!=='auto';})){let ancestor=wrap;while(ancestor&&ancestor!==document.documentElement){if(/auto|scroll|hidden/.test(getComputedStyle(ancestor).overflowY))break;ancestor=ancestor.parentElement;}pageHead=ancestor===document.documentElement;}
 const count=shown?Math.max(...[...head.rows].map(r=>[...r.cells].reduce((n,c)=>n+(getComputedStyle(c).display==='none'?0:c.colSpan),0))):0,generic=!table.matches('.worksheet,.warehouse-stock,.monthly-attendance-table,.factory-list-table,.factory-report-table')&&!wrap.classList.contains('driver-delivery-matrix');
 table.classList.toggle('erp-table-large',shown&&generic&&count>=7);table.classList.toggle('erp-table-medium',shown&&generic&&count>=5&&count<7);plans.push({wrap,table,state,head,shown,headers,pageHead});}
 for(const p of plans){const {wrap,table,shown,head,headers,pageHead}=p,rect=shown?table.getBoundingClientRect():null;p.wide=shown&&wrap.clientWidth>0&&rect.width>wrap.clientWidth+2;p.long=shown&&[...table.tBodies].reduce((n,b)=>n+b.rows.length,0)>12&&rect.height>480;p.key=p.wide?(headers.find(c=>/客户|产品|物料|库房|姓名|员工|名称|供应商|日期|收款方|流程|方法/.test(c.textContent))||headers.find(c=>!/^\s*(序|序号|顺序)\s*$/.test(c.textContent))||headers[0]):null;
 p.offsets=[];if(shown||pageHead){let offset=0;for(const row of head.rows){p.offsets.push(offset);offset+=row.getBoundingClientRect().height;}}}
 for(const {wrap,table,state,head,shown,wide,long,key,offsets,pageHead} of plans){
 if(long&&!state.toggle){const button=document.createElement('button');button.type='button';button.className='text-button table-header-toggle';button.textContent='固定表头浏览';button.setAttribute('aria-pressed','false');wrap.before(button);state.toggle=button;button.addEventListener('click',()=>{const on=wrap.classList.toggle('erp-table-contained');button.textContent=on?'返回整页浏览':'固定表头浏览';button.setAttribute('aria-pressed',String(on));wrap.scrollTop=0;scheduleMobileTables(wrap);});}
 if(state.toggle){state.toggle.hidden=!long;if(!long){wrap.classList.remove('erp-table-contained');state.toggle.setAttribute('aria-pressed','false');state.toggle.textContent='固定表头浏览';}}
 const active=wide||long;wrap.classList.toggle('mobile-scroll-table',active);wrap.classList.toggle('erp-horizontal',wide);
 if(active){if(!wrap.hasAttribute('tabindex')){wrap.tabIndex=0;wrap.dataset.erpAutoTab='1';}if(!wrap.hasAttribute('aria-label')||wrap.dataset.erpAutoLabel){const title=wrap.closest('.panel,.client-sheet')?.querySelector('h2,h3')?.textContent||'业务表格';wrap.setAttribute('role','region');wrap.setAttribute('aria-label',title+(wide?'，可左右滑动，关键列固定':'')+(wrap.classList.contains('erp-table-contained')?'，表内上下滑动，表头固定':'，上下随页面浏览'));wrap.dataset.erpAutoLabel='1';}}
 else{wrap.classList.remove('erp-table-contained');if(wrap.dataset.erpAutoLabel){wrap.removeAttribute('aria-label');wrap.removeAttribute('role');delete wrap.dataset.erpAutoLabel;}if(wrap.dataset.erpAutoTab){wrap.removeAttribute('tabindex');delete wrap.dataset.erpAutoTab;}}
 const heads=new Set();if((shown&&active)||pageHead)for(const [i,row] of [...head.rows].entries())for(const cell of row.cells){heads.add(cell);cell.classList.toggle('erp-sticky-head',shown&&active);cell.classList.toggle('erp-page-head',pageHead);const offset=offsets[i]+'px';if(cell.style.getPropertyValue('--erp-header-offset')!==offset)cell.style.setProperty('--erp-header-offset',offset);}
 for(const cell of state.heads)if(!heads.has(cell)){cell.classList.remove('erp-sticky-head','erp-page-head');cell.style.removeProperty('--erp-header-offset');}state.heads=heads;
 const keys=new Set();if(key){keys.add(key);for(const body of [...table.tBodies,...(table.tFoot?[table.tFoot]:[])])for(const row of body.rows){if([...row.cells].some(c=>c.colSpan>1)||row.classList.contains('matrix-market-heading'))continue;const cell=row.cells[key.cellIndex];if(cell)keys.add(cell);}}
 for(const cell of state.keys)if(!keys.has(cell))cell.classList.remove('erp-sticky-key');for(const cell of keys)if(!cell.classList.contains('erp-sticky-key'))cell.classList.add('erp-sticky-key');state.keys=keys;
 }}
if(typeof window!=='undefined')window.addEventListener('resize',()=>{if(window.innerWidth===mobileTableWidth)return;mobileTableWidth=window.innerWidth;scheduleMobileTables();},{passive:true});

function resetPricingRule(cid,pid){
 if(busy||!needPermission(masterPermission()))return;
 const rule=data.rules.find(r=>r.customer_id===cid&&r.product_id===pid);
 if(!rule)return;
 const customer=data.customers.find(c=>c.id===cid),product=data.products.find(p=>p.id===pid);
 const unit=product?billingUnit(product):'';
 openDialog('恢复产品默认价',`<p>删除 <b>${esc(customer?.name||cid)}</b> 在 <b>${esc(product?.name||pid)}</b> 上的客户专属价 <b>${esc(rule.price)} 元/${esc(unit)}</b>，之后新单按产品默认价计算。</p><p class="help-text">已保存的历史单据保留原有单价快照，不受影响；本次操作会写入审计。</p>`,'客户专属价格',`<button class="button" data-act="close">取消</button><button class="button primary" data-confirm-pricing-reset="${esc(cid)}|${esc(pid)}">确认恢复默认价</button>`);
}
async function confirmResetPricing(cid,pid){
 const rule=data.rules.find(r=>r.customer_id===cid&&r.product_id===pid);if(!rule)return;
 closeDialog();busy=true;
 try{await api('/api/master',{kind:'rule',customer_id:cid,product_id:pid,action:'reset',expected:{price:rule.price,tare:rule.tare}});pricingDrafts.delete(cid+'|'+pid);data=await api('/api/bootstrap');render();notify('已恢复产品默认价');}
 catch(e){const target=$('#master-error');if(target){target.textContent=e.message;target.hidden=false;target.scrollIntoView({block:'nearest'});}else notify(e.message);}
 finally{busy=false;}
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-pricing-reset]');if(b)resetPricingRule(b.dataset.cid,b.dataset.pid);const c=e.target.closest('[data-confirm-pricing-reset]');if(c){const [cid,pid]=c.dataset.confirmPricingReset.split('|');confirmResetPricing(cid,pid);}});
