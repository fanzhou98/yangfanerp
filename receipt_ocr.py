"""收款凭据截图识别：图片校验、OCR 提供方、字段解析与凭据存储。

只使用 Python 标准库。图片先做魔数、尺寸和元数据清洗，再交给
本机 macOS Vision 或管理员配置的 OpenAI 兼容视觉模型。识别结果
只是建议值，收款登记必须由出纳核对原图后确认。
"""

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import signal
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

TZ = timezone(timedelta(hours=8))
MAX_IMAGE_BYTES = 640_000
MAX_UPLOAD_TEXT = 900_000
MAX_PIXELS = 40_000_000
MAX_RAW_TEXT = 12_000
RATE_LIMIT_PER_HOUR = 100
DEFAULT_TIMEOUT = 35
DEFAULT_CONFIG = {'provider': 'auto', 'base_url': '', 'model': '', 'timeout': DEFAULT_TIMEOUT}
PROVIDER_LABELS = {'auto': '自动选择', 'macos': '本机 macOS Vision', 'openai': '云端视觉模型', 'off': '关闭识别'}
EMPTY_FIELDS = {
    'amount_cents': None, 'amount_text': None, 'occurred_at': None, 'time_precision': None,
    'transaction_no': None, 'payer': None, 'payee': None, 'method': None, 'direction': 'in',
    'field_confidence': {}, 'sources': {},
}
MONEY_LABEL_TEXT = '转账金额|收款金额|付款金额|交易金额|支付金额|到账金额|入账金额|实付金额|实收金额|成交金额|订单金额|总金额|合计|总计|金额'
MONEY_LABEL_RE = re.compile('(?:' + MONEY_LABEL_TEXT + ')')
MONEY_RE = re.compile('(?:' + MONEY_LABEL_TEXT + ')\\s*[:：]?\\s*[¥￥]?\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)')
CURRENCY_RE = re.compile('[¥￥]\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)')
RMB_RE = re.compile('人民币\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)\\s*元?')
STANDALONE_RE = re.compile('^\\s*[+\\-]?\\s*([0-9][0-9,]*\\.[0-9]{2})\\s*$')
DATE_RE = re.compile('(20\\d{2})\\s*[-/年.]\\s*(\\d{1,2})\\s*[-/月.]\\s*(\\d{1,2})\\s*日?(?:\\s*(\\d{1,2})\\s*[:：]\\s*(\\d{2})(?:\\s*[:：]\\s*(\\d{2}))?)?')
TIME_LABEL_RE = re.compile('转账时间|交易时间|支付时间|创建时间|付款时间|到账时间|交易日期|记账日期|入账日期|转账日期|支付日期|日期')
TX_LABEL_TEXT = '转账单号|交易单号|交易流水号|银行流水号|业务流水号|商户单号|订单编号|订单号|凭证号|交易号|参考号|回单编号|流水号'
TX_LABEL_RE = re.compile(TX_LABEL_TEXT)
TX_RE = re.compile('(?:' + TX_LABEL_TEXT + ')\\s*[:：]?\\s*([A-Za-z0-9][A-Za-z0-9\\-_]{5,63})')
PAYER_RE = re.compile('付款方(?!式)|付款人|汇款人|付款单位|转出方|转出人|对方户名')
PAYEE_RE = re.compile('收款方|收款人|收款单位|商户名称|商户简称|商家名称|收款商户|对方名称|转入方')
BALANCE_RE = re.compile('余额|零钱|可用|手续费|限额|额度|积分|优惠|抵扣|应还|欠款')
OUT_RE = re.compile('支付成功|交易成功|付款成功|已付款|已支付|转账给|支出|转出|付款给|扣款|扣费|消费')
SIGN_OUT_RE = re.compile(r'(?m)^\s*[-−—–]\s*(?:[¥￥]\s*)?\d')
SIGN_IN_RE = re.compile(r'(?m)^\s*\+\s*(?:[¥￥]\s*)?\d')
IN_RE = re.compile('收款成功|已收款|收款到账|到账|入账|收入|转入')
GENERIC_PARTY_RE = re.compile('^(?:微信支付|微信|支付宝|零钱|银行卡|银行|现金|商户|个人)$')

_VISION_LOCK = threading.Lock()
_OCR_SLOTS = threading.BoundedSemaphore(2)
VISION_SWIFT = r'''
import Foundation
import AppKit
import Vision

let args = CommandLine.arguments
guard args.count >= 2 else { fputs("missing image path\n", stderr); exit(2) }
guard let image = NSImage(contentsOfFile: args[1]),
      let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cg = bitmap.cgImage else { fputs("cannot decode image\n", stderr); exit(3) }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([request]) } catch { fputs("vision failed\n", stderr); exit(4) }
var rows: [[String: Any]] = []
for observation in request.results ?? [] {
    guard let top = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox
    rows.append([
        "text": top.string,
        "confidence": Double(top.confidence),
        "x": Double(box.minX),
        "y": Double(box.minY),
        "w": Double(box.width),
        "h": Double(box.height),
    ])
}
let data = try JSONSerialization.data(withJSONObject: rows, options: [])
if let text = String(data: data, encoding: .utf8) { print(text) }
'''


class EvidenceError(ValueError):
    pass


def _empty_fields():
    data = dict(EMPTY_FIELDS)
    data['field_confidence'] = {}
    data['sources'] = {}
    return data


def _now():
    return datetime.now(TZ)


def _iso(dt=None):
    return (dt or _now()).isoformat(timespec='seconds')


def _key_path(db_path):
    return Path(db_path).parent / 'receipt_ocr.key'


def _read_key(db_path):
    try:
        value = _key_path(db_path).read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        return ''
    return value


def _write_key(db_path, key):
    path = _key_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(key, encoding='utf-8')
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _delete_key(db_path):
    try:
        _key_path(db_path).unlink()
    except OSError:
        pass


