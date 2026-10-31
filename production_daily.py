"""One factory day: group attendance, common soybean issues and stock-derived output."""
from datetime import date,timedelta,datetime
from decimal import Decimal
import json,re
import resources_costs as rc
import inventory
import finished_goods
import production_config as pc

FINANCE_KEYS={'receivable_limit_yuan','receivable_days'}

def hide_finance(value):
    if isinstance(value,dict):return {k:hide_finance(v) for k,v in value.items() if k not in FINANCE_KEYS}
    if isinstance(value,list):return [hide_finance(v) for v in value]
    return value

def main_material(c,product):
    if finished_goods.is_purchased(c,product['id']):return '外购成品'
    if __import__('trade').product_config(c,product).get('supply_kind')=='processing':return '转加工'
    row=c.execute("SELECT value FROM meta WHERE key='product_main_materials'").fetchone()
    saved=json.loads(row[0]) if row else {}
    return saved.get(product['id']) or ('豆皮' if '素鸡' in product['name'] else '白干' if '熏干' in product['name'] else '魔芋' if '魔芋' in product['name'] else '淀粉' if '凉粉' in product['name'] else '黄豆')

def grinding_system(c,product):return pc.default_system(c,product)

def uses_slurry(material):return material in ('黄豆','大豆')

def production_day(c,b,old,settings):
    day=rc.day(b.get('business_date'))
    if old and day!=old['business_date']:raise ValueError('已登记的生产日期不能移动，请在原日期更正，新日期另行登记')
    for when in {day,(old or {}).get('business_date',day)}:
        rc.open_period(c,when)
        if any(json.loads(r[0])['state']=='closed' and r[1]>=when[:7] for r in c.execute('SELECT payload,month FROM resource_periods')):raise ValueError('后续成本月份已结账，请先重开相关月份再更正供浆登记')
    if any(json.loads(r[0])['business_date']==day and json.loads(r[0])['id']!=(old or {}).get('id') for r in c.execute('SELECT payload FROM factory_daily')):raise ValueError('当天已有生产登记，请打开当天记录修改')
    config=pc.get(c,day,old,settings);directory={s['id']:s for s in pc.active_systems(config)}
    if b.get('config_version',config['version'])!=config['version']:raise ValueError('生产配置已变化，请重新打开登记表')
    systems=b.get('systems',{})
    if not isinstance(systems,dict) or set(systems)!=set(directory):raise ValueError('请同时登记当日启用的所有磨浆系统')
    sys={}
    for key,entry in systems.items():
        if not isinstance(entry,dict):raise ValueError('磨浆系统登记格式无效')
        state=entry.get('state','running')
        if state not in ('running','stopped','pending'):raise ValueError('系统开机状态无效')
        value=number(entry.get('soak_tanks'),'泡豆桶数')
        if state=='stopped' and (Decimal(value or '0') or Decimal(issue_kg(c,day).get(key,'0'))):raise ValueError('未开机系统已有泡豆或领用，请核对后登记')
        sys[key]={'soak_tanks':'0' if state=='stopped' else value,'state':state}
    products=b.get('products')
    if not isinstance(products,list) or len(products)>10000:raise ValueError('产品用浆登记格式无效')
    values=[];seen=set();processes={p['id']:p for p in config['processes']}
    for row in products:
        if not isinstance(row,dict):raise ValueError('产品用浆登记格式无效，请重新打开表单')
        p=c.execute('SELECT id,name,unit FROM products WHERE id=?',(row.get('product_id'),)).fetchone()
        if not p:raise ValueError('产品不存在，请重新读取产品档案')
        material=main_material(c,p)
        if not uses_slurry(material):continue
        relation=config['products'].get(p['id'],{})
        system=row.get('system',pc.default_system(c,p,config))
        if system not in directory or system not in relation.get('system_ids',[]):raise ValueError('供浆来源无效，请先维护产品允许使用的磨浆系统')
        if (p['id'],system) in seen:raise ValueError('同一产品的同一供浆来源重复，请合并缸数')
        seen.add((p['id'],system));raw=pc.tank_counts(row)
        if not isinstance(raw,dict) or set(raw)-set(processes):raise ValueError('浆缸工艺无效，请重新读取生产配置')
        tanks={}
        for key,n in raw.items():
            n=number(n,'浆缸数')
            if Decimal(n or '0') and (key not in relation.get('process_ids',[]) or not processes[key]['active']):raise ValueError('该产品不允许使用所选浆缸工艺')
            tanks[key]=n
        if sys[system]['state']=='stopped' and any(Decimal(n or '0') for n in tanks.values()):raise ValueError('未开机系统不能登记用浆量')
        values.append({'main_material':material,'product_id':p['id'],'product_name':p['name'],'unit':p['unit'],'system':system,'system_name':directory[system]['name'],'tanks':tanks,**{k+'_tanks':tanks.get(k,'0') for k in pc.LEGACY_FIELDS},'conversion_confirmed':True})
    return {'format':'daily-v3','config_snapshot':config,'skin_product_id':(old or {}).get('skin_product_id') or next((s['residual_product_id'] for s in config['systems'] if s['id']=='skin'),None),'grinding_defaults':(old or {}).get('grinding_defaults',{p['id']:pc.default_system(c,p,config) for p in c.execute('SELECT id,name FROM products')}),'business_date':day,'systems':sys,'products':values,'settings_snapshot':hide_finance((old or {}).get('settings_snapshot',settings)),'note':rc.text(b.get('note',''),'当天生产说明',1000,False)}


