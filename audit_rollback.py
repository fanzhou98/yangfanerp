"""Admin-only audit rollback: restore the previous version of one operation's record.

The audit table keeps a before/after snapshot for every business write.  This
module turns one audit row back into its previous state.  Records created by the
operation are removed; records modified by it are restored to the before copy.
Records that were created after the operation and still reference the target are
offered as dependent deletions and must be confirmed in the same request.
"""
import hashlib
import json

import auth

PAYLOAD_TABLES = {
    'orders': '订单',
    'receipts': '收款',
    'sales_returns': '客户退货',
    'statement_documents': '货款对账确认单',
    'byproduct_sales': '豆渣销售',
    'material_entries': '库存流水',
    'expense_payments': '费用付款',
    'expense_reviews': '费用复核',
    'indirect_expenses': '间接费用',
    'factory_schedules': '厂长排班',
    'factory_attendance': '考勤',
    'factory_daily': '每日生产',
    'factory_runs': '生产记录',
    'factory_scrap': '烂豆皮登记',
    'factory_employees': '员工',
    'factory_groups': '生产小组',
    'factory_parameter_requests': '参数申请',
    'purchase_orders': '采购单',
    'purchase_receipts': '采购验收',
    'purchase_payments': '采购付款',
    'purchase_charges': '采购费用',
    'suppliers': '供应商',
    'asset_records': '资产记录',
    'finished_goods_records': '外购成品',
    'processing_batches': '加工批次',
    'trade_records': '周转筐记录',
    'driver_return_requests': '司机回框申请',
    'order_corrections': '单据纠错',
    'archived_orders': '归档单据',
    'factory_settings': '生产参数',
    'gel_daily_outputs': '凉粉生产登记',
}
COLUMN_TABLES = {'customers': '客户', 'products': '产品', 'operator_users': '经办人',
                 'delivery_markets': '配送市场', 'delivery_vehicles': '配送车辆', 'delivery_drivers': '司机'}
DATE_TABLES = {'dispatch_plans': '每日配送安排', 'warehouse_plans': '库存与发货安排', 'stock_closings': '库存日结'}
BLOCKED_TABLES = {'payroll_records': '工资表', 'role_permissions': '岗位权限', 'auth_users': '登录账号',
                  'auth_sessions': '登录会话', 'security_events': '安全事件', 'audit': '审计记录'}
PREFIXES = (('SO-', 'orders'), ('FP-', None), ('PO-', 'purchase_orders'), ('GR-', 'purchase_receipts'),
            ('PP-', 'purchase_payments'), ('RT-', 'sales_returns'), ('PR-', 'processing_batches'),
            ('AS-', 'asset_records'), ('MAP-', 'asset_records'), ('DZ-', 'statement_documents'),
            ('TR-', 'trade_records'), ('OP-', 'operator_users'), ('MT-', 'material_entries'),
            ('MAT-', 'material_items'), ('C', 'customers'), ('P', 'products'))
FACTORY_TABLES = ('factory_schedules', 'factory_attendance', 'factory_employees', 'factory_groups',
                  'factory_runs', 'factory_scrap', 'factory_daily', 'factory_parameter_requests')
TIME_KEYS = ('at', 'created_at', 'updated_at', 'recorded_at', 'issued_at', 'generated_at', 'voided_at')
CONTAINER_STRIP = {'factory_attendance': 'entries', 'factory_schedules': 'entries'}
MAX_DEPENDENTS = 200


def _payload(c, table, rid):
    row = c.execute(f'SELECT payload FROM {table} WHERE id=?', (rid,)).fetchone()
    return json.loads(row[0]) if row else None


def _date_payload(c, table, day):
    row = c.execute(f'SELECT payload FROM {table} WHERE business_date=?', (day,)).fetchone()
    return json.loads(row[0]) if row else None


def _columns(c, table):
    return [r[1] for r in c.execute(f'PRAGMA table_info({table})')]


def _row(c, table, rid):
    if table in DATE_TABLES:
        return _date_payload(c, table, rid)
    if table in PAYLOAD_TABLES:
        return _payload(c, table, rid)
    row = c.execute(f'SELECT * FROM {table} WHERE id=?', (rid,)).fetchone()
    if not row:
        return None
    return {k: row[k] for k in row.keys()}


