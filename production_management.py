"""Factory daily records, flexible attendance, evidence-based production reports.

Quantities are decimal strings. Records use optimistic versions and request keys;
posting output to finished stock is explicit and atomic. No function commits.
"""
import json,secrets,hashlib,re
from datetime import datetime,date,timedelta
from decimal import Decimal
import resources_costs as rc
import erp_access as access
import auth
import inventory
import production_daily as daily
import payroll
import production_config as pc
import sales_query

def production_qty(value,label,unit):
    q=rc.qty(value,label)
    if q==q.to_integral():return q
    if unit in ('公斤','kg','千克'):return q
    if unit=='筐' and (q*2)==(q*2).to_integral():return q
    raise ValueError(label+'按筐或包填写整数'+('，筐可填 0.5' if unit=='筐' else ''))

TABLES={'schedule':'factory_schedules','daily':'factory_daily','group':'factory_groups','employee':'factory_employees','attendance':'factory_attendance','run':'factory_runs','scrap':'factory_scrap'}
DEFAULTS={'tofu_soak_kg':'550','skin_soak_kg':'500','small_slurry_kg':'40','small_slurry_crates':'10','large_slurry_kg':'33','large_slurry_crates':'4','skin_slurry_kg':'','skin_slurry_crates':'','average_weight_alert_pct':'10','average_weight_alert_kg':'0.5','weight_alert_kg':'2','weight_alert_pct':'10','receivable_limit_yuan':'20000','receivable_days':'5','evidence_alert_pct':'10','driver_photo_limit':'6','driver_photo_max_edge':'1080','driver_crate_photo_required':'1','driver_photo_keep_days':'180',
 'session_idle_minutes':'30','session_hours':'8','remember_days':'7','password_min_length':'12','login_attempts':'5','login_lock_minutes':'15','login_ip_attempts':'30',
 'backup_keep_hourly_days':'7','backup_keep_daily_days':'60','backup_keep_monthly_months':'24','backup_min_keep':'30',
 'crate_overdue_days':'90','statement_objection_days':'3','statement_deemed_confirmed':'1','over_order_alert_pct':'20','order_max_lines':'50','purchase_default_payment_days':'0','production_backfill_days':'30','page_size_default':'50'}
PARAMETER_GROUPS=[
    {'id':'weight','title':'称重预警','items':[
        {'key':'average_weight_alert_kg','label':'平均净重偏离标准单重','unit':'公斤','description':'司机、客户平均净重每筐与标准单重比较；偏差绝对值超过此公斤数时标色，等于不提示。','max':100},
        {'key':'average_weight_alert_pct','label':'平均净重偏离标准比例','unit':'%','description':'与公斤阈值满足任一条件即提示；标准单重缺失时仅按比例判断。','min':1,'max':50},
        {'key':'weight_alert_kg','label':'称重分析重量差','unit':'公斤','description':'称重分析中，平均净重与参考均重、司机与客户净重差超过此值提示；与比例阈值满足任一条件即提示。'},
        {'key':'weight_alert_pct','label':'称重分析比例差','unit':'%','description':'用于司机、客户、本趟、全日均重的称重分析核对，与重量差阈值满足任一条件即提示。'}]},
    {'id':'production','title':'生产核对','items':[
        {'key':'evidence_alert_pct','label':'用豆核对与出品率变化','unit':'%','description':'用豆不同计量方法差异、同口径出品率变化超过此比例提示。'}, {'key':'production_backfill_days','label':'生产日报可补录天数','unit':'天','description':'允许补录过去多少天的生产日报；0表示只能登记今天，历史更正仍走原日期记录。','integer':True,'min':0,'max':30}]},
    {'id':'receivables','title':'应收预警','items':[
        {'key':'receivable_limit_yuan','label':'历史未收金额','unit':'元','description':'历史未收超过此金额提示；与账龄满足任一条件即提示。'},
        {'key':'receivable_days','label':'账龄','unit':'天','description':'最早未收业务至所选日期超过此天数提示；账龄提示不等于合同逾期。','integer':True}]},
    {'id':'soaking','title':'泡豆换算','items':[
        {'key':'tofu_soak_kg','label':'豆腐每桶干豆','unit':'公斤 / 桶','description':'豆腐泡豆桶折算干豆数量。','positive':True},
        {'key':'skin_soak_kg','label':'豆皮每桶干豆','unit':'公斤 / 桶','description':'豆皮泡豆桶折算干豆数量。','positive':True}]},
    {'id':'slurry','title':'浆缸换算','items':[
        {'key':'large_slurry_kg','label':'大豆腐每缸用豆','unit':'公斤 / 缸','description':'大豆腐用浆量折算干豆数量。','positive':True},
        {'key':'large_slurry_crates','label':'大豆腐每缸产出','unit':'筐 / 缸','description':'大豆腐产出反推用豆的换算依据。','positive':True},
        {'key':'small_slurry_kg','label':'中豆腐每缸用豆','unit':'公斤 / 缸','description':'中豆腐用浆量折算干豆数量。','positive':True},
        {'key':'small_slurry_crates','label':'中豆腐每缸产出','unit':'筐 / 缸','description':'中豆腐产出反推用豆的换算依据。','positive':True},
        {'key':'skin_slurry_kg','label':'豆皮每缸用豆','unit':'公斤 / 缸','description':'未核定可留空，缺失时不推算。','optional':True},
        {'key':'skin_slurry_crates','label':'豆皮每缸产出（倒推用豆参数）','unit':'产品单位 / 缸','description':'按产品档案的实际发货单位填写，不固定为筐。未核定留空，不倒推；余量法接收产品不依赖此值分摊实际用豆。','optional':True}]},
    {'id':'driver','title':'司机到店登记','items':[
        {'key':'driver_photo_limit','label':'每项照片上限','unit':'张','description':'司机称重、回框每项最多可保留的照片张数；修改后按此上限核对，超出需先删除。','integer':True,'positive':True,'min':1,'max':9},
        {'key':'driver_photo_max_edge','label':'照片压缩长边','unit':'像素','description':'司机拍照上传前按该长边压缩；数值越大越清晰、流量越大，默认1080。','integer':True,'positive':True,'min':120,'max':2400},
        {'key':'driver_crate_photo_required','label':'回框必须拍照','unit':'','description':'1=填写回框数量时必须拍回框照片；0=允许先不拍，由库管核对。','boolean':True,'integer':True,'max':1},
        {'key':'driver_photo_keep_days','label':'照片保留天数','unit':'天','description':'超过该天数且单据已结算满90天的司机照片，按月归档后清理；未结算或有退货争议的照片不清理。','integer':True,'min':30,'max':3650}]},
    {'id':'security','title':'账号与安全','items':[
        {'key':'session_idle_minutes','label':'登录空闲超时','unit':'分钟','description':'连续无操作超过此时间需重新登录；记住账号的长会话不按此值。','integer':True,'min':5,'max':240},
        {'key':'session_hours','label':'正常登录有效期','unit':'小时','description':'未勾选“记住账号”时一次登录的最长有效时间。','integer':True,'min':1,'max':24},
        {'key':'remember_days','label':'记住账号有效期','unit':'天','description':'勾选“记住账号”后的免登录天数，最长不超过30天。','integer':True,'min':1,'max':30},
        {'key':'password_min_length','label':'密码最小长度','unit':'位','description':'新建、重置、修改密码时的最小长度；只能调高，系统底线为12位。','integer':True,'min':12,'max':64},
        {'key':'login_attempts','label':'账号失败次数','unit':'次','description':'同一账号在锁定时长内允许的连续失败次数。','integer':True,'min':3,'max':20},
        {'key':'login_lock_minutes','label':'登录失败锁定时长','unit':'分钟','description':'失败计数窗口与锁定时长；修改后从下一次登录开始按新值计数。','integer':True,'min':5,'max':120},
        {'key':'login_ip_attempts','label':'同一IP失败次数','unit':'次','description':'同一来源IP在窗口内允许的失败次数，用于防止撞库。','integer':True,'min':10,'max':200}]},
    {'id':'backup','title':'数据备份','items':[
        {'key':'backup_keep_hourly_days','label':'近期全量保留','unit':'天','description':'最近这些天的自动备份全部保留。','integer':True,'min':1,'max':30},
        {'key':'backup_keep_daily_days','label':'按天保留','unit':'天','description':'超过全量保留期后，每天保留最新一份的天数。','integer':True,'min':7,'max':365},
        {'key':'backup_keep_monthly_months','label':'按月保留','unit':'月','description':'超过按天保留期后，每月保留最新一份的月数。','integer':True,'min':3,'max':120},
        {'key':'backup_min_keep','label':'至少保留份数','unit':'份','description':'任何清理策略下都至少保留的备份份数，调低前请确认可回退。','integer':True,'min':5,'max':500}]},
    {'id':'crates','title':'周转筐与欠框','items':[
        {'key':'crate_overdue_days','label':'欠框超期天数','unit':'天','description':'欠框超过此天数计入超期提醒；7天、30天分桶保持不变。','integer':True,'min':7,'max':365}]},
    {'id':'statement','title':'客户对账','items':[
        {'key':'statement_objection_days','label':'异议提出天数','unit':'天','description':'客户结算单提示的异议期限。','integer':True,'min':1,'max':30},
        {'key':'statement_deemed_confirmed','label':'逾期视为确认','unit':'','description':'1=异议期满未提出视为确认；0=只提示期限，不作视为确认表述。','boolean':True,'integer':True,'max':1}]}, {'id':'orders','title':'订单与超订','items':[{'key':'over_order_alert_pct','label':'超订提醒比例','unit':'%','description':'分配量超过订货量的比例达到此值时高亮提醒；0表示只要超订就提醒。','integer':True,'min':0,'max':100}, {'key':'order_max_lines','label':'单张订单最多产品行数','unit':'行','description':'新建或修改订货单时允许的最大产品行数。','integer':True,'min':10,'max':100}]}, {'id':'purchases','title':'采购默认值','items':[{'key':'purchase_default_payment_days','label':'新供应商默认账期','unit':'天','description':'新建供应商时付款账期的默认值；已有供应商仍按各自档案。','integer':True,'min':0,'max':120}]}, {'id':'lists','title':'列表与分页','items':[{'key':'page_size_default','label':'列表默认每页条数','unit':'条','description':'分页列表未指定时每页显示的条数，建议20/50/100。','integer':True,'min':10,'max':200}]}]

ADMIN_PARAMETER_KEYS={'driver_photo_limit','driver_photo_max_edge','driver_crate_photo_required','driver_photo_keep_days','session_idle_minutes','session_hours','remember_days','password_min_length','login_attempts','login_lock_minutes','login_ip_attempts','backup_keep_hourly_days','backup_keep_daily_days','backup_keep_monthly_months','backup_min_keep','crate_overdue_days','statement_objection_days','statement_deemed_confirmed'}

def parameter_permission(key,c=None):
    if c is None and isinstance(key,str) and re.fullmatch(r'(?:systems\.[A-Za-z][A-Za-z0-9_-]{0,49}\.soak_kg|processes\.[A-Za-z][A-Za-z0-9_-]{0,49}\.(?:dry_kg|output_qty))',key):return 'production.settings'
    if c is not None and key in {i['key'] for i in pc.parameter_items(pc.latest(c))}:return 'production.settings'
    if key not in DEFAULTS:raise ValueError('未知业务参数')
    if key in ADMIN_PARAMETER_KEYS:return 'system.parameters'
    return 'finance.alert-settings' if key in daily.FINANCE_KEYS else 'production.settings'