def selected_tank_conversion(reg,cfg,quantity,unit,config=None):
    if config is not None:
        factors={p['id']:p for p in config['processes']};counts=pc.tank_counts(reg);tanks=[(k,Decimal(n)) for k,n in counts.items() if n not in ('',None) and Decimal(n)>0]
        if quantity is None or not tanks:return None,'缺少产量或所用浆缸记录'
        if any(not factors.get(k,{}).get('dry_kg') or not factors[k].get('output_qty') for k,n in tanks):return None,'所用浆缸产量或用豆参数待补'
        if any(factors[k].get('output_unit','筐' if k in ('large','small') else '')!=unit for k,n in tanks):return None,'每缸产出单位未确认或与产品单位不一致，请核实工艺单位后再倒推'
        beans=sum(n*Decimal(factors[k]['dry_kg']) for k,n in tanks);outputs=sum(n*Decimal(factors[k]['output_qty']) for k,n in tanks)
        return quantity*beans/outputs,f'{quantity}{unit} × （{beans}kg ÷ {outputs}{unit}），按所用工艺加权'
    tanks=[(kind,Decimal(reg.get(kind+'_tanks') or '0')) for kind in ('large','small','skin') if Decimal(reg.get(kind+'_tanks') or '0')>0]
    if quantity is None or not tanks:return None,'缺少产量或所用浆缸记录'
    if any(not cfg.get(kind+'_slurry_crates') or not cfg.get(kind+'_slurry_kg') for kind,n in tanks):return None,'所用浆缸产量或用豆参数待补'
    if unit!='筐':return None,'历史每缸产出参数按筐登记，不能直接套用到其他单位；请在生产配置中确认产出单位'
    beans=sum(n*Decimal(cfg[k+'_slurry_kg']) for k,n in tanks)
    outputs=sum(n*Decimal(cfg[k+'_slurry_crates']) for k,n in tanks)
    if outputs<=0:return None,'浆缸产量参数须大于0'
    if len(tanks)==1:
        kind,n=tanks[0];formula=f"{quantity}{unit} ÷ {cfg[kind+'_slurry_crates']}{unit}/缸 × {cfg[kind+'_slurry_kg']}kg/缸"
    else:
        names={'large':'大豆腐浆缸','small':'中豆腐浆缸','skin':'豆皮浆缸'}
        basis='；'.join(f"{names[k]} {n}缸 × {cfg[k+'_slurry_crates']}{unit}/缸、{cfg[k+'_slurry_kg']}kg/缸" for k,n in tanks)
        formula=f'{quantity}{unit} × （{beans}kg ÷ {outputs}{unit}）；按所用缸数量加权：{basis}'
    return quantity*beans/outputs,formula

def number(value,label):return '' if value in ('',None) else rc.ds(rc.qty(value,label))

