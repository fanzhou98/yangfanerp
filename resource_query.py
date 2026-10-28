"""Read-only Q02 ledgers. Business dates, accrual months and cash dates differ.

Date/text filters run in SQLite; expense workflow projection is applied to the
SQL-scoped source bills before totals and paging. Embedded byproduct receipts
are expanded by JSON1, with the original sale-day receipt preserved separately.
Callers own one read transaction so totals and pages share a snapshot.
"""
import json
from datetime import date
from decimal import Decimal
import resources_costs as rc
from finance_query import _page, _text

KINDS = ('expenses', 'payables', 'payments', 'byproducts', 'byproduct-receipts')


def date_filter(start, end):
    if start: rc.day(start)
    if end: rc.day(end)
    if bool(start) != bool(end): raise ValueError('请同时填写开始和结束日期')
    if start and (start > end or (date.fromisoformat(end)-date.fromisoformat(start)).days > 3652):
        raise ValueError('日期范围须正序且不超过3652天')


def field(name, alias='e'):
    return f"json_extract({alias}.payload,'$.{name}')"


def period_clause(period):
    if period:
        try:
            if len(period)!=7 or date.fromisoformat(period+'-01').strftime('%Y-%m')!=period: raise ValueError()
        except (ValueError, TypeError): raise ValueError('费用所属月无效')
        # Accruals replace the source month for spread bills, exactly as period_expenses.
        return "e.id IN (SELECT expense_id FROM expense_accrual_lookup WHERE period=?)", [period]
    return '1', []


def ledger(c, *, kind='expenses', period='', start='', end='', all_dates=False,
           page=1, page_size=50, stage='all', query='', supplier_id='', counterparty_id='', customer_id='',
           payment_start='', payment_end='', record_id=''):
    if kind not in KINDS: raise ValueError('台账类型无效')
    if kind in ('byproducts','byproduct-receipts') and stage not in ('all','voided'):raise ValueError('豆渣状态无效')
    _page([], page, page_size)  # Validate even empty results.
    date_filter(start,end);date_filter(payment_start,payment_end)
    if stage not in ('all','review','pay','pending','approved','partial','returned','paid','voided','payroll','noncash'):
        raise ValueError('流程状态无效')
    query=_text(query,'搜索');record_id=_text(record_id,'单号')
    supplier_id=_text(supplier_id,'供应商');counterparty_id=_text(counterparty_id,'收款方');customer_id=_text(customer_id,'客户')
    if not all_dates and not start and not period and not record_id:
        raise ValueError('请选择日期、费用所属月或全部日期')
    if not c.in_transaction:c.execute('BEGIN')
    where=['1'];args=[]
    if kind in ('expenses','payables','payments'):
        clause,values=period_clause(period);where.append(clause);args.extend(values)
    elif period: raise ValueError('豆渣台账请按销售日或到账日查询')
    if start:
        where.append(field('business_date')+' BETWEEN ? AND ?');args.extend([start,end])
    for name,value in (('supplier_id',supplier_id),('counterparty_id',counterparty_id),('customer_id',customer_id)):
        if value:where.append(field(name)+'=?');args.append(value)
    if record_id:where.append('e.id=?');args.append(record_id)
    if query:
        expression="instr(lower(e.id||' '||COALESCE("+field('partner')+",'')||' '||COALESCE("+field('buyer')+",'')||' '||COALESCE("+field('handler')+",'')||' '||COALESCE("+field('reference')+",'')||' '||COALESCE("+field('note')+",'')||' '||COALESCE("+field('category')+",'')),lower(?))>0"
        args.append(query)
        if kind in ('expenses','payables','payments'):
            import cost_allocation
            category_ids=[r['id'] for r in cost_allocation.categories(c) if query.lower() in r['name'].lower()]
            expression+=" OR "+field('category')+" IN (SELECT value FROM json_each(?))"
            args.append(json.dumps(category_ids))
            expression+=" OR EXISTS (SELECT 1 FROM expense_payments p WHERE "+field('expense_id','p')+"=+e.id AND instr(lower(COALESCE("+field('payee','p')+",'')),lower(?))>0)"
            args.append(query)
        where.append('('+expression+')')
    condition=' AND '.join(where)
    if kind in ('byproducts','byproduct-receipts'):
        return byproducts(c,kind,condition,args,page,page_size,stage,payment_start,payment_end)
    import expense_query
    return expense_query.ledger(c,kind,condition,args,period=period,stage=stage,page=page,page_size=page_size,payment_start=payment_start,payment_end=payment_end)