def _resolve_by_scan(c, entity):
    for table in list(PAYLOAD_TABLES) + list(COLUMN_TABLES):
        if c.execute(f'SELECT 1 FROM {table} WHERE id=? LIMIT 1', (entity,)).fetchone():
            return table
    return None


def resolve(c, entity, action=''):
    """Return (table, row_id) for one audit entity, or (None, None)."""
    if not entity:
        return None, None
    if entity.startswith('FP-'):
        for table in FACTORY_TABLES:
            if c.execute(f'SELECT 1 FROM {table} WHERE id=? LIMIT 1', (entity,)).fetchone():
                return table, entity
        return None, None
    for prefix, table in PREFIXES:
        if prefix in ('C', 'P'):
            matched = entity.startswith(prefix) and entity[1:].isdigit()
        else:
            matched = entity.startswith(prefix)
        if matched:
            if table:
                return table, entity
            break
    if len(entity) == 10 and entity[4] == '-' and entity[7] == '-':
        for table, words in (('dispatch_plans', ('配送安排', '派车')),
                             ('warehouse_plans', ('预分配', '分配', '实发', '盘点')),
                             ('stock_closings', ('日结', '结账')),
                             ('statement_documents', ('对账',))):
            if any(word in action for word in words):
                return table, entity
        return None, None
    if entity in ('factory-settings', 'finance-settings', 'system-settings'):
        return 'factory_settings', 'default'
    table = _resolve_by_scan(c, entity)
    return (table, entity) if table else (None, None)


def _summary(table, obj):
    if not obj:
        return ''
    for key in ('name', 'customer_name', 'employee_name', 'group_name', 'product_name', 'action', 'note', 'business_date'):
        if obj.get(key):
            return str(obj[key])[:80]
    return str(obj.get('id', ''))[:80]


def _time(obj):
    if not isinstance(obj, dict):
        return ''
    for key in TIME_KEYS:
        if obj.get(key):
            return str(obj[key])
    return ''


def _walk(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, path + (str(key),))
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, path)
    elif isinstance(value, str):
        yield path, value


def _references(obj, target):
    for path, value in _walk(obj):
        if value != target:
            continue
        key = path[-1].lower() if path else ''
        if key == 'id' or key.endswith('_id') or key.endswith('_ids') or key in ('current', 'orders', 'order_ids', 'source_order_ids'):
            return True
    return False


def _strip(c, table, rid, target):
    obj = _payload(c, table, rid)
    if not obj:
        return False
    field = CONTAINER_STRIP[table]
    entries = [e for e in obj.get(field, []) if e.get('employee_id') != target and e.get('source_schedule_id') != target]
    if len(entries) == len(obj.get(field, [])):
        return False
    if not entries:
        c.execute(f'DELETE FROM {table} WHERE id=?', (rid,))
        return True
    updated = {**obj, field: entries, 'version': int(obj.get('version') or 0) + 1}
    if table == 'factory_attendance' and not any(e.get('employee_type', 'production') == 'production' for e in entries):
        updated.pop('source_schedule_id', None)
        updated.pop('source_schedule_version', None)
    c.execute(f'UPDATE {table} SET payload=? WHERE id=?', (json.dumps(updated, ensure_ascii=False), rid))
    return True


def _dependent(c, table, rid, target, cutoff, created, seen):
    if table in BLOCKED_TABLES:
        return None
    if table == 'audit' or (table, rid) in seen:
        return None
    obj = _row(c, table, rid)
    if not obj or not _references(obj, target):
        return None
    seen.add((table, rid))
    if table in CONTAINER_STRIP:
        field = CONTAINER_STRIP[table]
        hits = sum(1 for e in obj.get(field, []) if e.get('employee_id') == target or e.get('source_schedule_id') == target)
        if hits:
            return {'table': table, 'label': PAYLOAD_TABLES.get(table, table), 'id': rid,
                    'summary': _summary(table, obj), 'action': 'strip', 'count': hits}
        return None
    stamp = _time(obj)
    if not created and stamp and cutoff and stamp < cutoff:
        return None
    return {'table': table, 'label': PAYLOAD_TABLES.get(table, table), 'id': rid,
            'summary': _summary(table, obj), 'action': 'delete', 'count': 1}