def normalize_attendance(c,b,old,groups,employees,schedule=False):
    day=rc.day(b.get('business_date'));entries=b.get('entries');independent=not schedule and b.get('format')=='person-day-v1';times=b.get('groups',[]) if independent else b.get('groups')
    if not isinstance(entries,list) or not entries or len(entries)>500:raise ValueError('请填写员工当天考勤')
    if not isinstance(times,list):raise ValueError('请按组登记上下班时间')
    table='factory_schedules' if schedule else 'factory_attendance'
    if any(json.loads(r[0]).get('format') in ('group-day-v2','group-plan-v1','person-day-v1') and json.loads(r[0])['business_date']==day and json.loads(r[0])['id']!=(old or {}).get('id') for r in c.execute('SELECT payload FROM '+table)):raise ValueError('当天已有'+('排班' if schedule else '考勤')+'，请修改当天记录')
    gs={g['id']:g for g in groups};es={e['id']:e for e in employees};normalized=[];seen=set();group_times=[];used=set()
    for r in entries:
        e=es.get(r.get('employee_id'));g=gs.get(r.get('group_id'));status=r.get('status','unrecorded' if independent else 'full')
        if not e or (not independent and (not g or not g.get('active'))) or independent and r.get('group_id') and not g:raise ValueError('员工或小组无效')
        if e['id'] in seen:raise ValueError('同一员工当天只能归属一个作业组，调组请直接修改所属组')
        seen.add(e['id'])
        if independent and status=='unrecorded' and b.get('state')=='confirmed':continue
        if status not in (('full','half','leave','absent','rest','unrecorded') if independent else ('full','half','leave','absent','rest')):raise ValueError('考勤只支持全天、半天、请假、缺勤、休息')
        if e.get('active') is False and not any(x['employee_id']==e['id'] for x in (old or {}).get('entries',[])):raise ValueError('停用员工不能新增排班')
        used.add(g['id'] if g else '');normalized.append({'employee_id':e['id'],'employee_name':e['name'],'group_id':g['id'] if g else '','group_name':g['name'] if g else '', 'employee_type':e.get('employee_type','production'),'department':e.get('department',''),'position':e.get('position',''),'status':status,'days':'1' if status=='full' else '0.5' if status=='half' else '0','note':rc.text(r.get('note',''),'考勤备注',200,False)})
    for t in times:
        gid=t.get('group_id')
        if gid not in gs or any(x['group_id']==gid for x in group_times):raise ValueError('时间对应的小组无效或重复')
        start=t.get('start_time','');end=t.get('end_time','')
        for value in (start,end):
            if value and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise ValueError('小组上下班时间格式应为时:分')
        group_times.append({'group_id':gid,'group_name':gs[gid]['name'],'start_time':start,'end_time':end})
    state=b.get('state','draft')
    if state not in ('draft','confirmed'):raise ValueError('考勤状态无效')
    if state=='confirmed' and not normalized:raise ValueError('至少确认一名员工的实际考勤')
    if state=='confirmed' and independent and day>__import__('payroll').local_today().isoformat():raise ValueError('未来日期不能登记实际出勤')
    if state=='confirmed' and not independent:
        working={r['group_id'] for r in normalized if r['status'] in ('full','half')}
        if any(not next((t['start_time'] for t in group_times if t['group_id']==gid),'') for gid in working):raise ValueError(('确认排班' if schedule else '确认考勤')+'前请填写每个出勤小组的上班时间')
    result={'format':'person-day-v1' if independent else 'group-day-v2','business_date':day,'state':state,'groups':group_times,'entries':normalized,'note':rc.text(b.get('note',''),'考勤说明',500,False)}
    if not schedule and (independent or b.get('workflow')=='separate-v1'):result['workflow']='separate-v1'
    if schedule:
        result['format']='group-plan-v1'
        if state=='confirmed':result['notice']=attendance_notice(c,result)
    elif not independent and b.get('source_schedule_id'):
        source=c.execute('SELECT payload FROM factory_schedules WHERE id=?',(b['source_schedule_id'],)).fetchone()
        source=json.loads(source[0]) if source else None
        if not source or source['business_date']!=day or source['state']!='confirmed':raise ValueError('来源排班无效，请先确认当天排班')
        if b.get('source_schedule_version')!=source['version']:raise ValueError('排班已修改，请重新打开考勤核对')
        result.update(source_schedule_id=source['id'],source_schedule_version=source['version'])
    elif state=='confirmed' and not independent:result['notice']=attendance_notice(c,result)
    return result

def attendance_notice(c,record):
    yesterday=(date.fromisoformat(record['business_date'])-timedelta(days=1)).isoformat()
    history=[json.loads(r[0]) for r in c.execute('SELECT payload FROM '+('factory_schedules' if record.get('format')=='group-plan-v1' else 'factory_attendance'))]
    prior=next((r for r in reversed(history) if r['business_date']==yesterday and r.get('format')==record.get('format') and r.get('state')=='confirmed'),None)
    lines=[record['business_date']+' 排班通知']
    for g in record['groups']:
        staff=[r['employee_name']+('（半天）' if r['status']=='half' else '') for r in record['entries'] if r['group_id']==g['group_id'] and r['status'] in ('full','half')]
        if staff:lines.append(g['group_name']+' '+g['start_time']+'上班：'+'、'.join(staff))
    exceptional=[r['employee_name']+'（'+{'leave':'请假','absent':'缺勤','rest':'休息'}[r['status']]+'）' for r in record['entries'] if r['status'] not in ('full','half')]
    if exceptional:lines.append('其他：'+'、'.join(exceptional))
    lines.append('与昨天相比：')
    if prior is None:lines.append('昨天没有已确认排班，暂无法比较调整。');return '\n'.join(lines)
    prev={r['employee_id']:r for r in prior['entries'] if r['status'] in ('full','half')};current={r['employee_id']:r for r in record['entries'] if r['status'] in ('full','half')};changes=[]
    for eid,r in current.items():
        old=prev.get(eid)
        if old is None:changes.append(r['employee_name']+'加入'+r['group_name'])
        elif old['group_id']!=r['group_id']:changes.append(r['employee_name']+'：'+old['group_name']+'→'+r['group_name'])
        elif old['status']!=r['status']:changes.append(r['employee_name']+'：'+('全天' if old['status']=='full' else '半天')+'→'+('全天' if r['status']=='full' else '半天'))
    changes += [r['employee_name']+'今日不在原'+r['group_name']+'出勤' for eid,r in prev.items() if eid not in current]
    lines.append('人员：'+'；'.join(changes) if changes else '人员分组无调整。')
    pg={g['group_id']:g for g in prior['groups']};changed=[]
    for g in record['groups']:
        old=pg.get(g['group_id'])
        if g['start_time'] and (not old or old.get('start_time')!=g['start_time']):changed.append(g['group_name']+'：'+(old.get('start_time') or '未排班' if old else '未排班')+'→'+g['start_time'])
    lines.append('上班时间：'+'；'.join(changed) if changed else '各组上班时间无调整。')
    return '\n'.join(lines)

