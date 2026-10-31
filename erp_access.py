"""Stable module and action identifiers shared by navigation and request authorization.

The legacy catalog is retained for isolated compatibility tests. Account-mode
HTTP requests use authenticated route gates and scoped bootstrap projections.
"""
ROLES = ('库管', '会计', '出纳')
ACCOUNT_ROLES = (*ROLES,'老板','厂长','物流负责人','行政负责人','司机')
GROUPS = [('master','基础资料'),('purchase','采购管理'),('sales','销售管理'),('production','生产管理'),('inventory','库存管理'),('delivery','物流管理'),('finance','财务管理'),('asset','资产管理'),('hr','人力资源'),('system','系统管理'),('workspace','工作空间')]
# id, group, page, title, icon, description, optional master view
MODULES = [
    ('delivery.driver','delivery','driver-work','我的配送与回筐','⇄','司机查看本人配送、填报回筐并跟踪库管确认',''),
    ('asset.register','asset','assets','资产台账','◇','周转筐、设备与其他长期使用资产',''),
    ('asset.crates','asset','crates','筐子管理','▦','每日装货筐、空筐盘点与司机回筐',''),
    ('finance.payroll','hr','payroll','员工工资','▥','月薪 / 固定年薪、工资确认计入成本、未发余额与实际发放',''),
    ('master.suppliers','master','suppliers','供应商档案','♧','供应商联系方式、供货品类、账期与启停状态',''),
    ('purchase.orders','purchase','purchases','采购与外购成品登记','▤','原辅料采购订单、外购成品登记与未到货余量跟踪',''),
    ('purchase.receipts','purchase','purchase-receipts','采购验收入库','▦','分批验收入库，自动登记原辅料库存与成本',''),
    ('finance.payables','finance','payables','应付与采购付款','▥','按已验收入库形成应付，跟踪账期及付款',''),
    ('workspace.dashboard','workspace','dashboard','首页','◫','查看经营概况与业务待办',''),
    ('workspace.chat','workspace','chat','内部聊天','◫','同事私聊、群聊与未读消息提醒',''),
    ('workspace.directory','workspace','directory','功能总览','▦','按业务流程查找功能与岗位职责',''),
    ('sales.orders','sales','orders','订货管理','▤','客户订货、库存提示、订货打印',''),
    ('sales.archive','sales','archive','销售单据查询','▤','按客户、日期及归档编号查询对应结算单',''),
    ('inventory.reconciliation','inventory','allocation','库存与发货核对','▦','查看发货前后实盘、实发差异及客户反馈，不办理库存写入',''),
    ('inventory.operations','inventory','allocation','库存与发货分配','▦','库存生产、转加工、分配、隔离退货、日终结转',''),
    ('inventory.returns','sales','returns','退货与扣款','↩','库管登记、会计核定、出纳复核',''),
    ('inventory.cost','production','production','生产月报','▦','按月汇总产量、转加工、上豆量与已登记成本',''),
    ('inventory.materials','inventory','materials','原辅料库存','▦','大豆、辅料、耗材及包装入库领用盘点',''),
    ('finance.costs','finance','expenses','间接成本管理','▥','人工能源等期间费用登记、归集与月结',''),
    ('finance.expense-payables','finance','expense-payables','费用核销与付款','▥','出纳核对费用凭据、登记付款与跟踪未付余额',''),
    ('finance.byproducts','finance','byproducts','豆渣收入','↗','豆渣销售、实际到账和未收跟踪',''),
    ('finance.transport-settlement','finance','transport-settlement','配送费结算','⇢','按配送服务商核对已确认实发趟次、生成月度结算单与应付',''),
    ('workspace.report-map','workspace','report-map','报表地图','▦','按主题查找报表、数据就绪度及负责岗位',''),
    ('workspace.analytics','workspace','analytics','经营看板','◫','销售应收、材料耗用、费用结构与收入趋势',''),
    ('workspace.product-profit','workspace','product-profit','月度产品经营测算','▦','按产品查看月度收入、成本与经营测算，缺项另列',''),
    ('delivery.providers','delivery','transport-providers','配送服务商','☎','外包配送服务商档案与按客户地区生效的每趟运费',''),
    ('delivery.dispatch','delivery','dispatch','车辆排班','⇄','车辆司机、趟次安排及承包方独立台账，具体操作分别授权',''),
    ('delivery.weighing','delivery','weighing','发货称重','▧','实发核对、司机称重、客户复称与交会计',''),
    ('finance.settlement','finance','settlements','算票复核','⚖','会计算票、协商、出纳复核',''),
    ('finance.accounts','finance','fund-accounts','资金账户','▥','银行、现金等账户管理、账面余额与实际收付款流水',''),
    ('finance.receivables','finance','ledger','应收与收款','▥','客户应收、退货抵扣与到账登记',''),
    ('master.customers','master','masters','客户档案','♧','客户、地区、市场与配送方式','customers'),
    ('master.products','master','masters','产品资料','♧','产品、单位、规格与显示顺序','products'),
    ('master.pricing','master','masters','客户价格与皮重','♧','客户专属价格与皮重规则','pricing'),
    ('system.audit','system','logs','审计与维护','◷','操作追溯、数据库备份、试运行归档恢复',''),
    ('system.feedback','system','feedback','问题反馈','◷','向管理员提交问题、建议并跟踪回复',''),
    ('system.access','system','access','账号与权限','◇','功能权限矩阵与上线权限准备情况',''),
]
MODULES += [
 ('management.staff','hr','management-employees','管理人员档案','♧','行政负责人维护管理人员，不操作生产工人',''),
 ('management.attendance','hr','management-attendance','管理考勤','▤','行政负责人登记管理人员当天与整月考勤',''),
 ('production.manage','production','factory','上豆与浆缸','▦','每日上豆、泡豆桶与各产品浆缸数',''),
 ('production.issue','production','material-issue','原辅料领用','▦','按天登记辅料与包装领用，按承担产品与覆盖期分摊',''),
 ('production.workshop','production','workshop','车间余料','▦','月末盘点车间剩余辅料，按实耗结转当月成本',''),
 ('production.staff','hr','employees','生产人员档案','♧','生产工人部门岗位、联系方式与生产班组，管理人员另设入口',''),
 ('production.attendance','hr','attendance','生产考勤','▤','登记生产工人实际出勤、请假与整月考勤，保留生产排班',''),
 ('production.curing','production','curing','熏制登记','◫','登记当天用白干熏制的投入量，扣白干库存并按白干出品率折豆计入黄干',''),
 ('production.daily','production','production-report','生产日报','◫','用豆交叉核验、出品率、领料与考勤',''),
 ('production.inventory','inventory','soy-inventory','大豆分析','▦','四库黄豆、批次质量、FIFO与原辅料预警',''),
 ('production.settings','production','factory-settings','生产参数','◇','分类维护泡豆桶、浆缸与生产核对参数',''),
 ('sales.reports','sales','sales-daily','销售报表','◫','订货与实发核对、算票与收款进度、客户产品与市场销量',''),
]
# Stable action key, label, module, allowed pilot roles.
ACTIONS = [
    ('driver.weights','司机登记本人配送称重','delivery.driver',('司机',)),
    ('driver.returns','司机填报本人回筐','delivery.driver',('司机',)),
    ('crates.confirm','库管确认司机回筐','asset.crates',('库管',)),
    ('assets.write','维护资产台账','asset.register',('会计',)),
    ('crates.write','登记回筐与筐子盘点','asset.crates',('库管','会计')),
    ('suppliers.write','维护供应商档案','master.suppliers',('会计',)),
    ('purchases.write','保存 / 确认 / 关闭采购单','purchase.orders',('会计',)),
    ('purchases.receive','采购验收入库','purchase.receipts',('库管','会计')),
    ('purchases.cost','采购费用 / 外购成品算票','finance.payables',('会计',)),
    ('purchases.pay','登记采购付款','finance.payables',('出纳',)),
    ('orders.write','保存订货 / 修订单据','sales.orders',ROLES[:2]),
    ('inventory.stock','保存库存 / 拟实发','inventory.operations',ROLES[:2]),
    ('inventory.dispatch','确认写入实发','inventory.operations',ROLES[:2]),
    ('inventory.process','登记厂内转加工','inventory.operations',ROLES[:2]),
    ('inventory.close','确认 / 撤销日结','inventory.operations',ROLES[:2]),
    ('returns.register','登记退货、可发 / 转加工 / 报损去向及作废','inventory.returns',ROLES[:2]),
    ('returns.account','核定退货扣款','inventory.returns',('会计',)),
    ('returns.retract','退回退货核定','inventory.returns',('会计','出纳')),
    ('returns.review','复核退货抵账','inventory.returns',('出纳',)),
    ('returns.refund','登记退货退款','inventory.returns',('出纳',)),
    ('delivery.schedule','保存派车 / 车辆司机','delivery.dispatch',('库管','会计','物流负责人')),
    ('weight.confirm','确认称重交会计','delivery.weighing',ROLES[:2]),
    ('finance.settle','客户算票','finance.settlement',('会计',)),
    ('finance.review','复核应收入账','finance.settlement',('出纳',)),
    ('finance.statement-issue','出具及归档对账单','finance.receivables',('会计','出纳')),
    ('finance.review-return','退回会计重算','finance.settlement',('出纳',)),
    ('funds.manage','维护资金账户、流水归属与内部转账','finance.accounts',('会计','出纳')),
    ('finance.receipt','登记实际收款','finance.receivables',('出纳',)),
    ('finance.evidence','识别并查看收款截图','finance.receivables',('会计','出纳')),
    ('master.write','维护基础资料 / 价格规则','master.customers',('会计',)),
    ('system.archive','单据归档 / 试运行清理恢复','system.audit',('会计',)),
    ('system.operator-users','维护经办人名单','system.access',('会计',)),
    ('materials.write','原辅料入库 / 领用 / 盘点','inventory.materials',ROLES[:2]),
    ('materials.value','登记原辅料金额','inventory.materials',('会计',)),
    ('costs.write','登记 / 更正费用、分类与收款方','finance.costs',('会计','出纳')),
    ('costs.close','成本月结 / 重开','finance.costs',('会计',)),
    ('costs.review','核对间接成本凭据','finance.expense-payables',('出纳',)),
    ('costs.pay','登记间接成本付款','finance.expense-payables',('出纳',)),
    ('byproducts.write','豆渣销售 / 收款','finance.byproducts',('会计','出纳')),
    ('system.backup','生成数据库备份','system.audit',('会计',)),
]
ACTIONS += [
 ('production.curing.write','登记熏制投入','production.curing',('厂长',)),
 ('payroll.write','设置月薪 / 年薪、确认工资及归集成本','finance.payroll',('会计',)),
 ('payroll.pay','登记工资发放','finance.payroll',('出纳',)),
 ('production.staff','维护生产工人与生产班组','production.staff',('厂长',)),
 ('production.attendance','登记生产工人当天 / 整月考勤与生产排班','production.attendance',('厂长',)),
 ('production.record','登记每日用浆与浆缸','production.manage',('厂长',)),
 ('finance.alert-settings','调整应收金额与账龄预警','finance.receivables',('会计','出纳')),
 ('production.settings','设置生产换算与称重阈值','production.settings',('厂长','会计')),
 ('materials.issue','登记生产原料领用','production.issue',('厂长',)),
]
ACTION_MAP = {key: (label, module, roles) for key, label, module, roles in ACTIONS}
ORDER_ACTIONS = {'order':'orders.write','confirm-weight':'weight.confirm','settle':'finance.settle','negotiate':'finance.settle','review':'finance.review','return-review':'finance.review-return','receipt':'finance.receipt','void-receipt':'finance.receipt'}

