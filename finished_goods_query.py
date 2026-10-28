"""Q03 external finished-goods history: server filters, totals and stable pages.

Only the page ids are projected back with their receipts, payments and returns;
the monthly cost/order/statement projection remains in finished_goods.py.
"""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import resources_costs as rc
from finance_query import _text

STATUSES = ('pending', 'unpaid', 'paid', 'overpaid')
TODAY = lambda: datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


def _query(*, start, end, all_dates, supplier_id, search, status):
    where = []
    params = []
    if not all_dates:
        where.extend(("business_date>=?", "business_date<=?"))
        params.extend((start, end))
    if supplier_id:
        where.append('supplier_id=?')
        params.append(supplier_id)
    if search:
        where.append("(instr(lower(id||' '||COALESCE(json_extract(payload,'$.supplier_name'),'')||' '||"
                     "COALESCE(json_extract(payload,'$.reference'),'')||' '||"
                     "COALESCE(json_extract(payload,'$.note'),'')||' '||"
                     "COALESCE(json_extract(payload,'$.handler'),'')||' '||"
                     "COALESCE(json_extract(payload,'$.order_id'),'')),lower(?))>0 OR "
                     "EXISTS(SELECT 1 FROM json_each(calc.payload,'$.lines') line WHERE "
                     "instr(lower(COALESCE(json_extract(line.value,'$.product_name'),'')),lower(?))>0))")
        params.extend((search, search))
    if status == 'pending':
        where.append('pending=1')
    elif status == 'unpaid':
        where.append('pending=0 AND outstanding_cents>0')
    elif status == 'paid':
        where.append('pending=0 AND outstanding_cents=0')
    elif status == 'overpaid':
        where.append('pending=0 AND outstanding_cents<0')
    return ' WHERE ' + ' AND '.join(where) if where else '', params


def _cte(*, start, end, all_dates):
    # base is the original receipt (returns are settled into their receipt);
    # paid includes refunds, because a supplier refund reduces actual payment.
    return """WITH base AS (
      SELECT id,payload,
        json_extract(payload,'$.business_date') business_date,
        json_extract(payload,'$.supplier_id') supplier_id,
        CAST(json_extract(payload,'$.amount_cents') AS INTEGER) amount_cents,
        CASE WHEN COALESCE(json_extract(payload,'$.pricing_pending'),0)
               OR json_extract(payload,'$.pricing_status')='recalculate' THEN 1 ELSE 0 END pending
      FROM finished_goods_records
      WHERE json_extract(payload,'$.kind')='receipt'
        AND json_extract(payload,'$.return_of') IS NULL
        AND COALESCE(json_extract(payload,'$.voided'),0)=0
    ), paid AS (
      SELECT json_extract(payload,'$.receipt_id') receipt_id,
        SUM(CASE WHEN json_extract(payload,'$.kind')='payment'
                 THEN CAST(json_extract(payload,'$.amount_cents') AS INTEGER)
                 ELSE -CAST(json_extract(payload,'$.amount_cents') AS INTEGER) END) paid_cents
      FROM finished_goods_records
      WHERE json_extract(payload,'$.kind') IN ('payment','refund')
        AND COALESCE(json_extract(payload,'$.voided'),0)=0
      GROUP BY receipt_id
    ), returned AS (
      SELECT json_extract(payload,'$.return_of') receipt_id,
        -SUM(CAST(json_extract(payload,'$.amount_cents') AS INTEGER)) returned_cents
      FROM finished_goods_records
      WHERE json_extract(payload,'$.kind')='receipt'
        AND json_extract(payload,'$.return_of') IS NOT NULL
        AND COALESCE(json_extract(payload,'$.voided'),0)=0
      GROUP BY receipt_id
    ), calc AS (
      SELECT base.*, COALESCE(returned.returned_cents,0) returned_cents,
        base.amount_cents-COALESCE(returned.returned_cents,0) net_amount_cents,
        COALESCE(paid.paid_cents,0) paid_cents,
        base.amount_cents-COALESCE(returned.returned_cents,0)-COALESCE(paid.paid_cents,0) outstanding_cents
      FROM base
      LEFT JOIN paid ON paid.receipt_id=base.id
      LEFT JOIN returned ON returned.receipt_id=base.id
    )"""


