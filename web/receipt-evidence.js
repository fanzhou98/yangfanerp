'use strict';
/* 收款截图：压缩、识别、回填收款登记，查看历史凭据。识别只做辅助，登记前必须对照原图。 */
const RECEIPT_EVIDENCE_MAX_BYTES=560000,RECEIPT_EVIDENCE_MAX_FILE=25*1024*1024,RECEIPT_EVIDENCE_MAX_PIXELS=8000000;
let receiptEvidence=null,receiptEvidenceToken=0,receiptScanLast=null,receiptScanToken=0;

function receiptEvidenceAllowed(){return typeof canAction!=='function'||canAction('finance.evidence');}

function receiptEvidencePanelHTML(){
 return `<div class="evidence-head"><div><strong>转账截图识别</strong><small>微信 / 支付宝 / 银行回单 · 可选</small></div><span class="badge" data-evidence-badge hidden></span></div>
 <label class="evidence-drop" data-evidence-drop><input type="file" accept="image/jpeg,image/png,image/webp" data-evidence-file><span data-evidence-prompt>选择或拖入截图，自动提取金额、时间、单号</span></label>
 <div class="help-text" data-evidence-status role="status"></div>
 <div data-evidence-warnings></div>
 <div class="evidence-preview" data-evidence-preview hidden><img data-evidence-image alt="待登记收款截图"><div class="evidence-preview-main"><div class="evidence-fields" data-evidence-fields></div><details data-evidence-raw hidden><summary>识别原文（只读，供核对）</summary><pre data-evidence-rawtext></pre></details><button type="button" class="text-button" data-evidence-clear>移除截图</button></div></div>
 <label class="check-line evidence-confirm" data-evidence-confirm hidden><input type="checkbox" name="evidence_confirmed" value="1">截图金额与本次到账金额不一致，我已核对原图并确认按本次填写金额登记</label>
 <input type="hidden" name="evidence_id" data-evidence-id><input type="hidden" name="transaction_no" data-evidence-tx>
 <p class="help-text">截图保存在 ERP 数据库并随数据库备份保存；开启云端识别时图片会发送给所配置的模型服务。登记前请对照原图核对。</p>`;
}

function mountReceiptEvidence(){
 const form=$('#receipt-form');if(!form||form.querySelector('#receipt-evidence-panel'))return;
 receiptEvidence=null;receiptEvidenceToken++;receiptScanToken++;
 const panel=document.createElement('section');panel.id='receipt-evidence-panel';panel.className='receipt-evidence';panel.innerHTML=receiptEvidencePanelHTML();
 const summary=form.querySelector('.receipt-summary');if(summary)summary.after(panel);else form.prepend(panel);
 wireReceiptEvidence(form,panel);
}

function wireReceiptEvidence(form,panel){
 const file=panel.querySelector('[data-evidence-file]'),drop=panel.querySelector('[data-evidence-drop]'),clear=panel.querySelector('[data-evidence-clear]');
 file.addEventListener('change',()=>{const picked=file.files&&file.files[0];file.value='';if(picked)uploadReceiptEvidence(picked);});
 for(const type of ['dragenter','dragover'])drop.addEventListener(type,e=>{e.preventDefault();e.stopPropagation();drop.classList.add('dragging');});
 drop.addEventListener('dragleave',e=>{e.preventDefault();drop.classList.remove('dragging');});
 drop.addEventListener('drop',e=>{e.preventDefault();e.stopPropagation();drop.classList.remove('dragging');const picked=e.dataTransfer?.files&&e.dataTransfer.files[0];if(picked)uploadReceiptEvidence(picked);});
 clear.addEventListener('click',()=>clearReceiptEvidence(true));
 form.addEventListener('input',e=>{if(e.target.name==='amount')updateReceiptEvidenceMismatch();});
}

function setReceiptEvidenceStatus(text,kind=''){
 const el=$('#receipt-evidence-panel [data-evidence-status]');if(!el)return;
 el.className='help-text'+(kind==='error'?' error':'');el.textContent=text||'';
}

