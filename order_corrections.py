"""Audited shipment corrections and statement invalidation; never erase cash or physical counts."""
import hashlib,json,secrets
from decimal import Decimal
import erp_access as access
import resources_costs as rc
import inventory


def records(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='order_corrections' AND type='table'").fetchone():return []
    return rc.rows(c,'order_corrections')


def void_info(c,doc_id):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='statement_voids' AND type='table'").fetchone():return None
    row=c.execute('SELECT payload FROM statement_voids WHERE document_id=?',(doc_id,)).fetchone();return json.loads(row[0]) if row else None


def affected_documents(c,order):
    result=[]
    for row in c.execute('SELECT id,customer_id,business_date,payload FROM statement_documents'):
        value=json.loads(row['payload']);refs={o['id'] for key in ('current','history','historical_pending') for o in value.get(key,[])}
        if (order['id'] in refs or row['customer_id']==order['customer_id'] and row['business_date']>=order['business_date']) and not void_info(c,row['id']):result.append(row['id'])
    return result


def invalidate(c,order,reason,role,now,audit):
    ids=affected_documents(c,order)
    for key in ids:
        value={'document_id':key,'source_order_id':order['id'],'source_order_version':order['version'],'voided_at':now(),'voided_by':role,'reason':reason}
        c.execute('INSERT INTO statement_voids VALUES(?,?)',(key,rc.dump(value)));audit(c,role,'作废受更正影响的客户结算单',key,None,value)
    return ids


def effective_plan(c,plan,*,_amendments=None):
    if not plan:return plan
    amendments=[r for r in (records(c) if _amendments is None else _amendments) if r['kind']=='shipment' and r['business_date']==plan['business_date']]
    if not amendments:return plan
    value=json.loads(rc.dump(plan));allocation={(a['order_id'],a['product_id']):a for a in value.get('allocations',[])}
    for correction in amendments:
        for l in correction['after']['lines']:
            key=(correction['order_id'],l['product_id']);allocation[key]={'order_id':key[0],'product_id':key[1],'qty':l['actual_qty'],'ordered_qty':l['ordered_qty'],'mode':'manual','correction_id':correction['id']}
    value['allocations']=list(allocation.values());value['shipment_correction_ids']=[r['id'] for r in amendments];return value


def restated_closing(c,record):
    if not record or record['state']!='closed':return record
    amendments=[r for r in records(c) if r.get('stock_anchor_date')==record['business_date'] and r['kind']=='shipment']
    if not amendments:return record
    value=json.loads(rc.dump(record));delta={}
    for a in amendments:
        for l in a['quantity_changes']:delta[l['product_id']]=delta.get(l['product_id'],Decimal(0))+Decimal(l['delta_qty'])
    for p in value['products']:
        diff=delta.get(p['product_id'],Decimal(0))
        if diff:
            p['original_book_qty']=p['book_qty'];p['original_variance_qty']=p['variance_qty'];p['book_qty']=rc.ds(Decimal(p['book_qty'])-diff);p['variance_qty']=rc.ds(Decimal(p['counted_qty'])-Decimal(p['book_qty']));p['shipped_qty']=rc.ds(Decimal(p['shipped_qty'])+diff);p['shipment_correction_qty']=rc.ds(diff)
    value['shipment_corrections']=[{'id':r['id'],'order_id':r['order_id'],'reason':r['reason'],'at':r['at'],'quantity_changes':r['quantity_changes']} for r in amendments]
    value['correction_basis']='已实盘数量与翌日结转保持原确认值；仅重述实发、账面余量与盘点差异，原日结快照留存'
    return value


def preview(c,order):
    closed=inventory.closed(c,order['business_date']);locked=any(r['state']=='closed' and r['business_date']>=order['business_date'] for r in inventory.rows(c,'stock_closings'))
    return {'order':order,'document_ids':affected_documents(c,order),'closed':bool(closed),'locked':locked,'closing':closed,'inventory_revision':inventory.revision(c),'has_payments':bool(order.get('paid_cents') or order.get('return_credit_cents') or order.get('discount_cents') or order.get('rounding_cents')),'history':[r for r in records(c) if r['order_id']==order['id']],'inventory_basis':'昨日已实盘并结转：更正只重述当日账面差异，不再冲增或冲减今天库存；后续真实补送须另建发货单' if closed else '未日结：更正实发直接重新计算当日库存，并校验可供数量'}


def save(c,b,role,now,audit,normalize,save_order,get_order):
    kind=b.get('action')
    if kind not in ('reopen','shipment'):raise ValueError('请选择退回重算或实发更正')
    if kind=='shipment':
        for permission in ('finance.settle','orders.write','weight.write'):access.require_role(role,permission)
    elif not(access.role_can(role,'finance.review-return') or access.role_can(role,'finance.settle')):raise ValueError('当前账号无退回重算权限')
    key=rc.text(b.get('request_key'),'更正提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('request_key','_data_epoch')}).encode()).hexdigest()
    prior=c.execute('SELECT payload FROM order_correction_submissions WHERE request_key=?',(key,)).fetchone()
    if prior:
        result=json.loads(prior[0])
        if result['fingerprint']!=finger:raise ValueError('更正提交编号已使用，请重新打开核对')
        return result
    old=get_order(c,b.get('order_id'))
    if type(b.get('version')) is not int or b['version']!=old['version']:raise ValueError('订单已被修改，请刷新后重新核对')
    if old['state']=='reviewed' and not access.role_can(role,'finance.review-return'):raise ValueError('已复核入账订单须先由出纳撤销复核、退回会计重算')
    if old.get('paid_cents') or old.get('return_credit_cents') or old.get('discount_cents') or old.get('rounding_cents'):raise ValueError('该订单已有真实收款、抵扣或减免，不能直接撤销；请保留收款流水，通过退货扣款或补送单核对差额')
    if any(r.get('order_id')==old['id'] and not r.get('voided') for r in inventory.rows(c,'sales_returns')):raise ValueError('该订单已有退货扣款关联，请先按退货流程核对，不能直接更正原销售')
    rc.open_period(c,old['business_date'])
    if any(r['state']=='closed' and r['month']>=old['business_date'][:7] for r in rc.rows(c,'resource_periods')):raise ValueError('所属或后续成本月份已结账，请先重开相关月份再更正')
    reason=rc.text(b.get('reason'),'更正原因及核对依据',500)
    if b.get('evidence_checked') is not True:raise ValueError('请核对客户反馈、原发货和账款后勾选确认')
    if kind=='reopen':
        if old['state'] not in ('ready','reviewed'):raise ValueError('仅已算票或已复核的订单需要退回重算')
        value=json.loads(rc.dump(old));value.update(version=old['version']+1,updated_at=now())
    else:
        if old['state']=='reviewed':raise ValueError('请先撤销复核退回会计，再更正实发')
        inventory.expect_revision(c,b)
        body={**old,'lines':b.get('lines')}
        value=normalize(c,body,old)
        if len(value['lines'])!=len(old['lines']) or {l['product_id'] for l in value['lines']}!={l['product_id'] for l in old['lines']}:raise ValueError('实发更正不能添加或移除原单产品，请使用补送单')
    changes=[]
    for l in value['lines']:
        original=next(x for x in old['lines'] if x['product_id']==l['product_id']);diff=Decimal(l['actual_qty'])-Decimal(original['actual_qty'])
        if kind=='shipment' and l['price']!=original['price']:raise ValueError('实发更正不修改单价，请退回算票表另行核对价格')
        if diff:changes.append({'product_id':l['product_id'],'product_name':l['product_name'],'before_qty':original['actual_qty'],'after_qty':l['actual_qty'],'delta_qty':rc.ds(diff)})
    anchor=None
    if changes:
        locked=any(r['state']=='closed' and r['business_date']>=old['business_date'] for r in inventory.rows(c,'stock_closings'))
        if locked:
            anchor=inventory.closed(c,old['business_date'])
            if not anchor:raise ValueError('原发货日未单独日结但已进入后续日结范围，请先核查跨日盘点差异，不能直接更改历史实发')
            if b.get('physical_count_confirmed') is not True:raise ValueError('请确认日终实盘已核实、原实盘及翌日结转保持不变')
            for x in changes:
                p=next((p for p in anchor['products'] if p['product_id']==x['product_id']),None)
                if not p or Decimal(p['book_qty'])-Decimal(x['delta_qty'])<0:raise ValueError(x['product_name']+'更正后历史账面库存不足，请先核查漏记生产或库存')
    entry_id='OC-'+secrets.token_hex(8)
    entry={'id':entry_id,'kind':kind,'order_id':old['id'],'business_date':old['business_date'],'at':now(),'role':role,'reason':reason,'before':old,'after':None,'stock_anchor_date':anchor['business_date'] if anchor else None,'quantity_changes':changes}
    history={'id':entry_id,'status':'pending','at':now(),'role':role,'reason':reason,'source_version':old['version'],'total_cents':old['total_cents'],'settlement':old.get('settlement'),'lines':old['lines']}
    value.setdefault('review_history',[]).append(history);value['review_return']={k:v for k,v in history.items() if k not in ('lines','settlement')}
    value.update(state='dispatched' if any(Decimal(l['actual_qty'])>0 for l in value['lines']) else 'draft',settlement={'reason':'更正退回重算：'+reason},review=None,total_cents=0,weight_confirmation=None,correction_ids=[*old.get('correction_ids',[]),entry_id],updated_at=now())
    for l in value['lines']:l.update(bill_qty=None,amount_cents=0,agreed_net=None);l.pop('settlement_mode',None);l.pop('settlement_tares',None)
    entry['after']=value;entry['voided_document_ids']=invalidate(c,old,reason,role,now,audit)
    c.execute('INSERT INTO order_corrections VALUES(?,?)',(entry_id,rc.dump(entry)));save_order(c,value)
    if changes and not anchor:inventory.validate_book(c,old['business_date'],True)
    inventory.bump(c);audit(c,role,'更正历史实发并退回重算' if kind=='shipment' else '撤销算票或复核并退回重算',old['id'],old,entry)
    result={'order':value,'correction_id':entry_id,'voided_document_ids':entry['voided_document_ids'],'stock_anchor_date':entry['stock_anchor_date'],'quantity_changes':changes,'fingerprint':finger}
    c.execute('INSERT INTO order_correction_submissions VALUES(?,?)',(key,rc.dump(result)));return result
