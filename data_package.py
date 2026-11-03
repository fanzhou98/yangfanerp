"""月度/期间数据包：把会计需要的业务数据导出为一个多页签 Excel（无第三方依赖）。"""
from decimal import Decimal
from datetime import datetime
import io, json, zipfile, os, csv, sqlite3
from xml.sax.saxutils import escape
import resources_costs as rc
import funds

SHEETS = ['订单明细', '收款流水', '退货明细', '采购验收', '采购付款', '原辅料领用', '生产日报', '库存结存', '资金流水', '说明']

def _day(r, *keys):
    for k in keys:
        v = r.get(k)
        if v: return str(v)[:10]
    return ''

def _yuan(cents):
    try: return float((Decimal(str(cents or 0)) / 100).quantize(Decimal('0.01')))
    except Exception: return 0.0

def _in(r, start, end, *keys):
    d = _day(r, *keys)
    return start <= d <= end

def _products(r):
    return r.get('products') or r.get('lines') or []

def build(c, start, end):
    """返回 [(页签名, 表头, 行)]；日期闭区间。"""
    orders = [r for r in rc.rows(c, 'orders') if _in(r, start, end, 'business_date')]
    receipts = [r for r in rc.rows(c, 'receipts') if _in(r, start, end, 'received_date')]
    returns = [r for r in rc.rows(c, 'sales_returns') if _in(r, start, end, 'business_date')]
    purchase_receipts = [r for r in rc.rows(c, 'purchase_receipts') if _in(r, start, end, 'business_date')]
    purchase_payments = [r for r in rc.rows(c, 'purchase_payments') if _in(r, start, end, 'business_date')]
    materials = [r for r in rc.rows(c, 'material_entries') if _in(r, start, end, 'business_date')]
    daily = [r for r in rc.rows(c, 'factory_daily') if _in(r, start, end, 'business_date')]
    closings = [r for r in rc.rows(c, 'stock_closings') if _in(r, start, end, 'business_date')]
    paid = {}
    for r in receipts:
        if r.get('voided'): continue
        if r.get('order_id'): paid[r['order_id']] = paid.get(r['order_id'], 0) + int(r.get('amount_cents') or 0)
    sheets = []
    sheets.append(('订单明细', ['订单号', '业务日期', '客户', '状态', '金额（元）', '已收（元）', '未收（元）', '备注'], [
        [r.get('id'), _day(r, 'business_date'), r.get('customer_name', ''), r.get('state', ''),
         _yuan(r.get('total_cents')), _yuan(paid.get(r.get('id'), 0)),
         _yuan(max(0, int(r.get('total_cents') or 0) - paid.get(r.get('id'), 0))), r.get('note', '')]
        for r in orders]))
    sheets.append(('收款流水', ['收款单号', '到账日期', '客户', '关联订单', '到账（元）', '折扣（元）', '抹零（元）', '方式', '资金账户', '状态'], [
        [r.get('id'), _day(r, 'received_date'), r.get('customer_name', ''), r.get('order_id') or '期初应收',
         _yuan(r.get('amount_cents')), _yuan(r.get('discount_cents')), _yuan(r.get('rounding_cents')),
         r.get('method', ''), r.get('account_name', r.get('account_id', '')), '已冲销' if r.get('voided') else '有效']
        for r in receipts]))
    ret_rows = []
    for r in returns:
        fin = r.get('finance') or {}
        lines = r.get('lines') or []
        if not lines:
            ret_rows.append([_day(r, 'business_date'), r.get('customer_name', ''), '', '', '', _yuan(r.get('amount_cents')), _yuan(fin.get('refunded_cents')), _yuan(fin.get('credit_cents'))])
        for l in lines:
            ret_rows.append([_day(r, 'business_date'), r.get('customer_name', ''), l.get('product_name', ''), l.get('qty', ''), l.get('unit', ''),
                             _yuan(l.get('amount_cents')), _yuan(fin.get('refunded_cents')), _yuan(fin.get('credit_cents'))])
    sheets.append(('退货明细', ['退货日期', '客户', '产品', '数量', '单位', '金额（元）', '已退款（元）', '已抵扣（元）'], ret_rows))
    pr_rows = []
    for r in purchase_receipts:
        for l in r.get('lines') or []:
            pr_rows.append([r.get('id'), _day(r, 'business_date'), r.get('order_id', ''), r.get('supplier_name', ''),
                            l.get('material_name', ''), l.get('dispatch_qty', ''), l.get('arrival_qty', ''), l.get('settled_qty', ''),
                            l.get('settled_price', ''), _yuan(l.get('amount_cents')), l.get('warehouse_name', '')])
    sheets.append(('采购验收', ['入库单', '入库日期', '采购单', '供应商', '物料', '发车磅', '卸车磅', '结算重量', '结算单价', '货款（元）', '库房'], pr_rows))
    sheets.append(('采购付款', ['付款单号', '付款日期', '采购单', '收款方', '金额（元）', '资金账户', '状态'], [
        [r.get('id'), _day(r, 'business_date'), r.get('order_id', ''), r.get('payee_name') or r.get('supplier_name', ''),
         _yuan(r.get('amount_cents')), r.get('account_name', r.get('account_id', '')), '已冲销' if r.get('voided') else '有效']
        for r in purchase_payments]))
    sheets.append(('原辅料领用', ['发生日期', '物料', '类型', '库房', '数量', '单位', '金额（元）', '领用人', '说明'], [
        [_day(r, 'business_date'), r.get('material_name', ''), {'consume': '领用', 'return': '退料', 'loss': '报损', 'opening': '期初', 'receipt': '入库'}.get(r.get('kind'), r.get('kind', '')),
         r.get('warehouse_name', ''), r.get('qty', ''), r.get('unit', ''), _yuan(r.get('amount_cents')), r.get('handler', ''), r.get('note', '')]
        for r in materials]))
    prod_rows = []
    for r in daily:
        for p in _products(r):
            prod_rows.append([_day(r, 'business_date'), p.get('product_name', ''), p.get('derived_qty', ''), p.get('unit', ''),
                              p.get('bean_kg', ''), p.get('yield_kg_per_kg', '')])
    sheets.append(('生产日报', ['生产日期', '产品', '产量', '单位', '折豆（公斤）', '出品率'], prod_rows))
    close_rows = []
    for r in closings:
        for p in _products(r):
            close_rows.append([_day(r, 'business_date'), p.get('product_name', ''), p.get('counted_qty', p.get('closing_qty', '')), p.get('unit', ''), _yuan(p.get('closing_cents'))])
    sheets.append(('库存结存', ['日期', '产品', '实盘结存', '单位', '结存金额（元）'], close_rows))
    mov = [m for m in funds.movements(c) if start <= m['business_date'] <= end]
    sheets.append(('资金流水', ['日期', '账户', '来源', '方向', '金额（元）', '对方', '说明'], [
        [m['business_date'], m.get('account_id', ''), m.get('source', ''), '收入' if m.get('direction') == 'in' else '支出',
         _yuan(m.get('amount_cents')), m.get('partner', ''), m.get('note', '')]
        for m in mov]))
    sheets.append(('说明', ['项目', '内容'], [
        ['统计期间', f'{start} 至 {end}'],
        ['生成时间', datetime.now().isoformat(timespec='seconds')],
        ['口径', '按业务发生日期归期；金额单位元，保留两位；采购结算重量为协商后重量，入库按卸车磅。'],
        ['来源', '订单/收款/退货/采购/领用/生产/库存结存/资金流水，均为系统原始台账。'],
        ['说明', '本文件仅含业务数据，不含账号、密码与权限配置；整库备份请由管理员另行生成。'],
    ]))
    return sheets

