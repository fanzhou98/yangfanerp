import copy
import json
import uuid
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import test_production_daily as fixture
import production_config as pc
import material_allocation as allocation
import resources_costs as rc
import production_daily as daily


class ProductionConfigTests(unittest.TestCase):
    setUp = fixture.DailyFactoryTests.setUp
    tearDown = fixture.DailyFactoryTests.tearDown
    call = fixture.DailyFactoryTests.call
    material = fixture.DailyFactoryTests.material
    record = fixture.DailyFactoryTests.record

    def day(self, offset=1):
        return (date.today() + timedelta(days=offset)).isoformat()

    def directory(self):
        with fixture.erp.connect() as c:
            value = pc.get(c)
        value['systems'].append({'id': 'third', 'name': '第三磨浆系统', 'active': True, 'material_id': 'RM-SOY', 'warehouse_ids': ['WH-TOFU', 'WH-MAIN'], 'default_warehouse_id': 'WH-TOFU', 'soak_kg': '450', 'allocation_mode': 'proportional', 'residual_product_id': ''})
        value['processes'].append({'id': 'newvat', 'name': '压力浆缸', 'active': True, 'dry_kg': '25', 'output_qty': '5'})
        value['products']['P001']['system_ids'].append('third')
        value['products']['P001']['process_ids'].append('newvat')
        return value

    def publish(self, value=None, offset=1, role='管理员'):
        value = value or self.directory()
        return self.call('production-config', {'version': value['version'], 'effective_date': self.day(offset), 'config': value, 'note': '新增独立系统，允许与原系统共用库存库房'}, role)

    def issue(self, system, qty, wid='WH-TOFU', kind='consume', when=None):
        return self.material(kind, qty, warehouse=wid, business_date=when or self.day(), production_system_id=system)

    def register(self, **extra):
        return self.record(**{'business_date':self.day(), 'systems':{k: {'soak_tanks': '0', 'state': 'running'} for k in ('tofu', 'skin', 'gel-tofu', 'third')}, 'products':[{'product_id': 'P001', 'system': 'third', 'tanks': {'newvat': '2'}}], **extra})

    def test_config_can_publish_today_without_business(self):
        with fixture.erp.connect(True) as c:
            c.execute('DELETE FROM factory_daily');c.execute('DELETE FROM material_entries')
        cfg=self.directory()
        published=self.publish(cfg,offset=0)
        self.assertEqual(published['effective_date'],date.today().isoformat())
        with fixture.erp.connect(True) as c:
            c.execute('INSERT INTO factory_daily(id,request_key,payload) VALUES(?,?,?)',('CFG-T2','CFG-T2',json.dumps({'business_date':date.today().isoformat()})))
        with self.assertRaisesRegex(ValueError,'最早'):
            self.publish(self.directory(),offset=0)

    def test_product_can_be_configured_without_tank_process(self):
        cfg=self.directory()
        cfg['products']['P001']['process_ids']=[]
        self.publish(cfg)
        with fixture.erp.connect() as c:
            self.assertEqual(pc.history(c)[-1]['products']['P001']['process_ids'],[])

    def test_effective_date_defaults_to_today_without_business(self):
        with fixture.erp.connect(True) as c:
            c.execute('DELETE FROM factory_daily');c.execute('DELETE FROM material_entries')
            today=date.today().isoformat()
            self.assertEqual(pc.minimum_date(c),today)
            c.execute('INSERT INTO factory_daily(id,request_key,payload) VALUES(?,?,?)',('CFG-T1','CFG-T1',json.dumps({'business_date':today})))
            self.assertEqual(pc.minimum_date(c),(date.today()+timedelta(days=1)).isoformat())

    def test_third_system_shared_and_multiple_warehouses_no_double_count(self):
        self.publish()
        self.material('receipt', '1000', '4000', business_date=self.day())
        self.material('receipt', '500', '2500', warehouse='WH-MAIN', business_date=self.day())
        self.issue('tofu', '100'); self.issue('third', '200'); self.issue('third', '50', 'WH-MAIN'); self.issue('third', '10', kind='return')
        record = self.register()
        with fixture.erp.connect() as c:
            issued = fixture.daily.issue_kg(c, self.day())
            self.assertEqual(issued, {'tofu': '100', 'skin': '0', 'gel-tofu':'0', 'third': '240'})
            r = allocation.day_report(c, self.day())
            third = next(p for p in r['pools'] if p['system'] == 'third')
            self.assertEqual(third['issued_kg'], '240')
            self.assertEqual(third['cost_cents'], 101000)
            self.assertEqual(sum(a['cost_cents'] for a in r['allocations']), third['cost_cents'])
            self.assertEqual(sum(Decimal(a['allocated_kg']) for a in r['allocations']), 240)
            self.assertEqual(record['config_snapshot']['version'], 2)
            self.assertEqual(record['products'][0]['tanks'], {'newvat': '2'})
            self.assertEqual(len(fixture.fm.daily_report(c, self.day())['systems']), 4)

    def test_new_warehouse_purchase_receipt_transfer_and_issue(self):
        cfg = self.directory()
        cfg['warehouses'].append({'id': 'WH-NEW', 'name': '共享原豆库', 'active': True, 'material_ids': ['RM-SOY']})
        cfg['systems'][-1]['warehouse_ids'].append('WH-NEW')
        self.publish(cfg)
        with fixture.erp.connect(True) as c:
            ops=fixture.erp.purchasing.Operations(c,fixture.erp.now,fixture.erp.audit)
            supplier=ops.supplier({'name':'新增库房供应商','payment_days':0},'会计')
            order=ops.order({'request_key':str(uuid.uuid4()),'supplier_id':supplier['id'],'business_date':self.day(),'expected_date':self.day(),'handler':'采购','lines':[{'material_id':'RM-SOY','warehouse_id':'WH-NEW','qty':'100','price':'4'}]},'会计')
            order=ops.confirm({'id':order['id'],'version':order['version']},'会计')
            ops.receipt({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'id':order['id'],'version':order['version'],'business_date':self.day(),'handler':'库管','note':'新库房验收','lines':[{'line_id':'L1','qty':'100'}]},'库管')
        self.issue('third', '20', 'WH-NEW')
        with fixture.erp.connect() as c:
            stocks = rc.material_ledger(c, self.day(), True)[2]
            self.assertEqual(next(s['qty'] for s in stocks if s['id'] == 'RM-SOY' and s['warehouse_id'] == 'WH-NEW'), '80')
            self.assertEqual(rc.warehouse({'id': 'RM-SOY'}, 'WH-NEW', c=c, when=self.day()), 'WH-NEW')

    def test_new_flow_requires_explicit_source_and_product_relation(self):
        self.publish()
        self.material('receipt', '500', '2000', business_date=self.day())
        with self.assertRaisesRegex(ValueError, '磨浆系统'):
            self.material('consume', '1', business_date=self.day())
        with self.assertRaisesRegex(ValueError, '允许领用'):
            self.issue('skin', '1')
        with self.assertRaisesRegex(ValueError, '允许使用'):
            self.register(products=[{'product_id': 'P002', 'system': 'third', 'tanks': {'newvat': '1'}}])
        with self.assertRaisesRegex(ValueError, '浆缸工艺'):
            self.register(products=[{'product_id': 'P002', 'system': 'tofu', 'tanks': {'newvat': '1'}}])

    def test_future_config_and_rename_do_not_rewrite_history(self):
        self.material('receipt', '500', '2000'); self.material('consume', '50'); old = self.record()
        with fixture.erp.connect() as c:
            before = allocation.day_report(c, '2026-10-20')
        first = self.publish(); self.register()
        changed = copy.deepcopy(first); changed['systems'][0]['name'] = '一号系统'; changed['systems'][-1]['active'] = False
        self.publish(changed, offset=2)
        with fixture.erp.connect() as c:
            self.assertEqual(allocation.day_report(c, '2026-10-20'), before)
            self.assertEqual(len(pc.active_systems(pc.get(c, self.day()))), 4)
            self.assertEqual(len(pc.active_systems(pc.get(c, self.day(2)))), 3)
            self.assertEqual(len(fixture.fm.daily_report(c, self.day())['systems']), 4)
            self.assertEqual(rc.rows(c, 'factory_daily')[0], old)
            self.assertEqual(pc.get(c, '2026-10-20')['version'], 0)

    def test_admin_only_stale_version_date_conflict_and_referential_checks(self):
        for role in ('厂长', '会计', '库管', '司机', '老板'):
            with self.assertRaisesRegex(ValueError, '管理员'):
                self.publish(role=role)
        # 当天无生产或上豆记录时允许当天生效，日期边界另见 test_config_can_publish_today_without_business
        cfg = self.directory(); cfg['systems'][-1]['warehouse_ids'] = ['missing']
        with self.assertRaisesRegex(ValueError, '默认领用'):
            self.publish(cfg)
        self.publish()
        with self.assertRaisesRegex(ValueError, '已更新'):
            self.publish()
        with fixture.erp.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM production_config_versions').fetchone()[0], 3)

    def test_stopped_system_is_zero_without_spurious_issue_requirement(self):
        self.publish()
        systems = {k: {'state': 'stopped', 'soak_tanks': '0'} for k in ('tofu', 'skin', 'gel-tofu', 'third')}
        r = self.register(systems=systems, products=[])
        self.assertEqual(r['systems']['third'], {'state': 'stopped', 'soak_tanks': '0'})
        with self.assertRaisesRegex(ValueError, '未开机'):
            self.register(business_date=self.day(2), systems=systems)

    def test_parameter_group_rename_does_not_change_authorization(self):
        with fixture.erp.connect() as c:
            user = {'id': 'test', 'role': '库管', 'permissions': fixture.access.defaults('库管')}
            before = fixture.fm.parameter_catalog(c, user)
            groups = copy.deepcopy(fixture.fm.PARAMETER_GROUPS); groups[0]['title'] = '称重参数'
            with patch.object(fixture.fm, 'PARAMETER_GROUPS', groups):
                after = fixture.fm.parameter_catalog(c, user)
            self.assertEqual([i['key'] for g in before['groups'] for i in g['items']], [i['key'] for g in after['groups'] for i in g['items']])

    def test_independent_scoped_parameter_approvals_same_date_and_snapshot(self):
        self.publish(); record = self.register()
        pending = []
        for key, value in [('systems.third.soak_kg', '480'), ('processes.newvat.dry_kg', '27')]:
            pending.append(self.call('parameter-request', {'key': key, 'value': value, 'version': 1, 'config_version': 2, 'effective_date': self.day(2), 'reason': '核定实际换算'}))
        with fixture.erp.connect() as c:
            self.assertEqual(pc.get(c, self.day())['systems'][-1]['soak_kg'], '450')
        for request in pending:
            self.call('parameter-review', {'id': request['id'], 'version': 1, 'decision': 'approve', 'reason': '逐项核定通过'}, '管理员')
        with fixture.erp.connect() as c:
            config = pc.get(c, self.day(2))
            self.assertEqual(config['version'], 4)
            self.assertEqual(config['systems'][-1]['soak_kg'], '480')
            self.assertEqual(config['processes'][-1]['dry_kg'], '27')
            self.assertEqual(rc.rows(c, 'factory_daily')[0], record)
            self.assertEqual(pc.get(c, self.day())['systems'][-1]['soak_kg'], '450')

    def test_partial_bean_soak_keeps_new_system_pending_until_confirmed(self):
        self.publish()
        self.material('receipt','100','400',business_date=self.day())
        with fixture.erp.connect() as c:revision=rc.revision(c)
        self.call('beans',{'business_date':self.day(),'config_version':2,'entries':[{'production_system_id':'third','warehouse_id':'WH-TOFU','qty':'10'}],
            'soak_tanks':{'third':'0.5'},'revision':revision,'handler':'厂长'})
        with fixture.erp.connect() as c:
            record=rc.rows(c,'factory_daily')[0]
            self.assertEqual(record['systems']['third'],{'soak_tanks':'0.5','state':'pending'})
            self.assertEqual(record['systems']['tofu'],{'soak_tanks':'','state':'pending'})
            self.assertEqual(record['systems']['skin'],{'soak_tanks':'','state':'pending'})
            self.assertEqual(record['config_snapshot']['version'],2)

    def test_shared_residual_product_keeps_all_sources_and_pending_pool(self):
        config=self.directory()
        config['systems'][-1].update(allocation_mode='residual',residual_product_id='P004')
        config['products']['P004']['system_ids'].append('third')
        self.publish(config)
        self.material('receipt','100','400',warehouse='WH-SKIN',business_date=self.day())
        self.material('receipt','100','400',business_date=self.day())
        self.issue('skin','10',wid='WH-SKIN');self.issue('third','50')
        registered=self.register(products=[{'product_id':'P001','system':'skin','tanks':{'large':'1'}}])
        stock={'product_id':'P004','product_name':'豆皮','unit':'包','opening_qty':'0','shipped_qty':'10','loss_qty':'0',
            'processing_input_qty':'0','processing_output_qty':'0','counted_qty':'0'}
        def report():
            with fixture.erp.connect() as c,patch.object(daily.inventory,'stock',return_value={'products':[stock],'closing':None}):
                return fixture.fm.daily_report(c,self.day())['products'][0]
        pending=report()
        self.assertIsNone(pending['bean_kg'])
        self.assertIsNone(pending['yield_kg_per_kg'])
        self.assertIn('超过',str(pending['allocation_reasons']))
        self.assertEqual(pending['calculation_status'],'待补数据')
        self.call('daily',{'id':registered['id'],'version':registered['version'],'business_date':self.day(),'config_version':2,
            'systems':registered['systems'],'products':[]})
        complete=report()
        self.assertEqual(complete['bean_kg'],'60')
        self.assertEqual({a['system'] for a in complete['allocated_sources']},{'skin','third'})
        self.assertEqual(complete['system'],'mixed')
        self.assertEqual(complete['allocation_reasons'],[])
        self.assertEqual(complete['calculation_status'],'估算结果')
