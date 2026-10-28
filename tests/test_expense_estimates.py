import unittest,uuid,json
import test_expense_accrual as fixture
import expense_estimates as estimates,resources_costs as rc,reporting,expense_coverage
class ExpenseEstimateTests(unittest.TestCase):
    setUp=fixture.ExpenseAccrualTests.setUp
    tearDown=fixture.ExpenseAccrualTests.tearDown
    def body(self,start='2026-08-25',end='2026-08-31',amount='60',**extra):return {'request_key':str(uuid.uuid4()),'business_date':'2026-09-30','category':'water','amount':amount,'handler':'合成会计','note':'月底暂估待抄表','partner':'水务公司','service_account':'水表A','accrual_method':'service_days','service_start':start,'service_end':end,**extra}
    def estimate(self,**extra):return estimates.save(self.c,self.body(**extra),'管理员',fixture.erp.now,fixture.erp.audit)
    def actual(self,start='2026-08-25',end='2026-09-26',amount='320',**extra):
        b=self.body(start,end,amount,**extra);r=expense_coverage.preview(self.c,b);b['estimate_versions']=[{'id':p['id'],'version':p['version']} for p in r['estimate_candidates']];return self.op.expense(b,'管理员')
    def total(self,month):return reporting.expense_summary(self.c,month)['total_cents']
    def test_no_payable_actual_offsets_only_covered_days_and_negative_difference(self):
        a=self.estimate();b=self.estimate(start='2026-09-01',end='2026-09-30',amount='290')
        self.assertEqual(rc.expense_projection(self.c),[]);
        category=next(c for c in __import__('cost_allocation').categories(self.c) if c['id']=='water')
        with self.assertRaisesRegex(ValueError,'不能删除'):self.op.expense_category_delete({'id':'water','version':category['version']},'管理员')
        with self.assertRaisesRegex(ValueError,'未核销暂估'):self.op.expense_category({**category,'payment_mode':'noncash'},'管理员')
        self.assertEqual(self.total('2026-08'),6000);self.assertEqual(self.total('2026-09'),29000)
        # September estimate is Sep 2..30 (29 days); actual covers through Sep 26.
        bill=self.actual(amount='300');self.assertEqual(len(bill['estimate_ids']),2);self.assertEqual(bill['estimate_offset_cents'],31000);self.assertEqual(bill['estimate_difference_cents'],-1000)
        self.assertEqual(self.total('2026-08'),5625);self.assertEqual(self.total('2026-09'),28375)
        r=estimates.report(self.c,'2026-09');self.assertEqual(r['estimated_cents'],4000);self.assertEqual(r['actual_cents'],24375);self.assertEqual(r['total_cents'],28375)
        self.assertEqual(json.loads(self.c.execute('SELECT payload FROM expense_estimates WHERE id=?',(a['id'],)).fetchone()[0])['amount_cents'],6000)
        self.assertEqual(rc.expense_projection(self.c)[0]['outstanding_cents'],30000)
        self.op.void({'id':bill['id'],'version':1,'ledger':'expense','reason':'账单误录退回核查'},'管理员');self.assertEqual(self.total('2026-08'),6000);self.assertEqual(self.total('2026-09'),29000)
        self.op.restore({'id':bill['id'],'version':2,'ledger':'expense','reason':'核实后恢复账单'},'管理员');self.assertEqual(self.total('2026-09'),28375)
    def test_partial_interval_then_next_irregular_bill_and_single_payment(self):
        self.estimate(start='2026-09-26',end='2026-09-30',amount='40');self.estimate(start='2026-09-30',end='2026-10-31',amount='310')
        bill=self.actual(start='2026-09-26',end='2026-10-24',amount='280');self.assertEqual(bill['estimate_offset_cents'],28000);self.assertEqual(self.total('2026-09'),4000);self.assertEqual(self.total('2026-10'),31000)
        self.assertEqual(estimates.report(self.c,'2026-10')['estimated_cents'],7000)
        self.op.expense_review({'id':bill['id'],'version':1,'request_key':str(uuid.uuid4()),'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
        self.op.expense_payment({'id':bill['id'],'version':2,'request_key':str(uuid.uuid4()),'business_date':'2026-10-30','amount':'280','method':'银行转账','payee':'水务公司','handler':'出纳','reference':'水费票据','note':'付款'},'管理员');self.assertEqual(rc.expense_projection(self.c)[0]['outstanding_cents'],0);self.assertEqual(self.total('2026-10'),31000)
    def test_stale_preview_overlaps_and_meter_separation(self):
        e=self.estimate();b=self.body('2026-08-25','2026-09-26','320')
        with self.assertRaisesRegex(ValueError,'预览'):self.op.expense(b,'管理员')
        with self.assertRaisesRegex(ValueError,'重叠暂估'):self.estimate()
        self.estimate(service_account='水表B');bill=self.actual();self.assertEqual(len(bill['estimate_ids']),1)
        with self.assertRaisesRegex(ValueError,'重叠实际账单'):self.actual(start='2026-09-01')
        with self.assertRaisesRegex(ValueError,'已有实际账单'):self.estimate(start='2026-09-01',end='2026-09-20')
        with self.assertRaisesRegex(ValueError,'不能改写'):estimates.save(self.c,self.body(id=e['id'],version=1,amount='70'),'管理员',fixture.erp.now,fixture.erp.audit)
    def test_closed_months_atomicity_and_void_remaining(self):
        e=self.estimate();self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-08',1,rc.dump({'month':'2026-08','state':'closed'})))
        with self.assertRaisesRegex(ValueError,'结账'):self.actual()
        self.assertEqual(rc.rows(self.c,'indirect_expenses'),[]);self.assertEqual(self.total('2026-08'),6000)
        with self.assertRaisesRegex(ValueError,'结账'):estimates.save(self.c,{'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'action':'void','reason':'核查撤销'},'管理员',fixture.erp.now,fixture.erp.audit)
        self.c.execute('DELETE FROM resource_periods');self.actual();r=estimates.save(self.c,{'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'action':'void','reason':'核查撤销'},'管理员',fixture.erp.now,fixture.erp.audit);self.assertTrue(r['voided']);self.assertEqual(self.total('2026-08'),6000)
    def test_restore_old_actual_cannot_overlap_replacement_bill(self):
        self.estimate();bill=self.actual()
        self.op.void({'id':bill['id'],'version':1,'ledger':'expense','reason':'误录撤销'},'管理员');self.actual(amount='300')
        with self.assertRaisesRegex(ValueError,'重叠实际账单'):self.op.restore({'id':bill['id'],'version':2,'ledger':'expense','reason':'恢复核查'},'管理员')
    def test_create_cannot_hide_overlaps_using_an_existing_id_and_restore_links_are_checked(self):
        e=self.estimate();bill=self.actual()
        with self.assertRaisesRegex(ValueError,'重叠实际账单'):self.op.expense(self.body('2026-08-25','2026-09-26','320',id=bill['id']),'管理员')
        with self.assertRaisesRegex(ValueError,'保留覆盖日期'):self.op.expense_edit({**self.body(amount='320'), 'id':bill['id'],'version':1,'accrual_method':'months','period':'2026-08'},'管理员')
        self.op.void({'id':bill['id'],'version':1,'ledger':'expense','reason':'误录撤销'},'管理员')
        estimates.save(self.c,{'id':e['id'],'version':1,'request_key':str(uuid.uuid4()),'action':'void','reason':'撤销原暂估'},'管理员',fixture.erp.now,fixture.erp.audit)
        self.estimate()
        with self.assertRaisesRegex(ValueError,'暂估匹配关系已变化'):self.op.restore({'id':bill['id'],'version':2,'ledger':'expense','reason':'恢复旧账单'},'管理员')
    def test_audit_rollback_also_respects_frozen_coverage(self):
        self.estimate();bill=self.actual()
        audit_id=self.c.execute('SELECT MAX(id) FROM audit WHERE entity=?',(bill['id'],)).fetchone()[0]
        self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-08',1,rc.dump({'month':'2026-08','state':'closed'})))
        plan=__import__('audit_rollback').plan(self.c,audit_id);self.assertTrue(any('结账' in b for b in plan['blockers']))
    def test_estimate_idempotency_and_cent_exact_partial_offsets(self):
        body=self.body('2024-02-28','2024-03-02','0.03');e=estimates.save(self.c,body,'管理员',fixture.erp.now,fixture.erp.audit);self.assertEqual(estimates.save(self.c,body,'管理员',fixture.erp.now,fixture.erp.audit),e)
        bill=self.actual(start='2024-02-28',end='2024-03-01',amount='0.02');self.assertEqual(bill['estimate_offset_cents'],2);self.assertEqual(self.total('2024-02'),1);self.assertEqual(self.total('2024-03'),2)
