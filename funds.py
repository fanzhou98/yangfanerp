"""Book cash accounts projected from actual payments; receivables never move cash."""
import hashlib
import json
import secrets
from decimal import Decimal

import erp_access
import resources_costs as rc

KINDS=('银行账户','现金','微信','支付宝','其他')


def accounts(c):return rc.rows(c,'fund_accounts')


def validate_account(c,account_id):
    if not account_id:return ''  # Older clients and historical entries remain explicitly unassigned.
    if not isinstance(account_id,str):raise ValueError('资金账户编号无效')
    row=c.execute('SELECT payload FROM fund_accounts WHERE id=?',(account_id,)).fetchone()
    if not row or not json.loads(row[0]).get('active'):raise ValueError('资金账户不存在或已停用，请重新选择')
    return account_id


def account_catalog(c):return [{k:a[k] for k in ('id','name','kind','active')} for a in accounts(c)]


def movements(c):
    result=[]
    def add(key,day,amount,direction,label,partner='',record=None):
        if type(amount) is not int or amount<0:raise ValueError('资金流水金额无效，请核对原业务台账')
        if not amount:return
        value={'id':key,'business_date':day,'amount_cents':amount,'direction':direction,'source':label,
               'partner':partner,'source_account_id':(record or {}).get('account_id',''),'account_id':(record or {}).get('account_id',''),
               'note':(record or {}).get('note') or (record or {}).get('reference','')}
        value['fingerprint']=hashlib.sha256(rc.dump({k:value[k] for k in ('id','business_date','amount_cents','direction')}).encode()).hexdigest()
        result.append(value)
    for r in rc.rows(c,'receipts'):
        if not r.get('voided'):add('receipt:'+r['id'],r['received_date'],r['amount_cents'],'in','产品收款',r.get('customer_name',''),r)
    for r in rc.rows(c,'byproduct_sales'):
        if r.get('voided'):continue
        receipts=r.get('receipts',[]);initial=r['received_cents']-sum(x['amount_cents'] for x in receipts)
        add('byproduct:'+r['id']+':initial',r['business_date'],initial,'in','豆渣收款',r['buyer'],r)
        for i,x in enumerate(receipts):add('byproduct:'+r['id']+':'+str(i),x['business_date'],x['amount_cents'],'in','豆渣收款',r['buyer'],x)
    for table,label,partner in [('purchase_payments','采购付款','supplier_name'),('expense_payments','费用付款','payee')]:
        for r in rc.rows(c,table):
            if r.get('voided'):continue
            add(table+':'+r['id'],r['business_date'],r['amount_cents'],'out',label,r.get('payee_name') or r.get(partner,''),r)
    for r in rc.rows(c,'payroll_records'):
        if r.get('kind')=='payment' and not r.get('voided'):add('payroll:'+r['id'],r['business_date'],r['amount_cents'],'out','工资发放',r.get('employee_name',''),r)
    for r in rc.rows(c,'finished_goods_records'):
        if r.get('kind')=='payment' and not r.get('voided'):add('finished:'+r['id'],r['business_date'],r['amount_cents'],'out','外购成品付款',r.get('supplier_name',''),r)
        if r.get('kind')=='refund':add('finished-refund:'+r['id'],r['business_date'],r['amount_cents'],'in','外购成品供应商退款',r.get('supplier_name',''),r)
    for r in rc.rows(c,'sales_returns'):
        if r.get('voided'):continue
        for x in (r.get('finance') or {}).get('refunds',[]):
            if x.get('voided'):continue
            add('refund:'+x['id'],x['refund_date'],x['amount_cents'],'out','退货退款',r.get('customer_name',''),x)
    assigned={r['movement_id']:r for r in rc.rows(c,'fund_assignments')}
    for r in result:
        assignment=assigned.get(r['id']);r['assignment_version']=(assignment or {}).get('version',0)
        if assignment and assignment['fingerprint']==r['fingerprint']:r['account_id']=assignment['account_id']
    for r in rc.rows(c,'fund_transfers'):
        for suffix,direction,account,other in [('out','out',r['from_account_id'],r['to_account_id']),('in','in',r['to_account_id'],r['from_account_id'])]:
            add('transfer:'+r['id']+':'+suffix,r['business_date'],r['amount_cents'],direction,'内部转账',other,{**r,'account_id':account})
    return sorted(result,key=lambda r:(r['business_date'],r['id']),reverse=True)


def report(c,asof,*,month='',start='',end='',account_id='',direction='',page=None,page_size=50):
    import cash_query
    return cash_query.report(c,asof,month=month,start=start,end=end,account_id=account_id,direction=direction,page=page,page_size=page_size)