def parameter_catalog(c,user=None):
    role=user['role'] if user else '管理员';grants=user['permissions'] if user else access.defaults(role)
    definitions=parameter_definitions(c)
    visible={g['id'] for g in definitions} if role=='管理员' else access.parameter_groups_visible(grants) if role!='司机' else set()
    groups=[{**g,'items':[{**item,'can_request':role=='管理员' or role!='老板' and parameter_permission(item['key'],c) in grants.get('actions',[])} for item in g['items']]} for g in definitions if g['id'] in visible]
    keys={item['key'] for g in groups for item in g['items']};cfg=parameter_settings(c)
    requests=[r for r in rc.rows(c,'factory_parameter_requests') if (role=='管理员' or (r['key'] in keys or r.get('group_id') in visible) and r['requester_id']==(user or {}).get('id'))]
    labels={item['key']:item['label'] for g in groups for item in g['items']}
    result={'production_config':pc.get(c) if role=='管理员' or 'soaking' in visible else None,'production_config_history':pc.history(c) if role=='管理员' or 'soaking' in visible else [],'can_configure':role=='管理员','config_version':pc.latest(c)['version'],'config_min_date':pc.minimum_date(c),'settings':{k:v for k,v in cfg.items() if k in keys or k=='version'},'groups':groups,'defaults':{k:DEFAULTS.get(k,cfg[k]) for k in keys},'can_review':role=='管理员','requests':[{**r,'label':labels.get(r['key'],r.get('parameter_label',r['key']))} for r in reversed(requests)]}
    if role=='管理员':
        byproduct=rc.byproduct_config(c)
        result['byproduct_settings']={k:byproduct[k] for k in ('buyer','customer_id','basis','yield_ratio','add_kg','version')}
    return result

def parameter_definitions(c):
    groups=[{**g,'items':[dict(item) for item in g['items']]} for g in PARAMETER_GROUPS]
    config=pc.latest(c)
    for g in groups:
        for item in g['items']:
            if item['key'].endswith('_slurry_crates'):
                process_id=item['key'].split('_slurry_crates')[0]
                process=next((p for p in config['processes'] if p['id']==process_id),{})
                unit=process.get('output_unit','筐' if process_id in ('large','small') else '')
                item['unit']=(unit or '待核定产品单位')+' / 缸'
                item['description']+=' 此参数用于产出倒推用豆，不是浆缸体积。多单位工艺必须核实各产品换算，不能直接混用。'
    for item in pc.parameter_items(pc.latest(c)):
        next(g for g in groups if g['id']==item['group_id'])['items'].append(item)
    return groups

def parameter_settings(c):return {**settings(c),**{i['key']:i['value'] for i in pc.parameter_items(pc.latest(c))}}

def validated_parameter_value(key,value,c=None):
    parameter_permission(key,c)
    item=next((i for g in (parameter_definitions(c) if c is not None else PARAMETER_GROUPS) for i in g['items'] if i['key']==key),None)
    if not item:raise ValueError('未知业务参数')
    val=optional(value,'参数值')
    if val=='' and not item.get('optional'):raise ValueError('请填写参数值')
    if item.get('boolean'):
        if val not in ('0','1'):raise ValueError('请选择是或否')
        return val
    if val and item.get('positive') and Decimal(val)<=0:raise ValueError('换算参数必须大于0')
    if val and 'min' in item and Decimal(val)<item['min']:raise ValueError('参数值须在'+str(item['min'])+'到'+str(item['max'])+'之间')
    if val and 'max' in item and Decimal(val)>item['max']:raise ValueError('参数值须在'+str(item.get('min',0))+'到'+str(item['max'])+'之间')
    if val and item.get('integer') and Decimal(val)!=Decimal(val).to_integral():raise ValueError('账期预警天数须为整数')
    return val

def request_parameter(c,b,role,actor,now,audit):
    key=b.get('key');access.require_role(role,parameter_permission(key,c))
    grants=(actor or {}).get('permissions') or access.GRANTS.get() or access.defaults(role)
    if role!='管理员' and not any(g['id'] in access.parameter_groups_visible(grants) and any(i['key']==key for i in g['items']) for g in parameter_definitions(c)):raise ValueError('当前账号无此参数查看与申请权限')
    request_key=rc.text(b.get('request_key'),'提交编号',100);value=validated_parameter_value(key,b.get('value'),c);reason=rc.text(b.get('reason'),'修改原因',500)
    actor=actor or {};requester_id=actor.get('id',role)
    fingerprint=hashlib.sha256(rc.dump({'key':key,'value':value,'reason':reason,'version':b.get('version'),'effective_date':b.get('effective_date'),'config_version':b.get('config_version'),'actor':requester_id}).encode()).hexdigest()
    prior=c.execute('SELECT payload FROM factory_parameter_requests WHERE request_key=?',(request_key,)).fetchone()
    if prior:
        record=json.loads(prior[0])
        if record['fingerprint']!=fingerprint:raise ValueError('提交编号已用于其他参数申请')
        return record
    cfg=parameter_settings(c)
    if key not in DEFAULTS:
        config=pc.latest(c)
        if type(b.get('config_version')) is not int or b.get('config_version')!=config['version']:raise ValueError('生产配置已变化，请重新打开申请')
        effective=rc.day(b.get('effective_date'))
        if effective<pc.minimum_date(c):raise ValueError('请选择晚于已发布配置的生效日期')
    if type(b.get('version')) is not int or b['version']!=cfg['version']:raise ValueError('参数已更新，请刷新后重新申请')
    if value==cfg[key]:raise ValueError('新值与当前值相同，无需申请')
    record={'id':'PARAM-'+secrets.token_hex(8),'key':key,'old_value':cfg[key],'new_value':value,'reason':reason,'requester_id':requester_id,'requester_name':actor.get('display_name') or role,'requester_role':role,'submitted_at':now(),'status':'pending','version':1,'settings_version':cfg['version'],'fingerprint':fingerprint}
    definition=next((g,i) for g in parameter_definitions(c) for i in g['items'] if i['key']==key);record.update(group_id=definition[0]['id'],parameter_label=definition[1]['label'])
    if key not in DEFAULTS:record.update(scope='production-config',effective_date=effective,config_version=config['version'])
    c.execute('INSERT INTO factory_parameter_requests VALUES(?,?,?)',(record['id'],request_key,rc.dump(record)))
    audit(c,role,'申请修改业务参数',record['id'],None,record);return record

def review_parameter(c,b,role,actor,now,audit):
    if role!='管理员':raise ValueError('仅管理员可以审批参数修改')
    access.require_role(role,'system.parameters')
    row=c.execute('SELECT payload FROM factory_parameter_requests WHERE id=?',(b.get('id'),)).fetchone()
    if not row:raise ValueError('参数申请不存在')
    record=json.loads(row[0]);before=dict(record)
    if record['status']!='pending' or type(b.get('version')) is not int or record['version']!=b['version']:raise ValueError('此申请已处理，请刷新后查看')
    decision=b.get('decision')
    if decision not in ('approve','reject'):raise ValueError('请选择通过或驳回')
    reason=rc.text(b.get('reason',''),'审批说明',500,decision=='reject')
    if decision=='approve':
        cfg=parameter_settings(c)
        if cfg.get(record['key'])!=record['old_value']:raise ValueError('此参数已被其他申请修改，请驳回后重新申请')
        if record.get('scope')=='production-config':
            config=pc.latest(c);item=next(i for i in pc.parameter_items(config) if i['key']==record['key'])
            next(r for r in config[item['kind']] if r['id']==item['entity_id'])[item['field']]=record['new_value']
            pc.publish(c,{'version':config['version'],'effective_date':record['effective_date'],'config':config,'note':'参数审批：'+record['reason']},role,now,audit)
        else:save(c,'system-settings',{'version':cfg['version'],record['key']:record['new_value']},role,now,audit)
    actor=actor or {};record.update(status='approved' if decision=='approve' else 'rejected',version=record['version']+1,reviewer_id=actor.get('id',role),reviewer_name=actor.get('display_name') or role,reviewed_at=now(),review_reason=reason)
    c.execute('UPDATE factory_parameter_requests SET payload=? WHERE id=?',(rc.dump(record),record['id']))
    audit(c,role,'通过业务参数申请' if decision=='approve' else '驳回业务参数申请',record['id'],before,record);return record


PERMISSIONS={'company-info':'system.parameters','employee-bank':'payroll.write','employee-bank-preview':'payroll.write','employee-bank-import':'payroll.write','production-attendance':'production.attendance','management-attendance':'management.attendance','management-month-save':'management.attendance','wage-cost-post':'payroll.write','attendance-month-save':'production.attendance','contractor-staff':'delivery.contractors.write','contractor-attendance':'delivery.contractors.write','production-config':'system.parameters','parameter-request':'system.parameters','parameter-review':'system.parameters','beans':'materials.issue','bean-void':'materials.issue','bean-restore':'materials.issue','schedule':'production.attendance','wage-profile':'payroll.write','wage-sheet':'payroll.write','wage-reopen':'payroll.write','wage-pay':'payroll.pay','wage-payment-void':'payroll.pay','daily':'production.record','finance-settings':'finance.alert-settings','group':'production.staff','employee':'production.staff','attendance':'production.attendance','run':'production.record','scrap':'production.record','system-settings':'system.parameters','settings':'production.settings','issue':'materials.issue','post-output':'production.record','undo-output':'production.record'}

def init_schema(c):
    """Compatibility entry; upgrade ownership is centralized in migrations.py."""
    import migrations
    return migrations.ensure(c, 'production')


def settings(c):
    r=c.execute("SELECT version,payload FROM factory_settings WHERE id='default'").fetchone()
    return {**DEFAULTS,**json.loads(r['payload']),'version':r['version']}

def rows(c,kind):return rc.rows(c,TABLES[kind])
def get(c,kind,rid):
    r=c.execute('SELECT payload FROM '+TABLES[kind]+' WHERE id=?',(rid,)).fetchone()
    return json.loads(r[0]) if r else None

def optional(v,label):return '' if v in ('',None) else rc.ds(rc.qty(v,label))
def named(c,kind,rid,active=True):
    r=get(c,kind,rid)
    if not r or active and r.get('active') is False:raise ValueError('请选择有效的'+{'schedule':'排班','daily':'每日生产','group':'小组','employee':'员工'}[kind])
    return r

def stamp(v):
    try:
        x=datetime.fromisoformat(v)
        if x.tzinfo or len(v)!=16:raise ValueError()
    except (ValueError,TypeError):raise ValueError('请填写有效的本地起止时间')
    return x

BEAN_KINDS=('consume','return')

def bean_registrations(c,limit=800):
    """Every soybean issue stays as its own registration, including voided rows.

    Cost fields are deliberately omitted: production roles register quantities and
    must not receive material valuation through this projection.
    """
    result=[]
    for (payload,) in c.execute("SELECT payload FROM material_entries WHERE json_extract(payload,'$.material_id')='RM-SOY' AND json_extract(payload,'$.kind') IN ('consume','return') ORDER BY rowid DESC LIMIT ?",(limit,)):
        e=json.loads(payload)
        if not e.get('production_system_id'):continue
        result.append({'id':e['id'],'business_date':e.get('business_date',''),'production_system_id':e.get('production_system_id',''),
            'production_system_name':e.get('production_system_name',''),'warehouse_id':e.get('warehouse_id',''),'warehouse_name':e.get('warehouse_name',''),
            'kind':e.get('kind'),'qty':e.get('qty','0'),'handler':e.get('handler',''),'note':e.get('note',''),'created_at':e.get('created_at',''),
            'sequence':e.get('sequence',0),'version':e.get('version',1),'voided':bool(e.get('voided')),'void_reason':e.get('void_reason',''),
            'voided_at':e.get('voided_at',''),'restored_at':e.get('restored_at',''),'void_history':e.get('void_history',[]),
            'production_config_version':e.get('production_config_version',0),'source_lot_id':e.get('source_lot_id',''),'source_quality':e.get('source_quality',{})})
    return result


def bean_stock(c,when):
    rc.day(when)
    stocks=rc.material_ledger(c,until=when,warehouse_details=True)[2];warehouses=[]
    for w in stocks:
        if w['id']!='RM-SOY':continue
        lots={}
        for l in w['lots']:
            row=lots.setdefault(l['lot_id'],{'lot_id':l['lot_id'],'received_date':l['received_date'],'qty':Decimal(0),'quality':l.get('quality',{})})
            row['qty']+=Decimal(l['qty'])
        warehouses.append({'warehouse_id':w['warehouse_id'],'warehouse_name':w['warehouse_name'],'qty':w['qty'],'lots':[{**l,'qty':rc.ds(l['qty'])} for l in lots.values()]})
    return {'business_date':when,'warehouses':warehouses,'basis':'截至所选业务日，包含该日已登记流水。产地与播种类型分别登记；未登记属性不推断。指定批次领用按该批次扣库存和成本。'}

