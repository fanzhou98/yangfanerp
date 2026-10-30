"""车间余料盘点结转实耗；转加工材料成本按投入比例从来源产品结转。"""
import unittest,uuid
from decimal import Decimal
import test_production_daily as fixture
import product_profit
import resources_costs as rc

erp=fixture.erp
class WorkshopTransferTests(unittest.TestCase):
    setUp=fixture.DailyFactoryTests.setUp
    tearDown=fixture.DailyFactoryTests.tearDown
    def receipt(self,qty='100',amount='4000',material_id='A-GYPSUM'):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':material_id,'business_date':'2026-10-20','kind':'receipt','qty':qty,'amount':amount,'warehouse_id':'WH-COMMON','note':'测试入库','handler':'会计'},'管理员')
    def issue(self,qty='10',material_id='A-GYPSUM',pids=('P001','P002')):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':material_id,'business_date':'2026-10-20','kind':'consume','qty':qty,'warehouse_id':'WH-COMMON','note':'车间领用','handler':'厂长','product_ids':list(pids),'coverage_start':'2026-10-20','coverage_end':'2026-10-20'},'厂长')
    def count(self,qty,**extra):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).workshop_count({'request_key':str(uuid.uuid4()),'month':'2026-10','material_id':'A-GYPSUM','qty_close':qty,'note':'月末盘点','version':0,**extra},'厂长')
    def report(self):
        with erp.connect() as c:return product_profit.month(c,'2026-10')
    def order(self):
        o=erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-18','batch':'跨零点批次','note':'测试','lines':[{'product_id':'P001','ordered_qty':'100','actual_qty':'100','price':'3.333','driver':[{'gross':'110','count':'50','tare':'1.8'}],'customer':[{'gross':'219','count':'100','tare':'1.8'}]}]},'库管')
        o=erp.mutate('settle',{'version':o['version'],'mode':'customer'},'会计',o['id'])
        return erp.mutate('review',{'version':o['version'],'evidence_checked':True},'出纳',o['id'])
    def batch(self,input_kg='10',net_kg='9',business_date='2026-10-21'):
        payload={'id':'PB-'+uuid.uuid4().hex[:8],'business_date':business_date,'batch':'转加工','product_id':'P001','input_kg':input_kg,'outputs':[{'product_id':'P004','product_name':'素鸡','net_kg':net_kg}],'note':'测试转加工','voided':False}
        with erp.connect(True) as c:
            c.execute('INSERT INTO processing_batches(id,payload) VALUES(?,?)',(payload['id'],rc.dump(payload)))
        return payload
    def period(self, state, version=0):
        with erp.connect(True) as c:
            return rc.Operations(c, erp.now, erp.audit).period({'month': '2026-10', 'state': state, 'version': version, 'note': '月末结账'}, '会计')

    def test_month_end_count_gates_period_close(self):
        # 盘点实耗物料没收口就结账，成本会按未盘点口径落账，属于错账入口。
        with erp.connect(True) as c:
            __import__('material_consumption').save_settings(c, 'A-GYPSUM', {'cost_mode': 'count', 'cost_from': '2026-10'})
        self.receipt('100', '400'); self.issue('10')
        with self.assertRaisesRegex(ValueError, '尚未完成月末盘点'):
            self.period('closed')
        self.count('4')
        closed = self.period('closed')
        self.assertEqual(closed['state'], 'closed')

    def test_workshop_report_and_cost_scaling(self):
        self.receipt('100','400');self.issue('10')
        with erp.connect() as c:
            r=rc.workshop_report(c,'2026-10');row=r['rows'][0]
            self.assertEqual(row['issue_cents'],4000);self.assertEqual(row['qty_in'],'10')
            self.assertFalse(row['counted'])
        self.count('4')
        with erp.connect() as c:
            r=rc.workshop_report(c,'2026-10');row=r['rows'][0]
            self.assertEqual(row['counted'],True);self.assertEqual(row['qty_close'],'4')
            self.assertEqual(row['closing_cents'],1600);self.assertEqual(row['actual_cents'],2400)
            self.assertEqual(rc.workshop_ratios(c,'2026-10')['A-GYPSUM'],Decimal('0.6'))
        rep=self.report();rows={x['product_id']:x for x in rep['rows']}
        self.assertEqual(rep['costs']['workshop_adjust_cents'],-1600)
        self.assertEqual(rows['P001']['scope_material_cents'],1200);self.assertEqual(rows['P002']['scope_material_cents'],1200)
    def test_workshop_count_guards_and_version(self):
        self.receipt('100','400');self.issue('10')
        with self.assertRaisesRegex(ValueError,'大豆'):
            with erp.connect(True) as c:rc.Operations(c,erp.now,erp.audit).workshop_count({'month':'2026-10','material_id':'RM-SOY','qty_close':'1','version':0},'厂长')
        self.count('4')
        with self.assertRaisesRegex(ValueError,'刷新'):
            with erp.connect(True) as c:rc.Operations(c,erp.now,erp.audit).workshop_count({'month':'2026-10','material_id':'A-GYPSUM','qty_close':'3','version':0},'厂长')
    def test_transfer_moves_material_cost_between_products(self):
        self.receipt('100','400');self.issue('10',pids=('P001',));self.order();self.batch()
        rep=self.report();rows={x['product_id']:x for x in rep['rows']}
        self.assertEqual(len(rep['transfers']),1)
        t=rep['transfers'][0]
        self.assertEqual(t['source_product_id'],'P001');self.assertGreater(t['amount_cents'],0)
        self.assertEqual(t['amount_cents'],rows['P001']['transfer_out_cents'])
        self.assertEqual(rows['P004']['transfer_in_cents'],t['amount_cents'])
        self.assertEqual(sum(r['transfer_in_cents'] for r in rep['rows']),sum(r['transfer_out_cents'] for r in rep['rows']))
        self.assertTrue(any('转加工' in g['field'] for g in rep['gaps']))
        self.assertEqual(rep['total']['direct_cents'],4000)
    def test_transfer_without_outputs_is_skipped(self):
        self.receipt('100','400');self.issue('10',pids=('P001',));self.order()
        payload={'id':'PB-'+uuid.uuid4().hex[:8],'business_date':'2026-10-21','product_id':'P001','input_kg':'10','outputs':[],'voided':False}
        with erp.connect(True) as c:c.execute('INSERT INTO processing_batches(id,payload) VALUES(?,?)',(payload['id'],rc.dump(payload)))
        rep=self.report()
        self.assertEqual(rep['transfers'],[])
        self.assertFalse(any('缺少来源产品结算公斤' in g['field'] for g in rep['gaps']))
