"""Compact A4 matrices: demand quantities and delivered product quantities are distinct."""
from html import escape
from datetime import date
from decimal import Decimal
import hashlib,json,math,unicodedata

ROWS_PER_PAGE=26

def order_print_html(data,query,generated_at):
    def get(key,default=''):return query.get(key,[default])[0]
    def e(v):return escape(str(v or ''),quote=True)
    def n(v):return format(Decimal(str(v or 0)).normalize(),'f')
    document=get('document','delivery');demand=document=='order';title='订货单' if demand else '配送单'
    if document not in ('order','delivery'):raise ValueError('单据类型无效')
    day=get('date');mode=get('mode','grouped');trip_id=get('trip')
    try:
        if date.fromisoformat(day).isoformat()!=day:raise ValueError()
    except (TypeError,ValueError):raise ValueError('请选择有效的打印业务日期')
    if mode not in ('total','grouped','trip'):raise ValueError('打印模式无效')
    if get('scope') not in ('','sheet'):raise ValueError('打印范围无效')
    orders=[o for o in data['orders'] if o['business_date']==day and (get('scope')!='sheet' or o['id'] in set(query.get('order_id',[])))]
    customers={c['id']:c for c in data['customers']};markets={m['id']:m for m in data.get('delivery_markets',[])}
    plan=next((p for p in data.get('dispatch_plans',[]) if p['business_date']==day),{})
    def pickup(o):return (o.get('delivery_method') or customers.get(o['customer_id'],{}).get('delivery_method'))=='pickup'
    def market(o):return plan.get('order_markets',{}).get(o['id']) or customers.get(o['customer_id'],{}).get('market_id') or next((m['id'] for m in markets.values() if m['name']==customers.get(o['customer_id'],{}).get('route',o.get('route'))),'')
    def assignment(o):return next((a for a in plan.get('assignments',[]) if a['market_id']==market(o)),{})
    def trip(o):return 'pickup' if pickup(o) else assignment(o).get('trip_id','')
    market_rank={mid:i for i,mid in enumerate(markets)};customer_rank={cid:i for i,cid in enumerate(customers)}
    groups=[]
    if mode=='total':groups=[('全部客户（含自取）',orders)]
    else:
        for t in plan.get('trips',[]):
            if mode=='trip' and trip_id!=t['id']:continue
            groups.append((' · '.join([t['name'],t.get('vehicle_name') or '车辆待安排',t.get('driver') or '司机待安排']),[o for o in orders if trip(o)==t['id']]))
        if mode!='trip' or trip_id=='pickup':groups.append(('客户自取',[o for o in orders if pickup(o)]))
        if mode!='trip' or trip_id=='unassigned':groups.append(('待排车 / 待匹配市场',[o for o in orders if not pickup(o) and not trip(o)]))
        if mode=='trip' and not groups:raise ValueError('该趟次不存在，请先保存配送安排')
    pages=[];source_hash=hashlib.sha256(json.dumps(sorted((o['id'],o['version']) for o in orders)).encode()).hexdigest()[:10].upper()
    for label,source in groups:
        source.sort(key=lambda o:(assignment(o).get('sequence',1000),market_rank.get(market(o),999),customer_rank.get(o['customer_id'],999),o['id']))
        clients={}
        for o in source:
            cid=o['customer_id'];c=customers.get(cid,{})
            item=clients.setdefault(cid,{'cid':cid,'name':c.get('name',o['customer_name']),'route':c.get('route',o.get('route','')),'qty':{},'source':[]})
            item['source'].append(o['id'])
            for l in o['lines']:
                pid=l['product_id'];item['qty'][pid]=item['qty'].get(pid,Decimal(0))+Decimal(l['ordered_qty' if demand else 'actual_qty'])
        rows=[r for r in clients.values() if any(r['qty'].values())]
        products=[p for p in data['products'] if not demand or any(r['qty'].get(p['id'],0)>0 for r in rows)]
        # 所有产品排在同一页：产品多时压缩「备注 / 称重」列宽，而不是拆页。
        product_groups=[products] if products else [[]]
        if not rows:continue
        def text_units(v):return sum(2 if unicodedata.east_asian_width(ch) in ('W','F') else 1 for ch in str(v))
        batches=[];batch=[];units=0;start=0
        for row in rows:
            row_units=1
            if batch and units+row_units>ROWS_PER_PAGE:
                batches.append((start,batch));start+=len(batch);batch=[];units=0
            batch.append(row);units+=row_units
        if batch:batches.append((start,batch))
        note_mm=max(10,round(25-(len(products)-10)*1.5,1)) if len(products)>10 else 25
        note_head='' if demand else f'<th class="handwritten" style="width:{note_mm}mm">备注 / 称重</th>'
        product_note=''
        for product_index,columns in enumerate(product_groups):
            for start,batch in batches:
                heads='<th class="seq">序</th><th class="customer">客户</th><th class="market">市场 / 线路</th>'+''.join(f'<th>{e(p["name"])}<small>{e(p["unit"])}</small></th>' for p in columns)+note_head
                body=''
                for i,r in enumerate(batch,start+1):
                    body+=f'<tr data-print-label="{e(r["name"]+" · "+r["route"])}" data-order-ids="{e(",".join(r["source"]))}"><td>{i}</td><td class="customer"><b data-print-fit>{e(r["name"])}</b></td><td>{e(r["route"])}</td>'
                    body+=''.join(f'<td data-quantity="{n(r["qty"].get(p["id"],0))}">{n(r["qty"].get(p["id"],0)) if r["qty"].get(p["id"],0) else "—"}</td>' for p in columns)+('' if demand else '<td class="handwritten"></td>')+'</tr>'
                totals='<tr><th colspan="3">本页合计</th>'+''.join(f'<th>{n(sum((r["qty"].get(p["id"],Decimal(0)) for r in batch),Decimal(0)))}</th>' for p in columns)+('' if demand else '<th class="handwritten"></th>')+'</tr>'
                scope='订货表当前筛选' if get('scope')=='sheet' else '当天已保存'+('订货' if demand else '实发')
                note='数量为客户订货需求。' if demand else '数量按已保存实发汇总；— 表示未发，末列供司机填写备注 / 称重。'
                page=f'<section class="print-page"><header>{__import__("company").header_html(data.get("company"))}<h1>{title}</h1><div class="document-meta"><b>业务日期：{e(day)}</b><span>{e(label)}{e(product_note)}</span><span>本页 <b data-print-row-count>{len(batch)}</b> 客户 / 原组 {len(rows)} 客户</span></div></header><table class="quantity-matrix" data-print-label-column="1" data-print-title="{e(label)} · {title}"><thead><tr>{heads}</tr></thead><tbody>{body}</tbody><tfoot>{totals}</tfoot></table><footer><span>{note} 单位见各产品表头。</span><span>{"录单 / 备货" if demand else "发货 / 司机"}：____________</span><span>第 <b data-print-page-number>PAGE_NUMBER</b> / <b data-print-page-count>PAGE_COUNT</b> 页</span><small>范围：{scope} · 版本 {source_hash} · 打印 {e(generated_at.replace("T"," ")[:19])}</small></footer></section>'
                pages.append(page)
    count=len(pages)
    html=''.join(p.replace('PAGE_NUMBER',str(i)).replace('PAGE_COUNT',str(count)) for i,p in enumerate(pages,1)) or '<section class="print-page"><h1>'+title+'</h1><p>当天没有符合条件的已保存'+('订货单' if demand else '实发记录')+'。</p></section>'
    return '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><title>'+title+' · '+e(day)+'</title><link rel="stylesheet" href="/print.css"><script defer src="/print.js"></script></head><body><div class="print-toolbar"><button id="print-button"'+(' disabled' if not count else '')+'>打印 / 保存为 PDF</button><span>A4 横向 · 客户 × 产品数量总表 · 每页最多 '+str(ROWS_PER_PAGE)+' 客户 · 产品同页排布（多时自动压缩备注列）· 本次 '+str(count)+' 页</span></div>'+html+'</body></html>'