def bean_totals(c,day=None):
    """Effective quantity per system and warehouse for the selected day."""
    totals={}
    for row in bean_registrations(c,10000):
        if row['voided'] or day and row['business_date']!=day:continue
        key=(row['production_system_id'],row['warehouse_id'])
        totals[key]=totals.get(key,Decimal(0))+(Decimal(row['qty']) if row['kind']=='consume' else -Decimal(row['qty']))
    return {f'{k[0]}|{k[1]}':rc.ds(v) for k,v in totals.items()}

def _bean_submission(c,key,label,body):
    fingerprint=hashlib.sha256(rc.dump({k:v for k,v in body.items() if k not in ('_data_epoch','request_key')}).encode()).hexdigest()
    saved=c.execute('SELECT value FROM meta WHERE key=?',('bean-submit:'+key,)).fetchone()
    if saved:
        result=json.loads(saved[0])
        if result.get('fingerprint')!=fingerprint:raise ValueError('提交编号已用于其他'+label)
        return result
    return None

def bean_register(c,b,role,now,audit):
    key=rc.text(b.get('request_key'),'提交编号',100);when=rc.day(b.get('business_date'))
    saved=_bean_submission(c,key,'上豆登记',b)
    if saved:return saved
    if b.get('revision')!=rc.revision(c):raise ValueError('库存或成本台账已变更，请同步后核对再提交')
    rc.open_period(c,when)
    if inventory.closed(c,when):raise ValueError('当天库存已日结，请先重开后登记上豆量')
    config=pc.get(c,when)
    if b.get('config_version',config['version'])!=config['version']:raise ValueError('生产配置已变化，请重新打开上豆登记表单')
    systems={s['id']:s for s in pc.active_systems(config)}
    rows=b.get('entries')
    if not isinstance(rows,list) or not 1<=len(rows)<=20:raise ValueError('请登记1至20条上豆记录')
    handler=rc.text(b.get('handler'),'经办人',100);note=rc.text(b.get('note',''),'登记说明',500,False)
    parsed=[];seen=set()
    for raw in rows:
        if not isinstance(raw,dict):raise ValueError('上豆登记格式无效，请重新打开表单')
        sid=raw.get('production_system_id') or raw.get('system')
        system=systems.get(sid)
        if not system:raise ValueError('请选择当天启用的磨浆系统')
        wid=raw.get('warehouse_id') or system['default_warehouse_id']
        warehouse=next((w for w in pc.warehouses(c,when) if w['id']==wid and w.get('active',True)),None)
        if not warehouse or not pc.accepts_material(warehouse,'RM-SOY'):raise ValueError('请选择允许存放大豆的有效库房')
        q=rc.qty(raw.get('qty'),'本次上豆量',True)
        lot_id=rc.text(raw.get('source_lot_id',''),'上豆批次',100,False)
        if 'source_lot_id' in raw and not lot_id:raise ValueError('请选择实际使用的大豆批次')
        if (sid,wid,lot_id) in seen:raise ValueError(system['name']+'的同一库房已在本次登记中，请合并数量或分次登记')
        seen.add((sid,wid,lot_id));parsed.append((sid,wid,q,lot_id))
    soak=b.get('soak_tanks') or {}
    if soak and not isinstance(soak,dict):raise ValueError('泡豆桶登记格式无效')
    for sid,value in soak.items():
        if sid not in systems:raise ValueError('泡豆桶所属磨浆系统无效')
        number=rc.qty(value,'泡豆桶数')
    existing=next((json.loads(r[0]) for r in c.execute('SELECT payload FROM factory_daily') if json.loads(r[0]).get('business_date')==when),None)
    stopped={sid for sid,entry in (existing or {}).get('systems',{}).items() if entry.get('state')=='stopped'}
    if any(sid in stopped for sid,wid,q,lot_id in parsed) or any(sid in stopped and rc.qty(value,'泡豆桶数')>0 for sid,value in soak.items()):
        raise ValueError('该磨浆系统已登记未开机，请先在每日生产登记中确认开机状态，再登记上豆或泡豆桶数')
    entry_ids=[]
    for index,(sid,wid,q,lot_id) in enumerate(parsed):
        entry=rc.Operations(c,now,audit).material({'request_key':key+'-'+str(index),'business_date':when,'revision':rc.revision(c),
            'material_id':'RM-SOY','warehouse_id':wid,'production_system_id':sid,'kind':'consume','qty':rc.ds(q),'amount':'0',
            'source_lot_id':lot_id,'handler':handler,'note':'上豆登记'+('：'+note if note else '')},role,actual_warehouse=True)
        entry_ids.append(entry['id'])
    if soak:
        if existing:
            updated={**existing,'systems':{**existing.get('systems',{})}}
            for sid,value in soak.items():
                current=dict(updated['systems'].get(sid) or {})
                current['soak_tanks']=rc.ds(rc.qty(value,'泡豆桶数'));current.setdefault('state','pending');updated['systems'][sid]=current
            updated['version']=int(existing.get('version',0))+1;updated['updated_at']=now()
            c.execute('UPDATE factory_daily SET payload=? WHERE id=?',(rc.dump(updated),existing['id']))
            audit(c,role,'合并登记泡豆桶数',existing['id'],existing,updated)
        else:
            config=pc.get(c,when)
            daily_body={'business_date':when,'config_version':config['version'],'systems':{sid:{'soak_tanks':rc.ds(rc.qty(soak[sid],'泡豆桶数')) if sid in soak else '', 'state':'pending'} for sid in systems},'products':[],'note':''}
            created=daily.production_day(c,daily_body,None,settings(c));created['id']='FP-'+secrets.token_hex(6).upper();created['version']=1;created['request_key']='bean-soak-'+key
            c.execute('INSERT INTO factory_daily VALUES(?,?,?)',(created['id'],created['request_key'],rc.dump(created)))
            audit(c,role,'登记泡豆桶数',created['id'],None,created)
    result={'business_date':when,'entry_ids':entry_ids,'totals':daily.issue_kg(c,when),'warehouse_totals':bean_totals(c,when),'fingerprint':_fingerprint(b)}
    c.execute('INSERT INTO meta VALUES(?,?)',('bean-submit:'+key,rc.dump(result)))
    audit(c,role,'登记磨浆系统上豆量',when,None,{'entries':entry_ids,'note':note})
    return result

def _fingerprint(b):
    return hashlib.sha256(rc.dump({k:v for k,v in b.items() if k not in ('_data_epoch','request_key')}).encode()).hexdigest()

def bean_change(c,b,role,now,audit,restore=False):
    label='恢复上豆登记' if restore else '删除上豆登记'
    key=rc.text(b.get('request_key'),'提交编号',100)
    saved=_bean_submission(c,key,label,b)
    if saved:return saved
    row=c.execute('SELECT payload FROM material_entries WHERE id=?',(b.get('id'),)).fetchone()
    if not row:raise ValueError('上豆登记不存在，请同步最新数据')
    old=json.loads(row[0])
    if old.get('material_id')!='RM-SOY' or old.get('kind') not in BEAN_KINDS or not old.get('production_system_id'):
        raise ValueError('仅磨浆系统上豆登记可以删除或恢复；其他库存流水请在原辅料台账处理')
    when=old['business_date'];rc.open_period(c,when)
    if any(json.loads(r[0])['state']=='closed' and r[1]>=when[:7] for r in c.execute('SELECT payload,month FROM resource_periods')):
        raise ValueError('后续成本月份已结账，请先重开相关月份再处理上豆登记')
    if inventory.closed(c,when):raise ValueError('当天库存已日结，请先重开后处理上豆登记')
    if not restore and old.get('voided'):raise ValueError('该上豆登记已删除，请刷新后查看')
    if restore and not old.get('voided'):raise ValueError('该上豆登记未删除，无需恢复')
    if old.get('version')!=b.get('version'):raise ValueError('该上豆登记已被其他页面更新，请同步后重试')
    reason=rc.text(b.get('reason'),label+'原因',500)
    stamp=now();history=list(old.get('void_history',[]))
    history.append({'action':'restore' if restore else 'void','at':stamp,'role':role,'reason':reason})
    record={**old,'voided':not restore,'version':old['version']+1,'void_history':history}
    if restore:record.update(restored_at=stamp,restore_reason=reason)
    else:record.update(voided_at=stamp,void_reason=reason)
    c.execute('UPDATE material_entries SET payload=? WHERE id=?',(rc.dump(record),record['id']))
    rc.material_ledger(c)
    result={'id':record['id'],'voided':record['voided'],'version':record['version'],'business_date':when,'production_system_id':record.get('production_system_id',''),
        'warehouse_id':record.get('warehouse_id',''),'qty':record.get('qty','0'),'reason':reason,'fingerprint':_fingerprint(b)}
    c.execute('INSERT INTO meta VALUES(?,?)',('bean-submit:'+key,rc.dump(result)))
    audit(c,role,'恢复上豆登记' if restore else '删除上豆登记',record['id'],old,record)
    return result

def _confirmed_payroll(c,month):
    return bool(c.execute("SELECT 1 FROM payroll_records WHERE json_extract(payload,'$.kind')='sheet' AND json_extract(payload,'$.month')=? AND json_extract(payload,'$.state')='confirmed' LIMIT 1",(month,)).fetchone())

def _delete_claim(c,key,label,body):
    fingerprint=_fingerprint(body)
    saved=c.execute('SELECT value FROM meta WHERE key=?',('factory-delete:'+key,)).fetchone()
    if saved:
        result=json.loads(saved[0])
        if result.get('fingerprint')!=fingerprint:raise ValueError('提交编号已用于其他'+label)
        return result
    return None

def _attendance_state(entries,current='draft'):
    return 'confirmed' if entries and all(e.get('entry_state',current)=='confirmed' for e in entries) else 'draft'

def delete_record(c,b,role,now,audit):
    if role!='管理员':raise auth.AuthError(403,'仅管理员可以删除登记记录')
    kind=b.get('kind')
    if kind not in ('schedule','attendance','attendance-month'):raise ValueError('未知删除类型')
    key=rc.text(b.get('request_key'),'提交编号',100)
    reason=rc.text(b.get('reason'),'删除原因',500)
    saved=_delete_claim(c,key,'删除操作',b)
    if saved:return saved
    import personnel
    employees={e['id']:e for e in rows(c,'employee')}
    if kind=='schedule':
        old=get(c,'schedule',b.get('id'))
        if not old:raise ValueError('排班记录不存在，请刷新后重试')
        if old.get('version')!=b.get('version'):raise ValueError('排班记录已变化，请刷新后重试')
        c.execute('DELETE FROM factory_schedules WHERE id=?',(old['id'],))
        for attendance in rows(c,'attendance'):
            if attendance.get('source_schedule_id')==old['id']:
                updated={**attendance,'version':attendance['version']+1,'updated_at':now()}
                updated.pop('source_schedule_id',None);updated.pop('source_schedule_version',None)
                c.execute('UPDATE factory_attendance SET payload=? WHERE id=?',(rc.dump(updated),updated['id']))
                audit(c,role,'清除排班来源',updated['id'],attendance,updated)
        audit(c,role,'删除厂长排班',old['id'],old,None)
        result={'ok':True,'kind':kind,'id':old['id'],'business_date':old.get('business_date',''),'reason':reason}
    elif kind=='attendance':
        old=get(c,'attendance',b.get('id'))
        if not old:raise ValueError('考勤记录不存在，请刷新后重试')
        if old.get('version')!=b.get('version'):raise ValueError('考勤记录已变化，请刷新后重试')
        entries=old.get('entries') or []
        scopes={personnel.entry_type(e,employees) for e in entries}
        scope=b.get('scope') or ''
        if scope and scope not in personnel.TYPES:raise ValueError('删除范围无效')
        if not scope:
            if len(scopes)!=1:raise ValueError('当天同时有生产工人和管理人员考勤，请选择删除范围')
            scope=next(iter(scopes))
        if scope not in scopes:raise ValueError('当天没有该类人员的考勤，请刷新后查看')
        month=old['business_date'][:7]
        if _confirmed_payroll(c,month):raise ValueError(month+' 工资已确认，请先撤回工资确认后再删除考勤')
        remaining=[e for e in entries if personnel.entry_type(e,employees)!=scope]
        if remaining:
            types={personnel.entry_type(e,employees) for e in remaining}
            record={**old,'entries':remaining,'scope_notes':{k:v for k,v in (old.get('scope_notes') or {}).items() if k in types},'state':_attendance_state(remaining,old.get('state','draft')),'version':old['version']+1,'updated_at':now(),'role':role}
            if 'production' not in types:record.pop('source_schedule_id',None);record.pop('source_schedule_version',None)
            c.execute('UPDATE factory_attendance SET payload=? WHERE id=?',(rc.dump(record),record['id']))
            audit(c,role,'删除'+personnel.TYPES[scope]+'考勤',record['id'],old,record)
            result={'ok':True,'kind':kind,'id':record['id'],'business_date':record['business_date'],'scope':scope,'remaining':len(remaining),'version':record['version'],'reason':reason}
        else:
            c.execute('DELETE FROM factory_attendance WHERE id=?',(old['id'],))
            audit(c,role,'删除'+personnel.TYPES[scope]+'考勤',old['id'],old,None)
            result={'ok':True,'kind':kind,'id':old['id'],'business_date':old['business_date'],'scope':scope,'remaining':0,'reason':reason}
    else:
        employee_id=rc.text(b.get('employee_id'),'员工',100)
        month=rc.text(b.get('month'),'月份',7)
        payroll.month_days(month)
        employee=employees.get(employee_id)
        if not employee:raise ValueError('员工不存在，请刷新后重试')
        if _confirmed_payroll(c,month):raise ValueError(month+' 工资已确认，请先撤回工资确认后再删除考勤')
        touched=deleted=0
        for record in [r for r in rows(c,'attendance') if r['business_date'].startswith(month) and any(e.get('employee_id')==employee_id for e in r.get('entries') or [])]:
            remaining=[e for e in record['entries'] if e.get('employee_id')!=employee_id]
            if remaining:
                types={personnel.entry_type(e,employees) for e in remaining}
                updated={**record,'entries':remaining,'scope_notes':{k:v for k,v in (record.get('scope_notes') or {}).items() if k in types},'state':_attendance_state(remaining,record.get('state','draft')),'version':record['version']+1,'updated_at':now(),'role':role}
                if 'production' not in types:updated.pop('source_schedule_id',None);updated.pop('source_schedule_version',None)
                c.execute('UPDATE factory_attendance SET payload=? WHERE id=?',(rc.dump(updated),record['id']))
                after=updated
            else:
                c.execute('DELETE FROM factory_attendance WHERE id=?',(record['id'],));deleted+=1;after=None
            touched+=1
            audit(c,role,'删除整月考勤',record['id'],record,after)
        result={'ok':True,'kind':kind,'employee_id':employee_id,'month':month,'days':touched,'deleted':deleted,'reason':reason}
    result['fingerprint']=_fingerprint(b)
    c.execute('INSERT INTO meta VALUES(?,?)',('factory-delete:'+key,rc.dump(result)))
    return result