def _candidates(c, table):
    if table in DATE_TABLES:
        for row in c.execute(f'SELECT business_date AS rid FROM {table}'):
            yield row['rid']
    elif table in COLUMN_TABLES:
        for row in c.execute(f'SELECT id AS rid FROM {table}'):
            yield row['rid']
    else:
        for row in c.execute(f'SELECT id AS rid FROM {table}'):
            yield row['rid']


def dependents(c, table, target, cutoff, created):
    found, seen = [], {(table, target)}
    queue = [(table, target, 0)]
    while queue and len(found) < MAX_DEPENDENTS:
        current_table, current_id, depth = queue.pop(0)
        for candidate in list(PAYLOAD_TABLES) + list(DATE_TABLES):
            if candidate in BLOCKED_TABLES:
                continue
            for rid in _candidates(c, candidate):
                hit = _dependent(c, candidate, rid, current_id, cutoff, created or depth > 0, seen)
                if not hit:
                    continue
                found.append(hit)
                if hit['action'] == 'delete' and depth < 2 and hit['table'] not in DATE_TABLES:
                    queue.append((hit['table'], hit['id'], depth + 1))
                if len(found) >= MAX_DEPENDENTS:
                    break
            if len(found) >= MAX_DEPENDENTS:
                break
    return found