def history(c, *, start='', end='', all_dates=False, supplier_id='', status='', search='', page=1, page_size=50):
    start = _text(start, '开始日期', 10)
    end = _text(end, '结束日期', 10)
    if not all_dates:
        start = start or TODAY()
        end = end or start
        rc.day(start)
        rc.day(end)
        if start > end:
            raise ValueError('开始日期不能晚于结束日期')
        if (date.fromisoformat(end) - date.fromisoformat(start)).days > 3651:
            raise ValueError('外购成品日期范围最多3652天')
    elif start or end:
        raise ValueError('全部日期不能同时指定起止日期')
    supplier_id = _text(supplier_id, '供应人', 40)
    search = _text(search, '搜索内容', 100)
    status = _text(status, '外购成品状态')
    if status and status not in STATUSES:
        raise ValueError('外购成品状态无效')
    try:
        page = int(page)
        page_size = int(page_size)
    except (TypeError, ValueError):
        raise ValueError('分页参数无效')
    if not 1 <= page <= 100000 or not 1 <= page_size <= 200:
        raise ValueError('页码须为1至100000，每页条数须为1至200')

    where, params = _query(start=start, end=end, all_dates=all_dates, supplier_id=supplier_id, search=search, status=status)
    sql = _cte(start=start, end=end, all_dates=all_dates)
    totals = c.execute(
        sql + " SELECT COUNT(*),COALESCE(SUM(amount_cents),0),COALESCE(SUM(returned_cents),0),"
        "COALESCE(SUM(net_amount_cents),0),COALESCE(SUM(paid_cents),0),"
        "COALESCE(SUM(outstanding_cents),0),COALESCE(SUM(pending),0) FROM calc" + where,
        params,
    ).fetchone()
    total = totals[0]
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    ids = [r[0] for r in c.execute(
        sql + ' SELECT id FROM calc' + where + ' ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?',
        [*params, page_size, (page - 1) * page_size],
    )]
    if not ids:
        rows = []
    else:
        marks = ','.join('?' for _ in ids)
        by_id = {r[0]: json.loads(r[1]) for r in c.execute(
            'SELECT id,payload FROM finished_goods_records WHERE id IN (' + marks + ')', ids
        )}
        payments = {}
        for rid, payload in c.execute(
            "SELECT id,payload FROM finished_goods_records WHERE json_extract(payload,'$.kind')='payment' "
            "AND COALESCE(json_extract(payload,'$.voided'),0)=0 "
            "AND json_extract(payload,'$.receipt_id') IN (" + marks + ')', ids
        ):
            value = json.loads(payload);value['id'] = rid
            payments.setdefault(value['receipt_id'], []).append(value)
        refunds = {}
        for rid, payload in c.execute(
            "SELECT id,payload FROM finished_goods_records WHERE json_extract(payload,'$.kind')='refund' "
            "AND COALESCE(json_extract(payload,'$.voided'),0)=0 "
            "AND json_extract(payload,'$.receipt_id') IN (" + marks + ')', ids
        ):
            value = json.loads(payload);value['id'] = rid
            refunds.setdefault(value['receipt_id'], []).append(value)
        returned = {}
        for rid, payload in c.execute(
            "SELECT id,payload FROM finished_goods_records WHERE json_extract(payload,'$.kind')='receipt' "
            "AND COALESCE(json_extract(payload,'$.voided'),0)=0 "
            "AND json_extract(payload,'$.return_of') IN (" + marks + ')', ids
        ):
            value = json.loads(payload);value['id'] = rid
            returned.setdefault(value['return_of'], []).append(value)
        rows = []
        for rid in ids:
            value = by_id[rid];value['id'] = rid
            ps = payments.get(rid, [])
            rs = refunds.get(rid, [])
            back = returned.get(rid, [])
            paid = sum(int(p.get('amount_cents') or 0) for p in ps) - sum(int(p.get('amount_cents') or 0) for p in rs)
            ret = -sum(int(p.get('amount_cents') or 0) for p in back)
            amount = int(value.get('amount_cents') or 0)
            value.update(paid_cents=paid, returned_cents=ret, net_amount_cents=amount - ret,
                         outstanding_cents=amount - ret - paid, payments=ps, refunds=rs,
                         returns=[p['id'] for p in back])
            rows.append(value)
    return {
        'view': 'history', 'rows': rows, 'total': total, 'page': page, 'pages': pages,
        'page_size': page_size, 'start': start, 'end': end, 'all_dates': bool(all_dates),
        'summary': {
            'count': total, 'amount_cents': totals[1], 'returned_cents': totals[2],
            'net_amount_cents': totals[3], 'paid_cents': totals[4],
            'outstanding_cents': totals[5], 'pending_count': totals[6],
        },
    }
