'use strict';
// Business edits live only in the active editor. Leaving resolves them explicitly.
let navigationBypass=false,navigationPending=null,navigationLoading=false,dialogBaseline='';
function dialogValues(){const form=$('#dialog-body form');if(form?.id==='driver-return-form')return JSON.stringify({fields:[...form.querySelectorAll('input,select,textarea')].map(el=>[el.name,el.value,el.checked]),photos:[...form.querySelectorAll('figure')].map(el=>el.dataset.driverPhotoKind||el.dataset.driverPhotoToken)});if(form?.id==='asset-form'&&form.dataset.kind==='return-batch'&&typeof warehouseReturnDialogValues==='function')return warehouseReturnDialogValues(form);if(form?.id==='factory-form'&&['attendance','schedule'].includes(form.dataset.kind)&&typeof factoryAttendanceDialogValues==='function')return factoryAttendanceDialogValues(form);return form?JSON.stringify([...form.querySelectorAll('input,select,textarea')].map(el=>[el.name,el.dataset,el.value,el.checked,el.disabled])):'';}
function dialogDirty(){return !$('#overlay').hidden&&!!dialogBaseline&&dialogValues()!==dialogBaseline;}
function unsavedChanges(dialogOnly=false){const rows=[];if(dialogDirty())rows.push('当前窗口的表单');if(dialogOnly)return rows;
 if(typeof driverArrivalDirty==='function')rows.push(...driverArrivalDirty());
 const matrices=[...matrixRows.values()].filter(matrixDirty).length,orders=[...sheetOrders.values()].filter(orderDirty).length,pricing=[...pricingDrafts.values()].filter(pricingDirty).length;
 if(matrices)rows.push(`订货数量 · ${matrices} 位客户 / 原单`);if(orders)rows.push(`实发、称重或单价 · ${orders} 张单据`);if(decisionDirty.size)rows.push('计价依据 / 协商说明（需在本页确认算票）');
 if(pricing)rows.push(`客户专属价格 / 皮重 · ${pricing} 项`);if(productOrderDirty())rows.push('产品显示顺序');
 if([...dispatchDrafts.keys()].some(dispatchDirty))rows.push('配送车辆、司机或市场安排');if([...warehouseDrafts.keys()].some(warehouseDirty))rows.push('库存盘点或客户分配');return rows;
}
function clearWorkingCopies(){sheetOrders.clear();sheetBaselines.clear();matrixRows.clear();lineChoices.clear();clientReasons.clear();decisionDirty.clear();pricingDrafts.clear();productOrderDraft=null;dispatchDrafts.clear();warehouseDrafts.clear();visibleIssues=[];sheetError='';warehouseError='';dispatchError='';}
function latestSaveError(){for(const id of ['dialog-error','sheet-error','warehouse-error','dispatch-error','master-error']){const box=$('#'+id);if(box&&!box.hidden&&box.textContent.trim())return box.textContent.trim();}return '还有未保存的改动，请核对填写问题后重试。';}
async function saveActiveDialog(){const form=$('#dialog-body form');if(form?.id==='person-month-form')throw Error('整月考勤需要核对后确认，请返回考勤窗口保存，或选择放弃修改。');if(['company-info-form','employee-bank-form','employee-bank-import-form','cost-category-form','cost-expense-form','goods-stock-form','finished-form','supplier-category-form'].includes(form?.id))throw Error('请在当前窗口核对后点击确认按钮提交。');if(form?.id==='funds-form')throw Error('账户维护、流水关联及转账请在当前窗口核对后点击对应确认按钮。');if(form?.id==='byproduct-price-form')return byproductSettleAction('price');if(form?.id==='byproduct-settings-form')return saveByproductSettings();if(form?.id==='parameter-request-form')return submitParameterRequest();if(['parameter-review-form','production-config-form'].includes(form?.id))throw Error('审批与配置发布请返回当前窗口，核对后点击对应确认按钮。');if(form?.id==='soy-quality-form')return saveSoyQuality();if(form?.id==='payroll-form')throw Error('工资核算与发放请返回当前窗口，使用对应的保存或确认按钮提交。');if(form?.id==='factory-form')return factorySave();if(form?.id==='asset-form')return assetSave();if(form?.id==='driver-return-form')return submitDriverReturn('draft');if(form?.id==='driver-weight-form')return saveDriverWeights();if(['business-reset-form','restore-day-form','expense-action-form','payroll-form','purchase-form','resource-form','settle-form','review-form','review-client-form','return-review-form','byproduct-statement-form','statement-issue-form','statement-batch-form','receipt-form','return-account-form','return-review-form','return-refund-form','return-retract-form','dispatch-confirm-form','factory-form'].includes(form?.id))throw Error('实发确认、算票、退货核定、复核和收退款请返回当前窗口，使用对应的确认按钮提交。');const button=$('#dialog .dialog-actions .primary');if(!button)throw Error('请在当前窗口完成确认，或选择放弃修改。');
 if(button.hasAttribute('data-role-permissions-save'))await saveRolePermissions();else if(button.hasAttribute('data-user-save'))await saveManagedUser();else if(button.dataset.inventoryAct)await inventoryAction(button.dataset.inventoryAct,button);else if(button.dataset.act)await action(button.dataset.act,button);else if(button.dataset.masterAction)await masterAction(button.dataset.masterAction,button);else if(button.dataset.fleetAct)await fleetAction(button.dataset.fleetAct,button);else if(button.dataset.dispatchAct)await dispatchAction(button.dataset.dispatchAct,button);
 if(!$('#overlay').hidden)throw Error(latestSaveError());
}
async function saveCurrentEdits({dialogOnly=false}={}){
 if(busy)throw Error('正在保存，请稍候。');
 if(dialogDirty())await saveActiveDialog();
 if(dialogOnly)return true;
 if(typeof driverArrivalDirty==='function'&&driverArrivalDirty().length)throw Error('请分别点击“称重”或“框子”保存后再离开，或明确放弃本页修改。');
 if(decisionDirty.size)throw Error('计价依据和协商说明需在本页点击“确认本客户算票”。请返回完成确认，或明确放弃修改。');
 if(page==='orders'&&[...matrixRows.values()].some(matrixDirty))await sheetAction('save',{});
 else if(['weighing','settlements'].includes(page)&&[...sheetOrders.values()].some(orderDirty))await sheetAction('save',{});
 else if(page==='allocation'&&warehouseDirty(sheetDate()))await warehouseAction('save');
 else if(page==='dispatch'&&dispatchDirty(dispatchDate()))await dispatchAction('save',{});
 else if(page==='masters'&&masterView==='pricing'&&[...pricingDrafts.values()].some(pricingDirty))await masterAction('save-pricing',{});
 else if(page==='masters'&&masterView==='products'&&productOrderDirty())await masterAction('save-product-order',{});
 const remaining=unsavedChanges();
 if(remaining.length)throw Error(latestSaveError());return true;
}
function leaveOverlay(){let overlay=$('#leave-overlay');if(!overlay){overlay=document.createElement('div');overlay.id='leave-overlay';overlay.hidden=true;overlay.innerHTML='<section class="leave-dialog" role="dialog" aria-modal="true" aria-labelledby="leave-title"><h2 id="leave-title">离开前保存修改？</h2><p>以下内容尚未写入服务器：</p><ul id="leave-changes"></ul><p>保存成功后继续；若数据已被其他页面修改，将留在当前页核对。</p><div id="leave-error" class="leave-error" role="alert" hidden></div><div class="leave-actions"><button class="button" data-leave-choice="stay">继续编辑</button><button class="button danger" data-leave-choice="discard">放弃并离开</button><button class="button primary" data-leave-choice="save">保存并继续</button></div></section>';document.body.append(overlay);}return overlay;}
function finishLeavePrompt(){const overlay=$('#leave-overlay');if(overlay)overlay.hidden=true;navigationPending=null;}
async function completeTransition(pending){navigationLoading=true;$('#content').setAttribute('inert','');try{
 if(!pending.dialogOnly){const fresh=await api('/api/bootstrap');const users=fresh.auth_user?.role==='管理员'?await api('/api/users'):null;data=fresh;if(users)managedUsers=users;clearWorkingCopies();render();if(typeof resetSaveStatus==='function')resetSaveStatus();}
 let result;navigationBypass=true;try{result=pending.run();}finally{navigationBypass=false;}await result;
 finishLeavePrompt();if(typeof clearOperationFeedback==='function')clearOperationFeedback();
 }finally{navigationLoading=false;$('#content').removeAttribute('inert');}}