def purchase_print_html(c,query,generated_at):
    """采购订单 / 验收入库单：A4 纵向单页单据，只读，不改变任何账目。"""
    import purchasing,company
    def get(key,default=''):return query.get(key,[default])[0]
    def e(v):return escape(str(v if v is not None else ''),quote=True)
    def n(v):return format(Decimal(str(v or 0)).normalize(),'f')
    def money(cents):return format(Decimal(str(int(cents or 0)))/100,'.2f')
    def yuan(v):return format(Decimal(str(v if v is not None else 0)),'.2f')
    document=get('document','order');rid=get('id').strip()
    if document not in ('order','receipt'):raise ValueError('单据类型无效')
    if not rid:raise ValueError('请指定要打印的采购单据')
    data=purchasing.projection(c)
    suppliers={s['id']:s for s in data['suppliers']}
    def supplier_name(doc):return doc.get('supplier_name') or suppliers.get(doc.get('supplier_id'),{}).get('name','')
    def supplier_address(doc):return suppliers.get(doc.get('supplier_id'),{}).get('address','—')
    def payment_days(doc):
        v=doc.get('payment_days')
        if v is None:v=suppliers.get(doc.get('supplier_id'),{}).get('payment_days')
        return '—' if v is None else str(v)+' 天'
    if document=='order':
        doc=next((o for o in data['orders'] if o['id']==rid),None)
        if not doc:raise ValueError('采购单不存在或已删除')
        title='采购订单';no=doc['id'];day=doc['business_date'];handler=doc.get('handler')
        meta=[('供应商',supplier_name(doc)),('下单日期',day),('预计到货',doc.get('expected_date')),('采购经办',doc.get('handler')),('账期',payment_days(doc)),('收货地址',supplier_address(doc))]
        heads=['序号','物料','单位','订购数量','已入库','未到货','货款单价','金额']
        rows=''.join(f'<tr><td>{i}</td><td class="long-note">{e(l["material_name"])}<small>{e(l.get("warehouse_name"))}</small></td><td>{e(l["unit"])}</td><td>{n(l["qty"])}</td><td>{n(l.get("received_qty"))}</td><td>{n(l.get("remaining_qty"))}</td><td>{yuan(l.get("price"))}</td><td>{money(l["amount_cents"])}</td></tr>' for i,l in enumerate(doc['lines'],1))
        foot=f'<tr><th colspan="7">订单合计</th><th>{money(doc["total_cents"])}</th></tr>'
        note=doc.get('note') or '';reference=doc.get('reference') or ''
        extra=f'<p class="doc-note">合同 / 外部单号：{e(reference or "—")}</p><p class="doc-note">备注：{e(note or "—")}</p>'
    else:
        doc=next((r for r in data['receipts'] if r['id']==rid),None)
        if not doc:raise ValueError('验收入库单不存在或已删除')
        title='验收入库单';no=doc['id'];day=doc['business_date'];handler=doc.get('handler')
        meta=[('供应商',supplier_name(doc)),('验收日期',day),('关联采购单',doc.get('order_id')),('验收人',doc.get('handler')),('付款到期日',doc.get('due_date') or '—'),('收货库房',(doc['lines'][0].get('warehouse_name') if doc.get('lines') else ''))]
        heads=['序号','物料','单位','验收数量','入库库房','货款单价','金额']
        rows=''.join(f'<tr><td>{i}</td><td class="long-note">{e(l["material_name"])}</td><td>{e(l["unit"])}</td><td>{n(l["qty"])}</td><td>{e(l.get("warehouse_name"))}</td><td>{yuan(Decimal(str(l["amount_cents"]))/100/Decimal(str(l["qty"])) if Decimal(str(l["qty"]))>0 else 0)}</td><td>{money(l["amount_cents"])}</td></tr>' for i,l in enumerate(doc['lines'],1))
        foot=f'<tr><th colspan="6">本单合计</th><th>{money(doc["amount_cents"])}</th></tr>'
        note=doc.get('note') or '';reference=doc.get('reference') or ''
        extra=f'<p class="doc-note">验收凭据：{e(reference or "—")}</p><p class="doc-note">验收说明：{e(note or "—")}</p>'
    meta_html=''.join(f'<div><span>{e(k)}</span><b>{e(v)}</b></div>' for k,v in meta)
    html=(f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{e(title)} · {e(no)}</title>'
          f'<link rel="stylesheet" href="/print.css"><script defer src="/print.js"></script></head><body>'
          f'<div class="print-toolbar"><button id="print-button">打印 / 保存为 PDF</button><span>A4 纵向 · {e(title)} · 单页</span></div>'
          f'<section class="print-page doc-table">{company.header_html(company.current(c))}<h1>{e(title)}</h1>'
          f'<div class="document-meta"><b>单据号：{e(no)}</b><span>{e(day)}</span></div>'
          f'<div class="doc-meta-grid">{meta_html}</div>'
          f'<table><thead><tr>{"".join(f"<th>{e(h)}</th>" for h in heads)}</tr></thead><tbody>{rows}</tbody><tfoot>{foot}</tfoot></table>'
          f'{extra}<footer><span>本单据由洋帆豆制品 ERP 生成，只读单据，不改变账目。</span><span>制单：{e(handler)}</span><span>审核：____________</span><span>供应商确认：____________</span><small>打印 {e(generated_at.replace("T"," ")[:19])}</small></footer></section></body></html>')
    return html

