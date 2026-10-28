'use strict';
// Suggestions edit only the selected text field; the existing submit flow owns saving.
const notePresetFields=new WeakMap(),notePresetButtons=new WeakMap(),notePresetEdits=new WeakMap();
const NOTE_PRESET_SELECTOR='textarea,input[type="text"],input:not([type])';
function notePresetEligible(field){
 if(!field.matches(NOTE_PRESET_SELECTOR)||!field.required)return false;
 const key=field.name||field.dataset.field||field.dataset.key||'';
 return /^(note|reason|reason_detail|source_detail|line_note|variance_reason|loss_reason|source_note)$/.test(key)||field.hasAttribute('data-client-reason')||field.hasAttribute('data-reason')||field.matches('[data-wfield="note"]');
}
function notePresetChoices(field){
 const form=field.closest('form'),id=form?.id||'',kind=form?.dataset.kind||'',name=field.name||field.dataset.field||field.dataset.key||'',title=field.closest('#dialog')?(document.querySelector('#dialog-title')?.textContent||''):'';
 if(id==='factory-form'&&kind==='beans')return ['补登当天上豆量','按实际称量更正','录入数量有误，重新核对'];
 if(id==='parameter-request-form')return ['标准规格调整','依据近期称重记录调整','生产工艺调整'];
 if(id==='parameter-review-form')return ['修改依据不充分，请补充','参数已更新，请重新申请','当前参数仍适用'];
 if(name==='reason_detail')return ['包装破损','品质异常','客户退货'];
 if(name==='source_detail')return ['依据补充送货记录登记','依据双方留存凭据登记'];
 if(name==='loss_reason')return ['生产损耗，按实物报损','包装破损导致损耗','搬运破损，按实际报损'];
 if(name==='line_note')return ['规格已确认','按约定包装供货','随本批次到货'];
 if(id==='return-review-form'||id==='return-retract-form')return ['数量需重新核对','单价需重新核对','原始凭据需补充'];
 if(field.hasAttribute('data-reason')||name==='variance_reason')return ['盘点漏记，按实盘调整','录入数量有误，按实际更正','实物损耗，已复核'];
 if(field.hasAttribute('data-client-reason')||id==='settle-form')return ['已核对结算依据','按双方确认的净重结算','按复核后的称重记录结算'];
 if(name==='reason'||/作废|撤销|归档清理/.test(title))return ['重复登记，保留有效原单','录入有误，重新登记','业务取消，保留处理记录'];
 if(id==='purchase-form')return ({
  supplier:['合作信息已确认','供货及联系信息已核对'],order:['采购需求已确认','按约定数量和价格采购'],confirm:['采购信息已核对','数量与单价已确认'],
  receipt:['实收数量与送货单一致','验收信息已确认'],payment:['已核对付款凭据','本次付款信息已确认'],'charge-payment':['已核对费用付款凭据','本次费用付款信息已确认'],
  close:['本次不再采购剩余数量','未到货部分已取消'],warehouse:['已按实际存放库房核对','历史库房归属已确认'],charge:['费用按实际重量和单价登记','费用凭据已核对']
 })[kind]||['已确认','已核对相关信息'];
 if(id==='resource-form'){
  if(kind==='material')return ({opening:['已核对期初库存','按期初盘点记录登记'],receipt:['已核对送货单与实收数量','本次入库信息已确认'],consume:['按实际生产领用登记','领用数量已确认'],return:['按实际退回数量登记','退回物料信息已核对'],loss:['按实际损耗登记','报损数量已核对'],count:['盘点漏记，按实盘调整','录入数量有误，按实际更正'],transfer:['库间调拨，数量已核对','按实际调拨数量登记']})[form.elements.kind?.value]||['已确认','数量已核对'];
  if(kind==='period')return form.elements.state?.value==='closed'?['本月成本已核对，确认结账','本月凭据已核对完整']:['补录成本，重新打开月份','核对差异后重新处理'];
  return ({expense:['按实际费用凭据登记','费用归属与金额已核对'],byproduct:['按实际重量与约定价格登记','本次豆渣销售信息已核对'],receive:['已核对到账凭据','本次收款信息已确认'],value:['按实际采购凭据补录金额','按核对后的入库金额更正']})[kind]||['已确认','已核对相关信息'];
 }
 if(id==='receipt-form')return ['已核对到账凭据','微信到账已核实','尾款抹零处理'];
 if(/review/.test(id)||/复核/.test(title)&&form)return ['已对照原始凭据核对','数量与金额已核对','复核情况已确认'];
 if(/refund/.test(id)||/退款/.test(title)&&form)return ['已核对退款凭据','本次退款信息已确认'];
 if(id==='customer-form')return ['收货信息已确认','按约定配送'];
 if(id==='statement-issue-form')return ['账款明细已核对','本次结算范围已确认'];
 if(field.hasAttribute('data-allocation-customer'))return ['按订货数量安排发货','按实际库存调整分配','按约定安排发货'];
 if(field.hasAttribute('data-dispatch-trip')||field.hasAttribute('data-dispatch-market'))return ['配送安排已确认','按约定时间配送'];
 return ['已确认','已核对相关信息','按实际情况登记'];
}
function notePresetContext(field){const label=field.closest('label');if(label){const text=[...label.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim();if(text)return text;}return field.getAttribute('aria-label')||field.getAttribute('placeholder')||'补充信息';}
function refreshNotePreset(field,entry){
 const disabled=field.readOnly||field.matches(':disabled'),choices=notePresetChoices(field),signature=JSON.stringify(choices);entry.group.hidden=disabled;
 if(entry.signature===signature)return;entry.signature=signature;entry.buttons.replaceChildren();
 for(const value of choices){const button=document.createElement('button');button.type='button';button.className='note-preset-button';button.dataset.noteSuggestion=value;button.textContent=value;button.setAttribute('aria-label',`填入${entry.label}：${value}`);notePresetButtons.set(button,field);entry.buttons.append(button);}
}
function enhanceNotePresets(root){
 const fields=[...(root.matches?.(NOTE_PRESET_SELECTOR)?[root]:[]),...(root.querySelectorAll?.(NOTE_PRESET_SELECTOR)||[])];
 for(const field of fields){let entry=notePresetFields.get(field);if(!notePresetEligible(field)){entry?.group.remove();notePresetFields.delete(field);continue;}
  if(!entry||!entry.group.isConnected){const group=document.createElement('span'),label=document.createElement('span'),buttons=document.createElement('span'),status=document.createElement('span');group.className='note-presets';label.className='note-preset-label';label.textContent='常用填写';buttons.className='note-preset-buttons';status.className='note-preset-status';status.setAttribute('aria-live','polite');group.append(label,buttons,status);entry={group,buttons,status,label:notePresetContext(field)};notePresetFields.set(field,entry);field.insertAdjacentElement('afterend',group);}
  refreshNotePreset(field,entry);
 }
}
function fillNotePreset(button){const field=notePresetButtons.get(button);if(!field?.isConnected||!notePresetEligible(field)||field.readOnly||field.matches(':disabled'))return;
 const value=button.dataset.noteSuggestion,current=field.value,previous=notePresetEdits.get(field),base=previous&&current===previous.result?previous.before:current;
 if(base.split(/[；\n]/).some(part=>part.trim()===value)){field.focus();return;}
 const next=base.trim()?base+( /[；\n]$/.test(base)?'':'；')+value:value,entry=notePresetFields.get(field);
 if(field.maxLength>=0&&next.length>field.maxLength){entry.status.textContent='内容超过字数限制，请先精简已有文字';return;}
 field.value=next;notePresetEdits.set(field,{before:base,result:next});entry.status.textContent='已填入，可继续修改';
 field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));
 if(field.isConnected){field.focus();field.setSelectionRange?.(field.value.length,field.value.length);}
}
document.addEventListener('click',event=>{const button=event.target.closest('[data-note-suggestion]');if(button){event.preventDefault();fillNotePreset(button);}});
document.addEventListener('change',event=>{if(event.target.closest('#resource-form,#purchase-form'))enhanceNotePresets(event.target.closest('form'));});
function startNotePresets(){const roots=[...document.querySelectorAll('.shell,#dialog-body')];if(!roots.length)return;for(const root of roots)enhanceNotePresets(root);
 const observer=new MutationObserver(records=>{for(const mutation of records){if(mutation.type==='attributes'){enhanceNotePresets(mutation.target);continue;}for(const node of mutation.addedNodes)if(node.nodeType===Node.ELEMENT_NODE)enhanceNotePresets(node);}});
 for(const root of roots)observer.observe(root,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','readonly','required']});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',startNotePresets,{once:true});else startNotePresets();
