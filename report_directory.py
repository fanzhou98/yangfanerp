"""Permission-scoped report directory; read-only metadata, never report amounts.
Charts are inspected from the same report contracts used by their pages.
"""
import calendar
from pathlib import Path
import erp_access as access
import resources_costs as rc
import reporting

VERSION='report-directory-v5'
# Topic, question, responsible posts, (page, tab, chart source) entries.
TOPICS=[
 ('overview','经营总览','今天或本月哪里需要核对？','老板 / 会计', [('analytics','overview','management'),('analytics','profit','profit'),('dashboard','','owner')]),
 ('sales','销售与回款','发了什么、退了什么、谁还没有收回？','会计 / 出纳', [('sales-daily','','sales'),('sales-daily','fulfillment','sales-chain'),('sales-daily','collection','sales-chain'),('ledger','',''),('returns','','')]),
 ('production','生产与耗用','出品变化是否有可靠依据？','厂长 / 库管', [('production-report','','production'),('production','',''),('factory','','')]),
 ('purchase','采购与供应','哪些货没到、实际成本怎样？','采购负责人 / 会计', [('purchases','',''),('purchase-receipts','',''),('payables','','')]),
 ('stock','库存与盘点','库存及批次质量是否有据可查？','库管 / 采购负责人', [('allocation','reconciliation','inventory-check'),('soy-inventory','','soy'),('materials','','')]),
 ('funds','资金与应付','实际收付与待付款如何核对？','出纳 / 会计', [('ledger','',''),('payables','',''),('expense-payables','',''),('fund-accounts','','')]),
 ('cost','成本与利润','成本是否完整、产品贡献如何？','会计 / 老板', [('analytics','overview','management'),('analytics','profit','profit'),('expenses','','expense')]),
 ('delivery','配送与周转筐','哪些配送差异未解决、哪些筐未回？','物流负责人 / 库管', [('dispatch','',''),('crates','',''),('assets','','')]),
 ('people','人员与工资','排班、考勤、工资怎样核对？','厂长 / 会计 / 出纳', [('attendance','',''),('management-attendance','',''),('employees','',''),('management-employees','',''),('payroll','','')]),
]

def chart_status(charts,gaps=()):
    states=[]
    for ch in charts:
        points=ch.get('points',[])
        valid=[p for p in points if p.get('value') is not None or p.get('now') is not None or p.get('total') is not None]
        if ch.get('kind')=='dot':valid=[p for p in points if p.get('now') is not None and p.get('prev') is not None]
        if ch.get('kind')=='trend':
            # Calendar slots with no reviewed data never count as samples.
            valid=[p for p in valid if p.get('n',0)>0]
        if not valid:level='C';status='缺可用数据'
        elif ch.get('kind')=='trend' and len(valid)<3:level='B';status='稀疏数据，显示数值条'
        else:level='A';status='有可展示数据'
        states.append({'title':ch['title'],'kind':ch['kind'],'level':level,'status':status,'sample_count':len(valid)})
    count=sum(r['level']!='C' for r in states)
    if gaps:level='C';status='依据待核对'
    elif not states:level='B';status='表为主，无图'
    elif any(r['level']=='C' for r in states):level='C';status='部分图缺可用数据'
    elif any(r['level']=='B' for r in states):level='B';status='稀疏数据'
    else:level='A';status='有可展示数据'
    return {'level':level,'status':status,'chart_count':count,'chart_slots':len(states),'charts':states,'gaps':[{'field':r['field'],'owner':r.get('owner','负责岗位'),'target':r.get('target','')} for r in gaps]}

