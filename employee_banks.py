"""Restricted employee bank details and previewed XLSX imports (text card numbers)."""
import base64
import hashlib
import io
import json
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import erp_access as access
import resources_costs as rc

HEADERS=('员工编号','员工姓名','开户银行','银行卡号','开户姓名','开户支行')
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def bank(c,eid):
    row=c.execute('SELECT payload FROM employee_bank_accounts WHERE employee_id=?',(eid,)).fetchone()
    return json.loads(row[0]) if row else None


def mask(card):return ('*' * max(0,len(card)-4))+card[-4:] if card else ''


def report(c):
    banks={r[0]:json.loads(r[1]) for r in c.execute('SELECT employee_id,payload FROM employee_bank_accounts')}
    return {'rows':[{**{k:e.get(k,'') for k in ('id','name','employee_type','group_id','group_name','position','active','version')},'bank':banks.get(e['id'])} for e in rc.rows(c,'factory_employees')]}


def normalize(values,allow_missing_bank=False):
    card=values.get('bank_card','')
    if not isinstance(card,str):raise ValueError('银行卡号必须使用文本格式，不能使用数值或科学计数法')
    card=re.sub(r'[ \t-]','',card.strip())
    if card and not re.fullmatch(r'[0-9]{12,30}',card):raise ValueError('银行卡号请填写12至30位数字；请核对文本格式和完整位数')
    result={k:rc.text(values.get(k,''),label,size,False) for k,label,size in [('bank_name','开户银行',100),('account_name','开户姓名',60),('bank_branch','开户支行',150)]}
    if not card or not result['account_name'] or (not allow_missing_bank and not result['bank_name']):raise ValueError('请完整填写开户银行、银行卡号和开户姓名')
    return {**result,'bank_card':card}


def template(c):
    """Small dynamic XLSX; IDs and cards always use inline strings, never numbers."""
    rows=[HEADERS]+[(e['id'],e['name'],'','','','') for e in rc.rows(c,'factory_employees') if e.get('active',True)]
    xmlrows=[]
    for n,row in enumerate(rows,1):
        cells=''.join(f'<c r="{chr(65+i)}{n}" t="inlineStr" s="1"><is><t>{escape(str(v))}</t></is></c>' for i,v in enumerate(row))
        xmlrows.append(f'<row r="{n}">{cells}</row>')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="'+NS['s']+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="员工银行卡" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml','<styleSheet xmlns="'+NS['s']+'"><fonts count="1"><font><sz val="11"/><name val="Microsoft YaHei"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="'+NS['s']+'"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="1" width="27" customWidth="1"/><col min="2" max="3" width="20" customWidth="1"/><col min="4" max="4" width="32" style="1" customWidth="1"/><col min="5" max="6" width="24" customWidth="1"/></cols><sheetData>'+''.join(xmlrows)+'</sheetData></worksheet>')
    return output.getvalue()