async function uploadReceiptEvidence(file){
 const form=$('#receipt-form');if(!form)return;
 const token=++receiptEvidenceToken;setReceiptEvidenceStatus('正在压缩截图…');
 try{
  const prepared=await compressReceiptEvidence(file);
  if(token!==receiptEvidenceToken)return;
  const preview=$('#receipt-evidence-panel [data-evidence-preview]'),image=$('#receipt-evidence-panel [data-evidence-image]');
  preview.hidden=false;image.src=prepared.dataUrl;setReceiptEvidenceStatus('正在识别，通常需要几秒…');
  const result=await api('/api/receipt-evidence/recognize',{image_base64:prepared.base64,mime:prepared.mime,filename:file.name,order_id:activeOrder?.id||''});
  if(token!==receiptEvidenceToken){if(result?.id&&result.status!=='linked')api('/api/receipt-evidence/'+encodeURIComponent(result.id)+'/discard',{}).catch(()=>{});return;}
  applyReceiptEvidence(result);
 }catch(e){if(token===receiptEvidenceToken)setReceiptEvidenceStatus('未能识别：'+e.message,'error');}
}

function applyReceiptEvidence(result){
 const form=$('#receipt-form');if(!form)return;
 receiptEvidence=result;
 const f=result.fields||{},conflict=!!(result.duplicate&&result.order_id&&activeOrder&&result.order_id!==activeOrder.id);
 const linkable=(result.status==='recognized'||result.status==='failed')&&!conflict;
 form.elements.evidence_id.value=linkable?result.id:'';
 form.elements.transaction_no.value=linkable&&f.transaction_no?f.transaction_no:'';
 renderReceiptEvidence(result);
 if(linkable)fillReceiptFromEvidence(result);
 updateReceiptEvidenceMismatch();
 if(typeof updateReceiptPreview==='function')updateReceiptPreview();
}

function renderReceiptEvidence(result){
 const panel=$('#receipt-evidence-panel');if(!panel)return;
 const f=result.fields||{},items=[],badge=panel.querySelector('[data-evidence-badge]'),status=panel.querySelector('[data-evidence-status]'),warnings=panel.querySelector('[data-evidence-warnings]');
 if(f.amount_cents)items.push(['金额',amount(f.amount_cents)]);
 if(f.occurred_at)items.push(['时间',String(f.occurred_at).replace('T',' ').slice(0,16)]);
 if(f.transaction_no)items.push(['交易单号',f.transaction_no]);
 if(f.payer)items.push(['付款方',f.payer]);
 if(f.payee)items.push(['收款方',f.payee]);
 if(f.method)items.push(['方式',f.method]);
 if(f.direction==='out')items.push(['方向','付款/支出']);
 if(result.confidence)items.push(['可信度',result.confidence+'%']);
 panel.querySelector('[data-evidence-fields]').innerHTML=items.map(([k,v])=>`<span><small>${esc(k)}</small><b>${esc(v)}</b></span>`).join('')||'<span class="help-text">未提取到结构化字段，请手工填写。</span>';
 badge.hidden=false;badge.className='badge '+(result.status==='linked'?'red':result.status==='recognized'?(f.direction==='out'?'orange':'green'):'orange');
 badge.textContent=result.status==='linked'?'已用于收款':result.status==='recognized'?(f.direction==='out'?'付款截图':result.duplicate?'重复截图':'已识别'):'未识别';
 const message=result.message||(result.status==='linked'?'该截图已用于其他收款，不能重复登记。':'请对照原图核对后登记。');
 status.className='help-text'+(result.status==='failed'?' error':'');status.textContent=message+(result.engine_label?' · '+result.engine_label:'');
 const list=result.warnings||[];warnings.innerHTML=list.length?`<div class="callout warning">${list.map(w=>`<div>${esc(w)}</div>`).join('')}</div>`:'';
 const raw=panel.querySelector('[data-evidence-raw]'),rawText=panel.querySelector('[data-evidence-rawtext]');
 raw.hidden=!result.raw_text;rawText.textContent=result.raw_text||'';
}