def catalog(c,day,grants,role):
    rc.day(day);month=day[:7];start=month+'-01';end=month+'-'+str(calendar.monthrange(int(month[:4]),int(month[5:7]))[1])
    mods=set(grants.get('modules',[]));defs={r['page']:r for r in access.module_definitions()};cache={}
    full=all(access.can_read_data(grants,k) for k in ('sales-prices','purchase-prices','material-costs','supplier-terms'))
    def allowed(page,tab):
        if page=='allocation':return bool(mods & {'inventory.operations','inventory.reconciliation'})
        if page=='dashboard':return role=='老板' and 'workspace.analytics' in mods and full
        if page=='analytics' and tab=='profit':return bool(mods & {'workspace.analytics','workspace.product-profit'}) and role in ('管理员','老板','会计','出纳') and all(access.can_read_data(grants,k) for k in ('sales-prices','purchase-prices','material-costs'))
        if page=='analytics':return 'workspace.analytics' in mods and full
        if page=='sales-daily':return 'sales.reports' in mods and access.can_read_data(grants,'sales-prices')
        if page=='expenses':return 'finance.costs' in mods and access.can_read_data(grants,'material-costs')
        return page in defs and defs[page]['id'] in mods
    def readiness(source):
        if source in cache:return cache[source]
        if source=='management':
            r=reporting.management_month(c,month);v=chart_status([r['bridge']],r['gaps'])
        elif source=='sales':
            r=reporting.sales(c,start,end);v=chart_status(r['charts'],r['gaps'])
        elif source=='sales-chain':
            import sales_chain
            r=sales_chain.report(c,start,end)
            v=chart_status([])
            v.update(level='B' if r['summary']['orders'] else 'C',status='原单全程只读核对；历史时点余额待建' if r['summary']['orders'] else '所选范围无订单')
        elif source=='inventory-check':
            import inventory_reconciliation
            r=inventory_reconciliation.report(c,day)
            relevant=[p for p in r['products'] if p['pre_qty']!='' or p['post_qty']!='' or any(float(o['actual_qty'])>0 for o in p['orders'])]
            gaps=[{'field':p['product_name']+'：'+p['status'],'owner':'库管 / 会计','target':'allocation'} for p in relevant if p['status']!='已对平']
            v=chart_status([],gaps)
            v.update(level='A' if relevant and not gaps else 'C',status='已对平，可核对原单' if relevant and not gaps else '实盘 / 实发差异待核对' if relevant else '未登记实盘依据')
        elif source=='production':
            r=reporting.production_day(c,day);v=chart_status(r['charts'],r['gaps'])
        elif source=='soy':
            r=reporting.soy_stock(c,day);v=chart_status(r['charts'])
        elif source=='expense':
            r=reporting.expense_summary(c,month);v=chart_status(r['charts'])
            if not any(p['value'] is not None for p in r['categories']):v.update(level='C',status='本月无费用登记')
        elif source=='profit':
            import product_profit
            r=product_profit.month(c,month);gaps=list(r['gaps'])
            for p in r['rows']:
                gaps.extend({'field':p['product_name']+'：'+reason,'owner':'会计 / 厂长'} for reason in p['missing_data'])
            v=chart_status([],gaps)
            if not r['rows']:v.update(level='C',status='本月无可核对产品记录')
            elif not gaps:v.update(level='A',status='有测算依据，非净利润')
        elif source=='owner':
            import owner_analysis
            r=owner_analysis.report(c,day);v=chart_status([r['cost']['bridge']],r['cost']['missing_data'])
        else:v={'level':'—','status':'作业台账入口；闭环就绪度尚未接入','chart_count':0,'chart_slots':0,'charts':[],'gaps':[]}
        cache[source]=v;return v
    topics=[]
    for key,title,question,owner,entries in TOPICS:
        pages=[]
        for page,tab,source in entries:
            if not allowed(page,tab):continue
            d=defs.get(page,{})
            label='订货与实发核对' if tab=='fulfillment' else '算票与收款进度' if tab=='collection' else '库存与发货核对' if tab=='reconciliation' else '月度产品经营测算' if tab=='profit' else '经营概览（月）' if page=='analytics' else '老板经营日报' if page=='dashboard' else d.get('title',page)
            # Accounting-only users retain their existing standalone permission.
            target='product-profit' if tab=='profit' and 'workspace.analytics' not in mods else page
            state=readiness(source)
            safe_gaps=[{**g,'target':g['target'] if any(m['page']==g['target'] and m['id'] in mods for m in access.module_definitions()) else ''} for g in state['gaps']]
            pages.append({'id':page+':'+tab,'page':target,'page_title':'经营看板' if target=='analytics' else label,'tab':tab if target==page else '', 'section':'product-estimate' if target=='analytics' and tab=='profit' else '', 'tab_title':'订货与实发核对' if tab=='fulfillment' else '算票与收款进度' if tab=='collection' else '' if target=='analytics' else '库存与发货核对' if target=='allocation' and tab=='reconciliation' else '', 'title':label,'owner':owner,'scope':day if source in ('production','soy','owner','inventory-check') else month,**state,'gaps':safe_gaps})
        topics.append({'id':key,'title':title,'question':question,'owner':owner,'pages':pages})
    import metric_dictionary
    pages={p['page'] for t in topics for p in t['pages']}|{m['page'] for m in access.module_definitions() if m['id'] in mods and allowed(m['page'],'')}
    metrics=metric_dictionary.catalog(pages)
    return {'metrics':metrics,**reporting.context('报表地图',start,end,'服务端报表目录 / 同源报表契约','图数为所选范围内具备数据的图；C级图只显示缺口，表为主的作业入口不代表完整闭环已建。A表示有展示数据，不表示已审定或可认定净利润。'), 'directory_version':VERSION,'app_version':(Path(__file__).parent/'VERSION').read_text().strip(),'business_date':day,'topics':topics}
