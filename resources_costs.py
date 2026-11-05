"""Raw materials, period expenses and by-product revenue; immutable posted ledgers."""
import json,secrets,hashlib
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from datetime import date, datetime
import calendar
import erp_access
import production_config as pc

MATERIALS=[('RM-SOY','大豆','原料','公斤'),('A-GYPSUM','石膏','辅料','公斤'),('A-DEFOAMER','消泡剂','辅料','公斤'),('A-ALKALI','食用碱','辅料','公斤'),('A-SALT','食用盐','辅料','公斤'),('A-COLOR','豆皮黄色素','辅料','公斤'),('P-CLOTH','豆腐布','耗材','公斤'),('P-BAG','豆皮包装袋','包装','包'),('P-OTHER','其他消耗包装（膜等）','包装','个'),('P-LARGE','大豆腐框','包装','个'),('P-MEDIUM','中豆腐框','包装','个'),('P-SMOKED','熏干框','包装','个'),('P-KONJAC','魔芋框','包装','个'),('P-LONG','长框','包装','个')]
CATEGORIES=[('wages-production','生产工资','人工工资','固定','产量'),('wages-delivery','配送工资','人工工资','固定','产量'),('wages-management','管理工资','人工工资','固定','用豆量'),('electricity','生产电费（不含冷库）','能源','变动','用豆量'),('gas','天然气/燃气','能源','变动','用豆量'),('water','水费','能源','变动','用豆量'),('transport','外包配送费','配送','变动','产量'),('rent','厂房租金','制造费用','固定','用豆量'),('depreciation','设备折旧','制造费用','固定','用豆量'),('maintenance','维修保养','制造费用','变动','用豆量'),('office','管理/办公费','管理','固定','用豆量'),('meals','厨房伙食费','管理','固定','用豆量'),('leakage','漏浆/渗漏损耗','制造费用','变动','用豆量'),('other','其他杂费','其他','变动','用豆量'),('cold-power','冷库电费（专属成本）','专属直接费用','变动','直接归属')]
TABLES={'material':'material_entries','expense':'indirect_expenses','byproduct':'byproduct_sales'}
def dump(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'),sort_keys=True)
def text(v,label,maxlen=200,required=True):
    if not isinstance(v,str) or len(v)>maxlen or required and not v.strip():raise ValueError('请填写有效的'+label)
    return v.strip()
def qty(v,label='数量',positive=False):
    try:
        if isinstance(v,bool):raise ValueError()
        d=Decimal(str(v))
        if not d.is_finite() or d<0 or d>Decimal('100000000') or d.as_tuple().exponent < -3 or positive and d<=0:raise ValueError()
        return d
    except (InvalidOperation,ValueError,TypeError):raise ValueError(label+'须为有效非负数，最多3位小数')
def cents(v,label='金额',positive=False):
    d=qty(v,label,positive)
    if d.as_tuple().exponent < -2:raise ValueError(label+'最多2位小数')
    return int(d*100)
def ds(v):return format(Decimal(v).normalize(),'f')
def day(v):
    try:
        if date.fromisoformat(v).isoformat()!=v:raise ValueError()
    except (ValueError,TypeError):raise ValueError('业务日期无效')
    return v
def fund_account(c,body):
    import funds
    return funds.validate_account(c,body.get('account_id'))

def rows(c,table):return [json.loads(r[0]) for r in c.execute('SELECT payload FROM '+table+' ORDER BY rowid')]
def receipts_paid_asof(c,asof):
    """Product receipts actually received on or before the as-of day, by order."""
    rc={}
    for oid,amount in c.execute("SELECT json_extract(payload,'$.order_id'),COALESCE(json_extract(payload,'$.amount_cents'),0) FROM receipts WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 AND json_extract(payload,'$.received_date')<=?",(asof,)):
        if oid:rc[oid]=rc.get(oid,0)+int(amount or 0)
    return rc


def opening_receipts_paid(c,asof):
    """期初应收已收（到账+折扣+抹零），按客户汇总；只算到 asof 当天为止。"""
    paid={}
    for cid,amount in c.execute("""SELECT json_extract(payload,'$.customer_id'),
        SUM(COALESCE(json_extract(payload,'$.amount_cents'),0)+COALESCE(json_extract(payload,'$.discount_cents'),0)+COALESCE(json_extract(payload,'$.rounding_cents'),0))
        FROM receipts WHERE json_extract(payload,'$.order_id')='' AND COALESCE(json_extract(payload,'$.voided'),0)=0
        AND json_extract(payload,'$.received_date')<=? GROUP BY json_extract(payload,'$.customer_id')""",(asof,)):
        if cid:paid[cid]=paid.get(cid,0)+int(amount or 0)
    return paid
def byproduct_paid_asof(c,asof):
    """Byproduct money received on or before the as-of day; legacy gap stays sale-day."""
    paid={}
    for rowid,payload in c.execute("SELECT id,payload FROM byproduct_sales WHERE COALESCE(json_extract(payload,'$.voided'),0)=0"):
        record=json.loads(payload);embedded=record.get('receipts') or []
        total=sum(int(x.get('amount_cents') or 0) for x in embedded)
        received=sum(int(x.get('amount_cents') or 0) for x in embedded if (x.get('business_date') or '')<=asof)
        paid[record.get('id') or rowid]=max(0,int(record.get('received_cents') or 0)-total)+received
    return paid
def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'resources')

def revision(c):
    total=c.execute('SELECT COALESCE(SUM(version),0) FROM material_items').fetchone()[0]
    return total+sum(c.execute("SELECT COALESCE(SUM(COALESCE(json_extract(payload,'$.version'),1)),0) FROM "+table).fetchone()[0] for table in TABLES.values())

def open_period(c,when):
    r=c.execute('SELECT payload FROM resource_periods WHERE month=?',(when[:7],)).fetchone()
    if r and json.loads(r[0])['state']=='closed':raise ValueError('所属月份已结账，请由会计重新打开后登记')
WAREHOUSES=[{'id':'WH-TOFU','name':'豆腐库'},{'id':'WH-SKIN','name':'豆皮库'},{'id':'WH-EXTERNAL','name':'外库'},{'id':'WH-MAIN','name':'大库'},{'id':'WH-COMMON','name':'公共辅料与包装库'}]
WAREHOUSE_NAMES={**{w['id']:w['name'] for w in WAREHOUSES},'WH-UNASSIGNED':'历史待确认库'}
MATERIAL_TARGETS={'P-CLOTH':('豆腐线','豆腐'),'P-BAG':('豆皮线','豆皮'),'P-OTHER':('共用','共用'),'A-ALKALI':('素鸡线','素鸡'),'A-SALT':('素鸡线','素鸡'),'A-GYPSUM':('共用','共用'),'A-DEFOAMER':('共用','共用'),'A-COLOR':('豆皮线','豆皮')}
def attribution(item):
    department,target=MATERIAL_TARGETS.get(item['id'],('共用','共用'))
    return {'default_department':department,'default_cost_target':target}
def warehouse(item,wid,required=True,*,c=None,when=None):
    if item['id']!='RM-SOY' and not wid:wid='WH-COMMON'
    choices=pc.warehouses(c,when) if c is not None else [{**w,'active':True,'material_ids':['RM-SOY'] if w['id']!='WH-COMMON' else ['*']} for w in WAREHOUSES]
    row=next((w for w in choices if w['id']==wid and w.get('active',True)),None)
    if not row or not pc.accepts_material(row,item['id']):raise ValueError('请选择允许存放该物料的有效库房')
    return wid

def warehouse_names(c):return pc.warehouse_names(c)
def entry_warehouse(e):return e.get('warehouse_id') or ('WH-UNASSIGNED' if e['material_id']=='RM-SOY' else 'WH-COMMON')
def purpose(item,wid,value=None):
    if item['id']=='RM-SOY':
        if value and value not in ('共用','豆腐线','豆皮线') and value not in ('豆腐磨浆系统','豆皮磨浆系统'):raise ValueError('大豆库存不使用管理或配送产线，请选择磨浆系统')
        return {'WH-TOFU':'豆腐线','WH-SKIN':'豆皮线'}.get(wid,'共用')
    return value or attribution(item)['default_department']

SOY_ORIGIN_META='soy_origins'
DEFAULT_SOY_ORIGINS=('伊犁','东北','河南','天津','湖北')
def _clean_origins(values):
    result=[]
    if not isinstance(values,list):return result
    for value in values:
        if not isinstance(value,str):continue
        value=value.strip()
        if value and len(value)<=20 and value not in result:result.append(value)
    return result[:20]
def soy_origins(c):
    row=c.execute('SELECT value FROM meta WHERE key=?',(SOY_ORIGIN_META,)).fetchone()
    if not row:return list(DEFAULT_SOY_ORIGINS)
    try:raw=json.loads(row[0])
    except (TypeError,ValueError):raw=None
    values=_clean_origins(raw if isinstance(raw,list) else raw.get('origins') if isinstance(raw,dict) else [])
    return values or list(DEFAULT_SOY_ORIGINS)
def quality(body,origins=None):
    source=body.get('quality',body);result={}
    if not isinstance(source,dict):raise ValueError('黄豆检测数据格式无效')
    for key,label in [('protein_pct','蛋白质'),('soluble_protein_pct','水溶蛋白'),('moisture_pct','水分')]:
        value=source.get(key,'')
        if value in ('',None):result[key]='';continue
        number=qty(value,label)
        if number>100:raise ValueError(label+'须在0至100%之间')
        result[key]=ds(number)
    for key,label,choices in [('sowing_type','大豆播种类型',('春播','复播')),('origin','大豆产地',tuple(origins or DEFAULT_SOY_ORIGINS))]:
        value=source.get(key,'') or ''
        if value and value not in choices:raise ValueError(label+'无效')
        result[key]=value
    result['soy_variety']=text(source.get('soy_variety',''),'采购品种',60,False)
    result['batch_no']=text(source.get('batch_no',''),'批号',100,False)
    result['test_note']=text(source.get('test_note',''),'检测说明',300,False)
    return result