def return_print_html(c,query,generated_at):
    """客户退货单：A4 纵向单页，只读，不改变任何账目。"""
    import json,company
    def get(key,default=''):return query.get(key,[default])[0]
    def e(v):return escape(str(v if v is not None else ''),quote=True)
    def n(v):return format(Decimal(str(v or 0)).normalize(),'f')
    def money(cents):return format(Decimal(str(int(cents or 0)))/100,'.2f')
    rid=get('id').strip()
    if not rid:raise ValueError('请指定要打印的退货单')
    row=c.execute('SELECT payload FROM sales_returns WHERE id=?',(rid,)).fetchone()
    if not row:raise ValueError('退货单不存在或已删除')
    doc=json.loads(row['payload'])
    if doc.get('voided'):raise ValueError('退货单已作废，不能打印')
    condition={'broken':'破损 / 碎品','spoiled':'变质','other':'其他'}.get(doc.get('condition'),doc.get('condition') or '')
    unit=doc.get('unit') or doc.get('billing_unit') or ''
    meta=[('客户',doc.get('customer_name')),('退回日期',doc.get('received_date')),('关联原单',doc.get('order_id') or '—'),
          ('计价单位',doc.get('billing_unit') or unit),('退货数量',f"{n(doc.get('qty'))} {unit}"),('实称净重',f"{n(doc.get('net_kg'))} 公斤"),
          ('登记人',doc.get('registered_by') or doc.get('created_by') or '—')]
    heads=['序号','产品','退货数量','实称净重','退货情况','退货原因 / 来源']
    rows=(f'<tr><td>1</td><td class="long-note">{e(doc.get("product_name"))}<small>{e(unit)}</small></td>'
          f'<td>{n(doc.get("qty"))} {e(unit)}</td><td>{n(doc.get("net_kg"))} 公斤</td><td>{e(condition)}</td>'
          f'<td class="long-note">{e(doc.get("reason"))}<small>{e(doc.get("source_note"))}</small></td></tr>')
    fin=doc.get('finance') or {}
    amount_note=''
    if fin.get('amount_cents') is not None:
        amount_note=f'<p class="doc-note">会计核定扣款：{money(fin.get("amount_cents"))} 元（{n(fin.get("account_qty"))}{e(fin.get("billing_unit") or unit)} × 原价 {e(fin.get("original_price"))} 元）</p>'
    extra=f'{amount_note}<p class="doc-note">退货去向与处理按台账登记执行；本单据为退货凭据，不改变账目。</p>'
    meta_html=''.join(f'<div><span>{e(k)}</span><b>{e(v)}</b></div>' for k,v in meta)
    html=(f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><title>客户退货单 · {e(doc["id"])}</title>'
          f'<link rel="stylesheet" href="/print.css"><script defer src="/print.js"></script></head><body>'
          f'<div class="print-toolbar"><button id="print-button">打印 / 保存为 PDF</button><span>A4 纵向 · 客户退货单 · 单页</span></div>'
          f'<section class="print-page doc-table">{company.header_html(company.current(c))}<h1>客户退货单</h1>'
          f'<div class="document-meta"><b>单据号：{e(doc["id"])}</b><span>{e(doc.get("received_date"))}</span></div>'
          f'<div class="doc-meta-grid">{meta_html}</div>'
          f'<table><thead><tr>{"".join(f"<th>{e(h)}</th>" for h in heads)}</tr></thead><tbody>{rows}</tbody></table>'
          f'{extra}<footer><span>本单据由洋帆豆制品 ERP 生成，只读单据，不改变账目。</span><span>客户确认：____________</span><span>库管：____________</span><span>会计：____________</span><small>打印 {e(generated_at.replace("T"," ")[:19])}</small></footer></section></body></html>')
    return html