def save(c,kind,b,role,now,audit,actor=None):
    if kind in ('production-attendance','management-attendance'):return __import__('personnel').save_day(c,b,'management' if kind=='management-attendance' else 'production',role,now,audit,actor=actor)
    if kind=='management-month-save':return __import__('personnel').save_month(c,{**b,'attendance_scope':'management'},role,now,audit,actor=actor)
    if kind=='attendance-month-save':return __import__('personnel').save_month(c,b,role,now,audit,actor=actor)
    if kind in ('contractor-staff','contractor-attendance'):return __import__('personnel').save_contractor(c,kind,b,role,now,audit)
    if kind=='production-config':return pc.publish(c,b,role,now,audit)
    if kind=='parameter-request':return request_parameter(c,b,role,actor,now,audit)
    if kind=='parameter-review':return review_parameter(c,b,role,actor,now,audit)
    if kind=='company-info':return __import__('company').save(c,b,role,now,audit)
    if kind.startswith('employee-bank'):return __import__('employee_banks').save(c,kind,b,role,now,audit)
    if kind.startswith('wage-'):return payroll.save(c,kind,b,role,now,audit)
    permission=PERMISSIONS[kind]
    if kind=='employee':
        old_employee=get(c,'employee',b.get('id')) if b.get('id') else None
        scope=b.get('employee_type',(old_employee or {}).get('employee_type','production'));permission=__import__('personnel').type_permission(scope,staff=True)
        if old_employee:access.require_role(role,__import__('personnel').type_permission(old_employee.get('employee_type','production'),staff=True))
    access.require_role(role,permission)
    if kind=='employee' and any(k in b for k in ('monthly_salary','annual_salary','salary_mode')):access.require_role(role,'payroll.write')
    if role=='厂长' and kind in ('run','post-output','undo-output','finance-settings'):raise ValueError('请使用每日生产登记；产量从库管发货与盘库结存推算')
    if role=='厂长' and ((kind=='attendance' and b.get('format') not in ('group-day-v2','person-day-v1')) or (kind=='scrap' and b.get('format')!='note-v2')):raise ValueError('请使用分组考勤或烂豆皮重量与用途登记')
    if kind in ('settings','finance-settings','system-settings'):
        if kind=='system-settings' and role!='管理员':raise ValueError('仅管理员可以修改系统参数')
        old=settings(c)
        if type(b.get('version')) is not int or old['version']!=b['version']:raise ValueError('换算设置已修改，请同步后重试')
        allowed=set(DEFAULTS) if kind=='system-settings' else daily.FINANCE_KEYS if kind=='finance-settings' else set(DEFAULTS)-daily.FINANCE_KEYS
        if kind=='settings' and any(k in b and str(b[k])!=str(old[k]) for k in daily.FINANCE_KEYS):raise ValueError('应收与账龄参数请在财务预警设置中修改')
        val={k:optional(b.get(k,old[k]),k) if k in allowed else old[k] for k in DEFAULTS}
        for key in ('tofu_soak_kg','skin_soak_kg','small_slurry_kg','small_slurry_crates','large_slurry_kg','large_slurry_crates'):
            if not val[key] or Decimal(val[key])<=0:raise ValueError('已确认的豆腐与泡豆换算必须大于0')
        for key in ('average_weight_alert_kg','weight_alert_kg','weight_alert_pct','receivable_limit_yuan','receivable_days','evidence_alert_pct'):
            if val[key]=='':raise ValueError('请填写预警阈值')
        if not 0<=Decimal(val['average_weight_alert_kg'])<=100:raise ValueError('平均净重偏差公斤数须在0到100之间')
        if Decimal(val['receivable_days'])!=Decimal(val['receivable_days']).to_integral():raise ValueError('账期预警天数须为整数')
        c.execute("UPDATE factory_settings SET version=version+1,payload=? WHERE id='default'",(rc.dump(val),));audit(c,role,'修改生产换算与预警','factory-settings',old,val);return settings(c) if kind=='system-settings' else {k:v for k,v in settings(c).items() if k in daily.FINANCE_KEYS or k=='version'} if kind=='finance-settings' else daily.hide_finance(settings(c))
    if kind=='beans':return bean_register(c,b,role,now,audit)
    if kind=='bean-void':return bean_change(c,b,role,now,audit,restore=False)
    if kind=='bean-restore':return bean_change(c,b,role,now,audit,restore=True)
    if kind=='run' and pc.get(c,b.get('business_date'))['version']:raise ValueError('生产系统已使用动态配置，请使用每日生产登记')
    if kind=='issue':
        if b.get('material_id','RM-SOY')=='RM-SOY' and not b.get('production_system_id') and b.get('department') not in ('豆腐线','豆皮线'):raise ValueError('请选择磨浆系统；兼容入口仅支持豆腐线、豆皮线')
        body={**b,'kind':'consume','amount':'0'}
        result=rc.Operations(c,now,audit).material(body,role);return result
    if kind in ('post-output','undo-output'):return post_output(c,b,role,now,audit,undo=kind=='undo-output')
    table=TABLES[kind];key=rc.text(b.get('request_key'),'提交编号',100)
    existing=c.execute('SELECT payload FROM '+table+' WHERE request_key=?',(key,)).fetchone()
    fingerprint=hashlib.sha256(rc.dump({k:v for k,v in b.items() if k!='_data_epoch'}).encode()).hexdigest()
    if existing:
        record=json.loads(existing[0])
        if record.get('request_fingerprint')==fingerprint:return record
        if not b.get('id'):raise ValueError('提交编号已被其他内容使用，请重新打开表单')
    old=get(c,kind,b.get('id')) if b.get('id') else None
    if b.get('id') and not old:raise ValueError('记录不存在')
    if old and old.get('request_fingerprint')==fingerprint:return old
    if type(b.get('version',0)) is not int or b.get('version',0)!=(old or {}).get('version',0):raise ValueError('记录已修改，请同步后重试')
    if old and old.get('posted'):raise ValueError('已入成品库存的生产记录不能直接修改，请登记更正记录并核对库存')
    if kind in ('daily','run','scrap'):
        when=rc.day(b.get('business_date'))
        inventory.open_day(c,when)
        if kind=='daily' and not old:
            try:backfill=max(0,min(90,int(settings(c).get('production_backfill_days',30))))
            except (TypeError,ValueError):backfill=30
            earliest=(payroll.local_today()-timedelta(days=backfill)).isoformat()
            if when<earliest:raise ValueError('生产日期最多补录 %d 天，请登记 %s 之后的生产'%(backfill,earliest))
        if old and old.get('business_date') and old['business_date']!=when:inventory.open_day(c,old['business_date'])
    if kind in ('attendance','schedule'):
        em={e['id']:e for e in rows(c,'employee')}
        scopes={__import__('personnel').entry_type(e,em) for e in [*b.get('entries',[]),*(old or {}).get('entries',[])]}
        for scope in scopes:access.require_role(role,__import__('personnel').type_permission(scope))
        if kind=='schedule' and 'management' in scopes:raise ValueError('生产排班仅安排生产工人')
    record={}
    if kind=='daily':record=daily.production_day(c,b,old,settings(c))
    elif kind=='schedule':record=daily.normalize_attendance(c,b,old,rows(c,'group'),rows(c,'employee'),schedule=True)
    elif kind=='attendance' and b.get('format') in ('group-day-v2','person-day-v1'):record=daily.normalize_attendance(c,b,old,rows(c,'group'),rows(c,'employee'))
    elif kind=='scrap' and b.get('format')=='note-v2':
        when=rc.day(b.get('business_date'));kg=rc.qty(b.get('kg'),'烂豆皮重量',True);pid=b.get('product_id') or '';product=c.execute('SELECT name FROM products WHERE id=?',(pid,)).fetchone() if pid else None
        if pid and not product:raise ValueError('请选择处理成的产品')
        record={'format':'note-v2','business_date':when,'kg':rc.ds(kg),'product_id':pid,'product_name':product['name'] if product else '暂存 / 待处理','note':rc.text(b.get('note',''),'处理备注',500,False)}
    elif kind=='group':
        name=rc.text(b.get('name'),'组名',60)
        if any(r['name']==name and r['id']!=b.get('id') for r in rows(c,'group')):raise ValueError('小组名称已存在')
        record={'name':name,'active':b.get('active',True) is True}
    elif kind=='employee':
        record=__import__('personnel').employee(c,b,old)
    elif kind=='attendance':
        day=rc.day(b.get('business_date'));entries=b.get('entries')
        if not isinstance(entries,list) or not entries or len(entries)>500:raise ValueError('请登记考勤明细，最多500行')
        normalized=[];spans={}
        for row in entries:
            employee=named(c,'employee',row.get('employee_id'));group=named(c,'group',row.get('group_id'));status=row.get('status','present')
            if status not in ('present','leave','absent','rest'):raise ValueError('考勤状态无效')
            a=z=None;hours=Decimal(0);pause=rc.qty(row.get('break_minutes') or '0','休息分钟')
            if status=='present':
                a=stamp(row.get('start'));z=stamp(row.get('end'))
                if z<=a or z-a>timedelta(hours=24):raise ValueError('结束时间须晚于开始时间，单段不超过24小时；跨夜请选择次日日期')
                if abs((a.date()-date.fromisoformat(day)).days)>1:raise ValueError('起止时间须在生产日期前后一天内')
                minutes=Decimal(str((z-a).total_seconds()/60))
                if pause>=minutes:raise ValueError('休息时间不能达到或超过班段时长')
                hours=(minutes-pause)/60
                others=spans.setdefault(employee['id'],[])
                if any(a<end and z>start for start,end in others):raise ValueError(employee['name']+'同一时段不能重复分组，请分段登记')
                others.append((a,z))
            normalized.append({'employee_id':employee['id'],'employee_name':employee['name'],'group_id':group['id'],'group_name':group['name'],'status':status,'start':row.get('start','') if a else '', 'end':row.get('end','') if z else '', 'break_minutes':rc.ds(pause),'hours':rc.ds(hours.quantize(Decimal('.001'))),'note':rc.text(row.get('note',''),'考勤备注',200,False)})
        # A worker may switch groups, but cannot overlap another saved shift.
        for r in rows(c,'attendance'):
            if r['id']==(old or {}).get('id'):continue
            for row in r['entries']:
                if row['status']!='present' or row['employee_id'] not in spans:continue
                a,z=stamp(row['start']),stamp(row['end'])
                if any(a<end and z>start for start,end in spans[row['employee_id']]):raise ValueError(row['employee_name']+'与已登记班次时间重叠')
        state=b.get('state','recorded')
        if state not in ('planned','recorded'):raise ValueError('班次登记状态无效')
        record={'business_date':day,'state':state,'name':rc.text(b.get('name'),'班次名称',80),'entries':normalized,'note':rc.text(b.get('note',''),'班次备注',500,False)}
    elif kind=='run':
        day=rc.day(b.get('business_date'));system=b.get('system')
        if system not in ('tofu','skin'):raise ValueError('请选择豆腐或豆皮磨浆系统')
        cfg=settings(c);outputs=b.get('outputs',[])
        if not isinstance(outputs,list) or not outputs or len(outputs)>100:raise ValueError('请登记产出产品')
        normalized=[];seen=set()
        for r in outputs:
            product=c.execute('SELECT id,name,unit FROM products WHERE id=?',(r.get('product_id'),)).fetchone()
            if not product:raise ValueError('产出产品不存在')
            if product['id'] in seen:raise ValueError('同一生产记录的产品不能重复，请汇总填写')
            seen.add(product['id']);tank=r.get('tank_type','')
            if tank not in ('small','large','skin',''):raise ValueError('浆缸类型无效')
            if system=='skin' and tank not in ('skin',''):raise ValueError('豆皮系统请选择豆皮浆缸')
            q=production_qty(r.get('qty') or '0','产量',product['unit'])
            normalized.append({'product_id':product['id'],'product_name':product['name'],'unit':product['unit'],'qty':rc.ds(q),'net_kg':optional(r.get('net_kg',''),'成品实称净重'),'allocated_dry_kg':optional(r.get('allocated_dry_kg',''),'该产品实际用豆'),'tank_type':tank,'slurry_tanks':optional(r.get('slurry_tanks',''),'实录浆缸数'),'conversion_confirmed':r.get('conversion_confirmed') is True})
        dry=optional(b.get('dry_kg',''),'人工上豆公斤');bags=optional(b.get('bags',''),'上豆袋数');bagkg=optional(b.get('bag_kg',''),'每袋估重')
        allocated=sum((Decimal(o.get('allocated_dry_kg') or '0') for o in normalized),Decimal(0))
        if dry!='' and allocated>Decimal(dry):raise ValueError('各产品实际用豆合计超过本批上豆量，请核对')
        record={'business_date':day,'system':system,'batch_name':rc.text(b.get('batch_name'),'批次名称',80),'dry_kg':dry,'bags':bags,'bag_kg':bagkg,'soak_tanks':optional(b.get('soak_tanks',''),'泡豆满缸折合数'),'outputs':normalized,'settings_snapshot':cfg,'note':rc.text(b.get('note',''),'生产说明',1000,False),'posted':False}
    elif kind=='scrap':
        day=rc.day(b.get('business_date'));action=b.get('action')
        if action not in ('in','process','waste'):raise ValueError('请选择烂豆皮产生、转加工或报废')
        kg=rc.qty(b.get('kg'),'烂豆皮公斤',True);produced=[]
        if action=='process':
            for r in b.get('outputs',[]):
                p=c.execute('SELECT id,name,unit FROM products WHERE id=?',(r.get('product_id'),)).fetchone()
                if not p:raise ValueError('请选择转加工产出产品')
                q=production_qty(r.get('qty'),'转加工数量',p['unit'])
                produced.append({'product_id':p['id'],'product_name':p['name'],'unit':p['unit'],'qty':rc.ds(q),'net_kg':optional(r.get('net_kg',''),'转加工产出净重')})
            if not produced:raise ValueError('请登记转加工产出')
        record={'business_date':day,'action':action,'kg':rc.ds(kg),'outputs':produced,'note':rc.text(b.get('note'),'产生原因 / 处置说明',1000),'posted':False,'other_input_note':rc.text(b.get('other_input_note',''),'其他投入说明',500,False)}
    rid=(old or {}).get('id') or 'FP-'+secrets.token_hex(6).upper()
    if old and old.get('stock_history'):record['stock_history']=old['stock_history']
    record.update(sequence=(old or {}).get('sequence',len(rows(c,kind))+1),id=rid,version=(old or {}).get('version',0)+1,request_fingerprint=fingerprint,updated_at=now(),role=role)
    if old:c.execute('UPDATE '+table+' SET payload=? WHERE id=?',(rc.dump(record),rid))
    else:c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(rid,key,rc.dump(record)))
    if kind=='scrap' and record.get('format')!='note-v2':scrap_ledger(c)
    if kind=='employee':
        if any(k in b for k in ('monthly_salary','annual_salary','salary_mode')):
            category=b.get('salary_category') or ('wages-management' if record['employee_type']=='management' else 'wages-production')
            payroll.save(c,'wage-profile',{'employee_id':rid,'salary_mode':b.get('salary_mode','monthly'),'annual_salary':b.get('annual_salary'),'monthly_salary':b.get('monthly_salary'),'salary_category':category,'version':int(b.get('salary_version',b.get('monthly_salary_version',0))),'request_key':'employee-salary:'+hashlib.sha256(key.encode()).hexdigest()},role,now,audit)
        payroll.ensure_profiles(c)
    audit(c,role,'登记厂长'+{'schedule':'排班','daily':'每日生产','group':'小组','employee':'员工','attendance':'考勤','run':'生产','scrap':'烂豆皮'}[kind],rid,old,record)
    return record