def require(role, permission):
    definition=next((item for item in [*ACTIONS,*EXTRA_ACTIONS] if item[0]==permission),None)
    if definition is None:raise ValueError('未知操作权限：'+str(permission))
    label, _, _, allowed = definition
    if role not in allowed:
        raise ValueError(label+'请由'+'或'.join(allowed)+'操作；当前岗位无此操作权限')

def authorize(path, body, role):
    """本机试运行（未启用账号）与登录态共用同一张动作权限表，避免两套规则漂移。"""
    needed=mutation_permissions(path or '',body if isinstance(body,dict) else {})
    if needed is None:return
    for key in needed:
        if key=='__unknown__':raise ValueError('未知操作权限')
        require(role,key)

def catalog():
    # 未登录的演示 / 本机模拟态也按岗位默认值投影，避免与登录后的权限矩阵差一张动作表
    roles=['管理员',*ACCOUNT_ROLES]
    configs={role:defaults(role) for role in roles}
    return {'version':1,'mode':'pilot','authenticated':False,'read_scope':'shared',
        'roles':roles,'groups':[{'id':key,'title':title} for key,title in GROUPS],
        'modules':[{**{k:v for k,v in m.items() if k!='read_roles'},'read_roles':[r for r in roles if m['id'] in configs[r]['modules']]} for m in module_definitions()],
        'actions':[{**{k:v for k,v in a.items() if k!='roles'},'roles':[r for r in roles if a['id'] in configs[r]['actions']]} for a in action_definitions()]}

