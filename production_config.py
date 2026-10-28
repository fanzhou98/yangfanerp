"""Effective-dated production directory. No commits and no business ledger rewrites.

Systems, stock locations and product processes are independent entities. Only the
legacy adapter may infer a source from the original two warehouse identifiers.
"""
import copy
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

LEGACY_SOURCES = {'WH-TOFU': 'tofu', 'WH-SKIN': 'skin'}
LEGACY_FIELDS = ('large', 'small', 'skin')


def schema(c):
    import migrations
    return migrations.ensure(c, 'production-config')



def seed(c):
    products = list(c.execute('SELECT id,name FROM products'))
    row = c.execute("SELECT value FROM meta WHERE key='product_grinding_systems'").fetchone()
    defaults = json.loads(row[0]) if row else {}
    relations = {}
    residual = None
    for p in products:
        name = p['name'].replace('（', '(').replace('）', ')')
        system = defaults.get(p['id'], 'skin' if name in ('豆皮', '千张(豆皮)') else 'tofu' if name in ('大豆腐', '中豆腐', '白干', '白豆干', '白干(框)', '白干(包)') else '')
        if name in ('豆皮', '千张(豆皮)'): residual = p['id']
        relations[p['id']] = {'default_system_id': system, 'system_ids': ['tofu', 'skin'], 'process_ids': ['large', 'small', 'skin']}
    warehouses = [{'id': k, 'name': n, 'material_ids': ['RM-SOY'] if k != 'WH-COMMON' else ['@auxiliary'], 'active': True} for k, n in [('WH-TOFU', '豆腐库'), ('WH-SKIN', '豆皮库'), ('WH-EXTERNAL', '外库'), ('WH-MAIN', '大库'), ('WH-COMMON', '公共辅料与包装库')]]
    systems = [{'id': k, 'name': n, 'active': True, 'material_id': 'RM-SOY', 'warehouse_ids': [w], 'default_warehouse_id': w, 'soak_key': k + '_soak_kg', 'soak_kg': '', 'allocation_mode': mode if mode!='residual' or residual else 'proportional', 'residual_product_id': residual if k == 'skin' else ''} for k, n, w, mode in [('tofu', '豆腐磨浆系统', 'WH-TOFU', 'proportional'), ('skin', '豆皮磨浆系统', 'WH-SKIN', 'residual')]]
    processes = [{'id': k, 'name': n, 'active': True, 'dry_kg': '', 'output_qty': '', 'output_unit':'筐' if k in ('large','small') else '', 'kg_key': k + '_slurry_kg', 'output_key': k + '_slurry_crates'} for k, n in [('large', '大豆腐浆缸'), ('small', '中豆腐浆缸'), ('skin', '豆皮浆缸')]]
    return {'version': 0, 'effective_date': '0001-01-01', 'systems': systems, 'warehouses': warehouses, 'processes': processes, 'products': relations}


def ensure_seed(c):
    if not c.execute('SELECT 1 FROM production_config_versions').fetchone():
        value = seed(c)
        c.execute('INSERT INTO production_config_versions VALUES(0,?,?)', (value['effective_date'], json.dumps(value, ensure_ascii=False)))


def history(c):
    return [json.loads(r[0]) for r in c.execute('SELECT payload FROM production_config_versions ORDER BY effective_date,version')]


def get(c, day=None, record=None, settings=None):
    day = day or date.today().isoformat()
    if record and record.get('config_snapshot'):
        value = copy.deepcopy(record['config_snapshot'])
    else:
        versions = history(c)
        value = copy.deepcopy(next((v for v in reversed(versions) if v['effective_date'] <= day), None) or seed(c))
        # Pre-directory documents always use the original two-system topology.
        if record and 'config_snapshot' not in record: value = copy.deepcopy(versions[0] if versions else seed(c))
    if settings is None:
        row = c.execute("SELECT payload FROM factory_settings WHERE id='default'").fetchone()
        settings = json.loads(row[0]) if row else {}
    settings = (record or {}).get('settings_snapshot', settings)
    for s in value['systems']:
        if s.get('soak_key'): s['soak_kg'] = settings.get(s['soak_key'], s.get('soak_kg', ''))
    for p in value['processes']:
        if p.get('kg_key'): p['dry_kg'] = settings.get(p['kg_key'], p.get('dry_kg', ''))
        if p.get('output_key'): p['output_qty'] = settings.get(p['output_key'], p.get('output_qty', ''))
    return value


