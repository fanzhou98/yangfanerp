'use strict';
// Shared working copies keep unsaved entries when moving between the three sheets.
const sheetOrders=new Map(), sheetBaselines=new Map(), matrixRows=new Map(), lineChoices=new Map(), clientReasons=new Map(), decisionDirty=new Set();
const matrixExpanded=new Set();
let sheetBatch='日常订货', sheetRoute='', sheetSearch='', sheetStatus='all', processingBatch='', sheetTrip='', sheetArchive=false, sheetError='';
function sheetDate(){return selectedDate||today();}
function orderStageKey(o){if(o.review_return?.status==='pending')return 'rework';if(o.state==='draft')return 'shipping';if(['dispatched','negotiation'].includes(o.state))return o.workflow_version===1&&!o.weight_confirmation?'weight':'pending';return o.state==='ready'?'ready':o.state==='reviewed'?'reviewed':o.state;}
function isSettlementTodo(o){const stage=orderStageKey(o);return (['shipping','weight'].includes(stage)&&canOpenWorkflow('weighing','weight.confirm'))||(['pending','rework'].includes(stage)&&canAction('finance.settle'))||(stage==='ready'&&canAction('finance.review'));}
let settlementDateInitialized=false;
function openSettlementTodos(){if(!settlementDateInitialized){if(!rangeMode&&!selectedDate)selectedDate=shiftRangeDay(today(),-1);settlementDateInitialized=true;}sheetTrip='';sheetRoute='';sheetSearch='';processingBatch='';sheetStatus=settlementDefaultStage();sheetArchive=false;goto('settlements');}
function processingDateMatches(o){return typeof rangeDateMatches==='function'&&typeof page!=='undefined'&&page==='settlements'?rangeDateMatches(o):!selectedDate||o.business_date===selectedDate;}
function processingStatusMatches(o){const stage=orderStageKey(o);return sheetStatus==='all'||(sheetStatus==='pending'&&canAction('finance.settle')&&['weight','shipping'].includes(stage))||(sheetStatus==='handed'?!!o.weight_confirmation:sheetStatus==='negotiation'?stage==='pending':sheetStatus===stage);}
function originalOrder(id){return data.orders.find(o=>o.id===id);}
function workingOrder(o){const cached=sheetOrders.get(o.id);if(!cached||(cached.version!==o.version&&!orderDirty(cached))){sheetOrders.set(o.id,structuredClone(o));sheetBaselines.set(o.id,JSON.stringify(businessPayload(o)));if(!decisionDirty.has(o.id))for(const k of [...lineChoices.keys()])if(k.startsWith(o.id+'|'))lineChoices.delete(k);}return sheetOrders.get(o.id);}
function editableSheetOrder(o){return !o.discount_cents&&!o.rounding_cents&&!o.paid_cents&&!o.return_credit_cents&&['draft','dispatched','negotiation'].includes(o.state)&&canAction('orders.write')&&(canAction('finance.settle')||o.state!=='negotiation');}
function businessPayload(o){return {version:o.version,dispatch_required:true,workflow_version:1,delivery_method:o.delivery_method,customer_id:o.customer_id,business_date:o.business_date,batch:o.batch,note:o.note,...(typeof accountingReturnPayload==='function'&&accountingReturnPayload(o)?{accounting_returns:accountingReturnPayload(o)}:{}),lines:o.lines.map(l=>({product_id:l.product_id,...(typeof accountingCrateLines==='function'&&crateAttributes(l.product_id).length===1&&l.unit==='筐'?{crate_lines:accountingCrateLines(o,l),auto_crate:true}:Object.hasOwn(l,'crate_lines')?{crate_lines:l.crate_lines}:{}),...(l.driver_weight_basis?{driver_weight_basis:l.driver_weight_basis}:{}),ordered_qty:l.ordered_qty,actual_qty:l.actual_qty,price:l.price,package_net_kg:l.package_net_kg||'',factory_net_kg:l.factory_net_kg||'',package_customer_net_kg:l.package_customer_net_kg||'',not_shipped:!!l.not_shipped,driver:activeWeightRows(o,l,'driver'),customer:activeWeightRows(o,l,'customer')}))};}
function orderDirty(o){const old=originalOrder(o.id);return !!old&&JSON.stringify(businessPayload(o))!==(sheetBaselines.get(o.id)||JSON.stringify(businessPayload(old)));}
function choiceKey(o,l){return o.id+'|'+l.product_id;}
function lineChoice(o,l){const key=choiceKey(o,l);if(lineChoices.has(key)&&!lineChoices.get(key).manualMode&&!l.settlement_mode)lineChoices.get(key).mode=defaultSettlementMode(o,l);if(!lineChoices.has(key))lineChoices.set(key,{mode:defaultSettlementMode(o,l),net:l.agreed_net||'',tares:l.settlement_tares?.customer===undefined?{}:{customer:l.settlement_tares.customer}});return lineChoices.get(key);}
function customerLocation(c){const m=(data.delivery_markets||[]).find(m=>c.market_id?m.id===c.market_id:m.name===c.route);return {region:c.region||m?.city||'',market:m?.name||c.route||''};}
function compareLocationText(a,b){return a&&b?a.localeCompare(b,'zh-CN',{numeric:true}):a?-1:b?1:0;}
function marketSortedCustomers(rows){return [...rows].sort((a,b)=>{const x=customerLocation(a),y=customerLocation(b);return compareLocationText(x.region,y.region)||compareLocationText(x.market,y.market)||a.id.localeCompare(b.id,undefined,{numeric:true});});}
function marketGroupHeading(c,colspan,last){const loc=customerLocation(c),key=JSON.stringify([loc.region,loc.market]);return {key,html:key===last?'':`<tr class="matrix-market-heading"><th colspan="${colspan}">${esc(loc.region||'未设置地区')} · ${esc(loc.market||'未设置市场 / 收货点')}</th></tr>`};}

