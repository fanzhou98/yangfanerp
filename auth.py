"""Account and session primitives for the ERP, using only the Python standard library.

The HTTP layer owns transactions, secure cookies, same-origin checks and route
authorization. In particular it must COMMIT failed-login events before returning
an AuthError: rolling the transaction back also rolls rate limiting back.
All timestamps are integer UTC Unix seconds. No function commits a transaction.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3

ROLES = ('管理员', '库管', '会计', '出纳', '老板', '厂长', '物流负责人', '行政负责人', '司机')
SESSION_TTL = 8 * 60 * 60
SESSION_IDLE_TTL = 30 * 60
REMEMBER_TTL = 7 * 24 * 60 * 60
MAX_SESSION_TTL = 30 * 24 * 60 * 60
RATE_WINDOW = 15 * 60
USERNAME_ATTEMPTS = 5
IP_ATTEMPTS = 30
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 3
_USERNAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{2,31}\Z', re.ASCII)
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z', re.ASCII)
# Unknown users run the same KDF as real users; this is not a usable account.
_DUMMY_SALT = bytes.fromhex('71bc95494a6791c803d9f1b805cc7da8')
_LOGIN_ERROR = '账号或密码不正确，或账号不可用'
_PUBLIC_COLUMNS = ('id', 'username', 'display_name', 'role', 'active',
                   'must_change_password', 'version', 'created_at', 'updated_at')


class AuthError(ValueError):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class AccessRefused(ValueError):
    """访问被出入口规则拒绝（Host/来源/局域网限制）：GET 回 403，提交请求按参数错误回 400。"""


def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'auth')



def _row(cursor):
    result = cursor.fetchone()
    return dict(zip((d[0] for d in cursor.description), result)) if result else None


def _user(c, user_id):
    return _row(c.execute('SELECT * FROM auth_users WHERE id=?', (user_id,)))


def public_user(user):
    return {key: bool(user[key]) if key in ('active', 'must_change_password')
            else user[key] for key in _PUBLIC_COLUMNS}


def _username(value):
    if not isinstance(value, str) or not _USERNAME.fullmatch(value):
        raise AuthError(400, '账号须为 3—32 位英文字母、数字、点、下划线或短横线，并以字母或数字开头')
    return value.lower()


def _display_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise AuthError(400, '请填写姓名，最多 80 字')
    return value.strip()


def _role(value):
    if value not in ROLES:
        raise AuthError(400, '请选择有效岗位')
    return value


def _password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128 or not value.strip():
        raise AuthError(400, '密码须为 12—128 个字符，不能全为空白')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise AuthError(400, '密码包含无效字符') from None
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise AuthError(400, f'{label}须为是或否')
    return value


def _now(value):
    if type(value) is not int or value < 0:
        raise ValueError('now must be a nonnegative integer UTC epoch')
    return value


def _version(value):
    if type(value) is not int or value < 1:
        raise AuthError(409, '用户资料已有变化，请刷新后重试')
    return value


def _derive(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=SCRYPT_N,
                          r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=32)


def hash_password(password):
    password = _password(password)
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt)
    return f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}'


def verify_password(password, encoded):
    """Constant-time digest comparison; malformed records fail closed."""
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        _derive('invalid-password-placeholder', _DUMMY_SALT)
        return False
    try:
        password.encode('utf-8')
    except UnicodeEncodeError:
        _derive('invalid-password-placeholder', _DUMMY_SALT)
        return False
    try:
        scheme, n, r, p, salt, expected = encoded.split('$')
        if (scheme, int(n), int(r), int(p)) != ('scrypt', SCRYPT_N, SCRYPT_R, SCRYPT_P):
            raise ValueError()
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        _derive(password, _DUMMY_SALT)
        return False
    return hmac.compare_digest(_derive(password, salt), expected)


def _hash_token(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        return None
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _event(c, action, entity, now, actor=None, before=None, after=None, audit=None):
    # Only explicit public projections and non-secret scalar fields may enter here.
    c.execute('INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)',
              (now, action, actor['id'] if actor else None, entity,
               json.dumps({'actor': public_user(actor) if actor else None,
                           'before': before, 'after': after}, ensure_ascii=False, separators=(',', ':'))))
    if audit:
        audit(c, action, entity, before, after)


def _admin(c, actor):
    current = _user(c, actor.get('id')) if isinstance(actor, dict) else None
    if not current or not current['active'] or current['role'] != '管理员':
        raise AuthError(403, '仅管理员可以管理用户')
    if current['must_change_password']:
        raise AuthError(403, '请先修改初始密码')
    return current


def _cas(c, user_id, expected):
    user = _user(c, user_id)
    if not user:
        raise AuthError(404, '用户不存在')
    if user['version'] != _version(expected):
        raise AuthError(409, '用户资料已有变化，请刷新后重试')
    return user


def create_initial_admin(c, username, display_name, password, now, audit=None):
    """One-shot local CLI bootstrap. Caller should use BEGIN IMMEDIATE."""
    now = _now(now)
    username, display_name = _username(username), _display_name(display_name)
    password_hash = hash_password(password)
    if c.execute('SELECT 1 FROM auth_users LIMIT 1').fetchone():
        raise AuthError(409, '已有用户，不能再次初始化管理员')
    uid = 'U-' + secrets.token_hex(8)
    c.execute('INSERT INTO auth_users(id,username,display_name,role,password_hash,active,must_change_password,version,created_at,updated_at) VALUES(?,?,?,?,?,1,0,1,?,?)',
              (uid, username, display_name, '管理员', password_hash, now, now))
    result = public_user(_user(c, uid))
    _event(c, 'auth.bootstrap', uid, now, after=result, audit=audit)
    return result


def list_users(c):
    cursor = c.execute('SELECT * FROM auth_users ORDER BY created_at,id')
    names = [d[0] for d in cursor.description]
    users=[public_user(dict(zip(names,row))) for row in cursor]
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='driver_accounts'").fetchone():
        links=dict(c.execute('SELECT user_id,driver_id FROM driver_accounts'))
        for u in users:
            if u['role']=='司机':u['driver_id']=links.get(u['id'],'')
    return users


def sync_driver_account(c,user,body):
    if user['role']!='司机':return
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='driver_accounts'").fetchone():
        import migrations
        migrations.ensure(c,'driver')
    linked=c.execute('SELECT driver_id FROM driver_accounts WHERE user_id=?',(user['id'],)).fetchone()
    driver_id=body.get('driver_id') or (linked[0] if linked else '')
    driver=c.execute('SELECT * FROM delivery_drivers WHERE id=?',(driver_id,)).fetchone() if driver_id else c.execute('SELECT * FROM delivery_drivers WHERE name=?',(user['display_name'],)).fetchone()
    if driver_id and not driver:raise AuthError(400,'选择的司机档案不存在')
    if driver and not driver['active']:raise AuthError(400,'司机档案已停用，请先在车辆司机档案恢复')
    if not driver:
        driver_id='D-'+secrets.token_hex(6);c.execute('INSERT INTO delivery_drivers(id,name) VALUES(?,?)',(driver_id,user['display_name']))
    else:driver_id=driver['id']
    other=c.execute('SELECT user_id FROM driver_accounts WHERE driver_id=? AND user_id<>?',(driver_id,user['id'])).fetchone()
    if other:raise AuthError(409,'该司机已有绑定账号，请编辑原账号')
    c.execute('INSERT INTO driver_accounts VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET driver_id=excluded.driver_id',(user['id'],driver_id))
    user['driver_id']=driver_id


def create_user(c, actor, body, now, audit=None):
    actor, now = _admin(c, actor), _now(now)
    username, name = _username(body.get('username')), _display_name(body.get('display_name'))
    role = _role(body.get('role'))
    active = _boolean(body.get('active', True), '启用状态')
    password_hash = hash_password(body.get('password'))
    uid = 'U-' + secrets.token_hex(8)
    try:
        c.execute('INSERT INTO auth_users(id,username,display_name,role,password_hash,active,must_change_password,version,created_at,updated_at) VALUES(?,?,?,?,?,?,1,1,?,?)',
                  (uid, username, name, role, password_hash, int(active), now, now))
    except sqlite3.IntegrityError:
        raise AuthError(409, '账号已存在，请换一个账号') from None
    result = public_user(_user(c, uid))
    sync_driver_account(c,result,body)
    _event(c, 'auth.user.create', uid, now, actor, after=result, audit=audit)
    return result


def update_user(c, actor, user_id, body, now, audit=None):
    actor, now = _admin(c, actor), _now(now)
    old = _cas(c, user_id, body.get('version'))
    username = _username(body.get('username', old['username']))
    name = _display_name(body.get('display_name', old['display_name']))
    role = _role(body.get('role', old['role']))
    active = _boolean(body.get('active', bool(old['active'])), '启用状态')
    if old['active'] and old['role'] == '管理员' and (not active or role != '管理员'):
        remaining = c.execute("SELECT count(*) FROM auth_users WHERE active=1 AND role='管理员' AND id<>?", (user_id,)).fetchone()[0]
        if not remaining:
            raise AuthError(409, '不能停用或降级最后一位启用的管理员')
    try:
        changed = c.execute('UPDATE auth_users SET username=?,display_name=?,role=?,active=?,version=version+1,updated_at=? WHERE id=? AND version=?',
                            (username, name, role, int(active), now, user_id, old['version'])).rowcount
    except sqlite3.IntegrityError:
        raise AuthError(409, '账号已存在，请换一个账号') from None
    if changed != 1:
        raise AuthError(409, '用户资料已有变化，请刷新后重试')
    c.execute('DELETE FROM auth_sessions WHERE user_id=?', (user_id,))
    result = public_user(_user(c, user_id))
    sync_driver_account(c,result,body)
    _event(c, 'auth.user.update', user_id, now, actor, public_user(old), result, audit)
    return result


def reset_password(c, actor, user_id, new_password, expected_version, now, audit=None):
    actor, now = _admin(c, actor), _now(now)
    old = _cas(c, user_id, expected_version)
    password_hash = hash_password(new_password)
    if actor['id'] == user_id:
        raise AuthError(400, '修改自己的密码请使用修改密码功能并验证当前密码')
    changed = c.execute('UPDATE auth_users SET password_hash=?,must_change_password=1,version=version+1,updated_at=? WHERE id=? AND version=?',
                        (password_hash, now, user_id, old['version'])).rowcount
    if changed != 1:
        raise AuthError(409, '用户资料已有变化，请刷新后重试')
    c.execute('DELETE FROM auth_sessions WHERE user_id=?', (user_id,))
    result = public_user(_user(c, user_id))
    _event(c, 'auth.password.reset', user_id, now, actor, public_user(old), result, audit)
    return result


def change_password(c, actor, current_password, new_password, now, audit=None):
    now = _now(now)
    current = _user(c, actor.get('id')) if isinstance(actor, dict) else None
    if not current or not current['active']:
        raise AuthError(401, '登录已失效，请重新登录')
    if not verify_password(current_password, current['password_hash']):
        _event(c, 'auth.password.change_failed', current['id'], now, current, audit=audit)
        raise AuthError(400, '当前密码不正确')
    _password(new_password)
    if hmac.compare_digest(current_password.encode('utf-8'), new_password.encode('utf-8')):
        raise AuthError(400, '新密码不能与当前密码相同')
    password_hash = hash_password(new_password)
    changed = c.execute('UPDATE auth_users SET password_hash=?,must_change_password=0,version=version+1,updated_at=? WHERE id=? AND version=?',
                        (password_hash, now, current['id'], current['version'])).rowcount
    if changed != 1:
        raise AuthError(409, '用户资料已有变化，请重新登录')
    c.execute('DELETE FROM auth_sessions WHERE user_id=?', (current['id'],))
    result = public_user(_user(c, current['id']))
    _event(c, 'auth.password.change', current['id'], now, current, public_user(current), result, audit)
    return result


def _buckets(username, ip):
    name = username[:256].strip().lower() if isinstance(username, str) else ''
    address = ip[:256] if isinstance(ip, str) else ''
    return [('user:' + hashlib.sha256(name.encode('utf-8')).hexdigest(), USERNAME_ATTEMPTS),
            ('ip:' + hashlib.sha256(address.encode('utf-8')).hexdigest(), IP_ATTEMPTS)]


def login(c, username, password, ip, now, session_ttl=SESSION_TTL, audit=None):
    now = _now(now)
    if type(session_ttl) is not int or not 60 <= session_ttl <= MAX_SESSION_TTL:
        raise ValueError('session_ttl must be 60..2592000 seconds')
    buckets = _buckets(username, ip)
    origin = {'ip': ip[:64] if isinstance(ip, str) else ''}
    # Retain at most one active window per key; pruning prevents unbounded logs
    # of stale attack identifiers in the rate-limit table.
    c.execute('DELETE FROM auth_login_limits WHERE window_started_at<=? AND blocked_until<=?', (now - RATE_WINDOW, now))
    for bucket, _ in buckets:
        limited = _row(c.execute('SELECT * FROM auth_login_limits WHERE bucket=?', (bucket,)))
        if limited and limited['blocked_until'] > now:
            _event(c, 'auth.login.rate_limited', 'login', now, after=origin, audit=audit)
            raise AuthError(429, '登录尝试过多，请 15 分钟后重试')
    normalized = username.strip().lower() if isinstance(username, str) and len(username) <= 32 else ''
    user = _row(c.execute('SELECT * FROM auth_users WHERE username=?', (normalized,))) if _USERNAME.fullmatch(normalized) else None
    encoded = user['password_hash'] if user else ''
    valid = verify_password(password, encoded)
    if not user or not valid or not user['active']:
        for bucket, threshold in buckets:
            c.execute('INSERT INTO auth_login_limits(bucket,window_started_at,failures,blocked_until) VALUES(?,?,1,0) ON CONFLICT(bucket) DO UPDATE SET failures=failures+1', (bucket, now))
            c.execute('UPDATE auth_login_limits SET blocked_until=? WHERE bucket=? AND failures>=?', (now + RATE_WINDOW, bucket, threshold))
        _event(c, 'auth.login.failed', 'login', now, after=origin, audit=audit)
        raise AuthError(401, _LOGIN_ERROR)
    # Clear only the account bucket; successes may not erase an IP's spraying
    # counter and thus allow unlimited guesses against other accounts.
    c.execute('DELETE FROM auth_login_limits WHERE bucket=?', (buckets[0][0],))
    c.execute('DELETE FROM auth_sessions WHERE expires_at<=?', (now,))
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    sid = 'S-' + secrets.token_hex(16)
    expires_at = now + session_ttl
    c.execute('INSERT INTO auth_sessions(id,token_hash,csrf_hash,user_id,user_version,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',
              (sid, _hash_token(token), _hash_token(csrf), user['id'], user['version'], now, expires_at))
    c.execute('INSERT INTO auth_session_activity VALUES(?,?)', (sid, now))
    _event(c, 'auth.login.succeeded', user['id'], now, user, after=origin, audit=audit)
    return {'token': token, 'csrf_token': csrf, 'expires_at': expires_at, 'user': public_user(user),
            'session': session_status(authenticate(c, token, now), now)}


def authenticate(c, token, now):
    now = _now(now)
    token_hash = _hash_token(token)
    if not token_hash:
        raise AuthError(401, '请先登录')
    session = _row(c.execute('SELECT * FROM auth_sessions WHERE token_hash=?', (token_hash,)))
    if not session or session['expires_at'] <= now:
        raise AuthError(401, '登录已失效，请重新登录')
    activity = c.execute('SELECT last_activity FROM auth_session_activity WHERE session_id=?', (session['id'],)).fetchone()
    last_activity = activity[0] if activity else session['created_at']
    long_session = session['expires_at'] - session['created_at'] > SESSION_TTL
    idle_limit = session['expires_at'] - session['created_at'] if long_session else SESSION_IDLE_TTL
    if last_activity + idle_limit <= now:
        raise AuthError(401, '登录已超时，请重新登录')
    user = _user(c, session['user_id'])
    if not user or not user['active'] or user['version'] != session['user_version']:
        raise AuthError(401, '登录已失效，请重新登录')
    return {'user': public_user(user), 'session_id': session['id'],
            'created_at': session['created_at'], 'expires_at': session['expires_at'],
            'last_activity': last_activity,
            'csrf_hash': session['csrf_hash']}


def session_status(session, now):
    long_session = session['expires_at'] - session['created_at'] > SESSION_TTL
    idle = session['expires_at'] - session['created_at'] if long_session else SESSION_IDLE_TTL
    return {key: session[key] for key in ('session_id', 'expires_at', 'last_activity')} | {
        'idle_timeout_seconds': idle, 'server_time': now}


def record_activity(c, token, now):
    """Only explicit user activity renews idle time; reads and autosave do not."""
    session = authenticate(c, token, now)
    c.execute('INSERT INTO auth_session_activity VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET last_activity=MAX(last_activity,excluded.last_activity)',
              (session['session_id'], now))
    session['last_activity'] = now
    return session_status(session, now)


def verify_csrf(session, raw_csrf):
    supplied = _hash_token(raw_csrf)
    expected = session.get('csrf_hash', '') if isinstance(session, dict) else ''
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        raise AuthError(403, '安全校验失败，请刷新页面后重试')
    return True


def logout(c, token, now, audit=None):
    now = _now(now)
    token_hash = _hash_token(token)
    if not token_hash:
        return {'ok': True}
    session = _row(c.execute('SELECT * FROM auth_sessions WHERE token_hash=?', (token_hash,)))
    if session:
        user = _user(c, session['user_id'])
        c.execute('DELETE FROM auth_sessions WHERE id=?', (session['id'],))
        _event(c, 'auth.logout', session['user_id'], now, user, audit=audit)
    return {'ok': True}