# Authenticated authorization is data-driven; admins always have all rights.
import contextvars
import json
GRANTS=contextvars.ContextVar('erp_grants',default=None)
EXTRA_ACTIONS=[('finance.price-edit','修改单据单价','master.pricing',('会计',)),('system.users','维护用户 / 岗位 / 密码','system.users',('管理员',)),('system.permissions','配置岗位权限','system.access',('管理员',)),('system.parameters','审批业务参数修改','system.parameters',('管理员',))]
DATA_SCOPES=[('sales-prices','销售单价与结算金额','销售价格、算票、应收与到账'),('purchase-prices','采购价格与应付金额','货款、运装费、实际采购单价及付款'),('material-costs','原辅料成本金额','库存金额、加权单价与耗用成本'),('supplier-terms','供应商账期与税务资料','账期、税号等财务资料')]
ROLE_NOTES={'行政负责人':'维护管理人员档案和管理考勤；默认不查看薪资，不操作生产人员、生产考勤或工资发放。','物流负责人':'维护车辆司机档案和配送安排；承包方独立人员考勤另设查看、维护权限，不进入厂内工资与成本。','司机':'仅查看本人配送，填报回筐并提交库管确认。','库管':'订货、验收、库存、派车和称重交接；查看数量，不查看价格与公司经营金额。','会计':'维护客户与定价，管理采购、退货核定、材料计价和成本月结；不确认收付款。','出纳':'核对销售原始凭据，复核应收并登记收付款；不修改价格、采购单或成本核算。','厂长':'维护生产工人档案、生产班组和生产考勤，登记生产与原料领用；管理人员档案、管理考勤需单独授权。','老板':'只读查看经营、销售、采购、库存和成本；不办理单据或维护系统。'}
EXTRA_ACTIONS += [
 ('management.staff','维护管理人员档案','management.staff',('行政负责人',)),
 ('management.attendance','登记管理人员当天 / 整月考勤','management.attendance',('行政负责人',)),
 ('delivery.contractors.read','查看承包方人员与独立考勤','delivery.dispatch',('物流负责人',)),
 ('delivery.contractors.write','维护承包方人员与独立考勤','delivery.dispatch',('物流负责人',)),
 ('master.customers.write','维护客户 / 配送点资料','master.customers',('会计',)),
 ('master.products.write','维护产品 / 规格 / 排序','master.products',('会计',)),
 ('master.pricing.write','维护客户专属价格 / 皮重','master.pricing',('会计',)),
 ('weight.write','填写 / 更正实发与原始称重','delivery.weighing',('库管','会计')),
 ('materials.catalog','维护物料 / 库存预警','inventory.materials',('会计',)),
 ('materials.void','作废原辅料流水','inventory.materials',('会计',)),
 ('costs.void','作废期间成本记录','finance.costs',('会计',)),
 ('byproducts.receive','登记豆渣实际收款','finance.byproducts',('出纳',)),
 ('byproducts.void','作废未收款豆渣销售','finance.byproducts',('会计',)),
]
ACTION_MODULES={key:module for key,_,module,_ in [*ACTIONS,*EXTRA_ACTIONS]}
LEGACY_ACTIONS={'master.customers.write':'master.write','master.products.write':'master.write','master.pricing.write':'master.write','materials.catalog':'materials.write','materials.void':'materials.write','costs.void':'costs.write','byproducts.receive':'byproducts.write','byproducts.void':'byproducts.write','weight.write':'orders.write'}
def master_permission(kind):return {'customer':'master.customers.write','delivery_market':'master.customers.write','product':'master.products.write','rule':'master.pricing.write','delivery_vehicle':'delivery.schedule'}.get(kind,'master.write')
def inferred_scopes(grants):
    mods=set(grants.get('modules',[]));actions=set(grants.get('actions',[]));result=set()
    if mods & {'master.pricing','finance.settlement','finance.receivables','workspace.analytics','sales.reports'}:result.add('sales-prices')
    if mods & {'finance.payables','workspace.analytics'} or actions & {'purchases.write','purchases.cost','purchases.pay'}:result.add('purchase-prices')
    if mods & {'finance.costs','workspace.analytics','inventory.cost'} or 'materials.value' in actions:result.add('material-costs')
    if 'suppliers.write' in actions or mods & {'finance.payables','workspace.analytics'}:result.add('supplier-terms')
    return sorted(result)
def can_read_data(grants,key):return key in grants.get('data_scopes',inferred_scopes(grants))
def require_detail(role,key):
    if GRANTS.get() is not None:require_role(role,key)
PROTECTED_MODULES={'system.users','system.access','system.parameters'}
PROTECTED_ACTIONS={'system.users','system.permissions','system.parameters'}
ACTION_ROLE_LIMITS={'delivery.contractors.read':('物流负责人',),'delivery.contractors.write':('物流负责人',)}
ACTION_DEPENDENCIES={'delivery.contractors.write':{'delivery.contractors.read'},'crates.confirm':{'crates.write'},'inventory.dispatch':{'inventory.stock'},'finance.settle':{'orders.write'}}

FEATURE_PERMISSIONS=[
 {'feature':'生产人员与生产班组','read':['production.staff'],'write':['production.staff'],'note':'只维护生产工人与班组；管理人员另行授权。工资标准还需员工工资查看及工资核算权限。'},
 {'feature':'管理人员档案与管理考勤','read':['management.staff','management.attendance'],'write':['management.staff','management.attendance'],'note':'行政负责人默认维护；管理档案和考勤分别授权，不查看工资。生产权限不隐含管理权限。'},
 {'feature':'当天 / 整月生产考勤、生产排班','read':['production.attendance'],'write':['production.attendance'],'note':'考勤权限可保存整月实际考勤；不能读取薪资或登记工资发放。'},
 {'feature':'月薪 / 固定年薪及工资成本','read':['finance.payroll'],'write':['payroll.write'],'note':'设置标准、确认 / 撤回工资、补计历史成本；确认即归集成本，不能代替实际发放。'},
 {'feature':'实际工资发放','read':['finance.payroll'],'write':['payroll.pay'],'note':'仅冲减已确认工资的未发余额并记录资金支出，不修改工资标准和已确认成本。'},
 {'feature':'承包方独立人员与考勤','read':['delivery.dispatch'],'write':['delivery.contractors.read','delivery.contractors.write'],'note':'仅管理员、物流负责人；查看、维护分别授权，维护还需查看。不写入厂内员工、工资或人工成本。'},
 {'feature':'费用分类、收款方、跨月费用','read':['finance.costs'],'write':['costs.write'],'note':'费用收款方独立于采购供应商；年租金按所属月分摊。自动工资成本只能在员工工资更正。'},
 {'feature':'费用核对与付款','read':['finance.expense-payables'],'write':['costs.review','costs.pay'],'note':'核对凭据与实际付款分别授权；供应商采购付款、工资发放继续使用各自入口。'},
 {'feature':'退货可发 / 转加工 / 报损去向','read':['inventory.returns'],'write':['returns.register','inventory.process'],'note':'登记和选择退货去向需退货登记权限；执行转加工产出另需库存转加工权限；核价、复核和退款仍分别授权。'},
 {'feature':'报表地图与产品经营测算','read':['workspace.report-map'],'write':[],'note':'地图按本人可读模块过滤入口；查看地图不会扩大报表和经营金额权限。产品测算沿用经营看板或产品测算查看权限。'},
]
def permission_metadata():return {'action_dependencies':{k:sorted(v) for k,v in ACTION_DEPENDENCIES.items()},'feature_permissions':FEATURE_PERMISSIONS}

def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'access')


def module_definitions():
    # 不依赖 catalog()：catalog() 需要按岗位默认值投影，若再回头取本表会无限递归
    return [{'id':key,'group':group,'page':page,'title':title,'icon':icon,'description':description,'view':view,'read_roles':list(ROLES)} for key,group,page,title,icon,description,view in MODULES]+[{'id':'system.users','group':'system','page':'users','title':'用户管理','icon':'♧','description':'账号、岗位、停用与密码重设','view':'','read_roles':['管理员']},{'id':'system.parameters','group':'system','page':'system-settings','title':'参数设置','icon':'◇','description':'按岗位查看业务参数、申请修改及管理员审批','view':'','read_roles':['管理员']}]

