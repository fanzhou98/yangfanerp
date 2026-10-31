import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import test_workflow as fixture
import inventory
import material_allocation
import resources_costs as rc
import production_daily as daily
import production_management as fm

erp = fixture.erp


class ProcessingFlowTests(unittest.TestCase):
    def setUp(self):
        self.old = erp.DB
        self.temp = tempfile.TemporaryDirectory()
        erp.DB = Path(self.temp.name) / 'processing.db'
        erp.init_db(demo=True)
        self.day = '2026-10-20'
        with erp.connect(True) as c:
            mapping = json.loads(c.execute("SELECT value FROM meta WHERE key='product_main_materials'").fetchone()[0])
            mapping['P005'] = '豆皮'
            mapping['P006'] = '白干'
            c.execute("UPDATE meta SET value=? WHERE key='product_main_materials'", (erp.dumps(mapping),))
            rows = [{'product_id': p['id'], 'existing_qty': '0', 'produced_qty': '0', 'loss_qty': '0', 'loss_reason': '', 'counted_qty': '', 'variance_reason': ''} for p in c.execute('SELECT id FROM products')]
            for row in rows:
                if row['product_id'] == 'P004':
                    row['existing_qty'] = '100'; row['counted_qty'] = '90'
                elif row['product_id'] == 'P003':
                    row['existing_qty'] = '50'; row['counted_qty'] = '45'
                elif row['product_id'] == 'P005':
                    row['counted_qty'] = '8'
                elif row['product_id'] == 'P006':
                    row['counted_qty'] = '3'
            c.execute('INSERT INTO warehouse_plans VALUES(?,?)', (self.day, erp.dumps({'business_date': self.day, 'version': 1, 'stock': rows, 'allocations': [], 'customers': [], 'allocation_state': 'confirmed'})))

    def tearDown(self):
        erp.DB = self.old
        self.temp.cleanup()

    def process(self, source, input_qty, input_kg, output, output_qty, output_kg):
        with erp.connect(True) as c:
            batch = inventory.Operations(c, erp.now, erp.audit).process({
                'business_date': self.day, 'product_id': source, 'input_qty': input_qty, 'input_kg': input_kg,
                'outputs': [{'product_id': output, 'qty': output_qty, 'net_kg': output_kg}],
                'source_lot': '厂内未出厂批次', 'handler': '厂长', 'inspection_note': '已检验可用',
                'origin': 'internal', 'origin_confirmed': True, 'inspection_checked': True,
                'request_key': str(uuid.uuid4()), 'inventory_revision': inventory.revision(c)}, '管理员')
            return batch

    def test_processing_moves_stock_and_separates_soybean_and_processing_yield(self):
        self.process('P004', '10', '9', 'P005', '8', '7.5')
        self.process('P003', '5', '4.5', 'P006', '3', '2.8')
        with erp.connect() as c:
            stock = {p['product_id']: p for p in inventory.stock(c, self.day)['products']}
            self.assertEqual(stock['P004']['processing_input_qty'], '10')
            self.assertEqual(stock['P005']['processing_output_qty'], '8')
            self.assertEqual(stock['P003']['processing_input_qty'], '5')
            self.assertEqual(stock['P006']['processing_output_qty'], '3')
            self.assertEqual(stock['P004']['book_qty'], '90')
            self.assertEqual(stock['P003']['book_qty'], '45')
            self.assertEqual(stock['P005']['book_qty'], '8')
            summary = daily.processing_summary(c, self.day)
            self.assertEqual(len(summary), 2)
            tofu = next(x for x in summary if x['source_product_id'] == 'P004')
            skin = next(x for x in summary if x['source_product_id'] == 'P003')
            self.assertEqual(tofu['yield_kg'], '8.889')
            self.assertEqual(tofu['source_product_name'], '千张（豆皮）')
            self.assertEqual(tofu['outputs'][0]['product_name'], '素鸡')
            self.assertEqual(skin['yield_kg'], '0.622')
            self.assertEqual(skin['outputs'][0]['product_name'], '熏干')
            report = fm.daily_report(c, self.day)
            rows = {p['product_id']: p for p in report['products']}
            self.assertEqual(rows['P005']['main_material'], '豆皮')
            self.assertEqual(rows['P006']['main_material'], '白干')
            self.assertIsNone(rows['P005']['yield_kg_per_kg'])
            self.assertIsNone(rows['P006']['yield_kg_per_kg'])
            self.assertEqual(rows['P005']['calculation_status'], '待核算（转加工来源出品率）')
            self.assertEqual(rows['P006']['calculation_status'], '待核算（转加工来源出品率）')
            self.assertEqual(len(report['processing']), 2)
            self.assertEqual(report['processing'][0]['id'], summary[0]['id'])
            allocation = material_allocation.day_report(c, self.day)
            self.assertFalse(any(a['product_id'] in ('P005', 'P006') for a in allocation['allocations']))

    def test_offcut_input_without_finished_stock_uses_weight_for_yield(self):
        self.process('P004', '0', '9', 'P005', '8', '7.5')
        with erp.connect() as c:
            stock = {p['product_id']: p for p in inventory.stock(c, self.day)['products']}
            self.assertEqual(stock['P004']['processing_input_qty'], '0')
            self.assertEqual(stock['P004']['book_qty'], '100')
            self.assertEqual(stock['P005']['processing_output_qty'], '8')
            summary = daily.processing_summary(c, self.day)[0]
            self.assertEqual(summary['input_qty'], '0')
            self.assertEqual(summary['yield_kg'], '8.889')
            self.assertIsNone(summary['yield_units'])

    def test_output_net_weight_is_required_for_variable_baskets(self):
        with erp.connect(True) as c:
            with self.assertRaisesRegex(ValueError, '产出实称净重'):
                inventory.Operations(c, erp.now, erp.audit).process({'business_date': self.day, 'product_id': 'P003', 'input_kg': '100', 'outputs': [{'product_id': 'P006', 'qty': '8'}], 'origin': 'internal', 'request_key': str(uuid.uuid4()), 'inventory_revision': inventory.revision(c)}, '管理员')

    def test_processing_rules_can_be_saved_and_are_returned(self):
        with erp.connect(True) as c:
            saved = inventory.save_processing_rules(c, {'rules': [{'source_product_id': 'P004', 'output_product_id': 'P005'}, {'source_product_id': 'P003', 'output_product_id': 'P006'}]}, '管理员', erp.now, erp.audit)
            self.assertEqual(saved['version'], 1)
            self.assertEqual(inventory.processing_rules(c), [{'source_product_id': 'P004', 'output_product_id': 'P005'}, {'source_product_id': 'P003', 'output_product_id': 'P006'}])
            with self.assertRaisesRegex(ValueError, '不能相同'):
                inventory.save_processing_rules(c, {'rules': [{'source_product_id': 'P004', 'output_product_id': 'P004'}]}, '管理员', erp.now, erp.audit)

    def test_processing_rules_reject_unlisted_pairs_and_allow_edit_delete(self):
        with erp.connect(True) as c:
            with self.assertRaisesRegex(ValueError, '不能由'):
                inventory.Operations(c, erp.now, erp.audit).process({'business_date': self.day, 'product_id': 'P001', 'input_qty': '1', 'input_kg': '1', 'outputs': [{'product_id': 'P002', 'qty': '1', 'net_kg': '1'}], 'origin': 'internal', 'request_key': str(uuid.uuid4()), 'inventory_revision': inventory.revision(c)}, '管理员')
        batch = self.process('P004', '10', '9', 'P005', '8', '7.5')
        with erp.connect(True) as c:
            updated = inventory.Operations(c, erp.now, erp.audit).process_update({'id': batch['id'], 'version': batch['version'], 'business_date': self.day, 'product_id': 'P004', 'input_qty': '9', 'input_kg': '8.5', 'outputs': [{'product_id': 'P005', 'qty': '7', 'net_kg': '6.5'}]}, '管理员')
            self.assertEqual(updated['version'], 2)
            self.assertEqual(updated['input_kg'], '8.5')
            self.assertEqual(inventory.stock(c, self.day)['products'][3]['processing_input_qty'], '9')
            deleted = inventory.Operations(c, erp.now, erp.audit).process_delete({'id': batch['id'], 'version': updated['version'], 'reason': '测试删除'}, '管理员')
            self.assertTrue(deleted['voided'])
            stock = {p['product_id']: p for p in inventory.stock(c, self.day)['products']}
            self.assertEqual(stock['P004']['processing_input_qty'], '0')
            self.assertEqual(stock['P005']['processing_output_qty'], '0')
            self.assertFalse(any(b['id'] == batch['id'] for b in daily.processing_summary(c, self.day)))

    def test_simple_daily_cost_uses_source_yield_and_net_weight_allocation(self):
        self.process('P004', '10', '9', 'P005', '8', '7.5')
        with erp.connect(True) as c:
            rc.Operations(c, erp.now, erp.audit).expense({'business_date': self.day, 'period': self.day[:7], 'category': 'rent', 'amount': '3', 'request_key': str(uuid.uuid4()), 'handler': '会计', 'note': '本月非专属租金'}, '会计')
            summary = daily.processing_summary(c, self.day, [{'product_id': 'P004', 'yield_kg_per_kg': '2'}], [{'business_date': self.day, 'material_id': 'RM-SOY', 'kind': 'consume', 'qty': '10', 'cost_cents': 5000}])[0]
        self.assertEqual(summary['source_yield'], '2')
        self.assertEqual(summary['soy_input_kg'], '4.5')
        self.assertEqual(summary['soy_average_yuan_per_kg'], '5')
        self.assertEqual(summary['direct_cost_cents'], 2250)
        self.assertEqual(summary['indirect_cost_cents'], 300)
        self.assertEqual(summary['total_cost_cents'], 2550)
        self.assertEqual(summary['cost_status'], '估算')
        self.assertEqual(summary['soy_yield'], '17.778')
        self.assertEqual(summary['outputs'][0]['cost_cents'], 2550)
        self.assertEqual(summary['outputs'][0]['unit_cost_yuan_per_kg'], '0.32')
        with erp.connect() as c:
            missing = daily.processing_summary(c, self.day, [{'product_id': 'P004', 'yield_kg_per_kg': None}], [{'business_date': self.day, 'material_id': 'RM-SOY', 'kind': 'consume', 'qty': '10', 'cost_cents': 5000}])[0]
        self.assertEqual(missing['cost_status'], '待核算')
        self.assertIsNone(missing['direct_cost_cents'])

    def test_daily_and_monthly_cost_allocation_preserve_each_cent(self):
        with erp.connect(True) as c:
            inventory.save_processing_rules(c,{'rules':[{'source_product_id':'P004','output_product_id':pid} for pid in ('P005','P006')]},'管理员',erp.now,erp.audit)
            inventory.Operations(c,erp.now,erp.audit).process({'business_date':self.day,'product_id':'P004','input_kg':'1',
                'outputs':[{'product_id':pid,'qty':'1','net_kg':'10'} for pid in ('P005','P006')],
                'origin':'internal','origin_confirmed':True,'inspection_checked':True,'source_lot':'厂内批次','handler':'厂长','inspection_note':'已检验',
                'request_key':str(uuid.uuid4()),'inventory_revision':inventory.revision(c)},'管理员')
            rc.Operations(c,erp.now,erp.audit).expense({'business_date':self.day,'category':'rent','amount':'0.02','request_key':str(uuid.uuid4()),'handler':'会计','note':'分摊余分核对'},'会计')
            batch=daily.processing_summary(c,self.day,[{'product_id':'P004','yield_kg_per_kg':'1'}],
                [{'business_date':self.day,'material_id':'RM-SOY','kind':'consume','qty':'1','cost_cents':1}])[0]
            self.assertEqual(batch['direct_cost_cents'],1)
            self.assertEqual(batch['indirect_cost_cents'],2)
            self.assertEqual(batch['total_cost_cents'],sum(o['cost_cents'] for o in batch['outputs']))
            self.assertEqual([o['cost_cents'] for o in batch['outputs']],[2,1])
            with patch.object(fm,'daily_report',side_effect=lambda c,day:{'products':[{'net_kg':'40'}],'processing':[batch]} if day==self.day else {'products':[],'processing':[]}):
                month=fm.processing_month(c,self.day[:7]+'-01')
            self.assertEqual(month['direct_cost_cents'],1)
            self.assertEqual(month['indirect_cost_cents'],1)
            self.assertEqual(month['total_cost_cents'],sum(o['cost_cents'] for o in month['outputs']))
            self.assertEqual(sum(o['direct_cents'] for o in month['outputs']),1)
            self.assertEqual(sum(o['indirect_cents'] for o in month['outputs']),1)

    def test_monthly_indirect_pool_preserves_cent_between_batches(self):
        self.process('P004','0','1','P005','1','10')
        self.process('P004','0','1','P005','1','10')
        with erp.connect(True) as c:
            rc.Operations(c,erp.now,erp.audit).expense({'business_date':self.day,'category':'rent','amount':'0.01','request_key':str(uuid.uuid4()),'handler':'会计','note':'批次间余分核对'},'会计')
            batches=daily.processing_summary(c,self.day)
            self.assertEqual(sorted(b['indirect_cost_cents'] for b in batches),[0,1])
            self.assertEqual(sum(b['indirect_cost_cents'] for b in batches),1)

    def test_soybean_cost_stays_with_source_product(self):
        with erp.connect(True) as c:
            rc.Operations(c, erp.now, erp.audit).material({'request_key': str(uuid.uuid4()), 'material_id': 'RM-SOY', 'warehouse_id': 'WH-TOFU', 'business_date': self.day, 'kind': 'receipt', 'qty': '100', 'amount': '400', 'revision': rc.revision(c), 'handler': '管理员', 'note': '期初'}, '管理员')
            rc.Operations(c, erp.now, erp.audit).material({'request_key': str(uuid.uuid4()), 'material_id': 'RM-SOY', 'warehouse_id': 'WH-TOFU', 'business_date': self.day, 'kind': 'consume', 'qty': '50', 'amount': '0', 'revision': rc.revision(c), 'handler': '管理员', 'note': '上豆', 'production_system_id': 'tofu'}, '管理员')
            fm.save(c, 'daily', {'request_key': str(uuid.uuid4()), 'business_date': self.day, 'systems': {'tofu': {'soak_tanks': '1'}, 'skin': {'soak_tanks': '0', 'state': 'stopped'}}, 'products': [{'product_id': 'P004', 'system': 'tofu', 'large_tanks': '2', 'small_tanks': '0', 'skin_tanks': '0'}]}, '厂长', erp.now, erp.audit)
        self.process('P004', '10', '9', 'P005', '8', '7.5')
        with erp.connect() as c:
            allocation = material_allocation.day_report(c, self.day)
            allocated = {a['product_id'] for a in allocation['allocations']}
            self.assertEqual(allocated, {'P004'})
            report = fm.daily_report(c, self.day)
            rows = {p['product_id']: p for p in report['products']}
            self.assertIsNone(rows['P005']['yield_kg_per_kg'])
            self.assertEqual(rows['P005']['main_material'], '豆皮')

    def test_processing_quantity_and_weight_validation(self):
        with erp.connect(True) as c:
            rev = inventory.revision(c)
            base = {'business_date': self.day, 'product_id': 'P004', 'input_qty': '10', 'input_kg': '9', 'outputs': [{'product_id': 'P005', 'qty': '8', 'net_kg': '7.5'}], 'source_lot': '批次', 'handler': '厂长', 'inspection_note': '检验', 'origin': 'internal', 'origin_confirmed': True, 'inspection_checked': True, 'request_key': str(uuid.uuid4()), 'inventory_revision': rev}
            with self.assertRaisesRegex(ValueError, '客户退货'):
                inventory.Operations(c, erp.now, erp.audit).process({**base, 'origin': 'customer_return'}, '管理员')
        with erp.connect(True) as c:
            rev = inventory.revision(c)
            with self.assertRaisesRegex(ValueError, '实际投入净重'):
                inventory.Operations(c, erp.now, erp.audit).process({**base, 'input_kg': '', 'request_key': str(uuid.uuid4()), 'inventory_revision': rev}, '管理员')