def active_systems(config):
    return [s for s in config['systems'] if s['active']]


def accepts_material(warehouse, mid):
    ids=warehouse['material_ids']
    return mid in ids or '*' in ids or mid!='RM-SOY' and '@auxiliary' in ids


def warehouses(c, day=None):
    return get(c, day)['warehouses']


def warehouse_names(c):
    names = {'WH-UNASSIGNED': '历史待确认库'}
    for v in history(c) or [seed(c)]:
        names.update({w['id']: w['name'] for w in v['warehouses']})
    return names


def source(entry):
    # New entries explicitly carry even an empty source, never infer them.
    return entry.get('production_system_id', LEGACY_SOURCES.get(entry.get('warehouse_id'), ''))


def default_system(c, product, config=None):
    row = c.execute("SELECT value FROM meta WHERE key='product_grinding_systems'").fetchone()
    saved = json.loads(row[0]) if row else {}
    relation = (config or get(c))['products'].get(product['id'], {})
    return relation.get('default_system_id','') if (config or get(c))['version'] else saved.get(product['id'], relation.get('default_system_id', ''))


def tank_counts(row):
    if 'tanks' in row: return row['tanks']
    return {k: row.get(k + '_tanks', '0' if k == 'skin' else '') for k in LEGACY_FIELDS}


def bean_basis(row, config):
    factors = {p['id']: p for p in config['processes']}
    total = Decimal(0)
    for pid, n in tank_counts(row).items():
        if n in ('', None): return None
        n = Decimal(n)
        if n:
            factor = factors.get(pid, {}).get('dry_kg')
            if not factor or Decimal(factor) <= 0: return None
            total += n * Decimal(factor)
    return total


def parameter_items(config):
    """Scoped conversion definitions; a new entity adds no dedicated Python key."""
    items = []
    for kind, rows, fields, group in [
        ('systems', config['systems'], [('soak_kg', '每桶干豆', '公斤 / 桶', 'soak_key')], 'soaking'),
        ('processes', config['processes'], [('dry_kg', '每缸用豆', '公斤 / 缸', 'kg_key'), ('output_qty', '每缸产出', '发货单位 / 缸', 'output_key')], 'slurry')]:
        for row in rows:
            if not row['active']: continue
            for field, label, unit, legacy in fields:
                if row.get(legacy): continue
                items.append({'key': kind + '.' + row['id'] + '.' + field, 'group_id': group, 'kind': kind, 'entity_id': row['id'], 'field': field, 'label': row['name'] + ' · ' + label, 'unit': unit, 'positive': True, 'optional': kind == 'processes', 'value': row.get(field, ''), 'effective_date':config['effective_date'],'description': '配置v'+str(config['version'])+'，'+config['effective_date']+'生效。按对象独立申请，管理员审批后在指定日期生效；既有生产快照保持原值。'})
    return items


def latest(c):
    versions = history(c)
    return get(c, versions[-1]['effective_date']) if versions else get(c)


def minimum_date(c):
    """当天没有生产或上豆记录时允许当天生效，否则顺延到次日。"""
    versions = history(c)
    today = date.today()
    latest_day = c.execute("SELECT MAX(day) FROM (SELECT json_extract(payload,'$.business_date') day FROM factory_daily UNION ALL SELECT json_extract(payload,'$.business_date') day FROM material_entries)").fetchone()[0]
    busy = bool(latest_day) and latest_day >= today.isoformat()
    dates = [today + timedelta(days=1) if busy else today]
    if versions: dates.append(date.fromisoformat(versions[-1]['effective_date']))
    if latest_day: dates.append(date.fromisoformat(latest_day) + timedelta(days=1))
    return max(dates).isoformat()