def action_definitions():
    return [{'id':k,'title':title,'module':module,'roles':list(roles),**({'assignable_roles':list(ACTION_ROLE_LIMITS[k])} if k in ACTION_ROLE_LIMITS else {})} for k,title,module,roles in [*ACTIONS,*EXTRA_ACTIONS]]

PARAMETER_WEIGHT_MODULES={'delivery.dispatch','delivery.weighing','delivery.analysis','finance.settlement','production.settings','workspace.analytics'}
PARAMETER_PRODUCTION_MODULES={'production.manage','production.daily','production.inventory','production.settings','sales.reports','workspace.analytics'}

def parameter_groups_visible(grants):
    modules=set(grants.get('modules',[]));groups=set()
    if modules & PARAMETER_WEIGHT_MODULES:groups.add('weight')
    if modules & PARAMETER_PRODUCTION_MODULES:groups.update(('production','soaking','slurry'))
    if modules & {'finance.receivables','workspace.analytics'} and can_read_data(grants,'sales-prices'):groups.add('receivables')
    return groups

def parameter_navigation(value,role):
    value={**value,'modules':[m for m in value.get('modules',[]) if m!='system.parameters']}
    if role!='司机' and (parameter_groups_visible(value) or set(value['modules']) & {'master.products','master.pricing','inventory.materials'}):value['modules'].append('system.parameters')
    if role!='司机' and role in (*ACCOUNT_ROLES,'管理员'):
        value['modules']=list(dict.fromkeys([*value['modules'],'workspace.report-map']))
    else:value['modules']=[m for m in value['modules'] if m!='workspace.report-map']
    if set(value['modules']) & {'inventory.operations','finance.settlement','workspace.analytics'}:
        value['modules']=list(dict.fromkeys([*value['modules'],'inventory.reconciliation']))
    return value

def base_defaults(role):
    all_scopes=[k for k,_,_ in DATA_SCOPES]
    if role=='管理员':return {'role':role,'version':0,'modules':[m['id'] for m in module_definitions()],'actions':[a['id'] for a in action_definitions()],'data_scopes':all_scopes}
    if role=='司机':return {'role':role,'version':0,'modules':['workspace.dashboard','workspace.chat','workspace.directory','system.feedback','delivery.driver'],'actions':['driver.returns','driver.weights'],'data_scopes':[]}
    if role=='行政负责人':return {'role':role,'version':0,'modules':['workspace.dashboard','workspace.chat','workspace.directory','system.feedback','management.staff','management.attendance'],'actions':['management.staff','management.attendance'],'data_scopes':[]}
    if role=='物流负责人':return {'role':role,'version':0,'modules':['workspace.dashboard','workspace.chat','workspace.directory','system.feedback','delivery.providers','delivery.dispatch'],'actions':['delivery.schedule','delivery.contractors.read','delivery.contractors.write'],'data_scopes':[]}
    if role=='老板':return {'role':role,'version':0,'modules':[m['id'] for m in module_definitions() if m['page'] not in ('logs','access','users','employees','attendance','management-employees','management-attendance')],'actions':[],'data_scopes':all_scopes}
    common=['workspace.dashboard','workspace.chat','workspace.directory','system.feedback','master.customers','master.products']
    modules={
      '厂长':common+['production.manage','production.issue','production.staff','production.attendance','production.daily','production.inventory','production.settings','production.curing','inventory.materials','inventory.operations'],
      '库管':common+['master.suppliers','purchase.orders','purchase.receipts','sales.orders','inventory.operations','inventory.returns','inventory.materials','delivery.providers','delivery.dispatch','delivery.weighing'],
      '会计':common+['master.suppliers','master.pricing','purchase.orders','purchase.receipts','sales.orders','sales.archive','inventory.returns','inventory.materials','delivery.providers','delivery.weighing','finance.settlement','finance.receivables','finance.payables','finance.costs','finance.byproducts','finance.transport-settlement','inventory.cost','workspace.product-profit'],
      '出纳':common+['sales.archive','inventory.returns','finance.settlement','finance.receivables','finance.payables','finance.byproducts','finance.transport-settlement'],
    }.get(role,[])
    if role in ('会计','出纳'):modules+=['finance.accounts','sales.reports','finance.payroll','finance.expense-payables']
    if role in ('库管','会计'):modules+=['asset.register','asset.crates']
    if role=='会计':modules+=['production.daily','production.inventory']
    if role=='库管':modules+=['production.inventory']
    actions={
      '厂长':['production.staff','production.attendance','production.record','production.settings','production.curing.write','materials.issue','inventory.process'],
      '库管':['orders.write','weight.write','inventory.stock','inventory.dispatch','inventory.process','inventory.close','returns.register','delivery.schedule','weight.confirm','materials.write','purchases.receive'],
      '会计':['weight.write','weight.confirm','payroll.write','finance.alert-settings','finance.evidence','orders.write','finance.settle','finance.price-edit','finance.statement-issue','master.customers.write','master.products.write','master.pricing.write','suppliers.write','purchases.write','purchases.cost','returns.account','returns.retract','materials.value','materials.catalog','materials.void','costs.write','costs.void','costs.close','byproducts.write','byproducts.void'],
      '出纳':['payroll.pay','finance.alert-settings','finance.evidence','finance.review','finance.review-return','finance.receipt','finance.statement-issue','returns.review','returns.retract','returns.refund','purchases.pay','byproducts.receive'],
    }.get(role,[])
    if role in ('会计','出纳'):actions+=['funds.manage']
    if role in ('库管','会计'):actions+=['crates.write']
    if role=='库管':actions+=['crates.confirm']
    if role=='会计':actions+=['assets.write']
    if role=='出纳':actions+=['costs.review','costs.pay']
    scopes={'库管':[],'会计':all_scopes,'出纳':['sales-prices','purchase-prices','supplier-terms']}.get(role,[])
    return {'role':role,'version':0,'modules':modules,'actions':actions,'data_scopes':scopes}

def defaults(role):return parameter_navigation(base_defaults(role),role)

def _tighten_declared_roles():
    """收窄越界声明：费用与分类的登记归会计，出纳只做核对与付款。"""
    global ACTIONS,EXTRA_ACTIONS,ACTION_MAP
    narrow={'costs.write':('会计',)}
    ACTIONS[:]=[(key,label,module,narrow.get(key,roles)) for key,label,module,roles in ACTIONS]
    EXTRA_ACTIONS[:]=[(key,label,module,narrow.get(key,roles)) for key,label,module,roles in EXTRA_ACTIONS]
    ACTION_MAP={key:(label,module,roles) for key,label,module,roles in ACTIONS}

_tighten_declared_roles()

def _with_required_modules(modules,actions):
    """Keep each granted action's own page visible; older saved roles may predate a page split.

    Covers both action tables (ACTIONS and EXTRA_ACTIONS) and never re-opens a protected
    admin page, so reading an old role cannot silently escalate its page scope.
    """
    result=list(dict.fromkeys(modules))
    for key in actions or []:
        module=ACTION_MODULES.get(key)
        if module and module not in PROTECTED_MODULES and module not in result:result.append(module)
    return result