def scrap_ledger(c,until=None):
    balance=Decimal(0);result=[]
    for r in sorted(rows(c,'scrap'),key=lambda x:(x['business_date'],x.get('sequence',0),x['id'])):
        if r.get('format')=='note-v2':continue
        if until and r['business_date']>until:continue
        balance+=Decimal(r['kg'])*(1 if r['action']=='in' else -1)
        if balance<0:raise ValueError('烂豆皮可用量不足，不能先加工或报废后补登产生量')
        result.append({**r,'balance_kg':rc.ds(balance)})
    return {'balance_kg':rc.ds(balance),'entries':result}

def post_output(c,b,role,now,audit,undo=False):
    kind=b.get('kind','run')
    if kind not in ('run','scrap'):raise ValueError('产出来源无效')
    r=get(c,kind,b.get('id'))
    if not r:raise ValueError('生产记录不存在')
    if not undo and r.get('posted'):return r
    if undo and not r.get('posted'):raise ValueError('该生产记录尚未入库')
    if b.get('evidence_checked') is not True:raise ValueError('请确认本批产出尚未入库')
    if type(b.get('version')) is not int or r['version']!=b['version']:raise ValueError('生产记录已修改，请同步后入库')
    if kind=='scrap' and r['action']!='process':raise ValueError('仅转加工产出可以入成品库存')
    day=r['business_date'];inventory.open_day(c,day)
    inventory.expect_revision(c,b)
    row=c.execute('SELECT payload FROM warehouse_plans WHERE business_date=?',(day,)).fetchone()
    plan=json.loads(row[0]) if row else {'business_date':day,'version':0,'stock':[],'allocations':[],'customers':[]}
    if not row:
        prev=inventory.closed(c,(date.fromisoformat(day)-timedelta(days=1)).isoformat())
        if prev:
            plan.update(opening_source_date=prev['business_date'],opening_close_version=prev['version'])
            plan['stock']=[{'product_id':p['product_id'],'existing_qty':p['counted_qty'],'produced_qty':'0','loss_qty':'0','loss_reason':'','counted_qty':'','variance_reason':''} for p in prev.get('products',[])]
    for out in r['outputs']:
        if not undo and __import__('trade').product_config(c,{'id':out['product_id']}).get('supply_kind')=='processing':raise ValueError('转加工产品请在厂内转加工记录登记产出，不能计入普通生产')
        line=next((s for s in plan['stock'] if s['product_id']==out['product_id']),None)
        if line is None:
            line={'product_id':out['product_id'],'existing_qty':'','produced_qty':'0','loss_qty':'0','loss_reason':'','counted_qty':'','variance_reason':''};plan['stock'].append(line)
        quantity=Decimal(line.get('produced_qty') or '0')+Decimal(out['qty'])*(-1 if undo else 1)
        if quantity<0:raise ValueError('当天生产数量已被其他操作调整，请先核对成品库存')
        line['produced_qty']=rc.ds(quantity)
    plan['version']+=1;plan.setdefault('production_sources',[])
    if undo:plan['production_sources']=[x for x in plan['production_sources'] if x!=r['id']]
    else:plan['production_sources'].append(r['id'])
    c.execute('INSERT INTO warehouse_plans VALUES(?,?) ON CONFLICT(business_date) DO UPDATE SET payload=excluded.payload',(day,rc.dump(plan)))
    inventory.validate_book(c,day,check_reservations=True)
    r={**r,'posted':not undo,'version':r['version']+1,'posted_at':now(),'stock_history':r.get('stock_history',[])+[{'action':'undo' if undo else 'post','at':now(),'role':role}]};c.execute('UPDATE '+TABLES[kind]+' SET payload=? WHERE id=?',(rc.dump(r),r['id']))
    inventory.bump(c)
    audit(c,role,'撤销生产产出入库' if undo else '生产产出入成品库存',r['id'],None,{'record':r,'warehouse_version':plan['version']});return r

def snapshot(c,*,light=False,include_production_configs=True):
    # HTTP 投影只保留 resources 下的一份同名数据；默认保持内部快照口径（导出与内部调用方）不变。
    configurations=pc.history(c) or [pc.seed(c)] if include_production_configs else []
    result={'schedules':[] if light else rows(c,'schedule'),'daily':rows(c,'daily'),'groups':rows(c,'group'),'employees':rows(c,'employee'),'attendance':[] if light else rows(c,'attendance'),'runs':rows(c,'run'),'scrap':scrap_ledger(c),'scrap_notes':[r for r in rows(c,'scrap') if r.get('format')=='note-v2'],'settings':settings(c),'production_configs':configurations,'bean_registrations':bean_registrations(c)}
    if light:result['_attendance_deferred']=True
    return result

def attendance_activity(result):
    """Small date facts derived from the same already-scoped working records."""
    import personnel
    days={};employees={e['id']:e for e in result.get('employees',[])}
    def item(day):return days.setdefault(day,{'business_date':day,'scheduled':False,'production_confirmed':False,'schedule_saved':False})
    for record in result.get('attendance',[]):
        day=record.get('business_date')
        if not day:continue
        row=item(day)
        row['scheduled'] |= record.get('state')=='confirmed' and not record.get('source_schedule_id') and record.get('workflow')!='separate-v1'
        row['production_confirmed'] |= any(personnel.entry_type(e,employees)=='production' and e.get('entry_state',record.get('state'))=='confirmed' for e in record.get('entries',[]))
    for record in result.get('schedules',[]):
        day=record.get('business_date')
        if day:
            item(day)['scheduled'] |= record.get('state')=='confirmed'
            item(day)['schedule_saved']=True
    return [days[day] for day in sorted(days)]


