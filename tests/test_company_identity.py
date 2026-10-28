import json
import unittest
import uuid
import company
import payroll
import statements
import test_payroll as fixture


class CompanyIdentityTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    sheet=fixture.PayrollTests.sheet

    def update(self,**values):
        body={'request_key':str(uuid.uuid4()),'version':company.current(self.c)['version'],'name':'测试公司甲','address':'合成测试地址','phone':'000-TEST','tax_id':'TEST-IDENTITY',**values}
        return company.save(self.c,body,'管理员',fixture.erp.now,fixture.erp.audit)

    def test_frozen_payroll_and_payment_have_their_own_issuer(self):
        self.update();sheet=self.sheet();self.update(name='测试公司乙')
        report=payroll.report(self.c,'2020-09')
        self.assertEqual(report['company']['name'],'测试公司甲');self.assertFalse(report['company_legacy'])
        self.assertIn('测试公司甲',payroll.print_html(report,{},True))
        payment=self.save('wage-pay',{'employee_id':self.employee['id'],'month':'2020-09','version':sheet['version'],'paid_cents':0,'amount':'10','method':'cash','business_date':'2020-10-01','handler':'测试','reference':'测试付款'})
        self.assertIn('测试公司乙',payroll.slip_html(payroll.report(self.c,'2020-09'),self.employee['id'],payment['id']))
        stored=json.loads(self.c.execute('SELECT payload FROM payroll_records WHERE id=?',(sheet['id'],)).fetchone()[0]);self.assertEqual(stored['company']['name'],'测试公司甲')

    def test_permissions_version_retry_escaping(self):
        body={'version':0,'name':'测试<&公司','request_key':'company-test'}
        with self.assertRaises(ValueError):company.save(self.c,body,'会计',fixture.erp.now,fixture.erp.audit)
        record=company.save(self.c,body,'管理员',fixture.erp.now,fixture.erp.audit)
        self.assertEqual(company.save(self.c,body,'管理员',fixture.erp.now,fixture.erp.audit),record)
        self.assertIn('测试&lt;&amp;公司',company.header_html(record))
        with self.assertRaises(ValueError):company.save(self.c,{**body,'request_key':'stale'},'管理员',fixture.erp.now,fixture.erp.audit)

    def test_company_change_invalidates_statement_preview(self):
        cid=self.c.execute('SELECT id FROM customers LIMIT 1').fetchone()[0]
        first=statements.snapshot(self.c,cid,'2020-09-02',fixture.erp.now())
        self.update();second=statements.snapshot(self.c,cid,'2020-09-02',fixture.erp.now())
        self.assertNotEqual(first['source_fingerprint'],second['source_fingerprint'])
        self.assertEqual(second['issuer_profile']['name'],'测试公司甲')


if __name__=='__main__':unittest.main()