let crateOwed=null,crateOwedLoading=false;
function loadCrateOwed(){
 if(crateOwed!==null||crateOwedLoading||typeof api!=='function')return;
 crateOwedLoading=true;
 api('/api/crate-ledger?date='+today()).then(v=>{crateOwed=v.customers||{};crateOwedLoading=false;if(typeof render==='function')render();}).catch(()=>{crateOwed={};crateOwedLoading=false;});
}
function crateOwedBadge(cid){const r=crateOwed?.[cid];if(!r||!r.qty)return '';const older=Number(r.older||0);return `<span class="badge orange" data-crate-owed title="最早欠框 ${esc(r.oldest||'')}">欠框 ${num(r.qty)}${older?' · 超90天 '+num(older):''}</span>`;}
function matchesSheet(c){return (!sheetRoute||c.route===sheetRoute)&&(!sheetSearch||[c.id,c.name,c.route].join(' ').toLowerCase().includes(sheetSearch.toLowerCase())||data.orders.some(o=>o.customer_id===c.id&&o.id.toLowerCase().includes(sheetSearch.toLowerCase())));}
function sheetTripOptions(){const trips=new Map();for(const p of data.dispatch_plans||[])if(!selectedDate||p.business_date===selectedDate)for(const t of p.trips)trips.set(t.id,t);return [...trips.values(),{id:'pickup',name:'客户自取'}];}
function sheetControls(mode){const date=mode==='order'?sheetDate():selectedDate;
 return `<div class="sheet-filters">${mode==='account'&&typeof rangeControls==='function'?rangeControls():`<div class="sheet-date-control"><label>业务日期${mode!=='order'&&!date?' · 全部日期':''}<input id="sheet-date" type="date" value="${esc(date)}" aria-label="筛选业务日期"></label>${mode!=='order'?`<div class="sheet-date-shortcuts"><button class="text-button" data-sheet-action="today">今天</button><button class="text-button ${!date?'selected':''}" data-sheet-action="all-dates">全部日期</button></div>`:''}</div>`}<label>配送趟次<select id="sheet-trip"><option value="">全部趟次</option>${sheetTripOptions().map(t=>`<option value="${esc(t.id)}" ${sheetTrip===t.id?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label><label>市场 / 线路<select id="sheet-route"><option value="">全部线路</option>${[...new Set(data.customers.map(c=>c.route))].map(r=>`<option ${r===sheetRoute?'selected':''}>${esc(r)}</option>`).join('')}</select></label>${mode==='order'?'<span class="help-text">一天一张总表 · 全部订货按客户汇总</span>':`<label>状态<select id="sheet-status">${sheetStatusOptions(mode).map(([v,l])=>`<option value="${v}" ${sheetStatus===v?'selected':''}>${l}</option>`).join('')}</select></label>`}<label class="sheet-search">查找客户 / 单号<input id="sheet-search" placeholder="客户编号、名称、线路、单号" value="${esc(sheetSearch)}"></label></div>`;
}
function renderOrderArchive(){return renderSettlementArchive();}

function settlementDefaultStage(){if(role==='管理员')return 'pending';if(canAction('finance.settle'))return 'pending';if(canAction('finance.review'))return 'ready';return 'all';}
function settlementStages(){const stages=[];if(canAction('finance.settle'))stages.push(['pending','会计算票'],['rework','待重算']);if(canAction('finance.review'))stages.push(['ready','出纳待复核']);stages.push(['reviewed','已复核账单']);return stages.length>1?stages:[['all','全部交接进度'],['pending','算票进度'],['ready','复核进度'],['reviewed','已复核账单']];}
function settlementStageMatch(o,stage){if(stage==='all')return true;const s=orderStageKey(o);if(stage==='pending')return ['weight','shipping'].includes(s);if(stage==='handed')return !!o.weight_confirmation;if(stage==='negotiation')return s==='pending';return stage===s;}
function settlementStageCounts(){const search=(sheetSearch||'').trim().toLowerCase();const counts={};for(const [key] of settlementStages())counts[key]=data.orders.filter(o=>processingDateMatches(o)&&(!sheetTrip||typeof orderTripId!=='function'||orderTripId(o)===sheetTrip)&&(!sheetRoute||data.customers.find(c=>c.id===o.customer_id)?.route===sheetRoute)&&(!search||[o.id,o.customer_id,data.customers.find(c=>c.id===o.customer_id)?.name||''].join(' ').toLowerCase().includes(search))&&settlementStageMatch(o,key)).length;return counts;}
function settlementStageTabs(){const stages=settlementStages();if(!stages.some(([key])=>key===sheetStatus))sheetStatus=settlementDefaultStage();const counts=settlementStageCounts();return `<div class="workflow-tabs" role="tablist" aria-label="结算作业环节">${stages.map(([key,label])=>`<button role="tab" aria-selected="${sheetStatus===key}" class="${sheetStatus===key?'active':''}" data-settlement-stage="${key}">${label}<span class="tab-count">${counts[key]||0}</span></button>`).join('')}</div>`;}
function sheetStatusOptions(mode){if(mode==='weight')return [['all','全部单据'],['shipping','待发货'],['weight','待确认称重'],['handed','已交会计']];return [['all','全部单据'],...settlementStages().filter(([key])=>key!=='all')];}

function renderWorkbench(mode){
 if(deliveryHistoryActive())return deliveryHistoryPage();
 if(mode==='account'&&accountingBook==='purchase')return renderFinishedAccounting();

 sheetArchive=false;if(mode==='weight'&&canAction('weight.write'))autoFillActual();
 const titles={order:['订货总表','按市场集中客户，逐步填订货并保存；下方实时汇总需求，方便与厂长沟通。'],weight:['称重总表','司机直接录入净重；客户复称按实发量和客户皮重扣皮，算票时可调整客户皮重。'],account:[canAction('finance.settle')?(canAction('finance.review')?'算票与复核':'会计算票'):canAction('finance.review')?'账单复核':'结算与复核进度',canAction('finance.settle')?'按产品集中录入所有客户，或按客户核对整单；确认算票后交出纳复核。':canAction('finance.review')?'对照原始凭据核对账单，确认应收或退回会计重算。':'查看各岗位交接进度与已复核账单。']};
 const actions=`${['weight','account'].includes(mode)?deliveryHistoryButton('feedback','配送反馈历史'):''}${mode==='account'&&canAction('finance.statement-issue')?'<button class="button" data-act="batch-statements">批量归档结算单</button>':''}${mode==='weight'&&canAction('weight.confirm')?'<button class="button workflow-next" data-required-action="weight.confirm" data-sheet-action="confirm-weight-batch">批量交接</button>':''}${mode==='order'?warehousePrintButtons():''}${canAction('orders.write')&&(mode!=='weight'||canAction('weight.write'))?`<button class="button primary" data-sheet-action="save"><span class="button-label">${mode==='account'?'保存改单':mode==='order'?'保存订货':'保存改动'}</span><span class="button-count" id="sheet-dirty"></span></button>`:''}`;
 const html=head(titles[mode][0],titles[mode][1],actions,'DAILY WORKSHEET · 连续作业')+(mode==='account'?accountingBookTabs()+settlementStageTabs()+accountingViewControls():'')+sheetControls(mode)+`<div id="sheet-error" class="sheet-error" role="alert" ${sheetError?'':'hidden'}>${esc(sheetError)}</div>`+(mode==='order'?(renderOrderDemand()+renderOrderMatrix()):mode==='account'&&accountView==='product'?renderProductAccounting():renderProcessingSheet(mode))+`<div class="sheet-help"><span>Tab 下一格 · Enter 下一格 · Ctrl/⌘+S 保存 · 支持整块粘贴</span><span>空白或 0 表示未订该产品；已保存的原始称重保留不变。</span><span>数字可整块粘贴，跳过只读单元格；跳转前请保存或明确放弃修改。</span></div>`;
 setTimeout(()=>{updateSheetTotals();restoreValidation();},0);return html;
}
function getMatrixRow(c,source){const key=source?source.id:`NEW|${sheetDate()}|日常订货|${c.id}`;
 const cached=matrixRows.get(key);if(cached&&source&&cached.version!==source.version&&!matrixDirty(cached))matrixRows.delete(key);
 if(!matrixRows.has(key)){
  const values=Object.fromEntries(data.products.map(p=>[p.id,source?.lines.find(l=>l.product_id===p.id)?.ordered_qty||'']));
  matrixRows.set(key,{key,cid:c.id,date:sheetDate(),batch:source?.batch||'日常订货',id:source?.id,version:source?.version,values,initial:{...values}});
 }const row=matrixRows.get(key);for(const p of data.products){if(row.values[p.id]===undefined)row.values[p.id]='';if(row.initial[p.id]===undefined)row.initial[p.id]='';}return row;
}

function matrixDirty(r){return data.products.some(p=>Number(r.values[p.id]||0)!==Number(r.initial[p.id]||0));}
function matrixVisibleRows(){const result=[];for(const c of marketSortedCustomers(data.customers.filter(c=>c.business_kind!=='byproduct'&&(c.ordering_enabled!==0||data.orders.some(o=>o.customer_id===c.id&&o.business_date===sheetDate()))).filter(c=>matchesSheet(c)&&(!sheetTrip||typeof customerTripId!=='function'||customerTripId(c,sheetDate())===sheetTrip)))){
 const sources=data.orders.filter(o=>o.customer_id===c.id&&o.business_date===sheetDate());
 if(sources.length)for(const o of sources)result.push({c,o,row:getMatrixRow(c,o)});
 else result.push({c,o:null,row:getMatrixRow(c,null)});
 }return result;}
function sheetInput(value,attrs='',disabled=false){return `<input class="grid-input" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" value="${esc(value)}" ${attrs} ${disabled?'disabled':''}>`;}
function dailyMatrixGroups(){const groups=[];for(const item of matrixVisibleRows()){let g=groups.find(g=>g.c.id===item.c.id);if(!g){g={c:item.c,items:[]};groups.push(g);}g.items.push(item);}return groups;}
function orderDayDemand(pid){let demand=data.orders.filter(o=>o.business_date===sheetDate()).reduce((n,o)=>n+Number(o.lines.find(l=>l.product_id===pid)?.ordered_qty||0),0);for(const row of matrixRows.values())if(row.date===sheetDate())demand+=Number(row.values[pid]||0)-Number(row.id?data.orders.find(o=>o.id===row.id)?.lines.find(l=>l.product_id===pid)?.ordered_qty||0:0);return demand;}
function orderInventoryText(p){const plan=typeof warehouseSaved==='function'?warehouseSaved(sheetDate()):null,previous=typeof inventoryClosing==='function'?inventoryClosing(previousDay(sheetDate())):null,base=plan||{business_date:sheetDate(),stock:(previous?.products||[]).map(r=>({product_id:r.product_id,existing_qty:r.counted_qty,produced_qty:'0'})),allocations:[]},t=typeof warehouseTotals==='function'?warehouseTotals(base,p):null,known=t?.available!==null&&t?.available!==undefined,demand=orderDayDemand(p.id);return {known,demand,available:known?t.available:null,shipped:t?.shipped||0,shortage:known&&demand>t.available,text:known?(demand>t.available?'缺货 '+num(demand-t.available)+' '+p.unit:'还可接单 '+num(t.available-demand)+' '+p.unit):'昨日结转未确认'};}
function orderInventoryCells(p){const info=orderInventoryText(p);return `<td class="inventory-number">${num(info.demand)}</td><td class="inventory-number">${info.known?num(info.available):'<span class="inventory-pending">待确认</span>'}</td><td class="inventory-number">${num(info.shipped)}</td><td class="inventory-number">${info.known?num(info.available-info.shipped):'—'}</td><td><span class="inventory-status ${info.shortage?'shortage':info.known?'inventory-sufficient':'inventory-pending'}">${esc(info.text)}</span></td>`;}
function renderOrderDemand(){return `<section class="panel order-demand"><div class="panel-head"><div><h2>订货与实际库存提示</h2><p>全日订货包含未保存输入，不受客户筛选影响。库存不足可继续订货，再到发货分配调整；实发以确认分配为准。</p></div></div><div class="order-inventory-list"><table><thead><tr><th>产品 / 单位</th><th>当前筛选订货</th><th>全日订货</th><th>可发库存</th><th>已录实发</th><th>账面剩余</th><th>库存提示</th></tr></thead><tbody>${data.products.map(p=>`<tr data-order-inventory="${p.id}"><th scope="row">${esc(p.name)} <small>${esc(p.unit)}</small></th><td class="inventory-number"><strong data-demand-total="${p.id}">—</strong></td>${orderInventoryCells(p)}</tr>`).join('')}</tbody></table></div><p class="order-inventory-note">可发库存＝昨日结转＋当天生产＋转加工产出＋退货可发入库－转加工投入－报损。昨日结转为空表示未确认；无结转请填写 0。</p></section>`;}

function renderOrderMatrix(){const groups=dailyMatrixGroups();let gridRow=0,lastMarket='';
 const detail=({c,o,row},extra=false)=>{loadCrateOwed();const locked=o?!editableSheetOrder(o):!canAction('orders.write'),r=gridRow++;return `<tr data-matrix-row="${esc(row.key)}" ${extra?'class="matrix-original"':''}><td class="freeze-client"><strong>${extra?'原单 '+esc(o.id.slice(-6)):esc(c.name)}</strong>${extra?'':crateOwedBadge(c.id)}<small>${extra?esc(o.id):((o?isPickupOrder(o):c.delivery_method==='pickup')?'自取':'')}</small></td>${data.products.map((p,col)=>`<td>${sheetInput(row.values[p.id],`data-matrix-key="${esc(row.key)}" data-product-id="${p.id}" data-customer-id="${esc(c.id)}" data-grid-row="${r}" data-grid-col="${col}" aria-label="${esc(c.name)} ${extra?'原单'+esc(o.id.slice(-6))+' ':''}${esc(p.name)}订货${p.unit}"`,locked)}</td>`).join('')}<td>${o?badge(o):'<span class="dim">未订货</span>'}${o&&!locked?'<small>可修改</small>':o?'<small>只读</small>':''}</td></tr>`;};
 return `<section class="panel worksheet-panel"><div class="sheet-table-caption"><b>${esc(sheetDate())} · 当天全部订货</b><span>按地区 → 市场 → 客户排列；历史多张原单汇总显示</span><div class="head-actions">${canOpenWorkflow('allocation','inventory.stock')?'<button class="button workflow-next" data-required-action="inventory.stock" data-page="allocation">库存分配 ↗</button>':''}</div></div><div class="table-wrap expanded-table"><table class="worksheet matrix order-matrix" data-sheet-grid="matrix"><colgroup><col class="client-col">${data.products.map(()=>'<col class="product-col">').join('')}<col class="progress-col"></colgroup><thead><tr><th class="freeze-client">客户 / 线路</th>${data.products.map(p=>`<th>${esc(p.name)}<small>${esc(p.unit)}</small></th>`).join('')}<th>进度</th></tr></thead><tbody>${groups.map(g=>{const heading=marketGroupHeading(g.c,data.products.length+2,lastMarket),divider=heading.html;lastMarket=heading.key;if(g.items.length===1)return divider+detail(g.items[0]);return divider+`<tr class="daily-client-total"><td class="freeze-client"><strong>${esc(g.c.name)}</strong><small>${esc(g.c.route)}${g.c.delivery_method==='pickup'?' · 自取':''}</small><button class="text-button" data-sheet-action="toggle-originals" data-cid="${esc(g.c.id)}">${matrixExpanded.has(g.c.id)?'收起原单':'展开原单修改'} · ${g.items.length}单</button></td>${data.products.map(p=>`<td class="mono" data-daily-client="${esc(g.c.id)}" data-daily-product="${p.id}">${num(g.items.reduce((n,{row})=>n+Number(row.values[p.id]||0),0))}</td>`).join('')}<td>当天合计<small>修改请展开原单</small></td></tr>`+(matrixExpanded.has(g.c.id)?g.items.map(i=>detail(i,true)).join(''):'');}).join('')||'<tr><td colspan="20" class="empty">没有符合条件的客户</td></tr>'}</tbody><tfoot><tr><th class="freeze-client">本页订货需求</th>${data.products.map(p=>`<td class="amount" data-product-total="${p.id}">—</td>`).join('')}<td>${groups.length} 位客户</td></tr></tfoot></table></div><div class="table-end"><span>当天全部原单都计入，不再手动分订货批次</span><span>历史原单、实发和结算记录保留追溯</span></div></section>`;
}
function processingGroups(){const groups=[];for(const c of marketSortedCustomers(data.customers.filter(c=>c.business_kind!=='byproduct').filter(matchesSheet))){
 const orders=data.orders.filter(o=>o.customer_id===c.id&&processingDateMatches(o)&&processingStatusMatches(o)&&(!sheetTrip||typeof orderTripId!=='function'||orderTripId(o)===sheetTrip)&&(!sheetSearch||[c.id,c.name,c.route,o.id].join(' ').toLowerCase().includes(sheetSearch.toLowerCase()))).map(workingOrder);
 if(orders.length)groups.push({c,orders});
 }return groups;}
function virtualWeights(o,l,type){return l[type].length?l[type]:[{gross:'',count:Number(l.actual_qty)>0?String(physicalCrateCount(l)):'',tare:ruleFor(o.customer_id,l.product_id).tare,note:''}];}
function sourceNet(l,type){if(type==='driver'&&l.driver_weight_basis==='gross')return typedDriverNet(l);if(type==='customer'&&l.crate_lines?.some(r=>r.packing_lines))return typedCustomerNet({},l);const rows=l[type];if(!rows.length)return null;let n=0;for(const w of rows){const net=Number(w.gross)-Number(w.count)*Number(w.tare);if(w.gross===''||w.count===''||w.tare===''||!Number.isFinite(net)||net<=0||Number(w.count)<=0)return null;n+=net;}return Number(n.toFixed(3));}
function netText(n){return n===null?'待填写':num(n);}
function weightControls(o,l,type,editable,r,col){return `<div class="mini-labels"><span>毛重</span><span>筐数</span><span>皮重</span></div>${virtualWeights(o,l,type).map((w,j)=>`<div class="weight-inline">${['gross','count','tare'].map((k,i)=>sheetInput(w[k],`data-oid="${esc(o.id)}" data-pid="${l.product_id}" data-source="${type}" data-windex="${j}" data-field="${k}" data-grid-row="${r+j}" data-grid-col="${col+i}" aria-label="${esc(o.customer_name)} ${esc(l.product_name)} ${type==='driver'?'卸货':isPickupOrder(o)?'自提确认':'复称'}第${j+1}批${{gross:'毛重',count:'筐数',tare:'皮重'}[k]}"`,!editable)).join('')}</div>`).join('')}<div class="weight-cell-bottom"><span data-line-net="${type}">净重 ${(type==='customer'&&!isPickupOrder(o)&&!activeWeightRows(o,l,type).length?'未复称（可选）':netText(sourceNet(l,type)))}</span>${editable?`<button data-sheet-action="add-weight" data-oid="${esc(o.id)}" data-pid="${l.product_id}" data-source="${type}">＋ 加一批</button>`:''}</div>`;}
function weightCell(o,l,type,editable,r,col){if(type==='driver'&&isPickupOrder(o)&&!l.driver.length)return `<td class="source-cell pack-note">客户自取，无司机称重</td>`;if(l.not_shipped)return `<td class="source-cell pack-note">本次未发</td>`;return `<td class="source-cell" data-weight-cell="${type}">${weightControls(o,l,type,editable,r,col)}</td>`;}
function driverWeightPhotoKinds(o,pid){const base='weight-'+pid;return Object.keys(o.driver_photos||{}).filter(k=>k===base||k.startsWith(base+'-')).sort((a,b)=>a===base?-1:b===base?1:a.localeCompare(b,{numeric:true}));}
function driverWeightPhotos(o,pid){const kinds=driverWeightPhotoKinds(o,pid);if(!kinds.length)return '';return `<div class="weight-photo-strip">`+kinds.slice(0,3).map(k=>`<a class="weight-photo-thumb" href="/api/driver/photo/${encodeURIComponent(o.id)}/${encodeURIComponent(k)}" target="_blank" rel="noopener" title="查看称重照片" aria-label="查看称重照片"><img src="/api/driver/photo/${encodeURIComponent(o.id)}/${encodeURIComponent(k)}" alt="" loading="lazy"></a>`).join('')+(kinds.length>3?`<span class="weight-photo-more">+${kinds.length-3}</span>`:'')+`</div>`;}
function simpleWeightCell(o,l,type,editable,r,col){
 if(type==='driver'&&isPickupOrder(o)&&!l.driver.length)return `<td class="source-cell pack-note">客户自取</td>`;
 if(l.not_shipped)return `<td class="source-cell pack-note">本次未发</td>`;
 const rows=activeWeightRows(o,l,type),gross=type==='driver'&&l.driver_weight_basis==='gross'?rows.length?String(rows.reduce((n,w)=>n+Number(w.gross||0),0)):'' :type==='driver'?(rows.length===1&&Number(rows[0].tare)===0?rows[0].gross:sourceNet(l,type)===null?'':String(sourceNet(l,type))):rows.length?num(rows.reduce((n,w)=>n+Number(w.gross||0),0)).replaceAll(',',''):'';
 return `<td class="source-cell simple-weight-cell" data-weight-cell="${type}">${sheetInput(gross,`data-oid="${esc(o.id)}" data-pid="${l.product_id}" data-source="${type}" data-simple-weight="${type}" data-windex="0" data-field="gross" data-grid-row="${r}" data-grid-col="${col}" aria-label="${esc(o.customer_name)} ${esc(l.product_name)}${type==='driver'?'司机毛重':'客户复称'}公斤"`,!editable)}<small data-line-net="${type}">净重 ${!rows.length?(type==='customer'?'未复称（可选）':'待填写'):netText(settlementSourceNet(o,l,type))}</small>${type==='driver'&&rows.length&&l.driver_weight_basis!=='gross'?'<small>历史记录为净重，修改后按毛重扣皮</small>':''}${type==='driver'?driverWeightPhotos(o,l.product_id):''}</td>`;
}
function settlementSourceNet(o,l,type){if(type==='customer'&&typeof typedCustomerNet==='function'){const typed=typedCustomerNet(o,l);if(typed!==null)return typed;}const raw=l.unit==='筐'?sourceNet(l,type):Number(l[type==='driver'?'package_net_kg':'package_customer_net_kg']||0)||null,value=lineChoice(o,l).tares?.[type];if(type==='driver'||l.unit!=='筐'||value===undefined||value==='')return raw;if(raw===null)return null;const net=l[type].reduce((n,w)=>n+Number(w.gross),0)-physicalCrateCount(l)*Number(value);return Number.isFinite(net)?Number(net.toFixed(3)):null;}
function selectedSettlementNet(o,l,choice=lineChoice(o,l)){if(['ready','reviewed'].includes(o.state)&&!orderDirty(o)&&l.settlement_mode===choice.mode&&l.bill_qty!=null)return Number(l.bill_qty);return ['driver','customer'].includes(choice.mode)?settlementSourceNet(o,l,choice.mode):settlementNet(l,choice.mode);}
function averageSourceNet(o,l,type,account=false){if(l.unit==='筐'&&!weightSourceReady(o,l,type))return null;const net=account?settlementSourceNet(o,l,type):l.unit==='筐'?sourceNet(l,type):Number(l[type==='driver'?'package_net_kg':'package_customer_net_kg']||0)||null;return net===null||Number(l.actual_qty)<=0?null:Number((net/Number(l.actual_qty)).toFixed(3));}
function weightDifference(o,l,account=false){if(l.unit!=='筐')return '—';const d=account?settlementSourceNet(o,l,'driver'):sourceNet(l,'driver'),c=account?settlementSourceNet(o,l,'customer'):sourceNet(l,'customer');return d===null||c===null?'—':num(d-c);}
function originalSourceTare(o,l,type){const rows=l[type]||[],count=rows.reduce((n,w)=>n+Number(w.count||0),0);return count>0?Number((rows.reduce((n,w)=>n+Number(w.count||0)*Number(w.tare||0),0)/count).toFixed(3)):Number(ruleFor(o.customer_id,l.product_id).tare||0);}
function tareCellContent(o,l,account=false,r=0){
 if(l.unit!=='筐')return '—';
 if(typeof typedCrates==='function'&&typedCrates(o,l).length){const rows=typedCrates(o,l);const body=account?'<div class="ui-tare-list">'+rows.map(x=>`<div class="ui-tare-item"><span>${esc(x.asset_name)}</span><span>${x.packing_lines?'合计 '+num(crateLineTare(x))+' 公斤':num(x.tare)+' 公斤/个'}</span>${x.packing_lines?'<small>'+x.packing_lines.map(p=>esc(p.method_name||'原包法')+' '+num(p.qty)+'×'+num(p.tare)).join('，')+'</small>':''}</div>`).join('')+'</div>':rows.map(x=>`<div class="tare-row"><b>${esc(x.asset_name)}</b> ${num(x.qty)} 个${x.packing_lines?`<small>${x.packing_lines.map(p=>esc(p.method_name||'原包法')+' '+num(p.qty)+'×'+num(p.tare)).join('，')}</small><small>皮重合计 ${num(crateLineTare(x))} 公斤</small>`:`<small>单筐 ${num(x.tare)} 公斤</small>`}</div>`).join('');return body+(rows.some(x=>x.packing_lines)?(typeof packagingButton==='function'?packagingButton(o,l,account&&editableSheetOrder(o)):''):`<button class="text-button" data-trade-shipment="${esc(o.id)}">框型与皮重</button>`);}
 const choice=lineChoice(o,l),base=originalSourceTare(o,l,'customer'),value=choice.tares?.customer,editable=account&&editableSheetOrder(o)&&canAction('finance.settle')&&l.customer.length&&!l.not_shipped;
 return account?sheetInput(value??base,`data-oid="${esc(o.id)}" data-pid="${l.product_id}" data-tare-source="customer" data-field="settlement_tare" data-grid-row="${r}" data-grid-col="5" aria-label="${esc(o.customer_name)} ${esc(l.product_name)}客户复称单筐皮重"`,!editable):num(base);
}

function settlementWeightCell(o,l,type){if(l.not_shipped)return '<td class="source-cell pack-note">本次未发</td>';if(type==='driver'&&isPickupOrder(o)&&!l.driver.length)return '<td class="source-cell pack-note">客户自取</td>';return `<td class="source-cell"><span data-source-summary="${type}">${netText(settlementSourceNet(o,l,type))}</span></td>`;}

function lineAmount(o,l){if(l.not_shipped)return 0;if(['ready','reviewed'].includes(o.state)&&!orderDirty(o))return l.amount_cents;const choice=lineChoice(o,l),qty=(l.unit!=='筐'||billingUnit(l)!=='公斤')?(billingUnit(l)==='公斤'?packageBillKg(l):l.actual_qty):(choice.mode==='agreed'?choice.net:selectedSettlementNet(o,l,choice));if(qty===null||qty==='')return null;return roundedCents(qty,l.price);}
function roundedCents(qty,price){const scaled=x=>{const s=String(x);if(!/^\d+(\.\d{0,3})?$/.test(s))return null;const [a,b='']=s.split('.');return BigInt(a)*1000n+BigInt((b+'000').slice(0,3));};const q=scaled(qty),p=scaled(price);return q===null||p===null?null:Number((q*p+5000n)/10000n);}
function reasonKey(c){return sheetDate()+'|'+c.id;}
function weightHandoffStatus(o){return o.weight_confirmation&&!canAction('finance.settle')?'已交会计':o.status;}
function workflowStatusTone(label,fallback='pending'){
 if(/未保存|待确认算票修改|待重算|协商|已退回|已驳回|已作废|已撤回|异常|少回|多回/.test(label))return 'attention';
 if(/已交会计|待收款|已收清|已结清|已抵清|已清账|已完成|已复核|已确认|已通过|已归档|全部入库|一致/.test(label))return 'complete';
 if(/等待|暂无/.test(label))return 'neutral';
 if(/待|草稿|未|部分/.test(label))return 'pending';
 return fallback;
}
function normalizeWorkflowStatuses(root){
 for(const el of root.querySelectorAll('.badge,.workflow-status,.client-progress-badge')){
  const fallback=el.matches('.green,.complete,.done')?'complete':el.matches('.red,.attention,.unsaved')?'attention':el.matches('.orange,.blue,.pending')?'pending':'neutral';
  el.dataset.workflowTone=workflowStatusTone(el.textContent.trim(),fallback);
 }
}
function clientWorkflowProgress(orders,mode='account'){
 const statuses=new Map();for(const o of orders){const label=mode==='weight'?weightHandoffStatus(o):o.status;statuses.set(label,(statuses.get(label)||0)+1);}
 return [...statuses].map(([label,count])=>`<span class="client-progress-badge ${workflowStatusTone(label)}">${esc(label)}${statuses.size>1?' · '+count+'单':''}</span>`).join('')+(orders.some(orderDirty)?'<span class="client-progress-badge unsaved">有未保存修改</span>':'')+(mode==='account'&&orders.some(o=>decisionDirty.has(o.id))?'<span class="client-progress-badge unsaved">有待确认算票修改</span>':'');
}
function clientWeightProgress(orders){return clientWorkflowProgress(orders,'weight');}

// Collapse presentation only: the mounted inputs and working copies remain intact.
const customerDetailStates=new Map();
let customerDialogSequence=0;
function customerDisclosureKey(panel){
 if(panel.matches('.review-order'))return 'review|'+customerDialogSequence+'|'+panel.dataset.reviewOrder;
 return [data?.auth_user?.id||role,page,selectedDate,typeof rangeStart==='undefined'?'':rangeStart,typeof rangeEnd==='undefined'?'':rangeEnd,panel.dataset.clientSheet].join('|');
}
function setCustomerDetails(panel,open){
 const body=panel?.querySelector(':scope > .customer-detail-body'),toggle=panel?.querySelector('[data-customer-toggle]');if(!body||!toggle)return;
 customerDetailStates.set(panel.dataset.customerDisclosure,open);body.hidden=!open;toggle.setAttribute('aria-expanded',String(open));
 toggle.querySelector('.customer-detail-label').textContent=open?'收起明细':'展开明细';
 panel.classList.toggle('customer-details-open',open);
 if(open&&typeof alignBusinessTables==='function')alignBusinessTables(body);
}
function openCustomerDetailsFor(target){
 const panel=target?.closest('.customer-disclosure');if(panel)setCustomerDetails(panel,true);
}
function setupCustomerDisclosures(root){
 for(const panel of root.querySelectorAll('.client-sheet,.review-order')){
  if(panel.dataset.customerDisclosure)continue;
  const review=panel.matches('.review-order'),header=review?panel.querySelector(':scope > h3'):panel.querySelector(':scope > .client-sheet-head'),title=review?header:header?.querySelector('h2');
  if(!header||!title)continue;
  header.dataset.customerHeader='';
  const key=customerDisclosureKey(panel),id='customer-detail-'+Array.from(key,c=>c.codePointAt(0).toString(16)).join('-');
  panel.dataset.customerDisclosure=key;panel.classList.add('customer-disclosure');
  const toggle=document.createElement('button');toggle.type='button';toggle.className='customer-detail-toggle';toggle.dataset.customerToggle='';toggle.setAttribute('aria-controls',id);
  toggle.innerHTML='<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="m7 4 6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="customer-toggle-title"></span><span class="customer-detail-label"></span>';
  toggle.querySelector('.customer-toggle-title').innerHTML=title.innerHTML;title.replaceChildren(toggle);
  const body=document.createElement('div');body.className='customer-detail-body';body.id=id;
  while(header.nextSibling)body.append(header.nextSibling);
  const references=header.querySelector('.client-order-references');if(references)body.prepend(references);
  panel.append(body);
  if(!review){
   const save=header.querySelector('[data-sheet-action="save-weight-client"]');
   if(save){const actions=document.createElement('div');actions.className='client-header-actions';actions.append(save);header.append(actions);}
   const row=header.querySelector('.client-name-row');
   if(!row.querySelector('.client-weight-progress')){
    const progress=document.createElement('div');progress.className='client-weight-progress';progress.dataset.clientFlowProgress=panel.dataset.clientSheet;progress.setAttribute('aria-live','polite');
    const group=processingGroups().find(g=>g.c.id===panel.dataset.clientSheet);progress.innerHTML=clientWorkflowProgress(group?.orders||[]);row.append(progress);
   }
  }
  setCustomerDetails(panel,customerDetailStates.get(key)===true);
 }
}
document.addEventListener('click',event=>{
 const header=event.target.closest('[data-customer-header]');if(!header)return;
 const action=event.target.closest('button,a,input,select,textarea,label,[role="button"],[contenteditable]');
 if(action&&!action.matches('[data-customer-toggle]'))return;
 if(window.getSelection()?.isCollapsed===false)return;
 const toggle=header.querySelector('[data-customer-toggle]');
 if(toggle)setCustomerDetails(header.closest('.customer-disclosure'),toggle.getAttribute('aria-expanded')!=='true');
});
function clientWeightControls(c,orders){return `<div class="client-weight-controls"><div class="client-weight-progress" data-client-weight-progress="${esc(c.id)}" aria-live="polite">${clientWeightProgress(orders)}</div>${canAction('orders.write')&&canAction('weight.write')&&orders.some(editableSheetOrder)?`<button class="button primary" data-required-action="weight.write" data-sheet-action="save-weight-client" data-cid="${esc(c.id)}"><span class="button-label">保存本客户</span><span class="button-count" data-client-save-count="${esc(c.id)}"></span></button>`:''}</div>`;}
function standardWeightText(l){return `<span class="standard-total">${standardLineWeight(l)>0?num(standardLineWeight(l)):'—'}</span><small>${standardUnitWeight(l)>0?num(standardUnitWeight(l))+'/'+esc(l.unit):'未设置'}</small>`;}

function processingHeaders(mode,orders,focus=''){const units=[...new Set(orders.flatMap(o=>o.lines.filter(l=>!focus||l.product_id===focus).map(billingUnit)))],unit=units.join(' / '),th=(title,unit='',cls='')=>`<th class="${cls}">${title}${unit?`<small>${esc(unit)}</small>`:''}</th>`,averages=th('客户皮重','公斤 / 筐','tare-heading')+th('平均司机净重','公斤 / 筐·包','average-heading')+th('平均客户净重','公斤 / 筐·包','average-heading');return th('产品','','freeze-product')+th('订货','筐 / 包')+th('实发','筐 / 包')+(mode==='weight'?th('标准重量','公斤','standard-heading')+th('出厂净重','公斤','factory-heading')+th('司机毛重','公斤','source-heading')+th('客户复称','公斤 · 可选','source-heading')+averages+th('净重差','公斤','diff-heading'):th('司机毛重','公斤')+th('客户复称毛重 / 自提确认','公斤 · 可选','source-heading')+th('发出框型','个')+th('收回框数','昨日发出 · 个')+averages+th('净重差','公斤')+th('单价','元 / '+unit)+th('计价依据')+th(units.every(u=>u==='公斤')?'结算总重':'结算总量',units.every(u=>u==='公斤')?'公斤':'按计价单位')+th('分项金额','元'));}
function averageWeightDeviation(o,l,type,account=false){
 const standard=standardUnitWeight(l),average=averageSourceNet(o,l,type,account),rawThreshold=Number(data.weighing_settings?.average_weight_alert_kg??0.5),threshold=Number.isFinite(rawThreshold)&&rawThreshold>=0?rawThreshold:0.5;
 if(average===null||!Number.isFinite(standard)||standard<=0)return null;
 const delta=Number((average-standard).toFixed(3)),absolute=Math.abs(delta);
 if(absolute<=threshold)return null;
 const direction=delta>0?'high':'low';
 return {direction,kg:absolute,short:`${direction==='high'?'多于':'少于'}标准 ${num(absolute)}kg`,title:`${direction==='high'?'多于':'少于'}标准单重 ${num(absolute)} 公斤/筐 · 标准 ${num(standard)} 公斤/${l.unit} · 提示阈值 ${num(threshold)} 公斤`};
}
function averageWeightCell(o,l,type,account=false){const value=averageSourceNet(o,l,type,account),deviation=averageWeightDeviation(o,l,type,account);return `<td class="mono${deviation?' weight-average-alert '+deviation.direction:''}" data-average-net="${type}"${deviation?` data-average-deviation="${deviation.direction}" title="${esc(deviation.title)}"`:''}>${value===null?'—':num(value)}${deviation?'<small>'+esc(deviation.short)+'</small>':value!==null&&!(standardUnitWeight(l)>0)?'<small>未配置标准单重</small>':''}</td>`;}
function averageWeightCells(o,l,mode,r){return `<td class="mono" data-tare-cell>${tareCellContent(o,l,mode==='account',r)}</td>`+averageWeightCell(o,l,'driver',mode==='account')+averageWeightCell(o,l,'customer',mode==='account');}


function renderWeightLoadSummary(groups){const lines=groups.flatMap(g=>g.orders.flatMap(o=>o.lines));return `<section class="panel weight-load-summary"><div class="panel-head"><div><h2>装货汇总</h2><p>当前筛选范围 · ${groups.length} 位客户</p></div></div><div class="table-wrap"><table><thead><tr><th>产品</th><th>订货量<small>筐 / 包</small></th><th>实发量<small>筐 / 包</small></th></tr></thead><tbody>${data.products.map(p=>{const rows=lines.filter(l=>l.product_id===p.id);return rows.length?`<tr><th>${esc(p.name)}</th><td class="quantity-unit">${num(rows.reduce((n,l)=>n+Number(l.ordered_qty||0),0))}</td><td class="quantity-unit" data-weight-load-actual="${p.id}">${num(rows.reduce((n,l)=>n+Number(l.actual_qty||0),0))}</td></tr>`:'';}).join('')}</tbody></table></div></section>`;}
function renderProcessingSheet(mode){const groups=processingGroups();let rowIndex=0;
 if(!groups.length)return `<section class="panel"><div class="empty">当前筛选下没有符合条件的单据。可选择全部日期、全部单据，或清除线路与搜索条件。</div></section>`;
 return `${mode==='weight'?renderWeightLoadSummary(groups):''}<div class="sheet-groups">${groups.map(({c,orders})=>{const candidates=orders.filter(o=>editableSheetOrder(o)),reviewable=orders.filter(o=>o.state==='ready');const noteKey=reasonKey(c);if(!clientReasons.has(noteKey))clientReasons.set(noteKey,orders.find(o=>o.state==='negotiation')?.settlement?.reason||'');
 return `<section class="panel client-sheet" data-client-sheet="${esc(c.id)}"><div class="client-sheet-head prominent-client-head"><div><div class="client-name-row"><h2>${esc(c.name)}</h2>${mode==='weight'?clientWeightControls(c,orders):''}</div><span>${esc(c.id)} · ${esc(c.route)} · ${c.delivery_method==='pickup'?'客户自取 · ':''}${orders.length} 张原单 / ${orders.reduce((s,o)=>s+o.lines.length,0)} 项产品</span><div class="client-order-references">${orders.map(o=>`<small>${esc(o.business_date)} · ${esc(o.id)}${mode==='weight'?'':' · '+esc(o.status)}</small>`).join('')}</div></div>${mode==='account'?`<div class="client-sheet-total"><small>${orders.some(o=>!['ready','reviewed'].includes(o.state))?'产品合计（含试算）':'客户账单合计'}</small><strong data-client-total="${esc(c.id)}">—</strong></div>`:''}</div>${mode==='account'&&typeof reviewHistory==='function'?orders.map(reviewHistory).join(''):''}${mode==='account'&&typeof clientReturnsPanel==='function'?clientReturnsPanel(c):''}<div class="table-wrap ${mode==='weight'?'weight-expanded':'sheet-scroll'}"><table class="worksheet processing ${mode}" data-sheet-grid="${esc(c.id)}-${mode}"><thead><tr>${processingHeaders(mode,orders)}</tr></thead><tbody>${orders.map(o=>o.lines.map(l=>{const r=rowIndex;rowIndex+=Math.max(l.driver.length,l.customer.length,1)+1;return processingRow(mode,c,o,l,r);
 }).join('')).join('')}</tbody></table></div>${mode==='weight'?`<div class="client-sheet-actions">${canAction('weight.confirm')&&orders.some(o=>['draft','dispatched'].includes(o.state)&&(!o.weight_confirmation||orderDirty(o)))?`<label class="check-line client-review"><input type="checkbox" data-weight-evidence="${esc(c.id)}">已核对本客户实发数量与称重</label><button class="button workflow-next" data-required-action="weight.confirm" data-sheet-action="confirm-weight-client" data-cid="${esc(c.id)}">确认交接</button>`:orders.some(o=>o.weight_confirmation)?'<span class="help-text">称重已确认并提交；会计在待算票中处理。</span>':''}${canOpenWorkflow('settlements','finance.settle')?`<button class="button" data-sheet-action="account-client" data-cid="${esc(c.id)}">查看本客户算票 ↗</button>`:''}</div>`:''}${mode==='account'?`<div class="client-sheet-actions">${orders.some(o=>o.settlement?.reason)?`<div class="client-settlement-notes">${orders.filter(o=>o.settlement?.reason).map(o=>`<p><b>原单 ${esc(o.id.slice(-6))} · ${esc(o.status)}</b> ${esc(o.settlement.reason)}</p>`).join('')}</div>`:''}${canAction('finance.settle')&&candidates.length?`<label class="client-reason">结算说明 / 协商原因<input data-client-reason="${esc(c.id)}" value="${esc(clientReasons.get(noteKey))}" maxlength="500" placeholder="有协商产品时必填；本客户的产品一起提交"></label>`:''}${orders.some(o=>o.driver_photos&&Object.keys(o.driver_photos).length)?`<button class="button" data-sheet-action="driver-photos" data-cid="${esc(c.id)}">查看司机照片</button>`:''}${canAction('finance.settle')&&candidates.length?`<label class="check-line"><input type="checkbox" data-account-evidence="${esc(c.id)}">已核对司机照片、重量和框数</label><button class="button workflow-next" data-required-action="finance.settle" data-sheet-action="settle-client" data-cid="${esc(c.id)}">确认算票 <span>· ${candidates.length} 单</span></button>`:''}${canAction('finance.statement-issue')?`<button class="button" data-act="export-statement" data-id="${esc(c.id)}">导出结算单图片</button>`:''}${canAction('finance.review')&&reviewable.length?`<span class="help-text">复核前请准备本客户原始凭据，在对照窗口确认或退回。</span><button class="button workflow-next" data-required-action="finance.review" data-sheet-action="review-client" data-cid="${esc(c.id)}">打开复核对照 · ${reviewable.length} 单</button>`:''}${orders.some(o=>['draft','dispatched'].includes(o.state)&&!o.weight_confirmation)?`<span class="help-text">可在本表录入司机照片的重量与框数，勾选核对后一次完成交接和算票。</span><button class="button" data-sheet-action="weight-client" data-cid="${esc(c.id)}">去确认本客户称重 ↗</button>`:''}${!canAction('finance.settle')&&!canAction('finance.review')?'<span class="help-text">算票与复核由有相应权限的人员处理。</span>':''}</div>`:''}</section>`;}).join('')}</div>`;
}

function shipmentQuantityCell(c,o,l,r){
 const attrs=`data-oid="${esc(o.id)}" data-pid="${esc(l.product_id)}" data-field="actual_qty" data-actual-changed="${actualQuantityChanged(o,l)}" data-grid-row="${r}" data-grid-col="0"`;
 const editable=editableSheetOrder(o)&&canAction('weight.write'),closed=closedShipmentDay(o.business_date);
 if(editable&&canAction('finance.settle')&&(o.review_return?.status==='pending'||closed))return `<button type="button" class="shipment-quantity-edit" ${attrs} data-order-correction="shipment" data-order="${esc(o.id)}" data-focus-product="${esc(l.product_id)}" aria-label="${esc(c.name)} ${esc(l.product_name)}修改实发数量"><strong>${num(l.actual_qty)}</strong><span>修改实发</span></button><small>${closed?'已日结 · 更正保留原实盘':'待重算 · 可增减实发'}</small>`;
 return sheetInput(l.actual_qty,`${attrs} aria-label="${esc(c.name)} ${esc(l.product_name)}实发数量"`,!editable||!allocationReady(o,l)||closed)+(!allocationReady(o,l)?'<small class="shortage">先在发货分配确认拟实发</small>':'');
}



function processingRow(mode,c,o,l,r,productView=false){const editable=editableSheetOrder(o);const ch=lineChoice(o,l),d=sourceNet(l,'driver'),cn=sourceNet(l,'customer');const amountValue=lineAmount(o,l);const attrs=`data-oid="${esc(o.id)}" data-pid="${l.product_id}"`;
 return `<tr data-processing-order="${esc(o.id)}" data-processing-product="${l.product_id}"><td class="freeze-product"><strong>${esc(productView?c.name:l.product_name)}</strong>${productView?`<small>${esc(c.route)} · ${esc(o.business_date)}</small><small>${esc(o.id)}</small><div class="account-order-status"><span class="workflow-status ${workflowStatusTone(o.status)}">${esc(o.status)}</span></div>${correctionOrderActions(o)}`:''}</td><td class="mono"><span class="quantity-unit">${num(l.ordered_qty)}</span>${mode==='weight'&&typeof allocatedQuantity==='function'?`<small class="allocated-reference">分配 ${allocatedQuantity(o,l)===null?'待定':num(allocatedQuantity(o,l))}</small>`:''}</td><td>${shipmentQuantityCell(c,o,l,r)}</td>${mode==='weight'?`<td class="mono" data-standard-weight>${standardWeightText(l)}</td><td>${sheetInput(l.factory_net_kg||'',`${attrs} data-field="factory_net_kg" data-grid-row="${r}" data-grid-col="1" aria-label="${esc(c.name)} ${esc(l.product_name)}出厂净重"`,!editable||!canAction('weight.write')||l.not_shipped)}</td>${l.unit==='筐'?simpleWeightCell(o,l,'driver',editable&&canAction('weight.write'),r,2)+simpleWeightCell(o,l,'customer',editable&&canAction('weight.write'),r,3):`<td class="pack-note">${sheetInput(l.package_net_kg||'',`${attrs} data-field="package_net_kg" data-grid-row="${r}" data-grid-col="2" aria-label="${esc(c.name)} ${esc(l.product_name)}包装实称净重"`,!editable||!canAction('weight.write')||l.not_shipped)}</td><td class="pack-note">${sheetInput(l.package_customer_net_kg||'',`${attrs} data-field="package_customer_net_kg" data-grid-row="${r}" data-grid-col="3" aria-label="${esc(c.name)} ${esc(l.product_name)}包装客户复称净重"`,!editable||!canAction('weight.write')||l.not_shipped)}</td>`}${averageWeightCells(o,l,mode,r)}<td class="mono" data-line-diff>${weightDifference(o,l,mode==='account')}</td>`:`${l.unit==='筐'?simpleWeightCell(o,l,'driver',editable&&canAction('weight.write'),r,1):`<td>${sheetInput(l.package_net_kg||'',`${attrs} data-field="package_net_kg" data-grid-row="${r}" data-grid-col="1" aria-label="${esc(c.name+' '+l.product_name)}司机净重"`,!editable||!canAction('weight.write'))}</td>`}${l.unit==='筐'?simpleWeightCell(o,l,'customer',editable&&canAction('weight.write'),r,4):`<td class="pack-note">${billingUnit(l)==='公斤'?(l.package_customer_net_kg?'客户实称 '+num(l.package_customer_net_kg):l.package_net_kg?'司机实称 '+num(l.package_net_kg):l.factory_net_kg?'出厂 '+num(l.factory_net_kg):'标准单重 '+esc(l.standard_kg)):'按'+esc(billingUnit(l))+'计价'}</td>`}${crateInlineCell(o,l,r,editable)}${accountingReturnCell(o,l,r,editable)}${averageWeightCells(o,l,mode,r)}<td class="mono" data-line-diff>${weightDifference(o,l,mode==='account')}</td><td>${sheetInput(l.price,`${attrs} data-field="price" data-grid-row="${r}" data-grid-col="7" aria-label="${esc(c.name)} ${esc(l.product_name)}单价"`,!editable||!canAction('finance.price-edit'))}</td><td>${l.unit==='筐'&&billingUnit(l)==='公斤'?`<select class="grid-select" ${attrs} data-field="mode" aria-label="${esc(c.name)} ${esc(l.product_name)}结算依据" ${!editable||!canAction('weight.write')||l.not_shipped?'disabled':''}><option value="customer" ${ch.mode==='customer'?'selected':''}>${isPickupOrder(o)?'自提确认重量':'客户复称'}</option><option value="driver" ${ch.mode==='driver'?'selected':''}>司机卸货净重</option><option value="factory" ${ch.mode==='factory'?'selected':''}>出厂净重</option><option value="standard" ${ch.mode==='standard'?'selected':''}>标准重量</option><option value="agreed" ${ch.mode==='agreed'?'selected':''}>协商净重</option></select>`:(billingUnit(l)==='公斤'?(l.package_customer_net_kg?'客户复称净重':l.package_net_kg?'司机实称净重':l.factory_net_kg?'出厂净重':'标准包装折算公斤'):'实发'+esc(billingUnit(l))+'数')}</td><td>${sheetInput(l.not_shipped?'0':(l.unit!=='筐'||billingUnit(l)!=='公斤')?(billingUnit(l)==='公斤'?String(packageBillKg(l)):l.actual_qty):ch.mode==='agreed'?ch.net:(selectedSettlementNet(o,l,ch)===null?'':String(Number(selectedSettlementNet(o,l,ch).toFixed(3)))) ,`${attrs} data-field="agreed_net" data-grid-row="${r}" data-grid-col="8" aria-label="${esc(c.name)} ${esc(l.product_name)}最终结算量"`,!editable||l.unit!=='筐'||billingUnit(l)!=='公斤'||ch.mode!=='agreed')}</td><td class="amount mono" data-line-amount>${amountValue===null?'待填写':yuan(amountValue)}<small>${['ready','reviewed'].includes(o.state)?esc(o.status):'试算，未入应收'}</small></td>`}</tr>`;
}

function updateSheetTotals(){if(!data)return;if(typeof updateProductAccountTotals==='function')updateProductAccountTotals();
 for(const p of data.products){const el=$(`[data-product-total="${p.id}"]`);const total=matrixVisibleRows().reduce((n,{row})=>n+Number(row.values[p.id]||0),0);if(el)el.textContent=num(total)+' '+p.unit;const demand=$(`[data-demand-total="${p.id}"]`);if(demand)demand.textContent=num(total);const stockTip=$(`[data-order-inventory="${p.id}"]`);if(stockTip){const info=orderInventoryText(p);stockTip.querySelectorAll('td').forEach((cell,index)=>{if(index>0)cell.remove();});stockTip.insertAdjacentHTML('beforeend',orderInventoryCells(p));stockTip.classList.toggle('inventory-shortage-row',info.shortage);}}
 for(const g of dailyMatrixGroups())for(const p of data.products){const el=$(`[data-daily-client="${g.c.id}"][data-daily-product="${p.id}"]`);if(el)el.textContent=num(g.items.reduce((n,{row})=>n+Number(row.values[p.id]||0),0));}
 for(const p of data.products){const total=$(`[data-weight-load-actual="${p.id}"]`);if(total)total.textContent=num(processingGroups().flatMap(g=>g.orders.flatMap(o=>o.lines)).filter(l=>l.product_id===p.id).reduce((n,l)=>n+Number(l.actual_qty||0),0));}
 for(const {c,orders} of processingGroups()){const el=$(`[data-client-total="${c.id}"]`);if(!el)continue;if(page==='weighing'){const quantities=new Map();for(const o of orders)for(const l of o.lines)quantities.set(l.unit,(quantities.get(l.unit)||0)+Number(l.actual_qty||0));el.textContent=[...quantities].map(([unit,qty])=>num(qty)+' '+unit).join(' / ');}else{const vals=orders.flatMap(o=>o.lines.map(l=>lineAmount(o,l)));el.textContent=amount(vals.reduce((s,n)=>s+(n||0),0))+(vals.includes(null)?' ＋ 待填写项':'');}}
 if(['weighing','settlements'].includes(page))for(const {c,orders} of processingGroups()){const flow=$(`[data-client-flow-progress="${c.id}"]`);if(flow)flow.innerHTML=clientWorkflowProgress(orders);const progress=$(`[data-client-weight-progress="${c.id}"]`);if(progress)progress.innerHTML=clientWeightProgress(orders);const count=$(`[data-client-save-count="${c.id}"]`),n=orders.filter(o=>editableSheetOrder(o)&&orderDirty(o)).length;if(count)count.textContent=n?`（${n}单未保存）`:'';}
 const dirty=$('#sheet-dirty');if(dirty){const n=page==='orders'?matrixVisibleRows().filter(({row})=>matrixDirty(row)).length:processingGroups().flatMap(g=>g.orders).filter(orderDirty).length;dirty.textContent=n?`(${n})`:'';}
}
function actualQuantityChanged(o,l){const allocated=typeof allocatedQuantity==='function'?allocatedQuantity(o,l):null;return allocated!==null&&Number(l.actual_qty)!==Number(allocated);}
function updateWeightEntryControls(o,l,tr){const actual=$('[data-field="actual_qty"]',tr);if(actual)actual.dataset.actualChanged=String(actualQuantityChanged(o,l));if(!['weighing','settlements'].includes(page))return;const editable=editableSheetOrder(o)&&canAction('weight.write'),r=Number(actual?.dataset.gridRow)||0;
 for(const [type,index,col] of [['driver',page==='settlements'?3:5,2],['customer',page==='settlements'?4:6,3]]){const field=$(`[data-simple-weight="${type}"]`,tr);if(field){field.disabled=!editable||l.not_shipped;if(l.not_shipped)field.value='';}else if(!l.not_shipped&&l.unit==='筐'&&!(type==='driver'&&isPickupOrder(o)&&!l.driver.length)&&tr.cells[index]){tr.cells[index].outerHTML=simpleWeightCell(o,l,type,editable,r,col);}}
 for(const field of $$('[data-field="factory_net_kg"],[data-field="package_net_kg"],[data-field="package_customer_net_kg"]',tr)){field.disabled=!editable||l.not_shipped;if(l.not_shipped)field.value='';}
 if(typeof labelWeightCells==='function')labelWeightCells();}
function updateProcessingRow(o,l){const tr=$(`[data-processing-order="${o.id}"][data-processing-product="${l.product_id}"]`);if(!tr)return;updateWeightEntryControls(o,l,tr);const d=sourceNet(l,'driver'),c=sourceNet(l,'customer');
 for(const type of ['driver','customer']){const el=$(`[data-line-net="${type}"]`,tr);if(el)el.textContent='净重 '+(type==='customer'&&!isPickupOrder(o)&&!activeWeightRows(o,l,type).length?'未复称（可选）':netText(settlementSourceNet(o,l,type)));}
 for(const type of ['driver','customer']){const summary=$(`[data-source-summary="${type}"]`,tr);if(summary)summary.textContent=netText(settlementSourceNet(o,l,type));}
 for(const type of ['driver','customer']){const average=$(`[data-average-net="${type}"]`,tr),value=averageSourceNet(o,l,type,page==='settlements');if(average){const deviation=averageWeightDeviation(o,l,type,page==='settlements');average.innerHTML=(value===null?'—':num(value))+(deviation?'<small>'+esc(deviation.title)+'</small>':value!==null&&!(standardUnitWeight(l)>0)?'<small>未配置标准单重</small>':'');average.classList.toggle('weight-average-alert',!!deviation);average.classList.toggle('high',deviation?.direction==='high');average.classList.toggle('low',deviation?.direction==='low');if(deviation){average.dataset.averageDeviation=deviation.direction;average.title=deviation.title;}else{delete average.dataset.averageDeviation;average.removeAttribute('title');}}}
 const std=$('[data-standard-weight]',tr);if(std)std.innerHTML=standardWeightText(l);
 const diff=$('[data-line-diff]',tr);if(diff)diff.textContent=weightDifference(o,l,page==='settlements');
 const dn=$('[data-driver-net]',tr);if(dn)dn.textContent=netText(d);
 const choice=lineChoice(o,l),q=$('[data-field="agreed_net"]',tr);if(q){if(l.not_shipped)q.value='0';else if(l.unit!=='筐'||billingUnit(l)!=='公斤')q.value=billingUnit(l)==='公斤'?String(packageBillKg(l)):l.actual_qty;else if(['customer','driver','factory','standard'].includes(choice.mode)){const net=selectedSettlementNet(o,l,choice);q.value=net===null?'':String(Number(net.toFixed(3)));}q.disabled=!editableSheetOrder(o)||l.not_shipped||l.unit!=='筐'||billingUnit(l)!=='公斤'||choice.mode!=='agreed';}
 const a=$('[data-line-amount]',tr);if(a){const cents=lineAmount(o,l);a.innerHTML=(cents===null?'待填写':yuan(cents))+`<small>${['ready','reviewed'].includes(o.state)&&!orderDirty(o)?esc(o.status):'试算，未入应收'}</small>`;}
 updateSheetTotals();
}
function applySheetInput(el){
 if(el.dataset.accountReturnAsset){applyAccountingReturnInput(el);return;}if(el.hasAttribute?.('data-account-return-source'))return;
 if(el.dataset.allocationOrder){applyWarehouseInput(el);return;}
 if(el.dataset.ruleCid){applyPricingInput(el);return;}
 scheduleDraftSave();
 if(el.dataset.matrixKey){const r=matrixRows.get(el.dataset.matrixKey);r.values[el.dataset.productId]=el.value;el.classList.toggle('cell-changed',matrixDirty(r));updateSheetTotals();return;}
 if(el.dataset.clientReason){clientReasons.set(reasonKey({id:el.dataset.clientReason}),el.value);for(const o of processingGroups().find(g=>g.c.id===el.dataset.clientReason)?.orders||[])if(editableSheetOrder(o))decisionDirty.add(o.id);updateSheetTotals();return;}
 if(!el.dataset.oid)return;const o=workingOrder(originalOrder(el.dataset.oid));const l=o.lines.find(l=>l.product_id===el.dataset.pid),field=el.dataset.field;
 if(field==='mode'){decisionDirty.add(o.id);const ch=lineChoice(o,l);ch.mode=el.value;ch.manualMode=true;if(ch.mode==='agreed'&&!ch.net){const n=sourceNet(l,'customer')??sourceNet(l,'driver');ch.net=n===null?'':String(Number(n.toFixed(3)));}}
 else if(field==='crate_qty'){applyCrateInput(el,o,l);decisionDirty.add(o.id);}
 else if(field==='settlement_tare'){decisionDirty.add(o.id);const ch=lineChoice(o,l);ch.tares||={};if(el.value==='')delete ch.tares[el.dataset.tareSource];else ch.tares[el.dataset.tareSource]=el.value;}
 else if(field==='agreed_net'){decisionDirty.add(o.id);lineChoice(o,l).net=el.value;}
 else if(el.dataset.simpleWeight){const type=el.dataset.simpleWeight;if(type==='driver'){l.driver_weight_basis='gross';if(!l.crate_lines?.length)l.crate_lines=accountingCrateLines(o,l);}l[type]=el.value.trim()===''?[]:[{gross:el.value,count:String(physicalCrateCount(l)),tare:type==='driver'?'0':ruleFor(o.customer_id,l.product_id).tare,note:type==='driver'?'司机总毛重':''}];}
 else if(el.dataset.source){const type=el.dataset.source,j=Number(el.dataset.windex);if(!l[type].length)l[type]=structuredClone(virtualWeights(o,l,type));l[type][j][field]=el.value;}
 else if(field==='actual_qty'){if(allocationReady(o,l)&&!quantityProblem(el.value,'实发数量',l.unit)&&Number(el.value)>Number(allocatedQuantity(o,l))){el.value=l.actual_qty;notify('实发不能超过已确认分配 '+num(allocatedQuantity(o,l))+'，请先回发货分配调整');return;}const prev=l.actual_qty;l.actual_qty=el.value;if(!quantityProblem(el.value,'实发数量',l.unit)){l.not_shipped=Number(el.value)===0;if(l.not_shipped){l.driver=[];l.customer=[];l.factory_net_kg='';l.package_net_kg='';l.package_customer_net_kg='';}}for(const type of ['driver','customer']){
   if(l[type].length===1&&(!l[type][0].count||Number(l[type][0].count)===(l.unit==='筐'?Math.ceil(Number(prev)):Number(prev))))l[type][0].count=String(physicalCrateCount(l));
   const tr=el.closest('tr'),inputs=$$(`[data-source="${type}"][data-field="count"]`,tr);if(inputs.length===1)inputs[0].value=l[type].length?l[type][0].count:el.value;
 }}else l[field]=el.value;
 if(field==='mode'||field==='crate_qty'){const cell=$('[data-tare-cell]',el.closest('tr'));if(cell)cell.innerHTML=tareCellContent(o,l,true,Number(el.dataset.gridRow)||0);}
 el.classList.add('cell-changed');updateProcessingRow(o,l);
}
function matrixOperations(){const operations=[],keys=[],issues=[],cancelled=[],rows=matrixVisibleRows();for(const {c,o,row} of rows)if(matrixDirty(row))for(const p of data.products){const v=String(row.values[p.id]??'').trim();const m=v===''?'':quantityProblem(v,'订货数量',p.unit);if(m)issues.push({order_id:o?.id,customer_id:c.id,customer_name:c.name,product_id:p.id,product_name:p.name,field:'ordered_qty',message:m});}if(issues.length)throw Object.assign(Error('订货总表有填写问题'),{issues});for(const {c,o,row} of rows){
 if(!matrixDirty(row))continue;if(o&&!editableSheetOrder(o))throw Error(c.name+' 的原单已进入结算，不能从订货总表覆盖');
 const base=o?workingOrder(o):{customer_id:c.id,business_date:row.date,batch:'日常订货',note:'',lines:[]};
 if(o&&base.version!==row.version)throw Error(c.name+' 的订货与称重版本不一致，请核对并重新进入页面后重试');
 const lines=[];for(const p of data.products){const v=String(row.values[p.id]??'').trim();if(v!==''){const problem=quantityProblem(v,'订货数量',p.unit);if(problem)throw Error(`${c.name} ${p.name}：${problem}`);}const old=base.lines.find(l=>l.product_id===p.id);
  if(Number(v||0)>0)lines.push({...old||defaultLine(p.id,c.id),ordered_qty:v});
  else if(old&&(Number(old.actual_qty)>0||old.driver.length||old.customer.length))throw Error(`${c.name} ${p.name}已有实发或称重，不能从订货表移除`);
 }
 if(!lines.length){if(!o)throw Error(c.name+' 未订任何产品；请保留至少一项，或将本行恢复为空白');operations.push({action:'cancel-order',order_id:o.id,body:{version:row.version,business_date:o.business_date}});cancelled.push({id:o.id,name:c.name});keys.push(row.key);continue;}
 operations.push({action:'order',order_id:o?.id,body:{...businessPayload({...base,version:row.version,lines}),...(!o?{daily_order:true}:{})}});keys.push(row.key);
 }return {operations,keys,cancelled};}
function processingOperations(){const orders=processingGroups().flatMap(g=>g.orders).filter(o=>editableSheetOrder(o)&&orderDirty(o));return {operations:orders.map(o=>({action:'order',order_id:o.id,body:businessPayload(o)})),keys:orders.map(o=>o.id)};}
function autoFillActual(){let n=0;for(const {orders} of processingGroups())for(const o of orders)if(editableSheetOrder(o))for(const l of o.lines)if(!l.not_shipped&&!Number(l.actual_qty)&&!l.driver.length&&!l.customer.length){const qty=typeof allocatedQuantity==='function'?allocatedQuantity(o,l):null;if(qty===null)continue;l.actual_qty=qty;if(Number(qty)===0)l.not_shipped=true;n++;}return n;}
function allocationReady(o,l){return typeof allocatedQuantity==='function'&&allocatedQuantity(o,l)!==null;}
function blankActualCount(){return processingGroups().flatMap(g=>g.orders).filter(editableSheetOrder).flatMap(o=>o.lines).filter(l=>!l.not_shipped&&!Number(l.actual_qty)&&!l.driver.length&&!l.customer.length).length;}
function showSheetError(e){sheetError=e.message;if(e.issues?.length){presentValidation(e.issues);if(operationError(e).check)showOperationError(e,$('#sheet-error'));return;}const el=$('#sheet-error');if(el){showOperationError(e,el);}else notify(sheetError);}
async function sendSheetOperations(operations,keys=[],message='本页改动已保存'){
 if(busy)return;if(!operations.length){notify(decisionDirty.size?'结算依据和协商说明请点击「确认本客户算票」保存':'没有需要保存的改动');return;}
 const issues=operationIssues(operations);if(issues.length){presentValidation(issues);persistDrafts();return;}
 visibleIssues=[];clearValidationDecorations();busy=true;sheetError='';$('#content').setAttribute('inert','');
 try{const result=await api('/api/batch',{operations});for(const o of result.orders){const i=data.orders.findIndex(x=>x.id===o.id);if(i>=0)data.orders[i]=o;else data.orders.unshift(o);sheetOrders.delete(o.id);sheetBaselines.delete(o.id);if(operations.find(op=>op.order_id===o.id)?.action!=='order'){for(const key of [...lineChoices.keys()])if(key.startsWith(o.id+'|'))lineChoices.delete(key);decisionDirty.delete(o.id);}matrixRows.delete(o.id);}
 for(const x of result.cancelled||[]){data.orders=data.orders.filter(o=>o.id!==x.id);sheetOrders.delete(x.id);sheetBaselines.delete(x.id);matrixRows.delete(x.id);decisionDirty.delete(x.id);for(const key of [...lineChoices.keys()])if(key.startsWith(x.id+'|'))lineChoices.delete(key);}
 for(const key of keys)matrixRows.delete(key);persistDrafts();render();notify(`${message}（${result.count}张单据）`);
 // Audit is refreshed separately so a follow-up read failure cannot turn a saved batch into a retry.
 try{const fresh=await api('/api/bootstrap');data=fresh;render();}catch{}
 }catch(e){showSheetError(e);}finally{busy=false;$('#content').removeAttribute('inert');}
}
async function sheetAction(act,el){
 if(busy)return;
 if(act==='confirm-weight-batch'){
  if(!canAction('weight.confirm'))throw Error('当前账号无称重确认权限');
  const candidates=processingGroups().flatMap(g=>g.orders).filter(o=>['draft','dispatched'].includes(o.state)&&(!o.weight_confirmation||orderDirty(o)));
  if(!candidates.length){notify('当前筛选下没有待确认称重的单据');return;}
  if(candidates.length>200)throw Error('当前有超过200张待确认单据，请按日期或趟次缩小范围后提交');
  openDialog('批量确认称重并交会计',`<p class="callout">确认当前筛选范围内 ${candidates.length} 张单据。系统逐单校验实发、称重和版本；任一单不通过，整批不提交。</p><p>${candidates.map(o=>esc(o.customer_name)+' · '+esc(o.id)).join('<br>')}</p><label class="check-line"><input type="checkbox" id="weight-batch-evidence">已逐单核对实发数量与称重</label>`,'称重交接','<button class="button" data-act="close">取消</button><button class="button primary" data-sheet-action="submit-weight-batch">确认交接</button>');
  $('#overlay').weightBatch=candidates.map(o=>({action:'confirm-weight',order_id:o.id,body:{version:o.version,dispatch_required:true,evidence_checked:true},...(orderDirty(o)?{update:businessPayload(o)}:{})}));return;
 }
 if(act==='submit-weight-batch'){
  if(!canAction('weight.confirm'))throw Error('当前账号无称重确认权限');
  if(!$('#weight-batch-evidence')?.checked)throw Error('请先勾选已逐单核对实发与称重');
  const operations=$('#overlay').weightBatch;closeDialog();await sendSheetOperations(operations,[],'批量称重已确认，已交会计待算票');return;
 }
 if(act==='toggle-originals'){const cid=el.dataset.cid;matrixExpanded.has(cid)?matrixExpanded.delete(cid):matrixExpanded.add(cid);render();return;}
 if(act==='all-dates'||act==='today'){if(typeof clearDateRange==='function')clearDateRange();selectedDate=act==='today'?today():'';processingBatch='';render();return;}
 if(act==='wide'){document.body.classList.toggle('sheet-wide');updateWideModeControls();return;}
 if(act==='focus-order'||act==='open-pending-order'){const o=originalOrder(el.dataset.id);if(!o)return;if(typeof clearDateRange==='function')clearDateRange();selectedDate=o.business_date;processingBatch=o.batch;sheetSearch=o.id;sheetRoute='';sheetTrip='';sheetStatus='all';sheetArchive=false;goto(canAction('finance.settle')?'settlements':(act==='focus-order'&&role==='库管'||['draft','dispatched'].includes(o.state)&&!o.weight_confirmation)?'weighing':'settlements');return;}
 if(act==='pending-account'){if(!canOpenWorkflow('settlements','finance.settle'))throw Error('当前账号无会计算票权限');sheetStatus='pending';sheetSearch='';sheetRoute='';goto('settlements');return;}
 if(act==='archive'){goto('archive');return;}
 if(act==='save'){
  if(!canAction('orders.write')){notify('当前账号无订货或称重录入权限');return;}
  visibleIssues=[];clearValidationDecorations();sheetError='';const errorBox=$('#sheet-error');if(errorBox)errorBox.hidden=true;
  const batch=page==='orders'?matrixOperations():processingOperations();
  if(batch.cancelled?.length){const names=batch.cancelled.map(x=>x.name).join('、');if(!await confirmWorkflowAction(`以下客户的订货已全部清空：${names}。保存后将删除这些订货单（已录实发、称重、结算或收款的原单不能删除），是否继续？`))return;}
  await sendSheetOperations(batch.operations,batch.keys);return;
 }
 if(act==='reload'){
  const dirty=decisionDirty.size||[...sheetOrders.values()].some(orderDirty)||[...matrixRows.values()].some(matrixDirty);
  if(dirty){notify('有未保存输入，请先保存；同步不会覆盖正在录入的内容');return;}
  data=await api('/api/bootstrap');sheetOrders.clear();sheetBaselines.clear();matrixRows.clear();lineChoices.clear();sheetError='';render();notify('已同步最新单据');return;
 }
 if(act==='copy-actual'){
  if(!canAction('weight.write'))throw Error('当前账号不能更改实发或原始称重');const n=autoFillActual();
  persistDrafts();render();notify(`已按保存的分配填写 ${n} 项，请核对装车实际后保存；未分配的产品保持待填`);return;
 }
 if(act==='add-weight'||act==='remove-weight'){
  const o=workingOrder(originalOrder(el.dataset.oid)),l=o.lines.find(l=>l.product_id===el.dataset.pid),type=el.dataset.source;if(!editableSheetOrder(o))return;
  if(!l[type].length)l[type]=structuredClone(virtualWeights(o,l,type));
  if(act==='add-weight')l[type].push({gross:'',count:'',tare:ruleFor(o.customer_id,l.product_id).tare,note:''});else l[type].splice(Number(el.dataset.index),1);scheduleDraftSave();render();return;
 }
 if(act==='driver-photos'){const c=data.customers.find(c=>c.id===el.dataset.cid),group=processingGroups().find(g=>g.c.id===c?.id);if(!group)return;const rows=group.orders.filter(o=>o.driver_photos&&Object.keys(o.driver_photos).length);if(!rows.length){notify('本客户当前没有司机照片');return;}const html=rows.map(o=>`<section class="driver-photo-order"><h3>${esc(o.customer_name)} · ${esc(o.id)}</h3><div class="driver-photo-grid">${Object.entries(o.driver_photos).map(([k,at])=>{const name=k==='crate'?'回框照片':k==='weight'?'称重照片':'称重照片 · '+(data.products.find(p=>p.id===k.slice(7))?.name||k.slice(7));return `<figure><figcaption>${esc(name)} · ${esc(at)}</figcaption><a href="/api/driver/photo/${encodeURIComponent(o.id)}/${encodeURIComponent(k)}" target="_blank" rel="noopener"><img loading="lazy" src="/api/driver/photo/${encodeURIComponent(o.id)}/${encodeURIComponent(k)}" alt="${esc(name)}"></a><a class="text-button" href="/api/driver/photo/${encodeURIComponent(o.id)}/${encodeURIComponent(k)}" download>下载原图</a></figure>`;}).join('')}</div></section>`).join('');openDialog('司机到店照片 · '+c.name,html,'司机照片','<button class="button" data-act="close">关闭</button>');return;}
 const c=data.customers.find(c=>c.id===el.dataset.cid),group=processingGroups().find(g=>g.c.id===c?.id);if(!group)return;
 if(act==='weight-client'||act==='account-client'){if(!canOpenWorkflow(act==='weight-client'?'weighing':'settlements',act==='weight-client'?'weight.confirm':'finance.settle'))throw Error('当前账号无此流程操作权限');sheetSearch=c.id;sheetRoute='';sheetStatus='all';goto(act==='weight-client'?'weighing':'settlements');return;}
 if(act==='save-weight-client'){
  if(page!=='weighing'||!canAction('orders.write')||!canAction('weight.write'))throw Error('当前账号无称重保存权限');
  const orders=group.orders.filter(o=>editableSheetOrder(o)&&orderDirty(o));
  await sendSheetOperations(orders.map(o=>({action:'order',order_id:o.id,body:businessPayload(o)})),[],`${c.name}的称重已保存`);return;
 }
 if(act==='confirm-weight-client'){
  if(!canAction('weight.confirm'))throw Error('当前账号无称重确认权限');
  if(!$(`[data-weight-evidence="${c.id}"]`)?.checked)throw Error('请先核对本客户实发与称重，勾选交接确认');
  const candidates=group.orders.filter(o=>['draft','dispatched'].includes(o.state)&&(!o.weight_confirmation||orderDirty(o)));
  await sendSheetOperations(candidates.map(o=>({action:'confirm-weight',order_id:o.id,body:{version:o.version,dispatch_required:true,evidence_checked:true},...(orderDirty(o)?{update:businessPayload(o)}:{})})),[],`${c.name}称重已确认，已交会计待算票`);return;
 }
 const reason=clientReasons.get(reasonKey(c))||'';
 if(act==='settle-client'){
  if(!needPermission('finance.settle'))return;const candidates=group.orders.filter(o=>editableSheetOrder(o));if(!candidates.length)throw Error('当前没有可录入算票的单据');const evidence=$(`[data-account-evidence="${c.id}"]`);if(!evidence?.checked){evidence?.scrollIntoView({block:'center'});evidence?.focus();throw Error('请核对司机照片、重量和框数，勾选确认后算票');}
  const operations=candidates.map(o=>{const line_modes={},agreed={},tare_overrides={};for(const l of o.lines)if(l.unit==='筐'){const ch=lineChoice(o,l);line_modes[l.product_id]=ch.mode;if(ch.mode==='agreed')agreed[l.product_id]=ch.net;if(ch.tares&&Object.keys(ch.tares).length)tare_overrides[l.product_id]=ch.tares;}
   return {action:'settle',order_id:o.id,body:{version:o.version,mode:'auto',line_modes,agreed,tare_overrides,reason,confirm_accounting_entry:true,evidence_checked:true},...(orderDirty(o)?{update:businessPayload(o)}:{})};});
  await sendSheetOperations(operations,[],`${c.name}的全部待算票产品已提交复核`);return;
 }
 if(act==='negotiate-client'){
  if(!needPermission('finance.settle'))return;if(!reason.trim())throw Error('请先填写该客户的协商原因');
  if(group.orders.some(orderDirty))throw Error('请先保存本客户的重量或价格改动，再标记待协商');
  await sendSheetOperations(group.orders.filter(editableSheetOrder).map(o=>({action:'negotiate',order_id:o.id,body:{version:o.version,reason}})),[],`${c.name}已标记待协商`);return;
 }
 if(act==='review-client'){
  if(!needPermission('finance.review'))return;openReview(group.orders.filter(o=>o.state==='ready'),true);
 }
}
function parseSheetPaste(text){return text.replace(/\r\n?/g,'\n').replace(/\n$/,'').split('\n').map(row=>row.split('\t'));}
// These listeners use the same working copies for typing, keyboard movement and Excel paste.
document.addEventListener('click',e=>{

 const el=e.target.closest('[data-sheet-action]');if(el){e.preventDefault();sheetAction(el.dataset.sheetAction,el).catch(showSheetError);}
});
document.addEventListener('input',e=>{
 if(e.target.matches('.grid-input,[data-client-reason]'))applySheetInput(e.target);
 if(e.target.id==='sheet-search'){updateLiveSearch(e,value=>sheetSearch=value);}
});
document.addEventListener('change',e=>{
 const id=e.target.id;if(e.target.dataset.field==='full_shipped'){const el=e.target,o=workingOrder(originalOrder(el.dataset.oid)),l=o.lines.find(l=>l.product_id===el.dataset.pid);if(!editableSheetOrder(o)||!allocationReady(o,l)||Number(allocatedQuantity(o,l))<Number(l.ordered_qty)||l.not_shipped||l.driver.length||l.customer.length)return;l.actual_qty=el.checked?l.ordered_qty:'0';scheduleDraftSave();render();return;}if(id==='sheet-date'){if(typeof clearDateRange==='function')clearDateRange();selectedDate=e.target.value||(page==='orders'?today():'');processingBatch='';render();}
 if(id==='sheet-trip'){sheetTrip=e.target.value;render();}
 if(id==='sheet-route'){sheetRoute=e.target.value;render();}
 if(id==='sheet-status'){sheetStatus=e.target.value;render();}
 if(e.target.matches('.grid-select'))applySheetInput(e.target);
 if(e.target.dataset.field==='not_shipped'){const el=e.target,o=workingOrder(originalOrder(el.dataset.oid)),l=o.lines.find(l=>l.product_id===el.dataset.pid);if(el.checked&&(Number(l.actual_qty)>0||l.driver.length||l.customer.length)){el.checked=false;presentValidation([cellIssue(o,l,'not_shipped','此行已有实发或称重，请核对后再标记未发')]);return;}l.not_shipped=el.checked;clearEditedIssue(el);scheduleDraftSave();render();}
});
document.addEventListener('keydown',e=>{if(e.defaultPrevented||isTextComposing(e))return;
 if(!e.target.matches('.grid-input,.grid-select'))return;
 if(e.key==='Tab'){const controls=$$('[data-sheet-grid] .grid-input:not(:disabled),[data-sheet-grid] .grid-select:not(:disabled)').filter(el=>el.getClientRects().length);const next=controls[controls.indexOf(e.target)+(e.shiftKey?-1:1)];if(next){e.preventDefault();next.focus();if(next.matches('input'))next.select();}return;}
 if(e.key==='Enter'&&e.target.matches('.grid-input')){e.preventDefault();const el=e.target,grid=el.closest('[data-sheet-grid]'),col=el.dataset.gridCol,row=Number(el.dataset.gridRow),step=e.shiftKey?-1:1;let candidates=$$(`.grid-input[data-grid-col="${col}"]:not(:disabled)`,grid).filter(x=>step*(Number(x.dataset.gridRow)-row)>0).sort((a,b)=>step*(Number(a.dataset.gridRow)-Number(b.dataset.gridRow)));
  if(candidates[0]){candidates[0].focus();candidates[0].select();}else{const groups=$$('[data-sheet-grid]').filter(el=>el.getClientRects().length),next=groups[groups.indexOf(grid)+step];const target=next&&$$(`.grid-input[data-grid-col="${col}"]:not(:disabled)`,next)[step===1?0:$$(`.grid-input[data-grid-col="${col}"]:not(:disabled)`,next).length-1];if(target){target.focus();target.select();}}
 }
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if(page==='allocation'){warehouseAction('save').catch(err);}else sheetAction('save',e.target).catch(showSheetError);}
});
document.addEventListener('paste',e=>{
 const el=e.target;if(!el.matches('.grid-input')||el.disabled)return;const text=e.clipboardData?.getData('text/plain');if(!text||!/[\t\r\n]/.test(text))return;e.preventDefault();const rows=parseSheetPaste(text),grid=el.closest('[data-sheet-grid]'),all=$$('.grid-input',grid),startRow=Number(el.dataset.gridRow),startCol=Number(el.dataset.gridCol);
 // Use the actual displayed row positions, including expanded weighing batches.
 const rowNumbers=[...new Set(all.map(x=>Number(x.dataset.gridRow)))].sort((a,b)=>a-b),offset=rowNumbers.indexOf(startRow);let n=0,skipped=0;
 for(let r=0;r<rows.length;r++)for(let c=0;c<rows[r].length;c++){
  const target=all.find(x=>Number(x.dataset.gridRow)===rowNumbers[offset+r]&&Number(x.dataset.gridCol)===startCol+c);
  if(!target||target.disabled){skipped++;continue;}target.value=rows[r][c].trim();applySheetInput(target);target.classList.add('cell-changed');n++;
 }notify(`已粘贴 ${n} 个数值${skipped?`，${skipped} 个超出表格或只读位置已跳过`:''}，请核对后保存`);
});
window.addEventListener('beforeunload',e=>{if(productOrderDirty()||[...pricingDrafts.values()].some(pricingDirty)||decisionDirty.size||[...sheetOrders.values()].some(orderDirty)||[...matrixRows.values()].some(matrixDirty)){e.preventDefault();e.returnValue='';}});

function resetBusinessDrafts(){if(typeof warehouseDrafts!=='undefined'){warehouseDrafts.clear();localStorage.removeItem('erp-warehouse-drafts-v1');}sheetOrders.clear();sheetBaselines.clear();matrixRows.clear();lineChoices.clear();clientReasons.clear();decisionDirty.clear();visibleIssues=[];sheetError='';}

document.addEventListener('click',e=>{const el=e.target.closest('[data-settlement-stage]');if(el){sheetStatus=el.dataset.settlementStage;render();}});
