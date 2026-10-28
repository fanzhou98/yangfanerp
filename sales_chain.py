"""Read-only order fulfillment and current collection reconciliation.

Quantities retain their original product/unit. Return attribution is separate
from credits applied to a bill; this report never changes orders or cash.
"""
from datetime import date
from decimal import Decimal
import resources_costs as rc
import reporting
import order_corrections
import trade
import sales_query

STAGES = {'draft':'待确认实发','weights':'待确认称重','settle':'待算票','recalculate':'待重算',
          'review':'待复核','unpaid':'待收款','partial':'部分收款 / 抵扣','cleared':'已结清','unknown':'状态待核查'}
FULFILLMENT = {'pending':'实发待确认','short':'有少送','excess':'有多送','matched':'订货实发一致'}


def stage(o):
    if o.get('state') == 'reviewed':
        remaining = int(o.get('total_cents',0))-sum(int(o.get(k,0)) for k in ('paid_cents','return_credit_cents','discount_cents','rounding_cents'))
        if remaining < 0: return 'unknown'
        if remaining == 0: return 'cleared'
        return 'partial' if any(o.get(k,0) for k in ('paid_cents','return_credit_cents','discount_cents','rounding_cents')) else 'unpaid'
    if (o.get('review_return') or {}).get('status') == 'pending': return 'recalculate'
    if o.get('state') == 'ready': return 'review'
    if o.get('state') == 'draft': return 'draft'
    if o.get('state') in ('dispatched','negotiation'):
        return 'weights' if o.get('workflow_version') == 1 and not o.get('weight_confirmation') else 'settle'
    return 'unknown'


def lines(o, plan, corrections=()):
    allocations={(a['order_id'],a['product_id']):a for a in (plan or {}).get('allocations',[])}
    result=[]
    for l in o.get('lines',[]):
        actual=Decimal(l.get('actual_qty') or '0')
        allocation=allocations.get((o['id'],l['product_id']))
        corrected=any(r.get('kind')=='shipment' and any(p['product_id']==l['product_id'] and Decimal(p['actual_qty'])==actual
                      for p in (r.get('after') or {}).get('lines',[])) for r in corrections)
        confirmed=(o.get('state') in ('ready','reviewed') or bool(o.get('weight_confirmation'))
                   or l.get('not_shipped') is True or corrected
                   or o.get('state') in ('dispatched','negotiation') and not o.get('dispatch_required')
                   or bool(plan and plan.get('allocation_state','confirmed')=='confirmed' and allocation
                           and Decimal(allocation['qty'])==actual))
        ordered=Decimal(l['ordered_qty']) if l.get('ordered_qty') not in (None,'') else None
        short=max(ordered-actual,Decimal(0)) if confirmed and ordered is not None else None
        excess=max(actual-ordered,Decimal(0)) if confirmed and ordered is not None else None
        result.append({'product_id':l['product_id'],'product_name':l.get('product_name',l['product_id']),
                       'unit':l.get('unit',''),'ordered_qty':rc.ds(ordered) if ordered is not None else None,
                       'actual_qty':rc.ds(actual) if confirmed else None,
                       'recorded_qty':rc.ds(actual),'planned_qty':rc.ds(Decimal(allocation['qty'])) if allocation else None,
                       'allocation_state':plan.get('allocation_state','confirmed') if plan and allocation else '', 'short_qty':rc.ds(short) if short is not None else None,
                       'excess_qty':rc.ds(excess) if excess is not None else None,
                       'confirmed':bool(confirmed),'billing_unit':l.get('billing_unit',''),
                       'bill_qty':l.get('bill_qty') if o.get('state') in ('ready','reviewed') else None,
                       'amount_cents':l.get('amount_cents') if o.get('state') in ('ready','reviewed') else None})
    return result


