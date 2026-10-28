"""Synthetic payroll/Excel/browser fixtures. Never uses production data."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import server
import personnel
import payroll
import resources_costs as rc
from test_employee_banks import EmployeeBankTests

db=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True);server.DB=db
with server.connect(True) as c:
    import company
    company.save(c,{'request_key':'SYNTHETIC-COMPANY','version':0,'name':'合成测试公司甲','address':'合成测试地址1号','phone':'000-TEST','tax_id':'TEST-ONLY','contact':'合成测试联系人'},'管理员',server.now,server.audit)
    employees=[e for e in rc.rows(c,'factory_employees') if e.get('active',True)]
    for i,e in enumerate(employees):
        e['position']='测试岗位'+str(i%3);c.execute('UPDATE factory_employees SET payload=? WHERE id=?',(rc.dump(e),e['id']))
        old=next(r for r in payroll.records(c) if r['kind']=='profile' and r['employee_id']==e['id'])
        payroll.save(c,'wage-profile',{'request_key':str(uuid.uuid4()),'employee_id':e['id'],'version':old['version'],'monthly_salary':'3000','salary_mode':'monthly','social_base':'100','social_company_rate':'20','social_personal_rate':'8'},'管理员',server.now,server.audit)
    for day,status in [('2020-09-01','full'),('2020-09-02','half')]:
        for scope in ('production','management'):
            entries=[{'employee_id':e['id'],'group_id':e.get('group_id',''),'status':status} for e in employees if e.get('employee_type','production')==scope]
            if not entries:continue
            old=next((r for r in rc.rows(c,'factory_attendance') if r['business_date']==day),None)
            personnel.save_day(c,{'request_key':str(uuid.uuid4()),'business_date':day,'id':(old or {}).get('id'),'version':(old or {}).get('version',0),'entries':entries,'state':'confirmed'},scope,'管理员',server.now,server.audit)
    report=payroll.report(c,'2020-09')
    sheet=payroll.save(c,'wage-sheet',{'request_key':str(uuid.uuid4()),'month':'2020-09','state':'confirmed','version':0,'attendance_token':report['attendance_token'],'salary_token':report['salary_token'],'rows':[{'employee_id':r['employee_id'],'bonus':'0','deduction':'0'} for r in report['rows']]},'管理员',server.now,server.audit)
    selected=employees[0]
    payment=payroll.save(c,'wage-pay',{'request_key':str(uuid.uuid4()),'month':'2020-09','employee_id':selected['id'],'version':sheet['version'],'paid_cents':0,'amount':'10','method':'cash','business_date':'2020-10-01','handler':'测试出纳','reference':'TEST-PAY-069'},'管理员',server.now,server.audit)
    values=[selected['id'],selected['name'],'合成测试银行','0012345678901234567',selected['name'],'合成测试支行']
    import base64
    writer=SimpleNamespace(c=c)
    (out/'bank-valid.xlsx').write_bytes(base64.b64decode(EmployeeBankTests.workbook(writer,[values])))
    wrong=[*values];wrong[1]='错误员工姓名'
    (out/'bank-invalid.xlsx').write_bytes(base64.b64decode(EmployeeBankTests.workbook(writer,[values,wrong])))
    (out/'fixture.json').write_text(json.dumps({'employee':selected,'payment':payment,'month':'2020-09'},ensure_ascii=False))
