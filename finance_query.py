"""Server-side receivable ledger reads with a stable page contract.

The ledger keeps the order business date and the receipt date as separate
facts.  Order rows are selected by business date; receipt rows are selected by
their own received date, while both stay inside the same customer/market/search
scope.  Summaries always cover the complete filter result, never only one page.
"""
from datetime import date
import json

import resources_costs as rc
import sales_query

PAGE_SIZE = sales_query.PAGE_SIZE
MAX_RANGE_DAYS = sales_query.MAX_RANGE_DAYS
MAX_TEXT = 100


def _text(value, label, limit=MAX_TEXT):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError(f'{label}无效')
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f'{label}最多{limit}字')
    return value


def _date_range(c, start, end, all_dates=False, basis='business_date'):
    if all_dates:
        # All dates must include byproduct sales and actual receipts, which can
        # be later than the latest product order (month-end bean settlements).
        dates=[]
        for table,field in (('orders','business_date'),('byproduct_sales','business_date'),('receipts','received_date')):
            expression="json_extract(payload,'$."+field+"')"
            for direction in ('ASC','DESC'):
                row=c.execute('SELECT '+expression+' FROM '+table+' WHERE '+expression+' IS NOT NULL ORDER BY '+expression+' '+direction+',id '+direction+' LIMIT 1').fetchone()
                if row and row[0]:dates.append(row[0])
        if basis=='settled_date':
            for table,expression in (('orders',"substr(json_extract(payload,'$.settlement.at'),1,10)"),('byproduct_sales',"substr(json_extract(payload,'$.created_at'),1,10)")):
                for direction in ('ASC','DESC'):
                    row=c.execute('SELECT '+expression+' FROM '+table+' WHERE '+expression+" IS NOT NULL AND "+expression+"!='' ORDER BY "+expression+' '+direction+',id '+direction+' LIMIT 1').fetchone()
                    if row and row[0]:dates.append(row[0])
        receipt_bounds=c.execute("SELECT MIN(json_extract(r.value,'$.business_date')),MAX(json_extract(r.value,'$.business_date')) FROM byproduct_sales b,json_each(b.payload,'$.receipts') r").fetchone()
        dates.extend(value for value in receipt_bounds if value)
        return (min(dates),max(dates)) if dates else (date.today().isoformat(),date.today().isoformat())
    rc.day(start)
    rc.day(end)
    if start > end:
        raise ValueError('开始日期不能晚于结束日期')
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > MAX_RANGE_DAYS:
        raise ValueError('应收日期范围最多3652天')
    return start, end


def _page(rows, number, page_size=PAGE_SIZE):
    try:
        page_number = int(number)
    except (TypeError, ValueError):
        raise ValueError('页码无效')
    if not 1 <= page_number <= 100000:
        raise ValueError('页码无效')
    if not 1 <= page_size <= 200:
        raise ValueError('每页条数须为1至200')
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    current = min(page_number, pages)
    return rows[(current - 1) * page_size:current * page_size], current, pages


def _market_label(is_byproduct, customer, order, markets):
    if is_byproduct:
        return '豆渣客户'
    return (markets.get(customer.get('market_id')) or order.get('route')
            or customer.get('route') or '未设置市场')