function fillReceiptFromEvidence(result){
 const form=$('#receipt-form');if(!form)return;
 const f=result.fields||{},amountInput=form.elements.amount,dateInput=form.elements.received_date,methodInput=form.elements.method,noteInput=form.elements.note;
 if(f.direction!=='out'&&f.amount_cents&&!amountInput.value){const cents=Number(f.amount_cents);if(cents>0&&cents<=orderOutstanding(activeOrder))amountInput.value=(cents/100).toFixed(2);}
 if(f.occurred_at&&(!dateInput.value||dateInput.value===today()))dateInput.value=String(f.occurred_at).slice(0,10);
 if(f.method&&[...methodInput.options].some(o=>o.value===f.method))methodInput.value=f.method;
 if(f.transaction_no&&!noteInput.value.trim())noteInput.value=('交易单号 '+f.transaction_no+(f.payer?'；付款方 '+f.payer:'')).slice(0,480);
 updateReceiptEvidenceMismatch();
}

function updateReceiptEvidenceMismatch(){
 const form=$('#receipt-form');if(!form||!form.elements.evidence_confirmed)return;
 const box=form.elements.evidence_confirmed,label=box.closest('[data-evidence-confirm]'),shot=Number((receiptEvidence?.fields||{}).amount_cents||0),cents=Math.round(Number(form.elements.amount.value||0)*100);
 const mismatch=!!(form.elements.evidence_id.value&&shot>0&&cents>0&&shot!==cents);
 label.hidden=!mismatch;box.required=mismatch;if(!mismatch)box.checked=false;
}

function clearReceiptEvidence(discard){
 const form=$('#receipt-form');if(!form)return;
 const id=form.elements.evidence_id?.value;
 receiptEvidenceToken++;
 if(discard&&id)api('/api/receipt-evidence/'+encodeURIComponent(id)+'/discard',{}).catch(()=>{});
 receiptEvidence=null;
 if(form.elements.evidence_id)form.elements.evidence_id.value='';
 if(form.elements.transaction_no)form.elements.transaction_no.value='';
 const panel=$('#receipt-evidence-panel');if(!panel)return;
 const preview=panel.querySelector('[data-evidence-preview]'),image=panel.querySelector('[data-evidence-image]'),raw=panel.querySelector('[data-evidence-raw]'),badge=panel.querySelector('[data-evidence-badge]'),box=panel.querySelector('[data-evidence-confirm] input');
 preview.hidden=true;image.removeAttribute('src');raw.hidden=true;badge.hidden=true;
 panel.querySelector('[data-evidence-fields]').innerHTML='';panel.querySelector('[data-evidence-warnings]').innerHTML='';panel.querySelector('[data-evidence-status]').textContent='';
 if(box){box.checked=false;box.required=false;box.closest('[data-evidence-confirm]').hidden=true;}
 const file=panel.querySelector('[data-evidence-file]');if(file)file.value='';
}

function releaseReceiptEvidence(){receiptEvidenceToken++;receiptEvidence=null;}

async function compressReceiptEvidence(file){
 if(!file)throw Error('请选择截图文件');
 const name=String(file.name||'').toLowerCase();
 if(!/^image\//.test(file.type||'')&&!/\.(jpe?g|png|webp)$/.test(name))throw Error('请选择 JPG、PNG 或 WebP 格式的截图');
 if(file.size>RECEIPT_EVIDENCE_MAX_FILE)throw Error('图片超过 25MB，请先裁剪到转账信息区域');
 const loaded=await loadReceiptEvidenceImage(file);
 try{
  let w=loaded.width,h=loaded.height;if(!w||!h)throw Error('无法读取图片尺寸，请转成 JPG 后重试');
  let scale=Math.min(1,2600/Math.max(w,h));
  if(w*scale<900&&w<=1600)scale=Math.min(1,900/w);
  if(w*scale*h*scale>RECEIPT_EVIDENCE_MAX_PIXELS)scale=Math.sqrt(RECEIPT_EVIDENCE_MAX_PIXELS/(w*h));
  scale=Math.min(1,scale);
  for(let attempt=0;attempt<6;attempt++){
   const cw=Math.max(1,Math.round(w*scale)),ch=Math.max(1,Math.round(h*scale)),canvas=document.createElement('canvas');canvas.width=cw;canvas.height=ch;
   const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,cw,ch);ctx.drawImage(loaded.source,0,0,cw,ch);
   for(let quality=0.88;quality>=0.62;quality-=0.06){
    const dataUrl=canvas.toDataURL('image/jpeg',quality),comma=dataUrl.indexOf(','),bytes=Math.floor((dataUrl.length-comma-1)*3/4);
    if(bytes<=RECEIPT_EVIDENCE_MAX_BYTES)return {base64:dataUrl.slice(comma+1),dataUrl,mime:'image/jpeg',bytes,width:cw,height:ch};
   }
   scale*=0.85;
  }
  throw Error('截图压缩后仍超过 560KB，请裁剪到转账信息区域后重试');
 }finally{loaded.close();}
}