def report(c,start,end,*,region='',customer_id='',product_id='',query='',status='',view='fulfillment',page=1,page_size=50,all_dates=False):
    start,end=sales_query.resolve(c,start,end,all_dates)
    if view not in ('fulfillment','collection'):raise ValueError('核对视图无效')
    if status and status not in (FULFILLMENT if view=='fulfillment' else STAGES):raise ValueError('核对状态无效')
    page=sales_query.validate_page(page,page_size)
    if len(query)>100 or len(region)>100 or len(customer_id)>100 or len(product_id)>100:raise ValueError('筛选条件过长')
    customers={r['id']:dict(r) for r in c.execute('SELECT * FROM customers')}
    plans={r['business_date']:r for r in rc.rows(c,'warehouse_plans')}
    receipt_map={};return_map={};feedback_map={};correction_map={}
    for r in rc.rows(c,'receipts'):receipt_map.setdefault(r.get('order_id'),[]).append(r)
    for r in rc.rows(c,'sales_returns'):
        if not r.get('voided'):return_map.setdefault(r.get('order_id'),[]).append(r)
    for r in trade.records(c,'feedback'):feedback_map.setdefault(r.get('order_id'),[]).append(r)
    for r in order_corrections.records(c):correction_map.setdefault(r.get('order_id'),[]).append(r)
    rows=[]
    for o in sales_query.orders(c,start,end,region=region,customer_id=customer_id):
        customer=customers.get(o['customer_id'],{})
        current_region=customer.get('region') or '未设置地区'
        order_lines=lines(o,plans.get(o['business_date']),correction_map.get(o['id'],[]))
        if product_id and not any(l['product_id']==product_id for l in order_lines):continue
        searchable=' '.join(str(x) for x in [o['id'],o.get('customer_name',''),o['customer_id'],customer.get('route',''),
                                            *[l['product_name'] for l in order_lines]])
        if query and query.casefold() not in searchable.casefold():continue
        focused=[l for l in order_lines if not product_id or l['product_id']==product_id]
        pending=any(l['short_qty'] is None for l in focused)
        short=any(l['short_qty'] is not None and Decimal(l['short_qty'])>0 for l in focused)
        excess=any(l['excess_qty'] is not None and Decimal(l['excess_qty'])>0 for l in focused)
        fulfillment='pending' if pending else 'short' if short else 'excess' if excess else 'matched'
        current_stage=stage(o)
        # Short and excess can coexist; either filter includes the order once.
        if status and (view=='collection' and current_stage!=status or view=='fulfillment' and
                       not {'pending':pending,'short':short,'excess':excess,'matched':fulfillment=='matched'}[status]):continue
        posted=o.get('state')=='reviewed'
        money={k:int(o.get(k,0)) if posted else None for k in ('total_cents','paid_cents','return_credit_cents','discount_cents','rounding_cents')}
        remaining=money['total_cents']-sum(money[k] for k in ('paid_cents','return_credit_cents','discount_cents','rounding_cents')) if posted else None
        receipts=[{k:r.get(k) for k in ('id','received_date','amount_cents','discount_cents','rounding_cents','method','note')} for r in receipt_map.get(o['id'],[])]
        returns=[{'id':r['id'],'received_date':r['received_date'],'product_name':r.get('product_name',''),
                  'qty':r.get('qty'),'unit':r.get('unit',''),'state':(r.get('finance') or {}).get('state','unaccounted'),
                  'amount_cents':(r.get('finance') or {}).get('amount_cents')} for r in return_map.get(o['id'],[])]
        issues=[]
        if posted:
            for key in ('paid_cents','discount_cents','rounding_cents'):
                receipt_key='amount_cents' if key=='paid_cents' else key
                if sum(int(r.get(receipt_key) or 0) for r in receipts)!=money[key]:issues.append('收款流水与账单累计不一致，请核查')
            if remaining<0:issues.append('账款减少额超过已复核金额，请核查')
        rows.append({'order_id':o['id'],'order_version':o.get('version'),'business_date':o['business_date'],
                     'customer_id':o['customer_id'],'customer_name':o.get('customer_name',customer.get('name','')),
                     'region':current_region,'market':customer.get('route',''),'stage':current_stage,'stage_label':STAGES[current_stage],
                     'fulfillment':fulfillment,'fulfillment_label':'有少送及多送' if short and excess else FULFILLMENT[fulfillment],
                     'has_short':short,'has_excess':excess,'lines':order_lines,'focused_lines':focused,
                     **money,'outstanding_cents':remaining,
                     'pending_review_cents':int(o.get('total_cents',0)) if o.get('state')=='ready' else None,
                     'attributed_return_cents':sum(r['amount_cents'] or 0 for r in returns if r['state']=='posted'),
                     'receipts':receipts,'returns':returns,
                     'feedback':[{k:r.get(k) for k in ('id','feedback_date','product_name','unit','actual_qty','received_qty','difference_qty','state','note','resolution','source_order_version')} for r in feedback_map.get(o['id'],[])],
                     'corrections':[{'id':r['id'],'kind':r.get('kind'),'at':r.get('at'),'reason':r.get('reason'),
                                     'quantity_changes':r.get('quantity_changes',[])} for r in correction_map.get(o['id'],[])],
                     'issues':list(dict.fromkeys(issues))})
    rows.sort(key=lambda r:(r['business_date'],r['order_id']),reverse=True)
    quantities={}
    for r in rows:
        for l in r['focused_lines']:
            key=(l['product_id'],l['unit'])
            q=quantities.setdefault(key,{'product_id':l['product_id'],'product_name':l['product_name'],'unit':l['unit'],
                                         'ordered_qty':Decimal(0),'known_actual_qty':Decimal(0),'short_qty':Decimal(0),'excess_qty':Decimal(0),'pending_lines':0,'missing_ordered_lines':0})
            if l['ordered_qty'] is not None:q['ordered_qty']+=Decimal(l['ordered_qty'])
            else:q['missing_ordered_lines']+=1
            if l['actual_qty'] is not None:q['known_actual_qty']+=Decimal(l['actual_qty'])
            if l['short_qty'] is None:q['pending_lines']+=1
            else:q['short_qty']+=Decimal(l['short_qty']);q['excess_qty']+=Decimal(l['excess_qty'])
    summary={'orders':len(rows),'stage_counts':{key:sum(r['stage']==key for r in rows) for key in STAGES},
             'short_orders':sum(r['has_short'] for r in rows),'excess_orders':sum(r['has_excess'] for r in rows),
             'pending_orders':sum(r['fulfillment']=='pending' for r in rows),'issue_orders':sum(bool(r['issues']) for r in rows)}
    for key in ('total_cents','paid_cents','return_credit_cents','discount_cents','rounding_cents','outstanding_cents','attributed_return_cents'):
        summary[key]=sum(r[key] or 0 for r in rows)
    summary['pending_review_cents']=sum(r['pending_review_cents'] or 0 for r in rows)
    page_rows,page,pages=sales_query.page(rows,page,page_size)
    return {**reporting.context('订货实发与销售回款核对',start,end,'原单 / 实发 / 复核 / 收款 / 退货 / 反馈 / 更正',
                '按原单业务日期选择，显示读取时的当前办理和账款状态；不是历史时点余额。产品筛选只限定订单及数量，金额仍为整单，不能视为该产品收入。'),
            'view':view,'summary':summary,'quantities':[{k:rc.ds(v) if isinstance(v,Decimal) else v for k,v in q.items()} for q in quantities.values()],
            'rows':page_rows,'page':page,'pages':pages,'page_size':page_size,'total':len(rows),
            'filters':{'region':region,'customer_id':customer_id,'product_id':product_id,'query':query,'status':status,'all_dates':all_dates},
            'stage_labels':STAGES,'fulfillment_labels':FULFILLMENT,
            'notes':['未确认实发不计算少送；少送和多送逐行分别统计，不互相抵消。',
                     '原单退货核定额仅供溯源；账款公式只扣实际抵到本单的退货抵扣，避免重复扣减。',
                     '已复核金额＝实际收款＋本单退货抵扣＋折扣＋抹零＋当前未收。待复核金额不计应收。',
                     '期初应收和历史时点重建待R04；本视图不自动更正实发、扣款或认定赔偿。']}
