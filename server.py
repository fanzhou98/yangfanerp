#!/usr/bin/env python3
"""Local-only ERP pilot. Standard library, SQLite, exact decimal arithmetic."""
import cost_allocation
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contextlib import contextmanager, nullcontext
from datetime import datetime, date, timezone, timedelta
from urllib.parse import urlsplit, parse_qs
import gzip, time, contextvars
from http.cookies import SimpleCookie
import auth
import trade
import crate_accounting
import accounting_entry
import finished_goods
import gel_tofu
import order_corrections
import re, argparse, csv, io, json, os, secrets, sqlite3, sys, threading, webbrowser, ipaddress
import inventory
import erp_access
import billing
import audit_chain
import owner_analysis
import production_management
import payroll
import assets
import driver_portal
import resources_costs
import resource_query
import finance_query
import purchasing
import collaboration
import audit_query
import receipt_ocr

ROOT = Path(__file__).resolve().parent
APP_VERSION = (ROOT / 'VERSION').read_text().strip() if (ROOT / 'VERSION').is_file() else '0.0.0'
DB = ROOT / 'data' / 'erp.db'
TZ = timezone(timedelta(hours=8))
ROLES = ('库管', '会计', '出纳')
LOCK = threading.RLock()
REQUEST_ACTOR = contextvars.ContextVar("erp_actor", default=None)
REQUEST_TOKEN = contextvars.ContextVar("erp_token", default=None)