function loadReceiptEvidenceImage(file){
 return new Promise((resolve,reject)=>{
  if(typeof createImageBitmap==='function'){
   createImageBitmap(file,{imageOrientation:'from-image'}).then(bitmap=>resolve({source:bitmap,width:bitmap.width,height:bitmap.height,close:()=>bitmap.close&&bitmap.close()})).catch(()=>loadReceiptEvidenceImageElement(file).then(resolve,reject));
  }else loadReceiptEvidenceImageElement(file).then(resolve,reject);
 });
}
function loadReceiptEvidenceImageElement(file){
 return new Promise((resolve,reject)=>{
  const url=URL.createObjectURL(file),image=new Image();
  image.onload=()=>{URL.revokeObjectURL(url);resolve({source:image,width:image.naturalWidth,height:image.naturalHeight,close:()=>{}});};
  image.onerror=()=>{URL.revokeObjectURL(url);reject(Error('浏览器无法读取这张图片，请从相册导出为 JPG 后重试'));};
  image.src=url;
 });
}

async function openReceiptEvidence(id){
 try{
  const e=await api('/api/receipt-evidence/'+encodeURIComponent(id)),f=e.fields||{},items=[];
  if(f.amount_cents)items.push(['金额',amount(f.amount_cents)]);
  if(f.occurred_at)items.push(['时间',String(f.occurred_at).replace('T',' ').slice(0,16)]);
  if(f.transaction_no)items.push(['交易单号',f.transaction_no]);
  if(f.payer)items.push(['付款方',f.payer]);
  if(f.payee)items.push(['收款方',f.payee]);
  if(f.direction==='out')items.push(['方向','付款/支出']);
  if(e.linked_receipt_id)items.push(['对应收款',e.linked_receipt_id]);
  if(e.engine_label)items.push(['识别方式',e.engine_label]);
  const image=e.status==='discarded'?'<p class="callout warning">截图文件已移除，仅保留识别记录。</p>':`<img class="evidence-viewer-image" src="/api/receipt-evidence/${encodeURIComponent(e.id)}/image" alt="收款截图原图">`;
  const warnings=(e.warnings||[]).map(w=>`<div>${esc(w)}</div>`).join('');
  openDialog('收款凭据 · '+(e.linked_receipt_id||e.id),`<div class="evidence-viewer">${image}<div class="evidence-viewer-meta"><div class="evidence-fields">${items.map(([k,v])=>`<span><small>${esc(k)}</small><b>${esc(v)}</b></span>`).join('')}</div>${warnings?`<div class="callout warning">${warnings}</div>`:''}${e.message?`<p class="help-text">${esc(e.message)}</p>`:''}${e.raw_text?`<details class="evidence-raw"><summary>识别原文</summary><pre>${esc(e.raw_text)}</pre></details>`:''}</div></div>`,'RECEIPT EVIDENCE','<button class="button" data-act="close">关闭</button>');
 }catch(e){err(e);}
}

function openReceiptScan(){
 if(!receiptEvidenceAllowed()){notify('当前账号无截图识别权限');return;}
 receiptScanLast=null;receiptScanToken++;
 openDialog('识别收款截图',`<div class="receipt-evidence" data-scan-panel><div class="evidence-head"><div><strong>转账截图识别</strong><small>识别后复制金额、日期和单号；不会自动登记收款</small></div><span class="badge" data-scan-badge hidden></span></div><label class="evidence-drop" data-scan-drop><input type="file" accept="image/jpeg,image/png,image/webp" data-scan-file><span>选择或拖入截图</span></label><div class="help-text" data-scan-status role="status"></div><div data-scan-warnings></div><div class="evidence-preview" data-scan-preview hidden><img data-scan-image alt="识别截图"><div class="evidence-preview-main"><div class="evidence-fields" data-scan-fields></div><div class="head-actions evidence-copy-actions"><button type="button" class="button" data-copy-scan="amount">复制金额</button><button type="button" class="button" data-copy-scan="date">复制日期</button><button type="button" class="button" data-copy-scan="tx">复制单号</button></div><details data-scan-raw hidden><summary>识别原文</summary><pre data-scan-rawtext></pre></details></div></div></div>`,'RECEIPT SCAN','<button class="button" data-act="close">关闭</button>');
 wireReceiptScan();
}

