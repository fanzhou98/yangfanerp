'use strict';
// Standalone print component. Reuse via ERPPrint.open({title, html}) or mount({root, onChange}).
(()=>{
 const mounted=new WeakMap(),escape=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
 function sumDecimal(values){
  const parsed=values.map(value=>/^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value??'0')));if(parsed.some(value=>!value))return null;
  const scale=Math.max(0,...parsed.map(value=>(value[3]||'').length));if(scale>12)return null;
  const total=parsed.reduce((sum,value)=>sum+BigInt((value[1]||'')+value[2]+(value[3]||'').padEnd(scale,'0')),0n),negative=total<0n,raw=String(negative?-total:total).padStart(scale+1,'0');
  return (negative?'-':'')+(scale?raw.slice(0,-scale)+'.'+raw.slice(-scale):raw).replace(/(\.\d*?)0+$/,'$1').replace(/\.$/,'');
 }
 function money(cents){if(cents===null)return '待核对';const raw=String(cents??'0');if(!/^-?\d+$/.test(raw))return '待核对';const negative=raw[0]==='-',digits=(negative?raw.slice(1):raw).padStart(3,'0');return (negative?'-':'')+digits.slice(0,-2)+'.'+digits.slice(-2);}
 function grid(rows){
  const matrix=[],cells=[];let width=0;
  rows.forEach((row,r)=>{matrix[r]||=[];let col=0;for(const cell of row.cells){while(matrix[r][col])col++;const span=cell.colSpan||1,height=cell.rowSpan===0?rows.length-r:cell.rowSpan||1,info={cell,start:col,span,height,row:r,text:cell.textContent};cells.push(info);for(let y=r;y<r+height;y++){matrix[y]||=[];for(let x=col;x<col+span;x++)matrix[y][x]=info;}col+=span;width=Math.max(width,col);}});
  return {matrix,cells,width};
 }
 function element(doc,tag,cls,text){const node=doc.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;}
 function mount({root=document.body,onChange}={}){
  if(root?.nodeType===9)root=root.body;if(!root?.ownerDocument)throw Error('打印根节点须为HTML元素');
  if(mounted.has(root))return mounted.get(root);
  const doc=root.ownerDocument,win=doc.defaultView,button=doc.getElementById('print-button'),originallyDisabled=!!button?.disabled;
  const tableNodes=[...root.querySelectorAll('table')].filter(table=>!table.closest('[data-print-ignore]'));
  const settings=element(doc,'details','erp-print-settings');settings.open=true;settings.append(element(doc,'summary','','选择要打印的行和列'),element(doc,'p','','勾选后预览立即更新；只调整本次打印，不修改原单。'));
  const status=element(doc,'p','erp-print-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const error=element(doc,'p','erp-print-error','请至少选择一个表格中的一行和一列，再打印。');error.setAttribute('role','alert');error.hidden=true;
  const reset=element(doc,'button','','恢复全部');reset.type='button';settings.append(reset);
  const tables=tableNodes.map((table,index)=>{
   table.classList.add('quantity-matrix','erp-print-table');
   const head=grid(table.tHead?[...table.tHead.rows]:[]),bodyRows=[...table.tBodies].flatMap(body=>[...body.rows]),body=grid(bodyRows);
   if(table.dataset.printSumColumns&&!table.tFoot){const sums=new Set(table.dataset.printSumColumns.split(',').map(Number)),row=table.createTFoot().insertRow();for(let i=0;i<Math.max(head.width,body.width);i++){const cell=doc.createElement('th');cell.textContent=i===0?'所选行合计':'';if(sums.has(i))cell.dataset.printTotal='1';row.append(cell);}}
   const foot=grid(table.tFoot?[...table.tFoot.rows]:[]),count=Math.max(head.width,body.width,foot.width);
   const title=table.dataset.printTitle||table.closest('.print-page')?.querySelector('h1,h2')?.textContent||'明细表',id=table.dataset.printId||'table-'+index,keys=new Set();
   const columns=Array.from({length:count},(_,col)=>{const path=head.matrix.map(row=>row[col]?.cell).filter(Boolean),last=path.at(-1),label=[...new Set(path.map(cell=>cell.textContent.trim()))].join(' / ')||(bodyRows[0]?.cells[0]?.tagName==='TH'?['项目','内容'][col]:'第'+(col+1)+'列');let key=last?.dataset.printKey||'column-'+col;if(keys.has(key))key+='-'+col;keys.add(key);return {key,label,index:col};});
   // Keep rowspan-related body rows together to prevent orphaned merged cells.
   const parent=bodyRows.map((_,i)=>i),find=i=>parent[i]===i?i:(parent[i]=find(parent[i]));
   for(const info of body.cells)for(let r=info.row+1;r<Math.min(bodyRows.length,info.row+info.height);r++)parent[find(r)]=find(info.row);
   const groups=new Map();bodyRows.forEach((row,i)=>{const key=find(i);if(!groups.has(key))groups.set(key,[]);groups.get(key).push({row,index:i});});
   const labelColumn=Number(table.dataset.printLabelColumn??columns.findIndex(col=>/姓名|客户|人员|日期|项目/.test(col.label))),rows=[];
   for(const group of groups.values()){if(group.length===1&&group[0].row.cells.length===1&&group[0].row.cells[0].colSpan>1)continue;const first=group[0],label=first.row.dataset.printLabel||body.matrix[first.index]?.[Math.max(0,labelColumn)]?.cell.textContent.trim()||'第'+(first.index+1)+'行';rows.push({key:(first.row.dataset.printRowKey||String(first.index))+'#'+first.index,label:label+(group.length>1?'（'+group.length+'行）':''),group});}
   const oldCols=[...(table.querySelector(':scope > colgroup')?.children||[])];let colgroup=table.querySelector(':scope > colgroup');if(!colgroup){colgroup=doc.createElement('colgroup');table.insertBefore(colgroup,table.tHead||table.firstChild);}
   const originalColumns=[];for(const col of oldCols)for(let i=0;i<(col.span||1);i++){const clone=col.cloneNode(true);clone.span=1;originalColumns.push(clone);}while(originalColumns.length<count)originalColumns.push(doc.createElement('col'));
   const field=element(doc,'fieldset','erp-print-table-settings');field.append(element(doc,'legend','',title+(tableNodes.length>1?' · 表'+(index+1):'')));const options=element(doc,'div','erp-print-options');
   function choices(items,kind){const section=element(doc,'section'),actions=element(doc,'div','erp-print-actions');section.append(element(doc,'h3','',kind==='rows'?'明细行':'字段列'));for(const [label,checked] of [['全选',true],['清空',false]]){const action=element(doc,'button','',label);action.type='button';action.addEventListener('click',()=>{for(const item of items)item.input.checked=checked;update();});actions.append(action);}section.append(actions);const list=element(doc,'div','erp-print-choices');for(const item of items){const label=element(doc,'label'),input=doc.createElement('input');input.type='checkbox';input.checked=true;input.dataset.printOption=kind;input.dataset.printTable=id;input.value=item.key;item.input=input;label.append(input,element(doc,'span','',item.label));list.append(label);}if(!items.length)list.append(element(doc,'p','','当前没有可选择的明细。'));section.append(list);options.append(section);}
   choices(rows,'rows');choices(columns,'columns');field.append(options);settings.append(field);const summary=element(doc,'p','erp-print-table-status');field.append(summary);
   const sequence=columns.find(col=>/^(序|序号)$/.test(col.label)),originalSequence=sequence?bodyRows.map((_,i)=>body.matrix[i]?.[sequence.index]?.cell.textContent):[];
   return {id,title,table,head,body,foot,columns,rows,colgroup,originalColumns,field,summary,sequence,originalSequence,visibleRows:[],visibleColumns:[],partial:false};
  });
  settings.append(status,error);root.insertBefore(settings,[...root.children].find(node=>!node.matches('.print-toolbar'))||null);
  const pages=[...root.querySelectorAll('.print-page')];if(pages.length){const heading=element(doc,'h2','erp-print-preview-heading','实时预览');pages[0].before(heading);}for(const page of pages){if(page.closest('.erp-print-preview-scroll'))continue;const wrap=element(doc,'div','erp-print-preview-scroll');page.before(wrap);wrap.append(page);}
  let selection;
  function update(){
   let active=0;selection={};
   for(const t of tables){
    const visible=t.columns.filter(col=>col.input.checked),indices=new Set(visible.map(col=>col.index)),selected=t.rows.filter(row=>row.input.checked),selectedIndices=new Set(selected.flatMap(row=>row.group.map(item=>item.index)));t.visibleRows=selected;t.visibleColumns=visible;t.table.hidden=!selected.length||!visible.length;t.partial=selected.length!==t.rows.length||visible.length!==t.columns.length;
    for(const row of t.rows)for(const item of row.group)item.row.hidden=!row.input.checked;
    for(const info of [...t.head.cells,...t.body.cells,...t.foot.cells]){const span=Array.from({length:info.span},(_,i)=>info.start+i).filter(i=>indices.has(i)).length;info.cell.hidden=!span;info.cell.colSpan=Math.max(span,1);}
    t.colgroup.replaceChildren(...visible.map(col=>t.originalColumns[col.index].cloneNode(true)));
    if(t.sequence){let n=0;for(let i=0;i<t.body.matrix.length;i++){const cell=t.body.matrix[i]?.[t.sequence.index]?.cell;if(cell)cell.textContent=selected.length===t.rows.length?t.originalSequence[i]:(selectedIndices.has(i)?String(++n):t.originalSequence[i]);}}
    let unverifiedFooter=false;for(const info of t.foot.cells){if(info.span!==1||t.table.dataset.printSumColumns&&!info.cell.dataset.printTotal){if(t.partial&&/\d/.test(info.text||''))unverifiedFooter=true;continue;}const cells=[...new Set([...selectedIndices].map(i=>t.body.matrix[i]?.[info.start]?.cell).filter(Boolean))],values=cells.map(cell=>cell.dataset.printValue??cell.dataset.quantity);if(values.length&&values.every(value=>value!==undefined)){const sum=sumDecimal(values);info.cell.textContent=sum===null?'待核对':cells[0]?.dataset.printFormat==='money'?money(sum):sum;}else if(t.partial&&/\d/.test(info.text||''))unverifiedFooter=true;}if(unverifiedFooter&&t.table.tFoot)t.table.tFoot.dataset.printSummary='1';
    const monetary=(t.table.dataset.printMoneyColumns||'').split(',').filter(Boolean).map(key=>{const col=t.columns.find(col=>col.key===key);if(!col)return '';const values=[...selectedIndices].map(i=>t.body.matrix[i]?.[col.index]?.cell.dataset.printValue??'0');return col.label+' '+money(sumDecimal(values))+' 元';}).filter(Boolean);
    t.summary.textContent=`已选 ${selected.length} / ${t.rows.length} 行，${visible.length} / ${t.columns.length} 列`+(monetary.length?' · '+monetary.join(' · '):'');
    selection[t.id]={rows:selected.map(row=>row.key),columns:visible.map(col=>col.key)};if(selected.length&&visible.length)active++;
   }
   for(const page of pages){const own=tables.filter(t=>page.contains(t.table)),changed=own.some(t=>t.partial),hasRows=own.some(t=>t.visibleRows.length&&t.visibleColumns.length);page.hidden=!!own.length&&!hasRows;page.parentElement.hidden=page.hidden;for(const node of page.querySelectorAll('[data-print-summary]'))node.hidden=changed;for(const node of page.querySelectorAll('[data-print-row-count]')){const t=own[0];if(t)node.textContent=String(t.visibleRows.reduce((n,row)=>n+row.group.length,0));}let partial=page.querySelector('.erp-print-partial');if(!partial){partial=element(doc,'p','erp-print-partial',page.querySelector('[data-print-summary]')?'本页仅打印选中内容，原单汇总已隐藏；原单记录保持不变。':'本页仅打印选中内容。');page.append(partial);}partial.hidden=!changed;}
   const visiblePages=pages.filter(page=>!page.hidden);for(const page of pages)page.parentElement.classList.toggle('erp-print-last-page',page===visiblePages.at(-1));visiblePages.forEach((page,i)=>{for(const node of page.querySelectorAll('[data-print-page-number]'))node.textContent=String(i+1);});for(const node of root.querySelectorAll('[data-print-page-count]'))node.textContent=String(visiblePages.length);
   const valid=tables.length?active>0:!originallyDisabled;if(button)button.disabled=!valid;error.hidden=valid;status.textContent=tables.length?'已选择 '+active+' / '+tables.length+' 个表格，可直接查看下方预览。':'本单没有明细表，按原版式预览打印。';
   if(onChange)onChange(selection);return selection;
  }
  settings.addEventListener('change',event=>{if(event.target.matches('[data-print-option]'))update();});reset.addEventListener('click',()=>{for(const t of tables)for(const item of [...t.rows,...t.columns])item.input.checked=true;update();});
  win.addEventListener('beforeprint',update);button?.addEventListener('click',()=>{update();if(!button.disabled)win.print();});
  const api={update,reset:()=>reset.click(),getSelection:()=>JSON.parse(JSON.stringify(selection)),tables};mounted.set(root,api);update();return api;
 }
 function open({title='单据打印',html}={}){
  if(typeof html!=='string')throw Error('打印内容须为已转义的HTML字符串');const popup=window.open('','_blank');if(!popup)return null;
  const css=new URL('/print.css',window.location.href).href,script=new URL('/print.js',window.location.href).href,template=document.createElement('template');template.innerHTML=html;const content=template.content.querySelector('.print-page')?html:'<section class="print-page">'+html+'</section>';
  popup.document.write('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(title)+'</title><link rel="stylesheet" href="'+escape(css)+'"><script defer src="'+escape(script)+'"></script></head><body><div class="print-toolbar"><button id="print-button">打印所选内容</button><span>行列选择 · 实时预览 · 横向A4</span></div>'+content+'</body></html>');popup.document.close();return popup;
 }
 window.ERPPrint={open,mount,sumDecimal};
 if(document.getElementById('print-button'))mount();
})();

function fitDeliveryPrintNames(){for(const el of document.querySelectorAll('[data-print-fit]')){el.style.fontSize='8pt';let size=8;while(el.scrollWidth>el.clientWidth+1&&size>2){size-=.25;el.style.fontSize=size+'pt';}}}
if(typeof window!=='undefined'&&typeof window.addEventListener==='function'){window.addEventListener('load',fitDeliveryPrintNames);window.addEventListener('beforeprint',fitDeliveryPrintNames);window.addEventListener('resize',fitDeliveryPrintNames);}
