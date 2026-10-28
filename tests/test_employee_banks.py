import base64
import io
import json
import unittest
import uuid
import zipfile
from xml.etree import ElementTree as ET
import employee_banks as banks
import test_payroll as fixture
import production_management as fm


class EmployeeBankTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown

    def workbook(self,values,mutate=None,headers=None):
        output=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(banks.template(self.c))) as src,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as dst:
            for name in src.namelist():
                raw=src.read(name)
                if name=='xl/worksheets/sheet1.xml':
                    root=ET.fromstring(raw);data=root.find('s:sheetData',banks.NS)
                    for row in list(data)[1:]:data.remove(row)
                    for n,values_ in enumerate(values,2):
                        row=ET.SubElement(data,'{'+banks.NS['s']+'}row',r=str(n))
                        for i,value in enumerate(values_):
                            cell=ET.SubElement(row,'{'+banks.NS['s']+'}c',r=chr(65+i)+str(n),t='inlineStr')
                            ET.SubElement(ET.SubElement(cell,'{'+banks.NS['s']+'}is'),'{'+banks.NS['s']+'}t').text=value
                    if headers is not None:
                        labels=list(headers)+['']*(6-len(headers))
                        for i,label in enumerate(labels):
                            cell=root.find(f'.//s:c[@r="{chr(65+i)}1"]',banks.NS)
                            cell.find('s:is/s:t',banks.NS).text=label
                    if mutate:mutate(root)
                    raw=ET.tostring(root)
                dst.writestr(name,raw)
        return base64.b64encode(output.getvalue()).decode()

    def row(self,card='0012345678901234567'):
        return [self.employee['id'],self.employee['name'],'测试银行',card,self.employee['name'],'测试支行']

    def save(self,kind,b,role='管理员'):
        return banks.save(self.c,kind,b,role,fixture.erp.now,fixture.erp.audit)

    def test_preview_commit_exact_text_and_retry(self):
        file=self.workbook([self.row()]);p=self.save('employee-bank-preview',{'file':file})
        self.assertTrue(p['ok']);self.assertIsNone(banks.bank(self.c,self.employee['id']))
        body={'file':file,'token':p['token'],'request_key':str(uuid.uuid4())}
        result=self.save('employee-bank-import',body);self.assertEqual(result,{'saved':1})
        self.assertEqual(self.save('employee-bank-import',body),result)
        self.assertEqual(banks.bank(self.c,self.employee['id'])['bank_card'],'0012345678901234567')
        after=self.c.execute("SELECT after_json FROM audit WHERE action='维护员工银行卡' ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertNotIn('0012345678901234567',after)
        self.assertIn('4567',after)

    def test_errors_are_atomic_duplicate_identity_and_card(self):
        other=fm.save(self.c,'employee',{'request_key':str(uuid.uuid4()),'name':'另一员工','group_id':'G-TOFU','active':True},'管理员',fixture.erp.now,fixture.erp.audit)
        file=self.workbook([self.row(),[other['id'],'姓名不符','测试银行','1234567890123456','另一员工','']])
        p=banks.preview(self.c,file);self.assertFalse(p['ok']);self.assertEqual(len(p['errors']),1)
        with self.assertRaises(ValueError):self.save('employee-bank-import',{'file':file,'token':p['token'],'request_key':str(uuid.uuid4())})
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM employee_bank_accounts').fetchone()[0],0)
        self.assertFalse(banks.preview(self.c,self.workbook([self.row(),self.row()]))['ok'])
        self.assertFalse(banks.preview(self.c,self.workbook([self.row(),[other['id'],other['name'],*self.row()[2:]]]))['ok'])

    def test_name_only_simple_header_and_optional_bank(self):
        name=self.employee['name'];card='6222021234567890123'
        file=self.workbook([[name,card]],headers=('姓名','卡号'))
        p=self.save('employee-bank-preview',{'file':file})
        self.assertTrue(p['ok'],p)
        self.assertEqual(p['rows'][0]['employee_id'],self.employee['id'])
        self.assertEqual(p['rows'][0]['account_name'],name)
        self.assertEqual(p['rows'][0]['bank_name'],'')
        result=self.save('employee-bank-import',{'file':file,'token':p['token'],'request_key':str(uuid.uuid4())})
        self.assertEqual(result,{'saved':1})
        saved=banks.bank(self.c,self.employee['id'])
        self.assertEqual(saved['bank_card'],card)
        self.assertEqual(saved['account_name'],name)
        self.assertEqual(saved['bank_name'],'')
        reversed_file=self.workbook([[card,name]],headers=('卡号','姓名'))
        self.assertTrue(banks.preview(self.c,reversed_file)['ok'])
        template_file=self.workbook([['',name,'',card,'','']])
        template_preview=banks.preview(self.c,template_file)
        self.assertTrue(template_preview['ok'],template_preview)
        self.assertEqual(template_preview['rows'][0]['employee_id'],self.employee['id'])
        self.assertEqual(template_preview['rows'][0]['bank_name'],'')

    def test_duplicate_name_requires_employee_id(self):
        name=self.employee['name'];card='6222021234567890456'
        other=fm.save(self.c,'employee',{'request_key':str(uuid.uuid4()),'name':name,'group_id':'G-TOFU','active':True},'管理员',fixture.erp.now,fixture.erp.audit)
        file=self.workbook([[name,card]],headers=('姓名','卡号'))
        p=banks.preview(self.c,file)
        self.assertFalse(p['ok'])
        self.assertIn('多名员工',p['errors'][0]['message'])
        with_id=self.workbook([[self.employee['id'],name,'',card,'','']])
        p2=banks.preview(self.c,with_id)
        self.assertTrue(p2['ok'],p2)
        self.assertEqual(p2['rows'][0]['employee_id'],self.employee['id'])
        self.assertNotEqual(other['id'],self.employee['id'])

    def test_stale_preview_cannot_overwrite(self):
        file=self.workbook([self.row()]);p=banks.preview(self.c,file)
        self.save('employee-bank',{'employee_id':self.employee['id'],'version':0,'request_key':str(uuid.uuid4()),'bank_name':'其他测试行','bank_card':'998877665544332211','account_name':'测试员工'})
        with self.assertRaisesRegex(ValueError,'重新预览'):self.save('employee-bank-import',{'file':file,'token':p['token'],'request_key':str(uuid.uuid4())})
        self.assertEqual(banks.bank(self.c,self.employee['id'])['bank_card'],'998877665544332211')

    def test_numeric_card_and_formula_rejected(self):
        def numeric(root):
            cell=root.find('.//s:c[@r="D2"]',banks.NS);cell.clear();cell.set('r','D2');ET.SubElement(cell,'{'+banks.NS['s']+'}v').text='12345678901234567'
        with self.assertRaisesRegex(ValueError,'数值'):banks.preview(self.c,self.workbook([self.row()],numeric))
        def formula(root):ET.SubElement(root.find('.//s:c[@r="D2"]',banks.NS),'{'+banks.NS['s']+'}f').text='1+1'
        with self.assertRaisesRegex(ValueError,'公式'):banks.preview(self.c,self.workbook([self.row()],formula))

    def test_permission_conflict_validation_and_template(self):
        for role in ('库管','厂长','出纳'):
            with self.assertRaises(ValueError):self.save('employee-bank-preview',{'file':self.workbook([self.row()])},role)
        self.assertFalse(banks.preview(self.c,self.workbook([[*self.row()[:2],'','','','']]))['ok'])
        with self.assertRaises(ValueError):banks.normalize({'bank_card':1234567890123456})
        with self.assertRaises(ValueError):banks.normalize({'bank_card':'1.23456789E+18'})
        self.assertEqual(banks.read_xlsx(base64.b64encode(banks.template(self.c)).decode())[0][1][:2],self.row()[:2])


if __name__=='__main__':unittest.main()