def lan_interface(value):
    try:
        interface=ipaddress.IPv4Interface(value)
        ranges=[ipaddress.IPv4Network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
        if '/' not in value or not any(interface.network.subnet_of(n) for n in ranges):raise ValueError()
        if interface.ip in (interface.network.network_address,interface.network.broadcast_address):raise ValueError()
        return interface
    except (ValueError,TypeError):raise ValueError('局域网地址须为本机的私有IPv4地址及子网，例如192.168.31.39/24')

def now(): return datetime.now(TZ).isoformat(timespec='seconds')
def dumps(x): return json.dumps(x, ensure_ascii=False, separators=(',', ':'))
def dec(x, name='数值', maximum='100000000', positive=False):
    try:
        if isinstance(x, bool): raise ValueError()
        d = Decimal(str(x))
        if not d.is_finite() or d < 0 or d > Decimal(maximum) or (positive and d == 0): raise ValueError()
        if d.as_tuple().exponent < -3: raise ValueError()
        return d
    except (InvalidOperation, ValueError, TypeError): raise ValueError(f'{name}须为有效非负数，最多3位小数' + ('，且大于0' if positive else ''))
def ds(d): return format(Decimal(d).normalize(), 'f')
def money(d): return int((d * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
def clean(x, name, limit=200, required=True):
    if not isinstance(x, str) or len(x) > limit or (required and not x.strip()): raise ValueError(f'请填写有效的{name}（最多{limit}字）')
    return x.strip()
def valid_date(x):
    try:
        if date.fromisoformat(x).isoformat() != x: raise ValueError()
    except (ValueError, TypeError): raise ValueError('业务日期格式须为 YYYY-MM-DD')
    return x

class ValidationError(ValueError):
    def __init__(self, issues, message='请修正标出的填写问题后重试；本批次未保存'):
        self.issues=issues
        super().__init__(message)

def field_issue(o, line, field, message, source=None, index=None):
    item={'order_id':o.get('id'),'customer_id':o.get('customer_id'),
          'customer_name':o.get('customer_name',''),'product_id':line.get('product_id') if line else None,
          'product_name':line.get('product_name','') if line else '', 'field':field,'message':message}
    if source is not None:item['source']=source
    if index is not None:item['index']=index
    return item

def validate_order_input(c, body, old=None):
    """Return every invalid cell, including the precise weighing batch."""
    issues=[];context={**body,'id':old.get('id') if old else None}
    customer=c.execute('SELECT name FROM customers WHERE id=?',(body.get('customer_id'),)).fetchone()
    if customer:context['customer_name']=customer[0]
    else:issues.append(field_issue(context,None,'customer_id','请选择有效客户'))
    for key,check in [('business_date',valid_date),('batch',lambda v:clean(v,'发货批次',40))]:
        try:check(body.get(key))
        except ValueError as e:issues.append(field_issue(context,None,key,str(e)))
    lines=body.get('lines')
    if not isinstance(lines,list) or not 1<=len(lines)<=50:
        return issues+[field_issue(context,None,'lines','须有1至50项产品')]
    seen=set()
    for raw in lines:
        if not isinstance(raw,dict):
            issues.append(field_issue(context,None,'lines','产品明细格式错误'));continue
        pid=raw.get('product_id');p=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
        if not p:
            issues.append(field_issue(context,raw,'product_id','产品不存在，请核对产品档案'));continue
        prior=next((l for l in (old or {}).get('lines',[]) if l['product_id']==pid),None)
        line={**raw,'product_name':(prior or {}).get('product_name',p['name'])};unit=(prior or {}).get('unit',p['unit'])
        if pid in seen:issues.append(field_issue(context,line,'product_id','同一产品重复，请合并数量，称重可分批记录'))
        seen.add(pid);values={}
        for key,label,maximum,positive in [('ordered_qty','订货数量','100000',True),('actual_qty','实发数量','100000',False),('price','单价','100000',True)]:
            try:
                value=dec(raw.get(key),label,maximum,positive)
                if key!='price' and not next((u['fractional'] for u in trade.units(c) if u['id']==unit),False) and value!=value.to_integral():raise ValueError(label+'须为整数')
                values[key]=value
            except ValueError as e:issues.append(field_issue(context,line,key,str(e)))
        if raw.get('package_customer_net_kg') not in (None,''):
            try:
                dec(raw['package_customer_net_kg'],'包装客户复称净重',positive=True)
                if unit=='筐' or values.get('actual_qty',0)<=0:raise ValueError('仅已实发包装产品可填写包装客户复称净重')
            except ValueError as e:issues.append(field_issue(context,line,'package_customer_net_kg',str(e)))
        if raw.get('factory_net_kg') not in (None,''):
            try:
                dec(raw['factory_net_kg'],'出厂净重',positive=True)
                if values.get('actual_qty',0)<=0:raise ValueError('出厂称重须先填写实发数量')
            except ValueError as e:issues.append(field_issue(context,line,'factory_net_kg',str(e)))
        flag=raw.get('not_shipped',False)
        if not isinstance(flag,bool):issues.append(field_issue(context,line,'not_shipped','未发货确认格式无效'))
        if flag and values.get('actual_qty',0)>0:issues.append(field_issue(context,line,'not_shipped','已勾选本次未发，实发数量必须为0'))
        for source,label in [('driver','卸货'),('customer','复称')]:
            rows=raw.get(source,[])
            if not isinstance(rows,list) or len(rows)>100:
                issues.append(field_issue(context,line,'gross',label+'批次数量无效',source,0));continue
            if rows and flag:issues.append(field_issue(context,line,'not_shipped','本次未发产品不能保留称重，请核对后清除本次称重'))
            if rows and unit!='筐':issues.append(field_issue(context,line,'gross','包装产品请填写包装实称净重，不填写筐装称重',source,0))
            count=Decimal(0);counts_valid=True
            for i,w in enumerate(rows):
                if not isinstance(w,dict):issues.append(field_issue(context,line,'gross','称重批次格式无效',source,i));continue
                vals={}
                for key,name,maximum,positive in [('gross','毛重','100000000',True),('count','筐数','100000',True),('tare','单筐皮重','100',False)]:
                    try:
                        value=dec(w.get(key),name,maximum,positive)
                        if key=='count' and value!=value.to_integral():raise ValueError('筐数须为整数')
                        vals[key]=value
                    except ValueError as e:
                        issues.append(field_issue(context,line,key,f'{label}第{i+1}批：{e}',source,i))
                if len(vals)==3 and vals['gross']<=vals['count']*vals['tare']:
                    issues.append(field_issue(context,line,'gross',f'{label}第{i+1}批：毛重必须大于总皮重（{ds(vals["count"]*vals["tare"])}公斤）',source,i))
                if 'count' in vals:count+=vals['count']
                else:counts_valid=False
            if counts_valid and 'actual_qty' in values and count>values['actual_qty']:
                for i in range(len(rows)):issues.append(field_issue(context,line,'count',f'{label}合计{ds(count)}筐，超过实发{ds(values["actual_qty"])}筐',source,i))
    return issues

def snapshot_standard_weights(c,order):
    for line in order['lines']:
        if 'standard_unit_kg' not in line:
            product=c.execute('SELECT * FROM products WHERE id=?',(line['product_id'],)).fetchone()
            line['standard_unit_kg']=production_management.product_average(c,product) if product else None

def validate_settlement(o, body):
    issues=[];shipped=False
    overrides=body.get('tare_overrides',{})
    if not isinstance(overrides,dict):return [field_issue(o,None,'settlement_tare','结算皮重格式无效')]
    if set(overrides)-{l['product_id'] for l in o['lines']}:return [field_issue(o,None,'settlement_tare','结算皮重产品无效')]
    for line in o['lines']:
        tares=overrides.get(line['product_id'],{})
        if not isinstance(tares,dict) or any(k!='customer' for k in tares):
            issues.append(field_issue(o,line,'settlement_tare','皮重只用于客户复称，司机净重不扣皮'));continue
        for source,value in tares.items():
            try:
                dec(value,'结算单筐皮重','100')
                if line['unit']!='筐' or not line.get(source):raise ValueError('仅已有称重的筐装产品可调整结算皮重')
                if billing.settlement_net(line,source,tares)<=0:raise ValueError('调整皮重后的结算净重必须大于0')
            except ValueError as e:issues.append(field_issue(o,line,'settlement_tare',str(e),source,0))

        actual=Decimal(line['actual_qty'])
        if line.get('not_shipped') and actual==0:continue
        if actual==0:
            issues.append(field_issue(o,line,'not_shipped','实发为0：请填实发数量，或勾选“本次未发”，无需删除订货记录'));continue
        shipped=True
        if line['unit']!='筐' and billing.is_kg(line):
            if billing.package_kg(line)<=0:issues.append(field_issue(o,line,'package_net_kg','请填写包装实称净重或有效的标准包装公斤数'))
        if line['unit']=='筐' and billing.is_kg(line):
            mode=body.get('line_modes',{}).get(line['product_id'],body.get('mode'))
            sources=['driver','customer','factory'] if mode=='agreed' else [mode]
            ready=lambda source:(bool(line.get('factory_net_kg')) if source=='factory' else billing.standard_weight(line)>0 if source=='standard' else source in ('driver','customer') and bool(line[source]) and Decimal(line[source+'_count'])==actual and billing.settlement_net(line,source,tares)>0)
            if not any(ready(source) for source in sources):
                source=mode if mode in ('driver','customer') else None
                issues.append(field_issue(o,line,'gross','请填写所选计价依据：完整司机/客户称重、出厂净重或标准单位重量',source,0))
            if mode=='agreed':
                try:dec(body.get('agreed',{}).get(line['product_id']),'协商净重',positive=True)
                except ValueError as e:issues.append(field_issue(o,line,'agreed_net',str(e)))
                if not str(body.get('reason','')).strip():issues.append(field_issue(o,line,'reason','采用协商净重时，请填写本客户的协商原因'))
    if not shipped and not issues:issues.append(field_issue(o,None,'actual_qty','本单全部产品未发货，仅需保存草稿，不形成应收账单'))
    return issues

@contextmanager
def connect(write=False):
    with LOCK:
        c = sqlite3.connect(DB, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                c.execute('BEGIN IMMEDIATE')
                token=REQUEST_TOKEN.get()
                if token:auth.authenticate(c,token,int(time.time()))
            yield c
            if write: c.commit()
        except Exception:
            c.rollback(); raise
        finally: c.close()

def audit(c, role, action, entity, before=None, after=None):
    actor=REQUEST_ACTOR.get() or {}
    audit_chain.append(c, (now(), role, action, str(entity), dumps(before), dumps(after),actor.get('id',''),actor.get('display_name',''),actor.get('request_id','')))

def status(o):
    if o['state'] == 'reviewed':
        if inventory.balance(o)==0 and (o.get('discount_cents') or o.get('rounding_cents')):return '已结清'
        if inventory.balance(o)==0:return '已抵清' if not o['paid_cents'] and o.get('return_credit_cents') else '已结清' if o.get('return_credit_cents') else '已收清'
        return '部分收款 / 抵扣' if (o.get('return_credit_cents') or o.get('discount_cents') or o.get('rounding_cents')) else '部分收款' if o['paid_cents'] else '待收款'
    if (o.get('review_return') or {}).get('status')=='pending':return '待重算'
    if o['state']=='dispatched' and o.get('workflow_version')==1 and not o.get('weight_confirmation'):return '待确认称重'
    return {'draft':'待发货','dispatched':'待算票','negotiation':'待算票','ready':'待复核'}[o['state']]

def order_delivery_method(c,o):
    if o.get('delivery_method') in ('delivery','pickup'):return o['delivery_method']
    customer=c.execute('SELECT delivery_method FROM customers WHERE id=?',(o['customer_id'],)).fetchone()
    return customer[0] if customer else 'delivery'

def get_order(c, oid):
    r = c.execute('SELECT payload FROM orders WHERE id=?', (oid,)).fetchone()
    if not r: raise ValueError('单据不存在')
    o = json.loads(r[0]); o['status'] = status(o);o['delivery_method']=order_delivery_method(c,o)
    return o

def save(c, o):
    prior=c.execute('SELECT payload FROM orders WHERE id=?',(o['id'],)).fetchone()
    __import__('transport_closure').guard_order(c,json.loads(prior[0]) if prior else None,o)
    o.pop('status', None)
    c.execute('INSERT INTO orders(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (o['id'], dumps(o)))

def revision(o, body):
    if body.get('version') != o['version']: raise ValueError('单据已被修改，请关闭后重新打开，核对最新数据再操作')

def weights(rows, actual, source):
    if not isinstance(rows, list) or len(rows) > 100: raise ValueError('称重批次数量无效')
    result = []; count = Decimal(0); net = Decimal(0)
    for r in rows:
        gross = dec(r.get('gross'), '毛重', positive=True)
        n = dec(r.get('count'), '合称筐数', '100000', True)
        if n != n.to_integral(): raise ValueError('合称筐数须为整数')
        tare = dec(r.get('tare'), '单筐皮重', '100')
        if gross <= n*tare: raise ValueError('毛重必须大于总皮重')
        net += gross - n*tare; count += n
        result.append({'gross':ds(gross),'count':ds(n),'tare':ds(tare),'note':clean(r.get('note',''), '称重备注', 150, False)})
    if count > actual: raise ValueError(f'{source}合称筐数不能超过实发筐数')
    return result, net, count

def remove_unused_weights(c,body,old=None):
    body=json.loads(dumps(body))
    for line in body.get('lines',[]) if isinstance(body.get('lines'),list) else []:
        if not isinstance(line,dict):continue
        p=c.execute('SELECT unit,tare FROM products WHERE id=?',(line.get('product_id'),)).fetchone()
        if not p or p['unit']!='筐':continue
        rule=c.execute('SELECT tare FROM rules WHERE customer_id=? AND product_id=?',(body.get('customer_id'),line.get('product_id'))).fetchone()
        tare=rule[0] if rule else p['tare']
        prior=next((l for l in (old or {}).get('lines',[]) if l['product_id']==line.get('product_id')), {})
        def same(a,b):
            try:return Decimal(str(a))==Decimal(str(b))
            except Exception:return False
        blank=lambda v:v is None or not str(v).strip()
        for source in ['driver','customer']:
            rows=line.get(source,[])
            if not isinstance(rows,list):continue
            line[source]=[w for i,w in enumerate(rows) if not (isinstance(w,dict) and i>=len(prior.get(source,[])) and blank(w.get('gross')) and blank(w.get('note')) and (blank(w.get('count')) or same(w.get('count'),line.get('actual_qty'))) and (blank(w.get('tare')) or same(w.get('tare'),tare)))]
    return body

def weight_projection(o):
    return (o['customer_id'],o['business_date'],sorted((l['product_id'],l['ordered_qty'],l['actual_qty'],bool(l.get('not_shipped')),dumps(l.get('driver',[])),dumps(l.get('customer',[])),l.get('package_net_kg',''),l.get('factory_net_kg',''),l.get('package_customer_net_kg',''),dumps(l.get('crate_lines',[])),l.get('driver_weight_basis','legacy_net')) for l in o['lines']))

def normalize_order(c, body, old=None):
    actor=REQUEST_ACTOR.get()
    if actor and not erp_access.can_read_data(actor['permissions'],'sales-prices'):
        body=json.loads(dumps(body))
        for line in body.get('lines',[]):
            if isinstance(line,dict) and line.get('price') in (None,''):
                prior=next((l for l in (old or {}).get('lines',[]) if l['product_id']==line.get('product_id')),None)
                rule=c.execute('SELECT price FROM rules WHERE customer_id=? AND product_id=?',(body.get('customer_id'),line.get('product_id'))).fetchone()
                product=c.execute('SELECT price FROM products WHERE id=?',(line.get('product_id'),)).fetchone()
                line['price']=prior['price'] if prior else rule[0] if rule else product[0] if product else None
    body=remove_unused_weights(c,body,old)
    issues=validate_order_input(c,body,old)
    if issues:raise ValidationError(issues)
    workflow_version=body.get('workflow_version',(old or {}).get('workflow_version',0))
    if type(workflow_version) is not int or workflow_version not in (0,1):raise ValueError('称重交接流程版本无效')
    if (old or {}).get('workflow_version')==1:workflow_version=1
    cid = body.get('customer_id')
    customer = c.execute('SELECT * FROM customers WHERE id=?', (cid,)).fetchone()
    if not customer: raise ValueError('请选择客户')
    if not old and customer['business_kind']=='byproduct':raise ValueError('该客户仅开通豆渣业务，请在豆渣收入中登记销售，或先将客户业务类型改为兼营')
    if not old and 'ordering_enabled' in customer.keys() and customer['ordering_enabled']==0:raise ValueError('该客户已暂停订货，暂不能下单；恢复供货后请管理员在客户档案中开启订货')
    lines = body.get('lines')
    if not isinstance(lines,list) or not 1 <= len(lines) <= 50: raise ValueError('须有1至50项产品')
    out=[]; seen=set(); has_actual=False
    for x in lines:
        pid=x.get('product_id')
        if pid in seen: raise ValueError('同一产品请合并录入，称重可分批追加')
        seen.add(pid)
        p=c.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone()
        if not p: raise ValueError('请选择有效产品')
        ordered=dec(x.get('ordered_qty'),'订货数量','100000',True)
        actual=dec(x.get('actual_qty'),'实发数量','100000')
        if not next((u['fractional'] for u in trade.units(c) if u['id']==(next((l['unit'] for l in (old or {}).get('lines',[]) if l['product_id']==pid),p['unit']))),False) and (ordered != ordered.to_integral() or actual != actual.to_integral()): raise ValueError('筐数、包数须为整数')
        price=dec(x.get('price'),'单价','100000',True)
        if REQUEST_ACTOR.get() and not erp_access.role_can(REQUEST_ACTOR.get()['role'],'finance.price-edit'):
            prior_price=next((l['price'] for l in (old or {}).get('lines',[]) if l['product_id']==pid),None)
            rule=c.execute('SELECT price FROM rules WHERE customer_id=? AND product_id=?',(cid,pid)).fetchone()
            allowed_price=prior_price if prior_price is not None else rule[0] if rule else p['price']
            if price!=Decimal(allowed_price):raise ValueError('当前账号不能修改单价，请由有定价权限的人员核定后重试')
        driver,dnet,dcount=weights(x.get('driver',[]),actual,'司机卸货')
        customer_w,cnet,ccount=weights(x.get('customer',[]),actual,'客户复称')
        prior=next((l for l in (old or {}).get('lines',[]) if l['product_id']==pid),None)
        product_name=(prior or {}).get('product_name',p['name']);unit=(prior or {}).get('unit',p['unit'])
        standard_kg=(prior or {}).get('standard_kg',p['standard_kg'])
        if unit!='筐' and (driver or customer_w): raise ValueError('包装产品请填写包装实称净重，不填写筐装称重')
        billing_unit=(prior or {}).get('billing_unit',trade.product_billing(c,p))
        package_net=x.get('package_net_kg',(prior or {}).get('package_net_kg',''))
        if package_net not in (None,''):
            package_net=ds(dec(package_net,'包装产品实称净重',positive=True))
            if unit=='筐' or actual==0:raise ValueError('仅已实发的包装产品可填写包装实称净重')
        else:package_net=''
        factory_net=x.get('factory_net_kg',(prior or {}).get('factory_net_kg',''))
        factory_net=ds(dec(factory_net,'出厂净重',positive=True)) if factory_net not in (None,'') else ''
        if factory_net and actual==0:raise ValueError('出厂称重须先填写实发数量')
        package_customer=x.get('package_customer_net_kg',(prior or {}).get('package_customer_net_kg',''))
        package_customer=ds(dec(package_customer,'包装客户复称净重',positive=True)) if package_customer not in (None,'') else ''
        if package_customer and (unit=='筐' or actual==0):raise ValueError('仅已实发的包装产品可填写包装客户复称净重')
        standard_unit=(prior or {}).get('standard_unit_kg',production_management.product_average(c,p))
        raw_crates=x.get('crate_lines',(prior or {}).get('crate_lines'))
        if x.get('auto_crate') is True and not any('packing_lines' in row for row in (raw_crates or [])):
            automatic=accounting_entry.auto_crates(c,cid,pid,actual)
            if automatic is not None and (not raw_crates or len(raw_crates)==1 and automatic and raw_crates[0].get('asset_id')==automatic[0]['asset_id']):
                if automatic and raw_crates:automatic[0]['tare']=raw_crates[0].get('tare',automatic[0]['tare'])
                raw_crates=automatic
        crate_lines=crate_accounting.normalize(c,pid,raw_crates,actual,prior=(prior or {}).get('crate_lines'),customer_id=cid)
        has_actual=has_actual or actual>0
        out.append({'product_id':pid,'product_name':product_name,'unit':unit,'billing_unit':billing_unit,'package_net_kg':package_net,'factory_net_kg':factory_net,'package_customer_net_kg':package_customer,'standard_unit_kg':standard_unit,'standard_kg':standard_kg,'not_shipped':x.get('not_shipped',False),
          **({'crate_lines':crate_lines} if crate_lines is not None else {}),'ordered_qty':ds(ordered),'actual_qty':ds(actual),'price':ds(price),
          'driver':driver,'customer':customer_w,'driver_net':ds(dnet),'customer_net':ds(cnet),
          'driver_count':ds(dcount),'customer_count':ds(ccount), 'agreed_net': None,'bill_qty':None,'amount_cents':0})
        if customer_w and any('packing_lines' in row for row in (crate_lines or [])):out[-1]['customer_net']=ds(billing.settlement_net(out[-1],'customer'))
        basis=x.get('driver_weight_basis',(prior or {}).get('driver_weight_basis'))
        if basis is not None:
            if basis not in ('gross','legacy_net'):raise ValueError('司机称重口径无效')
            out[-1]['driver_weight_basis']=basis
            if driver and basis=='gross':out[-1]['driver_net']=ds(billing.settlement_net(out[-1],'driver'))
    return {'id':old['id'] if old else 'SO-'+datetime.now(TZ).strftime('%Y%m%d')+'-'+secrets.token_hex(3).upper(),
      'version':old['version']+1 if old else 1,'customer_id':cid,'customer_name':customer['name'],'route':customer['route'],'delivery_method':(old or {}).get('delivery_method',customer['delivery_method']),
      'business_date':valid_date(body.get('business_date')),'batch':clean(body.get('batch','晚班'), '发货批次',40),
      'note':clean(body.get('note',''),'单据备注',500,False),'lines':out,'state':'dispatched' if has_actual else 'draft',
      'dispatch_required':bool(body.get('dispatch_required') or (old or {}).get('dispatch_required')),'workflow_version':workflow_version,'weight_confirmation':(old or {}).get('weight_confirmation') if old and weight_projection({**old,'customer_id':cid,'business_date':body.get('business_date'),'lines':out})==weight_projection(old) else None,
      **({'accounting_returns':json.loads(dumps(old['accounting_returns']))} if (old or {}).get('accounting_returns') else {}),'correction_ids':(old or {}).get('correction_ids',[]),'review_history':json.loads(dumps((old or {}).get('review_history',[]))),'review_return':json.loads(dumps((old or {}).get('review_return'))),'settlement':None,'review':None,'total_cents':0,'paid_cents':0,'created_at':old['created_at'] if old else now(),'updated_at':now()}

def mutate(action, body, role, oid=None, connection=None, defer_inventory=False):
    if role not in (*ROLES,'管理员'): raise ValueError('请选择有效岗位')
    with (nullcontext(connection) if connection is not None else connect(True)) as c:
        check_business_epoch(c,body)
        old=get_order(c,oid) if oid else None
        if old: revision(old,body)
        if action=='order':
            if not oid and body.get('daily_order') is True:
                for row in c.execute('SELECT payload FROM orders'):
                    existing=json.loads(row[0])
                    if existing['customer_id']==body.get('customer_id') and existing['business_date']==body.get('business_date'):raise ValueError('该客户当天已有订货，请同步最新数据后修改现有订单，避免重复新增')
            erp_access.require_role(role,'orders.write')
            if old and (old['paid_cents'] or (old.get('return_credit_cents') or old.get('discount_cents') or old.get('rounding_cents'))): raise ValueError('已有收款或退货抵扣的单据已锁定，请保留原单')
            if old and not erp_access.role_can(role,'finance.settle') and old['state'] in ('ready','reviewed','negotiation'): raise ValueError('已进入结算流程，请由会计修订并重新结算')
            o=normalize_order(c,body,old)
            if REQUEST_ACTOR.get() and not erp_access.role_can(role,'weight.write'):
                movement=lambda value:sorted((l['product_id'],l['actual_qty'],dumps(l.get('driver',[])),dumps(l.get('customer',[])),l.get('package_net_kg',''),l.get('factory_net_kg',''),l.get('package_customer_net_kg',''),bool(l.get('not_shipped')),l.get('driver_weight_basis','legacy_net'),dumps(l.get('crate_lines',[]))) for l in value['lines'] if Decimal(l['actual_qty']) or l.get('driver') or l.get('customer') or l.get('package_net_kg') or l.get('factory_net_kg') or l.get('package_customer_net_kg') or l.get('not_shipped'))
                if movement(o)!=movement(old or {'lines':[]}):raise ValueError('当前账号不能更改实发或原始称重，请退回库管核对')
            accounting_entry.guard_source_edit(c,old,o)
            accounting_entry.sync_returns(c,o,body.get('accounting_returns'),old,role,now,audit)
            inventory.validate_order(c,o,old)
            if o.get('dispatch_required') and not defer_inventory:inventory.validate_dispatch(c,o,old)
            if old:order_corrections.invalidate(c,old,'订单内容修订，原结算及复核失效',role,now,audit)
            save(c,o)
            movement=lambda value:(value['business_date'],sorted((l['product_id'],l['actual_qty']) for l in value['lines'] if Decimal(l['actual_qty'])>0))
            if not defer_inventory and ((not old and any(Decimal(l['actual_qty'])>0 for l in o['lines'])) or old and movement(o)!=movement(old)):
                for stock_day in {o['business_date'],(old or o)['business_date']}:inventory.validate_book(c,stock_day,True)
            demand=lambda value:(value['business_date'],value['customer_id'],sorted((l['product_id'],l['ordered_qty']) for l in value['lines']))
            if o.get('dispatch_required') and not defer_inventory and (not old or demand(o)!=demand(old)):
                for affected in {o['business_date'],(old or o)['business_date']}:
                    plan=inventory.get(c,'warehouse_plans',affected,'business_date')
                    if plan and plan.get('allocation_state','confirmed')=='confirmed' and not inventory.closed(c,affected):
                        prior=json.loads(dumps(plan));plan.update(allocation_state='draft',version=plan['version']+1,updated_at=now());inventory.put(c,'warehouse_plans',plan,'business_date');audit(c,role,'订货变化，需重新核对发货分配',affected,prior,plan)
            inventory.bump(c)
            audit(c,role,'修订单据（原结算及复核失效）' if old else '创建订货单',o['id'],old,o)
        elif action=='confirm-weight':
            erp_access.require_role(role,'weight.confirm')
            resources_costs.open_period(c,old['business_date'])
            if old['state'] not in ('draft','dispatched') or old.get('paid_cents') or (old.get('return_credit_cents') or old.get('discount_cents') or old.get('rounding_cents')):raise ValueError('已进入算票或复核流程，不能重复提交称重')
            if old.get('weight_confirmation'):raise ValueError('此单称重已提交会计，无需重复确认')
            if body.get('evidence_checked') is not True:raise ValueError('请核对实际发货和称重后勾选确认')
            if old.get('dispatch_required') or body.get('dispatch_required'):inventory.validate_dispatch(c,old)
            snapshot_standard_weights(c,old)
            trade.attach_crates(c,old)
            modes={l['product_id']:billing.default_weight_mode(l,order_delivery_method(c,old)=='pickup') for l in old['lines'] if l['unit']=='筐'}
            issues=validate_order_input(c,old,old)+validate_settlement(old,{'mode':'driver','line_modes':modes})
            if issues:raise ValidationError(issues)
            o=json.loads(dumps(old));o.update(workflow_version=1,weight_confirmation={'at':now(),'role':role,'source_version':old['version']},version=old['version']+1,updated_at=now())
            save(c,o);audit(c,role,'确认称重并交会计算票',oid,old,o)
        elif action=='negotiate':
            erp_access.require_role(role,'finance.settle')
            resources_costs.open_period(c,old['business_date'])
            if old['paid_cents'] or (old.get('return_credit_cents') or old.get('discount_cents') or old.get('rounding_cents')): raise ValueError('已有收款或退货抵扣的单据已锁定')
            o=old.copy(); o.update(state='negotiation',settlement={'reason':clean(body.get('reason'),'协商说明',500)},review=None,total_cents=0,version=old['version']+1,updated_at=now())
            order_corrections.invalidate(c,old,'标记待协商，原结算失效',role,now,audit)
            save(c,o); audit(c,role,'标记待协商',oid,old,o)
        elif action=='settle':
            erp_access.require_role(role,'finance.settle')
            resources_costs.open_period(c,old['business_date'])
            if old['paid_cents'] or (old.get('return_credit_cents') or old.get('discount_cents') or old.get('rounding_cents')): raise ValueError('已有收款或退货抵扣的单据已锁定')
            if old.get('state')=='reviewed': raise ValueError('已复核未收款，须先由出纳退回会计后再重算')
            snapshot_standard_weights(c,old)
            trade.attach_crates(c,old)
            mode=body.get('mode','auto')
            if mode not in ('auto','customer','driver','factory','standard','agreed'): raise ValueError('请选择结算依据')
            line_modes=body.get('line_modes',{})
            if not isinstance(line_modes,dict) or any(v not in ('customer','driver','factory','standard','agreed') for v in line_modes.values()):
                raise ValueError('产品结算依据无效')
            if not isinstance(body.get('agreed',{}),dict):raise ValueError('协商重量格式错误')
            if mode=='auto':
                line_modes={l['product_id']:line_modes.get(l['product_id'],billing.default_weight_mode(l,order_delivery_method(c,old)=='pickup')) for l in old['lines'] if l['unit']=='筐'}
                body={**body,'line_modes':line_modes}
            trade.validate_shipment(c,old)
            issues=validate_order_input(c,old,old)+validate_settlement(old,body)
            if issues:raise ValidationError(issues)
            if old.get('workflow_version')==1 and not old.get('weight_confirmation'):raise ValueError('请先确认司机照片、称重和框数，再进行算票')
            uses_agreed=mode=='agreed' or 'agreed' in line_modes.values()
            reason=clean(body.get('reason',''),'结算说明',500,uses_agreed)
            agreed=body.get('agreed',{})
            if not isinstance(agreed,dict): raise ValueError('协商重量格式错误')
            o=json.loads(dumps(old)); total=0
            for line in o['lines']:
                actual=Decimal(line['actual_qty'])
                if line.get('not_shipped') and actual==0:
                    line.update(bill_qty='0',amount_cents=0,settlement_mode='not_shipped');continue
                if line['unit']=='筐' and billing.is_kg(line):
                    line_mode=line_modes.get(line['product_id'],mode)
                    qty=billing.settlement_net(line,line_mode,body.get('tare_overrides',{}).get(line['product_id'],{})) if line_mode in ('customer','driver') else Decimal(line['factory_net_kg']) if line_mode=='factory' else billing.standard_weight(line) if line_mode=='standard' else dec(agreed.get(line['product_id']), '协商净重', positive=True)
                    line['agreed_net']=ds(qty) if line_mode=='agreed' else None
                    line['settlement_mode']=line_mode
                    line['settlement_tares']={source:ds(dec(value,'结算单筐皮重','100')) for source,value in body.get('tare_overrides',{}).get(line['product_id'],{}).items()} if line_mode=='customer' else {}
                else:
                    qty=billing.package_kg(line) if billing.is_kg(line) else actual
                    line['settlement_mode']=('package_customer' if line.get('package_customer_net_kg') else 'package_actual' if line.get('package_net_kg') else 'factory' if line.get('factory_net_kg') else 'package_standard') if billing.is_kg(line) else 'package_count'
                line['bill_qty']=ds(qty); line['amount_cents']=money(qty*Decimal(line['price'])); total+=line['amount_cents']
            if total<=0: raise ValueError('结算金额必须大于0')
            inventory.validate_order(c,o,old)
            return_amount=sum((r['finance']['amount_cents'] for r in inventory.rows(c,'sales_returns') if not r.get('voided') and r.get('order_id')==oid and r.get('finance')),0)
            if return_amount>total:raise ValueError('原单已有退货核减，重算销售金额不能小于累计核减金额')
            selected_modes={l.get('settlement_mode') for l in o['lines'] if l['unit']=='筐' and not l.get('not_shipped')}
            summary_mode='mixed' if len(selected_modes)>1 else next(iter(selected_modes),mode)
            o.update(state='ready',total_cents=total,settlement={'mode':summary_mode,'reason':reason,'at':now(),'role':role},review=None,version=old['version']+1,updated_at=now())
            if (o.get('review_return') or {}).get('status')=='pending':
                o['review_return'].update(status='resubmitted',resubmitted_at=now(),resubmitted_by=role,resubmitted_version=o['version'])
                for entry in o.get('review_history',[]):
                    if entry.get('id')==o['review_return']['id']:entry.update(o['review_return'])
            order_corrections.invalidate(c,old,'重新算票，旧结算单作废',role,now,audit)
            save(c,o); audit(c,role,'退回重算完成，重新提交复核' if (old.get('review_return') or {}).get('status')=='pending' else '确认结算，提交复核',oid,old,o)
        elif action=='return-review':
            erp_access.require_role(role,'finance.review-return')
            if old['state']!='ready' or old.get('paid_cents') or (old.get('return_credit_cents') or old.get('discount_cents') or old.get('rounding_cents')):raise ValueError('仅未入账的待复核单据可退回会计；已收款或抵扣单据不能退回')
            reason=clean(body.get('reason'),'退回重算原因',500)
            o=json.loads(dumps(old))
            entry={'id':'RV-'+secrets.token_hex(6),'status':'pending','at':now(),'role':role,'reason':reason,'source_version':old['version'],'settlement':old.get('settlement'),'total_cents':old['total_cents'],'lines':json.loads(dumps(old['lines']))}
            o.setdefault('review_history',[]).append(entry);o['review_return']={k:v for k,v in entry.items() if k not in ('lines','settlement')}
            o.update(state='negotiation',settlement={'reason':'出纳退回重算：'+reason},review=None,total_cents=0,version=old['version']+1,updated_at=now())
            for l in o['lines']:l.update(bill_qty=None,amount_cents=0)
            order_corrections.invalidate(c,old,reason,role,now,audit)
            save(c,o);audit(c,role,'出纳退回会计重算',oid,old,o)
        elif action=='review':
            erp_access.require_role(role,'finance.review')
            resources_costs.open_period(c,old['business_date'])
            if old['state']!='ready': raise ValueError('仅待复核单据可以复核')
            if body.get('evidence_checked') is not True: raise ValueError('请先对照原始凭据核对重量、扣皮、价格和金额')
            o=json.loads(dumps(old)); o.update(state='reviewed',review={'at':now(),'role':role,'note':clean(body.get('note',''),'复核备注',500,False)},version=old['version']+1,updated_at=now())
            o.setdefault('review_history',[]).append({'id':'RV-'+secrets.token_hex(6),'status':'approved','at':now(),'role':role,'note':o['review']['note'],'source_version':old['version'],'total_cents':old['total_cents']})
            save(c,o); audit(c,role,'出纳复核通过，应收入账',oid,old,o)
            affected=inventory.allocate_credits(c,now)
            if affected:audit(c,role,'将退货余额抵入已复核账单',oid,None,{'orders':affected})
        elif action=='void-receipt':
            # 受控冲销：不删原流水，只标记作废并回退账单已收金额，原因与操作人留在流水和审计里。
            erp_access.require_role(role,'finance.receipt')
            rid=clean(body.get('receipt_id'),'收款编号',40)
            row=c.execute('SELECT payload FROM receipts WHERE id=?',(rid,)).fetchone()
            if not row:raise ValueError('收款记录不存在')
            receipt=json.loads(row[0])
            if receipt.get('voided'):raise ValueError('该收款已冲销')
            if receipt.get('order_id')!=oid:raise ValueError('收款与账单不匹配')
            resources_costs.open_period(c,str(receipt.get('received_date') or '')[:10])
            reason=clean(body.get('reason'),'冲销原因',200)
            if not reason.strip():raise ValueError('请填写冲销原因')
            amount=int(receipt.get('amount_cents') or 0);discount=int(receipt.get('discount_cents') or 0);rounding=int(receipt.get('rounding_cents') or 0)
            if old.get('paid_cents',0)<amount or old.get('discount_cents',0)<discount or old.get('rounding_cents',0)<rounding:
                raise ValueError('账单已收金额小于该笔收款，无法冲销，请核对')
            if old.get('state')!='reviewed':raise ValueError('只有已复核账单可以冲销收款')
            voided={**receipt,'voided':True,'void_reason':reason,'voided_at':now(),'voided_by':role,'version':int(receipt.get('version',0))+1}
            c.execute('UPDATE receipts SET payload=? WHERE id=?',(dumps(voided),rid))
            o=old.copy();o.update(paid_cents=old['paid_cents']-amount,discount_cents=old.get('discount_cents',0)-discount,rounding_cents=old.get('rounding_cents',0)-rounding,version=old['version']+1,updated_at=now())
            save(c,o)
            # 冲销后账单重新出现应收，未用完的退货抵扣按同一规则补抵，避免客户余额长期挂账。
            affected=inventory.allocate_credits(c,now)
            if affected:audit(c,role,'冲销收款后补抵退货余额',oid,None,{'orders':affected})
            # 冲销后把截图退回可登记状态、释放交易号，允许更正后的同一笔到账重新登记；原收款与审计仍保留。
            released=receipt_ocr.release(c,rid)
            audit(c,role,'冲销收款',oid,old,{'order':o,'receipt':voided,'reason':reason,'credited_orders':affected,'released_evidence':released})
        elif action=='receipt':
            erp_access.require_role(role,'finance.receipt')
            if old['state']!='reviewed': raise ValueError('账单须先经出纳复核才可收款')
            amount=dec(body.get('amount'),'收款金额','100000000')
            if amount.as_tuple().exponent < -2: raise ValueError('收款金额最多2位小数')
            cents=money(amount)
            adjustments={}
            for key,label in [('discount','折扣'),('rounding','抹零')]:
                value=dec(body.get(key,'0'),label+'金额','100000000')
                if value.as_tuple().exponent < -2:raise ValueError(label+'金额最多2位小数')
                adjustments[key+'_cents']=money(value)
            reduction=cents+sum(adjustments.values())
            if reduction<=0:raise ValueError('到账、折扣和抹零合计必须大于0')
            if reduction>inventory.balance(old): raise ValueError('到账、折扣和抹零合计不能超过此账单未收余额')
            if sum(adjustments.values()) and not str(body.get('note','')).strip():raise ValueError('有折扣或抹零时请填写原因或凭据备注')
            evidence_id=str(body.get('evidence_id') or '').strip()
            evidence=None;transaction_no=''
            if evidence_id:
                evidence=receipt_ocr.get(c,evidence_id)
                receipt_ocr.ensure_linkable(evidence,oid)
                try:shot_fields=json.loads(evidence.get('fields_json') or '{}')
                except (TypeError,ValueError):shot_fields={}
                shot_tx=str(shot_fields.get('transaction_no') or '').strip()
                body_tx=str(body.get('transaction_no') or '').strip()
                if body_tx and shot_tx and receipt_ocr.normalize_tx(body_tx)!=receipt_ocr.normalize_tx(shot_tx):
                    raise ValueError('交易单号与截图不一致，请核对原图')
                transaction_no=body_tx or shot_tx
                shot_amount=shot_fields.get('amount_cents')
                if shot_amount and int(shot_amount)!=cents and body.get('evidence_confirmed') not in (True,1,'1','true','on'):
                    raise ValueError('截图金额与本次到账金额不一致，请核对原图并勾选确认')
            else:
                transaction_no=str(body.get('transaction_no') or '').strip()
            if len(transaction_no)>64:raise ValueError('交易单号过长')
            if transaction_no:
                existing=receipt_ocr.transaction_exists(c,transaction_no)
                if existing:raise ValueError('该交易单号已登记于收款 '+(existing.get('receipt_id') or ''))
            received_date=valid_date(body.get('received_date'))
            if received_date>datetime.now(TZ).date().isoformat():raise ValueError('到账日期不能晚于今天')
            resources_costs.open_period(c,received_date)
            receipt={'id':'RC-'+secrets.token_hex(5).upper(),'order_id':oid,'customer_id':old['customer_id'],'customer_name':old['customer_name'],
              **adjustments,'account_id':resources_costs.fund_account(c,body),'amount_cents':cents,'received_date':received_date,'method':clean(body.get('method'),'收款方式',40),
              'note':clean(body.get('note',''),'收款备注',500,False),'at':now(),'role':role}
            if evidence:receipt['evidence_id']=evidence_id
            if transaction_no:receipt['transaction_no']=transaction_no
            c.execute('INSERT INTO receipts(id,payload) VALUES(?,?)',(receipt['id'],dumps(receipt)))
            if evidence:receipt_ocr.link(c,evidence_id,receipt['id'],oid,now())
            if transaction_no:receipt_ocr.record_transaction(c,transaction_no,receipt['id'],oid,now())
            o=old.copy(); o.update({k:old.get(k,0)+v for k,v in adjustments.items()}); o.update(paid_cents=old['paid_cents']+cents,version=old['version']+1,updated_at=now())
            save(c,o); audit(c,role,'登记收款',oid,old,{'order':o,'receipt':receipt})
        else: raise ValueError('未知操作')
        return get_order(c,o['id'])

def batch_mutate(body, role):
    """A sheet saves as one transaction, including revisions and customer settlements."""
    operations=body.get('operations')
    if not isinstance(operations,list) or not 1 <= len(operations) <= 200:
        raise ValueError('批量操作须包含1至200笔单据')
    seen=set();results=[];issues=[]
    with connect(True) as c:
        check_business_epoch(c,body)
        for index,item in enumerate(operations):
            if not isinstance(item,dict): raise ValueError('批量操作格式错误')
            action=item.get('action');oid=item.get('order_id');payload=item.get('body',{})
            if action not in ('order','settle','review','return-review','negotiate','confirm-weight') or not isinstance(payload,dict):
                raise ValueError('批量操作类型无效')
            payload={**payload,'_data_epoch':body.get('_data_epoch','0')}
            if oid:
                if not isinstance(oid,str) or oid in seen: raise ValueError('同一单据不能在一个批次中重复操作')
                seen.add(oid)
            elif action!='order': raise ValueError('请指定要操作的单据')
            try:
                if item.get('update') is not None:
                    if action not in ('settle','confirm-weight') or not isinstance(item['update'],dict): raise ValueError('仅称重确认或算票可以同时保存录入数据')
                    if payload.get('version')!=item['update'].get('version'): raise ValueError('修订号不一致，请刷新后重试')
                    updated=mutate('order',{**item['update'],'_data_epoch':body.get('_data_epoch','0')},role,oid,connection=c)
                    payload={**payload,'version':updated['version']}
                if action=='settle' and payload.get('confirm_accounting_entry') is True:
                    if payload.get('evidence_checked') is not True:raise ValueError('请勾选已核对司机照片、重量和框数')
                    current=get_order(c,oid)
                    if not current.get('weight_confirmation'):
                        confirmed=mutate('confirm-weight',{'version':current['version'],'evidence_checked':True,'dispatch_required':True,'_data_epoch':body.get('_data_epoch','0')},role,oid,connection=c)
                        payload={**payload,'version':confirmed['version']}
                results.append(mutate(action,payload,role,oid,connection=c))
            except ValidationError as e:issues.extend(e.issues)
            except ValueError as e:
                context=get_order(c,oid) if oid else payload
                issues.append(field_issue(context,None,'order',str(e)))
        if issues:raise ValidationError(issues)
    return {'orders':results,'count':len(results)}

def init_db(demo=True, *, convert_billing=False):
    DB.parent.mkdir(parents=True,exist_ok=True)
    if DB.parent==ROOT/'data':DB.parent.chmod(0o700)
    if DB.exists():DB.chmod(0o600)
    import migrations
    with connect(True) as c:
        initialized=c.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone() and c.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone()
        migrations.upgrade(c,context={'demo':demo,'now':now,'audit':audit},kilograms=convert_billing)
    if demo and not initialized:seed_demo()


def seed_demo():
    today=datetime.now(TZ).date().isoformat()
    def make(cid,pid,qty,price,driver=None,customer=None,actual=None):
        return mutate('order',{'customer_id':cid,'business_date':today,'batch':'夜间配送 · 演示','note':'虚构演示业务，请勿作为正式账目',
          'lines':[{'product_id':pid,'ordered_qty':str(qty),'actual_qty':str(qty if actual is None else actual),'price':price,'driver':driver or [],'customer':customer or []}]},'库管')
    o=make('C001','P001',12,'3.60',[{'gross':'266.6','count':'12','tare':'1.8'}],[{'gross':'263','count':'12','tare':'1.8'}])
    o=mutate('settle',{'version':o['version'],'mode':'customer','reason':'演示：人工确认接受客户复称'},'会计',o['id'])
    o=mutate('review',{'version':o['version'],'evidence_checked':True,'note':'演示：模拟核对原始记录'},'出纳',o['id'])
    mutate('receipt',{'version':o['version'],'amount':'500','received_date':today,'method':'银行转账','note':'虚构演示收款'},'出纳',o['id'])
    o=make('C002','P001',8,'3.50',[{'gross':'175','count':'8','tare':'1.7'}],[{'gross':'167','count':'8','tare':'1.7'}])
    mutate('negotiate',{'version':o['version'],'reason':'演示：两次净重相差8公斤，等待人工协商，不设置自动阈值'},'会计',o['id'])
    o=make('C003','P004',10,'75')
    mutate('settle',{'version':o['version'],'mode':'customer','reason':'演示：按实际包数计价'},'会计',o['id'])
    make('C001','P003',6,'6.20',actual=0)

def next_customer_id(c):
    numbers=[int(row[0][1:]) for row in c.execute('SELECT id FROM customers') if re.fullmatch(r'C[0-9]+',row[0])]
    return 'C'+str(max(numbers,default=0)+1).zfill(3)

def rc_factor(c,pid):return resources_costs.ds(cost_allocation.factor(c,pid,datetime.now(TZ).strftime('%Y-%m')))

def ordered_products(c):
    products=[{**dict(r),'billing_unit':trade.product_billing(c,r),'fractional':next((u['fractional'] for u in trade.units(c) if u['id']==r['unit']),False),'supply_kind':trade.product_config(c,r).get('supply_kind','self'),'supplier_ids':trade.product_config(c,r).get('supplier_ids',[]),'crate_type_ids':[v['id'] for v in crate_accounting.variants(c,r['id'])],'crate_tares':crate_accounting.product_tares(c,r['id']),'main_material':production_management.daily.main_material(c,r),'grinding_system':production_management.daily.grinding_system(c,r),'processing_intensity':rc_factor(c,r['id']),'intensity_history':cost_allocation.factor_history(c,r['id']),'default_average_kg':production_management.product_average(c,r)} for r in c.execute('SELECT * FROM products ORDER BY id')]
    row=c.execute("SELECT value FROM meta WHERE key='product_display_order'").fetchone()
    order=json.loads(row[0]) if row else []
    positions={pid:i for i,pid in enumerate(order)}
    return sorted(products,key=lambda p:positions.get(p['id'],len(positions)))

def save_product_order(body,role):
    erp_access.require_role(role,'master.products.write')
    ids=body.get('product_ids')
    with connect(True) as c:
        current=[p['id'] for p in ordered_products(c)]
        if not isinstance(ids,list) or not all(isinstance(pid,str) for pid in ids) or len(ids)!=len(current) or len(set(ids))!=len(ids) or set(ids)!=set(current):
            raise ValueError('排序必须包含全部产品，不能重复或遗漏；请同步产品列表后重试')
        if body.get('expected')!=current:raise ValueError('产品列表或顺序已在其他页面变化，请点击「同步产品列表」后重新排序')
        if ids!=current:
            c.execute("INSERT INTO meta VALUES('product_display_order',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(ids),))
            audit(c,role,'调整产品顺序','products',current,ids)
        return {'ok':True,'product_ids':ids}

BOOTSTRAP_ENTRY_DAYS=31

def bootstrap_resources(c,*,include_expense_history=True,include_byproduct_history=True):
    """登录 bootstrap 的材料投影：流水只带最近 BOOTSTRAP_ENTRY_DAYS 天（外加入库批次未耗尽的入库行），
    历史流水走 /api/material-history 分页接口。条目字段与数值一律原样保留，不做任何改写。
    同时下发工作台必要的紧凑投影，避免前端为一天的数据拉全部历史：
    - warehouse_stocks[*].has_entries / items[*].has_entries：是否发生过流水（等价 material_query.stock 的 touched）；
    - bean_days：[{business_date,source,qty}] RM-SOY 领用退回净量，source 复刻 productionSource 回退；
    - consume_days：RM-SOY 领用（kind=consume）出现过的业务日期，供工作台“有领用的日期”列表；
    - entry_days：[{business_date,count}] 每个有（未作废）流水的业务日期及条数，工作台判断窗口外日期
      是否已登记业务，避免按被裁剪的 entries 误报待办；
    - pending_valuations：未作废且未填金额的入库类流水（工作台待办）；
    - entries_window：{days,start,kept,total} 供前端判断窗口。
    """
    value=resources_costs.snapshot(c,include_expense_history=include_expense_history,include_byproduct_history=include_byproduct_history)
    entries=value.get('entries') or []
    touched={(e.get('material_id'),e.get('warehouse_id')) for e in entries}
    touched.update((e.get('material_id'),e.get('target_warehouse_id')) for e in entries if e.get('target_warehouse_id'))
    for row in value.get('warehouse_stocks') or []:row['has_entries']=(row.get('id'),row.get('warehouse_id')) in touched
    material_touched={mid for mid,_ in touched}
    for row in value.get('items') or []:row['has_entries']=row.get('id') in material_touched
    # 大豆批次属性弹窗（web/factory.js data-soy-quality）按 lot_id 在 entries 里取原入库行，因此
    # 未耗尽黄豆批次的入库行不按日期裁剪；更早日期耗尽的批次由前端按 /api/material-history 兜底读取。
    # 其他物料不提供批次编辑入口，只随窗口下发。
    soy_ids={e.get('id') for e in entries if e.get('material_id')=='RM-SOY'}
    soy_lots={lot.get('lot_id') for row in value.get('warehouse_stocks') or [] for lot in row.get('lots') or []
              if row.get('id')=='RM-SOY' and lot.get('lot_id') in soy_ids}
    start=(datetime.now(TZ).date()-timedelta(days=BOOTSTRAP_ENTRY_DAYS-1)).isoformat()
    kept=[e for e in entries if str(e.get('business_date') or '')>=start or e.get('id') in soy_lots]
    bean_days={}
    consume_days=set()
    entry_days={}
    pending=[]
    for e in entries:
        if e.get('voided'):continue
        kind=e.get('kind')
        day=e.get('business_date') or ''
        if day:entry_days[day]=entry_days.get(day,0)+1
        if e.get('material_id')=='RM-SOY':
            if kind=='consume':consume_days.add(e.get('business_date'))
            if kind in ('consume','return'):
                source=e.get('production_system_id')
                if source is None:source={'WH-TOFU':'tofu','WH-SKIN':'skin'}.get(e.get('warehouse_id'),'')
                key=(e.get('business_date') or '',source)
                bean_days[key]=bean_days.get(key,Decimal(0))+(Decimal(1) if kind=='consume' else Decimal(-1))*Decimal(str(e.get('qty')))
        if kind in ('opening','receipt','return','gain') and not e.get('amount_cents'):
            pending.append({k:e.get(k) for k in ('id','business_date','material_id','material_name','kind','qty','unit','warehouse_id','warehouse_name','handler','reference','version')})
    value['bean_days']=[{'business_date':day,'source':source,'qty':ds(qty)} for (day,source),qty in sorted(bean_days.items())]
    value['consume_days']=sorted(day for day in consume_days if day)
    value['entry_days']=[{'business_date':day,'count':count} for day,count in sorted(entry_days.items())]
    value['pending_valuations']=pending
    value['entries_window']={'days':BOOTSTRAP_ENTRY_DAYS,'start':start,'kept':len(kept),'total':len(entries)}
    value['entries']=kept
    return value

# 与 erp_access.scope_resources 的材料可见性判定保持一致（见 erp_access.py:531）。
RESOURCE_MODULES={'inventory.materials','workspace.analytics','inventory.cost','purchase.orders','purchase.receipts','production.inventory','production.daily','production.manage','production.issue','production.workshop'}

def scope_bootstrap_entries(result,user):
    """scope_resources 只清理 items/entries/warehouse_stocks/voided_entries；工作台的紧凑投影
    （bean_days/consume_days/pending_valuations/entries_window）按同一材料可见性一起清空，
    避免没有材料权限的角色经 bootstrap 拿到越权数据。"""
    resources=result.get('resources')
    if not isinstance(resources,dict) or not resources:return result
    modules=set((user.get('permissions') or {}).get('modules') or [])
    if not modules & RESOURCE_MODULES:
        for key in ('bean_days','consume_days','entry_days','pending_valuations','entries_window'):resources.pop(key,None)
    return result

EMPLOYEE_HTTP_OMIT=('request_fingerprint','updated_at','version')
def factory_bootstrap(c,*,light=False,include_production_configs=True):
    # 人员列表只下发页面实际读取的字段；指纹/更新时间/版本号仅服务端并发使用，前端无引用。
    snap=production_management.snapshot(c,light=light,include_production_configs=include_production_configs)
    snap['employees']=[{k:v for k,v in e.items() if k not in EMPLOYEE_HTTP_OMIT} for e in snap.get('employees',[])]
    return snap

def bootstrap(*, include_expense_history=True, include_byproduct_history=True, factory_light=False, include_audit=None):
    # 登录态默认不再随 bootstrap 下发审计最近200条：登录后订单详情按对象读取 /api/audit，
    # 匿名/演示态仍需这批行渲染“最近操作”。未显式传入时跟随 factory_light（登录态即不含）。
    if include_audit is None:include_audit=not factory_light
    with connect() as c:
        orders=[json.loads(r[0]) for r in c.execute('SELECT payload FROM orders ORDER BY rowid DESC')]
        photo_map={}
        try:
            for r in c.execute('SELECT order_id,kind,at FROM driver_photos'):photo_map.setdefault(r['order_id'],{})[r['kind']]=r['at']
        except sqlite3.OperationalError:pass
        for o in orders:
            o['status']=status(o);o['delivery_method']=order_delivery_method(c,o);o['driver_photos']=photo_map.get(o['id'],{})
        demo_row=c.execute("SELECT value FROM meta WHERE key='preview_demo'").fetchone()
        return {'company':__import__('company').current(c),'fund_accounts':__import__('funds').account_catalog(c),'app_version':APP_VERSION,'finished_goods_inventory':finished_goods.inventory_projection(c),'finished_goods_supply':[{'business_date':r['business_date'],'product_id':l['product_id'],'qty':l['qty']} for r in finished_goods.records(c,'receipt') if not r.get('voided') for l in r['lines']],'crate_tare_rules':crate_accounting.rules(c),'product_crate_attributes':{p['id']:crate_accounting.variants(c,p['id']) for p in c.execute('SELECT id FROM products')},'trade_units':trade.units(c),'crate_types':trade.crate_types(c),'crate_shipments':trade.records(c,'shipment'),'delivery_feedback':trade.records(c,'feedback'),'weighing_settings':{'average_weight_alert_pct':production_management.settings(c)['average_weight_alert_pct'],'average_weight_alert_kg':production_management.settings(c)['average_weight_alert_kg']},'demo_context':json.loads(demo_row[0]) if demo_row else None,'factory':factory_bootstrap(c,light=factory_light,include_production_configs=False),'weight_analysis':production_management.weight_report(c),'receivable_alerts':production_management.ar_alerts(c,datetime.now(TZ).date().isoformat()),'purchasing':purchasing.projection(c),'resources':bootstrap_resources(c,include_expense_history=include_expense_history,include_byproduct_history=include_byproduct_history),'customers':[dict(r) for r in c.execute('SELECT * FROM customers ORDER BY id')],
          'products':ordered_products(c),
          'rules':[dict(r) for r in c.execute('SELECT * FROM rules')], 'orders':orders,
          'statement_documents':[{'voided':bool(order_corrections.void_info(c,r['id'])),'document_id':r['id'],'customer_id':r['customer_id'],'business_date':r['business_date'],'issued_at':r['issued_at'],'source_order_ids':[o['id'] for o in json.loads(r['payload']).get('current',[])]} for r in c.execute('SELECT id,customer_id,business_date,issued_at,payload FROM statement_documents ORDER BY issued_at DESC,rowid DESC')],
          'receipts':[json.loads(r[0]) for r in c.execute("SELECT payload FROM receipts WHERE COALESCE(json_extract(payload,'$.voided'),0)=0 ORDER BY rowid DESC")],
          'audit':([dict(r) for r in c.execute('SELECT id,at,role,action,entity,actor_id,actor_name,request_id FROM audit ORDER BY id DESC LIMIT 200')] if include_audit else []),
          'delivery_markets':[dict(r) for r in c.execute('SELECT * FROM delivery_markets ORDER BY id')],
          'delivery_vehicles':[dict(r) for r in c.execute('SELECT * FROM delivery_vehicles ORDER BY id')],
          'delivery_drivers':[dict(r) for r in c.execute('SELECT * FROM delivery_drivers ORDER BY id')],
          'dispatch_plans':[json.loads(r[0]) for r in c.execute('SELECT payload FROM dispatch_plans ORDER BY business_date')],
          'warehouse_plans':[order_corrections.effective_plan(c,json.loads(r[0])) for r in c.execute('SELECT payload FROM warehouse_plans ORDER BY business_date')],
          'sales_returns':inventory.rows(c,'sales_returns'),'processing_batches':inventory.rows(c,'processing_batches'),'curing':__import__('curing').records(c),'processing_rules':inventory.processing_rules(c),'stock_closings':[order_corrections.restated_closing(c,r) for r in inventory.rows(c,'stock_closings')],'inventory_revision':inventory.revision(c),
          'business_data_epoch':business_epoch(c),'trial_archives':[{k:v for k,v in dict(r).items() if k!='payload'}|{'counts':json.loads(r['payload'])['counts'],'scope':json.loads(r['payload']).get('scope','all'),'business_date':json.loads(r['payload']).get('business_date',''),'format':json.loads(r['payload']).get('format','legacy')} for r in c.execute("SELECT * FROM trial_archives WHERE json_extract(payload,'$.format')='day-reset-v1' ORDER BY at DESC")],
          'operator_users':[dict(r) for r in c.execute('SELECT * FROM operator_users ORDER BY role,id')],'settlement_unit':'公斤' if billing.enabled(c) else 'legacy','access_catalog':erp_access.catalog(),'next_customer_id':next_customer_id(c),'capabilities':['material-consumption-v1','production-directory-v1','material-source-allocation-v1','expense-payables-v1','receipt-adjustments-v1','receipt-evidence-v1','separate-documents-v1','resources-costs-v1','purchasing-v1','material-warehouses-v1','purchase-landed-cost-v1','purchase-payees-v1','detailed-role-policy-v1'],'api_version':3,'today':datetime.now(TZ).date().isoformat(),'data_package_missing':(__import__('data_package').missing(c) if c else []),'mode':'本机业务服务','currency':'CNY'}

def evidence_actor(user=None, role=''):
    if user:return user
    role=role or '管理员'
    return {'id':'pilot-'+role,'display_name':role,'role':role,'permissions':erp_access.defaults(role)}

def receipt_ocr_settings_get(actor):
    if not actor or actor.get('role')!='管理员':raise auth.AuthError(403,'仅管理员可配置截图识别服务')
    with connect() as c:return receipt_ocr.settings_public(c,DB)

def receipt_ocr_settings_save(body,actor):
    if not actor or actor.get('role')!='管理员':raise auth.AuthError(403,'仅管理员可配置截图识别服务')
    with connect(True) as c:
        before=receipt_ocr.settings_public(c,DB)
        result=receipt_ocr.save_settings(c,body,DB)
        audit(c,actor.get('role'),'配置收款截图识别','receipt_ocr',before,result)
    return result

def recognize_receipt_evidence(body,actor):
    if not receipt_ocr.can_recognize(actor):raise auth.AuthError(403,'当前岗位无收款截图识别权限')
    prepared=receipt_ocr.prepare(body)
    order_id=str(body.get('order_id') or '').strip()
    if len(order_id)>40:raise ValueError('订单编号无效')
    if order_id:
        with connect() as c:get_order(c,order_id)
    with connect() as c:cfg=receipt_ocr.settings(c,DB)
    with connect(True) as c:evidence=receipt_ocr.begin(c,prepared,order_id,actor,now())
    if evidence.get('conflict'):return evidence
    if evidence.get('duplicate') and evidence.get('status')!='processing':return evidence
    try:analysis=receipt_ocr.analyze(prepared,cfg,DB)
    except Exception as exc:analysis=receipt_ocr.failure(receipt_ocr._safe_error(exc,cfg))
    with connect(True) as c:
        result=receipt_ocr.finish(c,evidence['id'],analysis,now())
        audit(c,actor.get('role'),'识别收款截图',result['id'],None,{'status':result['status'],'engine':result['engine'],'confidence':result['confidence']})
    return result

def receipt_evidence_get(evidence_id,actor):
    if not receipt_ocr.can_view(actor):raise auth.AuthError(403,'当前岗位无权查看收款凭据')
    with connect() as c:row=receipt_ocr.get(c,evidence_id)
    if not row:raise auth.AuthError(404,'收款凭据不存在')
    return receipt_ocr.public(row)

def receipt_evidence_image(evidence_id,actor):
    if not receipt_ocr.can_view(actor):raise auth.AuthError(403,'当前岗位无权查看收款凭据')
    with connect() as c:data=receipt_ocr.image(c,evidence_id)
    if not data:raise auth.AuthError(404,'收款凭据原图不存在')
    return data

def discard_receipt_evidence(evidence_id,actor):
    if not receipt_ocr.can_recognize(actor):raise auth.AuthError(403,'当前岗位无权删除收款截图')
    with connect(True) as c:
        row=receipt_ocr.get(c,evidence_id)
        if not row:raise auth.AuthError(404,'收款凭据不存在')
        result=receipt_ocr.discard(c,evidence_id)
        audit(c,actor.get('role'),'删除未登记收款截图',evidence_id,{'filename':row['filename'],'order_id':row['order_id'],'status':row['status']},None)
    return result

def business_epoch(c):
    row=c.execute("SELECT value FROM meta WHERE key='business_data_epoch'").fetchone()
    return row[0] if row else '0'

def check_business_epoch(c,body):
    if str(body.get('_data_epoch','0'))!=business_epoch(c):raise ValueError('试运行业务数据已经清理或恢复，请刷新页面；旧页面草稿不能重新提交')

def trial_data(body,role):
    erp_access.require_role(role,'system.archive')
    with connect(True) as c:
        check_business_epoch(c,body)
        if body.get('action')=='archive':
            tables=['orders','receipts','archived_orders']
            rows={table:[dict(r) for r in c.execute('SELECT * FROM '+table)] for table in tables}
            counts={table:len(rows[table]) for table in tables}
            if body.get('expected')!=counts:raise ValueError('业务记录数量已有变化，请重新核对后清理')
            inventory_rows={t:[dict(r) for r in c.execute('SELECT * FROM '+t)] for t in ('sales_returns','processing_batches','stock_closings','factory_runs','factory_scrap','factory_daily')}
            if not any(counts.values()) and not any(inventory_rows.values()) and not c.execute('SELECT 1 FROM warehouse_plans').fetchone():raise ValueError('当前没有需要归档的试运行业务数据')
            reason=clean(body.get('reason'),'清理说明',500)
            key='TRIAL-'+datetime.now(TZ).strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)
            warehouse=[dict(r) for r in c.execute('SELECT * FROM warehouse_plans')]
            c.execute('INSERT INTO trial_archives VALUES(?,?,?,?,NULL)',(key,dumps({'rows':rows,'counts':counts,'warehouse_plans':warehouse,'inventory_rows':inventory_rows,'settlement_unit':'公斤' if billing.enabled(c) else 'legacy'}),now(),reason))
            for table in tables:c.execute('DELETE FROM '+table)
            c.execute('DELETE FROM warehouse_plans')
            for table in inventory_rows:c.execute('DELETE FROM '+table)
            inventory.bump(c)
            audit(c,role,'清理试运行业务数据（整轮归档，可恢复）',key,counts,{'orders':0,'receipts':0})
        elif body.get('action')=='restore':
            key=clean(body.get('id'),'归档编号',80)
            row=c.execute('SELECT * FROM trial_archives WHERE id=?',(key,)).fetchone()
            if not row or row['restored_at']:raise ValueError('该轮数据不存在或已经恢复')
            for table in ['orders','receipts','archived_orders','warehouse_plans','sales_returns','processing_batches','stock_closings','factory_runs','factory_scrap','factory_daily']:
                if c.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():raise ValueError('当前已有业务数据，不能覆盖；如需切换，请先将当前一轮数据归档')
            snapshot=json.loads(row['payload']);counts=snapshot['counts']
            if snapshot.get('format')=='day-reset-v1':raise ValueError('按日期归档请使用管理员的按日恢复入口')
            if billing.enabled(c) and snapshot.get('settlement_unit')!='公斤':raise ValueError('此归档采用旧包价口径，不能直接恢复到公斤结算环境；请使用清理前数据库备份另行核对')
            for table,rows in snapshot['rows'].items():
                if table not in ('orders','receipts','archived_orders'):raise ValueError('归档格式无效')
                for r in rows:
                    columns=list(r)
                    c.execute('INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(r.values()))
            for r in snapshot.get('warehouse_plans',[]):
                c.execute('INSERT INTO warehouse_plans VALUES(?,?)',(r['business_date'],r['payload']))
            for table,items in snapshot.get('inventory_rows',{}).items():
                if table not in ('sales_returns','processing_batches','stock_closings','factory_runs','factory_scrap','factory_daily'):raise ValueError('库存归档格式无效')
                for item in items:
                    row_key='business_date' if table=='stock_closings' else 'id'
                    if table in ('factory_runs','factory_scrap','factory_daily'):c.execute('INSERT INTO '+table+'(id,request_key,payload) VALUES(?,?,?)',(item['id'],item['request_key'],item['payload']))
                    else:c.execute('INSERT INTO '+table+'('+row_key+',payload) VALUES(?,?)',(item[row_key],item['payload']))
            inventory.bump(c)
            c.execute('UPDATE trial_archives SET restored_at=? WHERE id=?',(now(),key))
            audit(c,role,'恢复整轮试运行业务数据',key,None,counts)
        else:raise ValueError('试运行数据操作无效')
        epoch=secrets.token_hex(12)
        c.execute("INSERT INTO meta VALUES('business_data_epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(epoch,))
        return {'id':key,'counts':counts,'business_data_epoch':epoch,'action':body['action']}

def duplicate_order_archive(body,role,connection=None):
    erp_access.require_role(role,'system.archive')
    if body.get('action')=='archive_many':
        rows=body.get('orders')
        if not isinstance(rows,list) or not 1<=len(rows)<=100 or len({r.get('id') for r in rows})!=len(rows):raise ValueError('请选择1至100张不同的重复订货单')
        with (nullcontext(connection) if connection is not None else connect(True)) as c:
            result=[duplicate_order_archive({**r,'action':'archive'},role,c) for r in rows]
        return {'orders':result,'count':len(result)}
    oid=clean(body.get('id'),'单号',80)
    with (nullcontext(connection) if connection is not None else connect(True)) as c:
        if body.get('action')=='restore':
            row=c.execute('SELECT * FROM archived_orders WHERE id=?',(oid,)).fetchone()
            if not row:raise ValueError('该单已恢复或不存在，请同步最新数据')
            if c.execute('SELECT 1 FROM orders WHERE id=?',(oid,)).fetchone():raise ValueError('原单号已存在，不能覆盖')
            restored=json.loads(row['payload']);inventory.open_day(c,restored['business_date'])
            c.execute('INSERT INTO orders VALUES(?,?)',(oid,row['payload']))
            inventory.validate_book(c,restored['business_date'],True);inventory.bump(c)
            c.execute('DELETE FROM archived_orders WHERE id=?',(oid,))
            audit(c,role,'恢复已归档重复订货',oid,None,json.loads(row['payload']))
            return {'id':oid,'restored':True}
        if body.get('action')!='archive':raise ValueError('归档操作无效')
        row=c.execute('SELECT payload FROM orders WHERE id=?',(oid,)).fetchone()
        if not row:raise ValueError('订单不存在或已归档，请同步最新数据')
        o=json.loads(row[0]);kept_id=clean(body.get('kept_id'),'保留单号',80)
        kept=c.execute('SELECT payload FROM orders WHERE id=?',(kept_id,)).fetchone()
        if not kept or kept_id==oid:raise ValueError('请选择另一张有效的保留订单')
        kept=json.loads(kept[0])
        if o['version']!=body.get('version'):raise ValueError('该单已变化，请同步后核对')
        if o['state']!='draft' or o.get('paid_cents') or o.get('settlement') or any(Decimal(l['actual_qty']) or l.get('driver') or l.get('customer') for l in o['lines']):raise ValueError('已有实发、称重或结算的原单不能作为空白重复订货归档')
        quantities=lambda x:sorted((l['product_id'],Decimal(l['ordered_qty'])) for l in x['lines'])
        if o['customer_id']!=kept['customer_id'] or o['business_date']!=kept['business_date'] or quantities(o)!=quantities(kept):raise ValueError('客户、日期和订货数量必须与保留订单一致，请人工核对')
        reason=clean(body.get('reason'),'归档原因',500)
        inventory.open_day(c,o['business_date']);inventory.bump(c)
        c.execute('INSERT INTO archived_orders VALUES(?,?,?,?,?)',(oid,row[0],kept_id,reason,now()))
        c.execute('DELETE FROM orders WHERE id=?',(oid,))
        audit(c,role,'归档重复订货（可恢复）',oid,o,{'kept_id':kept_id,'reason':reason})
        return {'id':oid,'archived':True,'kept_id':kept_id}

def master(body,role,connection=None):
    kind=body.get('kind')
    erp_access.require_role(role,erp_access.master_permission(kind))
    with (nullcontext(connection) if connection is not None else connect(True)) as c:
        if kind in ('delivery_market','delivery_vehicle'):
            table='delivery_markets' if kind=='delivery_market' else 'delivery_vehicles'
            prefix='M' if kind=='delivery_market' else 'V'
            name=clean(body.get('name'),'市场 / 配送点名称' if prefix=='M' else '车辆名称',50)
            if c.execute(f'SELECT 1 FROM {table} WHERE name=?',(name,)).fetchone():raise ValueError('名称已存在，请直接使用已有档案')
            numbers=[int(r[0][1:]) for r in c.execute(f'SELECT id FROM {table}') if re.fullmatch(prefix+r'[0-9]+',r[0])]
            key=prefix+str(max(numbers,default=0)+1).zfill(3)
            values={'id':key,'name':name}
            if prefix=='M':
                values['city']=clean(body.get('city'),'城市 / 区域',40)
                values['kind']=body.get('point_kind','market')
                if values['kind'] not in ('market','independent'):raise ValueError('请选择市场或独立配送点')
                c.execute('INSERT INTO delivery_markets(id,name,city,kind) VALUES(?,?,?,?)',(key,name,values['city'],values['kind']))
            else:
                values['vehicle_type']=clean(body.get('vehicle_type'),'车辆类型',20) if body.get('vehicle_type') else ''
                c.execute('INSERT INTO delivery_vehicles(id,name,vehicle_type) VALUES(?,?,?)',(key,name,values['vehicle_type']))
            audit(c,role,'新增配送点' if prefix=='M' else '新增车辆',key,None,values)
        elif kind=='customer':
            # Allocate inside the write transaction: simultaneous additions cannot reuse an ID.
            auto=body.get('create') is True or not body.get('id')
            cid=next_customer_id(c) if auto else clean(body.get('id'),'客户编号',30)
            name=clean(body.get('name'),'客户名称',80)
            before=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone()
            if 'expected' in body and body['expected']!=(dict(before) if before else None):raise ValueError('客户档案已被其他页面修改，请重新打开核对最新数据')
            if body.get('create') is False and not before:raise ValueError('客户不存在，请刷新客户列表')
            legal_name=clean(body.get('legal_name',before['legal_name'] if before else ''),'营业执照名称 / 姓名',120,False)
            method=body.get('delivery_method',before['delivery_method'] if before else 'delivery')
            if method not in ('delivery','pickup'):raise ValueError('请选择配送或自取')
            note=clean(body.get('note',''),'客户备注',500,False)
            phone=clean(body.get('phone',before['phone'] if before else ''),'客户电话',40,False)
            if 'opening' not in body:
                opening_cents=int(before['opening_cents']) if before else 0
            else:
                opening_text=body.get('opening')
                opening_cents=0 if opening_text in (None,'') else resources_costs.cents(opening_text,'期初应收')
            opening_date=clean(body.get('opening_date',(before['opening_date'] if before else '')),'期初日期',10,False)
            if opening_cents:
                if not opening_date:raise ValueError('填写期初应收后请选择期初日期')
                resources_costs.day(opening_date)
                if opening_date>date.today().isoformat():raise ValueError('期初日期不能晚于今天')
            else:opening_date=''
            if 'location_kind' in body:
                region=clean(body.get('region'),'地区',40)
                location_kind=body.get('location_kind')
                if location_kind not in ('market','independent'):raise ValueError('请选择市场或独立配送点')
                mid=clean(body.get('market_id',''),'配送点编号',30,False)
                if mid:
                    point=c.execute('SELECT * FROM delivery_markets WHERE id=?',(mid,)).fetchone()
                    if not point or point['city']!=region or point['kind']!=location_kind:
                        raise ValueError('所选市场 / 配送点与地区不一致，请重新选择')
                    route=point['name']
                else:
                    route=clean(body.get('location_name'),'市场名称' if location_kind=='market' else '具体收货点 / 所在地',50)
                    # Self pickup locations need no stop in a vehicle plan.
                    if method=='delivery' or location_kind=='market':
                        point=c.execute('SELECT * FROM delivery_markets WHERE name=?',(route,)).fetchone()
                        if point and (point['city']!=region or point['kind']!=location_kind):
                            raise ValueError('已有同名配送点属于其他地区或类型，请填写更具体的名称（如“昌吉某单位”）')
                        if point:mid=point['id']
                        else:
                            numbers=[int(r[0][1:]) for r in c.execute('SELECT id FROM delivery_markets') if re.fullmatch(r'M[0-9]+',r[0])]
                            mid='M'+str(max(numbers,default=0)+1).zfill(3)
                            c.execute('INSERT INTO delivery_markets(id,name,city,kind) VALUES(?,?,?,?)',(mid,route,region,location_kind))
                            audit(c,role,'新增配送点',mid,None,{'id':mid,'name':route,'city':region,'kind':location_kind})
            else:
                # Retain compatibility with older local pages and integrations.
                route=clean(body.get('route'),'市场 / 所在地',50)
                point=c.execute('SELECT * FROM delivery_markets WHERE name=?',(route,)).fetchone()
                region=point['city'] if point else (before['region'] if before and before['route']==route else '')
                mid=point['id'] if point else ''
                location_kind=point['kind'] if point else 'independent'
            business_kind=body.get('business_kind',before['business_kind'] if before else 'sales')
            if business_kind not in ('sales','byproduct','both'):raise ValueError('客户业务类型无效')
            raw_ordering=body.get('ordering_enabled',before['ordering_enabled'] if before and 'ordering_enabled' in before.keys() else 1)
            ordering_enabled=0 if str(raw_ordering).strip().lower() in ('0','false','no','off') else 1
            values={'delivery_method':method,'id':cid,'name':name,'legal_name':legal_name,'route':route,'note':note,'business_kind':business_kind,
                    'region':region,'market_id':mid,'location_kind':location_kind,'phone':phone,'opening_cents':opening_cents,'opening_date':opening_date,
                    'ordering_enabled':ordering_enabled}
            c.execute('''INSERT INTO customers(id,name,route,note,delivery_method,region,market_id,location_kind,legal_name,opening_cents,opening_date,ordering_enabled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,route=excluded.route,note=excluded.note,
                delivery_method=excluded.delivery_method,region=excluded.region,market_id=excluded.market_id,location_kind=excluded.location_kind,legal_name=excluded.legal_name,
                opening_cents=excluded.opening_cents,opening_date=excluded.opening_date,ordering_enabled=excluded.ordering_enabled''',
                (cid,name,route,note,method,region,mid,location_kind,legal_name,opening_cents,opening_date,ordering_enabled))
            c.execute('UPDATE customers SET phone=?,business_kind=? WHERE id=?',(phone,business_kind,cid))
            audit(c,role,'新增客户' if not before else '维护客户档案',cid,dict(before) if before else None,values)
        elif kind=='product':
            pid=body.get('id')
            if not isinstance(pid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,30}',pid):raise ValidationError([field_issue({}, {'product_id':pid,'product_name':body.get('name','')},'id','产品编号请使用1至30位字母、数字、横线或下划线')])
            before=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
            current=dict(before) if before else None
            if current and isinstance(body.get('expected'),dict) and 'main_material' in body['expected']:current['main_material']=production_management.daily.main_material(c,before)
            if current and isinstance(body.get('expected'),dict) and 'grinding_system' in body['expected']:current['grinding_system']=production_management.daily.grinding_system(c,before)
            if current and isinstance(body.get('expected'),dict) and 'default_average_kg' in body['expected']:current['default_average_kg']=production_management.product_average(c,before)
            if current and isinstance(body.get('expected'),dict):
                for key,value in [('processing_intensity',rc_factor(c,pid)),('intensity_history',cost_allocation.factor_history(c,pid))]:
                    if key in body['expected']:current[key]=value
                for extra,value in [('supplier_ids',trade.product_config(c,before).get('supplier_ids',[])),('crate_type_ids',[v['id'] for v in crate_accounting.variants(c,pid)]),('crate_tares',crate_accounting.product_tares(c,pid)),('supply_kind',trade.product_config(c,before).get('supply_kind','self')),('billing_unit',trade.product_billing(c,before)),('fractional',next((u['fractional'] for u in trade.units(c) if u['id']==before['unit']),False))]:
                    if extra in body['expected']:current[extra]=value
            if 'expected' in body and body['expected']!=current:raise ValueError('产品档案已被其他页面修改，请重新打开核对最新数据')
            context={};line={'product_id':pid,'product_name':body.get('name','')};issues=[];values={}
            if body.get('create') and before:issues.append(field_issue(context,line,'id','产品编号已存在，请使用其他编号'))
            if not body.get('create') and not before:issues.append(field_issue(context,line,'id','产品不存在，请刷新产品列表'))
            try:values['name']=clean(body.get('name'),'产品名称',80)
            except ValueError as e:issues.append(field_issue(context,line,'name',str(e)))
            unit=body.get('unit')
            if unit not in {u['id'] for u in trade.units(c)}:issues.append(field_issue(context,line,'unit','请选择已登记发货单位'))
            bill_unit=body.get('billing_unit',trade.product_billing(c,before) if before else '公斤')
            if bill_unit not in ('公斤',unit):issues.append(field_issue(context,line,'billing_unit','计价单位请选择公斤或当前发货单位'))
            for key,label,maximum,positive in [('price','默认单价','100000',True),('tare','默认单筐皮重','100',False)]:
                try:values[key]=ds(dec(body.get(key),label,maximum,positive))
                except ValueError as e:issues.append(field_issue(context,line,key,str(e)))
            standard=None
            if unit!='筐':
                if values.get('tare') not in (None,'0'):issues.append(field_issue(context,line,'tare','包装产品的皮重应为0'))
                if unit=='公斤':standard='1'
                elif body.get('standard_kg') not in (None,'') or bill_unit=='公斤':
                    try:standard=ds(dec(body.get('standard_kg'),'标准包装公斤数','100000',True))
                    except ValueError as e:issues.append(field_issue(context,line,'standard_kg',str(e)))
            if before and bill_unit!=trade.product_billing(c,before) and c.execute('SELECT 1 FROM rules WHERE product_id=?',(pid,)).fetchone():
                issues.append(field_issue(context,line,'billing_unit','该产品已有客户专属价；变更计价单位请新建对应规格产品，避免将原公斤价用于框价或盒价'))
            if before and unit!=before['unit']:
                def references_product(value):
                    if isinstance(value,dict):
                        if value.get('product_id')==pid:return True
                        return any(references_product(json.loads(v) if k=='payload' and isinstance(v,str) else v) for k,v in value.items())
                    if isinstance(value,list):return any(references_product(v) for v in value)
                    return False
                # Inventory plans do not snapshot the handling unit. Relabelling a
                # used product would reinterpret both current and archived stock.
                used=any(references_product(json.loads(r[0])) for table in ('orders','archived_orders','warehouse_plans','sales_returns','processing_batches','stock_closings','trial_archives','statement_documents','material_entries','indirect_expenses','expense_estimates') for r in c.execute('SELECT payload FROM '+table))
                if used or c.execute('SELECT 1 FROM rules WHERE product_id=?',(pid,)).fetchone():
                    issues.append(field_issue(context,line,'unit','该产品已有单据、库存或专属定价记录，不能改变计量单位；请为新的计量方式新增产品'))
            average=production_management.product_average(c,before) if before else None
            if unit=='公斤':average=None
            elif 'default_average_kg' in body:
                try:average=ds(dec(body['default_average_kg'],'默认平均重量','100000',True)) if body['default_average_kg'] not in ('',None) else None
                except ValueError as e:issues.append(field_issue(context,line,'default_average_kg',str(e)))
            if issues:raise ValidationError(issues,'请修正产品档案中标出的字段')
            supply_kind=body.get('supply_kind',trade.product_config(c,before).get('supply_kind','self') if before else 'self')
            material=clean(body.get('main_material',production_management.daily.main_material(c,before) if before else ('豆皮' if '素鸡' in values['name'] else '白干' if '熏干' in values['name'] else '魔芋' if '魔芋' in values['name'] else '淀粉' if '凉粉' in values['name'] else '黄豆')),'主要原料',30,supply_kind!='purchased')
            if supply_kind=='purchased':material=''
            grinding=body.get('grinding_system',production_management.daily.grinding_system(c,before) if before else '')
            production_cfg=production_management.pc.get(c)
            if grinding and grinding not in {s['id'] for s in production_management.pc.active_systems(production_cfg)}:raise ValueError('常用供浆系统无效，请重新选择')
            if supply_kind in ('purchased','processing'):grinding=''
            if supply_kind not in ('purchased','processing') and production_cfg['version'] and grinding!=production_cfg['products'].get(pid,{}).get('default_system_id',''):raise ValueError('请在参数设置的生产配置中维护产品供浆关系并指定生效日期')
            if grinding and not production_management.daily.uses_slurry(material):raise ValueError('非用浆产品不能设置供浆系统，请核对主要原料')
            display_order=[p['id'] for p in ordered_products(c)]
            c.execute('INSERT INTO products VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,unit=excluded.unit,price=excluded.price,tare=excluded.tare,standard_kg=excluded.standard_kg',
                      (pid,values['name'],unit,values['price'],values['tare'],standard))
            if 'processing_intensity' in body:
                cost_allocation.save_factor(c,pid,body['processing_intensity'],body.get('intensity_month') or datetime.now(TZ).strftime('%Y-%m'),(body.get('expected') or {}).get('intensity_history'),role,now,audit)
            configs=trade.metadata(c,'product_trade');configs[pid]={**configs.get(pid,{}),'billing_unit':bill_unit,'supply_kind':body.get('supply_kind',configs.get(pid,{}).get('supply_kind','self'))}
            if configs[pid]['supply_kind'] not in ('self','purchased','mixed','processing'):raise ValueError('产品来源无效')
            suppliers=body.get('supplier_ids',configs[pid].get('supplier_ids',[]))
            if not isinstance(suppliers,list) or any(not isinstance(v,str) for v in suppliers) or len(set(suppliers))!=len(suppliers):raise ValueError('供应商关联格式无效')
            valid_suppliers={r['id'] for r in purchasing.projection(c)['suppliers'] if purchasing.finished_supplier(c,r)}
            if supply_kind in ('purchased','mixed') and (not suppliers or any(v not in valid_suppliers for v in suppliers)):raise ValueError('外购产品请选择至少一家供货品类包含成品的合作供应商')
            configs[pid]['supplier_ids']=suppliers if supply_kind in ('purchased','mixed') else []
            if 'crate_type_ids' in body:crate_accounting.set_variants(c,pid,body['crate_type_ids'])
            if 'crate_tares' in body:crate_accounting.set_product_tares(c,pid,body['crate_tares'])
            c.execute("INSERT INTO meta VALUES('product_trade',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(configs),))
            average_row=c.execute("SELECT value FROM meta WHERE key='product_average_weights'").fetchone();averages=json.loads(average_row[0]) if average_row else {}
            if 'default_average_kg' in body or before:averages[pid]=average
            c.execute("INSERT INTO meta VALUES('product_average_weights',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(averages),))
            material_row=c.execute("SELECT value FROM meta WHERE key='product_main_materials'").fetchone();materials=json.loads(material_row[0]) if material_row else {};materials[pid]=material
            c.execute("INSERT INTO meta VALUES('product_main_materials',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(materials),))
            grinding_row=c.execute("SELECT value FROM meta WHERE key='product_grinding_systems'").fetchone();grinding_map=json.loads(grinding_row[0]) if grinding_row else {};grinding_map[pid]=grinding
            c.execute("INSERT INTO meta VALUES('product_grinding_systems',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(grinding_map),))
            if not before:
                c.execute("INSERT INTO meta VALUES('product_display_order',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(display_order+[pid]),))
            audit(c,role,'新增产品' if not before else '修改产品档案',pid,dict(before) if before else None,body)
        elif kind=='rule':
            cid=body.get('customer_id');pid=body.get('product_id')
            customer=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone();product=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
            context={'customer_id':cid,'customer_name':customer['name'] if customer else ''};line={'product_id':pid,'product_name':product['name'] if product else ''};issues=[];values={}
            if not customer or not product:raise ValidationError([field_issue(context,line,'price','客户或产品不存在')])
            if body.get('action')=='reset':
                before=c.execute('SELECT * FROM rules WHERE customer_id=? AND product_id=?',(cid,pid)).fetchone()
                if not before:raise ValidationError([field_issue(context,line,'price','该客户没有专属价，已经是产品默认价')])
                if 'expected' in body and body['expected']!={'price':before['price'],'tare':before['tare']}:
                    raise ValidationError([field_issue(context,line,'price','专属规则已在其他页面修改，请刷新后核对最新值')])
                c.execute('DELETE FROM rules WHERE customer_id=? AND product_id=?',(cid,pid))
                audit(c,role,'恢复产品默认价',cid+'/'+pid,dict(before),None)
                return {'ok':True,'reset':True}
            for key,label,maximum,positive in [('price','单价','100000',True),('tare','单筐皮重','100',False)]:
                try:values[key]=ds(dec(body.get(key),label,maximum,positive))
                except ValueError as e:issues.append(field_issue(context,line,key,str(e)))
            if product['unit']!='筐' and values.get('tare') not in (None,'0'):issues.append(field_issue(context,line,'tare','包装产品的皮重应为0'))
            before=c.execute('SELECT * FROM rules WHERE customer_id=? AND product_id=?',(cid,pid)).fetchone()
            if 'expected' in body:
                current={'price':before['price'],'tare':before['tare']} if before else None
                if body['expected']!=current:issues.append(field_issue(context,line,'price','专属规则已在其他页面修改，请核对最新值后重试'))
            if issues:raise ValidationError(issues)
            price=values['price'];tare=values['tare']
            c.execute('INSERT INTO rules VALUES(?,?,?,?) ON CONFLICT(customer_id,product_id) DO UPDATE SET price=excluded.price,tare=excluded.tare',(cid,pid,price,tare))
            audit(c,role,'维护客户价格及皮重规则',cid+'/'+pid,dict(before) if before else None,{'price':price,'tare':tare})
        else: raise ValueError('未知档案类型')
    return {'ok':True,**({'id':cid} if kind=='customer' else {})}

def fleet_master(body,role):
    erp_access.require_role(role,'delivery.schedule')
    kind=body.get('kind');action=body.get('action')
    if kind not in ('vehicle','driver') or action not in ('create','update','delete','restore'):raise ValueError('档案操作无效')
    table='delivery_vehicles' if kind=='vehicle' else 'delivery_drivers';prefix='V' if kind=='vehicle' else 'D'
    with connect(True) as c:
        before=c.execute(f'SELECT * FROM {table} WHERE id=?',(body.get('id'),)).fetchone()
        if action=='create':
            values=[int(r[0][1:]) for r in c.execute(f'SELECT id FROM {table}') if re.fullmatch(prefix+r'[0-9]+',r[0])]
            key=prefix+str(max(values,default=0)+1).zfill(3)
        else:
            if not before:raise ValueError('档案不存在，请刷新列表')
            key=before['id']
            if body.get('expected')!={'name':before['name'],'active':before['active']}:raise ValueError('档案已在其他页面修改，请刷新后重试')
        name=clean(body.get('name'),'车辆名称' if kind=='vehicle' else '司机姓名',50) if action in ('create','update') else before['name']
        if c.execute(f'SELECT 1 FROM {table} WHERE name=? AND id<>?',(name,key)).fetchone():raise ValueError('名称已存在，请使用已有档案；已删除的可恢复')
        active=0 if action=='delete' else 1 if action in ('create','restore') else before['active']
        after={'id':key,'name':name,'active':active}
        if kind=='vehicle':
            after['vehicle_type']=clean(body.get('vehicle_type') if action in ('create','update') else before['vehicle_type'],'车辆类型',20)
            c.execute('INSERT INTO delivery_vehicles(id,name,active,vehicle_type) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,active=excluded.active,vehicle_type=excluded.vehicle_type',(key,name,active,after['vehicle_type']))
        else:
            c.execute('INSERT INTO delivery_drivers(id,name,active) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,active=excluded.active',(key,name,active))
        audit(c,role,{'create':'新增','update':'修改','delete':'删除（可恢复）','restore':'恢复'}[action]+('车辆' if kind=='vehicle' else '司机'),key,dict(before) if before else None,after)
        return after

def save_operator_user(body,role):
    erp_access.require_role(role,'system.operator-users')
    name=clean(body.get('name'),'经办人姓名',80);user_role=body.get('role')
    if user_role not in ROLES:raise ValueError('请选择经办岗位')
    if type(body.get('active',True)) is not bool:raise ValueError('启用状态无效')
    with connect(True) as c:
        uid=body.get('id') or 'OP-'+secrets.token_hex(4).upper()
        old=c.execute('SELECT * FROM operator_users WHERE id=?',(uid,)).fetchone()
        version=old['version'] if old else 0
        if type(body.get('version',0)) is not int or body.get('version',0)!=version:raise ValueError('经办人资料已修改，请重新读取后编辑')
        if c.execute('SELECT 1 FROM operator_users WHERE name=? AND id<>?',(name,uid)).fetchone():raise ValueError('经办人姓名已存在')
        record={'id':uid,'name':name,'role':user_role,'active':int(body.get('active',True)),'version':version+1}
        c.execute('INSERT INTO operator_users VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,role=excluded.role,active=excluded.active,version=excluded.version',tuple(record.values()))
        audit(c,role,'维护单据经办人名单',uid,dict(old) if old else None,record)
        return record

def save_warehouse(body,role):
    erp_access.require_role(role,'inventory.dispatch' if body.get('stage')=='confirm_dispatch' else 'inventory.stock')
    day=valid_date(body.get('business_date'))
    with connect(True) as c:
        check_business_epoch(c,body)
        stage=body.get('stage','legacy')
        if stage not in ('legacy','stock','allocation_draft','confirm_dispatch'):raise ValueError('库存保存环节无效')
        if stage=='confirm_dispatch' and body.get('evidence_checked') is not True:raise ValueError('请核对库存和拟实发数量后明确确认')
        row=c.execute('SELECT payload FROM warehouse_plans WHERE business_date=?',(day,)).fetchone()
        inventory.open_day(c,day)
        if 'inventory_revision' in body:inventory.expect_revision(c,body)
        yesterday=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
        previous=inventory.closed(c,yesterday)
        if previous and (body.get('opening_source_date')!=yesterday or body.get('opening_close_version')!=previous['version']):
            raise ValueError('昨日结存已有更新，请载入昨日结存并核对后保存')
        before=json.loads(row[0]) if row else None
        if stage=='confirm_dispatch' and not erp_access.role_can(role,'inventory.stock') and (not before or body.get('stock')!=before.get('stock')):raise ValueError('当前账号不能在确认实发时修改库存，请先由有库存权限的人员保存')
        version=before['version'] if before else 0
        if type(body.get('version')) is not int or body['version']!=version:raise ValueError('当天库存分配已修改，请同步最新数据后核对再保存')
        orders={o['id']:o for (raw,) in c.execute('SELECT payload FROM orders') if (o:=json.loads(raw))['business_date']==day}
        if body.get('order_versions')!={oid:o['version'] for oid,o in orders.items()}:raise ValueError('当天订货或实发已有变化，请同步最新数据后重新核对分配')
        products={p['id']:p for p in ordered_products(c)}
        def quantity(value,label):
            q=dec(value,label,'100000')
            if not products[pid].get('fractional') and q!=q.to_integral():raise ValueError(label+'须为非负整数')
            return ds(q)
        stock=[];available={};seen=set()
        rows=body.get('stock')
        if not isinstance(rows,list) or len(rows)>len(products):raise ValueError('库存盘点格式无效')
        for r in rows:
            if not isinstance(r,dict):raise ValueError('库存盘点格式无效')
            pid=r.get('product_id')
            if pid not in products or pid in seen:raise ValueError('库存产品不存在或重复')
            seen.add(pid)
            existing=r.get('existing_qty','');produced=r.get('produced_qty','')
            existing='' if existing=='' else quantity(existing,'昨日结转库存')
            produced='' if produced=='' else quantity(produced,'当天普通生产入库')
            if products[pid].get('supply_kind') in ('purchased','processing') and produced=='':produced='0'
            if products[pid].get('supply_kind')=='processing' and Decimal(produced or '0')>0:raise ValueError(products[pid]['name']+'为转加工产品，请通过厂内转加工批次登记产出，不能填写普通生产')
            if products[pid].get('supply_kind')=='purchased' and Decimal(produced or '0')>0:raise ValueError(products[pid]['name']+'为纯外购产品，不能填写普通生产；自产与外购并存请先修改产品来源')
            managed=sum((Decimal(out['qty']) for kind in ('run','scrap') for run in production_management.rows(c,kind) if run.get('posted') and run['business_date']==day for out in run.get('outputs',[]) if out['product_id']==pid),Decimal(0))
            if Decimal(produced or '0')<managed:raise ValueError(products[pid]['name']+'含厂长已确认入库产量，不能直接调减；请先撤销对应生产入库')
            previous_product=next((p for p in (previous or {}).get('products',[]) if p['product_id']==pid),None)
            if previous_product and existing!=previous_product['counted_qty']:raise ValueError(products[pid]['name']+'昨日结转须与已确认日结一致')
            loss=quantity(r.get('loss_qty') or '0','本日成品报损数量')
            loss_reason=clean(r.get('loss_reason',''),'成品报损原因',500,Decimal(loss)>0)
            counted='' if r.get('counted_qty','')=='' else quantity(r['counted_qty'],'日终实盘数量')
            variance_reason=clean(r.get('variance_reason',''),'盘点差异说明',500,False)
            processes=[p for p in inventory.rows(c,'processing_batches') if p['business_date']==day and not p.get('voided')]
            process_in=sum((Decimal(o['qty']) for p in processes for o in p['outputs'] if o['product_id']==pid),Decimal(0))
            process_out=sum((Decimal(p['input_qty']) for p in processes if p['product_id']==pid),Decimal(0))
            # A blank count is unknown, rather than a zero stock count.
            if existing!='':available[pid]=Decimal(existing)+Decimal(produced or '0')+finished_goods.supplied(c,day,pid)+inventory.restocked(c,day,pid)+process_in-process_out-Decimal(loss)
            stock.append({'product_id':pid,'existing_qty':existing,'produced_qty':produced,'loss_qty':loss,'loss_reason':loss_reason,'counted_qty':counted,'variance_reason':variance_reason})
        listed={r['product_id']:r for r in stock}
        for p in (previous or {}).get('products',[]):
            if p['product_id'] in products and p['product_id'] not in listed:raise ValueError('不能省略昨日已确认结转的产品，请载入昨日结存')
        prior_stock={r['product_id']:r for r in (before or {}).get('stock',[])}
        processes=[p for p in inventory.rows(c,'processing_batches') if p['business_date']==day and not p.get('voided')]
        for pid in products:
            has_process=any(p['product_id']==pid and Decimal(p['input_qty'])>0 or any(o['product_id']==pid for o in p['outputs']) for p in processes)
            has_actual=any(l['product_id']==pid and Decimal(l['actual_qty'])>0 for o in orders.values() for l in o['lines'])
            had_opening=prior_stock.get(pid,{}).get('existing_qty','')!=''
            if listed.get(pid,{}).get('existing_qty','')=='' and (has_process or had_opening and has_actual):raise ValueError(products[pid]['name']+'已有库存变动，不能删除已确认的昨日结转')
        allocations=[];seen=set();totals={}
        rows=body.get('allocations')
        if not isinstance(rows,list) or len(rows)>10000:raise ValueError('客户分配格式无效')
        for r in rows:
            if not isinstance(r,dict):raise ValueError('客户分配格式无效')
            oid=r.get('order_id');pid=r.get('product_id');o=orders.get(oid)
            l=next((l for l in o['lines'] if l['product_id']==pid),None) if o else None
            if not l or (oid,pid) in seen:raise ValueError('分配对应的订货产品不存在或重复')
            if 'ordered_qty' in r and str(r['ordered_qty'])!=l['ordered_qty']:raise ValueError(o['customer_name']+'订货已变化，请逐项核对并重新填写分配量')
            seen.add((oid,pid));qty=quantity(r.get('qty'),'分配数量')
            if Decimal(qty)>max(Decimal(l['ordered_qty']),Decimal(l['actual_qty'])):raise ValueError(o['customer_name']+'的分配量超过订货量，请先核对订货')
            if stage in ('legacy','confirm_dispatch') and Decimal(qty)>0 and pid not in available:raise ValueError(products[pid]['name']+'尚未盘点已有库存，请明确填写数量（无库存填0）')
            totals[pid]=totals.get(pid,Decimal(0))+Decimal(qty)
            allocations.append({'order_id':oid,'product_id':pid,'qty':qty,'ordered_qty':l['ordered_qty'],**({'mode':'auto' if r.get('mode')=='auto' and Decimal(qty)==Decimal(l['ordered_qty']) else 'manual'} if stage!='legacy' else {})})
        if stage!='legacy':
            present={(a['order_id'],a['product_id']) for a in allocations}
            for a in inventory.proposed_allocations({'allocations':allocations},orders.values()):
                if (a['order_id'],a['product_id']) not in present:allocations.append(a)
            totals={pid:sum((Decimal(a['qty']) for a in allocations if a['product_id']==pid),Decimal(0)) for pid in products}
        for pid,total in totals.items():
            if stage=='confirm_dispatch' and total>0 and pid not in available:raise ValueError(products[pid]['name']+'尚未盘点当日库存，请先确认库存')
            if stage in ('legacy','confirm_dispatch') and total>available.get(pid,Decimal(0)):raise ValueError(products[pid]['name']+'分配合计超过可用库存，请调整客户分配或盘点数量')
        allocation_map={(a['order_id'],a['product_id']):Decimal(a['qty']) for a in allocations}
        for pid,supply in available.items():
            committed=sum((max(Decimal(l['actual_qty']),allocation_map.get((o['id'],pid),Decimal(0))) for o in orders.values() for l in o['lines'] if l['product_id']==pid),Decimal(0))
            if stage=='legacy' and committed>supply:raise ValueError(products[pid]['name']+'实发加待发预留超过可供库存，请核对当天生产与分配')
        notes=[];seen=set();customers={o['customer_id'] for o in orders.values()}
        rows=body.get('customers',[])
        if not isinstance(rows,list) or len(rows)>len(customers):raise ValueError('客户分配说明格式无效')
        for r in rows:
            if not isinstance(r,dict):raise ValueError('客户分配说明格式无效')
            cid=r.get('customer_id')
            if cid not in customers or cid in seen:raise ValueError('客户分配说明无效或重复')
            seen.add(cid);notes.append({'customer_id':cid,'note':clean(r.get('note',''),'分配说明',200,False)})
        if stage=='confirm_dispatch':
            if body.get('dispatch_version') is not None:
                prow=c.execute('SELECT payload FROM dispatch_plans WHERE business_date=?',(day,)).fetchone()
                current=json.loads(prow[0]).get('version') if prow else 0
                if isinstance(body.get('dispatch_version'),bool) or not isinstance(body.get('dispatch_version'),int) or body['dispatch_version']!=current:raise ValueError('当天排车安排已变化，请返回车辆排班重新核对后再确认实发')
            targets={(a['order_id'],a['product_id']):a['qty'] for a in allocations}
            for o in orders.values():
                updated=json.loads(dumps(o));changed=False
                for l in updated['lines']:
                    qty=targets[(o['id'],l['product_id'])]
                    if Decimal(qty)!=Decimal(l['actual_qty']) or Decimal(qty)==0 and not l.get('not_shipped') and not inventory.allocation_locked(o,l):
                        if inventory.allocation_locked(o,l):raise ValueError(o['customer_name']+' '+l['product_name']+'已有称重、交接或结算，不能从分配页覆盖实发；请到原单核对修订')
                        l['actual_qty']=qty;l['not_shipped']=Decimal(qty)==0;changed=True
                if changed:
                    updated['dispatch_required']=True
                    mutate('order',{**updated,'_data_epoch':body.get('_data_epoch','0')},role,o['id'],connection=c,defer_inventory=True)
        result={'production_sources':(before or {}).get('production_sources',[]),'allocation_state':'confirmed' if stage in ('legacy','confirm_dispatch') else 'draft','business_date':day,'version':version+1,'stock':stock,'allocations':allocations,'customers':notes,'updated_at':now(),
                'opening_source_date':yesterday if previous else '', 'opening_close_version':previous['version'] if previous else 0,'inventory_revision':inventory.bump(c)}
        c.execute('INSERT INTO warehouse_plans VALUES(?,?) ON CONFLICT(business_date) DO UPDATE SET payload=excluded.payload',(day,dumps(result)))
        if stage=='stock':
            increased_loss={r['product_id'] for r in stock if Decimal(r['loss_qty'])>Decimal(prior_stock.get(r['product_id'],{}).get('loss_qty') or '0')}
            for product in inventory.stock(c,day)['products']:
                if product['product_id'] in increased_loss and product['book_qty'] is not None and Decimal(product['book_qty'])<0:raise ValueError(product['product_name']+'报损后库存不足，请核对报损、生产与实发数量')
        if stage=='confirm_dispatch':
            missing=__import__('transport_closure').unplanned(c,day)
            if missing:raise ValueError('以下实发订单尚未排入任何趟次：'+'、'.join(missing[:8])+('等' if len(missing)>8 else '')+'；请先回到车辆排班分配市场并保存当天安排')
            inventory.validate_book(c,day,True)
            trade.ensure_dispatched_trips(c,day,role,now,audit)
        audit(c,role,'确认分配并写入实发' if stage=='confirm_dispatch' else '保存库存与发货预分配' if stage!='legacy' else '保存库存盘点与自主发货分配',day,before,result)
        if stage=='confirm_dispatch':return {'plan':result,'orders':[get_order(c,oid) for oid in orders],'inventory_revision':result['inventory_revision']}
        return result

def save_dispatch(body,role):
    erp_access.require_role(role,'delivery.schedule')
    business_date=valid_date(body.get('business_date'))
    with connect(True) as c:
        check_business_epoch(c,body)
        row=c.execute('SELECT payload FROM dispatch_plans WHERE business_date=?',(business_date,)).fetchone()
        before=json.loads(row[0]) if row else None
        version=before['version'] if before else 0
        if body.get('version')!=version:raise ValueError('当天配送安排已在其他页面修改，请同步最新数据后核对再保存')
        markets={r['id']:dict(r) for r in c.execute('SELECT * FROM delivery_markets')}
        vehicles={r['id']:dict(r) for r in c.execute('SELECT * FROM delivery_vehicles')}
        drivers={r['id']:dict(r) for r in c.execute('SELECT * FROM delivery_drivers')}
        old_trips={t['id']:t for t in (before or {}).get('trips',[])}
        raw_trips=body.get('trips');raw_assignments=body.get('assignments')
        if not isinstance(raw_trips,list) or not 1<=len(raw_trips)<=30:raise ValueError('每天请安排1至30个配送趟次')
        if not isinstance(raw_assignments,list) or len(raw_assignments)>1000:raise ValueError('市场分配格式无效')
        trips=[];trip_ids=set()
        for raw in raw_trips:
            if not isinstance(raw,dict):raise ValueError('配送趟次格式无效')
            tid=clean(raw.get('id'),'趟次编号',30)
            if tid in trip_ids:raise ValueError('配送趟次不能重复')
            trip_ids.add(tid);vehicle_id=raw.get('vehicle_id','')
            prior=old_trips.get(tid,{})
            if vehicle_id and (vehicle_id not in vehicles or not vehicles[vehicle_id]['active'] and prior.get('vehicle_id')!=vehicle_id):raise ValueError('请选择未删除的车辆')
            driver_ids=raw.get('driver_ids',[raw['driver_id']] if raw.get('driver_id') else [])
            if not isinstance(driver_ids,list) or len(driver_ids)>30 or not all(isinstance(d,str) for d in driver_ids) or len(set(driver_ids))!=len(driver_ids):raise ValueError('司机选择无效，请勾选不重复的司机')
            prior_ids=prior.get('driver_ids',[prior['driver_id']] if prior.get('driver_id') else [])
            for driver_id in driver_ids:
                if driver_id not in drivers or not drivers[driver_id]['active'] and driver_id not in prior_ids:raise ValueError('请选择未删除的司机')
            driver_name=(prior.get('driver') if driver_ids==prior_ids else '、'.join(drivers[d]['name'] for d in driver_ids)) if driver_ids else clean(raw.get('driver',''),'司机',60,False)
            trips.append({'id':tid,'name':clean(raw.get('name'),'趟次名称',60),'period':clean(raw.get('period'),'出发时段',30),
                'vehicle_id':vehicle_id,'vehicle_name':prior.get('vehicle_name',vehicles.get(vehicle_id,{}).get('name','')) if prior.get('vehicle_id')==vehicle_id else vehicles.get(vehicle_id,{}).get('name',''),
                'provider_id':__import__('transport_closure').provider(c,raw['provider_id'],raw.get('provider_id')!=prior.get('provider_id'))['id'] if raw.get('provider_id') else '',
                'task':raw.get('task') if raw.get('task') in __import__('transport_closure').task_keys(c) else prior.get('task','delivery'),
                'area':clean(raw.get('area',''),'计费地区',40,False) or prior.get('area',''),
                'driver_ids':driver_ids,'driver_id':driver_ids[0] if driver_ids else '','driver':driver_name or ''})
        assignments=[];seen=set();stops=set()
        for raw in raw_assignments:
            if not isinstance(raw,dict):raise ValueError('市场分配格式无效')
            mid=raw.get('market_id');tid=raw.get('trip_id','');sequence=raw.get('sequence')
            if mid not in markets or mid in seen:raise ValueError('市场不存在或重复分配')
            seen.add(mid)
            if tid and tid not in trip_ids:raise ValueError('市场对应的趟次不存在')
            if isinstance(sequence,bool) or not isinstance(sequence,int) or not 1<=sequence<=1000:raise ValueError('送达顺序请填写1至1000的整数')
            if tid and (tid,sequence) in stops:raise ValueError('同一趟次的市场送达顺序不能重复')
            if tid:stops.add((tid,sequence))
            assignments.append({'market_id':mid,'market_name':markets[mid]['name'],'city':markets[mid]['city'],'trip_id':tid,'sequence':sequence})
        # Keep the market of an already planned order stable when a customer later changes market.
        old_map=before.get('order_markets',{}) if before else {}
        customer_locations={r['id']:dict(r) for r in c.execute('SELECT id,route,market_id FROM customers')}
        market_names={m['name']:m['id'] for m in markets.values()}
        order_markets={}
        for (payload,) in c.execute('SELECT payload FROM orders'):
            o=json.loads(payload)
            if o['business_date']==business_date and order_delivery_method(c,o)!='pickup':
                customer=customer_locations.get(o['customer_id'],{})
                order_markets[o['id']]=old_map.get(o['id']) or customer.get('market_id') or market_names.get(customer.get('route',o.get('route','')),'')
        result={'business_date':business_date,'version':version+1,'trips':trips,'assignments':assignments,'order_markets':order_markets,'updated_at':now()}
        __import__('transport_closure').guard_dispatch(c,before,result)
        c.execute('INSERT INTO dispatch_plans VALUES(?,?) ON CONFLICT(business_date) DO UPDATE SET payload=excluded.payload',(business_date,dumps(result)))
        if c.execute("SELECT 1 FROM warehouse_plans WHERE business_date=? AND json_extract(payload,'$.allocation_state')='confirmed'",(business_date,)).fetchone():__import__('transport_closure').sync(c,business_date,role,now,audit)
        audit(c,role,'保存每日配送安排',business_date,before,result)
        return result

def batch_rules(body,role):
    rows=body.get('rules')
    if not isinstance(rows,list) or len(rows)>5000 or not rows and not body.get('crate_rules'):raise ValueError('请提交1至5000项价格规则')
    issues=[];seen=set()
    with connect(True) as c:
        for row in rows:
            if not isinstance(row,dict):raise ValueError('价格规则格式错误')
            key=(row.get('customer_id'),row.get('product_id'))
            if key in seen:raise ValueError('同一客户与产品的规则不能重复提交')
            seen.add(key)
            try:master({**row,'kind':'rule'},role,connection=c)
            except ValidationError as e:issues.extend(e.issues)
        if issues:raise ValidationError(issues,'客户价格表存在填写问题，整批未保存')
        crate_count=crate_accounting.save_rules(c,body.get('crate_rules',[]),role,now,audit) if body.get('crate_rules') else 0
    return {'ok':True,'count':len(rows)+crate_count}

class Handler(BaseHTTPRequestHandler):
    server_version='LocalERP/0.23'
    def log_message(self, fmt, *args): pass
    def setup(self):
        super().setup();self.connection.settimeout(15)
    def authenticated(self,write=False):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:raise auth.AuthError(401,'请重新登录')
        token=cookie['erp_session'].value if 'erp_session' in cookie else ''
        with connect() as c:
            session=auth.authenticate(c,token,int(time.time()));session['user']['permissions']=erp_access.permissions(c,session['user']['role'])
        if write:auth.verify_csrf(session,self.headers.get('X-CSRF-Token',''))
        self.auth_token=token;self.auth_session=session
        if session['user']['must_change_password'] and self.path.split('?')[0] not in ('/api/auth/session','/api/auth/password','/api/auth/logout','/api/auth/activity'):
            raise auth.AuthError(403,'请先修改初始密码')
        return session['user']
    def auth_enabled(self):return not getattr(self.server,'test_pilot',False)
    def auth_error(self,error):
        if error.status==403 and self.path.split('?')[0]!='/api/auth/login':
            context=REQUEST_TOKEN.set(None)
            try:
                actor=getattr(self,'auth_session',{}).get('user',{})
                with connect(True) as c:
                    c.execute('INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,?,?,?,?)',(int(time.time()),'access.denied',actor.get('id'),self.path.split('?')[0][:160],dumps({'status':error.status,'request_id':(REQUEST_ACTOR.get() or {}).get('request_id','')})))
            except sqlite3.Error:pass
            finally:REQUEST_TOKEN.reset(context)
        self.respond({'error':str(error)},error.status)
    def set_auth_cookies(self,token='',csrf='',max_age=0):
        secure='; Secure' if os.environ.get('ERP_COOKIE_SECURE')=='1' else ''
        self.extra_cookies=[f'erp_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}'+secure,f'erp_csrf={csrf}; Path=/; SameSite=Strict; Max-Age={max_age}'+secure]
    def security_audit(self,c,action,entity,before=None,after=None):
        actor=REQUEST_ACTOR.get() or {};audit(c,actor.get('role','系统'),action,entity,before,after)
    def headers_base(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'")
    def respond(self,body,status=200,ctype='application/json; charset=utf-8',filename=None):
        raw=body if isinstance(body,bytes) else dumps(body).encode()
        encoding=''
        if not filename and 'json' in ctype and len(raw)>=1024 and 'gzip' in (self.headers.get('Accept-Encoding') or ''):
            packed=gzip.compress(raw,5)
            if len(packed)<len(raw): raw,encoding=packed,'gzip'
        self.send_response(status);self.headers_base();self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)))
        if encoding:
            self.send_header('Content-Encoding',encoding);self.send_header('Vary','Accept-Encoding')
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        for cookie in getattr(self,'extra_cookies',[]):self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(raw)
    def check_host(self):
        allowed=getattr(self.server,'allowed_authorities',{f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'})
        network=getattr(self.server,'lan_network',None)
        if network is not None and ipaddress.ip_address(self.client_address[0]) not in network:raise auth.AccessRefused('仅允许同一局域网的设备访问')
        if self.headers.get('Host') not in allowed: raise auth.AccessRefused('访问地址不在服务允许的地址中')
        origin=self.headers.get('Origin')
        if origin and origin not in {'http://'+a for a in allowed}: raise auth.AccessRefused('不允许跨站访问本地 ERP')
    def print_report(self, path, query, month, user):
        with connect() as c:
            report=payroll.report(c,month) if path in ('/print/payroll','/print/payroll-slip') else payroll.attendance(c,month)
            if path=='/print/attendance-month':
                mods=set(user['permissions']['modules']) if user else set(erp_access.defaults('管理员')['modules']);scope=query.get('employee_type',[''])[0]
                visible={k for k in __import__('personnel').TYPES if __import__('personnel').type_permission(k) in mods or 'finance.payroll' in mods}
                if scope and scope not in visible:raise auth.AuthError(403,'当前账号无权打印此类人员考勤')
                report=__import__('personnel').attendance_report(c,month,{scope} if scope else visible)
            if 'company' not in report:report['company']=__import__('company').current(c)
            if path=='/print/payroll-slip' and query.get('all',[''])[0]=='1':text=payroll.slips_html(report,query)
            else:text=payroll.slip_html(report,query.get('employee',[''])[0],query.get('payment',[''])[0]) if path=='/print/payroll-slip' else payroll.print_html(report,query,path=='/print/payroll')
        return self.respond(text.encode(),ctype='text/html; charset=utf-8')

    def do_GET(self):
        try:
            self.check_host()
            path=self.path.split('?')[0]
            if path=='/api/health':
                with connect() as c:
                    c.execute('SELECT 1 FROM orders LIMIT 1');c.execute('SELECT 1 FROM auth_users LIMIT 1')
                return self.respond({'status':'ok'})
            user=None
            user=None
            if self.auth_enabled() and (path.startswith('/api/') or path.startswith('/print/')):
                user=self.authenticated()
            if path=='/api/data-package':
                import data_package
                perms=(user or {}).get('permissions') or {}
                if self.auth_enabled() and 'costs.close' not in (perms.get('actions') or []) and (user or {}).get('role')!='管理员':
                    raise auth.AuthError(403,'仅会计或管理员可以导出数据包')
                query=parse_qs(urlsplit(self.path).query)
                start_day=query.get('start',[''])[0] or datetime.now(TZ).strftime('%Y-%m-01')
                end_day=query.get('end',[''])[0] or datetime.now(TZ).date().isoformat()
                for value in (start_day,end_day):
                    if len(value)!=10 or value[4]!='-' or value[7]!='-':raise ValueError('数据包日期格式应为 YYYY-MM-DD')
                if start_day>end_day:raise ValueError('开始日期不能晚于结束日期')
                with connect() as c:
                    raw=data_package.xlsx(data_package.build(c,start_day,end_day))
                return self.respond(raw,ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='erp-data-'+start_day+'_'+end_day+'.xlsx')
            if self.auth_enabled() and (path.startswith('/api/') or path.startswith('/print/')) and not path.startswith('/api/driver/photo/'):
                erp_access.authorize_read(path,user)
            if path=='/api/auth/session':return self.respond({'authenticated':bool(user),'user':user,'mode':'accounts' if self.auth_enabled() else 'test-pilot','session':auth.session_status(self.auth_session,int(time.time())) if user else None})
            if path=='/api/receipt-ocr/settings':return self.respond(receipt_ocr_settings_get(user or evidence_actor()))
            if path.startswith('/api/receipt-evidence/'):
                segments=path.strip('/').split('/');actor=user or evidence_actor()
                if len(segments)==4 and segments[3]=='image':
                    payload=receipt_evidence_image(segments[2],actor)
                    return self.respond(payload['image'],ctype=payload['mime'])
                if len(segments)==3:return self.respond(receipt_evidence_get(segments[2],actor))
                raise auth.AuthError(404,'未知凭据操作')
            if path.startswith('/api/driver/photo/'):
                segments=path.strip('/').split('/')
                if len(segments)!=5:raise auth.AuthError(404,'未知照片操作')
                with connect() as c:payload=driver_portal.photo(c,user,segments[3],segments[4])
                return self.respond(payload['data'],ctype=payload['mime'])
            if path=='/api/driver/return-options':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=driver_portal.return_options(c,user,query.get('date',[datetime.now(TZ).date().isoformat()])[0])
                return self.respond(result)
            if path=='/api/driver':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=driver_portal.report(c,user,query.get('date',[datetime.now(TZ).date().isoformat()])[0],query.get('auto',['0'])[0]=='1')
                return self.respond(result)
            if path=='/print/driver-delivery':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:text=driver_portal.print_delivery(c,user,query.get('date',[''])[0],query.get('trip',[''])[0],now)
                return self.respond(text.encode(),ctype='text/html; charset=utf-8')
            if path=='/api/order-corrections':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=order_corrections.preview(c,get_order(c,query.get('order_id',[''])[0]))
                return self.respond(result)
            if path=='/api/gel-tofu':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=gel_tofu.report(c,query.get('date',[datetime.now(TZ).date().isoformat()])[0])
                return self.respond(result)
            if path=='/api/finished-goods':
                query=parse_qs(urlsplit(self.path).query)
                view=query.get('view',[''])[0]
                with connect() as c:
                    if view:
                        if view!='history':raise auth.AuthError(400,'外购成品查询类型无效')
                        import finished_goods_query
                        try:
                            result=finished_goods_query.history(c,start=query.get('start',[''])[0],end=query.get('end',[''])[0],all_dates=query.get('all',['0'])[0]=='1',supplier_id=query.get('supplier_id',[''])[0],status=query.get('status',[''])[0],search=query.get('search',[''])[0],page=query.get('page',['1'])[0],page_size=query.get('page_size',['50'])[0])
                        except ValueError as error:raise auth.AuthError(400,str(error))
                    elif query.get('supplier_id'):
                        result=finished_goods.statement_preview(c,query['supplier_id'][0],query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0])
                    else:
                        result=finished_goods.projection(c,query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0])
                return self.respond(result)
            if path=='/api/trade':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=trade.projection(c,query.get('date',[datetime.now(TZ).date().isoformat()])[0])
                return self.respond(result)
            if path=='/api/crate-ledger':
                query=parse_qs(urlsplit(self.path).query)
                day=query.get('date',[datetime.now(TZ).date().isoformat()])[0]
                with connect() as c:result=trade.crate_ledger(c,day)
                return self.respond(result)
            if path=='/api/transport-provider-quotes':
                with connect() as c:
                    tc=__import__('transport_closure');editable=not user or 'costs.write' in (user['permissions'].get('actions') or [])
                    result={'regions':tc.regions(c),'quotes':tc.quotes(c) if editable else [],'vehicle_types':tc.vehicle_types(c),'can_edit_rates':editable,'task_types':tc.task_list(c),'task_type_all':tc.task_config(c)}
                return self.respond(result)
            if path=='/api/transport-task-types':
                with connect() as c:result={'task_types':__import__('transport_closure').task_list(c)}
                return self.respond(result)
            if path=='/api/transport-providers':
                with connect() as c:result={'providers':__import__('transport_closure').providers(c)}
                return self.respond(result)
            if path=='/api/transport':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=trade.transport_report(c,query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0])
                financial=not user or bool(set(user['permissions']['modules']) & {'finance.costs','finance.expense-payables','finance.transport-settlement','workspace.analytics'})
                result['financial']=financial
                if not financial:result=__import__('transport_closure').operations_only(result)
                return self.respond(result)
            if path=='/api/assets':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=assets.report(c,query.get('date',[datetime.now(TZ).date().isoformat()])[0])
                return self.respond(result)
            if path=='/api/inventory-check':
                import inventory_reconciliation
                query=parse_qs(urlsplit(self.path).query)
                day=query.get('date',[datetime.now(TZ).date().isoformat()])[0]
                try:resources_costs.day(day)
                except ValueError:raise auth.AuthError(400,'业务日期无效')
                with connect() as c:
                    c.execute('BEGIN')
                    result=inventory_reconciliation.report(c,day)
                return self.respond(result)
            if path=='/api/report-directory':
                import report_directory
                query=parse_qs(urlsplit(self.path).query)
                day=query.get('date',[datetime.now(TZ).date().isoformat()])[0]
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                with connect() as c:
                    c.execute('BEGIN')
                    result=report_directory.catalog(c,day,grants,user['role'] if user else '管理员')
                return self.respond(result)
            if path=='/api/help-index':
                import help_index
                return self.respond(help_index.index(user if user else {'role':'管理员','permissions':erp_access.defaults('管理员')}))
            if path=='/api/expense-options':
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                if 'finance.costs' not in grants['modules'] or not erp_access.can_read_data(grants,'material-costs'):
                    raise auth.AuthError(403,'需要成本金额查看权限')
                if urlsplit(self.path).query:raise auth.AuthError(400,'费用选项不接受查询参数')
                import expense_parties
                with connect() as c:
                    c.execute('BEGIN')
                    result={'categories':cost_allocation.categories(c),'expense_counterparties':expense_parties.catalog(c),'expense_counterparty_kinds':expense_parties.KINDS}
                return self.respond(result)
            if path in ('/api/expense-record','/api/expense-workflow'):
                import expense_query
                query=parse_qs(urlsplit(self.path).query)
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                mods=set(grants['modules'])
                full_costs='finance.costs' in mods and erp_access.can_read_data(grants,'material-costs')
                if not full_costs and 'finance.expense-payables' not in mods:raise auth.AuthError(403,'需要费用金额或费用付款查看权限')
                try:
                    if any(len(values)!=1 for values in query.values()):raise ValueError('查询参数不能重复')
                    with connect() as c:
                        c.execute('BEGIN')
                        if path=='/api/expense-record':
                            record_id=finance_query._text(query.get('id',[''])[0],'费用单号')
                            if not record_id:raise ValueError('请选择费用单号')
                            result=expense_query.record(c,record_id)
                            if result is None:raise auth.AuthError(404,'费用原单不存在或已删除')
                            if not full_costs and not result['payment_required']:raise auth.AuthError(403,'当前账号仅可查看需付款费用的原单')
                        else:result=expense_query.workflow(c,query.get('date',[datetime.now(TZ).date().isoformat()])[0])
                except auth.AuthError:raise
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/resource-ledger':
                query=parse_qs(urlsplit(self.path).query)
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                mods=set(grants['modules']);kind=query.get('kind',['expenses'])[0]
                if kind in ('byproducts','byproduct-receipts'):
                    if 'finance.byproducts' not in mods:raise auth.AuthError(403,'需要豆渣财务模块权限')
                elif not (mods & {'finance.costs','finance.expense-payables'}):
                    raise auth.AuthError(403,'需要费用或费用付款模块权限')
                elif 'finance.expense-payables' not in mods and not erp_access.can_read_data(grants,'material-costs'):
                    raise auth.AuthError(403,'需要成本金额查看权限')
                try:
                    if any(len(values)!=1 for values in query.values()):raise ValueError('查询参数不能重复')
                    if query.get('all',['0'])[0] not in ('0','1'):raise ValueError('全部日期参数无效')
                    options={k:query[k][0] for k in ('kind','period','start','end','page','stage','query','supplier_id','counterparty_id','customer_id','payment_start','payment_end','record_id') if k in query}
                    options['page_size']=int(query.get('page_size',['50'])[0])
                    options['all_dates']=query.get('all',['0'])[0]=='1'
                    with connect() as c:
                        c.execute('BEGIN')
                        result=resource_query.ledger(c,**options)
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path in ('/api/byproduct-summary','/api/byproduct-sales'):
                import byproduct_accounts
                query=parse_qs(urlsplit(self.path).query)
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                if not ({'finance.byproducts','finance.receivables'} & set(grants['modules'])):
                    raise auth.AuthError(403,'需要豆渣财务或应收查看权限')
                try:
                    if any(len(values)!=1 for values in query.values()):raise ValueError('查询参数不能重复')
                    with connect() as c:
                        c.execute('BEGIN')
                        if path=='/api/byproduct-summary':
                            result=byproduct_accounts.summary(c,query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0])
                        else:
                            cid=(query.get('customer_id',[''])[0] or '').strip()
                            if not cid:raise ValueError('请选择客户')
                            result={'rows':byproduct_accounts.sales(c,cid)}
                except auth.AuthError:raise
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/receivables':
                query=parse_qs(urlsplit(self.path).query)
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                if not erp_access.can_read_data(grants,'sales-prices'):
                    raise auth.AuthError(403,'应收金额需要销售金额查看权限')
                try:
                    if any(len(values)!=1 for values in query.values()):raise ValueError('查询参数不能重复')
                    if query.get('all',['0'])[0] not in ('0','1'):raise ValueError('全部日期参数无效')
                    with connect() as c:
                        result=finance_query.ledger(c,
                            query.get('start',[datetime.now(TZ).date().isoformat()])[0],
                            query.get('end',[datetime.now(TZ).date().isoformat()])[0],
                            source=query.get('source',['all'])[0],
                            market=query.get('market',[''])[0],
                            clearance=query.get('clearance',['open'])[0],
                            customer_id=query.get('customer_id',[''])[0],
                            query=query.get('query',[''])[0],
                            page=query.get('page',['1'])[0],
                            receipt_page=query.get('receipt_page',['1'])[0],
                            receipt_start=query.get('receipt_start',[''])[0],
                            receipt_end=query.get('receipt_end',[''])[0],
                            page_size=int(query.get('page_size',['50'])[0]),
                            all_dates=query.get('all',['0'])[0]=='1',
                            basis=query.get('basis',['business_date'])[0])
                except ValueError as error:
                    raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path in ('/api/payroll-history','/api/payroll-history-record'):
                import payroll_query
                q=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in q.values()):raise ValueError('查询参数不能重复')
                    args={k:v[0] for k,v in q.items()}
                    with connect() as c:
                        c.execute('BEGIN')
                        if path=='/api/payroll-history-record':
                            if set(args)-{'kind','id','employee_id'}:raise ValueError('查询参数无效')
                            result=payroll_query.record(c,args.get('kind','sheet'),args.get('id',''),args.get('employee_id',''))
                        else:
                            if set(args)-{'kind','start','end','all','salary_month','employee_id','status','search','page','page_size'}:raise ValueError('查询参数无效')
                            all_value=args.pop('all','0')
                            if all_value not in ('0','1'):raise ValueError('全部日期参数无效')
                            result=payroll_query.history(c,all_dates=all_value=='1',**args)
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/attendance-month-count':
                import attendance_query,personnel
                if not user or user['role']!='管理员':raise auth.AuthError(403,'仅管理员可以查看整月删除确认数量')
                q=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in q.values()) or set(q)-{'month','employee_id'}:raise ValueError('查询参数无效')
                    scopes={scope for scope in personnel.TYPES if personnel.type_permission(scope) in user['permissions']['modules']}
                    with connect() as c:result=attendance_query.month_record_count(c,q.get('month',[''])[0],q.get('employee_id',[''])[0],scopes)
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/attendance-day':
                import attendance_query,personnel
                q=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in q.values()) or set(q)-{'date','scope'}:raise ValueError('查询参数无效')
                    scope=q.get('scope',['production'])[0]
                    if scope not in personnel.TYPES:raise ValueError('人员范围无效')
                    grants=user['permissions'] if user else erp_access.defaults('管理员')
                    if personnel.type_permission(scope) not in grants['modules']:raise auth.AuthError(403,'当前账号无权查看此类人员考勤')
                    with connect() as c:
                        c.execute('BEGIN')
                        result=attendance_query.day_records(c,q.get('date',[datetime.now(TZ).date().isoformat()])[0],scope,grants)
                except auth.AuthError:raise
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/attendance-history':
                import attendance_query, personnel
                q=parse_qs(urlsplit(self.path).query)
                mods=set((user['permissions'] if user else erp_access.defaults('管理员'))['modules'])
                visible={k for k in personnel.TYPES if personnel.type_permission(k) in mods or 'finance.payroll' in mods}
                scope=q.get('scope',[''])[0]
                if scope and scope not in personnel.TYPES:raise auth.AuthError(400,'人员范围无效')
                if scope and scope not in visible:raise auth.AuthError(403,'当前账号无权查看此类人员考勤')
                with connect() as c:
                    try:
                        result=attendance_query.history(c,{scope} if scope else visible,start=q.get('start',[''])[0],end=q.get('end',[''])[0],all_dates=q.get('all',['0'])[0]=='1',employee_id=q.get('employee_id',[''])[0],status=q.get('status',[''])[0],search=q.get('search',[''])[0],page=q.get('page',['1'])[0],page_size=q.get('page_size',['50'])[0])
                    except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path in ('/api/social-compensation','/api/crate-packaging'):
                q=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    allowed={'month'} if path=='/api/social-compensation' else set()
                    if set(q)-allowed or any(len(v)!=1 for v in q.values()):raise ValueError('查询参数无效')
                    with connect() as c:
                        if path=='/api/social-compensation':
                            import social_policy
                            result=social_policy.report(c,q.get('month',[''])[0])
                        else:
                            import crate_packaging
                            result=crate_packaging.catalog(c)
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/employee-banks':
                import employee_banks
                with connect() as c:
                    if parse_qs(urlsplit(self.path).query).get('template')==['1']:
                        raw=employee_banks.template(c)
                        self.respond(raw,ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='employee-bank-template.xlsx');return
                    result=employee_banks.report(c)
                self.respond(result);return
            if path=='/api/factory/report':
                query=parse_qs(urlsplit(self.path).query);kind=query.get('kind',['daily'])[0];day=query.get('date',[datetime.now(TZ).date().isoformat()])[0]
                grants=user['permissions'] if user else erp_access.defaults('管理员');mods=set(grants['modules'])
                required={'sales-chain':{'sales.reports'},'contractor-personnel':{'delivery.dispatch'},'expense-summary':{'finance.costs','finance.expense-payables','finance.payables','workspace.analytics'},'expense-all':{'finance.expense-payables','finance.payables','workspace.analytics'},'soy-stock':{'production.inventory','production.daily','inventory.materials','workspace.analytics'},'sales-decision':{'sales.reports','workspace.analytics'},'management-month':{'workspace.analytics'},'production-month':{'inventory.cost'},'production-charts':{'production.daily','inventory.cost','workspace.analytics'},'bean-stock':{'production.manage','production.daily','production.inventory','inventory.materials'},'system-settings':{'system.parameters'},'owner':{'workspace.analytics'},'attendance-month':{'production.attendance','management.attendance','finance.payroll'},'payroll':{'finance.payroll'},'daily':{'production.daily'},'processing-cost':{'inventory.cost','production.daily'},'material-costs':{'inventory.cost','finance.costs','workspace.analytics'},'sales':{'sales.reports'},'weights':{'finance.settlement'},'finance-settings':{'finance.receivables'}}
                if kind not in required or not mods & required[kind]:raise auth.AuthError(403,'当前账号无此报表查看权限')
                if kind=='contractor-personnel' and (user['role'] if user else '管理员') not in ('管理员','物流负责人'):raise auth.AuthError(403,'承包方人员考勤仅供管理员和运输负责人使用')
                if kind=='contractor-personnel' and user and 'delivery.contractors.read' not in user['permissions']['actions']:raise auth.AuthError(403,'当前账号无权查看承包方人员考勤')
                if kind=='finance-settings' and (user and user['role']=='厂长' or 'finance.alert-settings' not in grants['actions']):raise auth.AuthError(403,'仅财务授权岗位可查看应收预警设置')
                if kind=='material-costs' and not erp_access.can_read_data(grants,'material-costs'):raise auth.AuthError(403,'材料分摊报表需要材料成本查看权限')
                if kind in ('sales','sales-decision','sales-chain','management-month') and not erp_access.can_read_data(grants,'sales-prices'):raise auth.AuthError(403,'销售报表需要销售金额查看权限')
                if kind in ('owner','management-month') and any(not erp_access.can_read_data(grants,k) for k in ('sales-prices','purchase-prices','material-costs','supplier-terms')):raise auth.AuthError(403,'经营分析需要完整经营金额查看权限')
                if kind in ('expense-summary','expense-all') and not ('finance.expense-payables' in mods or erp_access.can_read_data(grants,'material-costs')):raise auth.AuthError(403,'费用汇总需要费用付款或成本金额查看权限')
                with connect() as c:
                    if kind in ('sales-decision','management-month','production-month','production-charts','soy-stock','expense-summary','expense-all'):
                        import reporting
                        if kind=='soy-stock':report=reporting.soy_stock(c,day)
                        
                        if kind=='soy-stock':
                            def quantity_only(value):
                                if isinstance(value,dict):return {k:quantity_only(v) for k,v in value.items() if not k.endswith('_cents') and k not in ('average_price','uncosted_qty')}
                                if isinstance(value,list):return [quantity_only(v) for v in value]
                                return value
                            report=quantity_only(report)
                        elif kind in ('expense-summary','expense-all'):report=reporting.expense_summary(c,day[:7] if kind=='expense-summary' else '')
                        elif kind=='production-charts':report=reporting.production_day(c,day)
                        elif kind=='sales-decision':report=reporting.sales(c,query.get('start',[day])[0],query.get('end',[day])[0],query.get('region',[''])[0],all_dates=query.get('all',['0'])[0]=='1')
                        elif kind=='management-month':report=reporting.management_month(c,day[:7])
                        else:report=reporting.production_month(c,day[:7])
                    elif kind=='sales-chain':
                        import sales_chain
                        c.execute('BEGIN')
                        try:
                            report=sales_chain.report(c,query.get('start',[day])[0],query.get('end',[day])[0],
                                region=query.get('region',[''])[0],customer_id=query.get('customer_id',[''])[0],
                                product_id=query.get('product_id',[''])[0],query=query.get('query',[''])[0],
                                status=query.get('status',[''])[0],view=query.get('view',['fulfillment'])[0],
                                page=int(query.get('page',['1'])[0]),all_dates=query.get('all',['0'])[0]=='1')
                        except ValueError as error:raise auth.AuthError(400,str(error))
                    elif kind=='bean-stock':report=production_management.bean_stock(c,day)
                    elif kind=='system-settings':report=production_management.parameter_catalog(c,user)
                    elif kind=='owner':report=owner_analysis.report(c,day)
                    elif kind=='contractor-personnel':report=__import__('personnel').contractor_report(c,query.get('month',[day[:7]])[0],day,user['role'] if user else '管理员')
                    elif kind=='attendance-month':
                        scope=query.get('attendance_scope',[''])[0]
                        visible={k for k in __import__('personnel').TYPES if __import__('personnel').type_permission(k) in mods or 'finance.payroll' in mods}
                        if scope and scope not in visible:raise auth.AuthError(403,'当前账号无权查看此类人员考勤')
                        report=__import__('personnel').attendance_report(c,query.get('month',[day[:7]])[0],{scope} if scope else visible)
                    elif kind=='payroll':report=payroll.report(c,query.get('month',[day[:7]])[0])
                    elif kind=='finance-settings':report={k:v for k,v in production_management.settings(c).items() if k in ('receivable_limit_yuan','receivable_days','version')}
                    elif kind=='material-costs':
                        import material_allocation
                        report=material_allocation.month_report(c,day[:7])
                    elif kind=='daily':report=production_management.daily_report(c,day)
                    elif kind=='processing-cost':report=production_management.processing_month(c,query.get('start',[day])[0])
                    elif kind=='sales':
                        all_dates=query.get('all',['0'])[0]=='1'
                        try:
                            page=int(query.get('page',['1'])[0]);page_size=int(query.get('page_size',['50'])[0])
                            report=production_management.sales_report(c,query.get('start',[day])[0],query.get('end',[day])[0],query.get('region',[''])[0],
                                view=query.get('view',['customers'])[0],customer_id=query.get('customer_id',[''])[0],
                                product_id=query.get('product_id',[''])[0],market=query.get('market',[''])[0],
                                query=query.get('query',[''])[0],state=query.get('state',[''])[0],sort=query.get('sort',['sales'])[0],
                                page=page,page_size=page_size,paginate=query.get('paginate',['0'])[0]=='1',all_dates=all_dates)
                        except ValueError as error:raise auth.AuthError(400,str(error))
                    else:report=production_management.weight_report(c,day)
                if kind in ('daily','sales','weights','processing-cost'):
                    import reporting
                    report['report_context']=reporting.context({'daily':'生产日报','sales':'销售报表','weights':'称重核对','processing-cost':'转加工测算'}[kind],report.get('start',query.get('start',[day])[0]),report.get('end',query.get('end',[day])[0]),{'daily':'生产登记 / 材料领用 / 实发与盘库','sales':'实发及已复核订单','weights':'司机与客户称重登记','processing-cost':'转加工批次 / 来源产品出品率'}[kind],report.get('basis','缺项不补零；实际记录与估算分别标注，单位按产品分别查看。'))
                if kind in ('daily','processing-cost') and not erp_access.can_read_data(grants,'material-costs'):report=erp_access.redact_costs(report)
                return self.respond(report)
            if path=='/api/role-permissions':
                with connect() as c:return self.respond({'roles':[erp_access.permissions(c,r) for r in erp_access.ACCOUNT_ROLES],'modules':erp_access.module_definitions(),'actions':erp_access.action_definitions(),'data_scopes':[{'id':k,'title':t,'description':d} for k,t,d in erp_access.DATA_SCOPES],'role_notes':erp_access.ROLE_NOTES,'groups':erp_access.catalog()['groups'],**erp_access.permission_metadata()})
            if path=='/api/users':
                with connect() as c:return self.respond(auth.list_users(c))
            if path=='/api/archive-records':
                with connect() as c:
                    try:
                        q=parse_qs(urlsplit(self.path).query)
                        return self.respond(audit_query.archives(c,kind=q.get('kind',['trial'])[0],start=q.get('start',[''])[0],end=q.get('end',[''])[0],all_dates=q.get('all',['0'])[0]=='1',search=q.get('search',[''])[0],page=q.get('page',['1'])[0],page_size=q.get('page_size',['30'])[0]))
                    except ValueError as error:raise auth.AuthError(400,str(error))
            if path=='/api/audit':
                with connect() as c:
                    try:
                        q=parse_qs(urlsplit(self.path).query)
                        return self.respond(audit_query.history(c,start=q.get('start',[''])[0],end=q.get('end',[''])[0],all_dates=q.get('all',['0'])[0]=='1',role=q.get('role',[''])[0],search=q.get('search',[''])[0],entity=q.get('entity',[''])[0],page=q.get('page',['1'])[0],page_size=q.get('page_size',['50'])[0]))
                    except ValueError as error:raise auth.AuthError(400,str(error))
            if path=='/api/audit-integrity':
                with connect() as c:
                    return self.respond(audit_chain.verify(c))
            if path=='/api/security-events':
                with connect() as c:
                    try:
                        q=parse_qs(urlsplit(self.path).query)
                        return self.respond(audit_query.security(c,start=q.get('start',[''])[0],end=q.get('end',[''])[0],all_dates=q.get('all',['0'])[0]=='1',search=q.get('search',[''])[0],page=q.get('page',['1'])[0],page_size=q.get('page_size',['50'])[0]))
                    except ValueError as error:raise auth.AuthError(400,str(error))
            if path=='/api/chat':
                if not user:raise auth.AuthError(401,'登录后可使用内部聊天')
                with connect() as c:result=collaboration.list_threads(c,user)
                return self.respond(result)
            if path=='/api/chat/messages':
                if not user:raise auth.AuthError(401,'登录后可使用内部聊天')
                query=parse_qs(urlsplit(self.path).query)
                try:after=max(0,int(query.get('after',['0'])[0]))
                except ValueError:after=0
                with connect() as c:result=collaboration.messages(c,user,query.get('thread_id',[''])[0],after)
                return self.respond(result)
            if path=='/api/notifications':
                if not user:raise auth.AuthError(401,'登录后可查看消息通知')
                with connect() as c:result=collaboration.list_notifications(c,user)
                return self.respond(result)
            if path=='/api/feedback':
                if not user:raise auth.AuthError(401,'登录后可使用问题反馈')
                q=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=collaboration.list_feedback(c,user,start=(q.get('start') or [''])[0],end=(q.get('end') or [''])[0],all_dates=(q.get('all') or [''])[0] in ('1','true'),status=(q.get('status') or [''])[0],search=(q.get('search') or [''])[0],page=int((q.get('page') or ['1'])[0]),page_size=int((q.get('page_size') or ['30'])[0]))
                return self.respond(result)
            if path=='/api/audit-rollback-plan':
                import audit_rollback
                if not user or user['role']!='管理员':raise auth.AuthError(403,'仅管理员可以回滚操作')
                query=parse_qs(urlsplit(self.path).query)
                if any(len(values)!=1 for values in query.values()):raise ValueError('查询参数不能重复')
                try:audit_id=int(query.get('id',[''])[0])
                except (TypeError,ValueError):raise ValueError('请选择操作记录')
                with connect() as c:
                    c.execute('BEGIN')
                    result=audit_rollback.plan(c,audit_id)
                return self.respond(result)
            if path=='/api/bootstrap':
                history_mode=self.headers.get('X-ERP-Expense-History','full')
                byproduct_mode=self.headers.get('X-ERP-Byproduct-History','full')
                if history_mode not in ('full','deferred'):raise auth.AuthError(400,'费用历史读取方式无效')
                if byproduct_mode not in ('full','deferred'):raise auth.AuthError(400,'豆渣历史读取方式无效')
                result=bootstrap(include_expense_history=history_mode!='deferred',include_byproduct_history=byproduct_mode!='deferred',factory_light=bool(user),include_audit=not bool(user))
                if user:
                    with connect() as c:
                        configs={r:erp_access.permissions(c,r) for r in ['管理员',*erp_access.ACCOUNT_ROLES]}
                        result=erp_access.scope_bootstrap(result,user,configs,c)
                    result=scope_bootstrap_entries(result,user)
                    if 'crates.confirm' in user['permissions']['actions']:
                        with connect() as c:
                            queue=driver_portal.pending(c);result['driver_return_pending']=len(queue)
                            result['driver_return_tasks']=[{'id':r['id'],'business_date':r['business_date'],'customer_name':r.get('driver_name','司机回筐')+' · '+('撤回申请' if r['state']=='withdraw_pending' else '回筐确认')} for r in queue]
                            completed={}
                            for r in driver_portal.requests(c):
                                if r['state']=='confirmed':completed[r['business_date']]=completed.get(r['business_date'],0)+1
                            result['driver_return_completed_by_date']=completed
                return self.respond(result)
            if path=='/api/export':
                data=bootstrap();query=parse_qs(urlsplit(self.path).query)
                start=query.get('start',[''])[0];end=query.get('end',[''])[0];day=query.get('date',[''])[0];basis=query.get('basis',['business_date'])[0]
                if basis not in ('business_date','settled_date'):raise ValueError('日期口径无效')
                for value in (start,end,day):
                    if value:valid_date(value)
                if start and end and start>end:raise ValueError('开始日期不能晚于结束日期')
                scope=query.get('scope',[''])[0];market=query.get('market',[''])[0];clearance=query.get('clearance',['all'])[0];cid=query.get('customer_id',[''])[0];search=query.get('search',[''])[0].casefold()
                if scope not in ('','receivables') or clearance not in ('all','open','cleared'):raise ValueError('订单范围或清账状态无效')
                customers={c['id']:c for c in data['customers']};markets={m['id']:m['name'] for m in data['delivery_markets']}
                output=io.StringIO();w=csv.writer(output)
                w.writerow(['单号','业务日期','客户编号','客户','线路','状态','结算金额（元）','已收款（元）','退货已抵（元）','折扣（元）','抹零（元）','未收款（元）','说明'])
                def safe(x):
                    s=str(x)
                    return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
                source=query.get('source',['sales'])[0]
                if source not in ('all','sales','byproduct'):raise ValueError('业务来源无效')
                export_rows=list(data['orders']) if source!='byproduct' else []
                if scope=='receivables' and source in ('all','byproduct'):
                    for r in data['resources']['byproducts']:
                        if r.get('voided'):continue
                        export_rows.append({'id':r['id'],'business_date':r['business_date'],'customer_id':r.get('customer_id',''),'customer_name':customers.get(r.get('customer_id'),{}).get('name') or r['buyer'],'route':'豆渣客户','is_byproduct':True,'state':'reviewed','status':'豆渣 · 已清账' if r['amount_cents']==r['received_cents'] else '豆渣 · 未清账','total_cents':r['amount_cents'],'paid_cents':r['received_cents'],'settlement':{'at':r.get('created_at','')}})
                for o in export_rows:
                    customer=customers.get(o['customer_id'],{});order_market='豆渣客户' if o.get('is_byproduct') else markets.get(customer.get('market_id')) or o.get('route') or customer.get('route') or '未设置市场'
                    if scope=='receivables':
                        if o['state']!='reviewed' or (market and market!=order_market) or (cid and cid!=o['customer_id']):continue
                        if clearance=='open' and inventory.balance(o)<=0 or clearance=='cleared' and inventory.balance(o)!=0:continue
                        if search and search not in ' '.join([o['id'],o['customer_id'],o['customer_name'],order_market]).casefold():continue
                    value=(o.get('settlement') or {}).get('at','')[:10] if basis=='settled_date' else o['business_date']
                    if (start and (not value or value<start)) or (end and (not value or value>end)) or (day and o['business_date']!=day):continue
                    posted=o['state']=='reviewed'
                    w.writerow([safe(o['id']),o['business_date'],safe(o['customer_id']),safe(o['customer_name']),safe(o['route']),o['status'],f"{o['total_cents']/100:.2f}",f"{o['paid_cents']/100:.2f}",f"{o.get('return_credit_cents',0)/100:.2f}",f"{o.get('discount_cents',0)/100:.2f}",f"{o.get('rounding_cents',0)/100:.2f}",f"{inventory.balance(o)/100:.2f}" if posted else '', '豆渣收入，未重复登记产品订单' if o.get('is_byproduct') else '仅已复核单据计入应收'])
                return self.respond(('\ufeff'+output.getvalue()).encode(),ctype='text/csv; charset=utf-8',filename='erp-orders.csv')
            if path=='/api/statement-status':
                import statements
                query=parse_qs(urlsplit(self.path).query)
                cid=query.get('customer_id',[''])[0];day=valid_date(query.get('date',[''])[0])
                with connect() as c:
                    c.execute('BEGIN');result=statements.latest_status(c,cid,day,now())
                return self.respond(result)
            if path=='/api/statement-documents':
                query=parse_qs(urlsplit(self.path).query);cid=query.get('customer_id',[''])[0]
                with connect() as c:result=[{**dict(r),'voided':bool(order_corrections.void_info(c,r['id']))} for r in c.execute('SELECT id,business_date,issued_at,content_hash FROM statement_documents WHERE customer_id=? ORDER BY issued_at DESC,rowid DESC',(cid,))]
                return self.respond(result)
            if path.startswith('/api/statement-documents/'):
                import statements
                with connect() as c:result=statements.get_document(c,path.rsplit('/',1)[-1])
                return self.respond(result)
            if path=='/api/statement-batch-preview':
                import statements
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:
                    c.execute('BEGIN');result=statements.batch_preview(c,valid_date(query.get('date',[''])[0]),now())
                return self.respond(result)
            if path=='/api/customer-statement':
                import statements
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:
                    c.execute('BEGIN')
                    result=statements.snapshot(c,query.get('customer_id',[''])[0],valid_date(query.get('date',[''])[0]),now())
                return self.respond(result)
            if path=='/api/purchase-ledger':
                import purchase_query
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'kind','start','end','all','supplier_id','search','status','payment_kind','charge_kind','month','page','page_size'}:raise ValueError('采购查询参数无效')
                    args={k:v[0] for k,v in query.items()};kind=args.get('kind','receipts')
                    grants=user['permissions'] if user else erp_access.defaults('管理员')
                    required='purchase.receipts' if kind in ('receipts','pending') else 'finance.payables'
                    if required not in grants['modules']:raise auth.AuthError(403,'当前账号无权查看此采购历史')
                    if kind in ('payments','charges','payables') and not erp_access.can_read_data(grants,'purchase-prices'):raise auth.AuthError(403,'采购付款与费用历史需要采购金额查看权限')
                    all_value=args.pop('all','0')
                    if all_value not in ('0','1'):raise ValueError('全部日期参数无效')
                    with connect() as c:
                        c.execute('BEGIN');result=purchase_query.ledger(c,all_dates=all_value=='1',**args)
                        bucket={'pending':'orders','payables':'orders','receipts':'receipts','payments':'payments','charges':'charges'}.get(kind,'receipts')
                        visible=purchasing.scope({bucket:result['rows'],'summary':result['summary']},grants)
                        result['rows']=visible[bucket];result['summary']=visible['summary']
                except auth.AuthError:raise
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/purchase-orders':
                import purchase_query
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'start','end','all','supplier_id','search','status','page','page_size'}:raise ValueError('采购查询参数无效')
                    args={k:v[0] for k,v in query.items()}
                    all_value=args.pop('all','0')
                    if all_value not in ('0','1'):raise ValueError('全部日期参数无效')
                    with connect() as c:
                        c.execute('BEGIN')
                        result=purchase_query.orders(c,all_dates=all_value=='1',**args)
                        if user:
                            # Reuse the same recursive amount/terms policy as existing procurement.
                            visible=purchasing.scope({'orders':result['rows'],'summary':result['summary']},user['permissions'])
                            result['rows']=visible['orders'];result['summary']=visible['summary']
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/purchasing':
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                allowed={'view','order_id','receipt_id','charge_id'}
                if set(query)-allowed or any(len(v)!=1 or not v[0].strip() for v in query.values()):
                    raise auth.AuthError(400,'采购原单查询参数无效')
                if query and (len(query)!=1 or ('view' in query and query['view'][0]!='options')):
                    raise auth.AuthError(400,'请选择一种采购原单查询方式')
                with connect() as c:
                    c.execute('BEGIN')
                    order_ids=None
                    if 'view' in query:order_ids=[]
                    elif query:
                        key=next(iter(query));rid=query[key][0]
                        if len(rid)>100:raise auth.AuthError(400,'采购单号过长')
                        table={'order_id':'purchase_orders','receipt_id':'purchase_receipts','charge_id':'purchase_charges'}[key]
                        row=c.execute('SELECT payload FROM '+table+' WHERE id=?',(rid,)).fetchone()
                        if not row:raise auth.AuthError(404,'采购原单不存在，请刷新后核对')
                        record=json.loads(row[0]);order_ids=[record['id'] if key=='order_id' else record['order_id']]
                    result=purchasing.projection(c,order_ids=order_ids)
                    if user:result=purchasing.scope(result,user['permissions'])
                return self.respond(result)
            if path=='/api/resources':
                with connect() as c:
                    result=resources_costs.snapshot(c)
                    if user:result=erp_access.scope_resources(result,user['permissions'])
                    return self.respond(result)
            if path=='/api/material-issue':
                import material_allocation as ma
                query=parse_qs(urlsplit(self.path).query)
                month=query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0]
                with connect() as c:
                    result=ma.issue_report(c,month)
                    if user and not erp_access.can_read_data(user['permissions'],'material-costs'):result=erp_access.redact_costs(result)
                return self.respond(result)
            if path=='/api/workshop':
                query=parse_qs(urlsplit(self.path).query)
                month=query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0]
                with connect() as c:
                    result=resources_costs.workshop_report(c,month)
                    if user and not erp_access.can_read_data(user['permissions'],'material-costs'):result=erp_access.redact_costs(result)
                return self.respond(result)
            if path=='/api/product-profit':
                query=parse_qs(urlsplit(self.path).query)
                if user and (user['role'] not in ('管理员','老板','会计','出纳') or any(not erp_access.can_read_data(user['permissions'],scope) for scope in ('sales-prices','purchase-prices','material-costs'))):raise auth.AuthError(403,'产品经营测算需要销售、采购及材料成本金额权限')
                import product_profit, finished_cost
                with connect() as c:
                    month=query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0]
                    result=product_profit.month(c,month)
                    try:result['inventory']=finished_cost.month(c,month)
                    except ValueError as exc:result['inventory']={'month':month,'rows':[],'totals':{},'gaps':[str(exc)],'basis':'成品成本结转未能生成'}
                return self.respond(result)
            if path=='/api/inventory-value':
                import inventory_valuation
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'month'}:raise ValueError('查询参数无效')
                    if not set(grants['modules'])&{'inventory.cost','finance.costs'}:raise auth.AuthError(403,'成品库存金额需要生产月报或财务成本权限')
                    month=query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0]
                    with connect() as c:
                        c.execute('BEGIN');result=inventory_valuation.ledger(c,month)
                except ValueError as exc:raise auth.AuthError(400,str(exc))
                return self.respond(result)
            if path in ('/api/byproduct-statement','/api/byproduct-documents') or path.startswith('/api/byproduct-documents/'):
                import byproduct_accounts as ba
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:
                    c.execute('BEGIN')
                    if path=='/api/byproduct-statement':result=ba.snapshot(c,query.get('customer_id',[''])[0],query.get('month',[''])[0],now())
                    elif path=='/api/byproduct-documents':result=ba.documents(c,query.get('customer_id',[''])[0])
                    else:
                        doc_id=path.rsplit('/',1)[-1].removesuffix('.csv');result=ba.get_document(c,doc_id)
                        if path.endswith('.csv'):
                            if result.get('voided'):raise ValueError('该结算单已作废，请重新出具')
                            return self.respond(ba.statement_csv(result),ctype='text/csv; charset=utf-8',filename=doc_id+'.csv')
                return self.respond(result)
            if path=='/api/fund-accounts':
                import funds
                query=parse_qs(urlsplit(self.path).query)
                page_raw=query.get('page',[''])[0]
                try:
                    if any(len(values)!=1 for values in query.values()):raise ValueError('查询参数不能重复')
                    if page_raw and (not page_raw.isdigit() or int(page_raw)<1):raise ValueError('页码无效')
                    with connect() as c:
                        c.execute('BEGIN');result=funds.report(c,query.get('date',[datetime.now(TZ).date().isoformat()])[0],
                            month=query.get('month',[''])[0],start=query.get('start',[''])[0],end=query.get('end',[''])[0],account_id=query.get('account',[''])[0],
                            direction=query.get('direction',[''])[0],page=int(page_raw) if page_raw else None,
                            page_size=int(query.get('page_size',['50'])[0]))
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/byproduct-settlement':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:return self.respond(resources_costs.byproduct_business_month(c,query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0]))
            if path=='/api/material-history':
                import material_query
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'view','start','end','all','as_of','material_id','category','warehouse_id','entry_kind','status','search','page','page_size'}:raise ValueError('查询参数无效')
                    args={k:v[0] for k,v in query.items()};value=args.pop('all','0')
                    if value not in ('0','1'):raise ValueError('全部日期参数无效')
                    financial=erp_access.can_read_data(grants,'material-costs') and bool(set(grants['modules']) & {'finance.costs','workspace.analytics','inventory.cost'} or 'materials.value' in grants['actions'])
                    with connect() as c:
                        c.execute('BEGIN');result=material_query.scope(material_query.query(c,all_dates=value=='1',**args),financial)
                    result['financial']=financial
                except auth.AuthError:raise
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path in ('/api/inventory-check-history','/api/inventory-check-record'):
                import check_history
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    args={k:v[0] for k,v in query.items()}
                    if path.endswith('-record'):
                        if set(args)!={'date','version'}:raise ValueError('请指定业务日期和版本号')
                        with connect() as c:
                            c.execute('BEGIN');result=check_history.record(c,args['date'],args['version'])
                    else:
                        if set(args)-{'start','end','all','product_id','status','search','versions','page','page_size'}:raise ValueError('查询参数无效')
                        value=args.pop('all','0')
                        if value not in ('0','1'):raise ValueError('全部日期参数无效')
                        with connect() as c:
                            c.execute('BEGIN');result=check_history.history(c,all_dates=value=='1',**args)
                except LookupError as error:raise auth.AuthError(404,str(error))
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/expense-close-preview':
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if set(query)!={'month'} or any(len(v)!=1 for v in query.values()):raise ValueError('请指定唯一成本月份')
                    with connect() as c:
                        c.execute('BEGIN');result=__import__('expense_close').public(__import__('expense_close').preview(c,query['month'][0]))
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/expense-estimates':
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if set(query)-{'month','page'} or any(len(v)!=1 for v in query.values()):raise ValueError('查询参数无效')
                    with connect() as c:
                        c.execute('BEGIN');result=__import__('expense_estimates').report(c,query.get('month',[''])[0],query.get('page',[1])[0])
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/expense-coverage-preview':
                import expense_coverage
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'amount','accrual_method','period','spread_months','service_start','service_end','category','counterparty_id','partner','service_account','exclude_expense','estimate_mode','business_date'}:raise ValueError('预览参数无效')
                    with connect() as c:
                        c.execute('BEGIN');result=expense_coverage.preview(c,{k:v[0] for k,v in query.items()})
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path in ('/api/delivery-history','/api/delivery-history-record'):
                import delivery_query
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    args={k:v[0] for k,v in query.items()};kind=args.pop('kind','trips');delivery_query.check_kind(kind)
                    modules=set((user['permissions'] if user else erp_access.defaults('管理员'))['modules'])
                    if not modules & delivery_query.MODULES[kind]:raise auth.AuthError(403,'当前账号无权查看此类历史')
                    financial=bool(modules & {'finance.costs','finance.expense-payables'})
                    if kind=='trips' and args.get('status') in ('settled','unsettled') and not financial:raise auth.AuthError(403,'当前账号无权按财务状态筛选')
                    with connect() as c:
                        c.execute('BEGIN')
                        if path=='/api/delivery-history-record':
                            if set(args)!={'id'}:raise ValueError('原单查询参数无效')
                            result=delivery_query.detail(c,kind,args['id'],financial=financial)
                            if result is None:raise auth.AuthError(404,'记录不存在或不可查看')
                        else:
                            if set(args)-{'start','end','all','status','search','driver_id','vehicle_id','customer_id','asset_id','partner','page','page_size'}:raise ValueError('查询参数无效')
                            value=args.pop('all','0')
                            if value not in ('0','1'):raise ValueError('全部日期参数无效')
                            result=delivery_query.history(c,kind=kind,all_dates=value=='1',financial=financial,**args)
                except auth.AuthError:raise
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/open-stock-history':
                import open_stock_query
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'start','end','all','product_id','status','search','page','page_size'}:raise ValueError('查询参数无效')
                    args={k:v[0] for k,v in query.items()};value=args.pop('all','0')
                    if value not in ('0','1'):raise ValueError('全部日期参数无效')
                    with connect() as c:
                        c.execute('BEGIN');result=open_stock_query.history(c,all_dates=value=='1',**args)
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/stock-history':
                import stock_history
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'start','end','all','product_id','status','search','page','page_size'}:raise ValueError('查询参数无效')
                    args={k:v[0] for k,v in query.items()};value=args.pop('all','0')
                    if value not in ('0','1'):raise ValueError('全部日期参数无效')
                    with connect() as c:
                        c.execute('BEGIN');result=stock_history.history(c,all_dates=value=='1',**args)
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/inventory-history':
                import inventory_query
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                grants=user['permissions'] if user else erp_access.defaults('管理员')
                try:
                    if any(len(v)!=1 for v in query.values()):raise ValueError('查询参数不能重复')
                    if set(query)-{'kind','start','end','all','product_id','customer_id','origin','status','search','page','page_size'}:raise ValueError('查询参数无效')
                    args={k:v[0] for k,v in query.items()};kind=args.get('kind','returns');mods=set(grants['modules'])
                    allowed={'inventory.returns','finance.receivables','workspace.analytics'} if kind=='returns' else {'inventory.operations','workspace.analytics','inventory.cost'}
                    if not mods & allowed:raise auth.AuthError(403,'当前账号无权查看此类历史')
                    financial=kind=='returns' and erp_access.can_read_data(grants,'sales-prices') and bool(mods & {'finance.receivables','finance.settlement','workspace.analytics','sales.reports'})
                    if not financial and kind=='returns' and args.get('status') in ('account','review','posted','credit','closed'):raise auth.AuthError(403,'此状态查询需要退货账款查看权限')
                    value=args.pop('all','0')
                    if value not in ('0','1'):raise ValueError('全部日期参数无效')
                    with connect() as c:
                        c.execute('BEGIN');result=inventory_query.scope(inventory_query.history(c,all_dates=value=='1',**args),financial)
                    result['financial']=financial
                except auth.AuthError:raise
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(result)
            if path=='/api/inventory':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:result=inventory.stock(c,valid_date(query.get('date',[''])[0]))
                return self.respond(result)
            if path in ('/print/attendance-month','/print/payroll','/print/payroll-slip'):
                query=parse_qs(urlsplit(self.path).query);month=query.get('month',[datetime.now(TZ).strftime('%Y-%m')])[0]
                try:
                    return self.print_report(path,query,month,user)
                except ValueError as error:
                    raise auth.AuthError(400,str(error))
            if path=='/print/returns':
                from printing import return_print_html
                query=parse_qs(urlsplit(self.path).query)
                try:
                    with connect() as c:html=return_print_html(c,query,now())
                except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(html.encode(),ctype='text/html; charset=utf-8')
            if path=='/print/purchases':
                from printing import purchase_print_html
                query=parse_qs(urlsplit(self.path).query)
                with connect() as c:
                    try:text=purchase_print_html(c,query,now())
                    except ValueError as error:raise auth.AuthError(400,str(error))
                return self.respond(text.encode(),ctype='text/html; charset=utf-8')
            if path=='/print/orders':
                from printing import order_print_html
                query=parse_qs(urlsplit(self.path).query)
                try:
                    text=order_print_html(bootstrap(),query,now())
                except ValueError as error:
                    raise auth.AuthError(400,str(error))
                return self.respond(text.encode(),ctype='text/html; charset=utf-8')
            files={'/crate-packaging.js':'crate-packaging.js','/payroll-history.js':'payroll-history.js','/transport-closure.js':'transport-closure.js','/accounting-returns.js':'accounting-returns.js','/delivery-history.js':'delivery-history.js','/open-stock-history.js':'open-stock-history.js','/expense-close.js':'expense-close.js','/expense-estimates.js':'expense-estimates.js','/expense-coverage.js':'expense-coverage.js','/check-history.js':'check-history.js','/stock-history.js':'stock-history.js','/material-history.js':'material-history.js','/inventory-history.js':'inventory-history.js','/employee-banks.js':'employee-banks.js','/company.js':'company.js','/personnel-ui.js':'personnel-ui.js','/inventory-check.js':'inventory-check.js','/cost-allocation.js':'cost-allocation.js','/charts.js':'charts.js','/charts.css':'charts.css','/reports.js':'reports.js','/sales-chain.js':'sales-chain.js','/funds.js':'funds.js','/byproduct.js':'byproduct.js','/product-editor.js':'product-editor.js','/accounting-products.js':'accounting-products.js','/order-corrections.js':'order-corrections.js','/accounting-entry.js':'accounting-entry.js','/finished-goods.js':'finished-goods.js','/trade.js':'trade.js','/collaboration.js':'collaboration.js','/production-config.js':'production-config.js','/owner.js':'owner.js','/driver.js':'driver.js','/assets.js':'assets.js','/workforce.js':'workforce.js','/factory.js':'factory.js','/curing.js':'curing.js','/daily-work.js':'daily-work.js','/workspace.js':'workspace.js','/note-presets.js':'note-presets.js','/purchasing.js':'purchasing.js','/resources.js':'resources.js','/material-issue.js':'material-issue.js','/workshop.js':'workshop.js','/billing-ui.js':'billing-ui.js','/receipt-evidence.js':'receipt-evidence.js','/auth-ui.js':'auth-ui.js','/':'index.html','/app.js':'app.js','/customers.js':'customers.js','/sheets.js':'sheets.js','/forms.js':'forms.js','/dispatch.js':'dispatch.js','/operations.js':'operations.js','/inventory.js':'inventory.js','/warehouse.js':'warehouse.js','/navigation.js':'navigation.js','/autosave.js':'autosave.js','/print.css':'print.css','/statement.js':'statement.js','/print.js':'print.js','/style.css':'style.css','/favicon.ico':'favicon.ico','/favicon.svg':'favicon.svg','/favicon-16x16.png':'favicon-16x16.png','/favicon-32x32.png':'favicon-32x32.png','/apple-touch-icon.png':'apple-touch-icon.png','/icon-192.png':'icon-192.png','/icon-512.png':'icon-512.png','/icon-maskable-512.png':'icon-maskable-512.png','/site.webmanifest':'site.webmanifest'}
            if path not in files: return self.respond({'error':'未找到页面'},404)
            p=ROOT/'web'/files[path]
            ctype={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml','png':'image/png','ico':'image/x-icon','webmanifest':'application/manifest+json; charset=utf-8'}[p.suffix[1:]]
            if path=='/':
                # 资产链接带版本号：升级后页面刷新必定取到新 CSS/JS，不受浏览器缓存影响。
                text=re.sub(r'((?:href|src)=")/([A-Za-z0-9_.-]+\.(?:js|css))"',lambda m:f'{m.group(1)}/{m.group(2)}?v={APP_VERSION}"',p.read_text('utf-8'))
                return self.respond(text.encode(),ctype=ctype)
            self.respond(p.read_bytes(),ctype=ctype)
        except auth.AuthError as e:self.auth_error(e)
        except auth.AccessRefused as e: self.respond({'error':str(e)},403)
        except ValueError as e: self.respond({'error':str(e)},400)
        except Exception: self.respond({'error':'读取失败，请查看本机服务状态'},500)
    def do_POST(self):
        actor_context=REQUEST_ACTOR.set(None)
        token_context=REQUEST_TOKEN.set(None)
        grants_context=erp_access.GRANTS.set(None)
        try:
            self.check_host()
            if self.headers.get('X-ERP-Client')!='local-pilot': raise ValueError('请求缺少本机应用标识')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=2621440: raise ValueError('请求大小无效')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValueError('请求格式错误')
            body['_data_epoch']=self.headers.get('X-ERP-Data-Epoch','0')
            role={'warehouse':'库管','accountant':'会计','cashier':'出纳','admin':'管理员'}.get(self.headers.get('X-ERP-Role',''),'')
            path=self.path.split('?')[0];parts=path.strip('/').split('/')
            actor=None;user=None
            if self.auth_enabled():
                if path=='/api/auth/login':
                    error=None
                    with connect(True) as c:
                        try:result=auth.login(c,body.get('username'),body.get('password'),self.client_address[0],int(time.time()),session_ttl=auth.REMEMBER_TTL if body.get('remember') is True else auth.SESSION_TTL,audit=self.security_audit)
                        except auth.AuthError as e:error=e
                    if error:raise error
                    self.set_auth_cookies(result['token'],result['csrf_token'],result['expires_at']-int(time.time()))
                    return self.respond({'user':result['user'],'session':result['session']})
                user=self.authenticated(write=True);role=user['role']
                actor={**user,'request_id':secrets.token_hex(12)}
                REQUEST_ACTOR.set(actor)
                REQUEST_TOKEN.set(self.auth_token)
                erp_access.GRANTS.set(user['permissions'])
                if path=='/api/auth/activity':
                    with connect(True) as c:status=auth.record_activity(c,self.auth_token,int(time.time()))
                    return self.respond({'session':status})
                if path=='/api/auth/logout':
                    with connect(True) as c:auth.logout(c,self.auth_token,int(time.time()),audit=self.security_audit)
                    self.set_auth_cookies();return self.respond({'ok':True})
                if path=='/api/auth/password':
                    error=None
                    with connect(True) as c:
                        try:auth.change_password(c,user,body.get('current_password'),body.get('new_password'),int(time.time()),audit=self.security_audit)
                        except auth.AuthError as e:error=e
                    if error:raise error
                    self.set_auth_cookies();return self.respond({'ok':True})
                if path=='/api/role-permissions':
                    with connect(True) as c:result=erp_access.save_permissions(c,user,body,now,audit)
                    return self.respond(result)
                if path=='/api/users' or path.startswith('/api/users/'):
                    with connect(True) as c:
                        if path=='/api/users':result=auth.create_user(c,user,body,int(time.time()),audit=self.security_audit)
                        elif path.endswith('/reset-password'):result=auth.reset_password(c,user,parts[2],body.get('password'),body.get('version'),int(time.time()),audit=self.security_audit)
                        elif len(parts)==3:result=auth.update_user(c,user,parts[2],body,int(time.time()),audit=self.security_audit)
                        else:raise auth.AuthError(404,'未知用户操作')
                        if path=='/api/users' or (len(parts)==3):
                            c.execute('INSERT INTO operator_users(id,name,role,active,version) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,role=excluded.role,active=excluded.active,version=excluded.version',(result['id'],result['display_name'],result['role'],int(result['active'] and result['role'] in ROLES),result['version']))
                    return self.respond(result)
                erp_access.authorize_authenticated(path,body,role)
                if path.startswith('/api/chat/') and 'workspace.chat' not in user['permissions']['modules']:raise auth.AuthError(403,'当前账号无权使用内部聊天')
                if path.startswith('/api/feedback') and 'system.feedback' not in user['permissions']['modules']:raise auth.AuthError(403,'当前账号无权使用问题反馈')
                if path=='/api/warehouse' and body.get('stage') not in ('stock','allocation_draft','confirm_dispatch'):raise auth.AuthError(400,'请按库存登记、保存拟实发或确认写入实发流程提交')
                if path=='/api/warehouse' and ('inventory_revision' not in body or 'version' not in body):raise auth.AuthError(409,'缺少库存版本，请重新读取库存后提交')
                if path=='/api/master' and (body.get('kind')=='rule' or (body.get('kind')=='product' and body.get('create') is not True) or (body.get('kind')=='customer' and body.get('id') and body.get('create') is not True)) and 'expected' not in body:raise auth.AuthError(409,'缺少档案版本，请重新读取后提交')
                if path=='/api/master/batch-rules' and any('expected' not in row for row in body.get('rules',[]) if isinstance(row,dict)):raise auth.AuthError(409,'缺少价格版本，请重新读取后提交')
                def modern(b):
                    if isinstance(b,dict):b.update(workflow_version=1,dispatch_required=True)
                if path=='/api/orders' or (len(parts)==4 and parts[3]=='order'):modern(body)
                if path=='/api/orders':body['daily_order']=True
                if path=='/api/batch':
                    for op in body.get('operations',[]):
                        if isinstance(op,dict):
                            if op.get('action')=='order':
                                modern(op.setdefault('body',{}))
                                if not op.get('order_id'):op['body']['daily_order']=True
                            if op.get('update') is not None:modern(op['update'])
            else:
                erp_access.authorize(path,body,role)
                actor=evidence_actor(None,role) if role else {'id':'pilot','display_name':'','role':'','permissions':{'modules':[],'actions':[],'data_scopes':[]}}
            if (path.startswith('/api/chat/') or path.startswith('/api/feedback') or path=='/api/notifications/read') and not self.auth_enabled():
                raise auth.AuthError(401,'请登录后使用内部协作功能')
            if path=='/api/receipt-ocr/settings':result=receipt_ocr_settings_save(body,actor)
            elif path=='/api/receipt-evidence/recognize':result=recognize_receipt_evidence(body,actor)
            elif len(parts)==4 and parts[:2]==['api','receipt-evidence'] and parts[3]=='discard':result=discard_receipt_evidence(parts[2],actor)
            elif path=='/api/chat/send':
                with connect(True) as c:result=collaboration.send(c,user,body,now,audit)
            elif path=='/api/chat/thread':
                with connect(True) as c:result=collaboration.create_thread(c,user,body,now,audit)
            elif path=='/api/chat/read':
                with connect(True) as c:result=collaboration.read_thread(c,user,body)
            elif path=='/api/notifications/read':
                with connect(True) as c:result=collaboration.mark_notifications(c,user,body)
            elif path=='/api/feedback':
                with connect(True) as c:result=collaboration.create_feedback(c,user,body,now,audit)
            elif path=='/api/feedback/reply':
                with connect(True) as c:result=collaboration.reply_feedback(c,user,body,now,audit)
            elif path=='/api/orders': result=mutate('order',body,role)
            elif path=='/api/batch': result=batch_mutate(body,role)
            elif len(parts)==4 and parts[:2]==['api','orders'] and parts[3] in ('order','negotiate','settle','review','return-review','receipt','void-receipt','confirm-weight'):
                result=mutate(parts[3],body,role,parts[2])
            elif path=='/api/master': result=master(body,role)
            elif path=='/api/master/batch-rules':result=batch_rules(body,role)
            elif path=='/api/master/product-order':result=save_product_order(body,role)
            elif path=='/api/dispatch':result=save_dispatch(body,role)
            elif path=='/api/inventory-check':
                import inventory_reconciliation
                with connect(True) as c:
                    check_business_epoch(c,body);result=inventory_reconciliation.save(c,body,role,now,audit)
            elif path=='/api/warehouse':result=save_warehouse(body,role)
            elif path in ('/api/returns','/api/returns/action','/api/processing','/api/processing/edit','/api/processing/delete','/api/stock-close'):
                with connect(True) as c:
                    check_business_epoch(c,body);ops=inventory.Operations(c,now,audit)
                    method={'/api/returns':ops.create_return,'/api/returns/action':ops.return_action,'/api/processing':ops.process,'/api/processing/edit':ops.process_update,'/api/processing/delete':ops.process_delete,'/api/stock-close':ops.close}[path]
                    result={'record':method(body,role),'inventory_revision':inventory.revision(c)}
            elif path=='/api/curing':
                import curing
                with connect(True) as c:
                    check_business_epoch(c,body);result=curing.save(c,body,role,audit,now())
                    result['inventory_revision']=inventory.revision(c)
            elif path=='/api/inventory-value':
                import inventory_valuation
                with connect(True) as c:
                    check_business_epoch(c,body);result=inventory_valuation.save_settings(c,body,role,now(),audit)
            elif path=='/api/processing/rules':
                with connect(True) as c:result=inventory.save_processing_rules(c,body,role,now,audit)
            elif path=='/api/driver/return-action':
                with connect(True) as c:
                    check_business_epoch(c,body);result=driver_portal.return_action(c,user,body,now,audit)
            elif path=='/api/driver/weights':
                with connect(True) as c:
                    check_business_epoch(c,body);result=driver_portal.save_weights(c,user,body,now,audit,weights,save)
            elif path=='/api/driver/returns':
                with connect(True) as c:
                    check_business_epoch(c,body);result=driver_portal.submit(c,user,body,now,audit)
            elif path=='/api/opening-receipts':
                import opening_receipts
                with connect(True) as c:
                    check_business_epoch(c,body);result=opening_receipts.save(c,body,role,now(),audit)
            elif path=='/api/order-corrections':
                with connect(True) as c:
                    check_business_epoch(c,body);result=order_corrections.save(c,body,role,now,audit,normalize_order,save,get_order)
            elif path=='/api/gel-tofu/output':
                with connect(True) as c:
                    check_business_epoch(c,body);result=gel_tofu.save(c,body,role,now,audit)
            elif path.startswith('/api/finished-goods/'):
                with connect(True) as c:
                    check_business_epoch(c,body);result=finished_goods.save(c,path.rsplit('/',1)[-1],body,role,now,audit)
            elif path.startswith('/api/trade/'):
                with connect(True) as c:
                    check_business_epoch(c,body);result=trade.save(c,path.rsplit('/',1)[-1],body,role,now,audit)
            elif path.startswith('/api/assets/'):
                with connect(True) as c:
                    check_business_epoch(c,body);result=assets.save(c,path.rsplit('/',1)[-1],body,role,now,audit)
            elif path=='/api/audit-rollback':
                import audit_rollback
                with connect(True) as c:
                    check_business_epoch(c,body)
                    try:audit_id=int(body.get('audit_id'))
                    except (TypeError,ValueError):raise ValueError('请选择操作记录')
                    result=audit_rollback.execute(c,audit_id,body.get('reason'),body.get('fingerprint'),role,now,audit)
            elif path=='/api/factory/delete':
                with connect(True) as c:
                    check_business_epoch(c,body);result=production_management.delete_record(c,body,role,now,audit)
            elif path in ('/api/social-compensation','/api/crate-packaging'):
                with connect(True) as c:
                    check_business_epoch(c,body)
                    if path=='/api/social-compensation':
                        import social_policy
                        result=social_policy.save(c,body,role,now,audit)
                    else:
                        import crate_packaging
                        result=crate_packaging.save(c,body,role,now,audit)
            elif path.startswith('/api/factory/'):
                kind=path.rsplit('/',1)[-1]
                if kind not in production_management.PERMISSIONS:raise ValueError('未知厂长作业')
                if kind in ('contractor-staff','contractor-attendance') and role not in ('管理员','物流负责人'):raise auth.AuthError(403,'承包方人员考勤仅供管理员和运输负责人维护')
                if kind in ('settings','finance-settings','system-settings'):raise ValueError('参数修改请在参数设置页逐项申请，管理员审批通过后生效')
                with connect(True) as c:
                    check_business_epoch(c,body);result=production_management.save(c,kind,body,role,now,audit,actor=REQUEST_ACTOR.get())
            elif path.startswith('/api/purchasing/'):
                method=path.rsplit('/',1)[-1]
                if method not in purchasing.PERMISSIONS:raise ValueError('未知采购操作')
                with connect(True) as c:
                    check_business_epoch(c,body);record=getattr(purchasing.Operations(c,now,audit),method.replace('-','_'))(body,role)
                result={'ok':True,'id':record['id']}
            elif path=='/api/fund-accounts':
                import funds
                with connect(True) as c:
                    check_business_epoch(c,body);result=funds.save(c,body.get('action'),body,role,now,audit)
            elif path=='/api/byproduct-statements/issue':
                import byproduct_accounts as ba
                with connect(True) as c:
                    check_business_epoch(c,body);result=ba.issue(c,body,role,now,audit)
            elif path=='/api/byproduct-settlement':
                action=body.get('action')
                methods={'config':resources_costs.save_byproduct_config,'price':resources_costs.save_byproduct_price,'settle':resources_costs.settle_byproduct}
                if action not in methods:raise ValueError('未知豆渣结算操作')
                if action=='config' and type(body.get('version')) is not int:raise ValueError('缺少豆渣参数版本，请重新读取')
                with connect(True) as c:
                    check_business_epoch(c,body);result=methods[action](c,body,role,now,audit)
                    if action=='config':result={k:result[k] for k in ('buyer','customer_id','basis','yield_ratio','add_kg','version')}
                    elif action=='settle':result=resources_costs.byproduct_business_record(result)
            elif path.startswith('/api/resources/'):
                methods={'item':'item','material':'material','material-batch':'material_batch','workshop-count':'workshop_count','item-delete':'item_delete','item-order':'item_order','amortize-close':'amortize_close','expense':'expense','expense-estimate':'expense_estimate','expense-edit':'expense_edit','expense-category':'expense_category','expense-category-delete':'expense_category_delete','expense-counterparty':'expense_counterparty','expense-review':'expense_review','expense-payment':'expense_payment','byproduct':'byproduct','receive':'receive_byproduct','void':'void','restore':'restore','period':'period','value':'value','quality':'quality','attribute':'attribute'}
                method=methods.get(path.rsplit('/',1)[-1])
                if not method:raise ValueError('未知台账操作')
                with connect(True) as c:
                    check_business_epoch(c,body);result=getattr(resources_costs.Operations(c,now,audit),method)(body,role)
                    if method in ('byproduct','receive_byproduct') or body.get('ledger')=='byproduct':result=resources_costs.byproduct_business_record(result)
            elif path=='/api/fleet':result=fleet_master(body,role)
            elif path=='/api/order-archive':result=duplicate_order_archive(body,role)
            elif path=='/api/business-reset':
                import business_reset
                with connect(True) as c:
                    check_business_epoch(c,body);result=business_reset.save(c,body,role,now,audit)
            elif path=='/api/trial-data':result=trial_data(body,role)
            elif path=='/api/operator-users':result=save_operator_user(body,role)
            elif path=='/api/statements/issue-batch':
                import statements
                with connect(True) as c:
                    check_business_epoch(c,body);result=statements.issue_batch(c,body,role,now,audit)
            elif path=='/api/statements/issue':
                import statements
                with connect(True) as c:
                    check_business_epoch(c,body);result=statements.issue(c,body,role,now,audit)
            elif path=='/api/backup':
                erp_access.require_role(role,'system.backup')
                folder=DB.parent/'backups';folder.mkdir(exist_ok=True);folder.chmod(0o700)
                target=folder/('erp-'+datetime.now(TZ).strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(2)+'.db')
                if self.auth_enabled():
                    from ops.erp_ops import backup_database
                    result=backup_database(DB,folder);target=Path(result['backup'])
                else:
                    with connect() as c:
                        dest=sqlite3.connect(target)
                        try:c.backup(dest)
                        finally:dest.close()
                target.chmod(0o600)
                with connect(True) as c: audit(c,role,'生成数据库备份',target.name)
                result={'path':str(target),'manifest':str(target)+'.manifest.json' if self.auth_enabled() else None}
            else: return self.respond({'error':'未知操作'},404)
            if path.startswith('/api/trade/transport-') and user and not set(user['permissions']['modules']) & {'finance.costs','finance.expense-payables','finance.transport-settlement','workspace.analytics'}:
                result={k:v for k,v in result.items() if k in ('id','kind','version','business_date','trip_id','trip_name','execution_state','voided','changed_count')}
            byproduct_response=path in ('/api/byproduct-settlement','/api/byproduct-statements/issue','/api/resources/byproduct','/api/resources/receive') or path in ('/api/resources/void','/api/resources/restore') and body.get('ledger')=='byproduct'
            if self.auth_enabled() and not byproduct_response and not ({'finance.receivables','finance.settlement'} & set(user['permissions']['modules'])):result=erp_access.redact_finance(result)
            if self.auth_enabled() and not byproduct_response and not erp_access.can_read_data(user['permissions'],'sales-prices'):result=erp_access.redact_prices(result)
            if self.auth_enabled() and not byproduct_response and path.startswith('/api/resources/') and path not in ('/api/resources/expense-review','/api/resources/expense-payment') and not erp_access.can_read_data(user['permissions'],'material-costs'):result=erp_access.redact_costs(result)
            if self.auth_enabled() and path.startswith('/api/finished-goods/') and not erp_access.can_read_data(user['permissions'],'purchase-prices'):result=finished_goods.quantity_only(result)
            self.respond(result)
        except auth.AuthError as e:self.auth_error(e)
        except ValidationError as e:self.respond({'error':str(e),'issues':e.issues},400)
        except (ValueError,TypeError,KeyError,InvalidOperation) as e: self.respond({'error':str(e)},400)
        except sqlite3.Error: self.respond({'error':'数据库操作未完成，请重试；原数据保持不变'},500)
        except Exception: self.respond({'error':'操作未完成，请刷新后重试'},500)
        finally:REQUEST_ACTOR.reset(actor_context);REQUEST_TOKEN.reset(token_context);erp_access.GRANTS.reset(grants_context)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='豆制品 ERP 本机试运行')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--lan-address',help='同时开放指定本机私有IPv4及子网，例如192.168.31.39/24；仍需账号登录')
    parser.add_argument('--database',type=Path,help='指定独立试验数据库')
    parser.add_argument('--test-pilot',action='store_true',help='仅隔离临时数据库的旧流程测试，禁止正式使用')
    parser.add_argument('--create-admin',action='store_true',help='交互创建首位管理员后退出')
    args=parser.parse_args()
    lan=None
    if args.lan_address:
        try:lan=lan_interface(args.lan_address)
        except ValueError as e:parser.error(str(e))
        if args.test_pilot:parser.error('无账号试验模式不能开放到局域网')
    if args.database:DB=args.database.resolve()
    if not os.environ.get('ERP_DRIVER_PHOTO_DIR'):
        os.environ['ERP_DRIVER_PHOTO_DIR']=str((DB.parent/'driver-photos'))
        driver_portal.PHOTO_ROOT=Path(os.environ['ERP_DRIVER_PHOTO_DIR'])
    if args.test_pilot and (not args.database or DB==ROOT/'data'/'erp.db' or not str(DB).startswith(('/tmp/','/private/tmp/','/var/folders/','/private/var/folders/'))):parser.error('--test-pilot 仅允许系统临时目录下的独立测试数据库')
    os.umask(0o077)
    init_db(demo=args.test_pilot)
    DB.chmod(0o600)
    if args.create_admin:
        import getpass
        username=input('管理员账号（英文/数字）: ').strip();name=input('显示姓名: ').strip();password=getpass.getpass('密码（至少12字符）: ')
        if password!=getpass.getpass('再次输入密码: '):parser.error('两次密码不一致')
        with connect(True) as c:auth.create_initial_admin(c,username,name,password,int(time.time()),audit=lambda c,a,e,b=None,d=None:audit(c,'系统',a,e,b,d))
        print('管理员已创建，请启动服务后登录。');sys.exit(0)
    if lan:
        with connect() as c:
            if not c.execute('SELECT 1 FROM auth_users WHERE active=1 LIMIT 1').fetchone():parser.error('请先创建正式账号，再开启局域网访问')
    servers=[]
    try:
        srv=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);servers.append(srv)
        if lan:
            lan_srv=ThreadingHTTPServer((str(lan.ip),srv.server_port),Handler)
            lan_srv.allowed_authorities={f'{lan.ip}:{lan_srv.server_port}'};lan_srv.lan_network=lan.network
            servers.append(lan_srv)
    except OSError as e:
        for instance in servers:instance.server_close()
        print(f'无法启动服务：{e}。请核对地址和端口。');sys.exit(1)
    for instance in servers:
        instance.test_pilot=args.test_pilot;instance.daemon_threads=False
    import signal
    def stop_service(signum,frame):
        def stop_all():
            for instance in servers:instance.shutdown()
        threading.Thread(target=stop_all,daemon=True).start()
    signal.signal(signal.SIGTERM,stop_service)
    signal.signal(signal.SIGINT,stop_service)
    if lan:threading.Thread(target=lan_srv.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{srv.server_port}'
    print(f'豆制品 ERP：{url}\n数据库：{DB}\n按 Ctrl+C 停止服务。',flush=True)
    if lan:print(f'同一Wi-Fi手机入口：http://{lan.ip}:{lan_srv.server_port}（需要账号登录）',flush=True)
    if not args.no_browser:threading.Timer(0.5,lambda:webbrowser.open(url)).start()
    try:srv.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        for instance in servers:instance.server_close()
