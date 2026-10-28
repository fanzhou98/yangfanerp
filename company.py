"""Versioned company identity; newly issued documents keep an identity snapshot."""
import hashlib
import json
from html import escape
import erp_access as access
import resources_costs as rc

KEY='company_identity_v1'
FIELDS={'name':('公司 / 工厂正式名称',120),'short_name':('简称',60),'tax_id':('统一社会信用代码',30),'address':('地址',300),'phone':('联系电话',40),'contact':('联系人',80)}


def current(c):
    row=c.execute('SELECT value FROM meta WHERE key=?',(KEY,)).fetchone()
    return json.loads(row[0]) if row else {'version':0,'name':'昌吉市洋帆豆制品厂',**{k:'' for k in FIELDS if k!='name'}}


def save(c,b,role,now,audit):
    access.require_role(role,'system.parameters')
    if role!='管理员':raise ValueError('公司信息仅限管理员维护')
    key=rc.text(b.get('request_key'),'提交编号',100);claim='company-request:'+key
    fingerprint=hashlib.sha256(rc.dump({k:v for k,v in b.items() if not k.startswith('_')}).encode()).hexdigest()
    prior=c.execute('SELECT value FROM meta WHERE key=?',(claim,)).fetchone()
    if prior:
        prior=json.loads(prior[0])
        if prior['fingerprint']!=fingerprint:raise ValueError('提交编号已用于其他公司信息')
        return prior['record']
    old=current(c)
    if b.get('version')!=old['version']:raise ValueError('公司信息已修改，请重新读取核对')
    record={k:rc.text(b.get(k,''),label,size,k=='name') for k,(label,size) in FIELDS.items()}
    record.update(version=old['version']+1,updated_at=now())
    c.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,rc.dump(record)))
    c.execute('INSERT INTO meta VALUES(?,?)',(claim,rc.dump({'fingerprint':fingerprint,'record':record})))
    audit(c,role,'维护公司信息',KEY,old,record);return record


def header_html(value=None,legacy=False):
    value=value or {'name':'昌吉市洋帆豆制品厂'}
    lines=[]
    for label,key in [('统一社会信用代码','tax_id'),('地址','address'),('联系电话','phone'),('联系人','contact')]:
        if value.get(key):lines.append(label+'：'+value[key])
    return '<div class="company-name">'+escape(value['name'])+'</div>'+(''.join('<div class="company-details">'+escape(line)+'</div>' for line in lines))+('<div class="company-details">公司信息按当前资料补充；历史单据未留存公司快照。</div>' if legacy else '')


def text_lines(value):
    return [label+'：'+value[key] for label,key in [('统一社会信用代码','tax_id'),('地址','address'),('联系电话','phone'),('联系人','contact')] if value and value.get(key)]