def material_ledger(c,until=None,warehouse_details=False,*,material_ids=None):
    masters={r['id']:dict(r) for r in c.execute('SELECT * FROM material_items ORDER BY sort_order,rowid') if material_ids is None or r['id'] in material_ids};stock={};entries=[];layers={};fifo_started=False
    marker=c.execute("SELECT value FROM meta WHERE key='material_fifo_start'").fetchone();cutover=int(marker[0]) if marker else 10**18
    wnames=warehouse_names(c);totals={mid:[Decimal(0),0,Decimal(0)] for mid in masters};live={};dead={};head={};seen={};index={};keys={};mbuckets={}
    def _order(lot):return (lot['received_date'],lot.get('fifo_sequence',0),lot['lot_id'])
    def _push(key,lots):
        stored=layers.setdefault(key,[]);ix=index.setdefault(key,[]);ks=keys.setdefault(key,[])
        for lot in lots:
            o=_order(lot);lo=0;hi=len(ks)
            while lo<hi:
                mid=(lo+hi)//2
                if ks[mid]<=o:lo=mid+1
                else:hi=mid
            ks.insert(lo,o);ix.insert(lo,lot);stored.append(lot)
            if lo<head.get(key,0):head[key]=lo
    def _drop_dead(key):
        layers[key][:]=[l for l in layers[key] if l['qty']>0]
        ix=index[key][:]=[l for l in index[key] if l['qty']>0]
        keys[key][:]=[_order(l) for l in ix];dead[key]=0;head[key]=0
    def seed_layers():
        for key,b in stock.items():
            if b['qty']>0:
                layers[key]=[{'lot_id':'LEGACY-'+key[0]+'-'+key[1],'received_date':'','fifo_sequence':0,'quality':{},'qty':b['qty'],'value_cents':b['value_cents'],'uncosted_qty':b['uncosted_qty'],'legacy':True}]
                index[key]=layers[key][:];keys[key]=[_order(lot) for lot in layers[key]]
                live[key]=b['uncosted_qty'];dead[key]=0;head[key]=0
    def take(mid,wid,q,source_lot_id=''):
        selected=[];remaining=q;key=(mid,wid);lst=index.get(key,[]);size=len(lst);i=head.get(key,0)
        while i<size and lst[i]['qty']<=0:i+=1
        head[key]=i
        while i<size:
            lot=lst[i];i+=1
            if remaining<=0:break
            if source_lot_id and lot['lot_id']!=source_lot_id:continue
            used=min(remaining,lot['qty'])
            if used<=0:continue
            value=lot['value_cents'] if used==lot['qty'] else int((Decimal(lot['value_cents'])*used/lot['qty']).quantize(Decimal(1),rounding=ROUND_HALF_UP))
            uncosted=lot.get('uncosted_qty',Decimal(0))*used/lot['qty']
            lot['qty']-=used;lot['value_cents']-=value;lot['uncosted_qty']-=uncosted;remaining-=used;live[key]=live.get(key,Decimal(0))-uncosted;selected.append({**lot,'qty':used,'value_cents':value,'uncosted_qty':uncosted})
            if lot['qty']<=0:dead[key]=dead.get(key,0)+1
        if remaining>0:raise ValueError('所选批次余额不足或不属于该库房 / 日期' if source_lot_id else 'FIFO批次余额不足')
        if dead.get(key,0)*2>=size:_drop_dead(key)
        return selected
    def bucket(mid,wid):
        if (mid,wid) not in stock:stock[(mid,wid)]={**masters[mid],'warehouse_id':wid,'warehouse_name':wnames.get(wid,wid),'qty':Decimal(0),'value_cents':0,'uncosted_qty':Decimal(0)};mbuckets.setdefault(mid,[]).append(stock[(mid,wid)])
        return stock[(mid,wid)]
    def sync(*bs):
        for b in bs:
            key=(b['id'],b['warehouse_id']);cur=(b['qty'],b['value_cents'],b['uncosted_qty']);prev=seen.get(key)
            if prev==cur:continue
            t=totals[b['id']]
            if prev is None:t[0]+=cur[0];t[1]+=cur[1];t[2]+=cur[2]
            else:t[0]+=cur[0]-prev[0];t[1]+=cur[1]-prev[1];t[2]+=cur[2]-prev[2]
            seen[key]=cur
    def total(mid):
        q,v,_=totals[mid];return (q,v,sum((b['uncosted_qty'] for b in mbuckets.get(mid,[])),Decimal(0)))
    warehouses=pc.warehouses(c,until)
    for mid in masters:
        for w in warehouses:
            if pc.accepts_material(w,mid):bucket(mid,w['id'])
    if material_ids is None:source=rows(c,'material_entries')
    elif not material_ids:source=[]
    else:
        condition="json_extract(payload,'$.material_id') IN ("+','.join('?' for _ in material_ids)+')';args=list(material_ids)
        if until:condition+=" AND json_extract(payload,'$.business_date')<=?";args.append(until)
        source=[json.loads(r[0]) for r in c.execute('SELECT payload FROM material_entries WHERE '+condition+' ORDER BY rowid',args)]
    for e in sorted(source,key=lambda r:(r['business_date'],r['sequence'])):
        if e.get('voided') or until and e['business_date']>until:continue
        if e['sequence']>=cutover and not fifo_started:seed_layers();fifo_started=True
        if fifo_started and e['sequence']<cutover:raise ValueError('FIFO切换前的历史流水不能跨越新流水日期，请调整业务日期')
        wid=entry_warehouse(e);s=bucket(e['material_id'],wid);q=Decimal(e['qty']);kind=e['kind'];incoming=kind in ('opening','receipt','return','gain');delta=q if incoming else -q
        if delta<0 and q>s['qty']:raise ValueError(s['name']+'在'+s['warehouse_name']+' '+e['business_date']+' 库存不足；不能跨库扣减或形成历史负库存')
        picked=[]
        if incoming:
            cost=e['amount_cents']
            if fifo_started:
                lot={'lot_id':e['id'],'received_date':e['business_date'],'fifo_sequence':e['sequence'],'quality':e.get('quality',{}),'qty':q,'value_cents':cost,'uncosted_qty':q if cost==0 else Decimal(0),'legacy':False}
                key=(e['material_id'],wid);_push(key,[lot]);live[key]=live.get(key,Decimal(0))+lot['uncosted_qty']
        elif fifo_started:
            picked=take(e['material_id'],wid,q,e.get('source_lot_id',''));cost=sum(l['value_cents'] for l in picked)
        else:
            if e.get('source_lot_id'):raise ValueError('历史流水尚未启用批次计价，不能指定批次')
            cost=s['value_cents'] if q==s['qty'] else int((Decimal(s['value_cents'])*q/s['qty']).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        before=s['qty'];uncosted_out=s['uncosted_qty']*q/before if not incoming and before else Decimal(0)
        s['qty']+=delta;s['value_cents']+=cost if incoming else -cost
        if incoming and cost==0:s['uncosted_qty']+=q
        elif not incoming:s['uncosted_qty']=max(Decimal(0),s['uncosted_qty']-uncosted_out)
        if fifo_started:
            s['uncosted_qty']=live.get((e['material_id'],wid),Decimal(0))
            uncosted_out=sum((l.get('uncosted_qty',Decimal(0)) for l in picked),Decimal(0))
        extra={'uncosted_out_qty':ds(uncosted_out),'valuation_method':'FIFO' if fifo_started else '历史移动加权','fifo_allocations':[{**l,'qty':ds(l['qty']),'uncosted_qty':ds(l.get('uncosted_qty',0))} for l in picked]}
        touched=[s]
        if kind=='transfer':
            if fifo_started:
                key=(e['material_id'],e['target_warehouse_id']);_push(key,picked);live[key]=live.get(key,Decimal(0))+uncosted_out
            target=bucket(e['material_id'],e['target_warehouse_id']);target['qty']+=q;target['value_cents']+=cost;target['uncosted_qty']+=uncosted_out;touched.append(target)
            extra.update({'transfer_value_cents':cost,'target_warehouse_balance_qty':ds(target['qty']),'target_warehouse_balance_cents':target['value_cents'],'target_uncosted_balance_qty':ds(target['uncosted_qty'])})
        sync(*touched)
        tq,tv,tu=total(e['material_id'])
        entries.append({**e,'warehouse_id':wid,'warehouse_name':s['warehouse_name'],'cost_cents':cost if kind!='transfer' else 0,'delta_qty':ds(delta if kind!='transfer' else Decimal(0)),'balance_qty':ds(tq),'balance_cents':tv,'uncosted_balance_qty':ds(tu),'warehouse_balance_qty':ds(s['qty']),'warehouse_balance_cents':s['value_cents'],'warehouse_uncosted_balance_qty':ds(s['uncosted_qty']),**extra})
    if not fifo_started:seed_layers()
    for key,b in stock.items():b['lots']=[{**l,'qty':ds(l['qty']),'uncosted_qty':ds(l.get('uncosted_qty',0))} for l in layers.get(key,[]) if l['qty']>0]
    def serial(s):return {**s,'qty':ds(s['qty']),'uncosted_qty':ds(s['uncosted_qty']),'low_stock':s['active'] and s['qty']<=Decimal(s['reorder_qty']),'average_price':ds(Decimal(s['value_cents'])/100/s['qty']) if s['qty'] else '0'}
    aggregate=[]
    for mid,item in masters.items():
        q,v,u=total(mid);aggregate.append(serial({**item,'qty':q,'value_cents':v,'uncosted_qty':u}))
    result=(aggregate,entries)
    return (*result,[serial(s) for s in stock.values()]) if warehouse_details else result

def expense_periods(e):
    return e.get('accruals') or [{'period':e['period'],'amount_cents':e['amount_cents']}]

def expense_open_periods(c,e):
    for row in expense_periods(e):open_period(c,row['period']+'-01')

def period_expenses(c,month):
    """Accrual projection only. Payment always references the single source bill."""
    result=[]
    for e in rows(c,'indirect_expenses'):
        if e.get('voided'):continue
        for part in expense_periods(e):
            if part['period']==month:
                result.append({**e,'source_amount_cents':e['amount_cents'],'period':month,'amount_cents':part['amount_cents']})
    import expense_estimates
    return result+expense_estimates.pending_costs(c,month)

def expense_payment_required(e):
    return e.get('payment_mode',e.get('category_snapshot',{}).get('payment_mode','payroll' if e['category'].startswith('wages-') else 'noncash' if e['category']=='depreciation' else 'payable'))=='payable'

def expense_projection(c, expenses=None):
    # A scoped reader can project only its selected source bills. Default callers
    # retain the complete accounting projection used by bootstrap/month close.
    if expenses is None:
        expenses=rows(c,'indirect_expenses')
    ids=dump([e['id'] for e in expenses])
    def events(table):
        return [json.loads(r[0]) for r in c.execute(
            "SELECT payload FROM "+table+" WHERE json_extract(payload,'$.expense_id') IN (SELECT value FROM json_each(?)) ORDER BY rowid",(ids,))]
    reviews=events('expense_reviews');payments=events('expense_payments');result=[]
    for expense in expenses:
        history=[r for r in reviews if r['expense_id']==expense['id']];paid=[p for p in payments if p['expense_id']==expense['id']]
        known_payees={p.get('payee','').strip() for p in paid if p.get('payee','').strip()}
        if not expense.get('partner','').strip() and len(known_payees)==1:expense={**expense,'partner':next(iter(known_payees)),'counterparty_from_payment':True}
        valid_reviews=[r for r in history if r.get('expense_version',0)>=expense.get('review_reset_version',0)];review=valid_reviews[-1] if valid_reviews else None;total=sum(p['amount_cents'] for p in paid);required=expense_payment_required(expense)
        state='voided' if expense.get('voided') else 'payroll' if expense.get('payment_mode',expense.get('category_snapshot',{}).get('payment_mode'))=='payroll' or expense['category'].startswith('wages-') else 'noncash' if not required else 'paid' if total==expense['amount_cents'] else 'partial' if total else 'pending' if not review else 'returned' if review['decision']=='return' else 'approved'
        if required and not expense.get('partner','').strip() and not total:state='pending'
        if expense.get('payroll_sheet_id') and not expense.get('voided'):
            sheet_row=c.execute('SELECT payload FROM payroll_records WHERE id=?',(expense['payroll_sheet_id'],)).fetchone();sheet=json.loads(sheet_row[0]) if sheet_row else {}
            employee_ids={r['employee_id'] for r in sheet.get('rows',[]) if r.get('salary_category','wages-production')==expense['category']}
            total=c.execute("SELECT COALESCE(SUM(json_extract(payload,'$.amount_cents')),0) FROM payroll_records WHERE json_extract(payload,'$.kind')='payment' AND json_extract(payload,'$.month')=? AND json_extract(payload,'$.employee_id') IN (SELECT value FROM json_each(?))",(expense['period'],dump(sorted(employee_ids)))).fetchone()[0]
        status={'voided':'已作废','payroll':'工资系统发放','noncash':'非现金成本','paid':'已付清','partial':'部分付款','pending':'待出纳核对','returned':'待会计处理','approved':'待付款'}[state]
        result.append({**expense,'payment_required':required,'payment_state':state,'payment_status':'待补费用收款方' if required and not expense.get('partner','').strip() and not total else ('工资已计成本 · '+('已发清' if total==expense['amount_cents'] else '尚有未发')) if expense.get('payroll_sheet_id') and not expense.get('voided') else status,'counterparty_pending':required and not expense.get('partner','').strip() and not total,'paid_cents':total,'outstanding_cents':expense['amount_cents']-total if (required or expense.get('payroll_sheet_id')) and not expense.get('voided') else 0,'review':review,'review_history':history,'payments':paid})
    return result

def voided_material_entries(c,limit=500):
    result=[]
    for e in rows(c,'material_entries'):
        if not e.get('voided'):continue
        result.append({**{k:e.get(k,'') for k in ('id','business_date','material_id','material_name','unit','kind','qty','warehouse_id','warehouse_name','production_system_id','production_system_name','handler','note','void_reason','voided_at','version','sequence')},'voided':True})
    return sorted(result,key=lambda e:e.get('sequence',0),reverse=True)[:limit]

def snapshot(c, *, include_expense_history=True, include_byproduct_history=True):
    stock,entries,locations=material_ledger(c,warehouse_details=True)
    stock=[{**i,**attribution(i),**__import__('material_consumption').settings(c,i['id']),'default_product_ids':json.loads(i.get('default_product_ids') or '[]')} for i in stock]
    expenses=expense_projection(c) if include_expense_history else []
    byproducts=[byproduct_business_record(r) for r in rows(c,'byproduct_sales')] if include_byproduct_history else []
    config_projection = pc.projection(c)
    return {'expense_history_deferred':not include_expense_history,'byproduct_history_deferred':not include_byproduct_history,'production_configs':config_projection['versions'],'production_config_index':config_projection['index'],'warehouses':pc.warehouses(c),'warehouse_stocks':locations,'items':stock,'entries':entries,'voided_entries':voided_material_entries(c),'expenses':expenses,'expense_payables':[e for e in expenses if e['payment_required']],'expense_payments':rows(c,'expense_payments') if include_expense_history else [],'byproducts':byproducts,'expense_counterparties':__import__('expense_parties').catalog(c),'expense_counterparty_kinds':__import__('expense_parties').KINDS,'categories':__import__('cost_allocation').categories(c),'periods':[{k:v for k,v in json.loads(r[0]).items() if k!='report_snapshot'} for r in c.execute('SELECT payload FROM resource_periods ORDER BY month')],'amortizations':amortization_projection(c),'revision':revision(c)}

def month_index(value):
    year,month=str(value)[:7].split('-');return int(year)*12+int(month)-1

def amortizations(c):
    result=[]
    for row in c.execute('SELECT entry_id,months,start_month,closed_month,version,payload FROM material_amortizations ORDER BY rowid'):
        value=json.loads(row[5]);value.update(months=int(row[1]),start_month=row[2],closed_month=row[3],version=int(row[4]))
        result.append(value)
    return result

def amortization_projection(c, month=None):
    import material_allocation as ma
    entries={e['id']:e for e in material_ledger(c)[1]}
    result=[]
    for r in amortizations(c):
        e=entries.get(r['entry_id'])
        if not e or e.get('voided'):continue
        amount=int(e.get('cost_cents') or 0)
        result.append({**{k:r.get(k) for k in ('id','entry_id','start_month','closed_month','months')},'material_id':r.get('material_id',''),'material_name':r.get('material_name',''),'unit':r.get('unit',''),'business_date':e['business_date'],'amount_cents':amount,'product_ids':r.get('product_ids') or [],**ma.amortization_state(r,amount,month)})
    return sorted(result,key=lambda x:(x['start_month'],x['business_date']),reverse=True)

def _workshop_issue(c, month):
    """Non-soy material movement inside the month, from the FIFO ledger."""
    end = month + '-' + str(calendar.monthrange(int(month[:4]), int(month[5:7]))[1])
    _, entries = material_ledger(c, end); result = {}
    for e in entries:
        if not str(e.get('business_date') or '').startswith(month) or e.get('voided'): continue
        if e.get('material_id') == 'RM-SOY' or e.get('kind') not in ('consume', 'return', 'loss'): continue
        sign = -1 if e['kind'] == 'return' else 1
        d = result.setdefault(e['material_id'], {'qty': Decimal(0), 'cents': 0, 'entries': 0})
        d['qty'] += Decimal(e.get('qty') or 0) * sign; d['cents'] += int(e.get('cost_cents') or 0) * sign; d['entries'] += 1
    return result


def _workshop_records(c, month):
    return {r['material_id']: json.loads(r['payload']) for r in c.execute('SELECT material_id,payload FROM workshop_counts WHERE month=?', (month,))}


def workshop_report(c, month):
    import material_consumption
    return material_consumption.report(c, month)


def workshop_ratios(c, month):
    result = {}
    for r in workshop_report(c, month)['rows']:
        if r['counted'] and r['issue_cents'] > 0 and r['actual_cents'] != '':
            result[r['material_id']] = Decimal(r['actual_cents']) / Decimal(r['issue_cents'])
    return result


def apply_workshop(entries, ratios):
    """Scale issued cost to actual consumption; the last entry absorbs rounding."""
    if not ratios: return entries, {}
    groups = {}
    for i, e in enumerate(entries):
        if e.get('material_id') in ratios and e.get('material_id') != 'RM-SOY': groups.setdefault(e['material_id'], []).append(i)
    out = [dict(e) for e in entries]; adjust = {}
    for mid, indexes in groups.items():
        total = sum(int(entries[i].get('cost_cents') or 0) for i in indexes)
        target = int((Decimal(total) * ratios[mid]).quantize(Decimal('1'), ROUND_HALF_UP)); running = 0
        for pos, i in enumerate(indexes):
            value = int(entries[i].get('cost_cents') or 0)
            newv = target - running if pos == len(indexes) - 1 else int((Decimal(value) * ratios[mid]).quantize(Decimal('1'), ROUND_HALF_UP))
            running += newv; out[i]['cost_cents'] = newv
        adjust[mid] = target - total
    return out, adjust


class Operations:
    def __init__(self,c,now,audit):self.c=c;self.now=now;self.audit=audit
    def product(self,pid):
        if pid and not self.c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise ValueError('归属产品不存在')
        return pid or ''
    def prior(self,table,body):
        key=text(body.get('request_key'),'提交编号',100);r=self.c.execute('SELECT payload FROM '+table+' WHERE request_key=?',(key,)).fetchone()
        if r:
            result=json.loads(r[0]);fingerprint=hashlib.sha256(dump({k:v for k,v in body.items() if k not in ('_data_epoch','request_key')}).encode()).hexdigest()
            if result.get('request_fingerprint')!=fingerprint:raise ValueError('提交编号已用于其他内容，请刷新后重试')
            return result
    def post(self,table,record,body,role,label):
        if record.get('product_id'):record['product_name']=self.c.execute('SELECT name FROM products WHERE id=?',(record['product_id'],)).fetchone()[0]
        key=text(body.get('request_key'),'提交编号',100);record.update(id={'material_entries':'MT-','indirect_expenses':'EX-','byproduct_sales':'BP-'}[table]+secrets.token_hex(6).upper(),version=1,created_at=self.now(),role=role,request_fingerprint=hashlib.sha256(dump({k:v for k,v in body.items() if k not in ('_data_epoch','request_key')}).encode()).hexdigest())
        self.c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(record['id'],key,dump(record)))
        if table=='material_entries':material_ledger(self.c)
        self.audit(self.c,role,label,record['id'],None,record);return record
    def product_list(self,raw):
        if raw is None:return []
        if isinstance(raw,str):
            value=raw.strip()
            if value.startswith('['):
                try:raw=json.loads(value)
                except ValueError:raise ValueError('默认承担产品格式无效')
            else:raw=[x for x in value.split(',') if x.strip()]
        if not isinstance(raw,list):raise ValueError('默认承担产品格式无效')
        pids=sorted({str(x).strip() for x in raw if str(x).strip()})
        for pid in pids:
            if not self.c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise ValueError('默认承担产品不存在')
        return pids
    def item(self,b,role):
        erp_access.require_detail(role,'materials.catalog')
        erp_access.require_role(role,'materials.catalog');mid=b.get('id');old=self.c.execute('SELECT * FROM material_items WHERE id=?',(mid,)).fetchone() if mid else None
        if mid in ('P-LARGE','P-MEDIUM','P-SMOKED','P-KONJAC','P-LONG'):raise ValueError('周转筐已移至资产管理，请在资产台账维护')
        if mid and not old:raise ValueError('物料不存在')
        if old and old['version']!=b.get('version'):raise ValueError('物料资料已变更，请同步后重试')
        name=text(b.get('name'),'物料名称',80);cat=text(b.get('category'),'物料类别',20);unit=text(b.get('unit'),'单位',12);low=ds(qty(b.get('reorder_qty','0'),'预警数量'))
        if cat not in ('原料','辅料','耗材','包装'):raise ValueError('物料类别无效')
        pids=self.product_list(b.get('default_product_ids')) if 'default_product_ids' in b else (json.loads(old['default_product_ids'] or '[]') if old else [])
        pinned=1 if str(b.get('pinned',1 if old and old['pinned'] else 0)).lower() in ('1','true') else 0
        months=int(b.get('amortize_months') or (old['amortize_months'] if old else 1))
        if not 1<=months<=24:raise ValueError('默认摊销月数须在 1—24 之间')
        if old and b.get('active') is False and any(i['id']==mid and Decimal(i['qty'])>0 for i in material_ledger(self.c)[0]):raise ValueError('仍有库存的物料不能停用，请先处理库存')
        purchase_used=old and self.c.execute("SELECT 1 FROM sqlite_master WHERE name='purchase_orders'").fetchone() and any(l['material_id']==mid for o in rows(self.c,'purchase_orders') if o['state']!='cancelled' for l in o['lines'])
        if purchase_used and (unit!=old['unit'] or cat!=old['category']):raise ValueError('已有采购单引用的物料不能更改类别或计量单位')
        if old and (unit!=old['unit'] or cat!=old['category']):
            entries=[e for e in rows(self.c,'material_entries') if e['material_id']==mid]
            period_used=any(mid in dump(r) for r in rows(self.c,'resource_periods'))
            if any(not e.get('voided') for e in entries) or period_used:raise ValueError('已有有效流水或月结引用的物料不能更改类别或计量单位，请另建物料')
            for e in entries:
                if not e.get('unit'):
                    e['unit']=old['unit'];self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(dump(e),e['id']))
        if old:self.c.execute('UPDATE material_items SET name=?,category=?,unit=?,reorder_qty=?,active=?,default_product_ids=?,pinned=?,amortize_months=?,version=version+1 WHERE id=?',(name,cat,unit,low,0 if b.get('active') is False else 1,dump(pids),pinned,months,mid))
        else:
            mid='MAT-'+secrets.token_hex(4).upper();order=self.c.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM material_items').fetchone()[0]
            self.c.execute('INSERT INTO material_items(id,name,category,unit,reorder_qty,active,default_product_ids,pinned,sort_order,amortize_months) VALUES(?,?,?,?,?,?,?,?,?,?)',(mid,name,cat,unit,low,1,dump(pids),pinned,order,months))
        __import__('material_consumption').save_settings(self.c,mid,b)
        result={**dict(self.c.execute('SELECT * FROM material_items WHERE id=?',(mid,)).fetchone()),**__import__('material_consumption').settings(self.c,mid)};result['default_product_ids']=json.loads(result.get('default_product_ids') or '[]');self.audit(self.c,role,'维护原辅料档案',mid,dict(old) if old else None,result);return result
    def item_delete(self,b,role):
        erp_access.require_detail(role,'materials.catalog')
        erp_access.require_role(role,'materials.catalog')
        mid=text(b.get('id'),'物料编号',40)
        old=self.c.execute('SELECT * FROM material_items WHERE id=?',(mid,)).fetchone()
        if not old:raise ValueError('物料不存在或已删除')
        if old['version']!=b.get('version'):raise ValueError('物料资料已变更，请同步后重试')
        reason=text(b.get('reason'),'删除原因',500)
        if mid in {m[0] for m in MATERIALS}:raise ValueError('系统预置物料不能删除；如需停用请改“启用状态”')
        if self.c.execute("SELECT 1 FROM material_entries WHERE json_extract(payload,'$.material_id')=? LIMIT 1",(mid,)).fetchone():raise ValueError('该物料已有库存流水，不能删除；请改“停用”')
        if self.c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='purchase_orders'").fetchone() and self.c.execute("SELECT 1 FROM purchase_orders,json_each(purchase_orders.payload,'$.lines') AS line WHERE json_extract(line.value,'$.material_id')=? LIMIT 1",(mid,)).fetchone():raise ValueError('该物料已被采购单引用，不能删除；请改“停用”')
        self.c.execute('DELETE FROM material_items WHERE id=?',(mid,))
        self.audit(self.c,role,'删除原辅料档案',mid,dict(old),{'id':mid,'deleted':True,'reason':reason})
        return {'id':mid,'deleted':True}
    def item_order(self,b,role):
        erp_access.require_detail(role,'materials.catalog')
        erp_access.require_role(role,'materials.catalog')
        ids=b.get('ids') or []
        if not isinstance(ids,list) or not ids:raise ValueError('请提供物料顺序')
        ids=[str(x).strip() for x in ids if str(x).strip()]
        if len(set(ids))!=len(ids):raise ValueError('物料顺序中有重复项')
        known={r[0] for r in self.c.execute('SELECT id FROM material_items')}
        if set(ids)-known:raise ValueError('物料不存在或已删除，请刷新后重试')
        marks={str(x) for x in (b.get('pinned') or [])} if b.get('pinned') is not None else None
        current=[row[0] for row in self.c.execute('SELECT id FROM material_items ORDER BY sort_order,rowid')]
        ordered=ids+[mid for mid in current if mid not in set(ids)]
        for index,mid in enumerate(ordered,1):
            self.c.execute('UPDATE material_items SET sort_order=?,version=version+1 WHERE id=?',(index,mid))
            if marks is not None and mid in ids:self.c.execute('UPDATE material_items SET pinned=? WHERE id=?',(1 if mid in marks else 0,mid))
        self.audit(self.c,role,'调整领用顺序',','.join(ids),None,{'ids':ids,'pinned':sorted(marks) if marks is not None else None})
        return {'ids':ids}
    def workshop_count(self,b,role):
        allowed=False
        for key in ('materials.issue','materials.value'):
            try:erp_access.require_detail(role,key);allowed=True;break
            except (PermissionError,ValueError):pass
        if not allowed:raise PermissionError('无权登记车间余料盘点')
        month=text(b.get('month'),'盘点月份',7)
        try:date.fromisoformat(month+'-01')
        except Exception:raise ValueError('盘点月份无效')
        open_period(self.c,month+'-01')
        mid=text(b.get('material_id'),'物料',20)
        item=self.c.execute('SELECT * FROM material_items WHERE id=?',(mid,)).fetchone()
        if not item:raise ValueError('物料不存在或已删除')
        if mid=='RM-SOY':raise ValueError('大豆不登记车间余料，请在磨浆系统登记上豆与缸数')
        close_qty=qty(b.get('qty_close'),'盘点数量');note=text(b.get('note',''),'说明',300,False)
        row=next((r for r in workshop_report(self.c,month)['rows'] if r['material_id']==mid),None)
        if row is None:raise ValueError('该物料本月没有领用或盘点记录，无需登记')
        if row['cost_mode'] in ('issue','amortize'):raise ValueError('当前成本方式不使用盘点实耗')
        if close_qty>Decimal(row['qty_open'])+Decimal(row['qty_in']):raise ValueError('期末余料超过期初加净领用，请先核对领退料')
        if row['packaging_expected'] is not None and (Decimal(row['qty_open'])+Decimal(row['qty_in'])-close_qty)*Decimal(row['bag_units'])!=Decimal(row['packaging_expected']) and not note:raise ValueError('包材耗用与产量有差异，请填写原因')
        unit=Decimal(str(row['unit_cents'] or 0));closing=int((close_qty*unit).quantize(Decimal('1'),ROUND_HALF_UP))
        existing=self.c.execute('SELECT version FROM workshop_counts WHERE month=? AND material_id=?',(month,mid)).fetchone()
        version=int(existing[0]) if existing else 0
        if int(b.get('version') or 0)!=version:raise ValueError('车间余料盘点已变更，请刷新后重试')
        payload={'id':'WS-'+secrets.token_hex(6).upper(),'month':month,'material_id':mid,'material_name':item['name'],'unit':item['unit'],'qty_close':ds(close_qty),'closing_cents':closing,'product_ids':row['product_ids'],'valuation_method':'weighted-average','source_fingerprint':row['source_fingerprint'],'unit_cents':ds(unit.quantize(Decimal('0.01'))),'note':note,'version':version+1,'counted_at':self.now(),'role':role}
        self.c.execute('INSERT INTO workshop_counts(id,month,material_id,qty_close,note,version,payload) VALUES(?,?,?,?,?,?,?) ON CONFLICT(month,material_id) DO UPDATE SET qty_close=excluded.qty_close,note=excluded.note,version=excluded.version,payload=excluded.payload',(payload['id'],month,mid,payload['qty_close'],note,payload['version'],dump(payload)))
        self.audit(self.c,role,'登记车间余料盘点',mid+' '+month,None,payload)
        return payload
    def create_amortization(self,entry,months):
        amount=int(entry.get('cost_cents') or 0)
        if amount<=0:raise ValueError('该批次领用成本尚未确定，不能登记分期摊销')
        aid='MA-'+secrets.token_hex(6).upper()
        payload={'id':aid,'entry_id':entry['id'],'material_id':entry['material_id'],'material_name':entry['material_name'],'unit':entry['unit'],'product_ids':entry.get('product_ids') or ([entry['product_id']] if entry.get('product_id') else []),'coverage_start':entry.get('coverage_start',''),'coverage_end':entry.get('coverage_end',''),'business_date':entry['business_date'],'created_at':self.now()}
        self.c.execute('INSERT INTO material_amortizations(id,entry_id,months,start_month,closed_month,version,payload) VALUES(?,?,?,?,?,?,?)',(aid,entry['id'],months,entry['business_date'][:7],None,1,dump(payload)))
        return aid
    def amortize_close(self,b,role):
        erp_access.require_detail(role,'materials.value')
        erp_access.require_role(role,'materials.value')
        aid=text(b.get('id'),'摊销编号',40);month=text(b.get('month'),'摊销月份',7)
        row=self.c.execute('SELECT * FROM material_amortizations WHERE id=?',(aid,)).fetchone()
        if not row:raise ValueError('待摊记录不存在')
        if row['closed_month']:raise ValueError('该待摊记录已提前摊完')
        start=row['start_month'];end=month_index(start)+int(row['months'])-1
        import material_allocation as ma
        if not (ma.month_index(start)<=ma.month_index(month)<=end):raise ValueError('摊销月份须在 '+start+' 至 '+str(end)+' 之间')
        open_period(self.c,month+'-01')
        later=[r['month'] for r in rows(self.c,'resource_periods') if r['state']=='closed' and ma.month_index(r['month'])>ma.month_index(month)]
        if later:raise ValueError('后续月份 '+min(later)+' 已结账，提前摊完会改变已固化成本；请先由会计重开后续月份')
        self.c.execute('UPDATE material_amortizations SET closed_month=?,version=version+1 WHERE id=?',(month[:7],aid))
        self.audit(self.c,role,'提前摊完耗材',aid,{'closed_month':None},{'closed_month':month[:7]})
        return {'id':aid,'closed_month':month[:7]}
    def material(self,b,role,*,bean_correction=False,actual_warehouse=False):
        if bean_correction:
            if b.get('kind')!='return' or b.get('material_id')!='RM-SOY' :raise ValueError('上豆更正仅支持磨浆系统的黄豆退料')
            erp_access.require_role(role,'materials.issue')
        else:erp_access.require_role(role,'materials.issue' if b.get('kind')=='consume' and erp_access.role_can(role,'materials.issue') else 'materials.write')
        prior=self.prior('material_entries',b)
        if prior:return prior
        when=day(b.get('business_date'));open_period(self.c,when)
        if b.get('revision')!=revision(self.c):raise ValueError('库存或成本台账已变更，请同步后核对再提交')
        item=self.c.execute('SELECT * FROM material_items WHERE id=? AND active=1',(b.get('material_id'),)).fetchone()
        if not item:raise ValueError('请选择有效物料')
        wid=warehouse(item,b.get('warehouse_id'),c=self.c,when=when);department=purpose(item,wid,b.get('department'));system_id='';system_name='';config=pc.get(self.c,when)
        kind=b.get('kind')
        if item['id']=='RM-SOY' and kind in ('consume','return'):
            system_id=b.get('production_system_id')
            if system_id is None and config['version']==0:system_id=pc.LEGACY_SOURCES.get(wid)
            system=next((s for s in pc.active_systems(config) if s['id']==system_id),None)
            # Registration records the warehouse actually used. Other issue routes keep
            # the configured allowed warehouses; 上豆登记 may span several soybean stores.
            if not system or (not actual_warehouse and wid not in system['warehouse_ids']):raise ValueError('请选择磨浆系统及其允许领用库房；储存库请先调入允许库房')
            system_name=system['name']
            if config['version']==0 and b.get('production_system_id') is None and b.get('department') not in (None,'',department):raise ValueError('旧入口仅支持豆腐线、豆皮线，请重新打开并选择磨浆系统')
            if b.get('production_system_id') is not None or config['version']>0:department=system_name
        if kind not in ('opening','receipt','consume','return','loss','count','transfer'):raise ValueError('库存业务类型无效')
        all_entries=rows(self.c,'material_entries')
        # 同一库房可存多批、多品种、多产地的大豆，期初必须能按批次分别登记，
        # 不再限制“一个库房只能录一次期初”。重复提交仍由 request_key 幂等拦截。
        if kind=='count':
            _,_,current=material_ledger(self.c,until=when,warehouse_details=True);s=next((r for r in current if r['id']==item['id'] and r['warehouse_id']==wid),{'qty':'0'})
            if any(e['material_id']==item['id'] and (entry_warehouse(e)==wid or e.get('target_warehouse_id')==wid) and e['business_date']>when and not e.get('voided') for e in all_entries):raise ValueError('盘点不能早于该物料已有的后续流水')
            delta=qty(b.get('qty'),'实盘数量')-Decimal(s['qty'])
            if delta==0:raise ValueError('实盘与账面一致，无需登记差异')
            q=abs(delta);kind='gain' if delta>0 else 'loss'
        else:q=qty(b.get('qty'),positive=True)
        amount=cents(b.get('amount','0')) if kind in ('opening','receipt','return','gain') else 0
        automatic_value=False
        if kind in ('return','gain') and amount<=0:
            # New entries follow existing entries on the same business day. Future
            # receipts/issues must not change the price of a backdated return.
            _,_,balances=material_ledger(self.c,until=when,warehouse_details=True)
            balance=next((x for x in balances if x['id']==item['id'] and x['warehouse_id']==wid),None)
            price=Decimal(balance['value_cents'])/Decimal(balance['qty']) if balance and Decimal(balance['qty'])>0 and balance['value_cents']>0 else None
            if price is None:
                prior_prices=[e for e in all_entries if not e.get('voided') and e['material_id']==item['id'] and e['kind'] in ('opening','receipt','return','gain') and e.get('amount_cents',0)>0 and e['business_date']<=when]
                last=max(prior_prices,key=lambda e:(e['business_date'],e['sequence'])) if prior_prices else None
                if last:price=Decimal(last['amount_cents'])/Decimal(last['qty'])
            if price is not None:amount=max(1,int((price*q).quantize(Decimal(1),rounding=ROUND_HALF_UP)));automatic_value=True
        if kind in ('opening','receipt','return','gain') and amount<=0:raise ValueError('入库必须有金额，请填写入库总金额，或通过已有价格的采购验收入库')
        if amount and not automatic_value:erp_access.require_role(role,'materials.value')
        if role=='厂长' and kind!='consume' and not bean_correction:raise ValueError('厂长在此仅登记生产领用，入库与调拨请交库管')
        latest=self.c.execute('SELECT MAX(month) FROM resource_periods WHERE json_extract(payload,\'$.state\')=\'closed\'').fetchone()[0]
        if latest and when[:7]<=latest:raise ValueError('不能在已结账历史期间之前追加库存流水')
        marker=self.c.execute("SELECT value FROM meta WHERE key='material_fifo_start'").fetchone()
        if marker and any(e['sequence']<int(marker[0]) and e['business_date']>when for e in all_entries):raise ValueError('新增FIFO流水不能早于历史计价流水，请先核对日期')
        record={'business_date':when,'material_id':item['id'],'material_name':item['name'],'unit':item['unit'],'kind':kind,'qty':ds(q),'amount_cents':amount,'product_id':self.product(b.get('product_id')),'warehouse_id':wid,'warehouse_name':warehouse_names(self.c).get(wid,wid),'department':department,'partner':text(b.get('partner',''),'供应商/交接人',100,False),'reference':text(b.get('reference',''),'凭据/批号',100,False),'note':text(b.get('note'),'用途/盘点原因',500),'handler':text(b.get('handler'),'经办人',80),'sequence':len(all_entries)+1}
        record.update(production_system_id=system_id or '',production_system_name=system_name,production_config_version=config['version'])
        record['cost_target']=text((system_name or '共用' if item['id']=='RM-SOY' else b.get('cost_target') or attribution(item)['default_cost_target']),'成本对象',80)
        pids=[]
        if item['id']!='RM-SOY' and kind in ('consume','return','loss'):
            raw=b.get('product_ids') or []
            if isinstance(raw,str):raw=[x for x in raw.split(',') if x.strip()]
            pids=sorted({str(x).strip() for x in raw if str(x).strip()})
            for pid in pids:
                if not self.c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise ValueError('承担产品不存在')
            if pids:
                start=day(b.get('coverage_start') or when);end=day(b.get('coverage_end') or when)
                if end<start:raise ValueError('覆盖期结束日期不能早于开始日期')
                if start[:7]!=when[:7] or end[:7]!=when[:7]:raise ValueError('领用覆盖期须与业务日期在同一个月；跨月请分月登记')
                record.update(product_ids=pids,coverage_start=start,coverage_end=end,allocation_basis='coverage-bean')
                if len(pids)==1:record['product_id']=pids[0]
                else:record['product_id']='';record['cost_target']='共用'
        if item['id']=='RM-SOY':record['product_id']=''
        if item['id']!='RM-SOY' and 'material_attribution' not in b and not record['product_id'] and record['cost_target'] not in ('共用','豆腐'):
            match=self.c.execute('SELECT id FROM products WHERE name=?',(record['cost_target'],)).fetchone()
            if match:record['product_id']=match[0]
        if item['id']=='RM-SOY' and kind in ('opening','receipt','return','gain'):record['quality']=quality(b,soy_origins(self.c))
        if b.get('source_lot_id'):
            if item['id']!='RM-SOY' or kind!='consume':raise ValueError('指定批次仅用于大豆生产领用')
            lot_id=text(b['source_lot_id'],'上豆批次',100)
            stocks=material_ledger(self.c,until=when,warehouse_details=True)[2]
            fragments=[l for w in stocks if w['id']=='RM-SOY' and w['warehouse_id']==wid for l in w['lots'] if l['lot_id']==lot_id]
            lot=fragments[0] if fragments else None
            if not lot or sum((Decimal(l['qty']) for l in fragments),Decimal(0))<q:raise ValueError('所选批次余额不足或不属于该库房 / 日期')
            record.update(source_lot_id=lot_id,source_quality=lot.get('quality',{}))
        if kind=='transfer':
            target=warehouse(item,b.get('target_warehouse_id'),c=self.c,when=when)
            if target==wid:raise ValueError('调出与调入库房不能相同')
            record.update(target_warehouse_id=target,target_warehouse_name=warehouse_names(self.c).get(target,target))
        cost_profile=__import__('material_consumption').settings(self.c,item['id'],when[:7])
        amortize_months=1
        if cost_profile['cost_mode']=='count' and int(b.get('amortize_months') or 1)>1:raise ValueError('盘点实耗物料不能同时分期摊销')
        if cost_profile['cost_mode']=='issue' and int(b.get('amortize_months') or 1)>1:raise ValueError('领用即耗物料不能同时分期摊销')
        if cost_profile['cost_mode']=='amortize' and kind=='consume' and int(b.get('amortize_months') or 1)<2:raise ValueError('跨月摊销物料请登记至少2个月摊销')
        if item['id']!='RM-SOY' and kind=='consume' and str(b.get('amortize_months') or '1') not in ('','1'):
            amortize_months=int(b.get('amortize_months'))
            if not 2<=amortize_months<=24:raise ValueError('摊销月数须在 2—24 之间')
            if item['category'] not in ('辅料','耗材','包装'):raise ValueError('仅辅料、耗材与包装可分期摊销')
            record['amortize_months']=amortize_months
        result=self.post('material_entries',record,b,role,'登记原辅料库存流水')
        if amortize_months>1:
            entry=next((e for e in material_ledger(self.c)[1] if e['id']==result['id']),None)
            if not entry:raise ValueError('领用成本尚未生成，请刷新后重试')
            self.create_amortization(entry,amortize_months)
        return result
    def material_batch(self,b,role):
        lines=b.get('lines') or []
        if not isinstance(lines,list) or not lines or len(lines)>50:raise ValueError('批量领用须为 1—50 行')
        key=text(b.get('request_key'),'提交编号',100);results=[]
        for index,line in enumerate(lines):
            if not isinstance(line,dict):raise ValueError('第 '+str(index+1)+' 行格式无效')
            merged={k:v for k,v in b.items() if k not in ('lines','request_key','revision')}
            merged.update(line);merged['request_key']=key+':'+str(index);merged['revision']=revision(self.c)
            results.append(self.material(merged,role))
        return {'count':len(results),'results':results}
    def value(self,b,role):
        erp_access.require_role(role,'materials.value');r=self.c.execute('SELECT payload FROM material_entries WHERE id=?',(b.get('id'),)).fetchone()
        if not r:raise ValueError('库存流水不存在')
        old=json.loads(r[0])
        if old.get('purchase_receipt_id'):raise ValueError('采购关联入库金额由采购单确定，不能在库存台账单独改价')
        open_period(self.c,old['business_date'])
        if old.get('voided') or old['kind'] not in ('opening','receipt','return','gain') or old['version']!=b.get('version'):raise ValueError('仅有效入库记录可以补录金额，请核对版本')
        if any(json.loads(r[0])['state']=='closed' and r[1]>=old['business_date'][:7] for r in self.c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('后续月份已结账，不能修改影响历史成本的入库金额')
        amount=cents(b.get('amount'),positive=True);reason=text(b.get('note'),'补价说明',500)
        record={**old,'amount_cents':amount,'version':old['version']+1};record.setdefault('valuation_history',[]).append({'prior_cents':old['amount_cents'],'amount_cents':amount,'reason':reason,'at':self.now(),'role':role})
        self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(dump(record),record['id']));material_ledger(self.c);self.audit(self.c,role,'补录原辅料入库金额',record['id'],old,record);return record
    def attribute(self,b,role):
        erp_access.require_role(role,'materials.value')
        row=self.c.execute('SELECT payload FROM material_entries WHERE id=?',(b.get('id'),)).fetchone()
        if not row:raise ValueError('库存流水不存在，请重新读取后核对')
        old=json.loads(row[0]);open_period(self.c,old['business_date'])
        if old.get('voided') or old['kind'] not in ('consume','return','loss'):raise ValueError('仅有效领用、退料或报损流水可更正归集')
        if type(b.get('version')) is not int or old['version']!=b['version'] or b.get('revision')!=revision(self.c):raise ValueError('库存或归集记录已更新，请重新读取后核对；本次未提交')
        if old['material_id']=='RM-SOY':raise ValueError('大豆按实际领用库房和当天供浆登记分摊，请到每日生产更正供浆来源与缸数')
        if any(json.loads(r[0])['state']=='closed' and r[1]>=old['business_date'][:7] for r in self.c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('后续月份已结账，请先重开相关月份再更正归集')
        reason=text(b.get('note'),'归集更正原因',500);pid=self.product(b.get('product_id'))
        raw=b.get('product_ids')
        if raw is None:pids=[pid] if pid else []
        else:
            if isinstance(raw,str):raw=[x for x in raw.split(',') if x.strip()]
            pids=sorted({str(x).strip() for x in raw if str(x).strip()})
            for item_pid in pids:
                if not self.c.execute('SELECT 1 FROM products WHERE id=?',(item_pid,)).fetchone():raise ValueError('承担产品不存在')
        target=text(b.get('cost_target') or '共用','成本归属',80)
        if target not in ('共用','豆腐','豆皮','素鸡','配送'):raise ValueError('共用成本归属无效，请重新选择')
        record={**old,'product_id':pids[0] if len(pids)==1 else '','cost_target':target,'department':{'豆腐':'豆腐线','豆皮':'豆皮线','素鸡':'素鸡线','配送':'配送'}.get(target,'共用'),'version':old['version']+1}
        if pids:
            start=day(b.get('coverage_start') or old.get('coverage_start') or old['business_date']);end=day(b.get('coverage_end') or old.get('coverage_end') or old['business_date'])
            if end<start:raise ValueError('覆盖期结束日期不能早于开始日期')
            if start[:7]!=old['business_date'][:7] or end[:7]!=old['business_date'][:7]:raise ValueError('领用覆盖期须与业务日期在同一个月；跨月请分月登记')
            record.update(product_ids=pids,coverage_start=start,coverage_end=end,allocation_basis='coverage-bean')
            if len(pids)>1:record['cost_target']='共用';record['department']='共用'
        else:
            for key in ('product_ids','coverage_start','coverage_end','allocation_basis'):record.pop(key,None)
        record['attribution_history']=list(old.get('attribution_history',[]))
        record['attribution_history'].append({'before':{k:old.get(k,'') for k in ('product_id','product_ids','cost_target','department','coverage_start','coverage_end')},'after':{k:record.get(k,'') for k in ('product_id','product_ids','cost_target','department','coverage_start','coverage_end')},'reason':reason,'at':self.now(),'role':role})
        self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(dump(record),record['id']))
        self.audit(self.c,role,'更正材料成本归集',record['id'],old,record);return record
    def quality(self,b,role):
        erp_access.require_role(role,'materials.value')
        row=self.c.execute('SELECT payload FROM material_entries WHERE id=?',(b.get('id'),)).fetchone()
        if not row:raise ValueError('大豆入库批次不存在')
        old=json.loads(row[0])
        if old.get('voided') or old['material_id']!='RM-SOY' or old['kind'] not in ('opening','receipt','return','gain'):raise ValueError('仅有效大豆入库批次可补录属性')
        if old['version']!=b.get('version') or b.get('revision')!=revision(self.c):raise ValueError('批次已变更，请刷新后重试')
        reason=text(b.get('note'),'属性修改说明',300)
        allowed=list(soy_origins(self.c));old_origin=(old.get('quality') or {}).get('origin')
        if old_origin and old_origin not in allowed:allowed.append(old_origin)
        record={**old,'quality':quality(b,allowed),'version':old['version']+1}
        record.setdefault('quality_history',[]).append({'before':old.get('quality',{}),'after':record['quality'],'note':reason,'at':self.now(),'role':role})
        self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(dump(record),record['id']))
        self.audit(self.c,role,'补录大豆批次属性',record['id'],old,record)
        return record
    def origin_options(self,b,role):
        erp_access.require_role(role,'materials.value')
        raw=b.get('origins')
        if not isinstance(raw,list):raise ValueError('产地选项格式无效')
        values=[]
        for value in raw:
            name=text(value,'大豆产地',20,False)
            if name and name not in values:values.append(name)
        if not values:raise ValueError('至少保留一个产地选项')
        if len(values)>20:raise ValueError('产地选项最多20个')
        before=soy_origins(self.c)
        if values==before:return {'origins':before}
        self.c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(SOY_ORIGIN_META,dump(values)))
        self.audit(self.c,role,'修改大豆产地选项',SOY_ORIGIN_META,{'origins':before},{'origins':values})
        return {'origins':values}
    def expense(self,b,role,_validate_only=False,_existing=None,_system_source=None,_estimate=False,_closing=False):
        erp_access.require_role(role,'costs.close' if _closing else 'costs.write');prior=None if _validate_only else self.prior('indirect_expenses',b)
        if prior:return prior
        when=day(b.get('business_date'))
        import expense_coverage
        if _existing and _existing.get('accrual_method')=='service_days' and 'accrual_method' not in b:raise ValueError('此费用按抄表区间归属，请更新页面后保留原覆盖区间再更正')
        if _existing and _existing.get('estimate_ids') and b.get('accrual_method')!='service_days':raise ValueError('此账单已核销暂估，更正须保留覆盖日期区间；如需撤回请走作废流程')
        coverage=expense_coverage.plan(b,cents(b.get('amount'),positive=not _closing));period=coverage['period']
        import cost_allocation as ca
        category=next((r for r in ca.categories(self.c) if r['id']==b.get('category')),None)
        if category is None:raise ValueError('成本项目不存在或已删除')
        desired=b.get('irregular_periodic',bool(category.get('irregular_periodic')))
        if not isinstance(desired,bool):raise ValueError('不定期费用属性无效')
        change=None
        if desired!=bool(category.get('irregular_periodic')):
            if b.get('irregular_category_version')!=category['version']:raise ValueError('费用项目属性已变化，请刷新后核对')
            if desired and category['payment_mode']!='payable':raise ValueError('只有普通账单项目可设为不定期费用')
            change={'id':category['id'],'version':category['version'],'irregular_periodic':desired}
            category={**category,'irregular_periodic':desired}
        if desired and b.get('accrual_method')!='service_days' and not (_existing and _existing.get('accrual_method')!='service_days'):raise ValueError('不定期费用须填写详细核算日期区间')
        if category.get('system_managed'):
            if _system_source!=category.get('system_source'):raise ValueError('外包配送费由运输月结按实际趟次自动生成，请在车辆排班 → 运输月结办理，不能手工重复登记')
        elif _system_source:raise ValueError('此成本项目不接受系统自动归集')
        elif category.get('retired'):raise ValueError('配送工资已停用，仅保留历史计薪和历史费用；新增请使用生产或管理工资')
        elif not category.get('active'):raise ValueError('成本项目已停用，请先启用或选择其他项目')
        if _existing and _existing['category']==category['id']:
            mode=_existing.get('payment_mode',_existing.get('category_snapshot',{}).get('payment_mode',category['payment_mode']))
            import expense_parties
            category={**category,'payment_mode':mode,'counterparty_kind':_existing.get('counterparty_kind') or _existing.get('category_snapshot',{}).get('counterparty_kind') or expense_parties.kind_for(category['id'],mode)}
        record={'business_date':when,'period':period,'category':b['category'],'amount_cents':cents(b.get('amount'),positive=not _closing),'department':text(b.get('department','共用'),'费用归属',40),'product_id':self.product(b.get('product_id')),'partner':text(b.get('partner',''),'费用对象',100,False),'reference':text(b.get('reference',''),'凭据号',100,False),'note':text(b.get('note'),'费用说明',500),'handler':text(b.get('handler'),'经办人',80)}
        record['category_snapshot']=category
        if _system_source:
            record['system_source']=_system_source
            record['system_source_label']=category.get('system_source_label','')
            record['source_document_id']=text(b.get('source_document_id',''),'系统来源单号',100,False)
        record['payment_mode']=category['payment_mode']
        record['product_ids']=ca.product_ids(self.c,b.get('product_ids',([record['product_id']] if record['product_id'] else category.get('product_ids',[]))))
        if record['product_ids']:
            record['product_id']=record['product_ids'][0] if len(record['product_ids'])==1 else ''
        record['allocation_rule']=ca.RULE
        schedule=coverage['accruals']
        record.update(coverage)

        supplier_id=text(b.get('supplier_id',''),'供应商编号',100,False)
        if supplier_id:
            supplier=self.c.execute('SELECT payload FROM suppliers WHERE id=?',(supplier_id,)).fetchone()
            if not supplier or not json.loads(supplier[0]).get('active',True):raise ValueError('请选择有效供应商')
            record.update(supplier_id=supplier_id,partner=json.loads(supplier[0])['name'])
        record['cost_target']='冻豆腐' if b['category']=='cold-power' else text(b.get('cost_target') or '共用','成本对象',80)
        if b['category']=='cold-power' and not record['product_ids']:
            match=self.c.execute("SELECT id FROM products WHERE name='冻豆腐'").fetchone();record['product_id']=match[0] if match else ''
            record['product_ids']=[match[0]] if match else []
        if any(e.get('payroll_sheet_id') and e['category']==record['category'] for part in schedule for e in period_expenses(self.c,part['period'])):raise ValueError('该月份工资已由工资表自动计入成本，请在员工工资更正，不能重复手工登记')
        import expense_parties
        expense_parties.apply(self.c,b,record,category)
        if not _estimate:
            __import__('expense_estimates').validate_actual(self.c,{**b,'id':(_existing or {}).get('id','')},record)
        for part in record['accruals']:
            if part['period'] not in record.get('closed_recognition_months',[]):open_period(self.c,part['period']+'-01')
        if change:record['_irregular_category_update']=change
        if _validate_only:return record
        ca.apply_expense_category_change(self.c,record,role,self.now,self.audit)
        return self.post('indirect_expenses',record,b,role,'登记期间成本')
    def expense_estimate(self,b,role):
        return __import__('expense_estimates').save(self.c,b,role,self.now,self.audit)
    def expense_counterparty(self,b,role):
        import expense_parties
        return expense_parties.save(self.c,b,role,self.now,self.audit)
    def expense_category(self,b,role):
        import cost_allocation
        return cost_allocation.save_category(self.c,b,role,self.now,self.audit)
    def expense_category_delete(self,b,role):
        import cost_allocation
        return cost_allocation.delete_category(self.c,b,role,self.now,self.audit)
    def expense_edit(self,b,role):
        erp_access.require_role(role,'costs.write')
        old=next((r for r in expense_projection(self.c) if r['id']==b.get('id')),None)
        if not old or old.get('voided'):raise ValueError('费用不存在或已作废')
        if old.get('payroll_sheet_id'):raise ValueError('工资成本由工资表维护，请到员工工资撤回并重新核算')
        if old.get('system_source') or old.get('source')=='transport-settlement':raise ValueError('运输月结自动生成的费用不能手工改写；请在运输月结核对结算单，付款按原单登记')
        if b.get('version')!=old['version']:raise ValueError('费用已更新，请刷新')
        expense_open_periods(self.c,old)
        if old['paid_cents']:raise ValueError('费用已有付款，不能改写；请保留原付款记录')
        if b.get('counterparty_id')=='legacy:'+old['id'] and not old.get('counterparty_id') and old.get('partner'):
            b={**b,'counterparty_id':'','counterparty_mode':'legacy-preserved','partner':old['partner'],'supplier_id':old.get('supplier_id','')}
        # Validate before replacing the original; keep one identity and audit.
        text(b.get('request_key'),'提交编号',100)
        original=json.loads(self.c.execute('SELECT payload FROM indirect_expenses WHERE id=?',(old['id'],)).fetchone()[0])
        created=self.expense(b,role,_validate_only=True,_existing=original)
        if original['category']==created['category']:
            created['payment_mode']=original.get('payment_mode',original.get('category_snapshot',{}).get('payment_mode',created['payment_mode']))
            created['category_snapshot']={**created['category_snapshot'],'payment_mode':created['payment_mode']}
        __import__('cost_allocation').apply_expense_category_change(self.c,created,role,self.now,self.audit)
        updated={**created,'id':old['id'],'version':old['version']+1,'created_at':original.get('created_at',created.get('created_at')),'updated_at':self.now(),'review_reset_version':old['version']+1}
        self.c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(dump(updated),old['id']))
        self.audit(self.c,role,'更正间接成本并重新核对',old['id'],original,updated)
        return updated
    def expense_record(self,b):
        old=next((e for e in expense_projection(self.c) if e['id']==b.get('id')),None)
        if not old:raise ValueError('费用记录不存在，请重新读取后核对')
        if type(b.get('version')) is not int or old['version']!=b['version']:raise ValueError('费用记录已被更新，请重新读取后核对；本次未提交')
        if old.get('voided'):raise ValueError('费用已作废，不能核对或付款')
        if not old['payment_required']:raise ValueError('工资请在工资系统发放，折旧不产生付款账款')
        return old
    def expense_event(self,table,record,b,role,label,old):
        key=text(b.get('request_key'),'提交编号',100)
        record.update(id=('ER-' if table=='expense_reviews' else 'EP-')+secrets.token_hex(6).upper(),expense_id=old['id'],expense_version=old['version'],created_at=self.now(),role=role,request_fingerprint=hashlib.sha256(dump({k:v for k,v in b.items() if k not in ('_data_epoch','request_key')}).encode()).hexdigest())
        self.c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(record['id'],key,dump(record)))
        original=json.loads(self.c.execute('SELECT payload FROM indirect_expenses WHERE id=?',(old['id'],)).fetchone()[0])
        self.c.execute('UPDATE indirect_expenses SET payload=? WHERE id=?',(dump({**original,'version':original['version']+1}),old['id']))
        self.audit(self.c,role,label,old['id'],old,record);return record
    def expense_review(self,b,role):
        erp_access.require_role(role,'costs.review');prior=self.prior('expense_reviews',b)
        if prior:return prior
        old=self.expense_record(b)
        if old['paid_cents']:raise ValueError('费用已有付款，不能再次核对或退回；请保留原付款记录')
        if old['payment_state'] not in ('pending','returned'):raise ValueError('费用已核对，请在待付款中登记付款')
        decision=b.get('decision')
        if decision not in ('approve','return'):raise ValueError('请选择核对通过或退回会计')
        if decision=='approve' and not old.get('partner','').strip():raise ValueError('请先由会计补齐实际费用收款方，再重新核对；工资和非现金成本不走此付款流程')
        if decision=='approve' and b.get('evidence_checked') is not True:raise ValueError('请先核对费用金额、收款方与原始凭据，并勾选确认')
        note=text(b.get('note',''),'核对说明 / 退回原因',500,decision=='return')
        return self.expense_event('expense_reviews',{'decision':decision,'note':note,'handler':text(b.get('handler'),'核对经办人',80)},b,role,'费用核对通过' if decision=='approve' else '费用退回会计',old)
    def expense_payment(self,b,role):
        erp_access.require_role(role,'costs.pay');prior=self.prior('expense_payments',b)
        if prior:return prior
        old=self.expense_record(b)
        if not old['review'] or old['review']['decision']!='approve':raise ValueError('费用尚未核对通过，请先由出纳核对原始凭据')
        if not old.get('partner','').strip():raise ValueError('原费用缺收款方，请先补齐并重新核对')
        if (old.get('counterparty_id') or old.get('counterparty_from_payment')) and b.get('payee')!=old['partner']:raise ValueError('付款收款方与已核对费用不一致，请退回会计更正后重新核对')
        when=day(b.get('business_date'));open_period(self.c,when)
        if when<old['business_date']:raise ValueError('付款日期不能早于费用登记日期，请核对付款日期')
        value=cents(b.get('amount'),'付款金额',positive=True)
        if value>old['outstanding_cents']:raise ValueError('付款金额超过未付余额，请重新读取并核对金额')
        method=b.get('method')
        if method not in ('银行转账','现金','微信','支付宝','其他'):raise ValueError('请选择付款方式')
        record={'counterparty_id':old.get('counterparty_id',''),'supplier_id':old.get('supplier_id',''),'account_id':fund_account(self.c,b),'business_date':when,'amount_cents':value,'method':method,'payee':text(b.get('payee'),'收款方',100),'handler':text(b.get('handler'),'付款经办人',80),'reference':text(b.get('reference',''),'付款凭据',100,False),'note':text(b.get('note'),'付款说明',500)}
        return self.expense_event('expense_payments',record,b,role,'登记间接成本付款',old)
    def byproduct(self,b,role):
        if cents(b.get('received') or '0'):erp_access.require_detail(role,'byproducts.receive')
        erp_access.require_role(role,'byproducts.write');prior=self.prior('byproduct_sales',b)
        if prior:return prior
        import byproduct_accounts as ba
        client=ba.sale_customer(self.c,b.get('customer_id'))
        when=day(b.get('business_date'));open_period(self.c,when);q=qty(b.get('qty'),positive=True);unit=b.get('unit','公斤')
        if unit not in ('公斤','吨'):raise ValueError('豆渣计量单位无效')
        price=qty(b.get('price'),'单价');amount=int((q*price*100).quantize(Decimal(1),rounding=ROUND_HALF_UP));received=cents(b.get('received','0'),'已收金额')
        if amount<=0 or received>amount:raise ValueError('请核对豆渣销售金额及已收金额')
        record={'account_id':fund_account(self.c,b),'business_date':when,'customer_id':client['id'],'qty':ds(q),'unit':unit,'price':ds(price),'amount_cents':amount,'received_cents':received,'buyer':client['name'],'reference':text(b.get('reference',''),'凭据号',100,False),'note':text(b.get('note',''),'备注',500,False),'handler':text(b.get('handler'),'经办人',80)}
        return self.post('byproduct_sales',record,b,role,'登记豆渣收入')
    def receive_byproduct(self,b,role):
        erp_access.require_role(role,'byproducts.receive');r=self.c.execute('SELECT payload FROM byproduct_sales WHERE id=?',(b.get('id'),)).fetchone()
        if not r:raise ValueError('豆渣销售不存在')
        old=json.loads(r[0]);received_day=day(b.get('business_date'));open_period(self.c,received_day)
        if received_day<old['business_date']:raise ValueError('到账日期不能早于豆渣销售日期')
        if old.get('voided') or old['version']!=b.get('version'):raise ValueError('单据已变更或作废')
        amount=cents(b.get('amount'),positive=True)
        if amount>old['amount_cents']-old['received_cents']:raise ValueError('收款超过豆渣未收余额')
        record={**old,'version':old['version']+1,'received_cents':old['received_cents']+amount};record.setdefault('receipts',[]).append({'account_id':fund_account(self.c,b),'business_date':day(b.get('business_date')),'amount_cents':amount,'note':text(b.get('note'),'到账说明',500),'at':self.now(),'role':role})
        self.c.execute('UPDATE byproduct_sales SET payload=? WHERE id=?',(dump(record),record['id']));self.audit(self.c,role,'登记豆渣收款',record['id'],old,record);return record
    def void(self,b,role):
        kind=b.get('ledger');table=TABLES.get(kind)
        if not table:raise ValueError('台账类型无效')
        erp_access.require_role(role,{'material':'materials.void','expense':'costs.void','byproduct':'byproducts.void'}[kind]);r=self.c.execute('SELECT payload FROM '+table+' WHERE id=?',(b.get('id'),)).fetchone()
        if not r:raise ValueError('单据不存在')
        old=json.loads(r[0])
        if old.get('payroll_sheet_id'):raise ValueError('工资成本由工资表同步维护，请在员工工资操作')
        if old.get('system_source') or old.get('source')=='transport-settlement':raise ValueError('运输月结自动生成的费用不能单独作废；请保留结算单与应付，付款按原单登记')
        if old.get('purchase_receipt_id'):raise ValueError('采购关联入库须保留与采购应付的对应关系，不能在库存台账单独作废')
        if kind=='expense':expense_open_periods(self.c,old)
        else:open_period(self.c,old.get('period',old['business_date'][:7])+'-01')
        if old.get('voided') or old['version']!=b.get('version'):raise ValueError('单据已作废或已变更，请同步后重试')
        if kind=='material' and any(json.loads(r[0])['state']=='closed' and r[1]>=old['business_date'][:7] for r in self.c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('后续月份已结账，不能作废影响已结账库存成本的流水')
        if kind=='material' and old.get('amount_cents'):erp_access.require_role(role,'materials.value')
        if kind=='byproduct' and old['received_cents']:raise ValueError('已有到账的豆渣收入不能作废，请保留原单')
        if kind=='expense' and any(p['expense_id']==old['id'] for p in rows(self.c,'expense_payments')):raise ValueError('费用已有付款，不能作废；请保留原单及付款记录')
        record={**old,'voided':True,'void_reason':text(b.get('reason'),'作废原因',500),'voided_at':self.now(),'version':old['version']+1}
        if kind=='byproduct':record['last_void_version']=record['version']
        self.c.execute('UPDATE '+table+' SET payload=? WHERE id=?',(dump(record),old['id']))
        if kind=='material':material_ledger(self.c)
        self.audit(self.c,role,'作废'+{'material':'原辅料流水','expense':'成本记录','byproduct':'豆渣收入'}[kind],old['id'],old,record);return record
    def restore(self,b,role):
        kind=b.get('ledger');table=TABLES.get(kind)
        if not table:raise ValueError('台账类型无效')
        erp_access.require_role(role,{'material':'materials.void','expense':'costs.void','byproduct':'byproducts.void'}[kind]);r=self.c.execute('SELECT payload FROM '+table+' WHERE id=?',(b.get('id'),)).fetchone()
        if not r:raise ValueError('单据不存在')
        old=json.loads(r[0])
        if old.get('payroll_sheet_id'):raise ValueError('工资成本由工资表同步维护，请在员工工资操作')
        if old.get('system_source') or old.get('source')=='transport-settlement':raise ValueError('运输月结自动生成的费用不能手工恢复；请核对运输结算单和付款记录')
        if not old.get('voided'):raise ValueError('该记录未作废，无需恢复')
        if old.get('purchase_receipt_id'):raise ValueError('采购关联入库不能单独恢复，请通过采购验收处理')
        if kind=='expense':expense_open_periods(self.c,old)
        else:open_period(self.c,old.get('period',old['business_date'][:7])+'-01')
        if old['version']!=b.get('version'):raise ValueError('单据已变化，请同步后重试')
        if kind=='material' and any(json.loads(r[0])['state']=='closed' and r[1]>=old['business_date'][:7] for r in self.c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('后续月份已结账，不能恢复影响已结账库存成本的流水')
        if kind=='material' and old.get('amount_cents'):erp_access.require_role(role,'materials.value')
        if kind=='byproduct' and old.get('received_cents'):raise ValueError('该豆渣销售已有到账，不能恢复')
        if kind=='byproduct' and old.get('source')=='daily-settlement' and any(not r.get('voided') and r.get('source')=='daily-settlement' and r.get('period')==old.get('period') for r in rows(self.c,'byproduct_sales')):raise ValueError('该月份已有有效豆渣收入，不能重复恢复')
        if kind=='expense' and any(p['expense_id']==old['id'] for p in rows(self.c,'expense_payments')):raise ValueError('该费用已有付款，不能恢复')
        stamp=self.now();reason=text(b.get('reason'),'恢复原因',500)
        record={**old,'voided':False,'restored_at':stamp,'restore_reason':reason,'version':old['version']+1}
        if kind=='expense':__import__('expense_estimates').validate_restore(self.c,record,old['id'])
        record['restore_history']=list(old.get('restore_history',[]));record['restore_history'].append({'at':stamp,'reason':reason,'role':role,'prior_void_reason':old.get('void_reason','')})
        self.c.execute('UPDATE '+table+' SET payload=? WHERE id=?',(dump(record),old['id']))
        if kind=='material':material_ledger(self.c)
        self.audit(self.c,role,'恢复'+{'material':'原辅料流水','expense':'成本记录','byproduct':'豆渣收入'}[kind],old['id'],old,record);return record
    def period(self,b,role):
        erp_access.require_role(role,'costs.close');month=b.get('month');day(month+'-01');old=self.c.execute('SELECT * FROM resource_periods WHERE month=?',(month,)).fetchone()
        if b.get('version')!=(old['version'] if old else 0):raise ValueError('月份状态已变化，请同步后重试')
        state=b.get('state')
        if state not in ('closed','open'):raise ValueError('月份状态无效')
        if old and json.loads(old['payload'])['state']==state:
            return {k:v for k,v in json.loads(old['payload']).items() if k!='report_snapshot'}
        if state=='closed' and any(not e.get('voided') and e['business_date'][:7]<=month and e['kind'] in ('opening','receipt','return','gain') and not e['amount_cents'] for e in rows(self.c,'material_entries')):raise ValueError('尚有未计价入库，请补录金额后再结账')
        if state=='closed':
            issues=__import__('material_consumption').closing_issues(self.c,month)
            if issues:raise ValueError('；'.join(issues[:5]))
            import finished_goods
            if any(not r.get('voided') and not r.get('return_of') and r['business_date'][:7]<=month and (r.get('pricing_pending') or r.get('pricing_status')=='recalculate') for r in finished_goods.records(self.c,'receipt')):raise ValueError('尚有外购成品订单未确认算票或待重算，请先在会计算票完成后结账')
        record={'month':month,'state':state,'version':(old['version'] if old else 0)+1,'note':text(b.get('note'),'结账/重开说明',500),'at':self.now(),'role':role}
        # The report must see the closing period, without a previous snapshot.
        # A savepoint also protects callers that catch an error inside a transaction.
        self.c.execute('SAVEPOINT erp_cost_period_change')
        try:
            later=[r[0] for r in self.c.execute("SELECT month FROM resource_periods WHERE month>? AND json_extract(payload,'$.state')='closed' ORDER BY month",(month,))]
            if later:raise ValueError('后续月份已结账（'+'、'.join(later)+'），请按倒序先处理后续月份，再操作'+month)
            if state=='open':
                import inventory_valuation
                frozen=inventory_valuation._frozen(self.c)
                if month in frozen:
                    frozen.pop(month)
                    inventory_valuation._write_frozen(self.c,frozen)
                    record['freeze_rolled_back']=True
            if state=='closed':
                import inventory_valuation
                inventory_valuation.check_close(self.c,month,self.now())
                completion=__import__('expense_close').apply(self.c,b,role,self.now,self.audit)
                record['cost_coverage_review']=completion['review'];record['automatic_estimate_ids']=completion['estimate_ids'];record['confirmed_estimates']=completion['confirmed_estimates']
                import cost_allocation as ca
                record['allocation_rule']=ca.RULE
                record['intensity_snapshot']={r['id']:ds(ca.factor(self.c,r['id'],month)) for r in self.c.execute('SELECT id FROM products')}
            self.c.execute('INSERT INTO resource_periods VALUES(?,?,?) ON CONFLICT(month) DO UPDATE SET version=excluded.version,payload=excluded.payload',(month,record['version'],dump(record)))
            if state=='closed':
                import product_profit
                snapshot=product_profit.month(self.c,month)
                pending=[d for d in snapshot.get('allocation',{}).get('details',[]) if d.get('unallocated_cents')]
                if snapshot.get('total',{}).get('net_cents') is None or pending:
                    # 利润仍未知时不写死快照：补齐发货复核、结算公斤或费用到单后继续实时重算，
                    # 避免把“未知”永久固化成已结账月的结论。
                    record['report_snapshot_pending']=True
                else:
                    record['report_snapshot']=snapshot
                self.c.execute('UPDATE resource_periods SET payload=? WHERE month=?',(dump(record),month))
            self.audit(self.c,role,'成本月份结账' if state=='closed' else '重开成本月份',month,json.loads(old['payload']) if old else None,record)
            self.c.execute('RELEASE erp_cost_period_change')
            if state=='closed':
                # 月结成功即自动生成当月数据包；生成失败不影响结账，但会在返回里提示。
                try:
                    import data_package
                    record['data_package']=data_package.save(self.c,month)
                except Exception as exc:
                    record['data_package_error']=str(exc)[:300]
        except Exception:
            self.c.execute('ROLLBACK TO erp_cost_period_change')
            self.c.execute('RELEASE erp_cost_period_change')
            raise
        return {k:v for k,v in record.items() if k!='report_snapshot'}


BYPRODUCT_META='byproduct_settlement'
def byproduct_config(c):
    row=c.execute("SELECT value FROM meta WHERE key=?",(BYPRODUCT_META,)).fetchone()
    cfg=json.loads(row[0]) if row else {}
    try:add=Decimal(str(cfg.get('add_kg') or '0'))
    except (InvalidOperation,TypeError,ValueError):add=Decimal(0)
    client=c.execute('SELECT name FROM customers WHERE id=?',(cfg.get('customer_id'),)).fetchone()
    return {'buyer':client[0] if client else str(cfg.get('buyer') or ''),'customer_id':cfg.get('customer_id',''),'basis':cfg.get('basis','bean'),'yield_ratio':str(cfg.get('yield_ratio') or '1'),'add_kg':ds(add),'prices':cfg.get('prices') or {},'version':int(cfg.get('version') or 0)}


def _write_byproduct_config(c,cfg):
    c.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(BYPRODUCT_META,dump(cfg)))


def save_byproduct_config(c,b,role,now,audit):
    import erp_access
    if role!='管理员':raise ValueError('豆渣结算设置仅允许管理员修改')
    erp_access.require_role(role,'system.parameters')
    cfg=byproduct_config(c)
    if 'version' in b and (type(b['version']) is not int or b['version']!=cfg['version']):raise ValueError('豆渣参数已变化，请重新读取后修改')
    import byproduct_accounts as ba
    client=ba.sale_customer(c,b['customer_id']) if b.get('customer_id') else ba.legacy_customer(c,b.get('buyer'),now,audit)
    basis=b.get('basis',cfg['basis'])
    if basis not in ('bean','converted'):raise ValueError('豆渣结算口径无效')
    ratio=qty(b.get('yield_ratio',cfg['yield_ratio']),'出渣换算系数',positive=True)
    if ratio>100:raise ValueError('出渣换算系数不能超过100，请核对每公斤干豆对应的豆渣公斤数')
    value={'buyer':client['name'],'customer_id':client['id'],'basis':basis,'yield_ratio':ds(ratio),'add_kg':ds(qty(b.get('add_kg','0'),'每日加量')),'prices':cfg['prices'],'version':cfg['version']+1}
    before=cfg;_write_byproduct_config(c,value)
    audit(c,role,'维护豆渣按日结算设置','byproduct-settlement',before,value)
    return byproduct_config(c)


def save_byproduct_price(c,b,role,now,audit):
    import erp_access
    erp_access.require_role(role,'byproducts.write')
    month=str(b.get('month') or '')
    try:datetime.strptime(month,'%Y-%m')
    except (ValueError,TypeError):raise ValueError('结算月份无效')
    if any(not r.get('voided') and r.get('source')=='daily-settlement' and r.get('period')==month for r in rows(c,'byproduct_sales')):raise ValueError('该月已生成收入记录，请先作废原记录后调整单价')
    price=qty(b.get('price'),'豆渣单价'); 
    if price<=0:raise ValueError('豆渣单价须大于0')
    cfg=byproduct_config(c);prices=dict(cfg['prices']);before=prices.get(month)
    prices[month]=ds(price);_write_byproduct_config(c,{**cfg,'prices':prices})
    audit(c,role,'维护豆渣月度单价',month,{'price':before},{'price':ds(price)})
    return {'month':month,'price':ds(price)}


def daily_bean_kg(c,day):
    total=Decimal(0)
    for r in rows(c,'material_entries'):
        if r.get('voided') or r.get('business_date')!=day or r.get('material_id')!='RM-SOY':continue
        if r.get('kind')=='consume':total+=Decimal(str(r.get('qty') or '0'))
        elif r.get('kind')=='return':total-=Decimal(str(r.get('qty') or '0'))
    return total if total>0 else Decimal(0)


def byproduct_month(c,month):
    try:datetime.strptime(str(month),'%Y-%m')
    except (ValueError,TypeError):raise ValueError('结算月份无效')
    cfg=byproduct_config(c);price=Decimal(str(cfg['prices'].get(month) or '0'));add=Decimal(cfg['add_kg'])
    dates=sorted({r.get('business_date','') for r in rows(c,'material_entries') if not r.get('voided') and r.get('material_id')=='RM-SOY' and str(r.get('business_date','')).startswith(str(month)) and r.get('kind') in ('consume','return')})
    days=[]
    for d in dates:
        bean=daily_bean_kg(c,d)
        if bean<=0:continue
        ratio=Decimal(cfg['yield_ratio']) if cfg['basis']=='converted' else Decimal(1)
        q=(bean*ratio+add).quantize(Decimal('0.001'),rounding=ROUND_HALF_UP);amount=int((q*price*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        days.append({'date':d,'bean_kg':ds(bean),'add_kg':ds(add),'qty':ds(q),'amount_cents':amount})
    total_qty=sum((Decimal(d['qty']) for d in days),Decimal(0));total_amount=sum((d['amount_cents'] for d in days),0)
    settlement=next((r for r in rows(c,'byproduct_sales') if not r.get('voided') and r.get('source')=='daily-settlement' and r.get('period')==month),None)
    return {'month':month,'config':cfg,'price':ds(price),'days':days,'total_qty':ds(total_qty),'total_amount_cents':total_amount,'settlement':settlement}


def settle_byproduct(c,b,role,now,audit):
    import erp_access
    erp_access.require_role(role,'byproducts.write')
    summary=byproduct_month(c,b.get('month'))
    if summary['settlement']:raise ValueError('该月份已有按日结算记录，如需重算请先作废原记录')
    if Decimal(summary['price'])<=0:raise ValueError('请先填写本月豆渣单价')
    if not summary['days']:raise ValueError('本月没有上豆记录，不能结算')
    if not b.get('customer_id') and not summary['config']['buyer']:raise ValueError('请先在豆渣设置中填写固定买家，或选择结算客户')
    import byproduct_accounts as ba
    client=ba.sale_customer(c,b.get('customer_id') or summary['config']['customer_id'])
    if not b.get('request_key'):raise ValueError('缺少提交编号')
    last=calendar.monthrange(int(summary['month'][:4]),int(summary['month'][5:7]))[1]
    open_period(c,summary['month']+'-%02d'%last)
    record={'business_date':summary['month']+'-%02d'%last,'qty':summary['total_qty'],'unit':'公斤','price':summary['price'],'amount_cents':summary['total_amount_cents'],'received_cents':0,
            'buyer':client['name'],'customer_id':client['id'],'reference':'','source':'daily-settlement','period':summary['month'],
            'daily_rows':[{k:day[k] for k in ('date','qty','amount_cents')} for day in summary['days']],
            'internal_calculation':{k:summary['config'][k] for k in ('basis','yield_ratio','add_kg','version')},
            'note':'%s 月度豆渣收入记录'%summary['month'],'handler':text(b.get('handler'),'经办人',80)}
    return Operations(c,now,audit).post('byproduct_sales',record,b,role,'按日结算豆渣收入')


def byproduct_business_record(record):
    """Business views retain quantities and money, without internal configuration notes."""
    value=dict(record)
    value.pop('internal_calculation',None)
    if value.get('source')=='daily-settlement':
        value['note']='%s 月度豆渣收入记录'%value.get('period',value.get('business_date','')[:7])
    return value


def byproduct_business_month(c,month):
    value=byproduct_month(c,month)
    def daily_rows(days):
        indexed={d['date']:d for d in days};last=calendar.monthrange(int(month[:4]),int(month[5:]))[1]
        return [{**{key:indexed[when][key] for key in ('date','qty','amount_cents')},'recorded':True} if when in indexed else {'date':when,'qty':None,'amount_cents':0,'recorded':False} for when in (month+'-%02d'%d for d in range(1,last+1))]
    if value['settlement']:
        record=value['settlement']
        return {'month':value['month'],'buyer':record['buyer'],'customer_id':record.get('customer_id',''),'price':record['price'],
                'days':daily_rows(record.get('daily_rows',[])),
                'total_qty':record['qty'],'total_amount_cents':record['amount_cents'],
                'settlement':byproduct_business_record(record)}
    return {'month':value['month'],'buyer':value['config']['buyer'],'customer_id':value['config']['customer_id'],'price':value['price'],
            'days':daily_rows(value['days']),
            'total_qty':value['total_qty'],'total_amount_cents':value['total_amount_cents'],
            'settlement':byproduct_business_record(value['settlement']) if value['settlement'] else None}