def permissions(c,role):
    if role=='管理员':return defaults(role)
    if role not in ACCOUNT_ROLES:return {'role':role,'version':0,'modules':[],'actions':[]}
    row=c.execute('SELECT version,payload FROM role_permissions WHERE role=?',(role,)).fetchone()
    if not row:return defaults(role)
    value=json.loads(row['payload']);value['modules']=_with_required_modules(list(dict.fromkeys(['workspace.dashboard','workspace.directory',*value.get('modules',[])])),value.get('actions',[]));return parameter_navigation({**value,'data_scopes':value.get('data_scopes',inferred_scopes(value)),'role':role,'version':row['version']},role)

def role_can(role,key):
    if role=='老板':return False
    if key in ACTION_ROLE_LIMITS and role not in ('管理员',*ACTION_ROLE_LIMITS[key]):return False
    current=GRANTS.get()
    if current is not None:return key in current['actions'] or ('data_scopes' not in current and LEGACY_ACTIONS.get(key) in current['actions'])
    if role=='管理员':return True
    return role in next((roles for k,_,_,roles in [*ACTIONS,*EXTRA_ACTIONS] if k==key),())

def require_role(role,key):
    if not role_can(role,key):
        allowed=next((roles for k,_,_,roles in [*ACTIONS,*EXTRA_ACTIONS] if k==key),())
        raise ValueError(('此操作请由'+'或'.join(allowed)+'处理；' if GRANTS.get() is None and allowed else '')+'当前账号无此操作权限')

def required_modules(key):
    if key=='master.write':return {'master.customers','master.products','master.pricing'}
    definition=next(a for a in action_definitions() if a['id']==key)
    result={definition['module']}
    if key in ('returns.account','returns.retract','returns.review','returns.refund'):result.add('finance.receivables')
    return result

def save_permissions(c,actor,body,now,audit):
    import auth
    if actor['role']!='管理员':raise auth.AuthError(403,'仅管理员可以配置岗位权限')
    role=body.get('role')
    if role not in ACCOUNT_ROLES:raise auth.AuthError(400,'只能配置业务岗位（含厂长）和老板；管理员始终拥有全部权限')
    old=permissions(c,role)
    if type(body.get('version')) is not int or body['version']!=old['version']:raise auth.AuthError(409,'岗位权限已被其他页面修改，请重新读取后保存')
    modules=body.get('modules');actions=body.get('actions')
    if isinstance(modules,list):modules=[m for m in modules if m!='system.parameters'] # Derived from existing business permissions; never an additional grant.
    valid_modules={m['id'] for m in module_definitions()}-PROTECTED_MODULES
    valid_actions={a['id'] for a in action_definitions()}-PROTECTED_ACTIONS
    for value,valid in [(modules,valid_modules),(actions,valid_actions)]:
        if not isinstance(value,list) or any(not isinstance(v,str) or v not in valid for v in value) or len(value)!=len(set(value)):raise auth.AuthError(400,'权限列表包含未知、重复或管理员专属权限')
    if role=='老板' and actions:raise auth.AuthError(400,'老板为经营查看岗位，仅能配置查看范围，不授予业务操作权限')
    for action in actions:
        if action in ACTION_ROLE_LIMITS and role not in ACTION_ROLE_LIMITS[action]:raise auth.AuthError(400,'承包方独立台账仅可授权物流负责人，其他岗位不适用')
        if not ACTION_DEPENDENCIES.get(action,set())<=set(actions):raise auth.AuthError(400,'此操作还需要关联录入权限，请同时勾选')
        if not required_modules(action)<=set(modules):raise auth.AuthError(400,'操作权限必须同时勾选对应功能的查看权限')
    scopes=body.get('data_scopes',inferred_scopes({'modules':modules,'actions':actions}))
    if not isinstance(scopes,list) or any(k not in {r[0] for r in DATA_SCOPES} for k in scopes) or len(scopes)!=len(set(scopes)):raise auth.AuthError(400,'信息查看范围无效')
    needed={'sales-prices':{'finance.price-edit','finance.settle','finance.review','finance.receipt','master.pricing.write','master.products.write','master.write','finance.statement-issue','returns.account','returns.review','returns.refund'},'purchase-prices':{'purchases.write','purchases.cost','purchases.pay'},'material-costs':{'materials.value','costs.close'},'supplier-terms':{'suppliers.write'}}
    if any(set(actions)&keys and key not in scopes for key,keys in needed.items()):raise auth.AuthError(400,'此操作需要对应的金额信息查看权限')
    if 'workspace.analytics' in modules and set(scopes)!={k for k,_,_ in DATA_SCOPES}:raise auth.AuthError(400,'经营看板需要完整的经营金额查看范围')
    result={'role':role,'version':old['version']+1,'modules':sorted(modules),'actions':sorted(actions),'data_scopes':sorted(scopes)}
    c.execute('INSERT INTO role_permissions VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET version=excluded.version,payload=excluded.payload,updated_at=excluded.updated_at',(role,result['version'],json.dumps(result,ensure_ascii=False),now()))
    revoked=c.execute('DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM auth_users WHERE role=?)',(role,)).rowcount
    audit(c,actor['role'],'修改岗位权限',role,old,{**result,'revoked_sessions':revoked})
    c.execute('INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)',(__import__('time').time().__int__(),'permissions.update',actor['id'],role,json.dumps({'before':old,'after':result,'revoked_sessions':revoked},ensure_ascii=False)))
    return {**result,'revoked_sessions':revoked}