function wireReceiptScan(){
 const file=$('[data-scan-file]'),drop=$('[data-scan-drop]');if(!file||!drop)return;
 file.addEventListener('change',()=>{const picked=file.files&&file.files[0];file.value='';if(picked)uploadReceiptScan(picked);});
 for(const type of ['dragenter','dragover'])drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add('dragging');});
 drop.addEventListener('dragleave',e=>{e.preventDefault();drop.classList.remove('dragging');});
 drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragging');const picked=e.dataTransfer?.files&&e.dataTransfer.files[0];if(picked)uploadReceiptScan(picked);});
}

async function uploadReceiptScan(file){
 const token=++receiptScanToken,status=$('[data-scan-status]');if(!status)return;
 status.className='help-text';status.textContent='正在压缩截图…';
 try{
  const prepared=await compressReceiptEvidence(file);if(token!==receiptScanToken)return;
  $('[data-scan-preview]').hidden=false;$('[data-scan-image]').src=prepared.dataUrl;status.textContent='正在识别，通常需要几秒…';
  const result=await api('/api/receipt-evidence/recognize',{image_base64:prepared.base64,mime:prepared.mime,filename:file.name,order_id:''});
  if(token!==receiptScanToken){if(result?.id&&result.status==='recognized')api('/api/receipt-evidence/'+encodeURIComponent(result.id)+'/discard',{}).catch(()=>{});return;}
  receiptScanLast=result;renderReceiptScan(result);
 }catch(e){if(token===receiptScanToken){status.className='help-text error';status.textContent='未能识别：'+e.message;}}
}

function renderReceiptScan(result){
 const f=result.fields||{},items=[],badge=$('[data-scan-badge]'),status=$('[data-scan-status]'),warnings=$('[data-scan-warnings]');
 if(f.amount_cents)items.push(['金额',amount(f.amount_cents)]);
 if(f.occurred_at)items.push(['时间',String(f.occurred_at).replace('T',' ').slice(0,16)]);
 if(f.transaction_no)items.push(['交易单号',f.transaction_no]);
 if(f.payer)items.push(['付款方',f.payer]);
 if(f.payee)items.push(['收款方',f.payee]);
 if(result.confidence)items.push(['可信度',result.confidence+'%']);
 $('[data-scan-fields]').innerHTML=items.map(([k,v])=>`<span><small>${esc(k)}</small><b>${esc(v)}</b></span>`).join('')||'<span class="help-text">未提取到结构化字段，请手工核对。</span>';
 badge.hidden=false;badge.className='badge '+(result.status==='recognized'?'green':'orange');badge.textContent=result.status==='recognized'?'已识别':'未识别';
 status.className='help-text'+(result.status==='failed'?' error':'');status.textContent=(result.message||'请对照原图核对。')+(result.engine_label?' · '+result.engine_label:'');
 const list=result.warnings||[];warnings.innerHTML=list.length?`<div class="callout warning">${list.map(w=>`<div>${esc(w)}</div>`).join('')}</div>`:'';
 $('[data-scan-raw]').hidden=!result.raw_text;$('[data-scan-rawtext]').textContent=result.raw_text||'';
}

