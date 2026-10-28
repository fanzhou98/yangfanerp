"""Administrator-only, date-scoped test-data archive with guarded restoration.

Master records never enter the deletion allowlist. Caller owns the transaction.
"""
import hashlib,json,secrets
import resources_costs as rc
import inventory,order_corrections

LABELS={
 'orders':'销售订单（含称重、算票）','receipts':'销售收款','archived_orders':'重复订单归档',
 'warehouse_plans':'库存与发货分配','dispatch_plans':'配送排车','stock_closings':'库存日结',
 'sales_returns':'退货及处置','processing_batches':'厂内转加工',
 'factory_runs':'生产作业','factory_scrap':'生产报损','factory_daily':'每日用豆与用浆',
 'factory_attendance':'当天考勤','factory_schedules':'当天排班','gel_daily_outputs':'内脂实际产出',
 'material_entries':'原辅料库存流水','indirect_expenses':'费用记录','expense_estimates':'成本暂估','byproduct_sales':'豆渣销售',
 'expense_reviews':'费用核对','expense_payments':'费用付款',
 'purchase_orders':'采购订单','purchase_receipts':'采购验收','purchase_payments':'采购付款','purchase_charges':'采购附加费用',
 'asset_records':'框子盘点与回框流水','trade_records':'配送及运输明细','finished_goods_records':'外购成品业务',
 'driver_return_requests':'司机回框填报','order_corrections':'实发更正记录',
 'asset_submissions':'框子提交记录','trade_submissions':'配送提交记录','driver_weight_submissions':'司机称重提交',
 'driver_return_submissions':'司机回框提交','finished_goods_submissions':'外购成品提交','order_correction_submissions':'更正提交记录',
 'fund_accounts':'资金账户','fund_assignments':'资金账户关联','fund_transfers':'账户内部转账','byproduct_statements':'豆渣结算单','statement_documents':'客户结算单','statement_voids':'结算单作废标记','payroll_records':'工资业务'}
PROTECTED=('fund_accounts','customers','products','rules','supplier_categories','suppliers','material_items','delivery_markets','delivery_vehicles','delivery_drivers','factory_employees','factory_groups','factory_settings','customer_crate_tares','production_config_versions','auth_users','role_permissions')
DAY_TABLES=set(LABELS)-{'fund_accounts','fund_assignments','fund_transfers','byproduct_statements','statement_documents','statement_voids','payroll_records'}
ORDER_TABLES={'orders','receipts','archived_orders','sales_returns','order_corrections','driver_return_requests'}
SUBMISSIONS={'asset_submissions','trade_submissions','driver_weight_submissions','driver_return_submissions','finished_goods_submissions','order_correction_submissions'}


def require_admin(role):
    if role!='管理员':raise ValueError('按日期清理及恢复测试数据仅允许管理员操作')