def _key_hint(key):
    if not key:
        return ''
    return ('*' * min(8, max(2, len(key) - 4))) + key[-4:]


def _validate_remote_url(url):
    if not url or len(url) > 300:
        raise EvidenceError('云端识别 Base URL 长度不正确')
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ('https', 'http'):
        raise EvidenceError('云端识别 Base URL 必须以 https:// 开头')
    if parts.username or parts.password:
        raise EvidenceError('Base URL 不能包含账号密码')
    if not parts.hostname:
        raise EvidenceError('云端识别 Base URL 缺少主机名')
    if parts.scheme == 'http' and parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise EvidenceError('云端识别只允许 https 地址；本机测试可使用 127.0.0.1')
    return url.rstrip('/')


def _remote_ready(cfg):
    try:
        _validate_remote_url(str(cfg.get('base_url') or ''))
    except EvidenceError:
        return False
    return bool(cfg.get('model') and cfg.get('api_key'))


def _effective_engine(cfg):
    provider = cfg.get('provider') or 'auto'
    if provider == 'off':
        return 'off'
    if provider == 'macos':
        return 'macos'
    if provider == 'openai':
        return 'openai' if _remote_ready(cfg) else 'off'
    if macos_available():
        return 'macos'
    if _remote_ready(cfg):
        return 'openai'
    return 'off'


def macos_available():
    return sys.platform == 'darwin' and bool(shutil.which('swiftc'))


def _public_config(cfg):
    provider = cfg.get('provider') or 'auto'
    key = cfg.get('api_key') or ''
    macos_ok = macos_available()
    remote_ok = _remote_ready(cfg)
    engine = _effective_engine(cfg)
    available = engine != 'off'
    if engine == 'macos':
        label = '本机 macOS Vision'
        message = '本机识别可用，截图不会离开这台电脑。'
    elif engine == 'openai':
        label = '云端视觉模型 · ' + str(cfg.get('model') or '')
        message = '云端识别可用；截图会发送到所配置的模型服务。'
    else:
        label = '未启用'
        if provider == 'off':
            message = '识别服务已关闭，仍可保存截图后手工填写。'
        elif provider == 'macos' and not macos_ok:
            message = '当前服务器不是 macOS 或缺少 swiftc，无法使用本机识别；请配置云端视觉模型。'
        elif provider == 'openai':
            if not cfg.get('base_url') or not cfg.get('model'):
                message = '请填写云端识别的 Base URL 和模型名称。'
            elif not key:
                message = '请填写云端识别服务的 API Key。'
            else:
                message = '云端识别配置不完整，请检查 Base URL 是否以 https:// 开头。'
        elif provider == 'auto' and not macos_ok:
            message = '本机识别不可用，且尚未配置云端视觉模型。'
        else:
            message = '识别服务不可用，请管理员检查设置。'
    return {
        'provider': provider, 'base_url': str(cfg.get('base_url') or ''),
        'model': str(cfg.get('model') or ''), 'timeout': int(cfg.get('timeout') or DEFAULT_TIMEOUT),
        'key_configured': bool(key), 'key_hint': _key_hint(key), 'macos_available': macos_ok,
        'available': available, 'engine': engine, 'engine_label': label, 'message': message,
    }


def settings(c, db_path):
    cfg = dict(DEFAULT_CONFIG)
    row = c.execute("SELECT value FROM meta WHERE key='receipt_ocr_settings'").fetchone()
    if row:
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError):
            data = {}
        if isinstance(data, dict):
            if data.get('provider') in PROVIDER_LABELS:
                cfg['provider'] = data['provider']
            if isinstance(data.get('base_url'), str):
                cfg['base_url'] = data['base_url'][:300]
            if isinstance(data.get('model'), str):
                cfg['model'] = data['model'][:120]
            try:
                timeout = int(data.get('timeout'))
                if 10 <= timeout <= 90:
                    cfg['timeout'] = timeout
            except (TypeError, ValueError):
                pass
    cfg['api_key'] = _read_key(db_path)
    return cfg


def settings_public(c, db_path):
    return _public_config(settings(c, db_path))