def validate(c, raw):
    if not isinstance(raw, dict): raise ValueError('生产配置格式无效')
    out = {}
    def label(v, name):
        if not isinstance(v, str) or not v.strip() or len(v) > 80: raise ValueError('请填写' + name)
        return v.strip()
    def quantity(v, required=False):
        if v in ('', None) and not required: return ''
        try: n = Decimal(str(v))
        except (InvalidOperation, TypeError): raise ValueError('换算数值无效')
        if not n.is_finite() or n <= 0 or n > 100000000 or n.as_tuple().exponent < -3: raise ValueError('换算须大于0，最多三位小数')
        return format(n, 'f')
    for kind in ('warehouses', 'systems', 'processes'):
        rows = raw.get(kind)
        if not isinstance(rows, list) or not rows or len(rows) > 100: raise ValueError('请维护库房、磨浆系统和工艺目录')
        seen = set(); out[kind] = []
        for r in rows:
            if not isinstance(r, dict): raise ValueError('目录格式无效')
            rid = r.get('id', '')
            if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,49}', rid) or rid in seen: raise ValueError('目录编号须唯一，仅用字母、数字、横杠或下划线')
            seen.add(rid)
            if type(r.get('active', True)) is not bool: raise ValueError('启停状态无效')
            item = {'id': rid, 'name': label(r.get('name'), '名称'), 'active': r.get('active', True)}
            if kind == 'warehouses':
                ids = r.get('material_ids', [])
                if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or (x not in ('*','@auxiliary') and not c.execute('SELECT 1 FROM material_items WHERE id=?', (x,)).fetchone()) for x in ids): raise ValueError('请选择库房可存物料')
                item['material_ids'] = list(dict.fromkeys(ids))
            elif kind == 'processes':
                item.update(dry_kg=quantity(r.get('dry_kg')), output_qty=quantity(r.get('output_qty')))
                output_unit=r.get('output_unit','筐' if rid in ('large','small') else '')
                if not isinstance(output_unit,str) or len(output_unit)>12:raise ValueError('每缸产出单位须为12字以内')
                item['output_unit']=output_unit.strip()
                # Existing parameter approvals remain the source for legacy conversions.
                for field, suffix in [('kg_key', '_slurry_kg'), ('output_key', '_slurry_crates')]:
                    if r.get(field):
                        if rid not in LEGACY_FIELDS or r[field] != rid + suffix: raise ValueError('换算参数引用无效')
                        item[field] = r[field]
            else:
                mid = r.get('material_id', 'RM-SOY')
                if mid != 'RM-SOY': raise ValueError('当前磨浆核算支持大豆；新原料核算需单独验证')
                ids = r.get('warehouse_ids', [])
                if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids): raise ValueError('请选择可领用库房')
                if r.get('default_warehouse_id') not in ids: raise ValueError('默认领用库房须在允许库房中')
                mode = r.get('allocation_mode')
                if mode not in ('proportional', 'residual'): raise ValueError('请选择用豆分摊方式')
                residual = r.get('residual_product_id') or ''
                if not isinstance(residual,str):raise ValueError('余量产品无效')
                if mode == 'residual' and item['active'] and not c.execute('SELECT 1 FROM products WHERE id=?', (residual,)).fetchone(): raise ValueError(item['name']+'：余量法须指定接收余量的产品；也可选择按用浆折豆占比分摊')
                item.update(material_id=mid, warehouse_ids=list(dict.fromkeys(ids)), default_warehouse_id=r['default_warehouse_id'], soak_kg=quantity(r.get('soak_kg'), not r.get('direct_bean_only',False)), allocation_mode=mode, residual_product_id=residual if mode == 'residual' else '')
                if r.get('direct_bean_only') is True:item['direct_bean_only']=True
                if r.get('standard_output_rule'):
                    rule=r['standard_output_rule']
                    if not isinstance(rule,dict) or rule.get('unit') not in ('盒','筐','包','公斤'):raise ValueError('标准产出规则的单位无效')
                    item['standard_output_rule']={'dry_kg':quantity(rule.get('dry_kg'),True),'output_qty':quantity(rule.get('output_qty'),True),'unit':rule['unit']}
                if r.get('soak_key'):
                    if rid not in ('tofu', 'skin') or r['soak_key'] != rid + '_soak_kg': raise ValueError('泡豆参数引用无效')
                    item['soak_key'] = r['soak_key']
            out[kind].append(item)
    ws = {w['id']: w for w in out['warehouses']}; ss = {s['id']: s for s in out['systems']}; ps = {p['id']: p for p in out['processes']}
    for s in ss.values():
        if any(w not in ws or s['active'] and (not ws[w]['active'] or not accepts_material(ws[w],s['material_id'])) for w in s['warehouse_ids']): raise ValueError('系统所选库房不存在、停用或不允许存放大豆')
    relations = raw.get('products')
    if not isinstance(relations, dict): raise ValueError('请维护产品工艺关系')
    out['products'] = {}
    for pid, r in relations.items():
        if not c.execute('SELECT 1 FROM products WHERE id=?', (pid,)).fetchone() or not isinstance(r, dict): raise ValueError('产品工艺关系无效')
        systems = r.get('system_ids', []); processes = r.get('process_ids', []); default = r.get('default_system_id', '')
        if not isinstance(systems, list) or not isinstance(processes, list) or not isinstance(default,str) or any(not isinstance(x,str) for x in systems+processes) or any(x not in ss for x in systems) or any(x not in ps for x in processes) or default and default not in systems: raise ValueError('产品供浆来源或工艺不存在，常用来源须在允许来源中')
        out['products'][pid] = {'default_system_id': default, 'system_ids': list(dict.fromkeys(systems)), 'process_ids': list(dict.fromkeys(processes))}
    for s in ss.values():
        if s['active'] and s['allocation_mode'] == 'residual' and s['id'] not in out['products'].get(s['residual_product_id'], {}).get('system_ids', []): raise ValueError('余量产品必须允许使用该系统供浆')
    # Retain stable identifiers forever; deactivate instead of deleting.
    prior = history(c)[-1] if history(c) else seed(c)
    for kind in ('warehouses', 'systems', 'processes'):
        if not {x['id'] for x in prior[kind]} <= {x['id'] for x in out[kind]}: raise ValueError('已有目录不能删除，请改为停用以保留历史')
    import resources_costs
    for balance in resources_costs.material_ledger(c,warehouse_details=True)[2]:
        if Decimal(balance['qty']) and (not ws.get(balance['warehouse_id'],{}).get('active') or not accepts_material(ws[balance['warehouse_id']],balance['id'])):
            if balance['warehouse_id']!='WH-UNASSIGNED':raise ValueError('库房仍有库存，请先转移或处理后停用或调整可存物料')
    return out


