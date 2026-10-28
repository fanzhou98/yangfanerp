"""Independent daily gel tofu bean/output check, using the factory's standard ratio."""
from decimal import Decimal
import json
import resources_costs as rc
import erp_access as access
import production_config as pc


def products(c,day):
    config=pc.get(c,day)
    return [dict(p) for p in c.execute('SELECT id,name,unit FROM products') if '内脂' in p['name'] or '内酯' in p['name'] or config['products'].get(p['id'],{}).get('default_system_id')=='gel-tofu']


def report(c,day):
    import production_daily as daily
    rc.day(day);config=pc.get(c,day);system=next((s for s in config['systems'] if s['id']=='gel-tofu'),None)
    if not system:return None
    saved=c.execute("SELECT value FROM meta WHERE key='gel_tofu_output_standard'").fetchone();reference=json.loads(saved[0]) if saved else {}
    rule=system.get('standard_output_rule') or reference
    if not rule or day<rule.get('effective_date','0001-01-01'):return None
    unit=rule.get('unit') or '盒'
    ps=[p for p in products(c,day) if p['unit']==unit]
    if not ps:return None
    dry=Decimal(rule['dry_kg']);standard_qty=Decimal(rule['output_qty']);used=Decimal(daily.issue_kg(c,day).get('gel-tofu','0'));registered=[r for r in rc.rows(c,'gel_daily_outputs') if r['business_date']==day]
    pids={p['id'] for p in ps};inferred=[r for r in daily.inferred_outputs(c,day) if r['product_id'] in pids]
    actual=sum((Decimal(r['qty']) for r in registered),Decimal(0)) if registered else sum((Decimal(r['derived_qty']) for r in inferred),Decimal(0)) if inferred and all(r['derived_qty'] is not None for r in inferred) else None
    expected=used/dry*standard_qty;required=actual/standard_qty*dry if actual is not None else None
    return {'business_date':day,'system_id':'gel-tofu','rule':rule,'unit':unit,'products':ps,'registrations':registered,'used_kg':rc.ds(used),'expected_output_qty':rc.ds(expected.quantize(Decimal('.001'))),'actual_output_qty':rc.ds(actual) if actual is not None else None,'output_difference_qty':rc.ds(actual-expected) if actual is not None else None,'standard_required_kg':rc.ds(required) if required is not None else None,'bean_difference_kg':rc.ds(used-required) if required is not None else None,'kg_per_box':rc.ds((used/actual).quantize(Decimal('.001'))) if actual else None,'basis':f'按独立上豆流水与实际产出对比；{rc.ds(dry)}公斤干豆标准产{rc.ds(standard_qty)}{unit}','actual_basis':'实际产出登记' if registered else '库存勾稽产量' if actual is not None else '待登记实际产出'}


def save(c,b,role,now,audit):
    import inventory
    access.require_role(role,'production.record');day=rc.day(b.get('business_date'));rc.open_period(c,day);inventory.open_day(c,day)
    current=report(c,day)
    if not current:raise ValueError('该日期尚未启用内脂豆腐产出标准，请核对生产配置生效日期与产品单位')
    if b.get('product_id') not in {p['id'] for p in current['products']}:raise ValueError('请选择与标准单位一致的内脂豆腐产品')
    qty=rc.qty(b.get('qty'),'实际产出数量')
    if qty!=qty.to_integral_value():raise ValueError('实际产出数量须为整数')
    row=c.execute('SELECT payload FROM gel_daily_outputs WHERE id=?',(day+'|'+b['product_id'],)).fetchone();old=json.loads(row[0]) if row else None
    if b.get('version')!=(old or {}).get('version',0):raise ValueError('当日内脂豆腐产出已更新，请刷新后核对')
    value={'id':day+'|'+b['product_id'],'business_date':day,'product_id':b['product_id'],'qty':rc.ds(qty),'version':(old or {}).get('version',0)+1,'note':rc.text(b.get('note'),'产出登记依据',500),'handler':role,'at':now(),'standard_output_rule':current['rule']}
    c.execute('INSERT INTO gel_daily_outputs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(value['id'],rc.dump(value)));audit(c,role,'登记内脂豆腐实际产出',value['id'],old,value);return value