def _product_order(order, customer, markets, receipts):
    total = int(order.get('total_cents') or 0)
    paid = int(order.get('paid_cents') or 0)
    credit = int(order.get('return_credit_cents') or 0)
    discount = int(order.get('discount_cents') or 0)
    rounding = int(order.get('rounding_cents') or 0)
    lines = []
    for line in order.get('lines') or []:
        lines.append({
            'product_id': line.get('product_id', ''),
            'product_name': line.get('product_name', ''),
            'bill_qty': line.get('bill_qty', line.get('actual_qty')),
            'unit': line.get('billing_unit') or line.get('unit') or '',
            'price': line.get('price'),
            'amount_cents': int(line.get('amount_cents') or 0),
        })
    return {
        'id': order['id'],
        'is_byproduct': False,
        'state': order.get('state', ''),
        'business_date': order['business_date'],
        'settled_date': ((order.get('settlement') or {}).get('at') or '')[:10],
        'customer_id': order.get('customer_id', ''),
        'customer_name': order.get('customer_name') or customer.get('name', ''),
        'market': _market_label(False, customer, order, markets),
        'route': order.get('route', ''),
        'total_cents': total,
        'paid_cents': paid,
        'return_credit_cents': credit,
        'discount_cents': discount,
        'rounding_cents': rounding,
        'outstanding_cents': total - paid - credit - discount - rounding,
        'version': order.get('version'),
        'lines': lines,
        'receipts': receipts,
    }


def _byproduct_order(record, customer, receipts):
    amount = int(record.get('amount_cents') or 0)
    received = int(record.get('received_cents') or 0)
    return {
        'id': record['id'],
        'is_byproduct': True,
        'state': 'reviewed',
        'business_date': record['business_date'],
        'settled_date': (record.get('created_at') or '')[:10],
        'customer_id': record.get('customer_id', ''),
        'customer_name': customer.get('name') or record.get('buyer', ''),
        'market': '豆渣客户',
        'route': '豆渣客户',
        'total_cents': amount,
        'paid_cents': received,
        'return_credit_cents': 0,
        'discount_cents': 0,
        'rounding_cents': 0,
        'outstanding_cents': amount - received,
        'version': record.get('version'),
        'lines': [{
            'product_id': 'BYPRODUCT',
            'product_name': '豆渣',
            'bill_qty': record.get('qty'),
            'unit': record.get('unit') or '公斤',
            'price': record.get('price'),
            'amount_cents': amount,
        }],
        'receipts': receipts,
    }


def _product_receipt(receipt, order):
    return {
        'id': receipt.get('id') or f"{order['id']}:receipt",
        'order_id': order['id'],
        'customer_id': order['customer_id'],
        'customer_name': order['customer_name'],
        'received_date': receipt['received_date'],
        'amount_cents': int(receipt.get('amount_cents') or 0),
        'discount_cents': int(receipt.get('discount_cents') or 0),
        'rounding_cents': int(receipt.get('rounding_cents') or 0),
        'method': receipt.get('method', ''),
        'note': receipt.get('note', ''),
        'evidence_id': receipt.get('evidence_id', ''),
        'transaction_no': receipt.get('transaction_no', ''),
    }


def _byproduct_receipts(record, order):
    result = []
    embedded = record.get('receipts') or []
    for index, receipt in enumerate(embedded):
        result.append({
            'id': receipt.get('id') or f"{order['id']}:receipt:{index + 1}",
            'order_id': order['id'],
            'customer_id': order['customer_id'],
            'customer_name': order['customer_name'],
            'received_date': receipt.get('business_date', order['business_date']),
            'amount_cents': int(receipt.get('amount_cents') or 0),
            'discount_cents': 0,
            'rounding_cents': 0,
            'method': '豆渣收款',
            'note': receipt.get('note', ''),
        })
    recorded = sum(int(r.get('amount_cents') or 0) for r in embedded)
    received = int(record.get('received_cents') or 0)
    if received > recorded:
        result.append({
            'id': f"{order['id']}:legacy",
            'order_id': order['id'],
            'customer_id': order['customer_id'],
            'customer_name': order['customer_name'],
            'received_date': order['business_date'],
            'amount_cents': received - recorded,
            'discount_cents': 0,
            'rounding_cents': 0,
            'method': '豆渣收款',
            'note': '原销售记录已收金额',
        })
    return result


def _select_receipts(receipts, start, end):
    return [r for r in receipts if start <= r['received_date'] <= end]


