"""Single migration registry and transactional runner for local and cloud upgrades.

No function commits. Application startup owns its IMMEDIATE transaction; standalone
callers must commit explicitly. Status inspection opens no write transaction.
"""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import inspect
import json

SCHEMA_VERSION = 70


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    id: str
    component: str
    title: str
    apply: object
    legacy_marker: str = ''
    manual: bool = False

    @property
    def checksum(self):
        return hashlib.sha256(inspect.getsource(self.apply).encode()).hexdigest()


def registry():
    import migration_steps as s
    return (
        Migration('001-core-tables', 'core', '基础单据与业务表', s.core_tables),
        Migration('002-core-columns', 'core', '客户、配送与审计历史补列', s.core_columns),
        Migration('010-auth-schema', 'auth', '账号角色、会话与活动记录', s.auth_schema),
        Migration('020-access-schema', 'access', '岗位授权表及角色约束', s.access_schema),
        # Keep the original permission eligibility order, not a lexicographic sort.
        Migration('021-expense-payables', 'access', '费用核对付款授权', s.expense_payables_v040, 'expense_payables_v040'),
        Migration('022-weight-handoff', 'access', '会计称重交接授权', s.accountant_weight_handoff_v037, 'accountant_weight_handoff_v037'),
        Migration('023-driver-weights', 'access', '司机称重授权', s.driver_weights_v0351, 'driver_weights_v0351'),
        Migration('024-driver-permissions', 'access', '库管审核司机回筐授权', s.driver_permissions_v035, 'driver_permissions_v035'),
        Migration('025-asset-permissions', 'access', '资产与周转筐授权', s.asset_permissions_v034, 'asset_permissions_v034'),
        Migration('026-payroll-permissions', 'access', '工资岗位授权', s.payroll_permissions_v033, 'payroll_permissions_v033'),
        Migration('030-material-schema', 'resources', '原辅料与费用台账', s.resource_schema),
        Migration('031-material-catalog', 'resources', '基础物料目录', s.material_catalog),
        Migration('032-material-fifo', 'resources', 'FIFO历史切换界点', s.material_fifo, 'material_fifo_start'),
        Migration('033-purchase-schema', 'purchasing', '采购、验收、应付及收款人表', s.purchase_schema),
        Migration('034-material-units', 'resources', '未使用物料名称和单位修正', s.material_units),
        Migration('035-payroll-schema', 'payroll', '工资记录表', s.payroll_schema),
        Migration('036-production-schema', 'production', '生产、考勤与参数申请表', s.production_schema),
        Migration('037-payroll-profiles', 'production', '旧工资档案转月工资口径', s.payroll_profiles),
        Migration('038-asset-schema', 'assets', '资产目录、筐型映射及旧耗材停用', s.asset_schema),
        Migration('039-driver-schema', 'driver', '司机关联及旧提交记录兼容', s.driver_schema),
        Migration('042-production-directory-v1', 'production-config', '日期化生产配置版本表', s.production_directory),
        Migration('043-bootstrap-mode', 'bootstrap', '正式空库与演示初始化隔离', s.bootstrap, 'initialized'),
        Migration('044-operator-catalog', 'bootstrap', '经办岗位基础目录', s.operator_catalog, 'operator_users_initialized'),
        Migration('045-driver-catalog', 'bootstrap', '历史配送司机目录', s.driver_catalog, 'driver_catalog_initialized'),
        Migration('046-customer-locations', 'bootstrap', '历史客户市场精确匹配', s.customer_locations, 'customer_locations_v09'),
        Migration('047-product-materials', 'bootstrap', '产品原料映射与旧熏干原料修正', s.product_materials, 'smoked_tofu_material_v0361'),
        Migration('047b-asset-product-mappings', 'bootstrap', '产品筐型初始映射', s.asset_product_mappings),
        Migration('048-directory-baseline', 'bootstrap', '已有产品的生产配置基线', s.directory_baseline),
        Migration('900-billing-kilograms', 'billing', '包价转公斤价（明确执行）', s.billing_kilograms, manual=True),
        Migration('049-collaboration-schema', 'collaboration', '内部聊天、通知与问题反馈表', s.collaboration_schema),
        Migration('050-collaboration-permissions', 'collaboration', '为已有岗位开通聊天与反馈菜单', s.collaboration_permissions),
        Migration('051-customer-delivery-trade', 'assets', '客户电话、框型、配送差异与运输结算', s.customer_delivery_trade),
        Migration('052-gel-tofu-system', 'production', '内脂豆腐独立磨浆上豆系统', s.gel_tofu_system),
        Migration('053-accounting-crate-attributes', 'assets', '框子固有属性与客户分框皮重', s.accounting_crate_attributes),
        Migration('054-purchased-finished-goods', 'purchasing', '外购成品库存、成本与供应人结算', s.purchased_finished_goods),
        Migration('055-gel-standard-output', 'production', '内脂豆腐50公斤10盒每日核对', s.gel_tofu_standard_output),
        Migration('056-order-corrections', 'core', '历史实发更正与结算单作废记录', s.order_corrections),
        Migration('057-product-unit-defaults', 'core', '公斤与筐的包装字段默认规则', s.product_unit_defaults),
        Migration('058-merge-sales-reports', 'core', '合并销售日报与月报模块授权', s.merge_sales_reports),
        Migration('059-byproduct-customers', 'resources', '豆渣客户关联与结算单归档', s.byproduct_customers),
        Migration('060-fund-accounts', 'core', '资金账户、流水归属与内部转账', s.fund_accounts),
        Migration('061-supplier-categories', 'purchasing', '供货品类目录与历史供应商关联', s.supplier_categories),
        Migration('062-production-system-names', 'production', '三套磨浆系统完整名称', s.production_system_names),
        Migration('063-administrative-role','access','行政负责人与独立管理人事考勤',s.administrative_role),
        Migration('064-period-snapshot-status','resources','仅修正已结成本快照的未结账提示',s.period_snapshot_status),
        Migration('065-outsourced-delivery-categories','resources','外包配送费与历史配送工资分类',s.outsourced_delivery_categories),
        Migration('066-sales-query-indexes','core','销售日期、客户与状态查询索引',s.sales_query_indexes),
        Migration('067-resource-query-indexes','resources','费用、付款与豆渣日期查询索引',s.resource_query_indexes),
        Migration('068-finance-cash-query-indexes','bootstrap','资金来源实际日期与算票确认日期查询索引',s.finance_cash_query_indexes),
        Migration('069-expense-accrual-query','bootstrap','费用所属期派生索引与状态查询支持',s.expense_accrual_query),
        Migration('070-employee-bank-accounts','payroll','员工银行卡独立台账',s.employee_bank_accounts),
        Migration('071-purchase-history-indexes','purchasing','采购历史日期与原单关联查询索引',s.purchase_history_indexes),
        Migration('072-purchase-ledger-indexes','purchasing','采购验收付款及附加费日期查询索引',s.purchase_ledger_indexes),
        Migration('073-reuse-purchase-payment-date-index','purchasing','复用既有采购付款日期索引并移除重复项',s.reuse_purchase_payment_date_index),
        Migration('074-inventory-history-indexes','core','退货及加工历史日期与来源查询索引',s.inventory_history_indexes),
        Migration('075-material-history-indexes','resources','原辅料流水日期物料与稳定顺序索引',s.material_history_indexes),
        Migration('076-stock-history-indexes','core','成品日结历史实发更正关联索引',s.stock_history_indexes),
        Migration('077-check-history-indexes','assets','库存实盘核对历史类型日期索引',s.check_history_indexes),
        Migration('078-receipt-evidence','core','收款截图识别、交易单号台账与岗位授权',s.receipt_evidence),
        Migration('079-expense-estimates','bootstrap','成本暂估及不规则账单覆盖区间',s.expense_estimates_schema),
        Migration('080-irregular-expense-settings','bootstrap','不定期费用项目属性及既有日期账单兼容',s.irregular_expense_settings),
        Migration('081-open-stock-query','core','未日结收发存历史更正日期索引',s.open_stock_query_indexes),
        Migration('082-delivery-history','bootstrap','配送反馈与周转筐历史日期索引',s.delivery_history_indexes),
        Migration('083-delivery-provider-permissions','access','配送服务商与配送费结算菜单',s.delivery_provider_permissions),
        Migration('084-audit-query-indexes','bootstrap','审计与安全事件查询索引',s.audit_query_indexes),
        Migration('085-feedback-history-index','collaboration','问题反馈历史索引',s.feedback_query_indexes),
    Migration('086-archive-history-indexes','bootstrap','归档历史查询索引',s.archive_query_indexes),
        Migration('087-attendance-history-index','bootstrap','厂内考勤历史日期索引',s.attendance_history_indexes),
        Migration('088-payroll-history-indexes','bootstrap','工资与实际发放历史索引',s.payroll_history_indexes),
        Migration('089-schedule-day-index','bootstrap','排班按日读取索引',s.schedule_day_index),
    )