def processing_summary(c,day,product_rows=None,entries=None):
    """Simple estimated cost and soybean-based yield for internal processing.

    Direct cost uses the source product's same-day average yield and the day's
    average soybean cost. Non-exclusive indirect costs are allocated by the month's
    processed output net weight. Missing cost or trace data stays "待结转/待核算".
    """
    from material_allocation import split
    names={r['id']:r['name'] for r in c.execute('SELECT id,name FROM products')};units={r['id']:r['unit'] for r in c.execute('SELECT id,unit FROM products')};standards={r['id']:r['standard_kg'] for r in c.execute('SELECT id,standard_kg FROM products')}
    def net_weight(item):
        raw=item.get('net_kg');standard=standards.get(item.get('product_id'))
        return Decimal(raw) if raw not in ('',None) else Decimal(item.get('qty') or '0')*Decimal(standard) if item.get('unit')!='筐' and standard not in (None,'') else Decimal(0)
    month=day[:7];rows=product_rows or [];yield_by_product={r.get('product_id'):r.get('yield_kg_per_kg') for r in rows}
    if entries is None:_,entries=rc.material_ledger(c,day)
    soy_qty=Decimal(0);soy_cost=0
    for e in entries:
        if e.get('business_date')!=day or e.get('material_id')!='RM-SOY' or e.get('kind') not in ('consume','return') or e.get('voided'):continue
        sign=1 if e['kind']=='consume' else -1;soy_qty+=Decimal(e.get('qty') or '0')*sign;soy_cost+=int(e.get('cost_cents') or 0)*sign
    soy_avg=Decimal(soy_cost)/soy_qty if soy_qty>0 and soy_cost>=0 else None
    month_batches=[b for b in rc.rows(c,'processing_batches') if not b.get('voided') and b.get('business_date','')[:7]==month]
    indirect_pool=sum(int(e.get('amount_cents') or 0) for e in rc.period_expenses(c,month) if not e.get('product_id'))
    indirect_by_batch=split(indirect_pool,{b['id']:sum((net_weight(o) for o in b.get('outputs',[])),Decimal(0)) for b in month_batches})
    result=[]
    for batch in rc.rows(c,'processing_batches'):
        if batch.get('voided') or batch.get('business_date')!=day:continue
        input_kg=Decimal(batch.get('input_kg') or '0');input_qty=Decimal(batch.get('input_qty') or '0');outputs=[];total_kg=Decimal(0);total_qty=Decimal(0)
        for item in batch.get('outputs',[]):
            qty=Decimal(item.get('qty') or '0');raw_net=item.get('net_kg');std=standards.get(item.get('product_id'));unit=item.get('unit')
            net=net_weight(item)
            total_qty+=qty;total_kg+=net
            outputs.append({**item,'unit':item.get('unit') or '','qty':rc.ds(qty),'net_kg':rc.ds(net) if raw_net not in ('',None) or unit!='筐' and std not in (None,'') else ''})
        source_yield=None if batch.get('origin')=='customer_return' else yield_by_product.get(batch.get('product_id'))
        soy_input=(input_kg/Decimal(str(source_yield))) if source_yield not in (None,'') and Decimal(str(source_yield))>0 else None
        direct_cents=int((soy_input*soy_avg).quantize(Decimal('1'))) if soy_input is not None and soy_avg is not None else None
        indirect_cents=indirect_by_batch.get(batch['id'],0)
        cost_status='退货原批成本待核对' if batch.get('origin')=='customer_return' else '估算' if direct_cents is not None else '待核算' if soy_input is None else '待结转'
        weights={item['product_id']:Decimal(item.get('net_kg') or '0') for item in outputs}
        direct_by_output=split(direct_cents,weights) if direct_cents is not None else {}
        indirect_by_output=split(indirect_cents,weights)
        costed=[]
        for item in outputs:
            net=Decimal(item.get('net_kg') or '0')
            out_direct=direct_by_output.get(item['product_id'],0) if direct_cents is not None else None
            out_indirect=indirect_by_output.get(item['product_id'],0)
            out_total=(out_direct+out_indirect) if out_direct is not None else None
            costed.append({**item,'cost_cents':out_total,'unit_cost_yuan_per_kg':rc.ds((Decimal(out_total)/net/100).quantize(Decimal('.01'))) if out_total is not None and net>0 else None,
                'unit_cost_yuan':rc.ds((Decimal(out_total)/Decimal(item.get('qty') or '1')/100).quantize(Decimal('.01'))) if out_total is not None and Decimal(item.get('qty') or '0')>0 else None})
        result.append({'id':batch.get('id'),'business_date':batch.get('business_date'),'source_product_id':batch.get('product_id'),'source_product_name':names.get(batch.get('product_id'),batch.get('product_id')),'source_unit':units.get(batch.get('product_id'),''),
            'input_kg':rc.ds(input_kg),'input_qty':rc.ds(input_qty),'outputs':costed,'output_net_kg':rc.ds(total_kg),'output_qty':rc.ds(total_qty),
            'yield_kg':rc.ds((total_kg/input_kg).quantize(Decimal('.001'))) if input_kg>0 and total_kg>0 else None,'yield_units':rc.ds((total_qty/input_qty).quantize(Decimal('.001'))) if input_qty>0 and total_qty>0 else None,
            'source_yield':source_yield,'soy_input_kg':rc.ds(soy_input.quantize(Decimal('.001'))) if soy_input is not None else None,'soy_yield':rc.ds((total_kg/soy_input).quantize(Decimal('.001'))) if soy_input and soy_input>0 and total_kg>0 else None,
            'soy_average_cents_per_kg':rc.ds(soy_avg.quantize(Decimal('.0001'))) if soy_avg is not None else None,'soy_average_yuan_per_kg':rc.ds((soy_avg/100).quantize(Decimal('.0001'))) if soy_avg is not None else None,'direct_cost_cents':direct_cents,'indirect_cost_cents':indirect_cents,
            'total_cost_cents':(direct_cents+indirect_cents) if direct_cents is not None else None,'cost_status':cost_status,
            'handler':batch.get('handler',''),'inspection_note':batch.get('inspection_note',''),'source_lot':batch.get('source_lot','')})
    return sorted(result,key=lambda x:(x['business_date'],x['id']),reverse=True)

