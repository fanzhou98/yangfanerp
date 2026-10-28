"""Indexed sales-order reads and stable page contracts.

Only date/customer filters are pushed to SQLite. Status/region/product/search
remain business filters after the indexed date-range read, so their semantics
keep matching the existing report contracts.
"""
from datetime import date
import json
import resources_costs as rc

MAX_RANGE_DAYS = 3651
PAGE_SIZE = 50


def bounds(c):
    """Earliest/latest order business date; today when there are no orders."""
    first = c.execute("SELECT json_extract(payload,'$.business_date') FROM orders WHERE json_extract(payload,'$.business_date') IS NOT NULL ORDER BY json_extract(payload,'$.business_date') ASC,id ASC LIMIT 1").fetchone()
    last = c.execute("SELECT json_extract(payload,'$.business_date') FROM orders WHERE json_extract(payload,'$.business_date') IS NOT NULL ORDER BY json_extract(payload,'$.business_date') DESC,id DESC LIMIT 1").fetchone()
    if not first or not last or not first[0] or not last[0]:
        today = date.today().isoformat()
        return today, today
    return first[0], last[0]


def resolve(c, start, end, all_dates=False):
    if all_dates:
        return bounds(c)
    rc.day(start); rc.day(end)
    if start > end:
        raise ValueError('开始日期不能晚于结束日期')
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > MAX_RANGE_DAYS:
        raise ValueError('销售报表日期范围最多3652天')
    return start, end


def orders(c, start, end, *, region='', customer_id=''):
    """Read orders in an inclusive date range through expression indexes.

    A customer filter is applied in SQL; a region is resolved to customer IDs
    first because region lives in the relational customer master, not in order
    JSON. The caller keeps all business-level status/product/search filtering.
    """
    sql = "SELECT payload FROM orders WHERE json_extract(payload,'$.business_date') BETWEEN ? AND ?"
    params = [start, end]
    if customer_id:
        sql += " AND json_extract(payload,'$.customer_id')=?"
        params.append(customer_id)
    elif region:
        ids = [r[0] for r in c.execute("SELECT id FROM customers WHERE COALESCE(NULLIF(region,''),'未设置地区')=?", (region,))]
        if not ids:
            return []
        sql += " AND json_extract(payload,'$.customer_id') IN (" + ','.join('?' for _ in ids) + ")"
        params.extend(ids)
    sql += " ORDER BY json_extract(payload,'$.business_date'),id"
    return [json.loads(r[0]) for r in c.execute(sql, params)]


def page(rows, page_number, page_size=PAGE_SIZE):
    if type(page_number) is not int or not 1 <= page_number <= 100000:
        raise ValueError('页码无效')
    if type(page_size) is not int or not 1 <= page_size <= 200:
        raise ValueError('每页条数须为1至200')
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    current = min(page_number, pages)
    return rows[(current - 1) * page_size:current * page_size], current, pages


def validate_page(value, page_size=50):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError('页码无效')
    if number < 1 or number > 100000:
        raise ValueError('页码无效')
    if type(page_size) is not int or not 1 <= page_size <= 200:
        raise ValueError('每页条数须为1至200')
    return number