def save(c,action,b,role,now,audit):
    erp_access.require_role(role,'funds.manage')
    if action=='account':
        old=None
        if b.get('id'):
            row=c.execute('SELECT payload FROM fund_accounts WHERE id=?',(b['id'],)).fetchone()
            if not row:raise ValueError('账户不存在或已删除，请刷新')
            old=json.loads(row[0])
            if b.get('version')!=old['version']:raise ValueError('账户资料已修改，请重新打开核对')
        elif b.get('version',0)!=0:raise ValueError('新增账户版本无效')
        name=rc.text(b.get('name'),'账户名称',80);kind=b.get('kind')
        if kind not in KINDS:raise ValueError('账户类型无效')
        if any(a['name']==name and a['id']!=(old or {}).get('id') for a in accounts(c)):raise ValueError('账户名称已存在，请使用可区分的名称')
        day=rc.day(b.get('opening_date'));amount=b.get('opening_balance','')
        # Signed opening balances support genuine overdrafts, with cents precision.
        try:value=Decimal(str(amount))
        except Exception:raise ValueError('期初余额无效')
        if not value.is_finite() or abs(value)>Decimal('100000000') or value.as_tuple().exponent < -2:raise ValueError('期初余额须为最多两位小数的有效金额')
        cents=int(value*100)
        if old and (day!=old['opening_date'] or cents!=old['opening_balance_cents']) and any(r['account_id']==old['id'] or r['source_account_id']==old['id'] for r in movements(c)):raise ValueError('账户已有流水，不能改写期初日期和余额；请核对原始账目')
        active=b.get('active',True)
        if type(active) is not bool:raise ValueError('账户启用状态无效')
        r={'id':old['id'] if old else 'FA-'+secrets.token_hex(6).upper(),'name':name,'kind':kind,'active':active,'opening_date':day,'opening_balance_cents':cents,
           'account_no':rc.text(b.get('account_no',''),'账号 / 尾号',80,False),'note':rc.text(b.get('note',''),'账户备注',500,False),
           'version':(old or {}).get('version',0)+1,'updated_at':now()}
        c.execute('INSERT INTO fund_accounts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(r['id'],rc.dump(r)))
        audit(c,role,'维护资金账户' if old else '新增资金账户',r['id'],old,r);return r
    if action=='delete':
        row=c.execute('SELECT payload FROM fund_accounts WHERE id=?',(b.get('id'),)).fetchone()
        if not row:raise ValueError('账户不存在或已删除')
        old=json.loads(row[0])
        if old['version']!=b.get('version'):raise ValueError('账户已修改，请刷新后再删除')
        if old['opening_balance_cents'] or any(r['account_id']==old['id'] or r['source_account_id']==old['id'] for r in movements(c)) or any(r['account_id']==old['id'] for r in rc.rows(c,'fund_assignments')):raise ValueError('账户有期初余额或历史流水，不能删除；请改为停用并保留账目')
        c.execute('DELETE FROM fund_accounts WHERE id=?',(old['id'],));audit(c,role,'删除未使用的资金账户',old['id'],old,None);return {'id':old['id'],'deleted':True}
    if action=='assign':
        row=next((r for r in movements(c) if r['id']==b.get('movement_id') and r['source']!='内部转账'),None)
        if not row or row['fingerprint']!=b.get('fingerprint') or row['assignment_version']!=b.get('version'):raise ValueError('收付款流水或归属已变化，请重新读取后关联')
        account_id=validate_account(c,b.get('account_id'))
        if not account_id:raise ValueError('请选择资金账户')
        r={'movement_id':row['id'],'account_id':account_id,'fingerprint':row['fingerprint'],'version':row['assignment_version']+1,'note':rc.text(b.get('note'),'关联依据',500),'at':now()}
        c.execute('INSERT INTO fund_assignments VALUES(?,?) ON CONFLICT(movement_id) DO UPDATE SET payload=excluded.payload',(r['movement_id'],rc.dump(r)))
        audit(c,role,'关联收付款资金账户',r['movement_id'],{'account_id':row['account_id']},r);return r
    if action=='transfer':
        key=rc.text(b.get('request_key'),'提交编号',100);fingerprint=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k!='_data_epoch'}).encode()).hexdigest()
        old=c.execute('SELECT payload FROM fund_transfers WHERE request_key=?',(key,)).fetchone()
        if old:
            r=json.loads(old[0])
            if r['fingerprint']!=fingerprint:raise ValueError('转账提交编号已用于其他内容')
            return r
        day=rc.day(b.get('business_date'));source=validate_account(c,b.get('from_account_id'));target=validate_account(c,b.get('to_account_id'))
        if not source or not target or source==target:raise ValueError('请选择两个不同的资金账户')
        if any(a['opening_date']>day for a in accounts(c) if a['id'] in (source,target)):raise ValueError('转账日期不能早于账户期初日期')
        r={'id':'FT-'+secrets.token_hex(6).upper(),'business_date':day,'from_account_id':source,'to_account_id':target,'amount_cents':rc.cents(b.get('amount'),'转账金额',True),'note':rc.text(b.get('note'),'转账凭据 / 说明',500),'fingerprint':fingerprint,'created_at':now()}
        c.execute('INSERT INTO fund_transfers VALUES(?,?,?)',(r['id'],key,rc.dump(r)));audit(c,role,'登记资金账户内部转账',r['id'],None,r);return r
    raise ValueError('未知资金账户操作')