READ_MODULES={'/api/order-corrections':{'finance.settlement','finance.receivables'},'/api/gel-tofu':{'production.manage','production.daily'},'/api/finished-goods':{'purchase.orders','purchase.receipts','finance.payables','finance.settlement'},'/api/trade':{'asset.crates','master.customers','delivery.weighing','finance.settlement'},'/api/transport':{'delivery.providers','delivery.dispatch','finance.costs','finance.expense-payables','finance.transport-settlement'},'/api/driver/return-options':{'delivery.driver'},'/api/driver':{'delivery.driver'},'/print/driver-delivery':{'delivery.driver'},'/api/assets':{'asset.register','asset.crates'},'/print/payroll-slip':{'finance.payroll'},'/print/attendance-month':{'production.attendance','management.attendance','finance.payroll'},'/print/payroll':{'finance.payroll'},'/api/purchasing':{'master.suppliers','purchase.orders','purchase.receipts','finance.payables','workspace.analytics'},'/api/resources':{'inventory.materials','finance.costs','finance.expense-payables','finance.byproducts','workspace.analytics'},'/api/byproduct-settlement':{'finance.byproducts','finance.costs','workspace.analytics'},'/api/product-profit':{'workspace.analytics','workspace.product-profit','finance.costs'},'/api/receivables':{'finance.receivables','finance.settlement'},'/api/export':{'finance.receivables','finance.settlement'},'/api/statement-documents':{'finance.receivables','finance.settlement'},'/api/statement-batch-preview':{'finance.receivables','finance.settlement'},'/api/customer-statement':{'finance.receivables','finance.settlement'},'/api/inventory':{'inventory.operations'},'/print/orders':{'sales.orders','delivery.dispatch'}}
READ_MODULES['/api/statement-status']={'finance.receivables','finance.settlement'}
READ_MODULES['/api/purchase-ledger']={'purchase.receipts','finance.payables'}
READ_MODULES['/print/returns']={'inventory.returns','inventory.operations','finance.receivables'}
READ_MODULES['/print/purchases']={'purchase.orders','purchase.receipts','finance.payables','workspace.analytics'}
READ_MODULES['/api/transport-providers']={'delivery.providers','delivery.dispatch','finance.costs','finance.expense-payables'}
READ_MODULES['/api/transport-provider-quotes']={'delivery.providers','finance.costs','finance.transport-settlement'}
READ_MODULES['/api/audit']={'system.audit'}
READ_MODULES['/api/audit-integrity']={'system.audit'}
READ_MODULES['/api/archive-records']={'system.audit'}
READ_MODULES['/api/security-events']={'system.audit'}
READ_MODULES['/api/purchase-orders']={'purchase.orders'}
READ_MODULES['/api/employee-banks']={'finance.payroll'}
READ_MODULES['/api/social-compensation']={'finance.payroll'}
READ_MODULES['/api/crate-packaging']={'finance.settlement','master.pricing','asset.crates','asset.register'}
READ_MODULES['/api/crate-ledger']={'sales.orders','asset.crates','finance.receivables'}
READ_MODULES['/api/payroll-history']={'finance.payroll'}
READ_MODULES['/api/payroll-history-record']={'finance.payroll'}
READ_MODULES['/api/attendance-history']={'production.attendance','management.attendance','finance.payroll'}
READ_MODULES['/api/attendance-day']={'production.attendance','management.attendance'}
READ_MODULES['/api/attendance-month-count']={'production.attendance','management.attendance'}
READ_MODULES['/api/expense-record']={'finance.costs','finance.expense-payables'}
READ_MODULES['/api/expense-options']={'finance.costs'}
READ_MODULES['/api/expense-workflow']={'finance.costs','finance.expense-payables'}
READ_MODULES['/api/resource-ledger']={'finance.costs','finance.expense-payables','finance.byproducts'}
READ_MODULES['/api/expense-close-preview']={'finance.costs'}
READ_MODULES['/api/expense-estimates']={'finance.costs'}
READ_MODULES['/api/expense-coverage-preview']={'finance.costs'}
READ_MODULES.update({k:{'delivery.providers','delivery.dispatch','delivery.weighing','finance.settlement','finance.costs','finance.expense-payables','finance.transport-settlement','asset.crates','asset.register'} for k in ('/api/delivery-history','/api/delivery-history-record')})
READ_MODULES['/api/open-stock-history']={'inventory.operations'}
READ_MODULES['/api/stock-history']={'inventory.operations'}
READ_MODULES['/api/material-history']={'inventory.materials','workspace.analytics','inventory.cost'}
READ_MODULES['/api/curing']={'production.curing','production.manage','production.daily','inventory.cost','workspace.analytics'}
READ_MODULES['/api/material-issue']={'production.issue','inventory.materials','production.manage','production.daily','inventory.cost','workspace.analytics'}
READ_MODULES['/api/workshop']={'production.workshop','inventory.materials','production.manage','production.daily','inventory.cost','workspace.analytics'}
READ_MODULES['/api/inventory-history']={'inventory.returns','finance.receivables','workspace.analytics','inventory.operations','inventory.cost'}
READ_MODULES['/api/inventory-check-history']={'inventory.operations','inventory.reconciliation'}
READ_MODULES['/api/inventory-check-record']={'inventory.operations','inventory.reconciliation'}
READ_MODULES['/api/inventory-check']={'inventory.operations','inventory.reconciliation'}
READ_MODULES['/api/report-directory']={'workspace.report-map'}
READ_MODULES['/api/fund-accounts']={'finance.accounts'}
READ_MODULES['/api/byproduct-summary']={'finance.byproducts','finance.receivables'}
READ_MODULES['/api/byproduct-sales']={'finance.byproducts','finance.receivables'}
READ_MODULES['/api/audit-rollback-plan']={'system.audit'}
READ_MODULES.update({key:{'finance.byproducts','finance.receivables','workspace.analytics'} for key in ('/api/byproduct-statement','/api/byproduct-documents')})

def authorize_read(path,user):
    import auth
    if isinstance(user,str):user={'role':user,'permissions':defaults(user)}
    if user['role']=='司机' and path not in ('/api/bootstrap','/api/auth/session','/api/driver','/api/driver/return-options','/print/driver-delivery','/api/chat','/api/chat/messages','/api/notifications','/api/feedback'):raise auth.AuthError(403,'司机账号只能查看本人的配送、回筐与内部消息')
    if path in ('/api/bootstrap','/api/auth/session','/api/factory/report'):return
    if path.startswith('/api/chat'):
        if 'workspace.chat' not in user['permissions']['modules']:raise auth.AuthError(403,'当前账号无权使用内部聊天')
        return
    if path=='/api/notifications':return
    if path=='/api/feedback':
        if 'system.feedback' not in user['permissions']['modules']:raise auth.AuthError(403,'当前账号无权使用问题反馈')
        return
    if path in ('/api/users','/api/role-permissions'):
        if user['role']=='管理员':return
        raise auth.AuthError(403,'仅管理员可以查看此管理数据')
    if path in ('/api/security-events','/api/audit','/api/audit-integrity','/api/archive-records'):
        if 'system.audit' in user['permissions']['modules']:return
        raise auth.AuthError(403,'当前账号无权查看审计历史')
    if path.startswith('/api/receipt-evidence/'):
        if 'finance.evidence' not in (user['permissions'].get('actions') or []):raise auth.AuthError(403,'当前账号无权查看收款截图')
        return
    if path=='/api/receipt-ocr/settings':
        if user['role']=='管理员':return
        raise auth.AuthError(403,'仅管理员可以查看截图识别设置')
    if path=='/api/finished-goods' and not can_read_data(user['permissions'],'purchase-prices'):raise auth.AuthError(403,'外购成品账款需要采购金额查看权限')
    if path in ('/api/order-corrections','/api/receivables','/api/export','/api/statement-documents','/api/statement-batch-preview','/api/customer-statement','/api/statement-status') or path.startswith('/api/statement-documents/'):
        if not can_read_data(user['permissions'],'sales-prices'):raise auth.AuthError(403,'当前账号无权查看销售金额')
    key='/api/statement-documents' if path.startswith('/api/statement-documents/') else '/api/byproduct-documents' if path.startswith('/api/byproduct-documents/') else path
    known=READ_MODULES.get(key)
    if not known:raise auth.AuthError(404,'未知接口')
    if not (known & set(user['permissions']['modules'])):raise auth.AuthError(403,'当前账号无权查看此数据')

