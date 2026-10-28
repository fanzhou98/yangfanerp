"""Frozen upgrade steps. Append new steps; existing step implementations are immutable.

All database writes belong to the caller's transaction. Domain init_schema entry
points are compatibility adapters to migrations.py, never alternate upgrade paths.
"""
import json,re,secrets
from decimal import Decimal
import auth,erp_access,resources_costs as rc,production_management as pm
import purchasing,payroll,assets,driver_portal,production_config as pc

def core_tables(c, ctx):
    for statement in '\n        CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY,name TEXT NOT NULL,route TEXT NOT NULL,note TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,name TEXT NOT NULL,unit TEXT NOT NULL,price TEXT NOT NULL,tare TEXT NOT NULL,standard_kg TEXT);\n        CREATE TABLE IF NOT EXISTS rules(customer_id TEXT NOT NULL,product_id TEXT NOT NULL,price TEXT NOT NULL,tare TEXT NOT NULL,PRIMARY KEY(customer_id,product_id));\n        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,payload TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS trial_archives(id TEXT PRIMARY KEY,payload TEXT NOT NULL,at TEXT NOT NULL,reason TEXT NOT NULL,restored_at TEXT);\n        CREATE TABLE IF NOT EXISTS archived_orders(id TEXT PRIMARY KEY,payload TEXT NOT NULL,kept_id TEXT NOT NULL,reason TEXT NOT NULL,archived_at TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,payload TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT,role TEXT,action TEXT,entity TEXT,before_json TEXT,after_json TEXT);\n        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS delivery_markets(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,city TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS delivery_vehicles(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE);\n        CREATE TABLE IF NOT EXISTS dispatch_plans(business_date TEXT PRIMARY KEY,payload TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS warehouse_plans(business_date TEXT PRIMARY KEY,payload TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS sales_returns(id TEXT PRIMARY KEY,payload TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS processing_batches(id TEXT PRIMARY KEY,payload TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS stock_closings(business_date TEXT PRIMARY KEY,payload TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS operator_users(id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1);\n        CREATE TABLE IF NOT EXISTS statement_documents(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,customer_id TEXT NOT NULL,business_date TEXT NOT NULL,issued_at TEXT NOT NULL,payload TEXT NOT NULL,content_hash TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS delivery_drivers(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,active INTEGER NOT NULL DEFAULT 1);\n        '.split(';'):
        if statement.strip():c.execute(statement)