DEPENDENCIES = {
    'core': set(), 'auth': {'core'}, 'access': {'auth'},
    'resources': {'core'}, 'purchasing': {'resources'}, 'payroll': {'core'},
    'production-config': {'core'},
    'production': {'resources', 'payroll', 'production-config'},
    'assets': {'resources'}, 'driver': {'auth'},
    'collaboration': {'auth', 'access'},
    'bootstrap': {'access', 'purchasing', 'production', 'assets', 'driver', 'collaboration'},
    'billing': {'bootstrap'},
}


def _now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')


def _audit(c, role, action, entity, before, after):
    c.execute('INSERT INTO audit(at,role,action,entity,before_json,after_json,actor_id,actor_name,request_id) VALUES(?,?,?,?,?,?,?,?,?)',
              (_now(), role, action, str(entity), json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), '', '', ''))


def _table(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _marker(c, key):
    return bool(key and _table(c, 'meta') and c.execute('SELECT 1 FROM meta WHERE key=?', (key,)).fetchone())


def _records(c):
    if not _table(c, 'schema_migrations'): return {}
    columns = [r[1] for r in c.execute('PRAGMA table_info(schema_migrations)')]
    if not {'id', 'applied_at'} <= set(columns): raise MigrationError('迁移台账结构无法识别，请核对数据库版本')
    return {r[0]: dict(zip(columns, r)) for r in c.execute('SELECT * FROM schema_migrations')}


def _validate(c, specs, records):
    ids = [m.id for m in specs]
    if len(ids) != len(set(ids)): raise MigrationError('迁移目录编号重复')
    unknown = set(records) - set(ids)
    if unknown: raise MigrationError('数据库包含当前程序不认识的迁移，拒绝以旧程序启动：' + ', '.join(sorted(unknown)))
    if c.execute('PRAGMA user_version').fetchone()[0] > SCHEMA_VERSION:
        raise MigrationError('数据库结构版本高于当前程序，拒绝降级启动')
    for sequence, m in enumerate(specs, 1):
        if m.component not in DEPENDENCIES: raise MigrationError('迁移组件缺少依赖声明：' + m.component)
        prior = records.get(m.id)
        if prior and prior.get('checksum') and prior['checksum'] != m.checksum:
            raise MigrationError('已执行迁移的实现发生改变，请新增迁移而非覆盖：' + m.id)
        if prior and prior.get('sequence') is not None and prior['sequence'] != sequence:
            raise MigrationError('已执行迁移顺序发生改变，请在目录末尾新增步骤：' + m.id)
        if prior and prior.get('component') and prior['component'] != m.component:
            raise MigrationError('已执行迁移的组件归属发生改变：' + m.id)


def _ledger(c):
    c.execute('CREATE TABLE IF NOT EXISTS schema_migrations(id TEXT PRIMARY KEY,applied_at TEXT NOT NULL)')
    columns = {r[1] for r in c.execute('PRAGMA table_info(schema_migrations)')}
    for name, declaration in [('sequence', 'INTEGER'), ('component', "TEXT NOT NULL DEFAULT ''"), ('title', "TEXT NOT NULL DEFAULT ''"), ('checksum', "TEXT NOT NULL DEFAULT ''"), ('source', "TEXT NOT NULL DEFAULT ''")]:
        if name not in columns: c.execute('ALTER TABLE schema_migrations ADD COLUMN ' + name + ' ' + declaration)


def _components(component):
    if component is None: return set(DEPENDENCIES)
    if component not in DEPENDENCIES: raise MigrationError('未知迁移组件：' + str(component))
    found = set()
    def visit(key):
        if key in found: return
        found.add(key)
        for dependency in DEPENDENCIES[key]: visit(dependency)
    visit(component)
    return found


def ensure(c, component=None, *, context=None):
    """Apply selected components atomically; already-recorded steps never replay."""
    specs = registry(); records = _records(c); _validate(c, specs, records)
    selected = _components(component); ctx = {'demo': False, 'now': _now, 'audit': _audit, **(context or {})}
    started = not c.in_transaction
    if started: c.execute('BEGIN IMMEDIATE')
    c.execute('SAVEPOINT erp_schema_upgrade')
    executed = []
    try:
        # Re-read after acquiring the write lock, so two upgraders cannot replay.
        records = _records(c); _validate(c, specs, records); _ledger(c)
        for sequence, m in enumerate(specs, 1):
            prior = records.get(m.id)
            if prior:
                if not prior.get('checksum'):
                    c.execute('UPDATE schema_migrations SET sequence=?,component=?,title=?,checksum=?,source=? WHERE id=?',
                              (sequence, m.component, m.title, m.checksum, 'legacy-ledger', m.id))
                continue
            if m.component not in selected: continue
            if m.manual:
                # An existing kilogram marker is proof; never execute conversion here.
                if not (_marker(c, 'settlement_unit') and c.execute("SELECT value FROM meta WHERE key='settlement_unit'").fetchone()[0] == '公斤'): continue
                source = 'legacy-marker'
            elif _marker(c, m.legacy_marker):
                source = 'legacy-marker'
            else:
                m.apply(c, ctx); source = 'applied'; executed.append(m.id)
            c.execute('INSERT INTO schema_migrations(id,applied_at,sequence,component,title,checksum,source) VALUES(?,?,?,?,?,?,?)',
                      (m.id, ctx['now'](), sequence, m.component, m.title, m.checksum, source))
        if c.execute('PRAGMA foreign_key_check').fetchone(): raise MigrationError('迁移后外键核对失败，已撤销本次升级')
        if component is None: c.execute('PRAGMA user_version=' + str(SCHEMA_VERSION))
        c.execute('RELEASE erp_schema_upgrade')
    except Exception:
        c.execute('ROLLBACK TO erp_schema_upgrade'); c.execute('RELEASE erp_schema_upgrade')
        if started: c.rollback()
        raise
    return executed


def run_manual(c, migration_id, *, context=None):
    """Explicit business conversion; same ledger, transaction and integrity rules."""
    if not c.in_transaction: raise MigrationError('业务转换必须在已备份数据库的写事务内执行')
    specs = registry(); records = _records(c); _validate(c, specs, records)
    m = next((m for m in specs if m.id == migration_id and m.manual), None)
    if m is None: raise MigrationError('未知独立迁移')
    if m.id in records:
        if m.id == '900-billing-kilograms' and not __import__('billing').enabled(c): raise MigrationError('迁移台账与结算口径不一致，请核对数据库')
        return {'already_enabled': True}
    c.execute('SAVEPOINT erp_manual_upgrade')
    try:
        _ledger(c)
        result = m.apply(c, {'now': _now, 'audit': _audit, **(context or {})})
        if c.execute('PRAGMA foreign_key_check').fetchone(): raise MigrationError('业务转换后外键核对失败')
        c.execute('INSERT INTO schema_migrations(id,applied_at,sequence,component,title,checksum,source) VALUES(?,?,?,?,?,?,?)',
                  (m.id, _now(), specs.index(m) + 1, m.component, m.title, m.checksum, 'explicit'))
        c.execute('RELEASE erp_manual_upgrade')
        return result
    except Exception:
        c.execute('ROLLBACK TO erp_manual_upgrade'); c.execute('RELEASE erp_manual_upgrade'); raise


def upgrade(c, *, context=None, kilograms=False):
    """One boundary for the full requested upgrade, including opt-in conversion."""
    if not c.in_transaction: raise MigrationError('完整升级必须由调用方开启写事务')
    c.execute('SAVEPOINT erp_complete_upgrade')
    try:
        executed = ensure(c, context=context)
        conversion = run_manual(c, '900-billing-kilograms', context=context) if kilograms else None
        c.execute('RELEASE erp_complete_upgrade')
        return {'executed': executed, 'conversion': conversion}
    except Exception:
        c.execute('ROLLBACK TO erp_complete_upgrade'); c.execute('RELEASE erp_complete_upgrade'); raise


def status(c):
    """Read-only plan: never create a ledger, acquire a write lock or repair rows."""
    specs = registry(); records = _records(c); _validate(c, specs, records)
    return {'schema_version': c.execute('PRAGMA user_version').fetchone()[0], 'supported_schema_version': SCHEMA_VERSION,
            'steps': [{'id': m.id, 'sequence': i, 'component': m.component, 'title': m.title, 'mode': 'explicit' if m.manual else 'automatic',
                       'state': 'applied' if m.id in records else 'legacy' if _marker(c, m.legacy_marker) else 'pending',
                       'applied_at': records.get(m.id, {}).get('applied_at'), 'source': records.get(m.id, {}).get('source', '')} for i, m in enumerate(specs, 1)]}


def assert_current(c):
    """Read-only worker gate; deployment, rather than a request worker, upgrades."""
    plan = status(c)
    pending = [s['id'] for s in plan['steps'] if s['mode'] == 'automatic' and s['state'] != 'applied']
    if plan['schema_version'] != SCHEMA_VERSION or pending:
        raise MigrationError('数据库尚未完成当前版本升级，请先执行部署升级步骤')
    return plan