def inferred_outputs(c,day):
    """Do not replace missing opening/counts by zero or by manually entered output."""
    stock=inventory.stock(c,day);closed=stock.get('closing');result=[]
    for p in stock['products']:
        closing=next((x.get('counted_qty') for x in (closed or {}).get('products',[]) if x['product_id']==p['product_id']),None)
        if closing is None:closing=p.get('counted_qty','')
        known=p['opening_qty'] not in ('',None) and closing not in ('',None)
        q=Decimal(p['shipped_qty'])+Decimal(closing or '0')+Decimal(p['loss_qty'])+Decimal(p['processing_input_qty'])-Decimal(p['opening_qty'] or '0')-Decimal(p['processing_output_qty'])-Decimal(p.get('purchased_qty','0'))-Decimal(p.get('return_restock_qty','0')) if known else None
        if q is not None and q<0:status='库存勾稽异常';q=None
        else:status='已日结' if known and closed else '待日结确认' if known else '待填期初 / 盘库结存'
        result.append({**p,'counted_qty':closing,'derived_qty':rc.ds(q) if q is not None else None,'output_status':status,'output_formula':f"实发{p['shipped_qty']} + 结存{closing} + 报损{p['loss_qty']} + 转加工投入{p['processing_input_qty']} − 期初{p['opening_qty']} − 转加工产出{p['processing_output_qty']} − 外购成品{p.get('purchased_qty','0')} − 退货可发入库{p.get('return_restock_qty','0')}" if known else '需库管登记期初、实发和盘库结存，缺项不按0计算'})
    return result

def issue_kg(c,day):
    _,entries=rc.material_ledger(c,day);record=next((r for r in rc.rows(c,'factory_daily') if r['business_date']==day),None)
    config=pc.get(c,day,record);result={s['id']:Decimal(0) for s in pc.active_systems(config)}
    for e in entries:
        if e['business_date']!=day or e['material_id']!='RM-SOY' or e['kind'] not in ('consume','return'):continue
        system=pc.source(e)
        if system:result[system]=result.get(system,Decimal(0))+Decimal(e['qty'])*(1 if e['kind']=='consume' else -1)
    return {k:rc.ds(v) for k,v in result.items()}

def soybean_analysis(warehouses):
    out=[]
    for w in warehouses:
        bands={'lt40':Decimal(0),'40to41':Decimal(0),'gt41':Decimal(0),'unknown':Decimal(0)};psum=pq=msum=mq=Decimal(0)
        for lot in w.get('lots',[]):
            q=Decimal(lot['qty']);quality=lot.get('quality',{});p=quality.get('protein_pct');m=quality.get('moisture_pct')
            if p in ('',None):bands['unknown']+=q
            else:
                protein=Decimal(p);bands['lt40' if protein<40 else 'gt41' if protein>41 else '40to41']+=q;psum+=q*protein;pq+=q
            if m not in ('',None):msum+=q*Decimal(m);mq+=q
        out.append({'warehouse_id':w['warehouse_id'],'warehouse_name':w['warehouse_name'],'qty':w['qty'],'bands':{k:rc.ds(v) for k,v in bands.items()},'average_protein':rc.ds((psum/pq).quantize(Decimal('.001'))) if pq else None,'protein_known_kg':rc.ds(pq),'average_moisture':rc.ds((msum/mq).quantize(Decimal('.001'))) if mq else None,'moisture_known_kg':rc.ds(mq)})
    return out