def page_numbers(total,page,page_size):
    pages=max(1,(total+page_size-1)//page_size)
    return min(int(page),pages),pages


def byproducts(c,kind,condition,args,page,page_size,stage,start,end):
    active=condition+" AND COALESCE("+field('voided')+",0)=0"
    if kind=='byproduct-receipts':
        # Receipt date filtering happens AFTER expanding ALL matching sales. Sales
        # dates are an optional, separate constraint supplied by the caller.
        receipt_cte="""WITH sales AS (SELECT e.id,e.payload FROM byproduct_sales e WHERE """+active+"""), cash AS (
          SELECT s.id||':receipt:'||(CAST(j.key AS INTEGER)+1) AS id,s.id AS sale_id,
            COALESCE(json_extract(j.value,'$.business_date'),json_extract(s.payload,'$.business_date')) AS business_date,
            CAST(json_extract(j.value,'$.amount_cents') AS INTEGER) AS amount_cents,
            json_extract(s.payload,'$.buyer') AS buyer, json_extract(j.value,'$.note') AS note
          FROM sales s,json_each(s.payload,'$.receipts') j
          UNION ALL
          SELECT s.id||':legacy',s.id,json_extract(s.payload,'$.business_date'),
            json_extract(s.payload,'$.received_cents')-COALESCE((SELECT SUM(json_extract(j.value,'$.amount_cents')) FROM json_each(s.payload,'$.receipts') j),0),
            json_extract(s.payload,'$.buyer'),'原销售记录已收金额'
          FROM sales s WHERE json_extract(s.payload,'$.received_cents')>COALESCE((SELECT SUM(json_extract(j.value,'$.amount_cents')) FROM json_each(s.payload,'$.receipts') j),0)
        ) """
        cond='business_date BETWEEN ? AND ?' if start else '1';params=[*args,*([start,end] if start else [])]
        total,amount=c.execute(receipt_cte+'SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM cash WHERE '+cond,params).fetchone()
        current,pages=page_numbers(total,page,page_size)
        cur=c.execute(receipt_cte+'SELECT * FROM cash WHERE '+cond+' ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?',[*params,page_size,(current-1)*page_size]);names=[d[0] for d in cur.description];rows=[dict(zip(names,r)) for r in cur]
        return dict(rows=rows,total=total,page=current,pages=pages,summary={'count':total,'amount_cents':amount})
    cond=condition+(" AND COALESCE("+field('voided')+",0)="+('1' if stage=='voided' else '0'))
    total,amount,received,milli=c.execute('SELECT COUNT(*),COALESCE(SUM('+field('amount_cents')+'),0),COALESCE(SUM('+field('received_cents')+"),0),COALESCE(SUM(CAST(ROUND(CAST("+field('qty')+" AS REAL)*1000) AS INTEGER)*CASE WHEN "+field('unit')+"='吨' THEN 1000 ELSE 1 END),0) FROM byproduct_sales e WHERE "+cond,args).fetchone()
    current,pages=page_numbers(total,page,page_size)
    rows=[rc.byproduct_business_record(json.loads(r[0])) for r in c.execute('SELECT e.payload FROM byproduct_sales e WHERE '+cond+' ORDER BY '+field('business_date')+' DESC,e.id DESC LIMIT ? OFFSET ?',[*args,page_size,(current-1)*page_size])]
    return dict(rows=rows,total=total,page=current,pages=pages,summary={'count':total,'amount_cents':amount,'received_cents':received,'outstanding_cents':amount-received,'qty_kg':str(Decimal(milli)/1000)})