def mutation_permissions(path,body):
    if path=='/api/social-compensation':return ['payroll.write']
    if path=='/api/crate-packaging':return ['master.pricing.write']
    if path=='/api/receipt-ocr/settings':return ['system.parameters']
    if path=='/api/receipt-evidence/recognize':return ['finance.evidence']
    if path.startswith('/api/receipt-evidence/') and path.endswith('/discard'):return ['finance.evidence']
    if path=='/api/inventory-check':return ['inventory.stock']
    if path=='/api/order-corrections':return ['finance.settle','orders.write','weight.write'] if body.get('action')=='shipment' else []
    if path in ('/api/processing','/api/processing/edit','/api/processing/delete'):return ['inventory.process']
    if path=='/api/processing/rules':return ['production.settings']
    if path=='/api/curing':return ['production.curing.write']
    if path in ('/api/chat/send','/api/chat/thread','/api/chat/read','/api/notifications/read','/api/feedback','/api/feedback/reply'):
        return []
    if path=='/api/byproduct-settlement':
        action=body.get('action')
        return ['system.parameters'] if action=='config' else ['byproducts.write'] if action in ('price','settle') else ['__unknown__']
    if path=='/api/fund-accounts':return ['funds.manage']
    if path=='/api/byproduct-statements/issue':return ['finance.statement-issue']
    if path=='/api/gel-tofu/output':return ['production.record']
    if path.startswith('/api/finished-goods/'):
        import finished_goods
        return list(finished_goods.PERMISSIONS.get(path.rsplit('/',1)[-1],('__unknown__',)))
    if path.startswith('/api/trade/'):
        import transport_closure
        if path.rsplit('/',1)[-1] in transport_closure.PERMISSIONS:return [transport_closure.PERMISSIONS[path.rsplit('/',1)[-1]]]
        return [{'shipment':'weight.write','feedback':'weight.write','resolve-feedback':'finance.settle','opening':'crates.write','unit':'master.products.write','trip':'delivery.schedule','void-trip':'delivery.schedule','transport-issue':'costs.write','transport-rates':'costs.write'}.get(path.rsplit('/',1)[-1],'__unknown__')]
    if path=='/api/driver/weights':return ['driver.weights']
    if path=='/api/driver/return-action':return ['driver.returns']
    if path=='/api/driver/returns':return ['driver.returns']
    if path in ('/api/assets/driver-confirm','/api/assets/driver-reject'):return ['crates.confirm']
    if path.startswith('/api/assets/'):return ['assets.write' if path.endswith(('/asset','/delete-asset')) else 'crates.write']
    if path=='/api/factory/parameter-request':
        import production_management
        return [production_management.parameter_permission(body.get('key'))]
    if path=='/api/factory/delete':return ['production.attendance']
    if path=='/api/audit-rollback':return []
    if path.startswith('/api/factory/'):
        import production_management
        kind=path.rsplit('/',1)[-1];permission=production_management.PERMISSIONS.get(kind)
        if kind=='employee':permission='management.staff' if body.get('employee_type')=='management' else 'production.staff'
        return [permission] if permission else None
    if path=='/api/resources/material' and body.get('kind')=='consume':return ['materials.issue'] if body.get('_factory_issue') else ['materials.write']
    if path.startswith('/api/purchasing/'):
        import purchasing
        permission=purchasing.PERMISSIONS.get(path.rsplit('/',1)[-1]);return [permission] if permission else None
    if path=='/api/orders':return ['orders.write']+(['crates.write'] if body.get('accounting_returns') is not None else [])
    if path.startswith('/api/orders/'):
        key=ORDER_ACTIONS.get(path.rsplit('/',1)[-1]);return [key]+(['crates.write'] if body.get('accounting_returns') is not None else []) if key else None
    if path=='/api/batch':
        result=[]
        for item in body.get('operations',[]) if isinstance(body.get('operations'),list) else []:
            if not isinstance(item,dict):continue
            if item.get('action') in ORDER_ACTIONS:result.append(ORDER_ACTIONS[item['action']])
            if item.get('update') is not None:result.append('orders.write')
            if (isinstance(item.get('body'),dict) and item['body'].get('accounting_returns') is not None) or (isinstance(item.get('update'),dict) and item['update'].get('accounting_returns') is not None):result.append('crates.write')
        return result
    if path.startswith('/api/resources/'):
        permission={'item':'materials.catalog','item-delete':'materials.catalog','item-order':'materials.catalog','amortize-close':'materials.value','workshop-count':'materials.issue','material':'materials.write','material-batch':'materials.write','expense':'costs.write','expense-estimate':'costs.write','expense-edit':'costs.write','expense-category':'costs.write','expense-category-delete':'costs.write','expense-counterparty':'costs.write','expense-review':'costs.review','expense-payment':'costs.pay','byproduct':'byproducts.write','receive':'byproducts.receive','period':'costs.close','value':'materials.value','quality':'materials.value','attribute':'materials.value','restore':'materials.void'}.get(path.rsplit('/',1)[-1])
        if path.endswith('/void') or path.endswith('/restore'):permission={'material':'materials.void','expense':'costs.void','byproduct':'byproducts.void'}.get(body.get('ledger'))
        return [permission] if permission else None
    if path=='/api/master':return [master_permission(body.get('kind'))]
    if path=='/api/master/batch-rules':return ['master.pricing.write']
    if path=='/api/master/product-order':return ['master.products.write']
    fixed={'/api/master':'master.write','/api/master/batch-rules':'master.write','/api/master/product-order':'master.write','/api/dispatch':'delivery.schedule','/api/fleet':'delivery.schedule','/api/processing':'inventory.process','/api/stock-close':'inventory.close','/api/returns':'returns.register','/api/order-archive':'system.archive','/api/business-reset':'system.archive','/api/trial-data':'system.archive','/api/operator-users':'system.operator-users','/api/statements/issue':'finance.statement-issue','/api/statements/issue-batch':'finance.statement-issue','/api/backup':'system.backup'}
    if path=='/api/warehouse':return ['inventory.dispatch' if body.get('stage')=='confirm_dispatch' else 'inventory.stock']
    if path=='/api/returns/action':
        key={'account':'returns.account','review':'returns.review','refund':'returns.refund','retract':'returns.retract','dispose':'returns.register','void':'returns.register','reverse-credit':'returns.review','reverse-refund':'returns.refund','void-dispose':'returns.register'}.get(body.get('action'));return [key] if key else None
    return [fixed[path]] if path in fixed else None

def authorize_authenticated(path,body,role):
    import auth
    if path=='/api/business-reset' and role!='管理员':raise auth.AuthError(403,'按日期清理及恢复测试数据仅允许管理员操作')
    if role=='司机' and path not in ('/api/driver/returns','/api/driver/weights','/api/driver/return-action','/api/chat/send','/api/chat/thread','/api/chat/read','/api/notifications/read','/api/feedback','/api/feedback/reply'):raise auth.AuthError(403,'司机账号只能填报本人的回筐或查看内部消息')
    needed=mutation_permissions(path,body)
    if needed is None:raise auth.AuthError(404,'未知操作')
    if any(not role_can(role,key) for key in needed):raise auth.AuthError(403,'当前账号无此操作权限')

def authenticated_catalog(user,configs=None):
    configs={**{r:defaults(r) for r in ['管理员',*ACCOUNT_ROLES]},**(configs or {})}
    result=catalog();result.update(permission_metadata());result.update(data_scopes=[{'id':k,'title':title,'description':desc} for k,title,desc in DATA_SCOPES],role_notes=ROLE_NOTES,version=4,mode='accounts',authenticated=True,read_scope='role',roles=['管理员',*ACCOUNT_ROLES],modules=module_definitions(),actions=action_definitions())
    for m in result['modules']:m['read_roles']=[r for r in result['roles'] if m['id'] in configs[r]['modules']]
    for a in result['actions']:a['roles']=[r for r in result['roles'] if a['id'] in configs[r]['actions']]
    return result