def ledger(c, start, end, *, source='all', market='', clearance='open',
           customer_id='', query='', page=1, receipt_page=1,
           receipt_start=None, receipt_end=None, all_dates=False,
           page_size=PAGE_SIZE, basis='business_date'):
    """Return one page of orders plus the complete filtered summary.

    ``receipt_start`` and ``receipt_end`` default to the order range.  The
    receipt page is still constrained to orders in the filtered ledger scope,
    so its page cannot leak a customer that the order filters excluded.
    """
    if not c.in_transaction:c.execute('BEGIN')
    if basis not in ('business_date','settled_date'):raise ValueError('日期口径无效')
    start, end = _date_range(c, start, end, all_dates, basis)
    source = _text(source, '业务来源') or 'all'
    clearance = _text(clearance, '清账状态') or 'open'
    market = _text(market, '市场')
    customer_id = _text(customer_id, '客户', 40)
    query = _text(query, '搜索', 100)
    if source not in ('all', 'sales', 'byproduct'):
        raise ValueError('业务来源无效')
    if clearance not in ('all', 'open', 'cleared'):
        raise ValueError('清账状态无效')
    receipt_start = _text(receipt_start, '到账开始日期') or start
    receipt_end = _text(receipt_end, '到账结束日期') or end
    rc.day(receipt_start)
    rc.day(receipt_end)
    if receipt_start > receipt_end:
        raise ValueError('到账开始日期不能晚于结束日期')
    if (date.fromisoformat(receipt_end) - date.fromisoformat(receipt_start)).days > MAX_RANGE_DAYS:
        raise ValueError('到账日期范围最多3652天')
    page_size = int(page_size)
    if not 1 <= page_size <= 200:
        raise ValueError('每页条数须为1至200')

    _page([],page,page_size);_page([],receipt_page,page_size)
    c.create_function('erp_casefold',1,lambda value:str(value or '').casefold(),deterministic=True)
    sql,params=_ledger_sql(start,end,source,market,clearance,customer_id,query,basis)
    total_keys=('total_cents','paid_cents','return_credit_cents','discount_cents','rounding_cents','outstanding_cents')
    sums=','.join('COALESCE(SUM('+key+'),0) AS '+key for key in total_keys)
    summary=_dicts(c,sql+'SELECT COUNT(*) AS count,'+sums+' FROM scoped',params)[0]
    total=summary['count'];pages=max(1,(total+page_size-1)//page_size);current=min(int(page),pages)
    customers_summary=_dicts(c,sql+'SELECT customer_id,(SELECT customer_name FROM scoped first WHERE first.customer_id=s.customer_id ORDER BY business_date,id,is_byproduct LIMIT 1) AS customer_name,COUNT(*) AS count,'+sums+' FROM scoped s GROUP BY customer_id ORDER BY customer_name,customer_id',params)
    summary['opening_cents']=0
    opening_rows=_dicts(c,"SELECT id AS customer_id,name AS customer_name,COALESCE(opening_cents,0) AS amount_cents,opening_date FROM customers WHERE COALESCE(opening_cents,0)>0 AND COALESCE(opening_date,'')<>'' AND opening_date<=?"+(" AND id=?" if customer_id else ""),[end]+([customer_id] if customer_id else []))
    opening_paid=rc.opening_receipts_paid(c,end) if opening_rows else {}
    for row in opening_rows:
        row['amount_cents']=max(0,int(row['amount_cents'] or 0)-opening_paid.get(row['customer_id'],0))
    opening_rows=[row for row in opening_rows if int(row['amount_cents'] or 0)>0]
    opening_total=sum(int(r['amount_cents']) for r in opening_rows)
    if opening_total and clearance!='cleared':
        opening_by_customer={r['customer_id']:r for r in opening_rows}
        summary['opening_cents']=opening_total
        summary['outstanding_cents']+=opening_total
        seen=set()
        for item in customers_summary:
            extra=opening_by_customer.get(item['customer_id'])
            if extra:
                item['opening_cents']=int(extra['amount_cents']);item['outstanding_cents']+=int(extra['amount_cents']);seen.add(item['customer_id'])
        for cid_,extra in opening_by_customer.items():
            if cid_ in seen:continue
            customers_summary.append({'customer_id':cid_,'customer_name':extra['customer_name'],'count':0,'total_cents':0,'paid_cents':0,'return_credit_cents':0,'discount_cents':0,'rounding_cents':0,'outstanding_cents':int(extra['amount_cents']),'opening_cents':int(extra['amount_cents'])})
        customers_summary.sort(key=lambda item:((item['customer_name'] or ''),item['customer_id']))
    market_options=[r[0] for r in c.execute(sql+'SELECT DISTINCT market FROM base ORDER BY market',params)]
    raw_page=_dicts(c,sql+'SELECT * FROM scoped ORDER BY business_date,id,is_byproduct LIMIT ? OFFSET ?',[*params,page_size,(current-1)*page_size])
    # Only the displayed bills are decoded; their nested details remain complete.
    order_ids=[r['id'] for r in raw_page if not r['is_byproduct']]
    receipts_by_order={}
    if order_ids:
        for payload, in c.execute("SELECT payload FROM receipts WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 AND json_extract(payload,'$.order_id') IN (SELECT value FROM json_each(?)) ORDER BY rowid",(json.dumps(order_ids),)):
            record=json.loads(payload)
            if record.get('received_date'):receipts_by_order.setdefault(record['order_id'],[]).append(record)
    row_page=[]
    for row in raw_page:
        record=json.loads(row['payload']);customer={'name':row['customer_name']}
        if row['is_byproduct']:
            normalized=_byproduct_order(record,customer,[]);normalized['receipts']=_byproduct_receipts(record,normalized)
        else:
            normalized=_product_order(record,customer,{},[])
            normalized['market']=row['market']
            normalized['receipts']=[_product_receipt(r,normalized) for r in receipts_by_order.get(row['id'],[])]
        row_page.append(normalized)
    cash_sql=sql+_receipt_sql()
    cash_params=[*params,receipt_start,receipt_end]
    receipt_summary=_dicts(c,cash_sql+"SELECT COUNT(*) AS count,COALESCE(SUM(amount_cents),0) AS amount_cents,COALESCE(SUM(discount_cents),0) AS discount_cents,COALESCE(SUM(rounding_cents),0) AS rounding_cents FROM cash",cash_params)[0]
    receipt_total=receipt_summary['count'];receipt_pages=max(1,(receipt_total+page_size-1)//page_size);receipt_current=min(int(receipt_page),receipt_pages)
    receipt_rows=_dicts(c,cash_sql+'SELECT * FROM cash ORDER BY received_date DESC,order_id DESC,id DESC LIMIT ? OFFSET ?',[*cash_params,page_size,(receipt_current-1)*page_size])
    return {'start':start,'end':end,'basis':basis,'receipt_start':receipt_start,'receipt_end':receipt_end,
            'rows':row_page,'summary':summary,'customers':customers_summary,'markets':market_options,
            'receipts':receipt_rows,'receipt_summary':receipt_summary,'page':current,'pages':pages,
            'page_size':page_size,'total':total,'receipt_page':receipt_current,'receipt_pages':receipt_pages,'receipt_total':receipt_total}


def _dicts(c,sql,params):
    cursor=c.execute(sql,params);names=[r[0] for r in cursor.description]
    return [dict(zip(names,row)) for row in cursor]


def _ledger_sql(start,end,source,market,clearance,customer_id,query,basis):
    """Parameter-only scope shared by totals, groups, pages and cash queries."""
    product_date="json_extract(o.payload,'$.business_date')" if basis=='business_date' else "substr(json_extract(o.payload,'$.settlement.at'),1,10)"
    bean_date="json_extract(o.payload,'$.business_date')" if basis=='business_date' else "substr(json_extract(o.payload,'$.created_at'),1,10)"
    scope=['1'];scope_params=[]
    if source!='all':scope.append('is_byproduct=?');scope_params.append(int(source=='byproduct'))
    if market:scope.append('market=?');scope_params.append(market)
    if customer_id:scope.append('customer_id=?');scope_params.append(customer_id)
    if query:
        scope.append("instr(erp_casefold(id||' '||customer_id||' '||customer_name||' '||market),erp_casefold(?))>0");scope_params.append(query)
    scope=' AND '.join(scope)
    params=[start,end,start,end,*scope_params,*scope_params]
    clearance_condition='outstanding_cents>0' if clearance=='open' else 'outstanding_cents=0' if clearance=='cleared' else '1'
    sql="""WITH candidates AS (
      SELECT o.id,0 AS is_byproduct,json_extract(o.payload,'$.business_date') AS business_date,
        COALESCE(json_extract(o.payload,'$.customer_id'),'') AS customer_id,
        COALESCE(NULLIF(json_extract(o.payload,'$.customer_name'),''),c.name,'') AS customer_name,
        COALESCE(NULLIF(m.name,''),NULLIF(json_extract(o.payload,'$.route'),''),NULLIF(c.route,''),'未设置市场') AS market,
        COALESCE(json_extract(o.payload,'$.total_cents'),0) AS total_cents,
        COALESCE(json_extract(o.payload,'$.paid_cents'),0) AS paid_cents,
        COALESCE(json_extract(o.payload,'$.return_credit_cents'),0) AS return_credit_cents,
        COALESCE(json_extract(o.payload,'$.discount_cents'),0) AS discount_cents,
        COALESCE(json_extract(o.payload,'$.rounding_cents'),0) AS rounding_cents,o.payload
      FROM orders o LEFT JOIN customers c ON c.id=json_extract(o.payload,'$.customer_id')
        LEFT JOIN delivery_markets m ON m.id=c.market_id
      WHERE json_extract(o.payload,'$.state')='reviewed' AND """+product_date+""" BETWEEN ? AND ?
      UNION ALL
      SELECT o.id,1,json_extract(o.payload,'$.business_date'),COALESCE(json_extract(o.payload,'$.customer_id'),''),
        COALESCE(NULLIF(c.name,''),json_extract(o.payload,'$.buyer'),''),'豆渣客户',
        COALESCE(json_extract(o.payload,'$.amount_cents'),0),COALESCE(json_extract(o.payload,'$.received_cents'),0),0,0,0,o.payload
      FROM byproduct_sales o LEFT JOIN customers c ON c.id=json_extract(o.payload,'$.customer_id')
      WHERE COALESCE(json_extract(o.payload,'$.voided'),0)=0 AND """+bean_date+""" BETWEEN ? AND ?
    ), base AS (SELECT *,total_cents-paid_cents-return_credit_cents-discount_cents-rounding_cents AS outstanding_cents FROM candidates),
    ledger_scope AS (SELECT * FROM base WHERE /*scope*/),
    scoped AS (SELECT * FROM ledger_scope WHERE /*clear*/),
    cash_orders AS (
      SELECT * FROM (
        SELECT o.id,0 AS is_byproduct,"""+product_date+""" AS business_date,
          COALESCE(json_extract(o.payload,'$.customer_id'),'') AS customer_id,
          COALESCE(NULLIF(json_extract(o.payload,'$.customer_name'),''),c.name,'') AS customer_name,
          COALESCE(NULLIF(m.name,''),NULLIF(json_extract(o.payload,'$.route'),''),NULLIF(c.route,''),'未设置市场') AS market,
          COALESCE(json_extract(o.payload,'$.total_cents'),0) AS total_cents,
          COALESCE(json_extract(o.payload,'$.paid_cents'),0) AS paid_cents,
          COALESCE(json_extract(o.payload,'$.return_credit_cents'),0) AS return_credit_cents,
          COALESCE(json_extract(o.payload,'$.discount_cents'),0) AS discount_cents,
          COALESCE(json_extract(o.payload,'$.rounding_cents'),0) AS rounding_cents,o.payload
        FROM orders o LEFT JOIN customers c ON c.id=json_extract(o.payload,'$.customer_id')
          LEFT JOIN delivery_markets m ON m.id=c.market_id
        WHERE json_extract(o.payload,'$.state')='reviewed'
        UNION ALL
        SELECT o.id,1,json_extract(o.payload,'$.business_date'),COALESCE(json_extract(o.payload,'$.customer_id'),''),
          COALESCE(NULLIF(c.name,''),json_extract(o.payload,'$.buyer'),''),'豆渣客户',
          COALESCE(json_extract(o.payload,'$.amount_cents'),0),COALESCE(json_extract(o.payload,'$.received_cents'),0),0,0,0,o.payload
        FROM byproduct_sales o LEFT JOIN customers c ON c.id=json_extract(o.payload,'$.customer_id')
        WHERE COALESCE(json_extract(o.payload,'$.voided'),0)=0
      ) WHERE /*scope*/
    ) """
    sql=sql.replace('/*scope*/',scope).replace('/*clear*/',clearance_condition)
    return sql,params


def _receipt_sql():
    # cash_all carries the real received date. The indexed product receipt range
    # is pushed into its own branch; JSON receipts stay tied to matching bills.
    return """, cash_bounds AS (SELECT ? AS start,? AS end), cash_all AS (
      SELECT COALESCE(NULLIF(json_extract(r.payload,'$.id'),''),s.id||':receipt') AS id,s.id AS order_id,
        s.customer_id,s.customer_name,json_extract(r.payload,'$.received_date') AS received_date,
        COALESCE(json_extract(r.payload,'$.amount_cents'),0) AS amount_cents,
        COALESCE(json_extract(r.payload,'$.discount_cents'),0) AS discount_cents,
        COALESCE(json_extract(r.payload,'$.rounding_cents'),0) AS rounding_cents,
        COALESCE(json_extract(r.payload,'$.method'),'') AS method,COALESCE(json_extract(r.payload,'$.note'),'') AS note,
        COALESCE(json_extract(r.payload,'$.evidence_id'),'') AS evidence_id,COALESCE(json_extract(r.payload,'$.transaction_no'),'') AS transaction_no
      FROM receipts r JOIN cash_orders s ON s.id=json_extract(r.payload,'$.order_id') AND s.is_byproduct=0
      WHERE COALESCE(json_extract(r.payload,'$.voided'),0)=0
        AND json_extract(r.payload,'$.received_date') BETWEEN (SELECT start FROM cash_bounds) AND (SELECT end FROM cash_bounds)
      UNION ALL
      SELECT COALESCE(NULLIF(json_extract(j.value,'$.id'),''),s.id||':receipt:'||(CAST(j.key AS INTEGER)+1)),s.id,s.customer_id,s.customer_name,
        COALESCE(json_extract(j.value,'$.business_date'),s.business_date),COALESCE(json_extract(j.value,'$.amount_cents'),0),0,0,'豆渣收款',COALESCE(json_extract(j.value,'$.note'),''),'',''
      FROM cash_orders s,json_each(s.payload,'$.receipts') j WHERE s.is_byproduct=1
      UNION ALL
      SELECT s.id||':legacy',s.id,s.customer_id,s.customer_name,s.business_date,
        s.paid_cents-COALESCE((SELECT SUM(json_extract(j.value,'$.amount_cents')) FROM json_each(s.payload,'$.receipts') j),0),0,0,'豆渣收款','原销售记录已收金额','',''
      FROM cash_orders s WHERE s.is_byproduct=1 AND s.paid_cents>COALESCE((SELECT SUM(json_extract(j.value,'$.amount_cents')) FROM json_each(s.payload,'$.receipts') j),0)
    ), cash AS (SELECT * FROM cash_all WHERE received_date BETWEEN (SELECT start FROM cash_bounds) AND (SELECT end FROM cash_bounds)) """
