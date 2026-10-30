import json
import unittest
from unittest.mock import patch
import payroll
import test_payroll as fixture


class PayrollSocialTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    sheet=fixture.PayrollTests.sheet

    def profile(self,**changes):
        old=next(r for r in payroll.records(self.c) if r['kind']=='profile' and r['employee_id']==self.employee['id'])
        return self.save('wage-profile',{'employee_id':self.employee['id'],'version':old['version'],'monthly_salary':'3000','social_base':'100','social_company_rate':'20','social_personal_rate':'8',**changes})

    def test_attendance_then_both_compensations_and_frozen(self):
        profile=self.profile();r=payroll.report(self.c,'2020-09')['rows'][0]
        self.assertEqual(r['attendance_cents'],14795)
        self.assertEqual(r['social_company_cents'],2000)
        self.assertEqual(r['social_personal_cents'],800)
        self.assertEqual(r['monthly_basic_cents'],297200)
        self.assertEqual(r['base_cents'],11995)
        sheet=self.sheet();self.assertEqual(sheet['rows'][0]['net_cents'],12795)
        expense=json.loads(self.c.execute("SELECT payload FROM indirect_expenses WHERE json_extract(payload,'$.payroll_sheet_id')=?",(sheet['id'],)).fetchone()[0])
        self.assertEqual(expense['amount_cents'],12795)
        self.profile(social_base='200',social_company_rate='30')
        frozen=payroll.report(self.c,'2020-09');self.assertEqual(frozen['rows'][0]['social_company_cents'],2000);self.assertFalse(frozen['stale'])
        html=payroll.slip_html(frozen,self.employee['id']);self.assertIn('社保补偿款 · 公司',html);self.assertIn('员工签字',html)
        summary=payroll.print_html(frozen,{},True);self.assertIn('员工签名',summary);self.assertIn('社保补偿款（个人）',summary)

    def test_rounding_and_bounds(self):
        profile={'monthly_cents':300000,'social_base_cents':10001,'social_company_rate':'12.3456','social_personal_rate':'0.005'}
        amounts=payroll.social_amounts(profile);self.assertEqual(amounts['social_company_cents'],1235);self.assertEqual(amounts['social_personal_cents'],1)
        for body in ({'social_company_rate':'101'},{'social_personal_rate':'NaN'},{'social_base':'-1'},{'social_company_rate':'1.12345'},{'social_base':'100000','social_company_rate':'100'}):
            with self.assertRaises(ValueError):self.profile(**body)
        self.profile(social_base='3000',social_company_rate='20',social_personal_rate='8')
        with self.assertRaisesRegex(ValueError,'小于0'):self.sheet()

    def test_legacy_zero_and_history_is_scoped_to_year(self):
        legacy=payroll.report(self.c,'2020-09')
        self.assertEqual(legacy['rows'][0]['base_cents'],14795)
        for i in range(100):
            record={'id':f'OLD-{i}','kind':'payment','month':'2019-01','employee_id':self.employee['id'],'amount_cents':99999}
            self.c.execute('INSERT INTO payroll_records VALUES(?,?,?)',(record['id'],record['id'],json.dumps(record)))
        with patch.object(payroll,'records',side_effect=AssertionError('报表不得读取全历史工资表')):
            result=payroll.report(self.c,'2020-09')
        self.assertEqual(result,legacy)
        self.assertNotIn(self.employee['name'],payroll.print_html(result,{'status':['absent']},True))

    def test_cash_and_transfer_real_payment_not_signature(self):
        import employee_banks
        self.profile();sheet=self.sheet();employee=self.employee['id']
        body={'month':'2020-09','employee_id':employee,'version':sheet['version'],'paid_cents':0,'amount':'10','method':'cash','business_date':'2020-10-01','handler':'测试','reference':'CASH-TEST'}
        payment=self.save('wage-pay',body,role='出纳')
        self.assertEqual(payment['method'],'cash');self.assertEqual(payment['recipient'],{})
        report=payroll.report(self.c,'2020-09');html=payroll.slip_html(report,employee,payment['id'])
        self.assertIn('个人现金工资签收单',html);self.assertIn('本次实发金额',html)
        self.assertEqual(report['rows'][0]['paid_cents'],1000)
        for method in ('cash','bank_transfer'):
            with self.assertRaises(ValueError):self.save('wage-pay',{**body,'paid_cents':0,'method':method},role='出纳')
        employee_banks.save(self.c,'employee-bank',{'employee_id':employee,'request_key':'BANK-TEST','version':0,'bank_name':'测试银行','bank_card':'0012345678901234567','account_name':'测试员工'},'管理员',fixture.erp.now,fixture.erp.audit)
        with self.assertRaisesRegex(ValueError,'银行卡已变化'):self.save('wage-pay',{**body,'paid_cents':1000,'method':'bank_transfer','bank_version':0},role='出纳')
        transfer=self.save('wage-pay',{**body,'paid_cents':1000,'method':'bank_transfer','bank_version':1},role='出纳')
        self.assertEqual(transfer['recipient']['card_tail'],'4567')
        self.assertNotIn('bank_card',transfer['recipient'])
        employee_banks.save(self.c,'employee-bank',{'employee_id':employee,'request_key':'BANK-UPDATED','version':1,'bank_name':'其他测试银行','bank_card':'998877665544332211','account_name':'测试员工'},'管理员',fixture.erp.now,fixture.erp.audit)
        self.assertEqual(payroll.report(self.c,'2020-09')['rows'][0]['bank_card'],'尾号4567')
        self.assertNotIn('0012345678901234567',json.dumps(payroll.report(self.c,'2020-09')))
        audit_value=self.c.execute("SELECT after_json FROM audit WHERE action='工资发放登记' ORDER BY id DESC LIMIT 1").fetchone()[0];self.assertNotIn('0012345678901234567',audit_value)
        report=payroll.report(self.c,'2020-09');self.assertEqual(report['rows'][0]['paid_cents'],2000)
        summary=payroll.print_html(report,{},True);self.assertIn('实发工资',summary);self.assertIn('现金 / 银行转账',summary)


if __name__=='__main__':unittest.main()
