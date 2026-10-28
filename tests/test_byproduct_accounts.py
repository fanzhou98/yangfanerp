import json
import unittest
import uuid
from decimal import Decimal

import test_workflow as fixture
import byproduct_accounts as ba
import resources_costs as rc
import migrations

erp=fixture.erp


class ByproductAccountsTests(unittest.TestCase):
    setUp=fixture.WorkflowTests.setUp
    tearDown=fixture.WorkflowTests.tearDown

    def client(self,name='豆渣客户甲'):
        return erp.master({'kind':'customer','create':True,'name':name,'legal_name':name+'养殖场','phone':'123456789','route':'豆渣自取','delivery_method':'pickup','business_kind':'byproduct'},'管理员')['id']

    def sale(self,cid,day='2026-10-20',qty='100',price='0.5',received='0'):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).byproduct({'customer_id':cid,'business_date':day,'qty':qty,'price':price,'received':received,'handler':'会计','note':'结算','request_key':str(uuid.uuid4())},'管理员')

    def receipt(self,r,amount='10'):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).receive_byproduct({'id':r['id'],'version':r['version'],'business_date':'2026-10-31','amount':amount,'note':'转账到账'},'管理员')

    def preview(self,cid):
        with erp.connect() as c:return ba.snapshot(c,cid,'2026-10',erp.now())

    def body(self,s):
        with erp.connect() as c:op=dict(c.execute("SELECT * FROM operator_users WHERE id='OP-CASHIER'").fetchone())
        return {'request_key':str(uuid.uuid4()),'customer_id':s['customer']['id'],'month':s['month'],'seller_name':'测试豆制品厂','seller_phone':'','buyer_name':s['customer']['legal_name'],'operator_user_id':op['id'],'operator_version':op['version'],'identity_checked':True,'source_fingerprint':s['source_fingerprint'],'note':''}

    def issue(self,b):
        with erp.connect(True) as c:return ba.issue(c,b,'管理员',erp.now,erp.audit)

    def test_customer_identity_required_and_snapshot_names_preserved(self):
        cid=self.client();r=self.sale(cid)
        self.assertEqual(r['customer_id'],cid)
        with self.assertRaisesRegex(ValueError,'豆渣业务'):self.sale('C001')
        with self.assertRaisesRegex(ValueError,'请选择'):self.sale('missing')
        erp.master({'kind':'customer','id':cid,'name':'新客户名称','route':'豆渣自取','business_kind':'both'},'管理员')
        s=self.preview(cid)
        self.assertEqual(s['customer']['name'],'新客户名称')
        self.assertEqual(s['current'][0]['amount_cents'],5000)
        with erp.connect() as c:self.assertEqual(rc.rows(c,'byproduct_sales')[-1]['buyer'],'豆渣客户甲')

    def test_statement_month_history_receipts_and_no_other_customer(self):
        a=self.client();b=self.client('客户乙')
        self.sale(a,'2026-09-20',received='20');self.sale(a,received='10');self.sale(a,'2026-11-20')
        other=self.sale(b,qty='999')
        s=self.preview(a)
        self.assertEqual(len(s['current']),1);self.assertEqual(len(s['history']),1)
        self.assertEqual(s['period_start'],'2026-10-01');self.assertEqual(s['period_end'],'2026-10-31')
        self.assertTrue(all(r['product_name']=='豆渣' for r in s['details']))
        self.assertEqual(len({r['date'] for r in s['details']}),31)
        self.assertEqual(next(r for r in s['details'] if r['date']=='2026-10-01')['status'],'无已入账记录')
        self.assertEqual(s['totals'],{'current_sales_cents':5000,'current_paid_cents':1000,'current_remaining_cents':4000,'history_remaining_cents':3000,'payable_cents':7000})
        self.assertNotIn(other['id'],s['source_sale_ids']);self.assertNotIn('add_kg',json.dumps(s))
        doc=self.issue(self.body(s));csv=ba.statement_csv(doc).decode('utf-8-sig')
        self.assertIn('2026-10-01',csv);self.assertIn('2026-10-31',csv);self.assertIn('出具日期',csv);self.assertIn('历史未收',csv);self.assertIn('70.00',csv);self.assertNotIn('加量',csv)

    def test_daily_details_keep_exact_money_and_archived_amount_after_receipt(self):
        cid=self.client();r=self.sale(cid,qty='3',price='0.335')
        with erp.connect(True) as c:
            r['daily_rows']=[{'date':'2026-10-19','qty':'1','amount_cents':34},{'date':'2026-10-20','qty':'2','amount_cents':67}]
            c.execute('UPDATE byproduct_sales SET payload=? WHERE id=?',(rc.dump(r),r['id']))
        s=self.preview(cid);self.assertEqual(sum(d['amount_cents'] for d in s['details']),101)
        body=self.body(s);doc=self.issue(body);self.assertEqual(self.issue(body)['document_id'],doc['document_id'])
        self.receipt(r,'0.5')
        self.assertEqual(self.preview(cid)['totals']['payable_cents'],51)
        with erp.connect() as c:original=ba.get_document(c,doc['document_id'])
        self.assertEqual(original['totals']['payable_cents'],101)
        self.assertEqual(original['content_hash'],doc['content_hash'])
        with self.assertRaisesRegex(ValueError,'已有变化'):self.issue({**body,'request_key':str(uuid.uuid4())})

    def test_empty_stale_and_unconfirmed_statements_rejected(self):
        cid=self.client();s=self.preview(cid)
        with self.assertRaisesRegex(ValueError,'没有已入账'):self.issue(self.body(s))
        r=self.sale(cid);s=self.preview(cid);b=self.body(s)
        with self.assertRaisesRegex(ValueError,'勾选'):self.issue({**b,'identity_checked':False})
        self.receipt(r)
        with self.assertRaisesRegex(ValueError,'已有变化'):self.issue(b)

    def test_void_marks_existing_statement_and_restore_does_not_revive_it(self):
        cid=self.client();r=self.sale(cid);doc=self.issue(self.body(self.preview(cid)))
        with erp.connect(True) as c:
            ops=rc.Operations(c,erp.now,erp.audit);void=ops.void({'ledger':'byproduct','id':r['id'],'version':r['version'],'reason':'登记有误'},'管理员')
            self.assertTrue(ba.get_document(c,doc['document_id'])['voided'])
            restored=ops.restore({'ledger':'byproduct','id':r['id'],'version':void['version'],'reason':'确认原单有效'},'管理员')
            self.assertTrue(ba.get_document(c,doc['document_id'])['voided'])
        newer=self.issue(self.body(self.preview(cid)))
        with erp.connect() as c:self.assertFalse(ba.get_document(c,newer['document_id']).get('voided',False))

    def test_legacy_migration_is_idempotent_preserves_cents_and_avoids_namesake_merge(self):
        with erp.connect(True) as c:
            name=c.execute("SELECT name FROM customers WHERE id='C001'").fetchone()[0]
            record={'id':'BP-LEGACY','buyer':name,'qty':'12.34','unit':'公斤','price':'0.5','amount_cents':617,'received_cents':123,'business_date':'2026-09-30','version':4}
            c.execute('INSERT INTO byproduct_sales VALUES(?,?,?)',(record['id'],'legacy-key',rc.dump(record)))
            c.execute("INSERT INTO meta VALUES('byproduct_settlement',?)",(rc.dump({'buyer':name,'add_kg':'10','version':2}),))
            c.execute("DELETE FROM schema_migrations WHERE id='059-byproduct-customers'");c.execute('PRAGMA user_version=49')
            migrations.ensure(c)
            stored=next(r for r in rc.rows(c,'byproduct_sales') if r['id']==record['id'])
            self.assertNotEqual(stored['customer_id'],'C001');self.assertEqual(stored['amount_cents'],617);self.assertEqual(stored['received_cents'],123)
            self.assertEqual(stored['qty'],'12.34');self.assertEqual(stored['version'],5)
            count=c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
            migrations.ensure(c)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],count)
            self.assertEqual(rc.byproduct_config(c)['customer_id'],stored['customer_id'])

    def test_receivable_alert_and_owner_total_count_each_record_once(self):
        import production_management as pm,owner_analysis
        cid=self.client();self.sale(cid,received='10')
        with erp.connect() as c:
            alert=next(a for a in pm.ar_alerts(c,'2026-10-31') if a['customer_id']==cid)
            self.assertEqual(alert['outstanding_cents'],4000)
            cash=owner_analysis.accounts(c,'2026-10-31')
            self.assertEqual(cash['byproduct_receivable_cents'],4000)
            self.assertEqual(cash['receivable_cents'],cash['sales_receivable_cents']+4000)