def attendance_date_facts(c,grants):
    """Same date facts as attendance_activity(scope(...)), aggregated inside SQLite.

    Bootstrap only needs four booleans per business date, so the entries are expanded,
    typed and compared in one statement and no payload ever reaches Python. The states
    follow scope(): an entry falls back to the record state, and that record state is the
    recomputed "all in-scope entries confirmed" value, not the stored payload state.
    Entries without an employee_id key still raise KeyError('employee_id'), as before.
    """
    import personnel
    modules=set(grants['modules']);attendance_scopes=sorted(k for k in personnel.TYPES if personnel.type_permission(k) in modules)
    include_schedules='production.attendance' in modules
    # v0.95.3 raised KeyError when an entry had no employee_id at all: scope() types every entry
    # of both tables before any visibility or business_date filter, and attendance_activity()
    # does the same for attendance entries. An explicit JSON null is not an error there (it
    # falls back to the entry's own type), so only a missing key may raise. Records the
    # aggregation below drops (invisible type, unusable date) must still fail, hence a guard
    # over both tables instead of an extra column on the scoped statement.
    missing=("SELECT 1 FROM factory_attendance a,json_each(COALESCE(json_extract(a.payload,'$.entries'),'[]')) j "
             "WHERE json_type(j.value,'$.employee_id') IS NULL")
    if include_schedules:missing+=" UNION ALL SELECT 1 FROM factory_schedules s,json_each(COALESCE(json_extract(s.payload,'$.entries'),'[]')) j WHERE json_type(j.value,'$.employee_id') IS NULL"
    if c.execute(missing+" LIMIT 1").fetchone():raise KeyError('employee_id')
    if not attendance_scopes and not include_schedules:return []
    sch="sch AS (SELECT json_extract(payload,'$.business_date') AS d,json_extract(payload,'$.state') AS st FROM factory_schedules WHERE json_extract(payload,'$.business_date') IS NOT NULL AND json_extract(payload,'$.business_date')<>'')"
    merged="merged AS (SELECT d,scheduled,production_confirmed,0 AS schedule_saved FROM df"
    if include_schedules:merged+=" UNION ALL SELECT d,CASE WHEN st='confirmed' THEN 1 ELSE 0 END,0,1 FROM sch"
    merged+=")"
    tail=" SELECT d,MAX(scheduled),MAX(production_confirmed),MAX(schedule_saved) FROM merged GROUP BY d ORDER BY d"
    if not attendance_scopes:
        return [{'business_date':d,'scheduled':bool(s),'production_confirmed':False,'schedule_saved':bool(v)} for d,s,v in c.execute("WITH "+sch+",merged AS (SELECT d,CASE WHEN st='confirmed' THEN 1 ELSE 0 END AS scheduled,0 AS production_confirmed,1 AS schedule_saved FROM sch) SELECT d,MAX(scheduled),MAX(production_confirmed),MAX(schedule_saved) FROM merged GROUP BY d ORDER BY d")]
    att=','.join('?' for _ in attendance_scopes)
    etype="COALESCE(json_extract(e.payload,'$.employee_type'),json_extract(j.value,'$.employee_type'),'production')"
    # scope() recomputes the record state from the stored payload state when an entry has none,
    # while attendance_activity() then falls back to that recomputed state; keep both passes.
    stored="CASE WHEN json_type(j.value,'$.entry_state') IS NULL THEN json_extract(a.payload,'$.state') ELSE json_extract(j.value,'$.entry_state') END"
    # An explicit JSON null is not "confirmed" in Python either, so encode it as '' instead of NULL.
    own="CASE WHEN json_type(j.value,'$.entry_state') IS NULL THEN NULL ELSE COALESCE(json_extract(j.value,'$.entry_state'),'') END"
    sql=("WITH ent AS (SELECT a.id AS rid,json_extract(a.payload,'$.business_date') AS d,"
         "json_extract(a.payload,'$.source_schedule_id') AS src,json_extract(a.payload,'$.workflow') AS wf,"
         +stored+" AS stored,"+own+" AS own,"+etype+" AS etype FROM factory_attendance a "
         "JOIN json_each(COALESCE(json_extract(a.payload,'$.entries'),'[]')) j "
         "LEFT JOIN factory_employees e ON e.id=json_extract(j.value,'$.employee_id') "
         "WHERE json_extract(a.payload,'$.business_date') IS NOT NULL AND json_extract(a.payload,'$.business_date')<>'' "
         "AND "+etype+" IN ("+att+")),"
         "rec AS (SELECT rid,d,MAX(src) AS src,MAX(wf) AS wf,"
         "MAX(CASE WHEN COALESCE(stored,'')<>'confirmed' THEN 1 ELSE 0 END) AS bad FROM ent GROUP BY rid,d),"
         "per AS (SELECT rec.d AS d,rec.src AS src,rec.wf AS wf,rec.bad AS bad,"
         "MAX(CASE WHEN ent.etype='production' AND COALESCE(ent.own,CASE WHEN rec.bad=0 THEN 'confirmed' ELSE 'draft' END)='confirmed' THEN 1 ELSE 0 END) AS prod "
         "FROM rec JOIN ent ON ent.rid=rec.rid AND ent.d=rec.d GROUP BY rec.rid,rec.d),"
         "df AS (SELECT d,MAX(CASE WHEN bad=0 AND COALESCE(src,'') IN ('',0) AND (wf IS NULL OR wf<>'separate-v1') THEN 1 ELSE 0 END) AS scheduled,"
         "MAX(prod) AS production_confirmed FROM per GROUP BY d),"
         +sch+","+merged+tail)
    args=list(attendance_scopes)
    return [{'business_date':d,'scheduled':bool(s),'production_confirmed':bool(p),'schedule_saved':bool(v)} for d,s,p,v in c.execute(sql,args)]


def scope(result,grants,c=None):
    import personnel
    modules=set(grants['modules']);allowed={'production.manage','production.daily','production.inventory','sales.reports'}
    if not modules & (allowed|{'production.staff','production.attendance','management.staff','management.attendance','production.settings'}):return {}
    out=dict(result);deferred=out.pop('_attendance_deferred',False)
    staff_scopes={k for k in personnel.TYPES if {personnel.type_permission(k,True),personnel.type_permission(k)} & modules}
    attendance_scopes={k for k in personnel.TYPES if personnel.type_permission(k) in modules};em={e['id']:e for e in out.get('employees',[])}
    out['employees']=[e for e in out.get('employees',[]) if e.get('employee_type','production') in staff_scopes]
    out['attendance']=[]
    for record in result.get('attendance',[]):
        entries=[e for e in record.get('entries',[]) if personnel.entry_type(e,em) in attendance_scopes]
        if entries:
            mixed=len(entries)!=len(record.get('entries',[]));fallback='' if mixed else record.get('note','')
            projected={**record,'entries':entries,'scope_notes':{k:v for k,v in record.get('scope_notes',{}).items() if k in attendance_scopes},'note':record.get('scope_notes',{}).get(next(iter(attendance_scopes)),fallback) if len(attendance_scopes)==1 else record.get('note',''),'state':'confirmed' if all(e.get('entry_state',record.get('state'))=='confirmed' for e in entries) else 'draft'}
            projected.pop('notice',None);out['attendance'].append(projected)
    if 'production.attendance' not in modules:out['schedules']=[]
    else:
        out['schedules']=[]
        for record in result.get('schedules',[]):
            entries=[e for e in record.get('entries',[]) if personnel.entry_type(e,em)=='production']
            out['schedules'].append({**record,'entries':entries,**({'note':'','notice':'历史排班包含非生产人员，请管理员核对后重新确认生产排班。'} if len(entries)!=len(record.get('entries',[])) else {})})
    if not modules & (allowed|{'production.staff','production.attendance','production.settings'}):
        out['groups']=[];out['daily']=[];out['runs']=[];out['scrap']={'entries':[],'balance_kg':'0'};out['scrap_notes']=[];out['bean_registrations']=[];out['production_configs']=[];out['settings']={}
    if not modules & {'production.manage','production.daily','sales.reports'}:out['runs']=[];out['scrap']={'entries':[],'balance_kg':'0'}
    if deferred:
        if c is None:raise ValueError('延后读取的考勤日期状态需要数据库连接')
        out['attendance_activity']=attendance_date_facts(c,grants)
    else:out['attendance_activity']=attendance_activity(out)
    return daily.hide_finance(out)

def run_analysis(r):
    cfg=r['settings_snapshot'];system=r['system'];methods=[];unconfirmed=[]
    actual=Decimal(r['dry_kg']) if r['dry_kg']!='' else None
    bag=Decimal(r['bags'])*Decimal(r['bag_kg']) if r['bags']!='' and r['bag_kg']!='' else None
    soak=Decimal(r['soak_tanks'])*Decimal(cfg[system+'_soak_kg']) if r['soak_tanks']!='' else None
    for name,value,formula in [('人工记录',actual,r['dry_kg']+' kg' if actual is not None else ''),('袋数估算',bag,f"{r['bags']}袋 × {r['bag_kg']}kg/袋"),('泡豆估算',soak,f"{r['soak_tanks']}缸 × {cfg[system+'_soak_kg']}kg干豆/缸")]:
        methods.append({'method':name,'kg':rc.ds(value) if value is not None else None,'formula':formula if value is not None else '待补数据'})
    slurry=Decimal(0);reverse=Decimal(0);slurry_complete=True;reverse_complete=True;outputs=[]
    for out in r['outputs']:
        tank=out['tank_type'];factor=cfg.get(tank+'_slurry_kg','');crates=cfg.get(tank+'_slurry_crates','')
        slurrykg=Decimal(out['slurry_tanks'])*Decimal(factor) if factor and out['slurry_tanks']!='' else None
        # Reverse yields must be explicitly confirmed for this product/tank; yellow/white curd use is never guessed.
        compatible=out.get('conversion_confirmed') and out['unit']=='筐' and factor and crates and Decimal(crates)>0
        reversekg=Decimal(out['qty'])/Decimal(crates)*Decimal(factor) if compatible else None
        if slurrykg is None:slurry_complete=False
        else:slurry+=slurrykg
        if reversekg is None:reverse_complete=False
        else:reverse+=reversekg
        net=Decimal(out['net_kg']) if out['net_kg']!='' else None
        actual_bean=Decimal(out['allocated_dry_kg']) if out.get('allocated_dry_kg') not in ('',None) else actual if len(r['outputs'])==1 else None
        yieldbean=actual_bean if actual_bean is not None else slurrykg
        outputs.append({**out,'slurry_bean_kg':rc.ds(slurrykg) if slurrykg is not None else None,'reverse_bean_kg':rc.ds(reversekg) if reversekg is not None else None,'slurry_formula':f"{out['slurry_tanks']}缸 × {factor}kg/缸" if slurrykg is not None else '待补浆缸换算','reverse_formula':f"{out['qty']}筐 ÷ {crates}筐/缸 × {factor}kg/缸" if reversekg is not None else '待确认该产品换算','actual_bean_kg':rc.ds(actual_bean) if actual_bean is not None else None,'yield_bean_kg':rc.ds(yieldbean) if yieldbean is not None else None,'yield_basis':'实录干豆' if actual_bean is not None else '浆缸估算干豆','yield_kg_per_kg':rc.ds(net/yieldbean) if net is not None and yieldbean else None,'yield_formula':f"{net}kg成品 ÷ {yieldbean}kg（{'实录干豆' if actual_bean is not None else '浆缸估算干豆'}）" if net is not None and yieldbean else '需产出净重和该产品用浆量'})
    methods.extend([{'method':'浆缸估算','kg':rc.ds(slurry) if slurry_complete else None,'formula':' + '.join(o['slurry_formula'] for o in outputs)},{'method':'产量倒推','kg':rc.ds(reverse) if reverse_complete else None,'formula':' + '.join(o['reverse_formula'] for o in outputs)}])
    available=[m for m in methods if m['kg'] is not None];baseline=next((m for m in available if m['method']=='人工记录'),available[0] if available else None)
    for m in methods:
        v=Decimal(m['kg']) if m['kg'] is not None else None;base=Decimal(baseline['kg']) if baseline else None
        delta=v-base if v is not None and base is not None else None;pct=delta/base*100 if delta is not None and base else None
        m.update(compare_to=baseline['method'] if baseline else '',difference_kg=rc.ds(delta) if delta is not None else None,difference_pct=rc.ds(pct.quantize(Decimal('.01'))) if pct is not None else None,alert=pct is not None and abs(pct)>Decimal(cfg['evidence_alert_pct']))
    known_net=all(o['net_kg']!='' for o in outputs);net=sum((Decimal(o['net_kg'] or '0') for o in outputs),Decimal(0))
    return {**r,'methods':methods,'analysis_outputs':outputs,'yield_kg_per_kg':rc.ds(net/actual) if known_net and actual else None,'yield_formula':f'{net}kg实称成品 ÷ {actual}kg人工干豆记录' if known_net and actual else '需完整成品净重及人工上豆量','note_analysis':'差异只能提示核对方向，不能直接证明漏浆、工艺损耗或人员问题；先核对记录、计量和批次对应。'}