function showLeaveError(error){const box=$('#leave-error');if(box){showOperationError(error,box);}else showOperationError(error);}
async function requestPageTransition(run,{dialogOnly=false}={}){
 if(navigationBypass)return run();if(navigationPending||navigationLoading)return;if(busy){notify('正在保存，请稍后跳转');return;}
 const pending={run,dialogOnly};if(!unsavedChanges(dialogOnly).length){try{await completeTransition(pending);}catch(error){showOperationError(error);}return;}
 navigationPending=pending;const overlay=leaveOverlay();$('#leave-changes').innerHTML=unsavedChanges(dialogOnly).map(label=>`<li>${esc(label)}</li>`).join('');$('#leave-error').hidden=true;overlay.hidden=false;overlay.querySelector('[data-leave-choice="stay"]').focus();
}
async function choosePageTransition(choice){const pending=navigationPending;if(!pending)return;if(choice==='stay'){finishLeavePrompt();return;}
 const buttons=$$('#leave-overlay button');buttons.forEach(b=>b.disabled=true);
 try{if(choice==='save')await saveCurrentEdits({dialogOnly:pending.dialogOnly});await completeTransition(pending);}
 catch(error){showLeaveError(error);}finally{buttons.forEach(b=>b.disabled=false);}
}
function navigationTarget(event){const el=event.target;
 if(event.type==='keydown')return event.key==='Escape'&&!$('#overlay').hidden?{element:$('#dialog-close'),dialogOnly:true}:null;
 if(event.type==='change'&&el.matches('#role,#sheet-date,#sheet-route,#sheet-trip,#sheet-status,#business-date-filter,#warehouse-date,#dispatch-date,#pricing-route,#range-basis,#factory-date,#resource-month,#purchase-month,#attendance-month,#payroll-month'))return {element:el};
 if(event.type==='submit'&&el.matches('[data-range-form]'))return {element:el};
 if(event.type!=='click')return null;
 const target=el.closest('[data-people-scope="employee"][data-people-filter="view"],[data-purchase-act],[data-page],[data-master-tab],[data-price-mode],[data-sheet-action],[data-dispatch-act],[data-warehouse-act],[data-master-action],[data-act],[data-fleet-act],[data-range-act],[data-print-draft-kind],[data-inventory-act],[data-warehouse-tab],[data-dispatch-tab],[data-settlement-stage],[data-return-stage],#dialog-close,.brand');
 if(el.id==='overlay')return {element:el,dialogOnly:true};if(!target)return null;
 if(target.id==='dialog-close'||target.dataset.act==='close')return {element:target,dialogOnly:true};
 const ds=target.dataset;if(ds.peopleScope==='employee'&&ds.peopleFilter==='view')return {element:target};
 if(ds.purchaseAct&&ds.purchaseAct!=='add-line'&&ds.purchaseAct!=='remove-line'&&ds.purchaseAct!=='save')return {element:target};
 if(['new-return','account','review','refund','dispose','void','retract','process','close'].includes(ds.inventoryAct))return {element:target};
 if(ds.warehouseTab||ds.dispatchTab||ds.settlementStage||ds.returnStage)return {element:target};
 if(ds.page||ds.masterTab||ds.priceMode||ds.printDraftKind||target.matches('.brand'))return {element:target};
 if(['today','all-dates','focus-order','open-pending-order','archive','reload','pending-account','account-client','weight-client'].includes(ds.sheetAction)||['today','open-trip','open-pickup','reload'].includes(ds.dispatchAct)||['orders','reload'].includes(ds.warehouseAct)||['reload-product-order','new-product','edit-product'].includes(ds.masterAction)||['new','edit'].includes(ds.fleetAct)||['configure-permissions','batch-statements','edit-operator-user','export-statement','pending-settlements','new','rule','today','all-dates','todo','edit','customer','settle','review','receipt'].includes(ds.act)||['quick','day','day-prev','day-next','month','month-prev','month-next','apply','rolling'].includes(ds.rangeAct))return {element:target};return null;
}
function replayNavigation(target,event){const original=target.element,ds={...original.dataset},id=original.id,type=event.type;
 const selector=id?'#'+CSS.escape(id):original.tagName.toLowerCase()+Object.entries(ds).map(([k,v])=>'[data-'+k.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())+'="'+CSS.escape(v)+'"]').join('');
 const values=original.matches('input,select,textarea')?{value:original.value,checked:original.checked}:null;
 const controls=type==='submit'?[...original.querySelectorAll('input,select')].map(el=>({id:el.id,value:el.value})):[];
 if(values){if(id==='role')original.value=role;else if(original.matches('select'))original.value=[...original.options].find(o=>o.defaultSelected)?.value||original.options[0]?.value||'';else original.value=original.defaultValue;}
 return async()=>{const el=document.querySelector(selector)||original;
  if(target.dialogOnly){closeDialog();return;}
  if(values){el.value=values.value;if(values.checked!==undefined)el.checked=values.checked;el.dispatchEvent(new Event(type,{bubbles:true}));return;}
  if(type==='submit'){for(const c of controls){const input=c.id&&$('#'+CSS.escape(c.id));if(input)input.value=c.value;}el.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));return;}
  if(ds.warehouseTab){warehouseTab=ds.warehouseTab;render();return;}if(ds.dispatchTab){dispatchTab=ds.dispatchTab;render();return;}if(ds.settlementStage){sheetStatus=ds.settlementStage;render();return;}if(ds.returnStage){returnStage=ds.returnStage;render();return;}
  if(ds.peopleScope==='employee'&&ds.peopleFilter==='view'){el.click();return;}
  if(ds.page){if(ds.page==='settlements'&&page!==ds.page)sheetStatus=canAction('finance.settle')||canAction('finance.review')?'todo':'all';goto(ds.page);return;}if(ds.masterTab){masterView=ds.masterTab;goto('masters',{keepTabs:true});return;}if(ds.priceMode){pricingMode=ds.priceMode;render();return;}
  if(ds.purchaseAct)return purchaseAction(ds.purchaseAct,el);
  if(ds.inventoryAct)return inventoryAction(ds.inventoryAct,el);if(ds.sheetAction)return sheetAction(ds.sheetAction,el);if(ds.dispatchAct)return dispatchAction(ds.dispatchAct,el);if(ds.warehouseAct)return warehouseAction(ds.warehouseAct);if(ds.masterAction)return masterAction(ds.masterAction,el);if(ds.fleetAct)return fleetAction(ds.fleetAct,el);if(ds.act)return action(ds.act,el);if(ds.rangeAct)return rangeAction(ds.rangeAct,el);if(ds.printDraftKind)return openPrintDraft(ds.printDraftKind,ds.printDraftKey);if(el.matches('.brand'))goto('orders');
 };
}
function capturePageTransition(event){if(navigationBypass||isTextComposing(event))return;
 const leave=$('#leave-overlay');if(leave&&!leave.hidden){if(event.type==='keydown'&&event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();choosePageTransition('stay');}else if(event.type==='keydown'&&event.key==='Tab'){const controls=$$('button:not(:disabled)',leave),at=controls.indexOf(document.activeElement),next=controls[(at+(event.shiftKey?-1:1)+controls.length)%controls.length];event.preventDefault();event.stopImmediatePropagation();next?.focus();}return;}
 const target=navigationTarget(event);if(!target)return;if(target.dialogOnly&&!unsavedChanges(true).length)return;
 event.preventDefault();event.stopImmediatePropagation();const run=replayNavigation(target,event);requestPageTransition(run,{dialogOnly:!!target.dialogOnly});
}
for(const type of ['click','change','input','submit','keydown'])document.addEventListener(type,capturePageTransition,true);
document.addEventListener('click',event=>{const button=event.target.closest('[data-leave-choice]');if(button){event.preventDefault();choosePageTransition(button.dataset.leaveChoice);}});

window.addEventListener('beforeunload',event=>{if(unsavedChanges().length){event.preventDefault();event.returnValue='';}});