def snapshot(c):
    existing={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {t:[dict(r) for r in c.execute('SELECT * FROM '+t)] for t in LABELS if t in existing}


def digest(value):return hashlib.sha256(rc.dump(value).encode()).hexdigest()


def stable_snapshot(rows):return {t:sorted(items,key=rc.dump) for t,items in sorted(rows.items())}


def fingerprint(rows):
    # Renaming a frame or changing a product mapping after cleanup is a retained
    # master-data edit, not new business that restoration would overwrite.
    filtered={}
    for t,items in rows.items():
        filtered[t]=[r for r in items if not (t in ('asset_records','asset_submissions') and value(r).get('kind') in ('asset','mapping')) and not (t in ('trade_records','trade_submissions') and value(r).get('kind') in ('unit',)) and not (t=='payroll_records' and value(r).get('kind') in ('profile','rate'))]
    return digest(stable_snapshot(filtered))


def value(row):return json.loads(row['payload']) if 'payload' in row else row


def contains(obj,ids):
    if isinstance(obj,str):return obj in ids
    if isinstance(obj,list):return any(contains(x,ids) for x in obj)
    if isinstance(obj,dict):return any(k in ids or contains(v,ids) for k,v in obj.items())
    return False


def business_date(r):
    if r.get('kind') in ('asset','mapping','opening','profile','rate'):return ''
    return r.get('business_date') or r.get('received_date') or (r.get('order') or {}).get('business_date','')


def plan(c,body,role):
    require_admin(role);day=rc.day(body.get('business_date'));scope=body.get('scope','orders')
    if scope not in ('orders','day'):raise ValueError('请选择清理订单或整日业务')
    source=snapshot(c);selected={t:[] for t in source};blockers=[]
    for t,rows in source.items():
        if t in ('fund_accounts','fund_assignments','fund_transfers','byproduct_statements','statement_documents','statement_voids') or t in SUBMISSIONS:continue
        for row in rows:
            r=value(row)
            if business_date(r)!=day:continue
            if scope=='orders' and t not in ('orders','archived_orders'):continue
            if t=='payroll_records' and r.get('kind') not in ('payment',):continue
            selected[t].append(row)
    orders=[value(r) for r in selected['orders']];oids={r['id'] for r in orders}
    for t in ('receipts','sales_returns','driver_return_requests','order_corrections','trade_records','asset_records'):
        for row in source[t]:
            r=value(row)
            if row not in selected[t] and contains(r,oids) and not (t=='asset_records' and r.get('kind') in ('asset','mapping')):selected[t].append(row)
    for row in selected['receipts']:
        r=value(row)
        if r.get('order_id') not in oids:blockers.append('所选日期的收款关联其他日期订单，须先核对原订单与实际收款，不能留下已收金额断账')
    for row in selected['sales_returns']:
        r=value(row);finance=r.get('finance') or {}
        if any(x.get('order_id') not in oids for x in finance.get('allocations',[])):blockers.append('退货抵扣关联其他日期订单，请先核对关联应收')
    # A reset must never erase a partially shared batch covering other customers/days.
    for row in selected['driver_return_requests']:
        other={x.get('order_id') for x in value(row).get('lines',[]) if x.get('order_id')} - oids
        if other:blockers.append('司机回框填报同时关联其他日期订单，须先核对整批归属')
    selected_ids={str(value(r).get('id')) for t,rs in selected.items() if t not in SUBMISSIONS for r in rs if value(r).get('id')}
    for t in SUBMISSIONS:
        for row in source[t]:
            r=value(row)
            if contains(r,selected_ids|oids) or scope=='day' and business_date(r)==day:selected[t].append(row)
    selected_ids|={str(value(r).get('id')) for rs in selected.values() for r in rs if value(r).get('id')}
    ignored={'fund_accounts','fund_assignments','fund_transfers','byproduct_statements','statement_documents','statement_voids','warehouse_plans','dispatch_plans'}|SUBMISSIONS
    for t,rows in source.items():
        if t in ignored:continue
        for row in rows:
            if row in selected[t]:continue
            r=value(row)
            if t=='asset_records' and r.get('kind') in ('asset','mapping'):continue
            if contains(r,selected_ids|oids):blockers.append(LABELS[t]+'仍引用待清理记录（'+str(r.get('id',''))+'），请先处理关联业务')
    # Do not sever a physical stock carry or rewrite a later inventory closing.
    if scope=='orders':
        if oids and any(value(r).get('state')=='closed' and value(r)['business_date']>=day for r in source['stock_closings']):blockers.append('所选订单已进入库存日结范围；如为测试数据，请改选整日业务清理，并先处理后续结转')
    else:
        for row in source['stock_closings']:
            r=value(row)
            if r['business_date']>day and r.get('state')=='closed':blockers.append(r['business_date']+'已有后续日结，请从最新业务日向前逐日清理')
        for row in source['warehouse_plans']:
            r=value(row)
            if r['business_date']>day and r.get('opening_source_date')==day:blockers.append(r['business_date']+'已引用本日结转，请先清理后续业务日')
        material_ids={value(r).get('material_id') for r in selected['material_entries']}
        if material_ids and any(business_date(value(r))>day and value(r).get('material_id') in material_ids for r in source['material_entries'] if r not in selected['material_entries']):blockers.append('后续日期有同物料的库存或成本流水，须先处理后续日期，避免原料库存和成本断账')
    for row in selected['trade_records']:
        r=value(row)
        if r.get('document_id') or r.get('kind')=='transport-document':blockers.append('运输趟次已结算，请先核对运输结算单，不能直接清理')
    for row in selected['finished_goods_records']:
        r=value(row)
        if r.get('document_id') or r.get('kind') in ('document','statement'):blockers.append('外购成品已出具供应商结算单，请先核对供应商账款')
    periods=rc.rows(c,'resource_periods')
    if any(p.get('state')=='closed' and p.get('month',p.get('period',''))>=day[:7] for p in periods) and any(selected[t] for t in selected):blockers.append('该日期已进入成本月结范围，请先重开相关成本月份并核对')
    documents={did for o in orders for did in order_corrections.affected_documents(c,o)}
    # Remove references from that day's plan for order-only cleanup, preserving stock.
    updates={}
    if scope=='orders':
        for t in ('warehouse_plans','dispatch_plans'):
            for row in source[t]:
                r=value(row)
                if r.get('business_date')!=day:continue
                before=rc.dump(r)
                if t=='warehouse_plans':
                    r['allocations']=[x for x in r.get('allocations',[]) if x.get('order_id') not in oids];r['allocation_state']='draft';r['version']=r.get('version',0)+1
                else:r['order_markets']={k:v for k,v in r.get('order_markets',{}).items() if k not in oids};r['version']=r.get('version',0)+1
                if oids and before!=rc.dump(r):updates.setdefault(t,[]).append({**row,'payload':rc.dump(r)})
    counts={t:len(rs) for t,rs in selected.items() if rs};summaries=[{'table':t,'label':LABELS[t],'count':n} for t,n in counts.items()]+[{'table':t,'label':LABELS[t]+'（移除原订单引用，保留其他内容）','count':len(rs)} for t,rs in updates.items()]
    protected={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in PROTECTED}
    visible={'business_date':day,'scope':scope,'fingerprint':fingerprint(source),'counts':counts,'summary':summaries,'order_ids':sorted(oids),'orders':[{'id':o['id'],'customer_name':o['customer_name'],'state':o['state'],'total_cents':o['total_cents'],'paid_cents':o.get('paid_cents',0)} for o in orders],'document_ids':sorted(documents),'cross_date_count':sum(1 for rs in selected.values() for row in rs if business_date(value(row)) and business_date(value(row))!=day),'blockers':list(dict.fromkeys(blockers)),'protected_counts':protected,'empty':not any(counts.values()),'retained':'产品、客户、价格皮重、产品框型属性、期初欠框、供应商、员工、账号权限和生产参数保留；操作审计与已出具结算单原件保留'}
    return visible,source,selected,updates


def key_columns(c,t):return [r[1] for r in sorted(c.execute('PRAGMA table_info('+t+')'),key=lambda x:x[5]) if r[5]]


def remove(c,t,row):
    keys=key_columns(c,t);c.execute('DELETE FROM '+t+' WHERE '+' AND '.join(k+'=?' for k in keys),tuple(row[k] for k in keys))


def put(c,t,row):
    cols=list(row);c.execute('INSERT OR REPLACE INTO '+t+'('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',tuple(row.values()))


def save(c,body,role,now,audit):
    require_admin(role);action=body.get('action')
    if action=='preview':return plan(c,body,role)[0]
    if action=='restore':
        row=c.execute('SELECT * FROM trial_archives WHERE id=?',(body.get('id'),)).fetchone()
        if not row or row['restored_at']:raise ValueError('按日归档不存在或已恢复')
        archive=json.loads(row['payload'])
        if archive.get('format')!='day-reset-v1':raise ValueError('请选择按日期清理的归档')
        if body.get('confirm_date')!=archive['business_date']:raise ValueError('请填写归档日期确认恢复')
        if fingerprint(snapshot(c))!=archive['after_fingerprint']:raise ValueError('清理后已有业务新增或变更，不能覆盖恢复；请先核对新录入业务或使用归档另行恢复')
        for t,items in archive['added'].items():
            for r in items:remove(c,t,r)
        for t,items in archive['before'].items():
            for r in items:put(c,t,r)
        key=row['id'];counts=archive['counts'];c.execute('UPDATE trial_archives SET restored_at=? WHERE id=?',(now(),key));audit(c,role,'恢复按日期归档的测试业务',key,None,{'business_date':archive['business_date'],'counts':counts})
    elif action=='archive':
        preview,before,selected,updates=plan(c,body,role)
        if body.get('fingerprint')!=preview['fingerprint']:raise ValueError('业务数据已变化，请重新预览后清理')
        if preview['blockers']:raise ValueError('；'.join(preview['blockers']))
        if preview['empty']:raise ValueError('所选日期没有需要清理的业务')
        if body.get('confirm_date')!=preview['business_date'] or body.get('test_data_confirmed') is not True:raise ValueError('请确认预览范围均为测试数据，并填写所选日期')
        reason=rc.text(body.get('reason'),'清理原因',500);key='DAY-'+secrets.token_hex(10);counts={'orders':0,'receipts':0,'archived_orders':0,**preview['counts']}
        for t,items in selected.items():
            for r in items:remove(c,t,r)
        for t,items in updates.items():
            for r in items:put(c,t,r)
        for o in [value(r) for r in selected['orders']]:order_corrections.invalidate(c,o,'测试数据按日期清理：'+reason,role,now,audit)
        after=snapshot(c);changed={};added={}
        for t,items in before.items():
            keys=key_columns(c,t);ident=lambda r:tuple(r[k] for k in keys);after_map={ident(r):r for r in after[t]};before_map={ident(r):r for r in items}
            changed[t]=[r for r in items if after_map.get(ident(r))!=r];added[t]=[r for r in after[t] if ident(r) not in before_map]
        archive={'format':'day-reset-v1','scope':preview['scope'],'business_date':preview['business_date'],'counts':counts,'before':{t:r for t,r in changed.items() if r},'added':{t:r for t,r in added.items() if r},'after_fingerprint':fingerprint(after),'voided_document_ids':preview['document_ids'],'protected_counts':preview['protected_counts']}
        c.execute('INSERT INTO trial_archives VALUES(?,?,?,?,NULL)',(key,rc.dump(archive),now(),reason));audit(c,role,'按日期归档清理测试业务',key,preview,{'business_date':preview['business_date'],'counts':counts})
    else:raise ValueError('按日期清理操作无效')
    epoch=secrets.token_hex(12);c.execute("INSERT INTO meta VALUES('business_data_epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(epoch,));inventory.bump(c)
    return {'id':key,'counts':counts,'business_data_epoch':epoch,'action':action}
