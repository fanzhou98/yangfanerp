'use strict';
// Compatibility asset name; save status only: all business edits require an explicit save or confirmation.
let saveIssue='',lastServerSave='',lastSavedPage='';
function setSaveText(el,text){if(el&&el.textContent!==text)el.textContent=text;}
function updateSaveStatus(){
 const el=$('#save-status');if(!el||typeof data==='undefined'||!data)return;
 const dirty=unsavedChanges(),readOnly=typeof role!=='undefined'&&role==='老板';
 const manualHint=(dirty.some(label=>label.startsWith('计价依据'))?'计价依据需确认算票。 ':'')+(dirty.includes('当前窗口的表单')?'当前窗口需手动保存或确认。 ':'');
 const savedHere=lastServerSave&&lastSavedPage===(typeof page==='undefined'?'':page);
 const state=saveIssue?'error':dirty.length?'dirty':'saved';
 const text=readOnly?'当前为只读查看':saveIssue?'保存遇到问题，请核对下方提示':dirty.length?'有未保存修改，请点击保存按钮':savedHere?'本页改动已保存 · '+lastServerSave:'当前没有未保存修改';
 el.dataset.state=state;setSaveText(el,text);
 const compact=$('#compact-save-status');if(compact){compact.dataset.state=state;compact.hidden=!readOnly&&!saveIssue&&!dirty.length&&!savedHere;setSaveText(compact,readOnly?'只读查看':saveIssue?'保存待处理':dirty.length?'有待保存内容':savedHere?'改动已保存':'');compact.title=saveIssue||text;}
 const bar=$('#work-status-bar');if(!bar)return;bar.dataset.state=state;bar.hidden=!saveIssue&&!dirty.length&&!savedHere;
 setSaveText(bar.querySelector('[data-work-save]'),text);
 const filtered=typeof page!=='undefined'&&(page==='masters'?typeof pricingSearch!=='undefined'&&pricingSearch:typeof sheetSearch!=='undefined'&&sheetSearch&&['orders','weighing','settlements'].includes(page));
 const hint=bar.querySelector('[data-work-next]'),hintText=dirty.length?manualHint+(filtered?'查找已隐藏部分行，未保存修改仍保留。':''):'';
 if(typeof refreshWorkflowSignals==='function')refreshWorkflowSignals($('#content'));
 setSaveText(hint,hintText.trim());if(hint)hint.hidden=!hintText.trim();
 let clear=bar.querySelector('[data-clear-editor-search]');if(filtered&&dirty.length&&!clear){clear=document.createElement('button');clear.type='button';clear.className='text-button';clear.dataset.clearEditorSearch='';clear.textContent='清除查找';bar.append(clear);}else if(clear&&(!filtered||!dirty.length))clear.remove();
}
function recordServerSave(){lastSavedPage=typeof page==='undefined'?'':page;lastServerSave=new Date().toLocaleTimeString('zh-CN',{hour12:false});saveIssue='';updateSaveStatus();}
function setSaveIssue(message){saveIssue=message;updateSaveStatus();}
function resetSaveStatus(){saveIssue='';lastServerSave='';lastSavedPage='';updateSaveStatus();}
// Run after the current input/change handlers. This updates text only; it never writes data.
for(const type of ['input','change'])document.addEventListener(type,event=>{if(event.target.closest('#content,#dialog-body'))queueMicrotask(updateSaveStatus);});
