"""Compact A4 matrices: demand quantities and delivered product quantities are distinct."""
from html import escape
from datetime import date
from decimal import Decimal
import hashlib,json,math,unicodedata

ROWS_PER_PAGE=26
PRODUCTS_PER_PAGE=10

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
        product_groups=[products[i:i+PRODUCTS_PER_PAGE] for i in range(0,len(products),PRODUCTS_PER_PAGE)] or [[]]
        if not rows:continue
        def text_units(v):return sum(2 if unicodedata.east_asian_width(ch) in ('W','F') else 1 for ch in str(v))
        batches=[];batch=[];units=0;start=0
        for row in rows:
            row_units=1
            if batch and units+row_units>ROWS_PER_PAGE:
                batches.append((start,batch));start+=len(batch);batch=[];units=0
            batch.append(row);units+=row_units
        if batch:batches.append((start,batch))
        for product_index,columns in enumerate(product_groups):
            for start,batch in batches:
                heads='<th class="seq">序</th><th class="customer">客户</th><th class="market">市场 / 线路</th>'+''.join(f'<th>{e(p["name"])}<small>{e(p["unit"])}</small></th>' for p in columns)+('' if demand else '<th class="handwritten">备注 / 称重</th>')
                body=''
                for i,r in enumerate(batch,start+1):
                    body+=f'<tr data-print-label="{e(r["name"]+" · "+r["route"])}" data-order-ids="{e(",".join(r["source"]))}"><td>{i}</td><td class="customer"><b data-print-fit>{e(r["name"])}</b></td><td>{e(r["route"])}</td>'
                    body+=''.join(f'<td data-quantity="{n(r["qty"].get(p["id"],0))}">{n(r["qty"].get(p["id"],0)) if r["qty"].get(p["id"],0) else "—"}</td>' for p in columns)+('' if demand else '<td class="handwritten"></td>')+'</tr>'
                totals='<tr><th colspan="3">本页合计</th>'+''.join(f'<th>{n(sum((r["qty"].get(p["id"],Decimal(0)) for r in batch),Decimal(0)))}</th>' for p in columns)+('' if demand else '<th class="handwritten"></th>')+'</tr>'
                scope='订货表当前筛选' if get('scope')=='sheet' else '当天已保存'+('订货' if demand else '实发')
                note='数量为客户订货需求。' if demand else '数量按已保存实发汇总；— 表示未发，末列供司机填写备注 / 称重。'
                product_note=f' · 产品 {product_index*PRODUCTS_PER_PAGE+1}—{product_index*PRODUCTS_PER_PAGE+len(columns)} / {len(products)}' if len(product_groups)>1 else ''
                page=f'<section class="print-page"><header>{__import__("company").header_html(data.get("company"))}<h1>{title}</h1><div class="document-meta"><b>业务日期：{e(day)}</b><span>{e(label)}{e(product_note)}</span><span>本页 <b data-print-row-count>{len(batch)}</b> 客户 / 原组 {len(rows)} 客户</span></div></header><table class="quantity-matrix" data-print-label-column="1" data-print-title="{e(label)} · {title}"><thead><tr>{heads}</tr></thead><tbody>{body}</tbody><tfoot>{totals}</tfoot></table><footer><span>{note} 单位见各产品表头。</span><span>{"录单 / 备货" if demand else "发货 / 司机"}：____________</span><span>第 <b data-print-page-number>PAGE_NUMBER</b> / <b data-print-page-count>PAGE_COUNT</b> 页</span><small>范围：{scope} · 版本 {source_hash} · 打印 {e(generated_at.replace("T"," ")[:19])}</small></footer></section>'
                pages.append(page)
    count=len(pages)
    html=''.join(p.replace('PAGE_NUMBER',str(i)).replace('PAGE_COUNT',str(count)) for i,p in enumerate(pages,1)) or '<section class="print-page"><h1>'+title+'</h1><p>当天没有符合条件的已保存'+('订货单' if demand else '实发记录')+'。</p></section>'
    return '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><title>'+title+' · '+e(day)+'</title><link rel="stylesheet" href="/print.css"><script defer src="/print.js"></script></head><body><div class="print-toolbar"><button id="print-button"'+(' disabled' if not count else '')+'>打印 / 保存为 PDF</button><span>A4 横向 · 客户 × 产品数量总表 · 每页最多 '+str(ROWS_PER_PAGE)+' 客户 · 本次 '+str(count)+' 页</span></div>'+html+'</body></html>'
