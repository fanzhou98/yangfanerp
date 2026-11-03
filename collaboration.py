"""Message notifications and administrator feedback.

The module keeps its own records (notifications and feedback tickets). It never
changes business documents; notifications only describe what happened and where
to look.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import auth

TZ = timezone(timedelta(hours=8))
FEEDBACK_CATEGORIES = ('功能异常', '使用问题', '改进建议', '其他')
FEEDBACK_STATUS = ('open', 'replied', 'closed')


def _now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def text(value, label, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError(('请填写' if required else '') + label + '（最多' + str(limit) + '字）')
    return value.strip()


def integer(value, label, minimum=0, maximum=10 ** 12):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(label + '无效')
    return value


def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'collaboration')


def fingerprint(body):
    return hashlib.sha256(dump({k: v for k, v in body.items() if k not in ('_data_epoch', 'request_key')}).encode()).hexdigest()


def _admin_ids(c):
    return [r[0] for r in c.execute("SELECT id FROM auth_users WHERE active=1 AND role='管理员'")]


def notify(c, user_ids, kind, title, body, page='', entity_id='', actor_name=''):
    recipients = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not recipients:
        return []
    created = []
    stamp = _now()
    for user_id in recipients:
        notification_id = 'NT-' + secrets.token_hex(8).upper()
        payload = {'id': notification_id, 'kind': kind, 'title': title, 'body': body, 'page': page,
                   'entity_id': entity_id, 'actor_name': actor_name, 'created_at': stamp}
        c.execute('INSERT INTO notifications VALUES(?,?,?,?,?)', (notification_id, user_id, stamp, '', dump(payload)))
        created.append(notification_id)
    return created


def list_notifications(c, user):
    rows = c.execute("SELECT payload,read_at FROM notifications WHERE user_id=? AND json_extract(payload,'$.kind')<>'chat' ORDER BY created_at DESC,rowid DESC LIMIT 100", (user['id'],)).fetchall()
    items = [{**json.loads(row['payload']), 'read': bool(row['read_at']), 'read_at': row['read_at'] or ''} for row in rows]
    unread = c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at='' AND json_extract(payload,'$.kind')<>'chat'", (user['id'],)).fetchone()[0]
    return {'items': items, 'unread_count': unread,
            'counts': {'feedback_open': _feedback_open_count(c, user)}}


def mark_notifications(c, user, body):
    stamp = _now()
    if body.get('all') is True:
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at=''", (stamp, user['id']))
    else:
        ids = body.get('ids')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 200 or any(not isinstance(item, str) for item in ids):
            raise ValueError('请选择要标记已读的通知')
        c.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at=\'\' AND id IN (' + ','.join('?' for _ in ids) + ')',
                  (stamp, user['id'], *ids))
    unread = c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at=''", (user['id'],)).fetchone()[0]
    return {'unread_count': unread}


def _feedback_open_count(c, user):
    if user.get('role') == '管理员':
        return c.execute("SELECT COUNT(*) FROM feedback_tickets WHERE json_extract(payload,'$.status')='open'").fetchone()[0]
    return c.execute("SELECT COUNT(*) FROM feedback_tickets WHERE user_id=? AND json_extract(payload,'$.status')='open'", (user['id'],)).fetchone()[0]


def _ticket_view(payload):
    return {**payload, 'replies': list(payload.get('replies', [])), 'status_label': {'open': '待处理', 'replied': '已回复', 'closed': '已关闭'}.get(payload.get('status'), payload.get('status'))}


def _feedback_window(start, end, all_dates):
    if all_dates:
        return '', ''
    today = datetime.now(TZ).date()
    if not start or not end:
        start, end = today.replace(day=1).isoformat(), today.isoformat()
    try:
        first, last = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    except ValueError:
        raise ValueError('请输入有效的反馈日期')
    if last < first:
        raise ValueError('结束日期不能早于开始日期')
    if (last - first).days > 3652:
        raise ValueError('查询范围不能超过10年')
    return first.isoformat(), (last + timedelta(days=1)).isoformat()


def list_feedback(c, user, *, start='', end='', all_dates=False, status='', search='', page=1, page_size=30):
    start, end = _feedback_window(start, end, all_dates)
    if status and status not in FEEDBACK_STATUS:
        raise ValueError('反馈状态不正确')
    page, page_size = int(page), int(page_size)
    if page < 1 or page > 100000 or page_size < 1 or page_size > 100:
        raise ValueError('分页参数不正确')
    scope, params = [], []
    if user.get('role') != '管理员':
        scope.append('user_id=?')
        params.append(user['id'])
    if start and end:
        scope.append('updated_at>=? AND updated_at<?')
        params.extend([start, end])
    term = (search or '').strip()
    if term:
        scope.append("(instr(lower(json_extract(payload,'$.title')),lower(?))>0 OR instr(lower(json_extract(payload,'$.body')),lower(?))>0 OR instr(lower(json_extract(payload,'$.user_name')),lower(?))>0)")
        params.extend([term, term, term])
    where = ' AND '.join(scope) if scope else '1=1'
    status_filter = [where]
    status_params = list(params)
    if status:
        status_filter.append("json_extract(payload,'$.status')=?")
        status_params.append(status)
    status_where = ' AND '.join(status_filter)
    total = c.execute('SELECT COUNT(*) FROM feedback_tickets WHERE ' + status_where, status_params).fetchone()[0]
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    summary = c.execute("SELECT COALESCE(SUM(json_extract(payload,'$.status')='open'),0),COALESCE(SUM(json_extract(payload,'$.status')='replied'),0),COALESCE(SUM(json_extract(payload,'$.status')='closed'),0),COALESCE(MAX(updated_at),'') FROM feedback_tickets WHERE " + where, params).fetchone()
    records = c.execute('SELECT payload FROM feedback_tickets WHERE ' + status_where + ' ORDER BY updated_at DESC,rowid DESC LIMIT ? OFFSET ?', status_params + [page_size, (page - 1) * page_size]).fetchall()
    return {'tickets': [_ticket_view(json.loads(row[0])) for row in records], 'can_manage': user.get('role') == '管理员',
            'categories': list(FEEDBACK_CATEGORIES), 'total': total, 'pages': pages, 'page': page, 'page_size': page_size,
            'range': {'start': start, 'end': (datetime.fromisoformat(end).date() - timedelta(days=1)).isoformat() if end else '', 'all': bool(all_dates)},
            'summary': {'open': summary[0], 'replied': summary[1], 'closed': summary[2], 'latest': summary[3]},
            'counts': {'feedback_open': _feedback_open_count(c, user)}}


def create_feedback(c, user, body, now, audit):
    key = text(body.get('request_key'), '提交编号', 100)
    saved = c.execute('SELECT payload FROM feedback_tickets WHERE request_key=?', (key,)).fetchone()
    if saved:
        value = json.loads(saved[0])
        if value.get('user_id') != user['id']:
            raise auth.AuthError(403, '提交编号已由其他账号使用，请重新提交')
        if value.get('request_fingerprint') != fingerprint(body):
            raise ValueError('提交编号已用于其他反馈')
        return _ticket_view(value)
    category = body.get('category')
    if category not in FEEDBACK_CATEGORIES:
        raise ValueError('请选择问题类型')
    title = text(body.get('title'), '问题标题', 120)
    if len(title) < 2:
        raise ValueError('问题标题至少2个字')
    message = text(body.get('body'), '问题描述', 4000)
    if len(message) < 4:
        raise ValueError('问题描述至少4个字')
    stamp = now()
    ticket_id = 'FB-' + secrets.token_hex(8).upper()
    payload = {'id': ticket_id, 'category': category, 'title': title, 'body': message, 'status': 'open',
               'user_id': user['id'], 'user_name': user.get('display_name', ''), 'user_role': user.get('role', ''),
               'created_at': stamp, 'updated_at': stamp, 'version': 1, 'replies': [], 'request_fingerprint': fingerprint(body)}
    c.execute('INSERT INTO feedback_tickets(id,request_key,user_id,created_at,updated_at,payload) VALUES(?,?,?,?,?,?)',
              (ticket_id, key, user['id'], stamp, stamp, dump(payload)))
    notify(c, _admin_ids(c), 'feedback', '新的问题反馈', user.get('display_name', '') + '：' + title, page='feedback', entity_id=ticket_id, actor_name=user.get('display_name', ''))
    audit(c, user['role'], '提交问题反馈', ticket_id, None, {'category': category, 'title': title})
    return _ticket_view(payload)


def reply_feedback(c, user, body, now, audit):
    ticket_id = text(body.get('id'), '反馈编号', 80)
    row = c.execute('SELECT payload FROM feedback_tickets WHERE id=?', (ticket_id,)).fetchone()
    if not row:
        raise ValueError('反馈不存在或已删除')
    old = json.loads(row[0])
    is_admin = user.get('role') == '管理员'
    if not is_admin and old.get('user_id') != user['id']:
        raise auth.AuthError(403, '只能查看和回复自己的反馈')
    if type(body.get('version')) is not int or old.get('version') != body['version']:
        raise ValueError('反馈已被更新，请刷新后重试')
    message = body.get('body')
    message = text(message, '回复内容', 2000, False) if message not in (None, '') else ''
    if not message and not is_admin:
        raise ValueError('请填写回复内容')
    requested = body.get('status')
    if is_admin:
        status = requested or ('replied' if message else old.get('status', 'open'))
        if status not in FEEDBACK_STATUS:
            raise ValueError('反馈状态无效')
    else:
        status = 'open'
    stamp = now()
    replies = list(old.get('replies', []))
    if message:
        replies.append({'id': 'FR-' + secrets.token_hex(6).upper(), 'user_id': user['id'], 'user_name': user.get('display_name', ''),
                        'role': user.get('role', ''), 'body': message, 'at': stamp, 'status': status})
    payload = {**old, 'replies': replies, 'status': status, 'updated_at': stamp, 'version': int(old.get('version', 1)) + 1}
    c.execute('UPDATE feedback_tickets SET payload=?,updated_at=? WHERE id=?', (dump(payload), stamp, ticket_id))
    if is_admin:
        if old.get('user_id') != user['id']:
            notify(c, [old['user_id']], 'feedback', '问题反馈有新回复', user.get('display_name', '') + '：' + (message[:120] if message else '状态更新为' + {'open': '待处理', 'replied': '已回复', 'closed': '已关闭'}.get(payload['status'], payload['status'])),
                   page='feedback', entity_id=ticket_id, actor_name=user.get('display_name', ''))
    else:
        notify(c, _admin_ids(c), 'feedback', '问题反馈有新跟进', user.get('display_name', '') + '：' + message[:120],
               page='feedback', entity_id=ticket_id, actor_name=user.get('display_name', ''))
    audit(c, user['role'], '回复问题反馈' if is_admin else '跟进问题反馈', ticket_id, old, payload)
    return _ticket_view(payload)