def daily_report(c,day):
    import cost_allocation
    return cost_allocation.public_yields(c,daily.report(c,day,settings(c),line_weight),day)
def processing_month(c,month_start):
    """Aggregate estimated processing costs, sharing non-exclusive indirect costs by all product net weight."""
    from material_allocation import split
    start=rc.day(month_start);month=start[:7]
    processing_dates=sorted({b['business_date'] for b in rc.rows(c,'processing_batches') if not b.get('voided') and str(b.get('business_date',''))[:7]==month})
    all_dates=sorted({r['business_date'] for table in ('factory_daily','warehouse_plans','orders') for r in rc.rows(c,table) if str(r.get('business_date',''))[:7]==month})
    dates=sorted(set(processing_dates)|set(all_dates));reports={day:daily_report(c,day) for day in dates}
    outputs={};direct=0;source_kg=soy_kg=Decimal(0);pending=False;batches=[];all_product_net=Decimal(0);processing_net=Decimal(0)
    for day in all_dates:all_product_net+=sum((Decimal(p['net_kg']) for p in reports[day].get('products',[]) if p.get('net_kg') not in (None,'')),Decimal(0))
    for day in processing_dates:
        report=reports[day]
        for batch in report.get('processing',[]):
            batches.append(batch);source_kg+=Decimal(batch.get('input_kg') or '0')
            if batch.get('soy_input_kg') not in (None,''):soy_kg+=Decimal(batch['soy_input_kg'])
            else:pending=True
            total_net=Decimal(batch.get('output_net_kg') or '0');processing_net+=total_net
            if batch.get('direct_cost_cents') is None:pending=True
            else:direct+=int(batch['direct_cost_cents'])
            direct_by_output=split(int(batch['direct_cost_cents']),{out['product_id']:Decimal(out.get('net_kg') or '0') for out in batch.get('outputs',[])}) if batch.get('direct_cost_cents') is not None else {}
            for out in batch.get('outputs',[]):
                net=Decimal(out.get('net_kg') or '0');item=outputs.setdefault(out['product_id'],{'product_id':out['product_id'],'product_name':out['product_name'],'unit':out['unit'],'qty':Decimal(0),'net_kg':Decimal(0),'soy_kg':Decimal(0),'direct_cents':0,'pending':False})
                item['qty']+=Decimal(out.get('qty') or '0');item['net_kg']+=net
                if batch.get('soy_input_kg') not in (None,'') and total_net>0:item['soy_kg']+=Decimal(batch['soy_input_kg'])*net/total_net
                if batch.get('direct_cost_cents') is None:item['pending']=True
                elif total_net>0:item['direct_cents']+=direct_by_output.get(out['product_id'],0)
    indirect_pool=sum(int(e.get('amount_cents') or 0) for e in rc.rows(c,'indirect_expenses') if not e.get('voided') and (e.get('period') or e.get('business_date','')[:7])==month and not e.get('product_id'))
    indirect_total=int((Decimal(indirect_pool)*processing_net/all_product_net).quantize(Decimal('1'))) if all_product_net>0 and indirect_pool else 0
    indirect_by_output=split(indirect_total,{pid:item['net_kg'] for pid,item in outputs.items()})
    rows=[];total=direct+indirect_total
    for item in outputs.values():
        net=item['net_kg'];indirect_share=indirect_by_output.get(item['product_id'],0);cost=item['direct_cents']+indirect_share
        rows.append({**{k:rc.ds(v) if isinstance(v,Decimal) else v for k,v in item.items()},'indirect_cents':indirect_share,'cost_cents':cost,'unit_cost_yuan_per_kg':rc.ds((Decimal(cost)/net/100).quantize(Decimal('.01'))) if net>0 else None,'yield_kg':rc.ds((net/item['soy_kg']).quantize(Decimal('.001'))) if item['soy_kg']>0 else None})
    return {'month':month,'batch_count':len(batches),'source_input_kg':rc.ds(source_kg),'soy_input_kg':rc.ds(soy_kg),'direct_cost_cents':direct,'indirect_cost_cents':indirect_total,'total_cost_cents':total,'outputs':sorted(rows,key=lambda x:x['product_id']),'status':'部分待结转 / 待核算' if pending else '估算'}

def line_weight(line,source):
    actual=Decimal(line.get('actual_qty') or '0');weights=line.get(source,[])
    count=sum((Decimal(w.get('count') or '0') for w in weights),Decimal(0))
    net=sum((Decimal(w.get('gross') or '0')-Decimal(w.get('tare') or '0')*Decimal(w.get('count') or '0') for w in weights),Decimal(0))
    if any('packing_lines' in row for row in line.get('crate_lines',[])) and (source=='customer' or source=='driver' and line.get('driver_weight_basis')=='gross'):
        import crate_packaging
        if sum((Decimal(str(row['qty'])) for row in line['crate_lines']),Decimal(0))!=actual:return None,actual
        net=sum((Decimal(w.get('gross') or '0') for w in weights),Decimal(0))-sum((crate_packaging.total_tare(row) for row in line['crate_lines']),Decimal(0))
    return (net,actual) if actual>0 and count==actual and net>0 else (None,actual)

def product_average(c,product):
    row=c.execute("SELECT value FROM meta WHERE key='product_average_weights'").fetchone()
    values=json.loads(row[0]) if row else {}
    if product['id'] in values:return values[product['id']]
    if product['unit']!='筐':return None
    name=product['name']
    for names,value in [(('大豆腐',),'18'),(('小豆腐','中豆腐'),'8'),(('熏干',),'10'),(('白干','白豆干'),'6'),(('魔芋','凉粉'),'10')]:
        if any(n in name for n in names):return value
    return None

def weight_report(c,day=None):
    products={p['id']:dict(p) for p in c.execute('SELECT * FROM products')};cfg=settings(c);orders=rc.rows(c,'orders');plans={r['business_date']:r for r in rc.rows(c,'dispatch_plans')};customers={r['id']:dict(r) for r in c.execute('SELECT * FROM customers')};result=[]
    for o in orders:
        if day and o['business_date']!=day:continue
        plan=plans.get(o['business_date'],{});cust=customers.get(o['customer_id'],{});mid=plan.get('order_markets',{}).get(o['id']) or cust.get('market_id','');trip=next((a.get('trip_id','') for a in plan.get('assignments',[]) if a['market_id']==mid),'unassigned')
        if o.get('delivery_method',cust.get('delivery_method'))=='pickup':trip='pickup'
        for line in o['lines']:
            if line.get('unit')!='筐':continue
            driver,q=line_weight(line,'driver');customer,_=line_weight(line,'customer')
            if not q:continue
            result.append({'order_id':o['id'],'business_date':o['business_date'],'customer_id':o['customer_id'],'customer_name':o['customer_name'],'product_id':line['product_id'],'product_name':line['product_name'],'trip_id':trip,'pickup':trip=='pickup','qty':rc.ds(q),'driver_net_kg':rc.ds(driver) if driver is not None else None,'customer_net_kg':rc.ds(customer) if customer is not None else None})
    def mean(records,field):
        eligible=[r for r in records if r[field] is not None];q=sum((Decimal(r['qty']) for r in eligible),Decimal(0));kg=sum((Decimal(r[field]) for r in eligible),Decimal(0))
        return kg/q if q else None
    daily_totals={};trip_totals={}
    for r in result:
        r['net_kg']=r['customer_net_kg'] if r['pickup'] else r['driver_net_kg']
        if r['net_kg'] is None:continue
        for mapping,key in [(daily_totals,(r['business_date'],r['product_id'])),(trip_totals,(r['business_date'],r['product_id'],r['trip_id']))]:
            a=mapping.setdefault(key,[Decimal(0),Decimal(0)]);a[0]+=Decimal(r['net_kg']);a[1]+=Decimal(r['qty'])
    def total_mean(mapping,key):
        a=mapping.get(key);return a[0]/a[1] if a and a[1] else None
    groups={}
    for r in result:groups.setdefault((r['business_date'],r['trip_id'],r['customer_id'],r['product_id']),[]).append(r)
    output=[]
    for key,group in groups.items():
        day,trip,cid,pid=key;base={k:v for k,v in group[0].items() if k not in ('order_id','qty','driver_net_kg','customer_net_kg')};driver=mean(group,'driver_net_kg');customer=mean(group,'customer_net_kg');tripmean=total_mean(trip_totals,(day,pid,trip));dailymean=total_mean(daily_totals,(day,pid))
        comparisons=[]
        for label,a,b in [('司机对客户',driver,customer),('客户对本趟司机',customer,tripmean),('客户对全日司机',customer,dailymean),('司机对本趟司机',driver,tripmean),('司机对全日司机',driver,dailymean)]:
            diff=a-b if a is not None and b is not None else None;pct=diff/b*100 if diff is not None and b else None
            comparisons.append({'label':label,'difference_kg':rc.ds(diff.quantize(Decimal('.001'))) if diff is not None else None,'difference_pct':rc.ds(pct.quantize(Decimal('.01'))) if pct is not None else None,'alert':diff is not None and (abs(diff)>Decimal(cfg['weight_alert_kg']) or pct is not None and abs(pct)>Decimal(cfg['weight_alert_pct']))})
        qty=sum((Decimal(r['qty']) for r in group),Decimal(0))
        complete=all(r.get('net_kg') is not None for r in group)
        net=sum((Decimal(r['net_kg']) for r in group),Decimal(0)) if complete else None
        average=net/qty if net is not None and qty else None
        reference=product_average(c,products[pid]) if pid in products else None
        notes=[]
        if not complete:notes.append(('自提' if trip=='pickup' else '司机')+'称重未登记完整，缺失重量不计为0')
        checks=[('本趟平均',tripmean if trip not in ('unassigned','pickup') else None),('当日平均',dailymean),('产品默认平均',Decimal(reference) if reference else None)]
        short_labels={'本趟平均':'本趟','当日平均':'当日平均','产品默认平均':'标准'}
        for label,target in checks:
            if average is None or target is None or target<=0:continue
            diff=average-target;pct=diff/target*100
            if abs(diff)>Decimal(cfg['weight_alert_kg']) or abs(pct)>Decimal(cfg['weight_alert_pct']):
                notes.append(f"每筐{'多于' if diff>0 else '少于'}{short_labels[label]} {rc.ds(abs(diff).quantize(Decimal('.001')))}kg")
        if driver is not None and customer is not None:
            diff=customer-driver
            if abs(diff)>Decimal(cfg['weight_alert_kg']) or driver>0 and abs(diff/driver*100)>Decimal(cfg['weight_alert_pct']):notes.append('客户复称与司机称重不一致，请核对原始凭据')
        if trip=='unassigned':notes.append('未安排趟次，本趟平均暂不计算')
        output.append({**base,'qty':rc.ds(qty),'net_kg':rc.ds(net) if net is not None else None,'average':rc.ds(average) if average is not None else None,'default_average_kg':reference,'notes':notes,'order_ids':[r['order_id'] for r in group],'driver_average':rc.ds(driver) if driver is not None else None,'customer_average':rc.ds(customer) if customer is not None else None,'trip_average':rc.ds(tripmean) if tripmean is not None and trip not in ('unassigned','pickup') else None,'day_average':rc.ds(dailymean) if dailymean is not None else None,'comparisons':comparisons,'alert':not complete or any(('多于' in n or '少于' in n or '不一致' in n) for n in notes),'incomplete_driver':any(r['driver_net_kg'] is None for r in group),'incomplete_customer':any(r['customer_net_kg'] is None for r in group)})
    return output

def outstanding(o,paid=None):
    paid=int(o.get('paid_cents',0)) if paid is None else int(paid)
    return max(0,int(o.get('total_cents',0))-paid-sum(int(o.get(k,0)) for k in ('return_credit_cents','discount_cents','rounding_cents')))