def scope_bootstrap(result,user,configs=None,c=None):
    import purchasing
    goods_inventory=result.pop('finished_goods_inventory',{})
    purchase_data=result.pop('purchasing',{})
    resource_data=result.pop('resources',{})
    factory_data=result.pop('factory',{})
    grants=user.get('permissions',defaults(user['role']))
    result.update(auth_user=user,permissions=grants,access_catalog=authenticated_catalog(user,configs),mode='账号登录 · 可配置岗位授权')
    if 'system.audit' not in grants['modules']:result['audit']=[];result['trial_archives']=[]
    readable=set(grants['modules'])
    if 'finance.accounts' not in readable and not set(grants.get('actions',[])) & {'finance.receipt','byproducts.receive','purchases.pay','costs.pay','payroll.pay','returns.refund'}:result['fund_accounts']=[]
    if not readable & {'asset.crates','master.customers','delivery.weighing','finance.settlement','inventory.operations'}:result['crate_shipments']=[];result['delivery_feedback']=[]
    domains={'orders':{'sales.orders','sales.archive','inventory.operations','inventory.returns','delivery.dispatch','delivery.weighing','finance.settlement','finance.receivables','workspace.analytics','inventory.cost','sales.reports'},'warehouse_plans':{'inventory.operations','delivery.weighing','delivery.dispatch','workspace.analytics','inventory.cost'},'stock_closings':{'inventory.operations','workspace.analytics','inventory.cost'},'processing_batches':{'inventory.operations','workspace.analytics','inventory.cost'},'curing':{'production.curing','workspace.analytics','inventory.cost'},'sales_returns':{'inventory.returns','finance.receivables','workspace.analytics'},'dispatch_plans':{'delivery.dispatch','delivery.weighing','inventory.operations','workspace.analytics'}}
    for key,allowed in domains.items():
        if not readable & allowed:result[key]=[]
    if not (readable-{'workspace.directory'}):
        for key in ('customers','products','rules','delivery_markets','delivery_vehicles','delivery_drivers','operator_users'):result[key]=[]
    if not ({'finance.receivables','finance.settlement','workspace.analytics','sales.reports'} & set(grants['modules'])):
        result=redact_finance(result);result['receipts']=[];result['statement_documents']=[]
    if not can_read_data(grants,'sales-prices'):
        def hide_prices(value):
            if isinstance(value,dict):return {k:hide_prices(v) for k,v in value.items() if k not in ('price','initial_price')}
            if isinstance(value,list):return [hide_prices(v) for v in value]
            return value
        result=redact_finance(hide_prices(result));result['receipts']=[];result['statement_documents']=[]
    if not readable & {'sales.orders','sales.archive','inventory.operations','inventory.returns','delivery.dispatch','delivery.weighing','finance.settlement','finance.receivables','master.pricing','workspace.analytics'}:result['rules']=[]
    result['finished_goods_inventory']=goods_inventory if readable & {'inventory.operations','purchase.orders','purchase.receipts','finance.payables','workspace.analytics'} else {}
    result['purchasing']=purchasing.scope(purchase_data,grants)
    result['resources']=scope_resources(resource_data,grants)
    import production_management
    result['factory']=production_management.scope(factory_data,grants,c)
    if result['factory']:
        result['factory'].update(attendance=[],schedules=[],attendance_deferred=True)
    if 'delivery.analysis' not in readable and not readable & {'delivery.weighing','finance.settlement'}:result['weight_analysis']=[]
    if user['role']=='厂长' or not can_read_data(grants,'sales-prices'):result['receivable_alerts']=[]
    if user['role']=='司机':
        for key in ('customers','products','rules','orders','archived_orders','statement_documents','receipts','audit','delivery_markets','delivery_vehicles','delivery_drivers','dispatch_plans','warehouse_plans','sales_returns','processing_batches','stock_closings','trial_archives','operator_users','weight_analysis','receivable_alerts','crate_shipments','delivery_feedback','crate_types','crate_tare_rules','finished_goods_supply','finished_goods_inventory'):result[key]=[]
        result['product_crate_attributes']={};result['factory']={};result['resources']={};result['purchasing']={}
    return result

def scope_resources(value,grants):
    import copy
    result=copy.deepcopy(value);mods=set(grants['modules'])
    material=bool(mods & {'inventory.materials','workspace.analytics','inventory.cost','purchase.orders','purchase.receipts','production.inventory','production.daily','production.manage','production.issue','production.workshop'})
    finance=bool(mods & {'finance.costs','workspace.analytics'})
    if not material:result['items']=[];result['entries']=[];result['warehouse_stocks']=[];result['voided_entries']=[]
    if not material and 'master.products' not in mods and 'production.settings' not in mods:result['production_configs']=[];result['production_config_index']=[]
    elif not parameter_groups_visible(grants) & {'production','soaking','slurry'}:
        for cfg in result.get('production_configs',[]):
            for system in cfg['systems']:system.pop('soak_kg',None);system.pop('soak_key',None)
            for process in cfg['processes']:
                for key in ('dry_kg','output_qty','kg_key','output_key'):process.pop(key,None)
    if not can_read_data(grants,'material-costs'):
        result=redact_costs(result)
        for r in [*result.get('items',[]),*result.get('warehouse_stocks',[])]:
            for k in ('value_cents','average_price'):r.pop(k,None)
        for r in result.get('entries',[]):
            for k in ('amount_cents','cost_cents','balance_cents','warehouse_balance_cents','target_warehouse_balance_cents','transfer_value_cents','purchase_goods_cents','purchase_charges_cents','purchase_charge_history','valuation_history'):r.pop(k,None)
    if not mods & {'finance.costs','workspace.analytics'}:result['expenses']=[];result['periods']=[]
    expense_view='finance.expense-payables' in mods or bool(mods & {'finance.costs','workspace.analytics'}) and can_read_data(grants,'material-costs')
    for key in ('expense_payables','expense_payments','expense_counterparties','expense_counterparty_kinds'):result[key]=copy.deepcopy(value.get(key,[])) if expense_view else []
    if not mods & {'finance.byproducts','finance.receivables','workspace.analytics'}:result['byproducts']=[]
    return result

def redact_prices(value):
    if isinstance(value,dict):return {k:redact_prices(v) for k,v in value.items() if k not in ('price','initial_price')}
    if isinstance(value,list):return [redact_prices(v) for v in value]
    return value
def redact_costs(value):
    if isinstance(value,dict):return {k:redact_costs(v) for k,v in value.items() if not k.endswith('_cents') and k not in ('average_price','purchase_charge_history','valuation_history')}
    if isinstance(value,list):return [redact_costs(v) for v in value]
    return value

def redact_finance(value):
    hidden={'discount_cents','rounding_cents','finance','settlement','review','review_history','review_return','receipts','return_credits','total_cents','paid_cents','return_credit_cents','amount_cents','bill_qty','agreed_net','settlement_mode'}
    if isinstance(value,dict):return {k:redact_finance(v) for k,v in value.items() if k not in hidden}
    if isinstance(value,list):return [redact_finance(v) for v in value]
    return value
