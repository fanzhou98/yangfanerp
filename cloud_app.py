"""WSGI boundary for the existing ERP routes; one process and one SQLite DB.

Waitress owns HTTP parsing, connection limits and worker threads. The legacy
handler is used only to dispatch already-parsed requests, never as a TCP server.
"""
from email.message import Message
from contextlib import closing
from http import HTTPStatus
import io
import ipaddress
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import server
import migrations


def validate_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.path or parsed.query or parsed.fragment or
            parsed.netloc != parsed.netloc.lower()):
        raise ValueError('ERP_PUBLIC_ORIGIN 必须为 HTTPS 站点地址，不带路径或末尾斜杠')
    # Validate port eagerly, rather than failing during a request.
    parsed.port
    if any(ch.isspace() for ch in value):
        raise ValueError('站点地址不能包含空白字符')
    return value


class Request(server.Handler):
    def __init__(self, environ, origin):
        self.path = environ.get('PATH_INFO', '/')
        if environ.get('QUERY_STRING'):
            self.path += '?' + environ['QUERY_STRING']
        self.command = environ['REQUEST_METHOD']
        self.headers = Message()
        for name, value in environ.items():
            if name.startswith('HTTP_'):
                self.headers[name[5:].replace('_', '-')] = value
        for name in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            if environ.get(name):
                self.headers[name.replace('_', '-')] = environ[name]
        self.rfile = environ['wsgi.input']
        self.wfile = io.BytesIO()
        self.client_address = (environ.get('REMOTE_ADDR', ''), 0)
        self.server = SimpleNamespace(test_pilot=False)
        self.origin = origin
        self.scheme = environ.get('wsgi.url_scheme', 'http')
        self.status = 500
        self.response_headers = []

    def check_host(self):
        host = self.headers.get('Host', '')
        # Local probes contain no business data; never expose this exception
        # through nginx, whose Host check accepts only the public site.
        try:
            loopback = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            raise ValueError('客户端地址无效') from None
        if (loopback and self.path == '/api/health' and
                host in ('127.0.0.1:8765', 'localhost:8765')):
            return
        if self.scheme != 'https' or host != urlsplit(self.origin).netloc:
            raise server.auth.AccessRefused('请通过指定的 HTTPS 地址访问系统')
        origin = self.headers.get('Origin')
        if origin is not None and origin != self.origin:
            raise server.auth.AccessRefused('请求来源与系统地址不一致')

    def set_auth_cookies(self, token='', csrf='', max_age=0):
        self.extra_cookies = [
            f'erp_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}; Secure',
            f'erp_csrf={csrf}; Path=/; SameSite=Strict; Max-Age={max_age}; Secure',
        ]

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, key, value):
        self.response_headers.append((key, str(value)))

    def end_headers(self):
        pass


def create_application(database, origin):
    origin = validate_origin(origin)
    database = Path(database).resolve()
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as c:
        c.execute('PRAGMA query_only=ON')
        migrations.assert_current(c)
    server.DB = database

    def application(environ, start_response):
        request = Request(environ, origin)
        method = environ['REQUEST_METHOD']
        if method in ('GET', 'HEAD'):
            request.do_GET()
        elif method == 'POST':
            request.do_POST()
        else:
            request.send_header('Allow', 'GET, HEAD, POST')
            request.respond({'error': '不支持的请求方法'}, 405)
        start_response(f'{request.status} {HTTPStatus(request.status).phrase}', request.response_headers)
        return [b'' if method == 'HEAD' else request.wfile.getvalue()]

    return application


def main():
    from waitress import serve
    os.umask(0o077)
    origin = validate_origin(os.environ['ERP_PUBLIC_ORIGIN'])
    database = Path(os.environ['ERP_DATABASE']).resolve()
    server.DB = database
    # Install/upgrade verifies migrations on a candidate copy before switching.
    # The live worker deliberately never migrates the business database.
    if not database.is_file():
        raise RuntimeError('数据库未初始化；请先执行部署安装或升级步骤')
    app = create_application(database, origin)
    serve(app, listen='127.0.0.1:8765', threads=4,
          connection_limit=64, channel_timeout=30,
          max_request_body_size=1048576, max_request_header_size=32768,
          trusted_proxy='127.0.0.1', trusted_proxy_count=1,
          trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto'},
          clear_untrusted_proxy_headers=True, expose_tracebacks=False,
          ident='ERP')


if __name__ == '__main__':
    main()