def ar_alerts(c,asof):
    cfg=settings(c);end=date.fromisoformat(rc.day(asof));groups={}
    paid_orders=rc.receipts_paid_asof(c,asof);paid_beans=rc.byproduct_paid_asof(c,asof)
    for o in rc.rows(c,'orders'):
        balance=outstanding(o,paid_orders.get(o['id'],0))
        if o.get('state')!='reviewed' or o['business_date']>asof or not balance:continue
        g=groups.setdefault(o['customer_id'],{'customer_id':o['customer_id'],'customer_name':o['customer_name'],'historical_cents':0,'outstanding_cents':0,'oldest_date':o['business_date'],'order_ids':[]})
        if o['business_date']<asof:g['historical_cents']+=balance
        g['outstanding_cents']+=balance;g['oldest_date']=min(g['oldest_date'],o['business_date']);g['order_ids'].append(o['id'])
    opening_paid=rc.opening_receipts_paid(c,asof)
    for row in c.execute("SELECT id,name,opening_cents,opening_date FROM customers WHERE opening_cents>0 AND opening_date<>'' AND opening_date<=? ORDER BY id",(asof,)):
        remaining=max(0,int(row['opening_cents'] or 0)-opening_paid.get(row['id'],0))
        if not remaining:continue
        g=groups.setdefault(row['id'],{'customer_id':row['id'],'customer_name':row['name'],'historical_cents':0,'outstanding_cents':0,'oldest_date':row['opening_date'],'order_ids':[]})
        if row['opening_date']<asof:g['historical_cents']+=remaining
        g['outstanding_cents']+=remaining
        g['oldest_date']=min(g['oldest_date'],row['opening_date'])
        g['opening_cents']=g.get('opening_cents',0)+remaining
    import byproduct_accounts as ba
    for r in ba.receivables(c):
        balance=max(0,int(r['amount_cents'])-paid_beans.get(r['id'],0))
        if r['business_date']>asof or not r.get('customer_id') or not balance:continue
        g=groups.setdefault(r['customer_id'],{'customer_id':r['customer_id'],'customer_name':r['customer_name'],'historical_cents':0,'outstanding_cents':0,'oldest_date':r['business_date'],'order_ids':[]})
        if r['business_date']<asof:g['historical_cents']+=balance
        g['outstanding_cents']+=balance;g['oldest_date']=min(g['oldest_date'],r['business_date']);g['order_ids'].append(r['id'])
    regions={row['id']:row['region'] for row in c.execute('SELECT id,region FROM customers')}
    for g in groups.values():
        g['days']=(end-date.fromisoformat(g['oldest_date'])).days;g['amount_alert']=g['historical_cents']>Decimal(cfg['receivable_limit_yuan'])*100;g['days_alert']=g['days']>Decimal(cfg['receivable_days']);g['alert']=g['amount_alert'] or g['days_alert'];g['region']=regions.get(g['customer_id'],'')
    return list(groups.values())

def sales_line_kg(line,state):
    actual=Decimal(line.get('actual_qty') or '0')
    if actual<=0:return Decimal(0),False
    if line.get('unit') in ('公斤','kg','千克'):return actual,False
    if state in ('ready','reviewed') and line.get('bill_qty') not in (None,'') and (line.get('billing_unit')=='公斤' or line.get('unit')=='筐'):
        return Decimal(line['bill_qty']),False
    if line.get('unit')=='筐':
        for source in ('customer','driver'):
            net,_=line_weight(line,source)
            if net is not None:return net,False
    if line.get('package_customer_net_kg') not in (None,''):return Decimal(line['package_customer_net_kg']),False
    if line.get('package_net_kg') not in (None,''):return Decimal(line['package_net_kg']),False
    if line.get('factory_net_kg') not in (None,''):return Decimal(line['factory_net_kg']),False
    standard=Decimal((line.get('standard_kg') if line.get('unit')!='筐' else line.get('standard_unit_kg')) or '0')
    if standard>0:return actual*standard,True
    return None,False

def sales_report(c,start,end,region='',*,view='customers',customer_id='',product_id='',market='',query='',state='',sort='sales',page=1,page_size=50,paginate=False,all_dates=False):
    """Sales tabs from one date range, with full-filter totals and stable pages.

    Legacy callers keep the full arrays. The page endpoint asks for paginate=True
    and receives only the current page plus customer/market filter options.
    """
    views=('customers','alerts','products','markets','regions')
    if view not in views:raise ValueError('销售报表页签无效')
    if all_dates:start,end=sales_query.bounds(c)
    else:
        rc.day(start);rc.day(end)
        if start>end:raise ValueError('开始日期不能晚于结束日期')
        if paginate:start,end=sales_query.resolve(c,start,end,False)
    if len(query)>100 or len(region)>100 or len(customer_id)>100 or len(product_id)>100 or len(market)>100:raise ValueError('筛选条件过长')
    if paginate:page=sales_query.validate_page(page,page_size)
    allowed_state={'customers':('','unpaid','pending'),'alerts':('','alert','amount','days')}.get(view,('',))
    if state not in allowed_state:raise ValueError('销售报表状态筛选无效')
    if sort not in (('sales','name','balance') if view in ('customers','alerts') else ('sales','name')):raise ValueError('销售排序无效')
    orders=sales_query.orders(c,start,end,region=region,customer_id=customer_id)
    customers={r['id']:dict(r) for r in c.execute('SELECT * FROM customers')}
    clients={};products={};markets={}
    region_options=sorted({r.get('region') or '未设置地区' for r in customers.values()})
    for o in orders:
        current_region=customers.get(o['customer_id'],{}).get('region') or '未设置地区'
        g=clients.setdefault(o['customer_id'],{'customer_id':o['customer_id'],'customer_name':o['customer_name'],'region':current_region,'market':customers.get(o['customer_id'],{}).get('route',o.get('route','未设置')),'sales_cents':0,'current_outstanding_cents':0,'pending_orders':0})
        reviewed=o.get('state')=='reviewed'
        if reviewed:g['sales_cents']+=o.get('total_cents',0);g['current_outstanding_cents']+=outstanding(o)
        else:g['pending_orders']+=1
        current_market=customers.get(o['customer_id'],{}).get('route',o.get('route','未设置'))
        for line in o['lines']:
            kg,estimated=sales_line_kg(line,o.get('state'))
            for mapping,key in [(products,line['product_id']),(markets,(current_region,current_market,line['product_id']))]:
                row=mapping.setdefault(key,{'region':current_region if mapping is markets else '', 'market':current_market if mapping is markets else '', 'product_id':line['product_id'],'product_name':line['product_name'],'unit':line['unit'],'qty':Decimal(0),'sales_cents':0,'known_kg':Decimal(0),'estimated_kg':Decimal(0),'missing_weight_lines':0})
                row['qty']+=Decimal(line.get('actual_qty') or '0')
                if kg is None:row['missing_weight_lines']+=1
                else:
                    row['known_kg']+=kg
                    if estimated:row['estimated_kg']+=kg
                if reviewed:row['sales_cents']+=int(line.get('amount_cents',0))
    def serial(mapping):return [{**g,'qty':rc.ds(g['qty']),'known_kg':rc.ds(g['known_kg']),'estimated_kg':rc.ds(g['estimated_kg']),'net_kg':None if g['missing_weight_lines'] else rc.ds(g['known_kg'])} for g in mapping.values()]
    customer_rows=sorted(clients.values(),key=lambda r:(-r['sales_cents'],r['customer_id']))
    product_rows=sorted(serial(products),key=lambda r:(-r['sales_cents'],r['product_id'],r['unit']))
    market_rows=sorted(serial(markets),key=lambda r:(-r['sales_cents'],r['region'],r['market'],r['product_id'],r['unit']))
    alerts=[{**a,'region':customers.get(a['customer_id'],{}).get('region') or '未设置地区'} for a in ar_alerts(c,end)]
    if region:alerts=[a for a in alerts if a['region']==region]
    alert_rows=sorted(alerts,key=lambda r:(-r['outstanding_cents'],r['customer_id']))
    regions={}
    for client in customer_rows:
        row=regions.setdefault(client['region'],{'region':client['region'],'customer_count':0,'sales_cents':0,'current_outstanding_cents':0,'pending_orders':0})
        row['customer_count']+=1
        for field in ('sales_cents','current_outstanding_cents','pending_orders'):row[field]+=client[field]
    region_rows=sorted(regions.values(),key=lambda r:(-r['sales_cents'],r['region']))
    # Filter option lists are complete for the selected region, independent of paging.
    customer_options=[{'customer_id':r['customer_id'],'customer_name':r['customer_name']} for r in (alert_rows if view=='alerts' else customer_rows)]
    market_options=sorted({r['market'] for r in customer_rows if r.get('market')})
    pools={'customers':customer_rows,'alerts':alert_rows,'products':product_rows,'markets':market_rows,'regions':region_rows}
    pool=pools[view]
    needle=query.casefold()
    def searchable(row):
        values=[row.get('customer_name'),row.get('product_name'),row.get('market'),row.get('region'),row.get('customer_id'),row.get('product_id')]
        return not needle or any(needle in str(v).casefold() for v in values if v is not None)
    def keep(row):
        if not searchable(row):return False
        if view in ('customers','alerts') and customer_id and row.get('customer_id')!=customer_id:return False
        if view in ('products','markets') and product_id and row.get('product_id')!=product_id:return False
        if view in ('customers','markets') and market and row.get('market')!=market:return False
        if view=='customers':
            if state=='unpaid' and not row['current_outstanding_cents']:return False
            if state=='pending' and not row['pending_orders']:return False
        if view=='alerts':
            if state=='alert' and not row.get('alert'):return False
            if state=='amount' and not row.get('amount_alert'):return False
            if state=='days' and not row.get('days_alert'):return False
        return True
    pool=[row for row in pool if keep(row)]
    def name(row):return str(row.get('customer_name') or row.get('product_name') or row.get('market') or row.get('region') or '')
    def unique(row):return tuple(str(row.get(k,'')) for k in ('customer_id','product_id','unit','region','market'))
    if sort=='name':pool.sort(key=lambda r:(name(r).casefold(),unique(r)))
    elif sort=='balance':pool.sort(key=lambda r:(-(r.get('current_outstanding_cents') or r.get('outstanding_cents') or 0),unique(r)))
    else:pool.sort(key=lambda r:(-(r.get('sales_cents') or 0),unique(r)))
    page_rows,page_no,pages=sales_query.page(pool,page,page_size)
    if view=='customers':
        summary={'customer_count':len(pool),'sales_cents':sum(r['sales_cents'] for r in pool),'current_outstanding_cents':sum(r['current_outstanding_cents'] for r in pool),'pending_orders':sum(r['pending_orders'] for r in pool)}
    elif view=='alerts':
        summary={'customer_count':len(pool),'outstanding_cents':sum(r['outstanding_cents'] for r in pool),'historical_cents':sum(r['historical_cents'] for r in pool)}
    elif view in ('products','markets'):
        summary={'row_count':len(pool),'sales_cents':sum(r['sales_cents'] for r in pool),'known_kg':rc.ds(sum((Decimal(r['known_kg']) for r in pool),Decimal(0))),'estimated_kg':rc.ds(sum((Decimal(r['estimated_kg']) for r in pool),Decimal(0))),'missing_weight_lines':sum(r['missing_weight_lines'] for r in pool),'qty':{}}
        for r in pool:
            key=r['unit'];summary['qty'][key]=rc.ds(Decimal(summary['qty'].get(key,'0'))+Decimal(r['qty']))
    else:
        summary={'region_count':len(pool),'customer_count':sum(r['customer_count'] for r in pool),'sales_cents':sum(r['sales_cents'] for r in pool),'current_outstanding_cents':sum(r['current_outstanding_cents'] for r in pool),'pending_orders':sum(r['pending_orders'] for r in pool)}
    result={**{k:v for k,v in {'region_options':region_options,'selected_region':region,'start':start,'end':end,'yields':[],'settings':daily.hide_finance(settings(c)),'basis':'按送货业务日期统计已复核销售额；未复核单独列笔数。未收为所选订单当前余额，不是历史时点余额。出品率统一在生产报表查看。'}.items()},
            'view':view,'page':page_no,'pages':pages,'page_size':page_size,'total':len(pool),'rows':page_rows,'summary':summary,
            'customer_options':customer_options,'market_options':market_options,'filters':{'region':region,'customer_id':customer_id,'product_id':product_id,'market':market,'query':query,'state':state,'sort':sort,'all_dates':all_dates}}
    if not paginate:
        result.update(customers=customer_rows,products=product_rows,markets=market_rows,regions=region_rows,receivable_alerts=alert_rows,rows=[],page=1,pages=1,total=0)
    return result
