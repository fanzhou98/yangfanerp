import unittest,uuid,json
import test_expense_accrual as fixture
import resources_costs as rc,cost_allocation as ca,expense_close as close,expense_estimates as es,expense_coverage as coverage,reporting
class IrregularExpenseCloseTests(unittest.TestCase):
    setUp=fixture.ExpenseAccrualTests.setUp
    tearDown=fixture.ExpenseAccrualTests.tearDown
    def bill(self,start='2026-08-31',end='2026-09-26',amount='260',registered='2026-09-26',**extra):
        b={'request_key':str(uuid.uuid4()),'business_date':registered,'category':'water','amount':amount,'handler':'会计','note':'实际水费账单','partner':'水务公司','service_account':'水表A','accrual_method':'service_days','service_start':start,'service_end':end,'irregular_periodic':True,'irregular_category_version':next(p['version'] for p in ca.categories(self.c) if p['id']=='water'),**extra}
        p=coverage.preview(self.c,b);b['estimate_versions']=[{'id':r['id'],'version':r['version']} for r in p['estimate_candidates']];return self.op.expense(b,'管理员')
    def finish(self,month):
        p=close.preview(self.c,month);old=self.c.execute('SELECT version FROM resource_periods WHERE month=?',(month,)).fetchone()
        return self.op.period({'month':month,'state':'closed','version':old[0] if old else 0,'note':'按项目核对区间后结账','close_fingerprint':p['fingerprint']},'管理员')
    def cost(self,month):return reporting.expense_summary(self.c,month)['total_cents']
    def test_month_closing_auto_completes_tail_in_same_item_without_payable(self):
        bill=self.bill();category=next(p for p in ca.categories(self.c) if p['id']=='water');self.assertTrue(category['irregular_periodic'])
        p=close.preview(self.c,'2026-09');r=next(p for p in p['rows'] if p['category']=='water');self.assertEqual(r['actual_days'],26);self.assertEqual(r['gap_days'],4);self.assertEqual(r['supplement_cents'],4000);self.assertEqual(r['mean_source'],'month_actual')
        period=self.finish('2026-09');self.assertEqual(len(period['automatic_estimate_ids']),1);self.assertEqual(self.cost('2026-09'),30000);self.assertEqual(len(rc.expense_projection(self.c)),1);self.assertEqual(rc.expense_projection(self.c)[0]['outstanding_cents'],26000)
        again=close.preview(self.c,'2026-09');self.assertEqual(again['supplement_cents'],0);self.assertEqual(again['rows'][0]['existing_intervals'][0]['start'],'2026-09-27')
    def test_closed_month_unchanged_next_actual_has_full_payable_and_current_adjustment(self):
        self.bill();self.finish('2026-09');frozen=self.c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0]
        next_bill=self.bill('2026-09-26','2026-10-24','336','2026-10-24');self.assertEqual(next_bill['amount_cents'],33600);self.assertEqual(next_bill['accruals'],[{'period':'2026-09','amount_cents':4000},{'period':'2026-10','amount_cents':29600}]);self.assertEqual(next_bill['registration_adjustment_cents'],800)
        self.assertEqual(self.cost('2026-09'),30000);self.assertEqual(self.cost('2026-10'),29600);self.assertEqual(frozen,self.c.execute("SELECT payload FROM resource_periods WHERE month='2026-09'").fetchone()[0]);self.assertEqual(es.report(self.c,'2026-09')['estimated_cents'],0)
        projected=next(e for e in rc.expense_projection(self.c) if e['id']==next_bill['id']);self.assertEqual(projected['outstanding_cents'],33600)
        p=close.preview(self.c,'2026-10');r=next(r for r in p['rows'] if r['category']=='water');self.assertEqual(r['mean_numerator_cents'],28800);self.assertEqual(r['mean_denominator_days'],24);self.assertEqual(r['supplement_cents'],8400)
        self.finish('2026-10');self.assertEqual(self.cost('2026-10'),38000)
        third=self.bill('2026-10-24','2026-11-24','403','2026-11-24');self.assertEqual(third['registration_adjustment_cents'],700);self.assertEqual(self.cost('2026-10'),38000);self.assertEqual(self.cost('2026-11'),31900)
    def test_negative_difference_and_registration_month_without_service_days(self):
        self.bill();self.finish('2026-09');bill=self.bill('2026-09-26','2026-09-30','20','2026-10-05')
        self.assertEqual(bill['accruals'],[{'period':'2026-09','amount_cents':4000},{'period':'2026-10','amount_cents':-2000}]);self.assertEqual(self.cost('2026-09'),30000);self.assertEqual(self.cost('2026-10'),-2000);self.assertEqual(bill['amount_cents'],2000)
        self.assertEqual(next(e for e in rc.expense_projection(self.c) if e['id']==bill['id'])['outstanding_cents'],2000)
    def test_current_month_no_actual_falls_back_to_latest_actual_invoice(self):
        source=self.bill();self.finish('2026-09');p=close.preview(self.c,'2026-10');r=next(r for r in p['rows'] if r['category']=='water');self.assertEqual(r['mean_source'],'latest_invoice');self.assertEqual(r['source_bills'][0]['id'],source['id']);self.assertEqual(r['supplement_cents'],31000)
    def test_weighted_mean_missing_evidence_and_stale_close_preview(self):
        self.bill('2026-08-31','2026-09-05','100');self.bill('2026-09-05','2026-09-20','150');p=close.preview(self.c,'2026-09');r=next(r for r in p['rows'] if r['category']=='water');self.assertEqual(r['mean_numerator_cents'],25000);self.assertEqual(r['mean_denominator_days'],20);self.assertEqual(r['supplement_cents'],12500)
        self.bill('2026-09-20','2026-09-21','10')
        with self.assertRaisesRegex(ValueError,'已变化'):self.op.period({'month':'2026-09','version':0,'state':'closed','note':'旧预览','close_fingerprint':p['fingerprint']},'管理员')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM expense_estimates').fetchone()[0],0);self.assertIsNone(self.c.execute("SELECT 1 FROM resource_periods WHERE month='2026-09'").fetchone())
    def test_unknown_mean_requires_reason_not_zero_and_flag_can_be_set_in_category(self):
        category=next(p for p in ca.categories(self.c) if p['id']=='water');self.op.expense_category({**category,'irregular_periodic':True},'管理员');p=close.preview(self.c,'2026-09');self.assertTrue(p['errors']);r=next(r for r in p['rows'] if r['category']=='water')
        with self.assertRaisesRegex(ValueError,'缺少'):self.finish('2026-09')
        result=self.op.period({'month':'2026-09','state':'closed','version':0,'note':'本月未启用该水表','close_fingerprint':p['fingerprint'],'exclude_streams':[{'stream_id':r['stream_id'],'reason':'本月不适用'}]},'管理员');self.assertEqual(result['automatic_estimate_ids'],[])
    def test_zero_cent_auto_supplement_preserves_coverage_and_frozen_guard(self):
        self.bill('2026-08-31','2026-09-29','0.01');self.finish('2026-09');estimate=json.loads(self.c.execute('SELECT payload FROM expense_estimates').fetchone()[0]);self.assertEqual(estimate['amount_cents'],0);self.assertTrue(estimate['close_source']);self.assertEqual(self.cost('2026-09'),1)
        with self.assertRaisesRegex(ValueError,'已结账'):self.bill('2026-08-31','2026-09-01','10','2026-10-01',service_account='另一水表')

    def test_reopen_reclose_keeps_partial_remaining_evidence(self):
        self.bill();self.finish('2026-09')
        self.bill('2026-09-26','2026-09-28','24','2026-10-01')
        self.op.period({'month':'2026-09','state':'open','version':1,'note':'复核后重开'},'管理员')
        self.finish('2026-09')
        bill=self.bill('2026-09-28','2026-10-24','312','2026-10-24')
        self.assertEqual(bill['registration_adjustment_cents'],400)
        self.assertEqual(self.cost('2026-09'),30000)
    def test_difference_uses_registration_month_not_coverage_end_month(self):
        self.bill();self.finish('2026-09')
        bill=self.bill('2026-09-26','2026-10-24','336','2026-11-05')
        self.assertEqual(bill['accruals'],[{'period':'2026-09','amount_cents':4000},{'period':'2026-10','amount_cents':28800},{'period':'2026-11','amount_cents':800}])
        self.assertEqual(bill['amount_cents'],33600)