def publish(c, body, role, now, audit):
    import erp_access
    if role != '管理员': raise ValueError('仅管理员可以审批并发布生产配置')
    erp_access.require_role(role, 'system.parameters')
    ensure_seed(c)
    versions = history(c); latest = max(v['version'] for v in versions)
    if type(body.get('version')) is not int or body['version'] != latest: raise ValueError('生产配置已更新，请重新读取后修改')
    day = body.get('effective_date', '')
    try: parsed = date.fromisoformat(day)
    except (ValueError, TypeError): raise ValueError('请选择生效日期')
    earliest = minimum_date(c)
    if day != parsed.isoformat() or day < earliest: raise ValueError(f'新配置最早 {earliest} 生效；当天已有生产或上豆记录时顺延到次日，历史日期不追溯修改')
    if day < versions[-1]['effective_date']: raise ValueError('生效日期不能早于已发布配置；既有版本保持留存')
    if any(r[0] >= day for r in c.execute("SELECT json_extract(payload,'$.business_date') FROM factory_daily UNION ALL SELECT json_extract(payload,'$.business_date') FROM material_entries")): raise ValueError('生效日期已有生产或库存流水，请选择尚未办理业务的日期')
    note = body.get('note', '')
    if not isinstance(note, str) or not note.strip() or len(note) > 500: raise ValueError('请填写配置调整原因')
    value = validate(c, body.get('config'))
    value.update(version=latest + 1, effective_date=day, published_at=now(), published_by=role, note=note.strip())
    c.execute('INSERT INTO production_config_versions VALUES(?,?,?)', (value['version'], day, json.dumps(value, ensure_ascii=False)))
    audit(c, role, '审批并发布生产配置', str(value['version']), versions[-1], value)
    return value