if __name__ == '__main__':
    unittest.main(verbosity=2)


class FramedTransferStockTests(unittest.TestCase):
    """筐装来源转加工必须扣减来源筐数，避免来源库存虚高。"""

    def setUp(self):
        self.old = erp.DB
        self.temp = tempfile.TemporaryDirectory()
        erp.DB = Path(self.temp.name) / 'framed.db'
        erp.init_db(demo=True)
        self.day = '2026-10-20'
        with erp.connect(True) as c:
            c.execute("INSERT INTO meta VALUES('processing_rules',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (erp.dumps({'version': 1, 'rules': [{'source_product_id': 'P003', 'output_product_id': 'P006'}]}),))
            rows = [{'product_id': p['id'], 'existing_qty': '', 'produced_qty': '0', 'loss_qty': '0', 'loss_reason': '', 'counted_qty': '', 'variance_reason': ''} for p in c.execute('SELECT id FROM products')]
            for row in rows:
                if row['product_id'] in ('P003', 'P006'):
                    row['existing_qty'] = '10' if row['product_id'] == 'P003' else '0'
                    row['counted_qty'] = row['existing_qty']
            c.execute('INSERT OR REPLACE INTO warehouse_plans VALUES(?,?)', (self.day, erp.dumps({'business_date': self.day, 'version': 1, 'stock': rows, 'allocations': [], 'customers': [], 'allocation_state': 'confirmed'})))

    def tearDown(self):
        erp.DB = self.old
        self.temp.cleanup()

    def test_framed_source_quantity_is_deducted(self):
        with erp.connect(True) as c:
            inventory.Operations(c, erp.now, erp.audit).process({
                'business_date': self.day, 'product_id': 'P003', 'input_qty': '4', 'input_kg': '30',
                'outputs': [{'product_id': 'P006', 'qty': '6', 'net_kg': '28'}], 'origin': 'internal',
                'request_key': str(uuid.uuid4()), 'inventory_revision': inventory.revision(c)}, '库管')
            stock = {p['product_id']: p for p in inventory.stock(c, self.day)['products']}
            self.assertEqual(stock['P003']['processing_input_qty'], '4')
            self.assertEqual(stock['P003']['book_qty'], '6')
            self.assertEqual(stock['P006']['processing_output_qty'], '6')

    def test_framed_source_cannot_exceed_available(self):
        with erp.connect(True) as c:
            with self.assertRaisesRegex(ValueError, '可用库存不足'):
                inventory.Operations(c, erp.now, erp.audit).process({
                    'business_date': self.day, 'product_id': 'P003', 'input_qty': '99', 'input_kg': '300',
                    'outputs': [{'product_id': 'P006', 'qty': '1', 'net_kg': '1'}], 'origin': 'internal',
                    'request_key': str(uuid.uuid4()), 'inventory_revision': inventory.revision(c)}, '库管')
