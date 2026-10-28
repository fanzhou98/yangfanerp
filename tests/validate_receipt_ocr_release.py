"""Synthetic v0.83.0 -> v0.84.0 upgrade for receipt evidence, without real data."""
from pathlib import Path
import json, sqlite3, struct, zlib, hashlib, sys, tempfile, subprocess
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from validate_resource_release import run, unpack

OLD = ROOT / 'output/releases/yangfan-erp-0.83.0.tar.gz'
NEW = ROOT / 'output/releases/yangfan-erp-0.84.0.tar.gz'
SEED = r'''
import server, json, sys
from pathlib import Path
server.DB = Path(sys.argv[1]); server.init_db()
order = {'id':'SO-UPGRADE-OCR','customer_id':'C001','customer_name':'演示·乌鲁木齐一店','business_date':'2026-10-21','state':'reviewed','total_cents':150000,'paid_cents':150000,'discount_cents':0,'rounding_cents':0,'version':2,'lines':[{'product_id':'P003','product_name':'白豆干','bill_qty':20,'billing_unit':'筐','price':'75','amount_cents':150000}]}
receipt = {'id':'RC-UPGRADE-OCR','order_id':order['id'],'customer_id':'C001','customer_name':order['customer_name'],'discount_cents':0,'rounding_cents':0,'account_id':'','amount_cents':150000,'received_date':'2026-10-26','method':'银行转账','note':'升级前旧凭据','at':'2026-10-26T10:00:00+08:00','role':'出纳','transaction_no':'OLD BANK TX 001'}
with server.connect(True) as c:
 c.execute("INSERT OR IGNORE INTO customers(id,name,route,note,legal_name,delivery_method,region,market_id,location_kind,phone,business_kind) VALUES('C001','演示·乌鲁木齐一店','乌鲁木齐线','合成客户','','delivery','','','independent','','sales')")
 c.execute("INSERT OR IGNORE INTO products(id,name,unit,price,tare,standard_kg) VALUES('P003','白豆干','筐','75','1.8',NULL)")
 c.execute('INSERT INTO orders(id,payload) VALUES(?,?)',(order['id'],json.dumps(order,ensure_ascii=False)))
 c.execute('INSERT INTO receipts(id,payload) VALUES(?,?)',(receipt['id'],json.dumps(receipt,ensure_ascii=False)))
'''
NEWTEST = r'''
import server, receipt_ocr, json, sys, struct, zlib, base64
from pathlib import Path
server.DB = Path(sys.argv[1]); server.init_db()
w = h = 120
raw = b''.join(b'\x00' + b'\xee\xee\xee' * w for _ in range(h))
def ch(k, d): return struct.pack('>I', len(d)) + k + d + struct.pack('>I', zlib.crc32(k + d) & 0xffffffff)
png = b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + ch(b'IDAT', zlib.compress(raw, 9)) + ch(b'IEND', b'')
p = receipt_ocr.prepare({'image_base64': base64.b64encode(png).decode(), 'filename': 'upgrade.png'})
assert p['mime'] == 'image/png' and p['width'] == w and p['height'] == h
with server.connect(True) as c: receipt_ocr.save_settings(c, {'provider': 'off'}, server.DB)
with server.connect(True) as c: ev = receipt_ocr.begin(c, p, '', {'id': 'upgrade', 'role': '出纳', 'display_name': '测试出纳'}, server.now())
with server.connect(True) as c: res = receipt_ocr.finish(c, ev['id'], {'status': 'failed', 'fields': {}, 'warnings': [], 'raw_text': '', 'confidence': 0, 'message': '合成升级测试'}, server.now())
assert res['status'] == 'failed'
with server.connect(True) as c:
 assert receipt_ocr.transaction_exists(c, 'oldbanktx001')
 row = c.execute('SELECT status,(image IS NOT NULL) FROM receipt_evidence WHERE id=?', (ev['id'],)).fetchone()
 assert row[0] == 'failed' and row[1] == 1, tuple(row)
print(json.dumps({'evidence': res, 'tx': True}, ensure_ascii=False))
'''
def snapshot(db):
    with sqlite3.connect(db) as c:
        return {'orders': [list(r) for r in c.execute('SELECT id,payload FROM orders ORDER BY id')],
                'receipts': [list(r) for r in c.execute('SELECT id,payload FROM receipts ORDER BY id')]}
if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='erp084-upgrade-') as folder:
        tmp = Path(folder); old = tmp / 'old'; new = tmp / 'new'; db = tmp / 'synthetic.db'
        prior = unpack(OLD, old); meta = unpack(NEW, new)
        run(['ops/initialize_cloud.py', '--database', str(db)], old)
        run(['-c', SEED, str(db)], old)
        before = snapshot(db)
        run(['ops/initialize_cloud.py', '--database', str(db)], new)
        after = snapshot(db)
        assert before == after, (before, after)
        with sqlite3.connect(db) as c:
            assert c.execute('PRAGMA user_version').fetchone()[0] == 66
            cols = {r[1] for r in c.execute('PRAGMA table_info(receipt_evidence)')}
            assert {'id', 'sha256', 'image', 'fields_json', 'status', 'linked_receipt_id'} <= cols, cols
            rows = [list(r) for r in c.execute('SELECT receipt_id,order_id,transaction_no FROM receipt_transaction_ids')]
            assert rows == [['RC-UPGRADE-OCR', 'SO-UPGRADE-OCR', 'OLDBANKTX001']], rows
        result = json.loads(run(['-c', NEWTEST, str(db)], new))
        repeat = snapshot(db)
        run(['ops/initialize_cloud.py', '--database', str(db)], new)
        assert snapshot(db) == repeat
        checks = json.loads(run(['ops/erp_ops.py', 'check-db', '--database', str(db), '--full'], new))
        business = json.loads(subprocess.check_output([sys.executable, 'ops/business_check.py', '--database', str(db)], cwd=new, text=True))
        assert checks['ok'] and business['ok'], (checks, business.get('errors'))
        evidence = {'ok': True, 'from': prior['version'], 'to': meta['version'], 'schema_before': 65, 'schema_after': 66,
                    'sha256': hashlib.sha256(NEW.read_bytes()).hexdigest(),
                    'existing_orders_and_receipts_unchanged': True, 'old_receipt_transaction_backfilled': True,
                    'new_evidence_saved': result['evidence']['id'], 'transaction_lookup': True,
                    'repeat_upgrade_unchanged': True, 'check_db': checks, 'business_check': business}
        out = ROOT / 'output/收款截图识别-v0.84.0'; out.mkdir(parents=True, exist_ok=True)
        (out / 'release-validation.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in evidence.items() if k not in ('check_db', 'business_check')}, ensure_ascii=False))