def core_columns(c, ctx):
    for field in ('actor_id','actor_name','request_id'):
        if field not in {r[1] for r in c.execute('PRAGMA table_info(audit)')}:
            c.execute('ALTER TABLE audit ADD COLUMN '+field+" TEXT NOT NULL DEFAULT ''")
    if 'legal_name' not in {r[1] for r in c.execute('PRAGMA table_info(customers)')}:
        c.execute("ALTER TABLE customers ADD COLUMN legal_name TEXT NOT NULL DEFAULT ''")
    if 'active' not in {r[1] for r in c.execute('PRAGMA table_info(delivery_vehicles)')}:
        c.execute('ALTER TABLE delivery_vehicles ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
    if 'delivery_method' not in {r[1] for r in c.execute('PRAGMA table_info(customers)')}:
        c.execute("ALTER TABLE customers ADD COLUMN delivery_method TEXT NOT NULL DEFAULT 'delivery'")
    for field in ('region','market_id'):
        if field not in {r[1] for r in c.execute('PRAGMA table_info(customers)')}:
            c.execute(f"ALTER TABLE customers ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
    if 'location_kind' not in {r[1] for r in c.execute('PRAGMA table_info(customers)')}:
        c.execute("ALTER TABLE customers ADD COLUMN location_kind TEXT NOT NULL DEFAULT 'independent'")
    if 'kind' not in {r[1] for r in c.execute('PRAGMA table_info(delivery_markets)')}:
        c.execute("ALTER TABLE delivery_markets ADD COLUMN kind TEXT NOT NULL DEFAULT 'market'")

def auth_schema(c, ctx):
    """Create account tables without creating default accounts or passwords."""
    # Individual statements preserve a caller's surrounding transaction (unlike
    # sqlite3.executescript, which implicitly commits a pending transaction).
    statements = [
        """CREATE TABLE IF NOT EXISTS auth_users(
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('管理员','库管','会计','出纳','老板','厂长','物流负责人','司机')),
        password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        must_change_password INTEGER NOT NULL DEFAULT 1 CHECK(must_change_password IN (0,1)),
        version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS auth_sessions(
        id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, csrf_hash TEXT NOT NULL,
        user_id TEXT NOT NULL REFERENCES auth_users(id), user_version INTEGER NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)""",
        'CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id)',
        'CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at)',
        """CREATE TABLE IF NOT EXISTS auth_login_limits(
        bucket TEXT PRIMARY KEY, window_started_at INTEGER NOT NULL,
        failures INTEGER NOT NULL, blocked_until INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS security_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, action TEXT NOT NULL,
        actor_id TEXT, entity TEXT NOT NULL, details_json TEXT NOT NULL)""",
        'CREATE INDEX IF NOT EXISTS security_events_at ON security_events(at)',
    ]
    for sql in statements:
        c.execute(sql)
    # Preserve account hashes and active sessions while extending the role CHECK.
    # Rebuild both related tables with foreign keys enabled, inside one savepoint.
    definition=c.execute("SELECT sql FROM sqlite_master WHERE name='auth_users'").fetchone()[0]
    if "'司机'" not in definition:
        activity_rows=list(c.execute('SELECT session_id,last_activity FROM auth_session_activity')) if c.execute("SELECT 1 FROM sqlite_master WHERE name='auth_session_activity'").fetchone() else []
        c.execute('SAVEPOINT owner_role_migration')
        try:
            c.execute(statements[0].replace('IF NOT EXISTS auth_users(', 'auth_users_v025('))
            c.execute(statements[1].replace('IF NOT EXISTS auth_sessions(', 'auth_sessions_v025(').replace('REFERENCES auth_users(id)', 'REFERENCES auth_users_v025(id)'))
            c.execute('INSERT INTO auth_users_v025 SELECT * FROM auth_users')
            c.execute('INSERT INTO auth_sessions_v025 SELECT * FROM auth_sessions')
            c.execute('DROP TABLE IF EXISTS auth_session_activity')
            c.execute('DROP TABLE auth_sessions')
            c.execute('DROP TABLE auth_users')
            c.execute('ALTER TABLE auth_users_v025 RENAME TO auth_users')
            c.execute('ALTER TABLE auth_sessions_v025 RENAME TO auth_sessions')
            c.execute(statements[2]);c.execute(statements[3])
            if c.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('账号角色迁移引用核对失败')
            c.execute('RELEASE owner_role_migration')
        except Exception:
            c.execute('ROLLBACK TO owner_role_migration');c.execute('RELEASE owner_role_migration');raise
    c.execute('''CREATE TABLE IF NOT EXISTS auth_session_activity(
        session_id TEXT PRIMARY KEY REFERENCES auth_sessions(id) ON DELETE CASCADE,
        last_activity INTEGER NOT NULL)''')
    if 'activity_rows' in locals():c.executemany('INSERT OR IGNORE INTO auth_session_activity VALUES(?,?)',activity_rows)

def access_schema(c, ctx):
    sql="CREATE TABLE IF NOT EXISTS role_permissions(role TEXT PRIMARY KEY CHECK(role IN ('库管','会计','出纳','老板','厂长','物流负责人','司机')),version INTEGER NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL)"
    c.execute(sql)
    definition=c.execute("SELECT sql FROM sqlite_master WHERE name='role_permissions'").fetchone()[0]
    if "'司机'" not in definition:
        c.execute('SAVEPOINT owner_permissions_migration')
        try:
            c.execute(sql.replace('IF NOT EXISTS role_permissions(', 'role_permissions_v025('))
            c.execute('INSERT INTO role_permissions_v025 SELECT * FROM role_permissions')
            c.execute('DROP TABLE role_permissions')
            c.execute('ALTER TABLE role_permissions_v025 RENAME TO role_permissions')
            c.execute('RELEASE owner_permissions_migration')
        except Exception:
            c.execute('ROLLBACK TO owner_permissions_migration');c.execute('RELEASE owner_permissions_migration');raise



def expense_payables_v040(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='expense_payables_v040'").fetchone():
        for role in ('会计','出纳'):
            row=c.execute('SELECT payload FROM role_permissions WHERE role=?',(role,)).fetchone()
            if not row:continue
            value=json.loads(row[0]);before=json.loads(row[0]);modules=value.get('modules',[]);actions=value.get('actions',[])
            eligible='finance.costs' in modules if role=='会计' else bool(set(actions)&{'purchases.pay','finance.receipt','payroll.pay'})
            if not eligible:continue
            value['modules']=list(dict.fromkeys([*modules,'finance.expense-payables']))
            if role=='出纳':value['actions']=list(dict.fromkeys([*actions,'costs.review','costs.pay']))
            if value!=before:
                c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role=?",(json.dumps(value,ensure_ascii=False),role))
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='auth_sessions'").fetchone():c.execute('DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM auth_users WHERE role=?)',(role,))
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='security_events'").fetchone():c.execute('INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)',(__import__('time').time().__int__(),'permissions.migrate',None,role,json.dumps({'before':before,'after':value,'reason':'间接成本核对与付款'},ensure_ascii=False)))
        c.execute("INSERT INTO meta VALUES('expense_payables_v040','1')")

def accountant_weight_handoff_v037(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='accountant_weight_handoff_v037'").fetchone():
        row=c.execute("SELECT payload FROM role_permissions WHERE role='会计'").fetchone()
        if row:
            value=json.loads(row[0]);before=json.loads(row[0])
            if 'delivery.weighing' in value.get('modules',[]) and 'orders.write' in value.get('actions',[]):
                value['actions']=list(dict.fromkeys([*value.get('actions',[]),'weight.confirm']))
                if value!=before:
                    c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role='会计'",(json.dumps(value,ensure_ascii=False),))
                    if c.execute("SELECT 1 FROM sqlite_master WHERE name='auth_sessions'").fetchone():c.execute("DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM auth_users WHERE role='会计')")
                    if c.execute("SELECT 1 FROM sqlite_master WHERE name='security_events'").fetchone():c.execute("INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)",(__import__('time').time().__int__(),'permissions.migrate',None,'会计',json.dumps({'before':before,'after':value,'reason':'v0.37 两岗称重交接'},ensure_ascii=False)))
        c.execute("INSERT INTO meta VALUES('accountant_weight_handoff_v037','1')")

def driver_weights_v0351(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='driver_weights_v0351'").fetchone():
        row=c.execute("SELECT payload FROM role_permissions WHERE role='司机'").fetchone()
        if row:
            value=json.loads(row[0]);value['modules']=list(dict.fromkeys([*value.get('modules',[]),'delivery.driver']));value['actions']=list(dict.fromkeys([*value.get('actions',[]),'driver.weights']))
            c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role='司机'",(json.dumps(value,ensure_ascii=False),))
        c.execute("INSERT INTO meta VALUES('driver_weights_v0351','1')")

def driver_permissions_v035(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='driver_permissions_v035'").fetchone():
        row=c.execute("SELECT payload FROM role_permissions WHERE role='库管'").fetchone()
        if row:
            value=json.loads(row[0]);value['modules']=list(dict.fromkeys([*value.get('modules',[]),'asset.crates']));value['actions']=list(dict.fromkeys([*value.get('actions',[]),'crates.confirm','crates.write']))
            c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role='库管'",(json.dumps(value,ensure_ascii=False),))
        c.execute("INSERT INTO meta VALUES('driver_permissions_v035','1')")

def asset_permissions_v034(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='asset_permissions_v034'").fetchone():
        for role in ('库管','会计','老板'):
            row=c.execute('SELECT payload FROM role_permissions WHERE role=?',(role,)).fetchone()
            if not row:continue
            value=json.loads(row[0]);value['modules']=list(dict.fromkeys([*value.get('modules',[]),'asset.register','asset.crates']))
            value['actions']=list(dict.fromkeys([*value.get('actions',[]),*(['crates.write','assets.write'] if role=='会计' else ['crates.write'] if role=='库管' else [])]))
            c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role=?",(json.dumps(value,ensure_ascii=False),role))
        c.execute("INSERT INTO meta VALUES('asset_permissions_v034','1')")

def payroll_permissions_v033(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='payroll_permissions_v033'").fetchone():
        for role,action in [('会计','payroll.write'),('出纳','payroll.pay'),('老板',None)]:
            row=c.execute('SELECT payload FROM role_permissions WHERE role=?',(role,)).fetchone()
            if not row:continue
            value=json.loads(row[0]);value['modules']=list(dict.fromkeys([*value.get('modules',[]),'finance.payroll']))
            if action:value['actions']=list(dict.fromkeys([*value.get('actions',[]),action]))
            c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role=?",(json.dumps(value,ensure_ascii=False),role))
        c.execute("INSERT INTO meta VALUES('payroll_permissions_v033','1')")

def resource_schema(c, ctx):
    for statement in "CREATE TABLE IF NOT EXISTS material_items(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,category TEXT NOT NULL,unit TEXT NOT NULL,reorder_qty TEXT NOT NULL DEFAULT '0',active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1);\n    CREATE TABLE IF NOT EXISTS material_entries(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL);\n    CREATE TABLE IF NOT EXISTS indirect_expenses(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL);\n    CREATE TABLE IF NOT EXISTS expense_reviews(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL);\n    CREATE TABLE IF NOT EXISTS expense_payments(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL);\n    CREATE TABLE IF NOT EXISTS byproduct_sales(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL);\n    CREATE TABLE IF NOT EXISTS resource_periods(month TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL);".split(';'):
        if statement.strip():c.execute(statement)

def material_fifo(c, ctx):
    c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('material_fifo_start',?)",(str(c.execute("SELECT COALESCE(MAX(json_extract(payload,'$.sequence')),0)+1 FROM material_entries").fetchone()[0]),))

def material_catalog(c, ctx):
    for mid,name,cat,unit in rc.MATERIALS:c.execute('INSERT OR IGNORE INTO material_items(id,name,category,unit) VALUES(?,?,?,?)',(mid,name,cat,unit))

def material_units(c, ctx):
    if not c.execute("SELECT 1 FROM material_entries WHERE json_extract(payload,'$.material_id')='P-OTHER' LIMIT 1").fetchone():c.execute("UPDATE material_items SET name='其他消耗包装（膜等）' WHERE id='P-OTHER' AND name='其他包装（框/膜等）'")
    # Correct unused catalog units only; posted quantities must never be relabeled.
    for mid,unit in [('P-CLOTH','公斤'),('P-BAG','包')]:
        ordered=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='purchase_orders'").fetchone() and c.execute("SELECT 1 FROM purchase_orders,json_each(purchase_orders.payload,'$.lines') AS line WHERE json_extract(line.value,'$.material_id')=? LIMIT 1",(mid,)).fetchone()
        if not ordered and not c.execute("SELECT 1 FROM material_entries WHERE json_extract(payload,'$.material_id')=? LIMIT 1",(mid,)).fetchone():
            c.execute('UPDATE material_items SET unit=?,version=version+1 WHERE id=? AND unit<>?',(unit,mid,unit))

def purchase_schema(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS suppliers(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,version INTEGER NOT NULL,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS purchase_payees(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(kind,name))')
    for t in purchasing.TABLES:c.execute('CREATE TABLE IF NOT EXISTS '+t+'(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)')

def payroll_schema(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS payroll_records(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)')

def production_schema(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS factory_parameter_requests(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)')
    for table in pm.TABLES.values():c.execute('CREATE TABLE IF NOT EXISTS '+table+'(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)')
    c.execute("CREATE TABLE IF NOT EXISTS factory_settings(id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL)")
    c.execute('INSERT OR IGNORE INTO factory_settings VALUES(?,?,?)',('default',1,rc.dump(pm.DEFAULTS)))
    for gid,name in [('G-SKIN','豆皮组'),('G-TOFU','豆腐组'),('G-DRY','豆干组')]:
        c.execute('INSERT OR IGNORE INTO factory_groups VALUES(?,?,?)',(gid,'seed:'+gid,rc.dump({'id':gid,'name':name,'active':True,'version':1})))

def payroll_profiles(c, ctx):
    payroll.ensure_profiles(c)

def asset_schema(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS asset_records(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS asset_submissions(request_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    for key,name in assets.CRATES.items():
        record={'id':key,'kind':'asset','name':name,'category':'周转筐','unit':'个','location':'厂内','custodian':'库管','note':'数量以每日筐子盘点及产品库存为准','version':1,'active':True}
        c.execute('INSERT OR IGNORE INTO asset_records VALUES(?,?,?)',(key,'seed:'+key,rc.dump(record)))
    # Historical material transactions retain their original quantities and values.
    for key in assets.CRATES:c.execute('UPDATE material_items SET active=0,version=version+1 WHERE id=? AND active<>0',(key,))

def driver_schema(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS driver_accounts(user_id TEXT PRIMARY KEY,driver_id TEXT NOT NULL UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS driver_weight_submissions(request_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS driver_return_submissions(request_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS driver_return_requests(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)')
    c.execute('INSERT OR IGNORE INTO driver_return_submissions SELECT request_key,payload FROM driver_return_requests')

def production_directory(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS production_config_versions(version INTEGER PRIMARY KEY,effective_date TEXT NOT NULL,payload TEXT NOT NULL)')

def bootstrap(c, ctx):
    demo=ctx.get('demo',False)
    if not demo and not c.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone():
        c.execute("INSERT OR IGNORE INTO meta VALUES('dispatch_initialized','1')")
        c.execute("INSERT OR IGNORE INTO meta VALUES('initialized','1')")
        c.execute("INSERT OR IGNORE INTO meta VALUES('settlement_unit','公斤')")
    if demo and not c.execute("SELECT 1 FROM meta WHERE key='dispatch_initialized'").fetchone():
        c.executemany('INSERT INTO delivery_markets(id,name,city) VALUES(?,?,?)',[(f'M{i:03}',name,city) for i,(name,city) in enumerate([('新联','乌鲁木齐'),('北园春','乌鲁木齐'),('豫园春','乌鲁木齐'),('岐峰','昌吉'),('亚中','昌吉'),('汇好','昌吉')],1)])
        c.executemany('INSERT INTO delivery_vehicles(id,name) VALUES(?,?)',[('V001','车 A'),('V002','车 B')])
        c.execute("INSERT INTO meta VALUES('dispatch_initialized','1')")
    if demo and not c.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone():
        c.executemany('INSERT INTO customers(id,name,route,note) VALUES(?,?,?,?)',[
          ('C001','演示·乌鲁木齐一店','乌鲁木齐线','虚构客户，用于流程验证'),('C002','演示·昌吉批发客户','昌吉线','按普通客户结算，不管理市场内部经营'),('C003','演示·米泉二店','米泉线','虚构客户，用于流程验证')])
        c.executemany('INSERT INTO products VALUES(?,?,?,?,?,?)',[
          ('P001','大豆腐','筐','3.60','1.8',None),('P002','中豆腐','筐','3.80','1.8',None),('P003','白豆干','筐','6.20','1.5',None),
          ('P004','千张（豆皮）','包','75','0','10'),('P005','素鸡','包','65','0','10'),('P006','熏干','筐','8.00','1.5',None)])
        c.execute("INSERT INTO rules VALUES('C002','P001','3.50','1.7')")
        c.execute("INSERT INTO meta VALUES('initialized','1')")

def operator_catalog(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='operator_users_initialized'").fetchone():
        c.executemany('INSERT OR IGNORE INTO operator_users(id,name,role) VALUES(?,?,?)',[('OP-CASHIER','出纳','出纳'),('OP-ACCOUNTANT','会计','会计'),('OP-WAREHOUSE','库管','库管')])
        c.execute("INSERT INTO meta VALUES('operator_users_initialized','1')")

def driver_catalog(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='driver_catalog_initialized'").fetchone():
        names=[]
        for (raw,) in c.execute('SELECT payload FROM dispatch_plans'):
            for trip in json.loads(raw).get('trips',[]):
                for name in re.split(r'[，,、；;]+',trip.get('driver','')):
                    name=name.strip()
                    if name and len(name)<=50 and name not in names:names.append(name)
        numbers=[int(r[0][1:]) for r in c.execute('SELECT id FROM delivery_drivers') if re.fullmatch(r'D[0-9]+',r[0])]
        next_id=max(numbers,default=0)
        for name in names:
            if not c.execute('SELECT 1 FROM delivery_drivers WHERE name=?',(name,)).fetchone():
                next_id+=1;c.execute('INSERT INTO delivery_drivers(id,name) VALUES(?,?)',('D'+str(next_id).zfill(3),name))
        c.execute("INSERT INTO meta VALUES('driver_catalog_initialized','1')")

def customer_locations(c, ctx):
    if not c.execute("SELECT 1 FROM meta WHERE key='customer_locations_v09'").fetchone():
        # Only exact matches are safe to migrate; retain unmatched legacy descriptions.
        for m in c.execute('SELECT * FROM delivery_markets').fetchall():
            c.execute("UPDATE customers SET region=?,market_id=?,location_kind=? WHERE route=? AND market_id=''",
                      (m['city'],m['id'],m['kind'],m['name']))
        c.execute("INSERT INTO meta VALUES('customer_locations_v09','1')")

def product_materials(c, ctx):
    material_row=c.execute("SELECT value FROM meta WHERE key='product_main_materials'").fetchone();materials=json.loads(material_row[0]) if material_row else {}
    for product in c.execute('SELECT id,name FROM products'):
        if product['id'] not in materials:materials[product['id']]=pm.daily.main_material(c,product)
    if not c.execute("SELECT 1 FROM meta WHERE key='smoked_tofu_material_v0361'").fetchone():
        for product in c.execute("SELECT id,name FROM products WHERE name LIKE '%熏干%'").fetchall():
            if materials.get(product['id']) in ('黄豆','大豆'):
                before={'main_material':materials[product['id']]};materials[product['id']]='白干'
                ctx['audit'](c,'系统','修正熏干主要原料',product['id'],before,{'main_material':'白干'})
        c.execute("INSERT INTO meta VALUES('smoked_tofu_material_v0361','1')")
    if materials:c.execute("INSERT INTO meta VALUES('product_main_materials',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(rc.dump(materials),))

def directory_baseline(c, ctx):
    pc.ensure_seed(c)

def billing_kilograms(c, ctx):
    now=ctx['now'];audit=ctx['audit']
    if __import__('billing').enabled(c):return {'already_enabled':True}
    def dump(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
    def fmt(v):return format(Decimal(v).normalize(),'f')
    def convert(price,standard):
        kg=Decimal(standard or '0')
        if kg<=0:raise ValueError('包装标准公斤数缺失，不能换算包价')
        result=Decimal(price)/kg
        if result<=0 or result.as_tuple().exponent < -3:
            raise ValueError('包价换算公斤价后超过3位小数，请先核定价格：'+str(price)+' / '+str(standard))
        return fmt(result)
    products={r['id']:dict(r) for r in c.execute('SELECT * FROM products')}
    changes={'products':[],'rules':0,'orders':0,'returns':0,'archived_orders':0}
    for p in products.values():
        if p['unit']!='包':continue
        price=convert(p['price'],p['standard_kg'])
        c.execute('UPDATE products SET price=? WHERE id=?',(price,p['id']))
        changes['products'].append({'id':p['id'],'name':p['name'],'old_package_price':p['price'],'standard_kg':p['standard_kg'],'price_per_kg':price})
    for r in list(c.execute('SELECT * FROM rules')):
        p=products[r['product_id']]
        if p['unit']=='包':
            c.execute('UPDATE rules SET price=? WHERE customer_id=? AND product_id=?',(convert(r['price'],p['standard_kg']),r['customer_id'],r['product_id']));changes['rules']+=1
    for table in ('orders','archived_orders'):
        for row in list(c.execute('SELECT * FROM '+table)):
            o=json.loads(row['payload']);changed=False
            for l in o['lines']:
                if l['unit']=='包' and l.get('billing_unit')!='公斤':
                    standard=l.get('standard_kg') or products[l['product_id']]['standard_kg']
                    l['legacy_billing']={'unit':'包','price':l['price'],'bill_qty':l.get('bill_qty'),'at':now()}
                    l['price']=convert(l['price'],standard)
                    if l.get('bill_qty') is not None:l['bill_qty']=fmt(Decimal(l['bill_qty'])*Decimal(standard))
                    if l.get('settlement_mode') not in (None,'not_shipped'):l['settlement_mode']='package_standard'
                    l['standard_kg']=standard;changed=True
                l['billing_unit']='公斤'
            if changed:
                o['version']+=1;o['updated_at']=now()
                c.execute('UPDATE '+table+' SET payload=? WHERE id=?',(dump(o),row['id']));changes[table]+=1
    for row in list(c.execute('SELECT * FROM sales_returns')):
        r=json.loads(row['payload'])
        if r['unit']=='包' and r.get('billing_unit')!='公斤':
            standard=r.get('standard_kg') or products[r['product_id']]['standard_kg']
            r['legacy_billing']={'source_price':r.get('source_price'),'reference_price':r.get('reference_price'),'finance':r.get('finance'),'at':now()}
            for key in ('source_price','reference_price'):
                if r.get(key) is not None:r[key]=convert(r[key],standard)
            f=r.get('finance')
            if f:
                f['account_qty']=fmt(Decimal(f['account_qty'])*Decimal(standard));f['original_price']=convert(f['original_price'],standard)
                f['billing_unit']='公斤';f['account_weight_kg']=f['account_qty'];f['weight_basis']='历史包装数量折算，原核定金额保留'
            r['billing_unit']='公斤';r['version']+=1
            c.execute('UPDATE sales_returns SET payload=? WHERE id=?',(dump(r),row['id']));changes['returns']+=1
    c.execute("INSERT INTO meta VALUES('settlement_unit','公斤') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    # An old open tab contains package prices; it must never resubmit them as kg prices.
    c.execute("INSERT INTO meta VALUES('business_data_epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(secrets.token_hex(12),))
    audit(c,'会计','统一公斤结算，按标准包装重量换算包价','billing-unit-kg',None,changes)
    return changes


def asset_product_mappings(c,ctx):
    defaults={'大豆腐':'P-LARGE','中豆腐':'P-MEDIUM','熏干':'P-SMOKED','魔芋':'P-KONJAC'}
    for product in c.execute("SELECT id,name FROM products WHERE unit='筐'").fetchall():
        if product['name'] not in defaults or any(r['kind']=='mapping' and r['product_id']==product['id'] for r in assets.rows(c)):continue
        record={'id':'MAP-'+product['id'],'kind':'mapping','product_id':product['id'],'asset_id':defaults[product['name']],'version':1}
        c.execute('INSERT OR IGNORE INTO asset_records VALUES(?,?,?)',(record['id'],'seed-map:'+product['id'],rc.dump(record)))


def collaboration_schema(c, ctx):
    """Internal chat, notification inbox and administrator feedback tickets."""
    statements = [
        'CREATE TABLE IF NOT EXISTS chat_threads(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS chat_messages(id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,request_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS chat_messages_thread ON chat_messages(thread_id)',
        'CREATE TABLE IF NOT EXISTS chat_reads(thread_id TEXT NOT NULL,user_id TEXT NOT NULL,last_read_seq INTEGER NOT NULL DEFAULT 0,last_read_at TEXT NOT NULL DEFAULT \'\',PRIMARY KEY(thread_id,user_id))',
        'CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,created_at TEXT NOT NULL,read_at TEXT NOT NULL DEFAULT \'\',payload TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id,read_at,created_at)',
        'CREATE TABLE IF NOT EXISTS feedback_tickets(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,user_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,payload TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS feedback_tickets_user ON feedback_tickets(user_id,updated_at)',
    ]
    for statement in statements:
        c.execute(statement)
    stamp = ctx['now']()
    group = {'id': 'GROUP-ALL', 'kind': 'group', 'title': '全员群', 'member_ids': ['@all'], 'created_by': 'system',
             'created_at': stamp, 'updated_at': stamp, 'last_message_at': '', 'version': 1}
    c.execute('INSERT OR IGNORE INTO chat_threads VALUES(?,?,?)', ('GROUP-ALL', 'system:group-all', json.dumps(group, ensure_ascii=False, separators=(',', ':'))))


def collaboration_permissions(c, ctx):
    """Grant the new collaboration menus to existing saved role configurations."""
    modules = ['workspace.chat', 'system.feedback']
    changed = []
    for (role,) in c.execute('SELECT role FROM role_permissions ORDER BY role').fetchall():
        row = c.execute('SELECT version,payload FROM role_permissions WHERE role=?', (role,)).fetchone()
        value = json.loads(row['payload'])
        before = list(value.get('modules', []))
        value['modules'] = list(dict.fromkeys([*before, *modules]))
        if value['modules'] == before:
            continue
        c.execute('UPDATE role_permissions SET version=version+1,payload=?,updated_at=? WHERE role=?',
                  (json.dumps(value, ensure_ascii=False), ctx['now'](), role))
        changed.append({'role': role, 'added': [m for m in modules if m not in before]})
    if changed:
        ctx['audit'](c, '管理员', '开通内部聊天与问题反馈', 'role-permissions', None, changed)


def customer_delivery_trade(c, ctx):
    if 'phone' not in {r[1] for r in c.execute('PRAGMA table_info(customers)')}:
        c.execute("ALTER TABLE customers ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
    c.execute('CREATE TABLE IF NOT EXISTS trade_records(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS trade_submissions(request_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    for key,name in [('CR-YELLOW','黄框'),('CR-WHITE','白框'),('CR-CLOTH','布')]:
        r={'id':key,'kind':'asset','name':name,'category':'周转筐','unit':'个','location':'','custodian':'','active':True,'version':1,'note':'大豆腐周转规格，可在资产台账扩展','handler':'系统迁移','updated_at':ctx['now']()}
        c.execute('INSERT OR IGNORE INTO asset_records VALUES(?,?,?)',(key,'trade-type:'+key,json.dumps(r,ensure_ascii=False)))


def gel_tofu_system(c, ctx):
    import copy
    versions=pc.history(c)
    if not versions:return
    latest=max(versions,key=lambda v:v['version'])
    if any(s['id']=='gel-tofu' or '内脂' in s['name'] or '内酯' in s['name'] for s in latest['systems']):return
    value=copy.deepcopy(latest)
    value['systems'].append({'id':'gel-tofu','name':'内脂豆腐磨浆系统','active':True,'material_id':'RM-SOY','warehouse_ids':['WH-TOFU'],'default_warehouse_id':'WH-TOFU','soak_kg':'','direct_bean_only':True,'allocation_mode':'proportional','residual_product_id':''})
    for p in c.execute('SELECT id,name FROM products'):
        if '内脂' in p['name'] or '内酯' in p['name']:
            value['products'][p['id']]={'default_system_id':'gel-tofu','system_ids':['gel-tofu'],'process_ids':[]}
    value.update(version=max(v['version'] for v in versions)+1,effective_date=max(ctx['now']()[:10],latest['effective_date']),published_at=ctx['now'](),published_by='系统升级',note='新增内脂豆腐独立上豆系统；按实称干豆登记，泡豆桶换算待现场核定')
    c.execute('INSERT INTO production_config_versions VALUES(?,?,?)',(value['version'],value['effective_date'],json.dumps(value,ensure_ascii=False)))


def accounting_crate_attributes(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS customer_crate_tares(customer_id TEXT NOT NULL,product_id TEXT NOT NULL,variant_id TEXT NOT NULL,tare TEXT NOT NULL,version INTEGER NOT NULL,PRIMARY KEY(customer_id,product_id,variant_id))')
    for key,name in [('CR-YELLOW','黄框'),('CR-WHITE','白框'),('CR-CLOTH','布')]:
        row=c.execute('SELECT payload FROM asset_records WHERE id=?',(key,)).fetchone()
        if row:
            value=json.loads(row[0]);value.update(parent_asset_id='P-LARGE',attribute_kind='color' if key!='CR-CLOTH' else 'material',attribute_name=name)
            c.execute('UPDATE asset_records SET payload=? WHERE id=?',(json.dumps(value,ensure_ascii=False),key))


def purchased_finished_goods(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS finished_goods_records(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS finished_goods_submissions(request_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')


def gel_tofu_standard_output(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS gel_daily_outputs(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    rule={'effective_date':ctx['now']()[:10],'dry_kg':'50','output_qty':'10','unit':'盒'}
    c.execute("INSERT OR IGNORE INTO meta VALUES('gel_tofu_output_standard',?)",(json.dumps(rule,ensure_ascii=False),))


def order_corrections(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS order_corrections(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS order_correction_submissions(request_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS statement_voids(document_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')


def product_unit_defaults(c, ctx):
    """公斤产品固定按1换算、不保留平均净重；筐产品不带标准包装；其余单位只在按公斤计价时保留换算。"""
    kg=c.execute("UPDATE products SET standard_kg='1', tare='0' WHERE unit='公斤' AND (standard_kg IS NOT '1' OR tare IS NOT '0')").rowcount
    basket=c.execute("UPDATE products SET standard_kg=NULL WHERE unit='筐' AND standard_kg IS NOT NULL").rowcount
    row=c.execute("SELECT value FROM meta WHERE key='product_trade'").fetchone()
    configs=json.loads(row[0]) if row else {}
    other=0
    for r in c.execute("SELECT id FROM products WHERE unit NOT IN ('公斤','筐')").fetchall():
        if (configs.get(r[0]) or {}).get('billing_unit','公斤')!='公斤':
            other+=c.execute("UPDATE products SET standard_kg=NULL WHERE id=? AND standard_kg IS NOT NULL",(r[0],)).rowcount
    cleared=0
    avg=c.execute("SELECT value FROM meta WHERE key='product_average_weights'").fetchone()
    if avg:
        values=json.loads(avg[0]);changed=False
        for r in c.execute("SELECT id FROM products WHERE unit='公斤'").fetchall():
            if values.get(r[0]) is not None:values[r[0]]=None;changed=True
        if changed:
            c.execute("UPDATE meta SET value=? WHERE key='product_average_weights'",(json.dumps(values,ensure_ascii=False),));cleared=1
    if kg or basket or other or cleared:
        ctx['audit'](c,'管理员','统一计量单位默认规则','product-unit-defaults',None,{'公斤产品':kg,'筐产品':basket,'其它单位':other,'平均净重清理':cleared})


def fund_accounts(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS fund_accounts(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS fund_assignments(movement_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS fund_transfers(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL)')
    # Only extend roles already entrusted with financial data, preserving custom restrictions.
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='role_permissions'").fetchone():return
    for row in c.execute('SELECT role,payload FROM role_permissions').fetchall():
        value=json.loads(row[1]);mods=value.get('modules',[]);actions=value.get('actions',[])
        if not set(mods)&{'finance.receivables','finance.payables','workspace.analytics'}:continue
        if 'finance.accounts' in mods:continue
        value['modules']=[*mods,'finance.accounts']
        if row[0] in ('会计','出纳') and set(actions)&{'finance.receipt','purchases.pay','finance.alert-settings'}:value['actions']=[*actions,'funds.manage']
        c.execute('UPDATE role_permissions SET payload=?,version=version+1,updated_at=? WHERE role=?',(json.dumps(value,ensure_ascii=False),ctx['now'](),row[0]))


def byproduct_customers(c, ctx):
    """Give legacy buyers dedicated customer identities; never guess a same-name identity."""
    if 'business_kind' not in {r[1] for r in c.execute('PRAGMA table_info(customers)')}:
        c.execute("ALTER TABLE customers ADD COLUMN business_kind TEXT NOT NULL DEFAULT 'sales'")
    c.execute('CREATE TABLE IF NOT EXISTS byproduct_statements(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,customer_id TEXT NOT NULL,month TEXT NOT NULL,payload TEXT NOT NULL,content_hash TEXT NOT NULL)')
    row=c.execute("SELECT value FROM meta WHERE key='byproduct_settlement'").fetchone()
    cfg=json.loads(row[0]) if row else {}
    records=[(r[0],json.loads(r[1])) for r in c.execute('SELECT id,payload FROM byproduct_sales')]
    names={str(r.get('buyer') or '').strip() for _,r in records if not r.get('customer_id')}
    if cfg.get('buyer') and not cfg.get('customer_id'):names.add(cfg['buyer'].strip())
    links={};numbers=[int(r[0][1:]) for r in c.execute('SELECT id FROM customers') if re.fullmatch(r'C[0-9]+',r[0])]
    number=max(numbers,default=0)
    for name in sorted(names):
        if not name:continue
        number+=1;cid='C'+str(number).zfill(3);links[name]=cid
        c.execute("INSERT INTO customers(id,name,route,note,delivery_method,legal_name,business_kind) VALUES(?,?,?,?,'pickup',?,'byproduct')",(cid,name,'豆渣自取','由原豆渣购货方建立，请核对联系电话和结算名称',name))
    changed=[]
    for rid,r in records:
        cid=links.get(str(r.get('buyer') or '').strip())
        if r.get('customer_id') or not cid:continue
        r['customer_id']=cid;r['version']=r.get('version',1)+1
        c.execute('UPDATE byproduct_sales SET payload=? WHERE id=?',(json.dumps(r,ensure_ascii=False),rid));changed.append(rid)
    if not cfg.get('customer_id') and cfg.get('buyer','').strip() in links:
        cfg['customer_id']=links[cfg['buyer'].strip()];cfg['version']=cfg.get('version',0)+1
        c.execute("UPDATE meta SET value=? WHERE key='byproduct_settlement'",(json.dumps(cfg,ensure_ascii=False),))
    if links or changed:ctx['audit'](c,'管理员','建立历史豆渣客户关联','byproduct-customers',None,{'customers':links,'records':changed,'money_unchanged':True})


def merge_sales_reports(c, ctx):
    """Sales daily and monthly share one page; keep one module id and carry grants."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='role_permissions'").fetchone():return
    changed=[]
    for row in c.execute('SELECT role,payload FROM role_permissions').fetchall():
        value=json.loads(row[1]);modules=value.get('modules')
        if not isinstance(modules,list) or 'sales.monthly' not in modules:continue
        value['modules']=list(dict.fromkeys(['sales.reports' if m=='sales.monthly' else m for m in modules]))
        c.execute('UPDATE role_permissions SET payload=? WHERE role=?',(json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True),row[0]))
        changed.append(row[0])
    if changed:ctx['audit'](c,'管理员','合并销售日报与月报模块授权','sales.reports',None,{'roles':changed})


def supplier_categories(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS supplier_categories(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    catalog=[{'id':'SC-RAW','name':'原辅料','kind':'raw'},{'id':'SC-FINISHED','name':'外购成品','kind':'finished'},{'id':'SC-OTHER','name':'其他','kind':'other'}]
    for item in catalog:
        c.execute('INSERT OR IGNORE INTO supplier_categories VALUES(?,?)',(item['id'],json.dumps({**item,'active':True,'version':1},ensure_ascii=False)))
    row=c.execute("SELECT value FROM meta WHERE key='product_trade'").fetchone()
    configs=json.loads(row[0]) if row else {}
    linked={sid for p in configs.values() if p.get('supply_kind') in ('purchased','mixed') for sid in p.get('supplier_ids',[])}
    linked|={json.loads(r[0])['supplier_id'] for r in c.execute('SELECT payload FROM finished_goods_records') if json.loads(r[0]).get('kind')=='receipt'}
    for sid,raw in c.execute('SELECT id,payload FROM suppliers').fetchall():
        s=json.loads(raw)
        if 'category_ids' in s:continue
        # The old free text stays as a description; eligibility follows actual links.
        s['category_ids']=['SC-FINISHED'] if sid in linked else ['SC-RAW']
        c.execute('UPDATE suppliers SET payload=? WHERE id=?',(json.dumps(s,ensure_ascii=False),sid))


def production_system_names(c, ctx):
    """Write explicit directory names once; display code uses the stored name verbatim."""
    names={'tofu':'豆腐磨浆系统','skin':'豆皮磨浆系统','gel-tofu':'内脂磨浆系统'}
    counts={}
    def directory(value):
        changed=False
        for system in value.get('systems',[]):
            if not isinstance(system,dict):continue
            name=names.get(system.get('id'))
            if name and system.get('name')!=name:system['name']=name;changed=True
        return changed
    for version,raw in c.execute('SELECT version,payload FROM production_config_versions').fetchall():
        value=json.loads(raw)
        if directory(value):
            c.execute('UPDATE production_config_versions SET payload=? WHERE version=?',(json.dumps(value,ensure_ascii=False),version));counts['production_config_versions']=counts.get('production_config_versions',0)+1
    for table in ('factory_daily','factory_runs','factory_scrap','material_entries'):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
        for rid,raw in c.execute('SELECT id,payload FROM '+table).fetchall():
            value=json.loads(raw);changed=False
            if isinstance(value.get('config_snapshot'),dict):changed=directory(value['config_snapshot'])
            name=names.get(value.get('production_system_id'))
            if name and value.get('production_system_name')!=name:
                old_name=value.get('production_system_name');value['production_system_name']=name;changed=True
                for field in ('department','cost_target'):
                    if old_name and value.get(field)==old_name:value[field]=name
            for product in value.get('products',[]):
                name=names.get(product.get('system'))
                if name and product.get('system_name')!=name:product['system_name']=name;changed=True
            if changed:
                c.execute('UPDATE '+table+' SET payload=? WHERE id=?',(json.dumps(value,ensure_ascii=False),rid));counts[table]=counts.get(table,0)+1
    if counts:ctx['audit'](c,'管理员','填写磨浆系统完整名称','production-system-names',None,{'names':names,'rows':counts,'quantities_and_amounts_unchanged':True})


def administrative_role(c,ctx):
    """Extend role constraints while preserving accounts, sessions and activity."""
    import re
    definitions={t:c.execute('SELECT sql FROM sqlite_master WHERE name=?',(t,)).fetchone()[0] for t in ('auth_users','auth_sessions','auth_session_activity','role_permissions')}
    if "'行政负责人'" in definitions['auth_users']:return
    for table in ('auth_users','auth_sessions','auth_session_activity','role_permissions'):
        sql=definitions[table]
        sql=re.sub(r'CREATE TABLE (?:IF NOT EXISTS )?["`]?'+table+r'["`]?', 'CREATE TABLE '+table+'_v060',sql,count=1,flags=re.I)
        sql=sql.replace("'司机'","'司机','行政负责人'")
        sql=sql.replace('REFERENCES auth_users(', 'REFERENCES auth_users_v060(').replace('REFERENCES auth_sessions(', 'REFERENCES auth_sessions_v060(')
        sql=sql.replace('REFERENCES "auth_users"(', 'REFERENCES auth_users_v060(').replace('REFERENCES "auth_sessions"(', 'REFERENCES auth_sessions_v060(')
        c.execute(sql);c.execute('INSERT INTO '+table+'_v060 SELECT * FROM '+table)
    for table in ('auth_session_activity','auth_sessions','auth_users','role_permissions'):c.execute('DROP TABLE '+table)
    for table in ('auth_users','auth_sessions','auth_session_activity','role_permissions'):c.execute('ALTER TABLE '+table+'_v060 RENAME TO '+table)
    c.execute('CREATE INDEX auth_sessions_user ON auth_sessions(user_id)');c.execute('CREATE INDEX auth_sessions_expiry ON auth_sessions(expires_at)')
    if c.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('行政角色升级引用检查失败')


def period_snapshot_status(c, ctx):
    """Correct one proven status warning; never recalculate frozen financial data."""
    import copy
    import hashlib
    warning={'field':'成本月份未结账，费用可能未录全','owner':'会计','target':'expenses'}
    for month,version,raw in c.execute('SELECT month,version,payload FROM resource_periods').fetchall():
        before=json.loads(raw)
        snapshot=before.get('report_snapshot')
        if before.get('state')!='closed' or not isinstance(snapshot,dict):continue
        if before.get('month')!=month or snapshot.get('month')!=month:continue
        gaps=snapshot.get('gaps')
        if not isinstance(gaps,list) or warning not in gaps:continue
        after=copy.deepcopy(before)
        after['report_snapshot']['gaps']=[g for g in gaps if g!=warning]
        canonical=lambda value:json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        after['version']=version+1
        after['snapshot_status_revision']={
            'migration':'064-period-snapshot-status','at':ctx['now'](),
            'previous_period_version':version,
            'before_snapshot_sha256':hashlib.sha256(canonical(snapshot)).hexdigest(),
            'after_snapshot_sha256':hashlib.sha256(canonical(after['report_snapshot'])).hexdigest(),
            'removed_warning_count':sum(g==warning for g in gaps),
        }
        c.execute('UPDATE resource_periods SET version=?,payload=? WHERE month=?',
                  (after['version'],json.dumps(after,ensure_ascii=False,sort_keys=True,separators=(',',':')),month))
        ctx['audit'](c,'管理员','修正已结成本快照状态提示',month,before,after)


def outsourced_delivery_categories(c, ctx):
    """Retire delivery wages and protect the transport settlement category.

    Only directory/settings metadata changes. Existing expense rows, amounts,
    dates, payment records and frozen category snapshots are left untouched.
    """
    row = c.execute("SELECT value FROM meta WHERE key='expense_category_settings'").fetchone()
    before = json.loads(row[0]) if row else {}
    after = json.loads(json.dumps(before))
    stamp = ctx['now']()
    changed = False

    wage = dict(after.get('wages-delivery') or {})
    desired = {
        'active': False,
        'retired': True,
        'retired_reason': '配送已外包，配送工资不再新增；已有计薪配置、历史工资与历史费用继续保留。',
    }
    if not wage.get('retired_at'): desired['retired_at'] = stamp
    if any(wage.get(key) != value for key, value in desired.items()):
        wage.update(desired)
        wage['version'] = int(wage.get('version', 0)) + 1
        after['wages-delivery'] = wage
        changed = True

    transport = dict(after.get('transport') or {})
    desired = {
        'name': '外包配送费',
        'group': '配送',
        'nature': '变动',
        'active': True,
        'payment_mode': 'payable',
        'counterparty_kind': 'logistics',
        'system_managed': True,
        'system_source': 'transport-settlement',
        'system_source_label': '运输月结',
        'system_note': '由车辆排班 → 运输月结按实际趟次生成，自动形成费用应付；不能手工重复登记或删除。',
    }
    if not transport.get('system_since'): desired['system_since'] = stamp
    if any(transport.get(key) != value for key, value in desired.items()):
        transport.update(desired)
        transport['version'] = int(transport.get('version', 0)) + 1
        after['transport'] = transport
        changed = True

    if not changed: return
    c.execute("INSERT INTO meta VALUES('expense_category_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (json.dumps(after, ensure_ascii=False, sort_keys=True, separators=(',', ':')),))
    ctx['audit'](c, '管理员', '调整外包配送费用分类', 'expense_category_settings', before, after)


def sales_query_indexes(c, ctx):
    """Expression indexes for indexed sales date/customer reads."""
    statements = (
        "CREATE INDEX IF NOT EXISTS orders_business_date_id ON orders(json_extract(payload,'$.business_date'),id)",
        "CREATE INDEX IF NOT EXISTS orders_customer_business_date_id ON orders(json_extract(payload,'$.customer_id'),json_extract(payload,'$.business_date'),id)",
        "CREATE INDEX IF NOT EXISTS orders_state_business_date_id ON orders(json_extract(payload,'$.state'),json_extract(payload,'$.business_date'),id)",
        "CREATE INDEX IF NOT EXISTS receipts_received_date_id ON receipts(json_extract(payload,'$.received_date'),id)",
        "CREATE INDEX IF NOT EXISTS receipts_order_id ON receipts(json_extract(payload,'$.order_id'),id)",
        "CREATE INDEX IF NOT EXISTS sales_returns_received_date_id ON sales_returns(json_extract(payload,'$.received_date'),id)",
        "CREATE INDEX IF NOT EXISTS sales_returns_order_id ON sales_returns(json_extract(payload,'$.order_id'),id)",
    )
    for statement in statements:
        c.execute(statement)
    ctx['audit'](c, '管理员', '建立销售日期查询索引', 'sales-query-indexes', None,
                 {'indexes': [statement.split(' ON ', 1)[0].split('EXISTS ', 1)[1] for statement in statements]})


def resource_query_indexes(c, ctx):
    """Read indexes only; preserve all business payloads and historical facts."""
    for table, name, field in (
        ('indirect_expenses','expenses_business_date_id','business_date'),
        ('indirect_expenses','expenses_period_id','period'),
        ('expense_payments','expense_payments_date_id','business_date'),
        ('expense_payments','expense_payments_expense_id','expense_id'),
        ('expense_reviews','expense_reviews_expense_id','expense_id'),
        ('byproduct_sales','byproducts_business_date_id','business_date'),
        ('byproduct_sales','byproducts_customer_id','customer_id'),
    ):
        c.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}(json_extract(payload,'$.{field}'),id)")
    ctx['audit'](c,'管理员','建立费用与豆渣查询索引','resource-query-indexes',None,{'migration':'067'})


def finance_cash_query_indexes(c, ctx):
    """Indexes for the read projection; no business facts or snapshots change."""
    for table, name, expression in (
        ('purchase_payments','purchase_payments_date_id',"json_extract(payload,'$.business_date')"),
        ('payroll_records','payroll_payment_kind_date_id',"json_extract(payload,'$.kind'),json_extract(payload,'$.business_date')"),
        ('finished_goods_records','finished_cash_kind_date_id',"json_extract(payload,'$.kind'),json_extract(payload,'$.business_date')"),
        ('fund_transfers','fund_transfers_date_id',"json_extract(payload,'$.business_date')"),
        ('orders','orders_state_settled_date_id',"json_extract(payload,'$.state'),substr(json_extract(payload,'$.settlement.at'),1,10)"),
        ('byproduct_sales','byproducts_created_date_id',"substr(json_extract(payload,'$.created_at'),1,10)"),
    ):
        c.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table}({expression},id)')
    ctx['audit'](c,'管理员','建立资金实际日期与确认日期查询索引','finance-cash-query-indexes',None,{'migration':'068'})


def expense_accrual_query(c, ctx):
    """Derived lookup only; inserts/edits/restores update it atomically in SQLite."""
    c.execute('CREATE TABLE IF NOT EXISTS expense_accrual_lookup(expense_id TEXT NOT NULL REFERENCES indirect_expenses(id) ON DELETE CASCADE,position INTEGER NOT NULL,period TEXT NOT NULL,amount_cents INTEGER NOT NULL,PRIMARY KEY(expense_id,position))')
    c.execute('CREATE INDEX IF NOT EXISTS expense_accrual_period_id ON expense_accrual_lookup(period,expense_id,position)')
    c.execute("CREATE INDEX IF NOT EXISTS expense_category_id ON indirect_expenses(json_extract(payload,'$.category'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS payroll_employee_month_payment ON payroll_records(json_extract(payload,'$.kind'),json_extract(payload,'$.month'),json_extract(payload,'$.employee_id'),id)")
    # An empty/missing accrual array retains the original single-month bill.
    c.execute("INSERT INTO expense_accrual_lookup SELECT e.id,CAST(a.key AS INTEGER),json_extract(a.value,'$.period'),json_extract(a.value,'$.amount_cents') FROM indirect_expenses e,json_each(e.payload,'$.accruals') a WHERE COALESCE(json_array_length(json_extract(e.payload,'$.accruals')),0)>0 ON CONFLICT(expense_id,position) DO NOTHING")
    c.execute("INSERT INTO expense_accrual_lookup SELECT id,0,json_extract(payload,'$.period'),json_extract(payload,'$.amount_cents') FROM indirect_expenses WHERE COALESCE(json_array_length(json_extract(payload,'$.accruals')),0)=0 ON CONFLICT(expense_id,position) DO NOTHING")
    for action in ('INSERT','UPDATE'):
        c.execute("CREATE TRIGGER IF NOT EXISTS expense_accrual_after_"+action.lower()+" AFTER "+action+" ON indirect_expenses BEGIN DELETE FROM expense_accrual_lookup WHERE expense_id=NEW.id; INSERT INTO expense_accrual_lookup SELECT NEW.id,CAST(a.key AS INTEGER),json_extract(a.value,'$.period'),json_extract(a.value,'$.amount_cents') FROM json_each(NEW.payload,'$.accruals') a WHERE COALESCE(json_array_length(json_extract(NEW.payload,'$.accruals')),0)>0; INSERT INTO expense_accrual_lookup SELECT NEW.id,0,json_extract(NEW.payload,'$.period'),json_extract(NEW.payload,'$.amount_cents') WHERE COALESCE(json_array_length(json_extract(NEW.payload,'$.accruals')),0)=0; END")
    c.execute('CREATE TRIGGER IF NOT EXISTS expense_accrual_after_delete AFTER DELETE ON indirect_expenses BEGIN DELETE FROM expense_accrual_lookup WHERE expense_id=OLD.id; END')
    ctx['audit'](c,'管理员','建立费用所属期查询派生索引','expense-accrual-query',None,{'migration':'069','source_unchanged':True})


def employee_bank_accounts(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS employee_bank_accounts(employee_id TEXT PRIMARY KEY REFERENCES factory_employees(id),payload TEXT NOT NULL)')
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS employee_bank_card_unique ON employee_bank_accounts(json_extract(payload,'$.bank_card'))")


def purchase_history_indexes(c, ctx):
    c.execute("CREATE INDEX IF NOT EXISTS purchase_orders_business_date_id ON purchase_orders(json_extract(payload,'$.business_date'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS purchase_orders_supplier_business_date_id ON purchase_orders(json_extract(payload,'$.supplier_id'),json_extract(payload,'$.business_date'),id)")
    for table in ('purchase_receipts','purchase_payments','purchase_charges'):
        c.execute("CREATE INDEX IF NOT EXISTS "+table+"_order_id ON "+table+"(json_extract(payload,'$.order_id'),id)")


def purchase_ledger_indexes(c, ctx):
    for table in ('purchase_receipts','purchase_payments','purchase_charges'):
        c.execute("CREATE INDEX IF NOT EXISTS "+table+"_business_date_id ON "+table+"(json_extract(payload,'$.business_date'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS purchase_receipts_supplier_business_date_id ON purchase_receipts(json_extract(payload,'$.supplier_id'),json_extract(payload,'$.business_date'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS purchase_charges_receipt_id ON purchase_charges(json_extract(payload,'$.receipt_id'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS purchase_payments_charge_id ON purchase_payments(json_extract(payload,'$.charge_id'),id)")


def reuse_purchase_payment_date_index(c, ctx):
    # 068 already owns this expression; retain 072's recorded checksum and
    # remove its redundant name so finance and procurement share one index.
    c.execute("CREATE INDEX IF NOT EXISTS purchase_payments_date_id ON purchase_payments(json_extract(payload,'$.business_date'),id)")
    c.execute('DROP INDEX IF EXISTS purchase_payments_business_date_id')


def inventory_history_indexes(c, ctx):
    c.execute("CREATE INDEX IF NOT EXISTS returns_customer_date_id ON sales_returns(json_extract(payload,'$.customer_id'),json_extract(payload,'$.received_date'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS returns_product_date_id ON sales_returns(json_extract(payload,'$.product_id'),json_extract(payload,'$.received_date'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS processing_business_date_id ON processing_batches(json_extract(payload,'$.business_date'),id)")


def material_history_indexes(c, ctx):
    c.execute("CREATE INDEX IF NOT EXISTS material_history_date_sequence_id ON material_entries(json_extract(payload,'$.business_date'),json_extract(payload,'$.sequence'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS material_history_item_date_sequence_id ON material_entries(json_extract(payload,'$.material_id'),json_extract(payload,'$.business_date'),json_extract(payload,'$.sequence'),id)")


def stock_history_indexes(c, ctx):
    c.execute("CREATE INDEX IF NOT EXISTS corrections_stock_anchor_kind_id ON order_corrections(json_extract(payload,'$.stock_anchor_date'),json_extract(payload,'$.kind'),id)")


def check_history_indexes(c, ctx):
    c.execute("CREATE INDEX IF NOT EXISTS trade_check_kind_date_id ON trade_records(json_extract(payload,'$.kind'),json_extract(payload,'$.business_date'),id)")


def receipt_evidence(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS receipt_evidence(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,mime TEXT NOT NULL,bytes INTEGER NOT NULL,width INTEGER,height INTEGER,filename TEXT NOT NULL,order_id TEXT NOT NULL DEFAULT \'\',actor_id TEXT NOT NULL DEFAULT \'\',actor_name TEXT NOT NULL DEFAULT \'\',created_at TEXT NOT NULL,provider TEXT NOT NULL DEFAULT \'\',engine TEXT NOT NULL DEFAULT \'\',status TEXT NOT NULL,message TEXT NOT NULL DEFAULT \'\',fields_json TEXT NOT NULL DEFAULT \'{}\',warnings_json TEXT NOT NULL DEFAULT \'[]\',raw_text TEXT NOT NULL DEFAULT \'\',confidence INTEGER NOT NULL DEFAULT 0,linked_receipt_id TEXT NOT NULL DEFAULT \'\',linked_order_id TEXT NOT NULL DEFAULT \'\',image BLOB)')
    c.execute('CREATE INDEX IF NOT EXISTS receipt_evidence_sha256 ON receipt_evidence(sha256)')
    c.execute('CREATE INDEX IF NOT EXISTS receipt_evidence_created_at ON receipt_evidence(created_at)')
    c.execute('CREATE INDEX IF NOT EXISTS receipt_evidence_order_id ON receipt_evidence(order_id)')
    c.execute('CREATE INDEX IF NOT EXISTS receipt_evidence_linked_receipt_id ON receipt_evidence(linked_receipt_id)')
    c.execute('CREATE TABLE IF NOT EXISTS receipt_transaction_ids(transaction_no TEXT PRIMARY KEY,receipt_id TEXT NOT NULL,order_id TEXT NOT NULL,created_at TEXT NOT NULL)')
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipts'").fetchone():
        for receipt_id, payload in c.execute('SELECT id,payload FROM receipts ORDER BY id').fetchall():
            try:
                data = json.loads(payload)
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            transaction_no = re.sub(r'[\s\-_—–]', '', str(data.get('transaction_no') or '')).upper().strip()
            if transaction_no:
                c.execute('INSERT OR IGNORE INTO receipt_transaction_ids(transaction_no,receipt_id,order_id,created_at) VALUES(?,?,?,?)',
                          (transaction_no, receipt_id, str(data.get('order_id') or ''), str(data.get('at') or ctx['now']())))
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='role_permissions'").fetchone():
        for role in ('会计', '出纳'):
            row = c.execute('SELECT payload FROM role_permissions WHERE role=?', (role,)).fetchone()
            if not row:
                continue
            try:
                value = json.loads(row[0])
            except (TypeError, ValueError):
                continue
            actions = value.get('actions') if isinstance(value.get('actions'), list) else []
            if 'finance.evidence' in actions:
                continue
            value['actions'] = [*actions, 'finance.evidence']
            c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role=?",
                      (json.dumps(value, ensure_ascii=False), role))
    ctx['audit'](c, '管理员', '建立收款截图识别与交易单号台账', 'receipt-evidence', None,
                 {'migration': '078', 'source_unchanged': True})


def expense_estimates_schema(c, ctx):
    c.execute('CREATE TABLE IF NOT EXISTS expense_estimates(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL)')
    c.execute("CREATE INDEX IF NOT EXISTS expense_estimates_coverage ON expense_estimates(COALESCE(json_extract(payload,'$.voided'),0),json_extract(payload,'$.service_start'),json_extract(payload,'$.service_end'))")


def irregular_expense_settings(c, ctx):
    row=c.execute("SELECT value FROM meta WHERE key='expense_category_settings'").fetchone()
    settings=json.loads(row[0]) if row else {};before=json.loads(json.dumps(settings))
    keys={r[0] for r in c.execute("SELECT DISTINCT json_extract(payload,'$.category') FROM indirect_expenses WHERE json_extract(payload,'$.accrual_method')='service_days'")}
    keys|={r[0] for r in c.execute("SELECT DISTINCT json_extract(payload,'$.category') FROM expense_estimates")}
    for key in keys:
        old=settings.get(key,{})
        if 'irregular_periodic' not in old:settings[key]={**old,'irregular_periodic':True,'version':int(old.get('version',0))+1}
    if settings!=before:
        c.execute("INSERT INTO meta VALUES('expense_category_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(settings,ensure_ascii=False),))
        ctx['audit'](c,'管理员','沿用既有日期费用的不定期属性','expense_category_settings',before,settings)


def open_stock_query_indexes(c, ctx):
    c.execute("CREATE INDEX IF NOT EXISTS corrections_business_date_kind_id ON order_corrections(json_extract(payload,'$.business_date'),json_extract(payload,'$.kind'),id)")


def delivery_history_indexes(c, ctx):
    c.execute("CREATE INDEX IF NOT EXISTS trade_feedback_date_id ON trade_records(json_extract(payload,'$.kind'),json_extract(payload,'$.feedback_date'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS asset_history_kind_date_id ON asset_records(json_extract(payload,'$.kind'),json_extract(payload,'$.business_date'),id)")
    c.execute("CREATE INDEX IF NOT EXISTS driver_return_history_date_id ON driver_return_requests(json_extract(payload,'$.business_date'),id)")


def delivery_provider_permissions(c, ctx):
    changed = {}
    for role, payload in c.execute('SELECT role,payload FROM role_permissions').fetchall():
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            continue
        modules = value.get('modules') if isinstance(value.get('modules'), list) else []
        additions = []
        if (role in ('库管', '会计', '物流负责人') or 'delivery.dispatch' in modules) and 'delivery.providers' not in modules:
            additions.append('delivery.providers')
        if (role in ('会计', '出纳') or {'finance.byproducts', 'finance.costs'} & set(modules)) and 'finance.transport-settlement' not in modules:
            additions.append('finance.transport-settlement')
        if not additions:
            continue
        value['modules'] = [*modules, *additions]
        c.execute("UPDATE role_permissions SET payload=?,version=version+1,updated_at=datetime('now') WHERE role=?",
                  (json.dumps(value, ensure_ascii=False), role))
        changed[role] = additions
    if changed:
        ctx['audit'](c, '管理员', '开通配送服务商与配送费结算菜单', 'role_permissions', None,
                     {'migration': '083', 'roles': changed})


def audit_query_indexes(c, ctx):
    c.execute('CREATE INDEX IF NOT EXISTS audit_at_id ON audit(at,id)')
    c.execute('CREATE INDEX IF NOT EXISTS audit_entity_at_id ON audit(entity,at,id)')
    c.execute('CREATE INDEX IF NOT EXISTS audit_role_at_id ON audit(role,at,id)')
    ctx['audit'](c, '管理员', '建立审计与安全事件查询索引', 'audit', None,
                 {'migration': '084', 'indexes': ['audit_at_id', 'audit_entity_at_id', 'audit_role_at_id']})
