"""物料属性、领用顺序与分期摊销：按月结转、提前摊完、默认承担产品。"""
import unittest,uuid
import test_production_daily as fixture
import resources_costs as rc
import material_allocation as ma
import product_profit

erp=fixture.erp
class MaterialAmortizationTests(unittest.TestCase):
    setUp=fixture.DailyFactoryTests.setUp
    tearDown=fixture.DailyFactoryTests.tearDown
    def item(self,body,role='管理员'):
        with erp.connect(True) as c:return rc.Operations(c,erp.now,erp.audit).item({'request_key':str(uuid.uuid4()),**body},role)
    def material(self,material_id,kind,qty,amount='0',**extra):
        with erp.connect(True) as c:
            body={'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':material_id,'business_date':'2026-10-20','kind':kind,'qty':qty,'warehouse_id':'WH-COMMON','note':'测试','handler':'厂长',**extra}
            if kind in ('receipt','opening'):body.update(amount=amount,handler='会计')
            return rc.Operations(c,erp.now,erp.audit).material(body,'管理员')
    def test_item_keeps_default_products_pinned_and_months(self):
        item=self.item({'name':'测试耗材布','category':'耗材','unit':'公斤','reorder_qty':'0','active':True,'default_product_ids':['P001','P002'],'pinned':True,'amortize_months':6})
        self.assertEqual(sorted(item['default_product_ids']),['P001','P002'])
        self.assertEqual(item['pinned'],1);self.assertEqual(item['amortize_months'],6)
        with self.assertRaisesRegex(ValueError,'默认承担产品不存在'):
            self.item({'name':'错产品耗材','category':'耗材','unit':'公斤','reorder_qty':'0','active':True,'default_product_ids':['NOPE']})
    def test_item_order_and_pinned_marks(self):
        self.item({'name':'耗材乙','category':'耗材','unit':'公斤','reorder_qty':'0','active':True})
        with erp.connect(True) as c:
            items=[r[0] for r in c.execute("SELECT id FROM material_items WHERE category='辅料' ORDER BY sort_order,id")][:3]
            rc.Operations(c,erp.now,erp.audit).item_order({'request_key':str(uuid.uuid4()),'ids':list(reversed(items)),'pinned':[items[0]]},'管理员')
            marks={r[0]:r[1] for r in c.execute("SELECT id,pinned FROM material_items WHERE id IN (?,?,?)",tuple(items))}
            orders=[r[0] for r in c.execute('SELECT id FROM material_items ORDER BY sort_order')]
        self.assertEqual(marks[items[0]],1);self.assertEqual(marks[items[1]],0)
        self.assertEqual(orders[:3],list(reversed(items)))
    def test_three_month_allocation_only_recognizes_share(self):
        self.material('A-GYPSUM','receipt','30',amount='300')
        entry=self.material('A-GYPSUM','consume','30',product_ids=['P001','P002'],coverage_start='2026-10-20',coverage_end='2026-10-20',amortize_months=3)
        self.assertEqual(entry['amortize_months'],3)
        with erp.connect() as c:
            schedules=rc.amortizations(c);self.assertEqual(len(schedules),1)
            report=product_profit.month(c,'2026-10')
            total=sum(int(row.get('amortized_cents') or 0) for row in report['rows'])
            self.assertEqual(total,10000)
            self.assertEqual(report['costs']['amortized_cents'],10000)
            detail=next(item for item in report['material_allocations'] if item.get('months')==3)
            self.assertEqual(detail['amount_cents'],30000);self.assertEqual(detail['month_cents'],10000)
        with erp.connect() as c:
            november=product_profit.month(c,'2026-11')
            self.assertEqual(sum(int(row.get('amortized_cents') or 0) for row in november['rows']),10000)
        with erp.connect(True) as c:
            sid=rc.amortizations(c)[0]['id']
            rc.Operations(c,erp.now,erp.audit).amortize_close({'request_key':str(uuid.uuid4()),'id':sid,'month':'2026-11'},'会计')
        with erp.connect() as c:
            november=product_profit.month(c,'2026-11')
            self.assertEqual(sum(int(row.get('amortized_cents') or 0) for row in november['rows']),20000)
            december=product_profit.month(c,'2026-12')
            self.assertEqual(sum(int(row.get('amortized_cents') or 0) for row in december['rows']),0)
    def test_amortization_rejects_bad_months(self):
        self.material('A-GYPSUM','receipt','5',amount='50')
        with self.assertRaisesRegex(ValueError,'2—24'):
            self.material('A-GYPSUM','consume','1',amortize_months=25)
