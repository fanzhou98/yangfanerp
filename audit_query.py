"""Read-only business audit and security-event history with stable pagination.

The bootstrap keeps a small recent slice for order detail and first paint; this
module is the explicit history entry. It never changes audit rows.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json
import resources_costs as rc
from finance_query import _text

TZ = ZoneInfo('Asia/Shanghai')
MAX_DAYS = 3652


def _window(start, end, all_dates):
    start = _text(start, '开始日期', 10)
    end = _text(end, '结束日期', 10)
    if all_dates:
        if start or end:
            raise ValueError('全部日期不能同时指定起止日期')
        return '', ''
    today = datetime.now(TZ).date()
    start = start or today.replace(day=1).isoformat()
    end = end or today.isoformat()
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
    except ValueError:
        raise ValueError('日期格式应为 YYYY-MM-DD')
    if first > last:
        raise ValueError('开始日期不能晚于结束日期')
    if (last - first).days > MAX_DAYS:
        raise ValueError('查询范围最多3652天')
    return start, end


def _page(page, page_size):
    try:
        page = int(page)
        page_size = int(page_size)
    except (TypeError, ValueError):
        raise ValueError('分页参数无效')
    if not 1 <= page <= 100000 or not 1 <= page_size <= 200:
        raise ValueError('页码须为1至100000，每页须为1至200条')
    return page, page_size


def _page_result(rows, total, pages, page, page_size, **extra):
    return {'rows': rows, 'total': total, 'pages': pages, 'page': page, 'page_size': page_size, **extra}


def history(c, *, start='', end='', all_dates=False, role='', search='', entity='', page=1, page_size=50):
    """Business audit rows, newest first. Search is literal, not LIKE patterns."""
    start, end = _window(start, end, all_dates)
    role = _text(role, '岗位', 20)
    search = _text(search, '搜索', 100)
    entity = _text(entity, '对象', 200)
    page, page_size = _page(page, page_size)
    where = []
    args = []
    if not all_dates:
        # `at` is ISO-8601 with an offset and always starts with the local
        # date; comparing the stored text keeps the audit(at) index usable.
        next_day = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        where.append("at>=? AND at<?")
        args += [start, next_day]
    if role:
        where.append("role=?")
        args.append(role)
    if entity:
        where.append("entity=?")
        args.append(entity)
    if search:
        where.append("instr(lower(action||' '||entity||' '||COALESCE(role,'')||' '||COALESCE(actor_name,'')||' '||COALESCE(request_id,'')),lower(?))>0")
        args.append(search)
    clause = (' WHERE ' + ' AND '.join('(' + w + ')' for w in where)) if where else ''
    base = "FROM audit" + clause
    summary = c.execute("SELECT COUNT(*),COUNT(DISTINCT COALESCE(NULLIF(actor_id,''),'历史记录')),MAX(at) " + base, args).fetchone()
    total = int(summary[0] or 0)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    rows = [dict(zip(('id', 'at', 'role', 'action', 'entity', 'actor_id', 'actor_name', 'request_id'), r))
            for r in c.execute("SELECT id,at,role,action,entity,actor_id,actor_name,request_id " + base + " ORDER BY at DESC,id DESC LIMIT ? OFFSET ?",
                               [*args, page_size, (page - 1) * page_size])]
    roles = [r[0] for r in c.execute("SELECT DISTINCT role FROM audit WHERE role<>'' ORDER BY role")]
    return _page_result(rows, total, pages, page, page_size,
                        range={'start': start, 'end': end, 'all_dates': bool(all_dates)},
                        summary={'actors': int(summary[1] or 0), 'latest': summary[2] or ''}, roles=roles)


def security(c, *, start='', end='', all_dates=False, search='', page=1, page_size=50):
    """Security events use epoch seconds; end date is inclusive by local day."""
    start, end = _window(start, end, all_dates)
    search = _text(search, '搜索', 100)
    page, page_size = _page(page, page_size)
    where = []
    args = []
    if not all_dates:
        first = int(datetime.fromisoformat(start + 'T00:00:00').replace(tzinfo=TZ).timestamp())
        last = int((datetime.fromisoformat(end + 'T00:00:00') + timedelta(days=1)).replace(tzinfo=TZ).timestamp())
        where += ['at>=?', 'at<?']
        args += [first, last]
    if search:
        where.append("instr(lower(action||' '||COALESCE(actor_id,'')||' '||entity||' '||COALESCE(details_json,'')),lower(?))>0")
        args.append(search)
    clause = (' WHERE ' + ' AND '.join('(' + w + ')' for w in where)) if where else ''
    base = "FROM security_events" + clause
    summary = c.execute("SELECT COUNT(*),COUNT(DISTINCT COALESCE(actor_id,'匿名')),MAX(at) " + base, args).fetchone()
    total = int(summary[0] or 0)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    rows = [dict(zip(('id', 'at', 'action', 'actor_id', 'entity'), r))
            for r in c.execute("SELECT id,at,action,actor_id,entity " + base + " ORDER BY at DESC,id DESC LIMIT ? OFFSET ?",
                               [*args, page_size, (page - 1) * page_size])]
    return _page_result(rows, total, pages, page, page_size,
                        range={'start': start, 'end': end, 'all_dates': bool(all_dates)},
                        summary={'actors': int(summary[1] or 0), 'latest': summary[2] or 0})


ARCHIVE_KINDS = ('trial', 'order')


def archives(c, kind='trial', *, start='', end='', all_dates=False, search='', page=1, page_size=30):
    """Read archived trial rounds or duplicate orders, newest first."""
    if kind not in ARCHIVE_KINDS:
        raise ValueError('归档类型无效')
    start, end = _window(start, end, all_dates)
    search = _text(search, '搜索', 100)
    page, page_size = _page(page, page_size)
    table = 'trial_archives' if kind == 'trial' else 'archived_orders'
    date_field = 'at' if kind == 'trial' else 'archived_at'
    where, args = [], []
    if not all_dates:
        next_day = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        where.append(date_field + '>=? AND ' + date_field + '<?')
        args += [start, next_day]
    if kind == 'trial':
        where.append("COALESCE(json_extract(payload,'$.format'),'')<>'day-reset-v1'")
        if search:
            where.append("instr(lower(id||' '||reason||' '||COALESCE(json_extract(payload,'$.business_date'),'')),lower(?))>0")
            args.append(search)
        base = 'FROM trial_archives'
        select = 'SELECT id,at,reason,restored_at,payload '
        order = ' ORDER BY at DESC,id DESC'
    else:
        if search:
            where.append("instr(lower(id||' '||kept_id||' '||reason||' '||COALESCE(json_extract(payload,'$.order.business_date'),'')||' '||COALESCE(json_extract(payload,'$.order.customer_name'),'')),lower(?))>0")
            args.append(search)
        base = 'FROM archived_orders'
        select = 'SELECT id,kept_id,reason,archived_at,payload '
        order = ' ORDER BY archived_at DESC,id DESC'
    clause = (' WHERE ' + ' AND '.join('(' + w + ')' for w in where)) if where else ''
    summary = c.execute('SELECT COUNT(*),MAX(' + date_field + ') ' + base + clause, args).fetchone()
    total = int(summary[0] or 0)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    rows = []
    for r in c.execute(select + base + clause + order + ' LIMIT ? OFFSET ?', [*args, page_size, (page - 1) * page_size]):
        payload = json.loads(r[4] or '{}')
        if kind == 'trial':
            rows.append({'id': r[0], 'at': r[1], 'reason': r[2], 'restored_at': r[3] or '',
                         'format': payload.get('format', ''), 'business_date': payload.get('business_date', ''),
                         'scope': payload.get('scope', ''), 'counts': payload.get('counts', {})})
        else:
            order = payload.get('order') or {}
            rows.append({'id': r[0], 'kept_id': r[1], 'reason': r[2], 'archived_at': r[3],
                         'business_date': order.get('business_date', ''), 'customer_name': order.get('customer_name', ''),
                         'order': order})
    return _page_result(rows, total, pages, page, page_size,
                        range={'start': start, 'end': end, 'all_dates': bool(all_dates)},
                        summary={'latest': summary[1] or ''})