def _fingerprint(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def _payroll_blockers(c, target):
    found = []
    for row in c.execute('SELECT id,payload FROM payroll_records'):
        try:
            obj = json.loads(row['payload'])
        except (TypeError, ValueError):
            continue
        if _references(obj, target):
            found.append(row['id'])
    return found


def _audit_row(c, audit_id):
    row = c.execute('SELECT id,at,role,action,entity,before_json,after_json,actor_name,request_id FROM audit WHERE id=?', (audit_id,)).fetchone()
    return dict(row) if row else None


def _closed_period(c, obj):
    when = str((obj or {}).get('business_date') or '')[:10]
    if len(when) < 10:
        return ''
    try:
        import inventory
        if inventory.closed(c, when):
            return '所属日期已库存日结'
    except ValueError:
        pass
    row = c.execute('SELECT payload FROM resource_periods WHERE month=?', (when[:7],)).fetchone()
    if row and json.loads(row[0]).get('state') == 'closed':
        return '所属月份已成本结账'
    return ''


def plan(c, audit_id):
    entry = _audit_row(c, audit_id)
    if not entry:
        raise ValueError('操作记录不存在')
    action = entry['action'] or ''
    if action.startswith('auth.') or '权限' in action or '备份' in action or '清理' in action or '登录' in action:
        raise ValueError('登录、账号、权限、备份和安全记录不支持回滚')
    before = json.loads(entry['before_json']) if entry['before_json'] and entry['before_json'] != 'null' else None
    after = json.loads(entry['after_json']) if entry['after_json'] and entry['after_json'] != 'null' else None
    entity = entry['entity']
    created = not before
    target_id = (after or {}).get('id') if created and isinstance(after, dict) else entity
    if created and not target_id:
        target_id = entity
    table, rid = resolve(c, target_id, action) if target_id else (None, None)
    if not table:
        if str(target_id).startswith(('PARAM-', 'GROUP-', 'G-')):
            raise ValueError('参数申请、内部消息和系统配置请在对应页面处理，不能用操作回滚')
        if str(target_id) in ('processing_rules', 'role-permissions'):
            raise ValueError('加工规则和岗位权限请在对应设置页面调整，不能用操作回滚')
        if str(target_id) in ('factory-settings', 'finance-settings', 'system-settings'):
            raise ValueError('系统设置请在参数设置页面调整，不能用操作回滚')
        if str(target_id).isdigit():
            raise ValueError('生产配置版本请在配置发布页面处理，不能用操作回滚')
        raise ValueError('该操作没有可回滚的业务记录（可能已归档或属于系统事件）')
    if table in BLOCKED_TABLES:
        raise ValueError(BLOCKED_TABLES[table] + '不支持在操作记录中回滚')
    current = _row(c, table, rid)
    if current is None:
        raise ValueError('目标记录已不存在，不能回滚')
    cutoff = entry['at'] or ''
    depends = dependents(c, table, rid, cutoff, created)
    blockers = []
    reason = _closed_period(c, current)
    if reason:
        blockers.append('目标记录' + reason + '，请先重开对应日期或月份再回滚')
    if table=='trade_records' and current.get('kind') in ('trip','transport-document'):
        blockers.append('运输趟次与结算须在配送闭环中更正，不能拆开回滚')
    fee=current if table=='indirect_expenses' else _payload(c,'indirect_expenses',current.get('expense_id','')) if table in ('expense_reviews','expense_payments') else None
    if fee and (fee.get('system_source')=='transport-settlement' or fee.get('source')=='transport-settlement'):
        blockers.append('运输月结应付与付款须保留来源链，不能在操作记录中拆开回滚')
    if table=='orders':
        try:
            import transport_closure
            transport_closure.guard_order(c,current,before or {**current,'lines':[]})
        except ValueError as error:blockers.append(str(error))
    if table=='dispatch_plans':
        try:
            import transport_closure
            transport_closure.guard_dispatch(c,current,before or {**current,'trips':[],'assignments':[]})
        except ValueError as error:blockers.append(str(error))
    if table=='indirect_expenses' and any(isinstance(v,dict) and v.get('accrual_method')=='service_days' for v in (current,before)):
        import resources_costs as rc,expense_estimates
        try:
            rc.expense_open_periods(c,current)
            if before:
                rc.expense_open_periods(c,before);expense_estimates.validate_restore(c,before,rid)
        except ValueError as error:blockers.append(str(error))
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='expense_estimates'").fetchone():
        for row in c.execute('SELECT id,payload FROM expense_estimates'):
            if _references(json.loads(row['payload']),rid):blockers.append('成本暂估（'+row['id']+'）引用该资料，请保留原依据并在成本管理中核查')
    for hit in list(depends):
        if hit['table'] in DATE_TABLES:
            blockers.append(f"{hit['label']}（{hit['id']}）引用了该记录，请先撤销对应日期的安排或日结后再回滚")
            depends.remove(hit)
        elif hit['table'] == 'statement_documents':
            blockers.append(f"已出具的客户对账单（{hit['id']}）引用了该记录，请先按对账单流程作废后再回滚")
            depends.remove(hit)
        else:
            reason = _closed_period(c, _row(c, hit['table'], hit['id']))
            if reason:
                blockers.append(f"依赖记录 {hit['label']}（{hit['id']}）{reason}，请先重开对应日期或月份再回滚")
                depends.remove(hit)
    for payroll_id in _payroll_blockers(c, rid)[:5]:
        blockers.append(f'工资表（{payroll_id}）引用了该记录，请先在工资核算中撤回相关工资表')
    if table in ('factory_attendance', 'factory_schedules'):
        month = str((_payload(c, table, rid) or {}).get('business_date') or '')[:7]
        if month:
            sheets = [row['id'] for row in c.execute("SELECT id FROM payroll_records WHERE json_extract(payload,'$.kind')='sheet' AND json_extract(payload,'$.month')=? AND json_extract(payload,'$.state')='confirmed'", (month,))]
            for sheet in sheets:
                blockers.append(f'{month} 工资表（{sheet}）已确认，请先撤回工资确认后再回滚考勤或排班')
    if table in DATE_TABLES:
        label = DATE_TABLES[table]
    else:
        label = PAYLOAD_TABLES.get(table) or COLUMN_TABLES.get(table) or table
    later = c.execute("SELECT COUNT(*) FROM audit WHERE entity=? AND id>? AND action NOT LIKE 'auth.%'", (entity, audit_id)).fetchone()[0]
    detail = {
        'audit_id': audit_id, 'action': action, 'at': entry['at'], 'actor': entry['actor_name'] or entry['role'],
        'entity': entity, 'target_id': rid, 'mode': 'restore' if before else 'delete',
        'table': table, 'table_label': label,
        'target_summary': _summary(table, current), 'previous_summary': _summary(table, before) if before else '',
        'changed_since': later, 'dependents': depends, 'blockers': blockers,
        'dependents_truncated': len(depends) >= MAX_DEPENDENTS,
    }
    detail['fingerprint'] = _fingerprint({'audit_id': audit_id, 'target': rid, 'current': current,
                                          'before': before, 'dependents': depends})
    return detail


def _restore(c, table, rid, before):
    if table in DATE_TABLES:
        c.execute(f'UPDATE {table} SET payload=? WHERE business_date=?', (json.dumps(before, ensure_ascii=False), rid))
        return
    if table == 'factory_settings':
        restored = {k: v for k, v in before.items() if k != 'version'}
        c.execute("UPDATE factory_settings SET version=version+1,payload=? WHERE id=?", (json.dumps(restored, ensure_ascii=False), rid))
        return
    if table in PAYLOAD_TABLES:
        current = _payload(c, table, rid) or {}
        restored = {k: v for k, v in before.items() if k not in ('version',)}
        restored['version'] = int(current.get('version') or 0) + 1
        if table == 'statement_documents':
            raw = json.dumps(restored, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            c.execute('UPDATE statement_documents SET payload=?,content_hash=? WHERE id=?', (raw, hashlib.sha256(raw.encode()).hexdigest(), rid))
        else:
            c.execute(f'UPDATE {table} SET payload=? WHERE id=?', (json.dumps(restored, ensure_ascii=False), rid))
        return
    columns = set(_columns(c, table))
    fields = {k: v for k, v in before.items() if k in columns and k != 'id'}
    if not fields:
        return
    assignments = ','.join(f'{key}=?' for key in fields)
    c.execute(f'UPDATE {table} SET {assignments} WHERE id=?', (*fields.values(), rid))


def execute(c, audit_id, reason, fingerprint, role, now, audit):
    if role != '管理员':
        raise auth.AuthError(403, '仅管理员可以回滚操作')
    if not reason:
        raise ValueError('请填写回滚原因')
    reason = str(reason).strip()[:500]
    detail = plan(c, audit_id)
    if detail['blockers']:
        raise ValueError('存在依赖数据阻塞，请先处理：' + '；'.join(detail['blockers'][:3]))
    if detail['fingerprint'] != fingerprint:
        raise ValueError('目标记录已变化，请刷新后重新核对')
    entry = _audit_row(c, audit_id)
    before = json.loads(entry['before_json']) if entry['before_json'] and entry['before_json'] != 'null' else None
    current = _row(c, detail['table'], detail['target_id'])
    for hit in sorted(detail['dependents'], key=lambda x: 0 if x['action'] == 'strip' else 1):
        if hit['table'] == 'factory_attendance' or hit['table'] == 'factory_schedules':
            _strip(c, hit['table'], hit['id'], detail['target_id'])
        else:
            c.execute(f"DELETE FROM {hit['table']} WHERE {'business_date' if hit['table'] in DATE_TABLES else 'id'}=?", (hit['id'],))
    if detail['mode'] == 'delete':
        c.execute(f"DELETE FROM {detail['table']} WHERE {'business_date' if detail['table'] in DATE_TABLES else 'id'}=?", (detail['target_id'],))
        after = None
    else:
        _restore(c, detail['table'], detail['target_id'], before)
        after = _row(c, detail['table'], detail['target_id'])
    audit(c, role, '回滚操作到此前版本' if before else '回滚新建操作', detail['target_id'], current, after)
    # Rollback deletes/restores business rows outside the normal mutation helpers;
    # refresh the inventory revision so open pages re-read derived stock and cost.
    import inventory
    inventory.bump(c)
    return {'ok': True, 'audit_id': audit_id, 'mode': detail['mode'], 'target_id': detail['target_id'],
            'table': detail['table'], 'dependents': len(detail['dependents']), 'reason': reason}
