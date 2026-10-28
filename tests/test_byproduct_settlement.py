import unittest, uuid
import test_workflow as fixture
import resources_costs as rc

erp = fixture.erp


class ByproductSettlementTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    tearDown = fixture.WorkflowTests.tearDown

    def material(self, day, qty, kind='consume', amount='0'):
        with erp.connect(True) as c:
            return rc.Operations(c, erp.now, erp.audit).material({'request_key': str(uuid.uuid4()), 'revision': rc.revision(c), 'kind': kind,
                'material_id': 'RM-SOY', 'warehouse_id': 'WH-TOFU', 'business_date': day, 'qty': qty, 'amount': amount,
                'handler': '库管', 'note': '测试', 'production_system_id': 'tofu'}, '管理员')

    def day1(self): return '2026-10-20'

    def day2(self): return '2026-10-21'

    def stock(self):
        self.material('2026-10-19', '1000', 'receipt', '4000')

    def config(self, role='管理员', **extra):
        with erp.connect(True) as c:
            return rc.save_byproduct_config(c, {'buyer': '豆渣收购点', 'add_kg': '10', **extra}, role, erp.now, erp.audit)

    def price(self, month='2026-10', price='0.5'):
        with erp.connect(True) as c:
            return rc.save_byproduct_price(c, {'month': month, 'price': price}, '会计', erp.now, erp.audit)

    def settle(self, month='2026-10'):
        with erp.connect(True) as c:
            return rc.settle_byproduct(c, {'month': month, 'request_key': str(uuid.uuid4()), 'handler': '会计'}, '会计', erp.now, erp.audit)

    def month(self, month='2026-10'):
        with erp.connect() as c:
            return rc.byproduct_month(c, month)

    def test_add_kg_is_admin_only_and_used_in_daily_settlement(self):
        self.stock(); self.material(self.day1(), '100'); self.material(self.day2(), '50')
        with self.assertRaisesRegex(ValueError, '管理员'):
            self.config(role='会计')
        self.config()
        with erp.connect() as c:
            self.assertEqual(rc.byproduct_config(c)['add_kg'], '10')
        view = self.month()
        self.assertEqual([d['date'] for d in view['days']], [self.day1(), self.day2()])
        self.assertEqual([d['qty'] for d in view['days']], ['110', '60'])
        self.price()
        view = self.month()
        self.assertEqual([d['amount_cents'] for d in view['days']], [5500, 3000])
        self.assertEqual(view['total_qty'], '170')
        self.assertEqual(view['total_amount_cents'], 8500)
        record = self.settle()
        self.assertEqual(record['qty'], '170')
        self.assertEqual(record['amount_cents'], 8500)
        self.assertEqual(record['buyer'], '豆渣收购点')
        self.assertEqual(record['source'], 'daily-settlement')
        self.assertEqual(record['period'], '2026-10')
        with self.assertRaisesRegex(ValueError, '已有按日结算'):
            self.settle()
        self.assertEqual(self.month()['settlement']['id'], record['id'])

    def test_settlement_requires_price_buyer_and_days(self):
        with self.assertRaisesRegex(ValueError, '单价'):
            self.settle()
        self.stock(); self.material(self.day1(), '100')
        with self.assertRaisesRegex(ValueError, '单价'):
            self.settle()
        self.price()
        with self.assertRaisesRegex(ValueError, '固定买家'):
            self.settle()
        self.config()
        self.assertEqual(self.settle()['amount_cents'], 5500)

    def test_returns_reduce_daily_bean_kg(self):
        self.stock(); self.material(self.day1(), '100'); self.material(self.day1(), '20', 'return')
        self.config(add_kg='0'); self.price()
        self.assertEqual(self.month()['days'][0]['bean_kg'], '80')

    def test_business_view_excludes_internal_parameters_and_preserves_money(self):
        self.stock(); self.material(self.day1(), '100'); self.config(); self.price()
        record=self.settle()
        with erp.connect() as c:
            view=rc.byproduct_business_month(c,'2026-10')
        self.assertNotIn('config',view)
        self.assertNotIn('add_kg',str(view))
        self.assertNotIn('bean_kg',str(view))
        self.assertEqual(next(d for d in view['days'] if d['date']==self.day1())['qty'],'110')
        self.assertEqual(view['total_amount_cents'],record['amount_cents'])
        legacy={**record,'note':'按日结算：1 天，上豆与加量合计 110 公斤'}
        clean=rc.byproduct_business_record(legacy)
        self.assertNotIn('加量',clean['note'])
        self.assertEqual(clean['qty'],legacy['qty'])
        self.assertEqual(clean['amount_cents'],legacy['amount_cents'])
        self.assertIn('加量',legacy['note'],'保留原始记录用于内部追溯')

    def test_parameter_visibility_and_stale_save(self):
        import production_management as pm, erp_access as access
        self.config()
        with erp.connect() as c:
            for role in ('会计','出纳','老板','库管','厂长','物流负责人','司机'):
                view=pm.parameter_catalog(c,{'role':role,'permissions':access.defaults(role)})
                self.assertNotIn('byproduct_settings',view)
            cfg=pm.parameter_catalog(c,{'role':'管理员','permissions':access.defaults('管理员')})['byproduct_settings']
            self.assertEqual(cfg['add_kg'],'10')
        self.config(version=cfg['version'],add_kg='12')
        with self.assertRaisesRegex(ValueError,'已变化'):
            self.config(version=cfg['version'],add_kg='20')

    def test_posted_daily_rows_are_stable_after_parameter_changes(self):
        self.stock();self.material(self.day1(),'100');self.config();self.price();record=self.settle()
        self.config(add_kg='25',buyer='新的购货方')
        with erp.connect() as c:
            view=rc.byproduct_business_month(c,'2026-10')
        self.assertEqual(view['buyer'],record['buyer'])
        self.assertEqual(next(d for d in view['days'] if d['date']==self.day1())['qty'],'110')
        self.assertEqual(view['total_amount_cents'],5500)
        with self.assertRaisesRegex(ValueError,'已生成收入'):
            self.price(price='0.6')

    def test_selectable_basis_default_one_to_one_and_adjustable_ratio(self):
        self.stock();self.material(self.day1(),'100');self.config(basis='converted',yield_ratio='1');self.price()
        self.assertEqual(self.month()['total_qty'],'110')
        self.config(basis='converted',yield_ratio='2.25')
        self.assertEqual(self.month()['total_qty'],'235')
        record=self.settle();self.assertEqual(record['amount_cents'],11750)
        self.assertEqual(record['internal_calculation']['yield_ratio'],'2.25')
        self.config(basis='bean',yield_ratio='3')
        self.assertEqual(self.month()['total_qty'],'110','按用豆量时不使用换算系数')
        with erp.connect() as c:view=rc.byproduct_business_month(c,'2026-10')
        self.assertEqual(view['total_qty'],'235','参数变化不改写原入账单')
        self.assertNotIn('internal_calculation',str(view));self.assertNotIn('yield_ratio',str(view));self.assertNotIn('add_kg',str(view))

    def test_invalid_conversion_options_are_rejected_and_days_are_complete(self):
        for ratio in ('0','-1','NaN','Infinity','100.001'):
            with self.assertRaises(ValueError):self.config(basis='converted',yield_ratio=ratio)
        with self.assertRaisesRegex(ValueError,'口径'):self.config(basis='unknown')
        with erp.connect() as c:view=rc.byproduct_business_month(c,'2028-02')
        self.assertEqual(len(view['days']),29)
        self.assertTrue(all(not d['recorded'] and d['qty'] is None and d['amount_cents']==0 for d in view['days']))