def read_xlsx(encoded):
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)>524288:raise ValueError('Excel文件请控制在512KB以内')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist())>100 or sum(i.file_size for i in z.infolist())>8*1024*1024:raise ValueError('Excel文件内容过大')
            def xml(name):
                raw=z.read(name)
                if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Excel包含不支持的XML声明')
                return ET.fromstring(raw)
            book=xml('xl/workbook.xml');sheets=book.findall('s:sheets/s:sheet',NS)
            if len(sheets)!=1:raise ValueError('请使用只有一个工作表的银行卡导入模板')
            rid=sheets[0].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            rels=xml('xl/_rels/workbook.xml.rels');rel=next((r for r in rels if r.get('Id')==rid),None)
            if rel is None or rel.get('TargetMode')=='External':raise ValueError('Excel工作表关联无效')
            target=rel.get('Target','');name=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            if '..' in name.split('/') or not name.startswith('xl/worksheets/'):raise ValueError('Excel工作表路径无效')
            shared=[''.join(e.itertext()) for e in xml('xl/sharedStrings.xml').findall('s:si',NS)] if 'xl/sharedStrings.xml' in z.namelist() else []
            rows=[]
            for row in xml(name).findall('s:sheetData/s:row',NS):
                n=int(row.get('r','0'))
                if not 1<=n<=1001:raise ValueError('每次最多导入1000行员工')
                cells={};numeric=set()
                for cell in row.findall('s:c',NS):
                    ref=cell.get('r','');match=re.fullmatch(r'([A-F])([0-9]+)',ref)
                    if not match:continue
                    if cell.find('s:f',NS) is not None:raise ValueError(f'第{n}行含公式，请粘贴为文本值后导入')
                    kind=cell.get('t','n');value=cell.findtext('s:v','',NS)
                    if kind=='inlineStr':value=''.join(cell.find('s:is',NS).itertext()) if cell.find('s:is',NS) is not None else ''
                    elif kind=='s':value=shared[int(value)]
                    elif kind not in ('str','n'):raise ValueError(f'第{n}行含不支持的单元格类型')
                    cells[match[1]]=value.strip()
                    if kind=='n' and value.strip():numeric.add(match[1])
                values=[cells.get(chr(65+i),'') for i in range(6)]
                if any(values):rows.append((n,values,numeric))
            if not rows or rows[0][0]!=1:raise ValueError('表头不匹配，请下载员工银行卡模板')
            labels=[h.strip() for h in rows[0][1]]
            if tuple(labels)==HEADERS:
                indexes={label:i for i,label in enumerate(HEADERS)}
            else:
                alias={'员工编号':('员工编号','编号'),'员工姓名':('员工姓名','姓名'),'开户银行':('开户银行','银行'),'银行卡号':('银行卡号','卡号'),'开户姓名':('开户姓名','持卡人','户名'),'开户支行':('开户支行','支行')}
                indexes={}
                for key,names in alias.items():
                    found=[i for i,h in enumerate(labels) if h in names]
                    if len(found)>1:raise ValueError('表头重复，请只保留一列“'+names[0]+'”')
                    if found:indexes[key]=found[0]
                if '员工姓名' not in indexes or '银行卡号' not in indexes:raise ValueError('表头不匹配，请使用员工银行卡模板，或至少包含“姓名”和“银行卡号”两列')
            data=rows[1:]
            if len({n for n,_,_ in data})!=len(data):raise ValueError('Excel行号重复')
            card_col=chr(65+indexes['银行卡号'])
            for n,values,kinds in data:
                if card_col in kinds:raise ValueError(f'第{n}行银行卡号是数值，可能已丢失精度；请核对原卡并改为文本')
            def mapped(values):return [values[indexes[k]] if k in indexes else '' for k in HEADERS]
            return [(n,mapped(values)) for n,values,_ in data]
    except (zipfile.BadZipFile,KeyError,ET.ParseError,IndexError,TypeError,OverflowError) as e:
        raise ValueError('无法读取Excel文件，请使用.xlsx格式的员工银行卡模板') from e