def save_settings(c, payload, db_path):
    if not isinstance(payload, dict):
        raise EvidenceError('识别配置无效')
    provider = str(payload.get('provider') or 'auto').strip()
    if provider not in PROVIDER_LABELS:
        raise EvidenceError('识别方式无效')
    base_url = str(payload.get('base_url') or '').strip()
    model = str(payload.get('model') or '').strip()
    if len(base_url) > 300 or len(model) > 120:
        raise EvidenceError('Base URL 或模型名称过长')
    if base_url:
        base_url = _validate_remote_url(base_url)
    try:
        timeout = int(payload.get('timeout') or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        raise EvidenceError('识别超时必须是整数秒')
    if not 10 <= timeout <= 90:
        raise EvidenceError('识别超时应在 10 到 90 秒之间')
    existing = _read_key(db_path)
    new_key = payload.get('api_key')
    if new_key is not None:
        new_key = str(new_key).strip()
        if len(new_key) > 400 or any(ch.isspace() for ch in new_key):
            raise EvidenceError('API Key 不能包含空格或换行')
    clear_key = bool(payload.get('clear_key'))
    effective_key = '' if clear_key else (new_key or existing)
    if provider == 'openai' and not (base_url and model and effective_key):
        raise EvidenceError('云端识别需同时填写 Base URL、模型名称和 API Key')
    if clear_key:
        _delete_key(db_path)
    elif new_key:
        _write_key(db_path, new_key)
    cfg = {'provider': provider, 'base_url': base_url, 'model': model, 'timeout': timeout}
    c.execute("INSERT INTO meta(key,value) VALUES('receipt_ocr_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (json.dumps(cfg, ensure_ascii=False),))
    return settings_public(c, db_path)


def can_recognize(actor):
    if not isinstance(actor, dict):
        return False
    if actor.get('role') == '管理员':
        return True
    permissions = actor.get('permissions') or {}
    return 'finance.evidence' in (permissions.get('actions') or [])


def can_view(actor):
    return can_recognize(actor)


def _clean_filename(name):
    name = str(name or '转账截图')[:120]
    name = re.sub(r'[\x00-\x1f/\\]', '_', name).strip()
    return name or '转账截图'


def _to_cents(value):
    text = str(value or '').strip().replace(',', '').replace('¥', '').replace('￥', '').replace('元', '')
    text = re.sub(r'[^\d.\-]', '', text)
    if not text or text.count('.') > 1:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if number <= 0 or number > Decimal('100000000'):
        return None
    if -number.as_tuple().exponent > 2:
        return None
    cents = int((number * 100).to_integral_value(rounding=ROUND_HALF_UP))
    return cents if cents > 0 else None


def _fmt_amount(cents):
    return f'{cents / 100:,.2f}'


def _jpeg_sanitize(data):
    if not data.startswith(b'\xff\xd8'):
        raise EvidenceError('图片格式无效')
    output = bytearray(b'\xff\xd8')
    index = 2
    width = height = None
    saw_scan = False
    while index < len(data) - 1:
        if data[index] != 0xFF:
            raise EvidenceError('图片格式无效')
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker == 0xD9:
            output.extend(data[index:index + 2])
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            output.extend(data[index:index + 2])
            index += 2
            continue
        if index + 4 > len(data):
            raise EvidenceError('图片文件不完整')
        length = int.from_bytes(data[index + 2:index + 4], 'big')
        if length < 2 or index + 2 + length > len(data):
            raise EvidenceError('图片文件不完整')
        if marker == 0xDA:
            output.extend(data[index:])
            saw_scan = True
            break
        if not (marker in (0xE1, 0xFE) or 0xE2 <= marker <= 0xEF):
            output.extend(data[index:index + 2 + length])
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and length >= 7:
            height = int.from_bytes(data[index + 5:index + 7], 'big')
            width = int.from_bytes(data[index + 7:index + 9], 'big')
        index += 2 + length
    if not saw_scan or len(output) < 100:
        raise EvidenceError('图片文件不完整')
    return bytes(output), width, height


def _png_sanitize(data):
    signature = b'\x89PNG\r\n\x1a\n'
    if not data.startswith(signature):
        raise EvidenceError('图片格式无效')
    output = bytearray(signature)
    index = 8
    width = height = None
    saw_header = False
    saw_data = False
    while index + 12 <= len(data):
        length = int.from_bytes(data[index:index + 4], 'big')
        kind = data[index + 4:index + 8]
        end = index + 12 + length
        if end > len(data):
            raise EvidenceError('图片文件不完整')
        if kind == b'IHDR':
            if length < 13:
                raise EvidenceError('图片文件不完整')
            width = int.from_bytes(data[index + 8:index + 12], 'big')
            height = int.from_bytes(data[index + 12:index + 16], 'big')
            saw_header = True
        if kind == b'IDAT':
            saw_data = True
        if kind not in (b'eXIf', b'tEXt', b'zTXt', b'iTXt', b'tIME'):
            output.extend(data[index:end])
        index = end
        if kind == b'IEND':
            break
    if not saw_header or not saw_data:
        raise EvidenceError('图片文件不完整')
    return bytes(output), width, height


def _webp_sanitize(data):
    if len(data) < 20 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        raise EvidenceError('图片格式无效')
    output = bytearray(data[:12])
    index = 12
    width = height = None
    saw_image = False
    while index + 8 <= len(data):
        kind = data[index:index + 4]
        length = int.from_bytes(data[index + 4:index + 8], 'little')
        end = index + 8 + length + (length & 1)
        if end > len(data):
            raise EvidenceError('图片文件不完整')
        if kind not in (b'EXIF', b'XMP '):
            output.extend(data[index:end])
        if kind in (b'VP8 ', b'VP8L'):
            saw_image = True
        if kind == b'VP8X' and length >= 10:
            width = 1 + int.from_bytes(data[index + 12:index + 15], 'little')
            height = 1 + int.from_bytes(data[index + 15:index + 18], 'little')
        elif kind == b'VP8 ' and length >= 10 and data[index + 11:index + 14] == b'\x9d\x01\x2a':
            width = int.from_bytes(data[index + 14:index + 16], 'little') & 0x3fff
            height = int.from_bytes(data[index + 16:index + 18], 'little') & 0x3fff
        elif kind == b'VP8L' and length >= 5 and data[index + 8] == 0x2f:
            bits = int.from_bytes(data[index + 9:index + 13], 'little')
            width = (bits & 0x3fff) + 1
            height = ((bits >> 14) & 0x3fff) + 1
        index = end
    if not saw_image or len(output) < 30:
        raise EvidenceError('图片文件不完整')
    output[4:8] = (len(output) - 8).to_bytes(4, 'little')
    return bytes(output), width, height


def _decode_image(data):
    if data.startswith(b'\xff\xd8'):
        mime = 'image/jpeg'
        clean, width, height = _jpeg_sanitize(data)
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
        clean, width, height = _png_sanitize(data)
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        mime = 'image/webp'
        clean, width, height = _webp_sanitize(data)
    else:
        raise EvidenceError('只支持 JPG、PNG 或 WebP 截图')
    if width and height:
        if width < 40 or height < 40:
            raise EvidenceError('截图尺寸过小，无法识别')
        if width > 20000 or height > 30000 or width * height > MAX_PIXELS:
            raise EvidenceError('截图尺寸过大，请压缩后再试')
    return mime, width, height, clean


def prepare(payload):
    if not isinstance(payload, dict):
        raise EvidenceError('请求内容无效')
    raw = payload.get('image_base64')
    if not isinstance(raw, str):
        raise EvidenceError('请选择要识别的截图')
    raw = raw.strip()
    if raw.startswith('data:'):
        comma = raw.find(',')
        if comma < 0:
            raise EvidenceError('截图编码无效')
        raw = raw[comma + 1:]
    raw = ''.join(raw.split())
    if not raw:
        raise EvidenceError('请选择要识别的截图')
    if len(raw) > MAX_UPLOAD_TEXT:
        raise EvidenceError('截图文件过大，请压缩后再试')
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise EvidenceError('截图编码无效')
    if len(data) > MAX_IMAGE_BYTES:
        raise EvidenceError('截图文件过大，请压缩后再试')
    if len(data) < 64:
        raise EvidenceError('截图文件不完整')
    mime, width, height, clean = _decode_image(data)
    return {
        'image': clean, 'mime': mime, 'width': width, 'height': height,
        'bytes': len(clean), 'sha256': hashlib.sha256(clean).hexdigest(),
        'filename': _clean_filename(payload.get('filename')),
    }


def _meta_columns():
    return ('id,sha256,mime,bytes,width,height,filename,order_id,actor_id,actor_name,created_at,'
            'provider,engine,status,message,fields_json,warnings_json,raw_text,confidence,'
            'linked_receipt_id,linked_order_id,CASE WHEN image IS NOT NULL THEN 1 ELSE 0 END AS has_image')


def get(c, evidence_id):
    row = c.execute('SELECT ' + _meta_columns() + ' FROM receipt_evidence WHERE id=?', (evidence_id,)).fetchone()
    return dict(row) if row else None


def public(row):
    if not row:
        return None
    data = dict(row)
    try:
        fields = json.loads(data.get('fields_json') or '{}')
    except (TypeError, ValueError):
        fields = {}
    try:
        warnings = json.loads(data.get('warnings_json') or '[]')
    except (TypeError, ValueError):
        warnings = []
    return {
        'id': data.get('id'), 'status': data.get('status') or 'failed',
        'filename': data.get('filename') or '转账截图', 'mime': data.get('mime'),
        'bytes': data.get('bytes'), 'width': data.get('width'), 'height': data.get('height'),
        'order_id': data.get('order_id') or '', 'created_at': data.get('created_at') or '',
        'provider': data.get('provider') or '', 'engine': data.get('engine') or '',
        'engine_label': {'macos':'本机 macOS Vision','openai':'云端视觉模型'}.get(data.get('engine') or '', data.get('engine') or ''),
        'message': data.get('message') or '', 'fields': fields if isinstance(fields, dict) else {},
        'warnings': [str(item) for item in warnings] if isinstance(warnings, list) else [],
        'raw_text': data.get('raw_text') or '', 'confidence': int(data.get('confidence') or 0),
        'linked_receipt_id': data.get('linked_receipt_id') or '',
        'linked_order_id': data.get('linked_order_id') or '',
        'has_image': bool(data.get('has_image')), 'duplicate': False, 'conflict': False,
    }


def begin(c, prepared, order_id, actor, now):
    duplicate = c.execute('SELECT ' + _meta_columns() + ' FROM receipt_evidence '
                          'WHERE sha256=? AND image IS NOT NULL ORDER BY created_at DESC LIMIT 1',
                          (prepared['sha256'],)).fetchone()
    if duplicate:
        result = public(duplicate)
        result['duplicate'] = True
        if result['status'] == 'linked':
            result['message'] = '该截图已用于收款 ' + (result['linked_receipt_id'] or '')
        elif result['status'] == 'processing':
            result['message'] = '这张截图正在识别，请稍候。'
        elif result['order_id'] and order_id and result['order_id'] != order_id:
            result['conflict'] = True
            result['message'] = '该截图已关联到其他订单，请核对是否重复上传。'
        else:
            result['message'] = '这张截图此前已识别，已直接载入原结果。'
        return result
    cutoff = (_now() - timedelta(hours=1)).isoformat(timespec='seconds')
    actor_id = str(actor.get('id') or actor.get('role') or '')
    count = c.execute('SELECT COUNT(*) FROM receipt_evidence WHERE actor_id=? AND created_at>=?', (actor_id, cutoff)).fetchone()[0]
    if count >= RATE_LIMIT_PER_HOUR:
        raise EvidenceError('凭据识别过于频繁，请稍后再试')
    evidence_id = 'EV-' + secrets.token_hex(6).upper()
    c.execute('INSERT INTO receipt_evidence(id,sha256,mime,bytes,width,height,filename,order_id,actor_id,actor_name,'
              'created_at,provider,engine,status,message,fields_json,warnings_json,raw_text,confidence,image) '
              'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (evidence_id, prepared['sha256'], prepared['mime'], prepared['bytes'], prepared['width'],
               prepared['height'], prepared['filename'], order_id or '', actor_id,
               str(actor.get('display_name') or actor.get('name') or ''), now, '', '', 'processing',
               '正在识别，请稍候。', json.dumps(EMPTY_FIELDS, ensure_ascii=False), '[]', '', 0,
               prepared['image']))
    result = public(get(c, evidence_id))
    result['duplicate'] = False
    return result


def finish(c, evidence_id, analysis, now):
    fields = analysis.get('fields') if isinstance(analysis, dict) else None
    warnings = analysis.get('warnings') if isinstance(analysis, dict) else None
    c.execute('UPDATE receipt_evidence SET status=?,provider=?,engine=?,message=?,fields_json=?,warnings_json=?,'
              'raw_text=?,confidence=? WHERE id=?',
              (str(analysis.get('status') or 'failed'), str(analysis.get('provider') or ''),
               str(analysis.get('engine') or ''), str(analysis.get('message') or '')[:300],
               json.dumps(fields if isinstance(fields, dict) else EMPTY_FIELDS, ensure_ascii=False),
               json.dumps(warnings if isinstance(warnings, list) else [], ensure_ascii=False),
               str(analysis.get('raw_text') or '')[:MAX_RAW_TEXT], int(analysis.get('confidence') or 0),
               evidence_id))
    return public(get(c, evidence_id))


def image(c, evidence_id):
    row = c.execute('SELECT image,mime FROM receipt_evidence WHERE id=?', (evidence_id,)).fetchone()
    if not row or not row[0]:
        return None
    return {'image': bytes(row[0]), 'mime': row[1] or 'image/jpeg'}


def discard(c, evidence_id):
    row = get(c, evidence_id)
    if not row:
        raise EvidenceError('凭据不存在')
    if row['status'] == 'linked':
        raise EvidenceError('已登记收款的凭据不能删除')
    c.execute("UPDATE receipt_evidence SET status='discarded',image=NULL,raw_text='',fields_json=?,warnings_json='[]' WHERE id=?",
              (json.dumps(EMPTY_FIELDS, ensure_ascii=False), evidence_id))
    return public(get(c, evidence_id))


def ensure_linkable(row, order_id):
    if not row:
        raise EvidenceError('凭据不存在或已被删除')
    if row['status'] == 'discarded':
        raise EvidenceError('该凭据已删除，请重新上传截图')
    if row['status'] == 'linked':
        raise EvidenceError('该截图已用于收款 ' + (row.get('linked_receipt_id') or ''))
    if row['status'] == 'processing':
        raise EvidenceError('截图仍在识别，请稍候再登记')
    if order_id and row['order_id'] and row['order_id'] != order_id:
        raise EvidenceError('该截图属于其他订单，不能用于当前收款')


def link(c, evidence_id, receipt_id, order_id, now):
    c.execute("UPDATE receipt_evidence SET status='linked',linked_receipt_id=?,linked_order_id=? WHERE id=?",
              (receipt_id, order_id, evidence_id))


def normalize_tx(value):
    return re.sub(r'[\s\-_—–]', '', str(value or '')).upper().strip()


def transaction_exists(c, transaction_no):
    canonical = normalize_tx(transaction_no)
    if not canonical:
        return None
    row = c.execute('SELECT receipt_id,order_id FROM receipt_transaction_ids WHERE transaction_no=?', (canonical,)).fetchone()
    return {'receipt_id': row[0], 'order_id': row[1]} if row else None


def record_transaction(c, transaction_no, receipt_id, order_id, now):
    canonical = normalize_tx(transaction_no)
    if not canonical:
        return
    try:
        c.execute('INSERT INTO receipt_transaction_ids(transaction_no,receipt_id,order_id,created_at) VALUES(?,?,?,?)',
                  (canonical, receipt_id, order_id, now))
    except sqlite3.IntegrityError:
        raise EvidenceError('该交易单号已经登记过收款，不能重复登记')


def _clean_party(value):
    value = str(value or '').strip()
    value = re.sub(r'\s+', ' ', value).strip(' :：,，;；|｜')
    if len(value) < 2 or len(value) > 60:
        return None
    if GENERIC_PARTY_RE.match(value) or re.fullmatch(r'[\d\s\-*]+', value):
        return None
    return value


def _parse_amount(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates = []
    for index, line in enumerate(lines):
        if len(line) > 180:
            continue
        labelled = bool(MONEY_LABEL_RE.search(line))
        if BALANCE_RE.search(line) and not labelled:
            continue
        found = []
        for match in MONEY_RE.finditer(line):
            found.append((match.group(1), 100))
        for match in CURRENCY_RE.finditer(line):
            found.append((match.group(1), 30))
        for match in RMB_RE.finditer(line):
            found.append((match.group(1), 25))
        if not labelled and '¥' not in line and '￥' not in line:
            match = STANDALONE_RE.match(line)
            if match:
                found.append((match.group(1), 20))
        for raw, base in found:
            cents = _to_cents(raw)
            if cents is None:
                continue
            score = base + (10 if index < 12 else 0) + (3 if '.' in raw else 0)
            candidates.append((cents, score, raw, index))
    if not candidates:
        return None, None, [], 0
    candidates.sort(key=lambda item: (-item[1], item[3]))
    cents, score, raw, index = candidates[0]
    warnings = []
    if len({item[0] for item in candidates}) > 1:
        warnings.append('检测到多个金额，已采用“' + _fmt_amount(cents) + '”，请核对。')
    confidence = 94 if score >= 100 else (82 if score >= 30 else 72)
    return cents, raw, warnings, confidence


def _parse_time(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ordered = []
    for line in lines:
        if TIME_LABEL_RE.search(line):
            ordered.insert(0, line)
    ordered.extend(line for line in lines if line not in ordered)
    for line in ordered:
        match = DATE_RE.search(line)
        if not match:
            continue
        try:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            hour = int(match.group(4) or 0)
            minute = int(match.group(5) or 0)
            second = int(match.group(6) or 0)
            dt = datetime(year, month, day, hour, minute, second, tzinfo=TZ)
        except ValueError:
            continue
        if dt.year < 2000 or dt.year > _now().year + 1:
            continue
        precision = 'datetime' if match.group(4) else 'date'
        return dt.isoformat(timespec='seconds'), precision, 92 if precision == 'datetime' else 74
    return None, None, 0


def _looks_like_number_date(value):
    return bool(re.fullmatch(r'20\d{6}', value))


def _parse_transaction(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        compact = re.sub(r'(?<=\d)[ \t]+(?=\d)', '', line)
        if not TX_LABEL_RE.search(compact):
            continue
        match = TX_RE.search(compact)
        if match:
            value = match.group(1).strip(' .,;，。')
            if 6 <= len(value) <= 64 and not _looks_like_number_date(value):
                return value, 90
        for next_line in lines[index + 1:index + 3]:
            candidate = re.sub(r'(?<=\d)[ \t]+(?=\d)', '', next_line).strip()
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\-_]{5,63}', candidate) and not _looks_like_number_date(candidate):
                return candidate, 82
    return None, 0


def _parse_parties(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = {}
    for key, pattern in (('payee', PAYEE_RE), ('payer', PAYER_RE)):
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            value = re.split(pattern, line, maxsplit=1)[1]
            value = re.sub(r'^[\s:：]+', '', value)
            value = re.split(r'\s{2,}|[|｜]', value)[0]
            value = re.split(r'\s+(?=(?:收款|付款|转账|交易|金额|单号|时间|日期|备注|附言|用途))', value)[0]
            cleaned = _clean_party(value)
            if cleaned:
                result[key] = cleaned
                break
            if index + 1 < len(lines):
                cleaned = _clean_party(lines[index + 1])
                if cleaned:
                    result[key] = cleaned
                    break
    return result


def _parse_method(text):
    if '微信' in text or '财付通' in text or '零钱' in text:
        return '微信收款', 86
    if '支付宝' in text:
        return '支付宝', 86
    if '现金' in text:
        return '现金', 70
    if re.search('银行|建设银行|工商银行|农业银行|中国银行|邮储|招商银行|转账|回单|账户|尾号', text):
        return '银行转账', 78
    return None, 0


def _merge_model(fields, warnings, model):
    if not isinstance(model, dict):
        return
    raw = fields.get('_raw_text') or ''
    digits = re.sub(r'[^\d.]', '', raw)
    compact_raw = re.sub(r'\s+', '', raw)
    amount_cents = None
    if 'amount_cents' in model and isinstance(model.get('amount_cents'), (int, float)) and not isinstance(model.get('amount_cents'), bool):
        amount_cents = int(model['amount_cents'])
        if amount_cents <= 0 or amount_cents > 10000000000:
            amount_cents = None
    elif model.get('amount') not in (None, ''):
        amount_cents = _to_cents(model.get('amount'))
    if amount_cents:
        forms = {format(amount_cents / 100, '.2f'), format(amount_cents / 100, 'f').rstrip('0').rstrip('.'), str(amount_cents)}
        present = any(form and form in digits for form in forms)
        if fields.get('amount_cents') and fields['amount_cents'] != amount_cents:
            warnings.append('截图原文金额与模型金额不一致，已采用原文金额。')
        elif not fields.get('amount_cents') and present:
            fields['amount_cents'] = amount_cents
            fields['amount_text'] = format(amount_cents / 100, '.2f')
            fields['sources']['amount_cents'] = 'model'
            fields['field_confidence']['amount_cents'] = 55
            warnings.append('金额由模型补充，请核对原图。')
        elif not fields.get('amount_cents') and not present:
            warnings.append('模型给出的金额未在截图中找到，未采用。')
    model_time = model.get('occurred_at') or model.get('time')
    if model_time and not fields.get('occurred_at'):
        dt = _parse_iso(model_time)
        if dt:
            fields['occurred_at'] = dt.isoformat(timespec='seconds')
            fields['time_precision'] = 'datetime' if ('T' in str(model_time) or ':' in str(model_time)) else 'date'
            fields['sources']['occurred_at'] = 'model'
            fields['field_confidence']['occurred_at'] = 55
            warnings.append('交易时间由模型补充，请核对原图。')
    if model.get('transaction_no') not in (None, '') and not fields.get('transaction_no'):
        candidate = str(model['transaction_no']).strip()
        canonical = normalize_tx(candidate)
        if 6 <= len(candidate) <= 64 and canonical and (not compact_raw or canonical in normalize_tx(compact_raw)):
            fields['transaction_no'] = candidate
            fields['sources']['transaction_no'] = 'model'
            fields['field_confidence']['transaction_no'] = 58
            warnings.append('交易单号由模型补充，请核对原图。')
        else:
            warnings.append('模型给出的交易单号未在原文中出现，未采用。')
    for key, keys in (('payer', ('payer', 'payer_name')), ('payee', ('payee', 'payee_name'))):
        if fields.get(key):
            continue
        value = None
        for model_key in keys:
            if model.get(model_key):
                value = _clean_party(model[model_key])
                break
        if not value:
            continue
        if compact_raw and re.sub(r'\s+', '', value) not in compact_raw:
            warnings.append('模型给出的' + ('付款方' if key == 'payer' else '收款方') + '未在原文中出现，未采用。')
            continue
        fields[key] = value
        fields['sources'][key] = 'model'
        fields['field_confidence'][key] = 52
    if not fields.get('method') and model.get('method'):
        method = str(model['method'])
        if '微信' in method:
            method = '微信收款'
        elif '支付宝' in method:
            method = '支付宝'
        elif '银行' in method:
            method = '银行转账'
        elif '现金' in method:
            method = '现金'
        else:
            method = None
        if method:
            fields['method'] = method
            fields['sources']['method'] = 'model'
            fields['field_confidence']['method'] = 55
    if model.get('direction') in ('in', 'out'):
        if not fields.get('sources', {}).get('direction'):
            fields['direction'] = model['direction']
            fields['sources']['direction'] = 'model'


def _parse_iso(value):
    text = str(value or '').strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def extract_fields(text):
    normalized = text.replace('\u3000', ' ').replace('：', ':').replace('，', ',')
    warnings = []
    amount_cents, amount_text, amount_warnings, amount_confidence = _parse_amount(normalized)
    warnings.extend(amount_warnings)
    occurred_at, precision, time_confidence = _parse_time(normalized)
    transaction_no, tx_confidence = _parse_transaction(normalized)
    parties = _parse_parties(normalized)
    method, method_confidence = _parse_method(normalized)
    out_signal = bool(OUT_RE.search(normalized)) or bool(SIGN_OUT_RE.search(normalized) and not SIGN_IN_RE.search(normalized))
    in_signal = bool(IN_RE.search(normalized)) or bool(SIGN_IN_RE.search(normalized))
    direction = 'out' if out_signal and not in_signal else 'in'
    fields = _empty_fields()
    fields.update({'amount_cents': amount_cents, 'amount_text': amount_text, 'occurred_at': occurred_at,
                   'time_precision': precision, 'transaction_no': transaction_no,
                   'payer': parties.get('payer'), 'payee': parties.get('payee'), 'method': method,
                   'direction': direction, 'field_confidence': {}, 'sources': {}, '_raw_text': normalized})
    if amount_cents:
        fields['field_confidence']['amount_cents'] = amount_confidence
        fields['sources']['amount_cents'] = 'rule'
    if occurred_at:
        fields['field_confidence']['occurred_at'] = time_confidence
        fields['sources']['occurred_at'] = 'rule'
    if transaction_no:
        fields['field_confidence']['transaction_no'] = tx_confidence
        fields['sources']['transaction_no'] = 'rule'
    for key, confidence in (('payer', 65), ('payee', 65), ('method', method_confidence)):
        if fields.get(key):
            fields['field_confidence'][key] = confidence
            fields['sources'][key] = 'rule'
    fields['sources']['direction'] = 'rule'
    return fields, warnings


def _finalize(fields, warnings):
    fields.pop('_raw_text', None)
    if not fields.get('amount_cents'):
        warnings.append('未识别到金额，请手工填写。')
    if not fields.get('occurred_at'):
        warnings.append('未识别到交易时间，请手工填写。')
    if not fields.get('transaction_no'):
        warnings.append('未识别到交易单号，请核对原图后手工填写。')
    if fields.get('direction') == 'out':
        warnings.append('截图显示为付款/转出，请确认是否用于收款登记。')
    occurred_at = fields.get('occurred_at')
    if occurred_at:
        dt = _parse_iso(occurred_at)
        if dt and dt > _now() + timedelta(days=2):
            warnings.append('截图交易时间晚于当前时间，请核对。')
        if dt and dt < _now() - timedelta(days=3650):
            warnings.append('截图交易时间过于久远，请核对。')
    warnings = list(dict.fromkeys(warnings))
    weights = {'amount_cents': 35, 'occurred_at': 25, 'transaction_no': 25, 'payer': 5, 'payee': 5, 'method': 5}
    confidence = min(95, sum(weight for key, weight in weights.items() if fields.get(key)))
    essentials = [fields.get('amount_cents'), fields.get('occurred_at'), fields.get('transaction_no')]
    if not any(essentials):
        return fields, warnings, 0, 'failed', '未识别出金额、交易时间或交易单号，请手工填写。'
    if not all(essentials):
        return fields, warnings, confidence, 'recognized', '部分字段未识别，请对照原图补充。'
    return fields, warnings, confidence, 'recognized', '识别完成，请核对原图后登记。'


def _safe_error(exc, cfg):
    text = str(exc) or exc.__class__.__name__
    key = str((cfg or {}).get('api_key') or '')
    if key:
        text = text.replace(key, '***')
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:240]


def _failure(message, provider='', engine=''):
    return {'status': 'failed', 'provider': provider, 'engine': engine, 'message': message[:300],
            'fields': _empty_fields(), 'warnings': [message[:300]], 'raw_text': '', 'confidence': 0}


def failure(message):
    return _failure(message)


def analyze(prepared, cfg, db_path):
    engine = _effective_engine(cfg)
    provider = str((cfg or {}).get('provider') or 'auto')
    if engine == 'off':
        public_cfg = _public_config(cfg or {})
        return _failure(public_cfg['message'], provider, 'off')
    if not _OCR_SLOTS.acquire(blocking=False):
        return _failure('识别任务繁忙，请稍后再试，截图已保存。', provider, engine)
    try:
        text = ''
        model = None
        if engine == 'macos':
            try:
                text = _macos_ocr(prepared['image'], db_path)
            except Exception as exc:
                return _failure(_safe_error(exc, cfg), provider, engine)
            engine_label = 'macos'
        else:
            try:
                text, model = _openai_ocr(prepared, cfg)
            except Exception as exc:
                return _failure(_safe_error(exc, cfg), provider, engine)
            engine_label = 'openai'
        if not text.strip() and isinstance(model, dict):
            text = str(model.get('raw_text') or '')
        if not text.strip():
            return _failure('未从截图中识别到文字，请确认截图清晰、完整。', provider, engine)
        fields, warnings = extract_fields(text)
        if isinstance(model, dict):
            fields['_raw_text'] = text
            _merge_model(fields, warnings, model)
        fields, warnings, confidence, status, message = _finalize(fields, warnings)
        return {'status': status, 'provider': provider, 'engine': engine_label, 'message': message,
                'fields': fields, 'warnings': warnings, 'raw_text': text[:MAX_RAW_TEXT], 'confidence': confidence}
    finally:
        _OCR_SLOTS.release()


def _vision_cache(db_path):
    path = Path(db_path).parent / '.cache' / 'receipt_ocr'
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _run_vision_compiler(command, timeout=90):
    # swiftc launches swift-frontend children: timeout must stop the whole group.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _vision_binary(db_path):
    cache = _vision_cache(db_path)
    digest = hashlib.sha256(VISION_SWIFT.encode('utf-8')).hexdigest()[:12]
    binary = cache / ('vision_ocr_' + digest)
    with _VISION_LOCK:
        if binary.is_file():
            try:
                os.chmod(binary, 0o700)
            except OSError:
                pass
            return binary
        compiler = shutil.which('swiftc')
        if not compiler:
            raise EvidenceError('本机缺少 swiftc，无法使用 macOS Vision。请安装 Xcode Command Line Tools，或配置云端视觉模型。')
        source = cache / ('vision_ocr_' + digest + '.swift')
        source.write_text(VISION_SWIFT, encoding='utf-8')
        target = cache / ('vision_ocr_' + digest + '.tmp')
        command = [compiler, '-O', '-suppress-warnings', '-module-cache-path', str(cache / 'modules'), '-o', str(target), str(source)]
        try:
            try:
                result = _run_vision_compiler(command)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise EvidenceError('本机 OCR 编译失败：' + str(exc)[:160])
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or b'').decode('utf-8', 'replace')[-240:]
                raise EvidenceError('本机 OCR 编译失败：' + detail)
            os.chmod(target, 0o700)
            os.replace(target, binary)
            return binary
        finally:
            try:
                target.unlink()
            except OSError:
                pass


def _macos_ocr(image_bytes, db_path):
    if sys.platform != 'darwin':
        raise EvidenceError('当前服务器不是 macOS，不能使用本机识别。')
    binary = _vision_binary(db_path)
    cache = _vision_cache(db_path)
    handle = tempfile.NamedTemporaryFile(prefix='ocr_', suffix='.jpg', dir=str(cache), delete=False)
    path = handle.name
    try:
        handle.write(image_bytes)
        handle.close()
        result = subprocess.run([str(binary), path], capture_output=True, timeout=40)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if result.returncode != 0:
        detail = (result.stderr or b'').decode('utf-8', 'replace').strip()
        raise EvidenceError('本机 OCR 失败：' + (detail[-160:] or ('退出码 ' + str(result.returncode))))
    try:
        rows = json.loads(result.stdout.decode('utf-8', 'replace') or '[]')
    except ValueError:
        raise EvidenceError('本机 OCR 返回数据无法解析')
    if not isinstance(rows, list):
        raise EvidenceError('本机 OCR 返回数据无法解析')
    rows = [row for row in rows if isinstance(row, dict) and str(row.get('text') or '').strip()]
    rows.sort(key=lambda row: (-round(float(row.get('y') or 0), 2), float(row.get('x') or 0)))
    return '\n'.join(str(row['text']).strip() for row in rows)




def _openai_ocr(prepared, cfg):
    base_url = _validate_remote_url(str(cfg.get('base_url') or ''))
    url = base_url if base_url.endswith('/chat/completions') else base_url + '/chat/completions'
    image_url = 'data:' + prepared['mime'] + ';base64,' + base64.b64encode(prepared['image']).decode('ascii')
    prompt = (
        '你是财务转账截图信息提取器。只提取截图中明确可见的信息，禁止推测、补全或改写。'
        '严格输出一个 JSON 对象，不要 Markdown、不要解释。字段：raw_text（按行转录的全部文字）、'
        'amount（数字字符串或 null）、occurred_at（ISO 8601 带时区或 null）、transaction_no（原样字符串或 null）、'
        'payer、payee、method（微信/支付宝/银行转账/现金/其他）、direction（in/out）。'
        '金额只写数字，不带货币符号和千分位；无法确认的字段必须为 null。'
    )
    body = {
        'model': str(cfg.get('model') or ''),
        'max_tokens': 1200,
        'messages': [
            {'role': 'system', 'content': prompt},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': '识别这张转账或收款截图，按系统要求只输出 JSON。'},
                {'type': 'image_url', 'image_url': {'url': image_url}},
            ]},
        ],
    }
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                              'Authorization': 'Bearer ' + str(cfg.get('api_key') or ''),
                                              'User-Agent': 'yangfan-erp/ocr'})
    timeout = min(int(cfg.get('timeout') or DEFAULT_TIMEOUT), 40)
    try:
        with _NO_REDIRECT.open(request, timeout=timeout) as response:
            raw = response.read(900_000)
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read(4000).decode('utf-8', 'replace')
            parsed = json.loads(detail)
            detail = str(((parsed.get('error') or {}).get('message') if isinstance(parsed, dict) else '') or detail)
        except (OSError, ValueError):
            pass
        raise EvidenceError('模型服务返回 HTTP ' + str(exc.code) + '：' + detail[:160])
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise EvidenceError('模型服务证书校验失败：请检查服务器 CA 根证书，或设置 SSL_CERT_FILE 指向可信证书文件后重启服务。')
        raise EvidenceError('无法连接模型服务：' + str(exc.reason)[:160])
    except TimeoutError:
        raise EvidenceError('模型服务响应超时，请稍后重试或手工填写。')
    try:
        data = json.loads(raw.decode('utf-8', 'replace'))
    except ValueError:
        raise EvidenceError('模型服务返回内容无法解析')
    if isinstance(data, dict) and data.get('error'):
        detail = data['error'].get('message') if isinstance(data['error'], dict) else str(data['error'])
        raise EvidenceError('模型服务返回错误：' + str(detail)[:160])
    choices = data.get('choices') if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise EvidenceError('模型服务没有返回识别结果')
    message = choices[0].get('message') if isinstance(choices[0], dict) else None
    content = message.get('content') if isinstance(message, dict) else None
    if isinstance(content, list):
        content = ''.join(str(part.get('text') or '') for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise EvidenceError('模型服务没有返回文字内容')
    model = _json_object(content)
    raw_text = str((model or {}).get('raw_text') or content)
    return raw_text, model


def _json_object(content):
    text = content.strip()
    if text.startswith('```'):
        text = re.sub(r'^```[A-Za-z]*\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, dict)), None)
    if not isinstance(value, dict):
        return None
    if isinstance(value.get('data'), dict) and 'amount' not in value:
        value = value['data']
    if isinstance(value.get('fields'), dict):
        nested = value['fields']
        if value.get('raw_text') and not nested.get('raw_text'):
            nested = dict(nested)
            nested['raw_text'] = value['raw_text']
        value = nested
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, '不允许重定向', headers, fp)


def _tls_context():
    """系统 Python 可能没有可用的默认 CA 文件，补载常见系统根证书包。"""
    context = ssl.create_default_context()
    candidates = (os.environ.get('SSL_CERT_FILE'), '/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt')
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                context.load_verify_locations(cafile=path)
            except (OSError, ssl.SSLError):
                pass
    return context


_TLS_CONTEXT = _tls_context()
_NO_REDIRECT = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_TLS_CONTEXT))


def warmup(db_path):
    """Compile the local Vision helper before the first user upload."""
    if sys.platform != 'darwin' or not shutil.which('swiftc'):
        return False
    try:
        _vision_binary(db_path)
        return True
    except Exception:
        return False
