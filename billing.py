"""Explicit monetary units, independent of warehouse handling units."""
from decimal import Decimal

def enabled(c):
    row=c.execute("SELECT value FROM meta WHERE key='settlement_unit'").fetchone()
    return bool(row and row[0]=='公斤')

def is_kg(line):return line.get('billing_unit','公斤' if line['unit']=='筐' else line['unit'])=='公斤'

def package_kg(line):
    if line.get('package_customer_net_kg') not in (None,''):return Decimal(line['package_customer_net_kg'])
    if line.get('package_net_kg') not in (None,''):return Decimal(line['package_net_kg'])
    if line.get('factory_net_kg') not in (None,''):return Decimal(line['factory_net_kg'])
    return standard_weight(line)

def standard_weight(line):
    unit_weight='1' if line['unit']=='公斤' else line.get('standard_kg') if line['unit']!='筐' else line.get('standard_unit_kg')
    return Decimal(line['actual_qty'])*Decimal(unit_weight or '0')

def default_weight_mode(line, pickup=False):
    if not pickup and line.get('driver_weight_basis')=='gross':return 'driver'
    if line.get('customer'):return 'customer'
    if line.get('driver'):return 'driver'
    if line.get('factory_net_kg'):return 'factory'
    if standard_weight(line)>0:return 'standard'
    return 'customer' if pickup else 'driver'

def settlement_net(line,source,tares=None):
    if source not in ('driver','customer'):raise ValueError('皮重调整仅适用于司机或客户称重')
    if source=='driver':
        if line.get('driver_weight_basis')!='gross':return Decimal(line['driver_net'])
        typed=line.get('crate_lines') or []
        if sum((Decimal(str(r['qty'])) for r in typed),Decimal(0))!=Decimal(line['actual_qty']):raise ValueError('司机毛重算票须先核对发出框型，框数合计须等于实发数量')
        value=sum((Decimal(w['gross']) for w in line['driver']),Decimal(0))-sum((Decimal(str(r['qty']))*Decimal(r['tare']) for r in typed),Decimal(0))
        if value<=0:raise ValueError('司机总毛重必须大于发出框型总皮重')
        return value
    tare=(tares or {}).get(source)
    typed=line.get('crate_lines',[])
    if typed:return sum((Decimal(w['gross']) for w in line[source]),Decimal(0))-sum((Decimal(str(w['qty']))*Decimal(w['tare']) for w in typed),Decimal(0))
    if tare in (None,''):return Decimal(line[source+'_net'])
    return sum((Decimal(w['gross']) for w in line[source]),Decimal(0))-Decimal(line['actual_qty'])*Decimal(tare)
