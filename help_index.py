"""Read-only help index behind the workspace search dialog.

Metadata only: the module catalogue, the report-directory topics and the metric
dictionary, each filtered to the pages this account may open. No database
access, no amounts, no business writes. The dialog ranks these rows in the
browser; this module only supplies the words people actually type.
"""
import erp_access as access
import metric_dictionary
import report_directory

VERSION='help-index-v1'

# 口头说法 → 模块 id。标题与业务说明本身已参与匹配，这里只补口语、简称与岗位
# 用语，让「算票」「过磅」「回筐」这类叫法也能落到具体页面。
MODULE_WORDS={
 'sales.orders':['订货','下单','订单','订货单','开单','打单','客户要货'],
 'sales.archive':['查单','找单据','归档','原单查询'],
 'sales.reports':['销售报表','销量','订货实发核对','收款进度','客户销量'],
 'delivery.dispatch':['排班','派车','车辆','趟次','司机安排','外包趟'],
 'delivery.weighing':['称重','过磅','复称','司机称','实发核对'],
 'delivery.providers':['配送方','外包','服务商','每趟运费'],
 'delivery.driver':['我的配送','司机','回筐','今天跑哪'],
 'inventory.operations':['盘点','库存写入','分配','结转','日结','转加工','隔离'],
 'inventory.returns':['退货','扣款','冲红','退货登记'],
 'inventory.materials':['大豆','辅料','入库','领用','耗材','包装','原辅料'],
 'inventory.cost':['生产月报','月度产量','月成本'],
 'production.manage':['上豆','泡豆','浆缸','磨豆','今天上豆'],
 'production.daily':['生产日报','出品率','用豆','日报'],
 'production.issue':['领料','领辅料','分摊'],
 'production.workshop':['车间余料','月末盘点','余料'],
 'production.curing':['熏制','白干','熏干'],
 'production.inventory':['黄豆库存','批次','FIFO','库存分析','原辅料预警'],
 'production.settings':['泡豆桶','浆缸设置','生产参数'],
 'production.staff':['工人','生产人员','班组'],
 'production.attendance':['考勤','出勤','请假','记工','报工'],
 'management.staff':['管理人员','管理层档案'],
 'management.attendance':['管理考勤','办公室考勤'],
 'finance.payroll':['工资','员工工资','应发','实发工资','社保'],
 'finance.costs':['费用','成本','水电','人工费','期间费用'],
 'finance.expense-payables':['报账','报销','费用付款','凭据'],
 'finance.byproducts':['豆渣','豆渣收入'],
 'finance.transport-settlement':['运费结算','配送费','运输月结'],
 'finance.settlement':['算票','算票复核','复核','协商','结算单'],
 'finance.accounts':['银行','现金','账户','流水','余额','账户余额'],
 'finance.receivables':['应收','收款','欠款','回款','核销','到账'],
 'finance.payables':['应付','付款','账期','欠供应商'],
 'master.customers':['客户','地区','市场','配送方式','客户档案'],
 'master.products':['产品','规格','单位','产品资料'],
 'master.pricing':['价格','皮重','专属价','客户价格'],
 'master.suppliers':['供应商','供货','联系方式'],
 'purchase.orders':['采购','外购','到货','余量','采购订单'],
 'purchase.receipts':['验收','采购入库','分批入库'],
 'workspace.dashboard':['首页','待办','今天做什么','工作台'],
 'workspace.analytics':['日报月报','日报','月报','毛利','趋势','经营概况'],
 'workspace.product-profit':['产品测算','单品利润','产品经营'],
 'workspace.report-map':['报表地图','有哪些报表','报表在哪'],
 'workspace.directory':['功能总览','谁负责','岗位职责','流程'],
 'asset.register':['资产','设备','台账'],
 'asset.crates':['筐','周转筐','空筐','回筐','装货筐'],
 'system.audit':['备份','审计','日志','恢复','操作记录'],
 'system.feedback':['反馈','建议','报错','提问题'],
 'system.access':['权限','授权','权限矩阵'],
 'system.users':['账号','用户','密码','停用'],
 'system.parameters':['参数','参数修改'],
}

# 口头说法 → 指标 id（metric_dictionary.DEFINITIONS）
METRIC_WORDS={
 'wage_basic':['工资','基本工资','应发','考勤工资','怎么算工资'],
 'social_company_compensation':['社保补偿','公司社保'],
 'social_personal_compensation':['个人社保','社保个人'],
 'wage_paid':['实发','发工资','实际发放'],
 'ordered_qty':['订货量','订了多少','订单数量'],
 'shipped_qty':['实发','实发量','送了多少','发货数量'],
 'unfulfilled_qty':['少送','没送够','未满足','欠客户'],
 'settled_kg':['结算公斤','结算量','算票公斤','公斤'],
 'settlement_yield':['出品率','出成率','出豆腐','得率','单框重量','均重','出多少豆腐'],
 'monthly_yield':['月出品率','月度出品率'],
 'processing_yield':['转加工出品率','转加工出成'],
 'inferred_output':['倒推产量','库存倒推'],
 'gross_sales':['发货金额','销售额','发货额','卖了多少'],
 'net_sales':['净额','净销售','扣退货','实际收入'],
 'receivable_current':['欠款','应收','没给钱','未收','回款','收款余额'],
 'actual_cash':['实际收支','现金余额','账户余额','银行对不上'],
 'allocation_weight':['分摊权重','费用分摊','怎么分摊'],
 'allocation_balance':['分摊勾稽','待分摊'],
 'operating_difference':['毛利','净利润','赚了多少','经营差','盈亏'],
 'inventory_variance':['盘差','短库','盘点差','账实不符'],
 'delivery_difference':['收货差异','客户说少','反馈少送'],
 'transport_payable':['运费','配送费','趟费'],
 'delivery_claim':['赔偿','赔款','扣司机'],
 'net_profit':['利润表','月利润','正式利润'],
}


def _visible_modules(modules):
    defs=[m for m in access.module_definitions() if m['id'] in modules]
    return defs


def _module_row(m):
    return {'id':m['id'],'page':m['page'],'view':m.get('view') or '','group':m['group'],
            'title':m['title'],'description':m['description'],
            'keywords':MODULE_WORDS.get(m['id'],[])}


def index(user):
    """帮助索引：按当前账号能打开的页面过滤。user 为空时按空的权限处理。"""
    user=user if isinstance(user,dict) else {}
    role=user.get('role') or ''
    grants=user.get('permissions') or {}
    modules=set(grants.get('modules') or [])
    visible=_visible_modules(modules)
    pages={m['page']:m for m in visible}
    rows=[_module_row(m) for m in visible]

    metrics=[]
    for item in metric_dictionary.catalog(set(pages))['items']:
        item=dict(item)
        item['keywords']=METRIC_WORDS.get(item['id'],[])
        item['where']=[{'page':m['page'],'view':m.get('view') or '','title':m['title']}
                       for m in visible if m['page']==item['page']]
        metrics.append(item)

    topics=[]
    for key,title,question,owner,targets in report_directory.TOPICS:
        where=[]
        seen=set()
        for page,tab,chart in targets:
            m=pages.get(page)
            if not m or page in seen:
                continue
            seen.add(page)
            where.append({'page':page,'view':m.get('view') or '','title':m['title']})
        if not where:
            continue
        topics.append({'id':key,'title':title,'question':question,'owner':owner,
                       'where':where,'keywords':[title,question,owner]})

    return {'version':VERSION,'role':role,
            'metric_version':metric_dictionary.VERSION,
            'directory_version':report_directory.VERSION,
            'modules':rows,'metrics':metrics,'topics':topics}