def _col(i):
    s = ''
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s

def _cell(ref, value):
    if value is None or value == '': return ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

def _sheet_xml(headers, rows, widths):
    cols = ''.join(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols>{cols}</cols><sheetData>']
    head = ''.join(_cell(f'{_col(i)}1', h) for i, h in enumerate(headers))
    out.append(f'<row r="1">{head}</row>')
    for ri, row in enumerate(rows, start=2):
        cells = ''.join(_cell(f'{_col(ci)}{ri}', v) for ci, v in enumerate(row))
        out.append(f'<row r="{ri}">{cells}</row>')
    out.append('</sheetData></worksheet>')
    return ''.join(out)

def _widths(headers):
    return [max(10, min(28, 8 + len(str(h)) * 2)) for h in headers]

def xlsx(sheets, title='ERP 数据包'):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        n = len(sheets)
        ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
              '<Default Extension="xml" ContentType="application/xml"/>',
              '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
              '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
        for i in range(n):
            ct.append(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        ct.append('</Types>')
        z.writestr('[Content_Types].xml', ''.join(ct))
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
        rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        for i, (name, headers, rows) in enumerate(sheets):
            wb.append(f'<sheet name="{escape(name)}" sheetId="{i+1}" r:id="rId{i+1}"/>')
            rels.append(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>')
            z.writestr(f'xl/worksheets/sheet{i+1}.xml', _sheet_xml(headers, rows, _widths(headers)))
        rels.append(f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
        rels.append('</Relationships>')
        wb.append('</sheets></workbook>')
        z.writestr('xl/workbook.xml', ''.join(wb))
        z.writestr('xl/_rels/workbook.xml.rels', ''.join(rels))
        z.writestr('xl/styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    return buf.getvalue()



def _photo_rows(c, start, end):
    """Return driver photo rows in the date range. Empty when schema/table is absent."""
    try:
        cur = c.execute("SELECT order_id,kind,at,path,customer_id,bytes,meta FROM driver_photos WHERE substr(at,1,10)>=? AND substr(at,1,10)<=? ORDER BY at,order_id,kind", (start, end))
    except sqlite3.OperationalError:
        return []
    return cur.fetchall() if hasattr(cur, 'fetchall') else list(cur)


def photo_bundle(c, start, end):
    """Excel data package plus driver photos and a manifest, returned as ZIP bytes."""
    import resources_costs as rc
    excel = xlsx(build(c, start, end))
    try:
        names = {str(r[0]): r[1] for r in c.execute('SELECT id,name FROM customers')}
    except sqlite3.OperationalError:
        names = {}
    out = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'ERP数据包-{start}_{end}.xlsx', excel)
        for row in _photo_rows(c, start, end):
            order_id, kind, at, path, customer_id, size, meta = (list(row) + [None] * 7)[:7]
            order_id = str(order_id or '')
            kind = str(kind or '')
            at = str(at or '')
            path = str(path or '')
            ext = os.path.splitext(path)[1].lower() or '.jpg'
            if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
                ext = '.jpg'
            zip_name = f"司机照片/{at[:10] or '未知日期'}/{order_id}-{kind}{ext}"
            status = '已打包'
            if path and os.path.isfile(path):
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                    z.writestr(zip_name, data)
                    size = len(data)
                except OSError:
                    status = '读取失败'
            else:
                status = '文件缺失'
            manifest.append([order_id, customer_id or '', names.get(customer_id, ''), kind, at, zip_name, size or 0, status])
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['订单号', '客户编号', '客户名称', '类型', '拍摄时间', '文件', '字节', '状态'])
        writer.writerows(manifest)
        z.writestr('司机照片清单.csv', '\ufeff' + buf.getvalue())
    return out.getvalue(), f'erp-data-{start}_{end}-photos.zip', len(manifest)

def package_dir():
    import os
    path = os.environ.get('ERP_PACKAGE_DIR') or '/var/lib/yangfan-erp/packages'
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, '.write-test')
        open(test, 'w').close(); os.remove(test)
        return path
    except Exception:
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'packages')
        os.makedirs(local, exist_ok=True)
        return local

def _dirs():
    import os
    env = os.environ.get('ERP_PACKAGE_DIR')
    out = [env] if env else []
    out.append('/var/lib/yangfan-erp/packages')
    out.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'packages'))
    return out

def missing(c, months=3):
    import json, os
    rows = [json.loads(r[0]) for r in c.execute('SELECT payload FROM resource_periods')]
    closed = sorted({r['month'] for r in rows if r.get('state') == 'closed'}, reverse=True)[:months]
    result = []
    for m in closed:
        name = f'ERP数据包-{m[:4]}-{str(m)[5:7]}.xlsx'
        found = None
        for d in _dirs():
            p = os.path.join(d, name)
            if os.path.exists(p) and os.path.getsize(p) > 0:
                found = p
                break
        if not found:
            result.append({'month': m, 'name': name})
    return result

def save(c, month, directory=None):
    import calendar, os
    year, mon = (int(x) for x in str(month)[:7].split('-'))
    start = f'{year:04d}-{mon:02d}-01'
    end = f'{year:04d}-{mon:02d}-{calendar.monthrange(year, mon)[1]:02d}'
    directory = directory or package_dir()
    name = f'ERP数据包-{year:04d}-{mon:02d}.xlsx'
    path = os.path.join(directory, name)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(xlsx(build(c, start, end)))
    os.replace(tmp, path)
    return {'path': path, 'name': name, 'start': start, 'end': end, 'bytes': os.path.getsize(path)}
