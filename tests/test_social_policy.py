import json
import unittest
import uuid
import payroll
import social_policy
import test_payroll as fixture

erp=fixture.erp


class SocialPolicyTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown
    save=fixture.PayrollTests.save
    sheet=fixture.PayrollTests.sheet

    def policy(self,month='2020-09',base='100',adopt=None,**extra):
        body={'version':social_policy.catalog(self.c)['version'],'request_key':str(uuid.uuid4()),'effective_month':month,'social_base':base,'social_company_rate':'20','social_personal_rate':'8','adopt_employee_ids':adopt or [],**extra}
        return social_policy.save(self.c,body,'管理员',erp.now,erp.audit)

    def profile(self,**extra):
        old=next(p for p in payroll.records(self.c) if p['kind']=='profile' and p['employee_id']==self.employee['id'])
        return self.save('wage-profile',{'employee_id':self.employee['id'],'version':old['version'],'monthly_salary':'3000',**extra})

    def test_defaults_follow_policy_personal_override_and_restore(self):
        self.policy()
        r=payroll.report(self.c,'2020-09');self.assertEqual(r['rows'][0]['social_company_cents'],2000)
        self.profile(social_policy_mode='override',social_base='50',social_company_rate='10',social_personal_rate='2')
        self.policy(base='200')
        self.assertEqual(payroll.report(self.c,'2020-09')['rows'][0]['social_company_cents'],500)
        self.profile(social_policy_mode='inherit',month='2020-09')
        self.assertEqual(payroll.report(self.c,'2020-09')['rows'][0]['social_company_cents'],4000)

    def test_draft_stale_and_confirmed_snapshot_and_payments_unchanged(self):
        self.policy();draft=self.sheet('draft')
        self.policy(base='110')
        self.assertTrue(payroll.report(self.c,'2020-09')['stale'])
        sheet=self.sheet(version=draft['version'])
        frozen=payroll.report(self.c,'2020-09')['rows']
        self.policy(month='2020-10',base='120')
        self.assertEqual(payroll.report(self.c,'2020-09')['rows'],frozen)
        self.assertFalse(payroll.report(self.c,'2020-09')['stale'])
        with self.assertRaisesRegex(ValueError,'晚于'):self.policy(base='90')
        self.assertEqual(sheet['rows'][0]['social_company_cents'],2200)

    def test_legacy_settings_preserved_and_selected_people_adopt_only_from_month(self):
        self.profile(social_base='50',social_company_rate='10',social_personal_rate='2')
        self.policy(month='2020-09')
        self.assertEqual(payroll.report(self.c,'2020-09')['rows'][0]['social_company_cents'],500)
        self.policy(month='2021-01',base='120',adopt=[self.employee['id']])
        old=next(r for r in payroll.records(self.c) if r['kind']=='profile')
        self.assertEqual(old['social_policy_from_month'],'2021-01')
        self.assertEqual(payroll.report(self.c,'2020-09')['rows'][0]['social_company_cents'],500)
        self.assertEqual(social_policy.resolve(old,'2021-01',social_policy.catalog(self.c))['social_base_cents'],12000)

    def test_personal_restore_following_is_month_bounded(self):
        self.profile(social_base='50',social_company_rate='10',social_personal_rate='2')
        self.policy(month='2020-09',base='100')
        self.profile(social_policy_mode='inherit',month='2021-01')
        self.assertEqual(payroll.report(self.c,'2020-09')['rows'][0]['social_company_cents'],500)
        saved=next(p for p in payroll.records(self.c) if p['kind']=='profile')
        self.assertEqual(social_policy.resolve(saved,'2021-01',social_policy.catalog(self.c))['social_base_cents'],10000)

    def test_versions_retry_readonly_and_bounds(self):
        before=self.c.total_changes;self.assertEqual(social_policy.report(self.c,'2020-09')['version'],0);self.assertEqual(self.c.total_changes,before)
        body={'version':0,'request_key':'policy-key','effective_month':'2020-09','social_base':'100','social_company_rate':'20','social_personal_rate':'8'}
        result=social_policy.save(self.c,body,'管理员',erp.now,erp.audit)
        self.assertEqual(social_policy.save(self.c,body,'管理员',erp.now,erp.audit),result)
        with self.assertRaises(ValueError):social_policy.save(self.c,{**body,'request_key':'stale'},'管理员',erp.now,erp.audit)
        for changes in ({'social_base':'-1'},{'social_company_rate':'NaN'},{'social_personal_rate':'100.00001'},{'adopt_employee_ids':['no-such-person']},{'effective_month':'bad'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.policy(**changes)