def report(c,day,settings,weight_fn):
    rc.day(day);cfg=hide_finance(settings);row=c.execute("SELECT payload FROM factory_daily WHERE json_extract(payload,'$.business_date')=? LIMIT 1",(day,)).fetchone();record=json.loads(row[0]) if row else None
    if record:cfg=record['settings_snapshot']
    config=pc.get(c,day,record,cfg);residuals={}
    for system in pc.active_systems(config):
        if system['allocation_mode']=='residual':residuals.setdefault(system['residual_product_id'],set()).add(system['id'])
    used=issue_kg(c,day);outputs=inferred_outputs(c,day);_,entries,warehouses=rc.material_ledger(c,day,True);issues=[e for e in entries if e['business_date']==day and e['kind']=='consume']
    registrations=(record or {}).get('products',[])
    import material_allocation
    allocation=material_allocation.day_report(c,day,record,entries)
    all_orders=[json.loads(r[0]) for r in c.execute("SELECT payload FROM orders WHERE json_extract(payload,'$.business_date')=?",(day,))];products={p['id']:dict(p) for p in c.execute('SELECT * FROM products')}
    scrap=[json.loads(r[0]) for r in c.execute("SELECT payload FROM factory_scrap WHERE json_extract(payload,'$.business_date')=? AND json_extract(payload,'$.format')='note-v2'",(day,))];scrap_total=sum((Decimal(r['kg']) for r in scrap),Decimal(0));product_rows=[]
    for p in outputs:
        source_rows=[r for r in registrations if r['product_id']==p['product_id']];reg=dict(source_rows[0]) if source_rows else {}
        all_counts=[pc.tank_counts(r) for r in source_rows];counts={}
        for key in {k for r in all_counts for k in r}:
            counts[key]=rc.ds(sum((Decimal(r.get(key) or '0') for r in all_counts),Decimal(0))) if all(r.get(key) not in ('',None) for r in all_counts) else ''
        reg.update(tanks=counts,**{k+'_tanks':counts.get(k,'0') for k in pc.LEGACY_FIELDS})
        actual_sources=sorted({r['system'] for r in source_rows if any(Decimal(n or '0')>0 for n in pc.tank_counts(r).values())})
        residual_sources=residuals.get(p['product_id'],set());known_sources=set(actual_sources)|{sid for sid in residual_sources if Decimal(used.get(sid,'0'))>0}
        system=next(iter(known_sources)) if len(known_sources)==1 else 'mixed' if len(known_sources)>1 else reg.get('system',next(iter(residual_sources)) if len(residual_sources)==1 else '')
        basis=pc.bean_basis(reg,config) if source_rows else None;complete=basis is not None;est=basis or Decimal(0)
        parts=[f"{counts.get(pr['id'])}缸 × {pr['dry_kg']}kg" for pr in config['processes'] if Decimal(counts.get(pr['id']) or '0')>0 and pr['dry_kg']]
        qty=Decimal(p['derived_qty']) if p['derived_qty'] is not None else None
        weight=quantity=Decimal(0)
        for o in all_orders:
            for l in o['lines']:
                if l['product_id']!=p['product_id']:continue
                kg,q=weight_fn(l,'driver')
                if kg is not None:weight+=kg;quantity+=q
        unit_kg=weight/quantity if quantity else None;weight_basis='按当天司机实称平均净重估算'
        if unit_kg is None:
            standard=products[p['product_id']].get('standard_kg')
            if standard and Decimal(standard)>0:unit_kg=Decimal(standard);weight_basis='按产品标准净重估算'
        if unit_kg is None:
            import production_management
            reference=production_management.product_average(c,products[p['product_id']])
            if reference:unit_kg=Decimal(reference);weight_basis='按产品默认平均净重估算'
        net=qty*unit_kg if qty is not None and unit_kg is not None else None
        bean=est if complete else None
        reverse,reverse_formula=selected_tank_conversion(reg,cfg,qty,p['unit'],config if record and record.get('config_snapshot') else None)
        incoming=sum((Decimal(r['kg']) for r in scrap if r.get('product_id')==p['product_id']),Decimal(0))
        def val(x):return rc.ds(x) if x is not None else None
        skin=p['product_id'] in residuals;denom=sum((Decimal(used.get(sid,'0')) for sid in residual_sources),Decimal(0)) if skin else bean
        allocated=[a for a in allocation['allocations'] if a['product_id']==p['product_id']]
        source_keys=set(actual_sources)|residual_sources
        pending=[pool for pool in allocation['pools'] if pool['system'] in source_keys and pool['reasons']]
        if record and record.get('format')=='daily-v3':denom=sum((Decimal(a['allocated_kg']) for a in allocated),Decimal(0)) if allocated and not pending else None
        product_rows.append({**p,**reg,'system':system,'source_systems':actual_sources,'allocated_sources':allocated,'allocation_reasons':[reason for pool in pending for reason in pool['reasons']],'slurry_bean_kg':val(est) if complete else None,'slurry_formula':' + '.join(parts) if complete else '浆缸记录或换算待补：'+' + '.join(parts),'reverse_bean_kg':val(reverse),'reverse_formula':reverse_formula,'net_kg':val(net),'weight_basis':weight_basis if net is not None else '待有司机实称重量或产品标准净重','unit_net_kg':val(unit_kg),'bean_kg':val(denom),'yield_units_per_kg':val(qty/denom) if qty is not None and denom else None,'yield_kg_per_kg':val(net/denom) if net is not None and denom else None,'scrap_input_kg':val(incoming),'skin_scrap_kg':val(scrap_total) if skin else None,'yield_with_scrap':val((net+scrap_total)/denom) if skin and net is not None and denom else None,'yield_formula':f"{val(net)}kg估算成品 ÷ {val(denom)}kg干豆" if net is not None and denom else '待补产量、净重依据或用豆','scrap_note':f'有{incoming}kg烂豆皮进入本产品加工，仅作备注' if incoming else ''})
    processing=processing_summary(c,day,product_rows,entries);processable={r['output_product_id'] for r in inventory.processing_rules(c)};proc_map={}
    for batch in processing:
        total_net=Decimal(batch.get('output_net_kg') or '0');soy=Decimal(batch.get('soy_input_kg') or '0') if batch.get('soy_input_kg') not in (None,'') else None
        for out in batch.get('outputs',[]):
            net=Decimal(out.get('net_kg') or '0');share=net/total_net if total_net>0 else Decimal(0);target=proc_map.setdefault(out['product_id'],{'net':Decimal(0),'qty':Decimal(0),'soy':Decimal(0),'soy_known':True,'source':[],'input_kg':Decimal(0)})
            target['net']+=net;target['qty']+=Decimal(out.get('qty') or '0')
            if soy is None:target['soy_known']=False
            else:target['soy']+=soy*share
            if batch.get('source_product_name') not in target['source']:target['source'].append(batch.get('source_product_name'))
    for row in product_rows:
        material=next((r.get('main_material') for r in registrations if r['product_id']==row['product_id'] and r.get('main_material')),None) or main_material(c,products[row['product_id']])
        row['main_material']=material
        if not uses_slurry(material) and row['product_id'] not in proc_map and row['product_id'] not in processable:
            row.update(system=None,slurry_bean_kg=None,reverse_bean_kg=None,bean_kg=None,yield_units_per_kg=None,yield_kg_per_kg=None,yield_with_scrap=None,slurry_formula='非用浆产品，不参与黄豆换算',reverse_formula='非用浆产品，不参与黄豆换算',yield_formula='非黄豆制品，不计算黄豆出品率')
    for row in product_rows:
        missing=[]
        def lack(field,owner,target):missing.append({'field':field,'owner':owner,'target':target,'business_date':day})
        if row['opening_qty'] in ('',None):lack('期初库存','库管','allocation')
        if row['counted_qty'] in ('',None):lack('盘库结存','库管','allocation')
        if row['derived_qty'] is None and row['output_status']=='库存勾稽异常':lack('库存数量勾稽（推算产量为负）','库管','allocation')
        if uses_slurry(row['main_material']):
            for reason in row.get('allocation_reasons',[]):lack(reason,'厂长 / 会计','daily')
            if row['product_id'] in residuals:
                if sum((Decimal(used.get(sid,'0')) for sid in residuals[row['product_id']]),Decimal(0))<=0:lack('磨浆系统上豆量','厂长 / 库管','beans')
            else:
                if not any(Decimal(n or '0')>0 for n in pc.tank_counts(row).values()) and row['derived_qty']!='0':lack('该产品所用大豆腐 / 中豆腐浆缸数','厂长','daily')
                elif row['bean_kg'] is None:lack('浆缸用豆换算参数','厂长 / 管理员','factory-settings')
            if row['unit_net_kg'] is None:lack('司机称重或产品默认平均净重','司机补称重，库管核对；会计维护产品参考','weighing')
        row['missing_data']=missing
        row['calculation_status']='不计算黄豆出品率' if not uses_slurry(row['main_material']) else '待补数据' if missing else '估算结果' if row['yield_kg_per_kg'] is not None else '当天无产量 / 用豆'
        row['follow_up']=('；'.join(m['field']+'：'+m['owner']+'补录' for m in missing))
    for row in product_rows:
        target=proc_map.get(row['product_id'])
        if not target:continue
        row['net_kg']=val(target['net']) if target['net']>=0 else row.get('net_kg');row['processing_output_qty']=val(target['qty'])
        if row.get('derived_qty') in (None,'0') and target['qty']>0:row['derived_qty']=val(target['qty'])
        row['processing_output_net_kg']=val(target['net']);row['processing_input_kg']=rc.ds(sum((Decimal(b.get('input_kg') or '0') for b in processing if b.get('source_product_name') in target['source']),Decimal(0)))
        row['processing_source_name']='、'.join(target['source'])
        if target['soy_known'] and target['soy']>0:
            row['bean_kg']=val(target['soy']);row['yield_kg_per_kg']=val(target['net']/target['soy']);row['yield_units_per_kg']=None
            row['yield_formula']=f"转加工产出净重{val(target['net'])}kg ÷ 对应黄豆投入{val(target['soy'])}kg"
            row['calculation_status']='估算结果（转加工）';row['missing_data']=[];row['follow_up']=''
        else:
            row['bean_kg']=None;row['yield_kg_per_kg']=None;row['calculation_status']='待核算（转加工来源出品率）';row['yield_formula']='转加工来源产品当日出品率待补；补齐来源产量与用豆后自动折算'
    for row in product_rows:
        if row['product_id'] in processable and row['product_id'] not in proc_map:
            row['calculation_status']='待核算（暂无转加工投入）';row['yield_formula']='通过厂内转加工投入后可计算对应黄豆出品率'
    systems=[]
    for item in pc.active_systems(config):
        key=item['id'];label=item['name'];n=(record or {}).get('systems',{}).get(key,{}).get('soak_tanks','')
        soak=Decimal(n)*Decimal(item['soak_kg']) if n not in ('',None) and item['soak_kg'] else None
        rs=[{**r,'slurry_bean_kg':rc.ds(pc.bean_basis(r,config)) if pc.bean_basis(r,config) is not None else None,'slurry_formula':'按本来源浆缸折豆量核对','reverse_bean_kg':next((p['reverse_bean_kg'] for p in product_rows if p['product_id']==r['product_id'] and p['system']!='mixed'),None),'reverse_formula':'混用来源不按全部产量重复倒推','derived_qty':next((p['derived_qty'] for p in product_rows if p['product_id']==r['product_id']),None)} for r in registrations if r['system']==key]
        active=[r for r in rs if any(Decimal(n or '0')>0 for n in pc.tank_counts(r).values()) or Decimal(r.get('derived_qty') or '0')>0]
        slurry=sum((Decimal(r['slurry_bean_kg']) for r in rs),Decimal(0)) if rs and all(r['slurry_bean_kg'] is not None for r in rs) else None
        reverse=sum((Decimal(r['reverse_bean_kg']) for r in active),Decimal(0)) if active and all(r['reverse_bean_kg'] is not None for r in active) else None
        if item['allocation_mode']=='residual':slurry=reverse=None
        methods=[];base=Decimal(used[key])
        for name,value,formula in [('上豆量',base,'共用库管与厂长的原料领用流水，退料扣回'),('泡豆桶估算',soak,f"{n}桶 × {item['soak_kg']}kg/桶" if soak is not None else '待填写泡豆桶数'),('浆缸估算',slurry,'；'.join(r['product_name']+'：'+r['slurry_formula'] for r in active)),('产量倒推',reverse,'；'.join(r['product_name']+'：'+r['reverse_formula'] for r in active))]:
            diff=value-base if value is not None else None;pct=diff/base*100 if diff is not None and base else None
            methods.append({'method':name,'kg':rc.ds(value) if value is not None else None,'formula':formula or '待补记录','difference_kg':rc.ds(diff) if diff is not None else None,'difference_pct':rc.ds(pct.quantize(Decimal('.01'))) if pct is not None else None,'alert':pct is not None and abs(pct)>Decimal(cfg['evidence_alert_pct'])})
        systems.append({'system':key,'name':label,'allocation_mode':item['allocation_mode'],'issued_kg':used[key],'soak_tanks':n,'methods':methods})
    attendance=[json.loads(r[0]) for r in c.execute('SELECT payload FROM factory_attendance') if json.loads(r[0])['business_date']==day and json.loads(r[0]).get('format') in ('group-day-v2','person-day-v1') ];summary=[]
    for g in rc.rows(c,'factory_groups'):
        es=[e for a in attendance for e in a['entries'] if e['group_id']==g['id'] and e.get('employee_type','production')=='production' and e.get('entry_state',a.get('state'))=='confirmed'];summary.append({'group_name':g['name'],'full':sum(e['status']=='full' for e in es),'half':sum(e['status']=='half' for e in es),'absent':sum(e['status'] in ('absent','leave') for e in es),'days':rc.ds(sum((Decimal(e['days']) for e in es),Decimal(0)))})
    return {'business_date':day,'record':record,'production_config':config,'settings':cfg,'systems':systems,'products':product_rows,'soybean_warehouses':[w for w in warehouses if w['id']=='RM-SOY'],'soybean_analysis':soybean_analysis([w for w in warehouses if w['id']=='RM-SOY']),'issues':issues,'attendance_groups':summary,'scrap':scrap,'scrap_total_kg':rc.ds(scrap_total),'materials':rc.material_ledger(c,day)[0],'output_basis':'产量＝实发＋盘库结存＋报损＋转加工投入－期初－转加工产出；盘库未齐时不补零。','processing':processing}