async function openReceiptOcrSettings(){
 try{
  const s=await api('/api/receipt-ocr/settings'),cloud=['auto','openai'].includes(s.provider);
  const options=[['auto','自动（本机优先）'],['macos','本机 macOS Vision（不联网）'],['openai','云端视觉模型（OpenAI 兼容）'],['off','关闭识别（仅保存截图）']];
  openDialog('凭据识别服务',`<form id="receipt-ocr-form"><div class="callout ${s.available?'':'warning'}">${s.available?'当前可用：'+esc(s.engine_label):'当前不可用：'+esc(s.message||'请完成配置')}</div><div class="form-grid"><label class="field">识别方式<select name="provider">${options.map(([v,t])=>`<option value="${v}" ${s.provider===v?'selected':''}>${t}</option>`).join('')}</select></label><label class="field">超时（秒）<input name="timeout" type="number" min="10" max="120" step="1" value="${Number(s.timeout||35)}"></label><label class="field">API Key<input name="api_key" type="password" autocomplete="new-password" maxlength="400" placeholder="${s.key_configured?'已配置 '+esc(s.key_hint)+'；留空保持不变':'粘贴服务商 API Key'}"><small>${s.key_configured?'密钥只写入服务器，不会回传到页面。':'未配置 API Key。'}</small></label><div class="wide" data-ocr-cloud ${cloud?'':'hidden'}><div class="form-grid"><label class="field">服务地址（OpenAI 兼容 Base URL）<input name="base_url" type="url" maxlength="300" value="${esc(s.base_url||'')}" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"></label><label class="field">模型名称<input name="model" maxlength="120" value="${esc(s.model||'')}" placeholder="qwen-vl-plus"></label><div class="field">API Key 操作<label class="check-line"><input type="checkbox" name="clear_key">清除已保存的密钥</label></div></div></div></div><p class="help-text">本机识别只在这台 Mac 上运行，截图不离开本机。云端识别会把截图发送到所填服务；请确认服务商的数据留存与隐私条款。关闭识别后仍可在收款弹窗上传截图并手工填写。</p></form>`,'RECEIPT OCR · 管理员配置','<button class="button" data-act="close">取消</button><button class="button primary" data-receipt-ocr-save>保存并检查</button>');
  const form=$('#receipt-ocr-form');if(!form)return;
  const toggle=()=>{const show=['auto','openai'].includes(form.elements.provider.value);form.querySelector('[data-ocr-cloud]').hidden=!show;};
  form.elements.provider.addEventListener('change',toggle);toggle();
 }catch(e){err(e);}
}

async function saveReceiptOcrSettings(){
 const form=$('#receipt-ocr-form');if(!form||!form.reportValidity())return;
 const body={provider:form.elements.provider.value,base_url:form.elements.base_url.value.trim(),model:form.elements.model.value.trim(),timeout:Number(form.elements.timeout.value||35),api_key:form.elements.api_key.value.trim(),clear_key:form.elements.clear_key.checked};
 await perform(async()=>{
  const r=await api('/api/receipt-ocr/settings',body);busy=false;closeDialog();notify(r.available?'识别服务已保存：'+r.engine_label:'已保存，但当前不可用：'+r.message);if(page==='system-settings')render();
 });
}

document.addEventListener('click',e=>{
 const scan=e.target.closest('[data-receipt-scan]');if(scan){openReceiptScan();return;}
 const evidence=e.target.closest('[data-receipt-evidence]');if(evidence){openReceiptEvidence(evidence.dataset.receiptEvidence).catch(err);return;}
 const settings=e.target.closest('[data-receipt-ocr-settings]');if(settings){openReceiptOcrSettings();return;}
 const save=e.target.closest('[data-receipt-ocr-save]');if(save){saveReceiptOcrSettings().catch(err);return;}
 const copy=e.target.closest('[data-copy-scan]');if(copy){
  const f=receiptScanLast?.fields||{},key=copy.dataset.copyScan,text=key==='amount'?(f.amount_cents?(Number(f.amount_cents)/100).toFixed(2):''):key==='date'?(f.occurred_at||'').slice(0,10):(f.transaction_no||'');
  if(!text){notify('没有可复制的内容，请核对识别结果');return;}
  navigator.clipboard?.writeText(text).then(()=>notify('已复制：'+text)).catch(()=>notify('请长按选择复制：'+text));
 }
});

if(typeof receipt==='function'){
 const baseReceipt=receipt;receipt=function(id){baseReceipt(id);mountReceiptEvidence();};
}
if(typeof closeDialog==='function'){
 const baseCloseDialog=closeDialog;closeDialog=function(){releaseReceiptEvidence();baseCloseDialog();};
}
