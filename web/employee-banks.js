'use strict';
let employeeBankRows=[],employeeBankFile='',employeeBankPreview=null,employeeBankPersonnelId='';
const maskedEmployeeCard=card=>card?'**** '+card.slice(-4):'未登记';
async function showEmployeeBanks(employeeId='',{personnel=false}={}){
 const result=await api('/api/employee-banks');employeeBankRows=result.rows;employeeBankFile='';employeeBankPreview=null;employeeBankPersonnelId=personnel?employeeId:'';
 if(employeeId){openEmployeeBankEditor(employeeId);return;}
 const edit=canAction('payroll.write');
 openDialog('员工银行卡',`<p class="help-text">按员工编号或姓名维护银行卡；变更不修改历史工资与实际发放记录。</p><div class="head-actions"><a class="button" href="/api/employee-banks?template=1" download="employee-bank-template.xlsx">下载Excel模板</a></div>${edit?'<form id="employee-bank-import-form"><label class="field">选择填写后的Excel<input name="file" id="employee-bank-file" type="file" accept=".xlsx" required></label><p class="help-text">可只填员工姓名和银行卡号，行顺序不限；员工编号留空时按姓名唯一匹配，重名请填编号。开户银行可空，开户姓名默认员工姓名；支行可选。卡号须为文本；空白银行卡行不导入。最多1000行、512KB。</p><button type="submit" class="button">预览导入</button><div id="employee-bank-preview" aria-live="polite"></div></form>':''}${resourceTable(['员工 / 编号','小组 / 岗位','开户银行','开户姓名','银行卡','操作'],factoryPeopleSort(employeeBankRows).map(e=>`<tr><td>${esc(e.name)}<small>${esc(e.id)}</small>${e.active?'':'<small>已停用</small>'}</td><td>${esc(e.group_name||'未分组')}<small>${esc(e.position||'—')}</small></td><td>${esc(e.bank?.bank_name||'—')}</td><td>${esc(e.bank?.account_name||'—')}</td><td>${esc(maskedEmployeeCard(e.bank?.bank_card))}</td><td><button class="text-button" data-employee-bank-edit="${esc(e.id)}">${edit?'维护银行卡':'查看'}</button></td></tr>`).join(''))}`,'员工收款账户','<button class="button" data-act="close">关闭</button>');
}
function openEmployeeBankEditor(eid){
 const e=employeeBankRows.find(e=>e.id===eid);if(!e)return;const b=e.bank||{},edit=canAction('payroll.write');
 openDialog('银行卡 · '+e.name,`<form id="employee-bank-form" data-employee="${esc(e.id)}" data-version="${b.version||0}" data-key="${erpRequestKey()}"><p>${esc(e.id)} · ${esc(e.name)}</p>${resourceField('开户银行','bank_name','text',b.bank_name||'','required maxlength="100"')+resourceField('银行卡号','bank_card','text',b.bank_card||'','required inputmode="numeric" autocomplete="off" maxlength="35"')+resourceField('开户姓名','account_name','text',b.account_name||e.name,'required maxlength="60"')+resourceField('开户支行','bank_branch','text',b.bank_branch||'','maxlength="150"')}</form>`,'员工收款账户',`<button class="button" data-act="close">关闭</button>${employeeBankPersonnelId?'<button type="button" class="button" data-employee-bank-personnel>返回人员档案</button>':''}${edit?'<button class="button primary" data-employee-bank-save>保存银行卡</button>':''}`);
 if(!edit)for(const input of document.querySelectorAll('#employee-bank-form input'))input.readOnly=true;
}
async function previewEmployeeBanks(){
 const input=document.getElementById('employee-bank-file'),file=input.files[0];if(!file)throw Error('请选择Excel文件');if(!/\.xlsx$/i.test(file.name)||file.size>524288)throw Error('请选择512KB以内的.xlsx文件');
 const source=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(Error('读取Excel失败'));r.readAsDataURL(file);});
 const result=await api('/api/factory/employee-bank-preview',{file:source});
 if(input!==document.getElementById('employee-bank-file')||input.files[0]!==file)return;
 employeeBankFile=source;employeeBankPreview=result;
 document.getElementById('employee-bank-preview').innerHTML=`${result.errors.length?'<p class="callout">存在错误，本次不会保存任何银行卡。</p>'+result.errors.map(e=>`<p>第 ${e.row} 行：${esc(e.message)}</p>`).join(''):''}${resourceTable(['员工','变更','原卡尾号','新卡尾号','开户银行','开户姓名'],result.rows.map(r=>`<tr><td>${esc(r.employee_name)}<small>${esc(r.employee_id)}</small></td><td>${esc(r.action)}</td><td>${esc(r.old_card||'—')}</td><td>${esc(maskedEmployeeCard(r.bank_card))}</td><td>${esc(r.bank_name||'—')}</td><td>${esc(r.account_name)}</td></tr>`).join(''))}<p>待保存 ${result.count} 人；错误 ${result.errors.length} 行。</p>${result.ok?`<button type="button" class="button primary" data-employee-bank-import data-key="${erpRequestKey()}">确认导入 ${result.count} 人</button>`:''}`;
}
async function saveEmployeeBank(button){
 if(!canAction('payroll.write'))throw Error('当前账号没有工资维护权限');
 const f=document.getElementById('employee-bank-form');if(f&&!f.reportValidity())return;
 const importing=button.hasAttribute('data-employee-bank-import');if(importing&&!employeeBankPreview?.ok)throw Error('请先预览并修正导入错误');
 const body=importing?{file:employeeBankFile,token:employeeBankPreview.token,request_key:button.dataset.key}:{...Object.fromEntries(new FormData(f)),employee_id:f.dataset.employee,version:Number(f.dataset.version),request_key:f.dataset.key};
 await perform(async()=>{const result=await api('/api/factory/'+(importing?'employee-bank-import':'employee-bank'),body);busy=false;closeDialog();if(employeeBankPersonnelId&&!importing)factoryOpenForm('employee',employeeBankPersonnelId);else await showEmployeeBanks();notify(`已保存 ${result.saved} 人银行卡`);});
}
document.addEventListener('click',event=>{
 const personnel=event.target.closest('[data-personnel-bank]');
 if(personnel)requestPageTransition(()=>showEmployeeBanks(personnel.dataset.personnelBank,{personnel:true}),{dialogOnly:true});
 if(event.target.closest('[data-employee-bank-personnel]'))requestPageTransition(()=>factoryOpenForm('employee',employeeBankPersonnelId),{dialogOnly:true});
 const open=event.target.closest('[data-employee-banks]'),edit=event.target.closest('[data-employee-bank-edit]'),save=event.target.closest('[data-employee-bank-save],[data-employee-bank-import]');
 if(open)requestPageTransition(()=>showEmployeeBanks(open.dataset.employeeBanks||''));
 if(edit)requestPageTransition(()=>openEmployeeBankEditor(edit.dataset.employeeBankEdit),{dialogOnly:true});
 if(save)saveEmployeeBank(save).catch(err);
});
document.addEventListener('submit',event=>{if(event.target.id==='employee-bank-import-form'){event.preventDefault();perform(previewEmployeeBanks).catch(err);}if(event.target.id==='employee-bank-form'){event.preventDefault();saveEmployeeBank(document.querySelector('[data-employee-bank-save]')).catch(err);}});
document.addEventListener('change',event=>{if(event.target.id==='employee-bank-file'){employeeBankPreview=null;employeeBankFile='';document.getElementById('employee-bank-preview').innerHTML='';}});
