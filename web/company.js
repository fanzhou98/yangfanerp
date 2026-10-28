'use strict';
function companyDocumentHeader(record){
 const c=record?.company;
 if(!c)return '<p class="help-text">历史单据未留存公司信息，请核对原始出具版本。</p>';
 return `<header class="document-company"><strong>${esc(c.name)}</strong>${companyDetailLines(c).map(line=>`<p>${esc(line)}</p>`).join('')}</header>`;
}
function companyDetailLines(c){return [['统一社会信用代码','tax_id'],['地址','address'],['联系电话','phone'],['联系人','contact']].filter(([,key])=>c?.[key]).map(([label,key])=>label+'：'+c[key]);}
function companyStatementItems(s){return companyDetailLines(s.company).map(text=>({type:'note',text}));}
function openCompanyInfo(){
 const c=data.company||{name:'昌吉市洋帆豆制品厂',version:0},edit=(authUser?.role||role)==='管理员';
 openDialog('公司信息',`<form id="company-info-form" data-version="${c.version}" data-key="${erpRequestKey()}">${[['公司 / 工厂正式名称','name',120],['简称','short_name',60],['统一社会信用代码','tax_id',30],['地址','address',300],['联系电话','phone',40],['联系人','contact',80]].map(([label,key,max])=>resourceField(label,key,'text',c[key]||'',`${key==='name'?'required ':''}maxlength="${max}" ${edit?'':'readonly'}`)).join('')}<p class="help-text">公司信息用于工资、考勤、订货、送货及各类结算单。新确认的工资和新出具的结算单保存当时公司信息，后续修改不覆盖历史快照。</p></form>`,'公司身份与单据抬头',`<button class="button" data-act="close">关闭</button>${edit?'<button class="button primary" data-company-save>保存公司信息</button>':''}`);
}
async function saveCompanyInfo(){const f=document.getElementById('company-info-form');if(!f.reportValidity())return;await perform(async()=>{await api('/api/factory/company-info',{...Object.fromEntries(new FormData(f)),version:Number(f.dataset.version),request_key:f.dataset.key});busy=false;closeDialog();await refresh();notify('公司信息已保存，新单据使用更新后的资料');});}
document.addEventListener('click',event=>{if(event.target.closest('[data-company-info]'))requestPageTransition(openCompanyInfo);if(event.target.closest('[data-company-save]'))saveCompanyInfo().catch(err);});
document.addEventListener('submit',event=>{if(event.target.id==='company-info-form'){event.preventDefault();saveCompanyInfo().catch(err);}});