def preview(c,encoded):
    employees={e['id']:e for e in rc.rows(c,'factory_employees')};by_name={}
    for employee in employees.values():by_name.setdefault(employee['name'],[]).append(employee)
    rows=[];errors=[];seen=set();cards={}
    existing={r[0]:json.loads(r[1]) for r in c.execute('SELECT employee_id,payload FROM employee_bank_accounts')}
    for n,values in read_xlsx(encoded):
        eid,name,bank_name,card,holder,branch=values
        if not any(values[2:]):continue
        try:
            if not eid and not name:raise ValueError('请填写员工姓名或员工编号')
            if eid:
                employee=employees.get(eid)
                if not employee:raise ValueError('员工编号不存在，请核对')
                if name and employee['name']!=name:raise ValueError('员工编号与姓名不匹配')
            else:
                matches=by_name.get(name,[])
                if not matches:raise ValueError('姓名未匹配到员工，请核对姓名或填写员工编号')
                if len(matches)>1:raise ValueError('姓名对应多名员工，请填写员工编号')
                employee=matches[0]
            eid=employee['id'];name=employee['name']
            if not employee.get('active',True):raise ValueError('员工已停用，请先核对人员档案')
            if eid in seen:raise ValueError('员工编号重复')
            seen.add(eid)
            record=normalize({'bank_name':bank_name,'bank_card':card,'account_name':holder or name,'bank_branch':branch},allow_missing_bank=True)
            if record['bank_card'] in cards:raise ValueError('银行卡号与第'+str(cards[record['bank_card']])+'行重复')
            cards[record['bank_card']]=n
            if any(k!=eid and r['bank_card']==record['bank_card'] for k,r in existing.items()):raise ValueError('银行卡号已登记给其他员工，请核对')
            old=existing.get(eid)
            rows.append({'row':n,'employee_id':eid,'employee_name':name,'employee_version':employees[eid]['version'],'version':(old or {}).get('version',0),'action':'更新' if old else '新增','old_card':mask((old or {}).get('bank_card','')),**record})
        except ValueError as e:errors.append({'row':n,'message':str(e)})
    if not rows and not errors:errors.append({'row':0,'message':'没有待导入的银行卡，请填写员工姓名（或员工编号）和银行卡号'})
    token=hashlib.sha256(rc.dump({'rows':rows,'errors':errors}).encode()).hexdigest()
    return {'rows':rows,'errors':errors,'token':token,'count':len(rows),'ok':not errors}


def save(c,kind,b,role,now,audit):
    access.require_role(role,'payroll.write')
    if kind=='employee-bank-preview':return preview(c,b.get('file',''))
    key=rc.text(b.get('request_key'),'提交编号',100);finger=hashlib.sha256(rc.dump({k:v for k,v in b.items() if not k.startswith('_')}).encode()).hexdigest();claim='employee-bank-request:'+key
    prior=c.execute('SELECT value FROM meta WHERE key=?',(claim,)).fetchone()
    if prior:
        prior=json.loads(prior[0])
        if prior['fingerprint']!=finger:raise ValueError('提交编号已用于其他内容')
        return prior['result']
    if kind=='employee-bank-import':
        p=preview(c,b.get('file',''))
        if p['errors']:raise ValueError('导入内容存在错误，请修正后重新预览')
        if p['token']!=b.get('token'):raise ValueError('预览后人员或银行卡资料已变化，请重新预览')
        planned=p['rows']
    else:
        eid=b.get('employee_id');employee=next((e for e in rc.rows(c,'factory_employees') if e['id']==eid),None)
        if not employee:raise ValueError('员工不存在')
        old=bank(c,eid)
        if b.get('version')!=(old or {}).get('version',0):raise ValueError('银行卡已修改，请重新打开核对')
        record=normalize(b)
        if c.execute("SELECT 1 FROM employee_bank_accounts WHERE employee_id!=? AND json_extract(payload,'$.bank_card')=?",(eid,record['bank_card'])).fetchone():raise ValueError('银行卡号已登记给其他员工，请核对')
        planned=[{'employee_id':eid,'employee_name':employee['name'],**record}]
    c.execute('SAVEPOINT employee_bank_write')
    try:
        for row in planned:
            eid=row['employee_id'];old=bank(c,eid);record={k:row[k] for k in ('bank_name','bank_card','account_name','bank_branch')}
            record.update(employee_id=eid,version=(old or {}).get('version',0)+1,updated_at=now())
            c.execute('INSERT INTO employee_bank_accounts VALUES(?,?) ON CONFLICT(employee_id) DO UPDATE SET payload=excluded.payload',(eid,rc.dump(record)))
            safe=lambda r:{**r,'bank_card':mask(r['bank_card'])} if r else None
            audit(c,role,'维护员工银行卡',eid,safe(old),safe(record))
        result={'saved':len(planned)}
        c.execute('INSERT INTO meta VALUES(?,?)',(claim,rc.dump({'fingerprint':finger,'result':result})))
        c.execute('RELEASE SAVEPOINT employee_bank_write');return result
    except Exception:
        c.execute('ROLLBACK TO SAVEPOINT employee_bank_write');c.execute('RELEASE SAVEPOINT employee_bank_write');raise
