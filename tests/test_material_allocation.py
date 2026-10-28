import unittest,uuid,json
from decimal import Decimal
import test_production_daily as fixture
import material_allocation as ma
import production_daily as daily
import resources_costs as rc

class MaterialAllocationTests(unittest.TestCase):
    setUp=fixture.DailyFactoryTests.setUp
    tearDown=fixture.DailyFactoryTests.tearDown
    call=fixture.DailyFactoryTests.call
    record=fixture.DailyFactoryTests.record
    material=fixture.DailyFactoryTests.material
    def pool(self,system,qty='100',amount='400'):
        wid='WH-TOFU' if system=='tofu' else 'WH-SKIN'
        self.material('receipt',qty,amount,warehouse=wid);return self.material('consume',qty,warehouse=wid)
    def rows(self,*items):return [{'product_id':pid,'system':source,'large_tanks':large,'small_tanks':small} for pid,source,large,small in items]
    def allocation(self):
        with fixture.erp.connect() as c:return ma.month_report(c,'2026-10')
    def test_two_source_same_product_skin_residual_and_exact_money(self):
        self.pool('tofu','100','400');self.pool('skin','200','1000')
        self.record(products=self.rows(('P001','tofu','1','0'),('P002','tofu','0','1'),('P001','skin','2','0')))
        r=self.allocation();self.assertEqual((r['total_cents'],r['allocated_cents'],r['unallocated_cents']),(140000,140000,0))
        a={(a['product_id'],a['system']):a for a in r['allocations']}
        self.assertEqual(a['P001','skin']['allocated_kg'],'66');self.assertEqual(a['P004','skin']['allocated_kg'],'134')
        self.assertEqual(a['P001','skin']['cost_cents'],33000);self.assertEqual(a['P004','skin']['cost_cents'],67000)
        self.assertEqual(a['P001','tofu']['cost_cents'],18082);self.assertEqual(a['P002','tofu']['cost_cents'],21918)
        self.assertEqual(sum(Decimal(a['allocated_kg']) for a in r['allocations']),Decimal('300'))
        with fixture.erp.connect() as c:
            report=daily.report(c,'2026-10-20',fixture.fm.settings(c),fixture.fm.line_weight)
            p=next(p for p in report['products'] if p['product_id']=='P001');skin=next(p for p in report['products'] if p['product_id']=='P004')
            self.assertEqual(p['bean_kg'],'111.205');self.assertEqual(p['system'],'mixed');self.assertEqual(skin['bean_kg'],'134')
    def test_cost_uses_actual_fifo_not_reference_tank_kg(self):
        self.pool('tofu','1','0.01')
        self.record(products=self.rows(('P001','tofu','1','0'),('P002','tofu','1','0'),('P003','tofu','1','0')))
        r=self.allocation();self.assertEqual(sum(a['cost_cents'] for a in r['allocations']),1)
        self.assertEqual(sum(Decimal(a['allocated_kg']) for a in r['allocations']),1)
        self.assertEqual(sorted(a['cost_cents'] for a in r['allocations']),[0,0,1])
    def test_overtransfer_is_visible_and_skin_pool_not_allocated(self):
        self.pool('skin','50','200');self.record(products=self.rows(('P001','skin','2','0')))
        r=self.allocation();self.assertEqual(r['unallocated_cents'],20000);self.assertEqual(r['allocations'],[])
        self.assertIn('超过',str(r['pools']))
    def test_missing_record_or_blank_counts_remain_unallocated(self):
        self.pool('tofu');r=self.allocation();self.assertEqual(r['unallocated_cents'],40000)
        record=self.record(products=self.rows(('P001','tofu','','0')));self.assertEqual(self.allocation()['unallocated_cents'],40000)
        self.call('daily',{'id':record['id'],'version':record['version'],'business_date':'2026-10-20','systems':record['systems'],'products':self.rows(('P001','tofu','1','0'))})
        self.assertEqual(self.allocation()['unallocated_cents'],0)
    def test_skin_own_no_vats_and_tofu_to_skin_exception(self):
        self.pool('skin','100','500');self.pool('tofu','50','200')
        self.record(products=self.rows(('P004','tofu','1','0')))
        r=self.allocation();self.assertEqual(r['unallocated_cents'],0);self.assertEqual(sum(a['cost_cents'] for a in r['allocations'] if a['product_id']=='P004'),70000)
    def test_no_issue_with_tanks_is_pending_instead_of_invented_cost(self):
        self.record(products=self.rows(('P001','skin','1','0')))
        r=self.allocation();self.assertEqual(r['allocations'],[]);self.assertTrue(any(p['reasons'] for p in r['pools']))
    def test_unique_product_source_and_parameter_snapshot(self):
        items=self.rows(('P001','tofu','1','0'),('P001','skin','1','0'))
        r=self.record(products=items);self.assertEqual(len(r['products']),2)
        with self.assertRaisesRegex(ValueError,'同一供浆来源'):self.record(business_date='2026-10-21',products=[items[0],items[0]])
        self.pool('skin');before=self.allocation()
        with fixture.erp.connect(True) as c:
            cfg=fixture.fm.settings(c);cfg['large_slurry_kg']='99';c.execute("UPDATE factory_settings SET payload=? WHERE id='default'",(rc.dump(cfg),))
        self.assertEqual(self.allocation(),before)
    def test_closed_month_blocks_new_and_existing_supply_edits(self):
        record=self.record(products=self.rows(('P001','tofu','1','0')))
        with fixture.erp.connect(True) as c:rc.Operations(c,fixture.erp.now,fixture.erp.audit).period({'month':'2026-11','state':'closed','version':0,'note':'后续结账'},'会计')
        with self.assertRaisesRegex(ValueError,'结账'):self.record(business_date='2026-10-21',products=[])
        with self.assertRaisesRegex(ValueError,'结账'):self.record(id=record['id'],version=record['version'],products=[])
    def test_legacy_daily_record_still_allocates_without_rewriting_it(self):
        self.pool('skin');record=self.record(products=[])
        with fixture.erp.connect(True) as c:
            record['format']='daily-v2';record.pop('skin_product_id',None);record.pop('grinding_defaults',None)
            c.execute('UPDATE factory_daily SET payload=? WHERE id=?',(rc.dump(record),record['id']))
        self.assertEqual(self.allocation()['allocated_cents'],40000)
        with fixture.erp.connect() as c:self.assertEqual(rc.rows(c,'factory_daily')[0],record)
    def test_defaults_only_confirmed_products_and_can_override(self):
        with fixture.erp.connect(True) as c:
            products={p['id']:dict(p) for p in c.execute('SELECT id,name FROM products')}
            self.assertEqual(daily.grinding_system(c,products['P001']),'tofu');self.assertEqual(daily.grinding_system(c,products['P004']),'skin');self.assertEqual(daily.grinding_system(c,products['P005']),'')
            c.execute("INSERT INTO meta VALUES('product_grinding_systems',?)",(json.dumps({'P001':'skin'}),));self.assertEqual(daily.grinding_system(c,products['P001']),'tofu')
            # The effective production directory remains authoritative after an upgrade.
            import production_config as pc
            self.assertEqual(pc.default_system(c,products['P001'],pc.get(c,'2026-10-20')),'skin')
    def test_auxiliary_attribute_changes_no_quantity_warehouse_or_cost(self):
        def aux(kind,**extra):
            with fixture.erp.connect(True) as c:return rc.Operations(c,fixture.erp.now,fixture.erp.audit).material({'material_id':'A-SALT','warehouse_id':'WH-COMMON','business_date':'2026-10-20','kind':kind,'qty':'10','amount':'50' if kind=='receipt' else '0','revision':rc.revision(c),'request_key':str(uuid.uuid4()),'handler':'会计','note':'归集验收',**extra},'管理员')
        aux('receipt');e=aux('consume',product_id='P001')
        with fixture.erp.connect(True) as c:
            before=rc.snapshot(c);rev=rc.revision(c)
            b={'id':e['id'],'version':1,'revision':rev,'product_id':'P002','cost_target':'共用','note':'实际用于中豆腐'}
            with self.assertRaises(ValueError):rc.Operations(c,fixture.erp.now,fixture.erp.audit).attribute(b,'库管')
            saved=rc.Operations(c,fixture.erp.now,fixture.erp.audit).attribute(b,'会计');after=rc.snapshot(c)
            self.assertEqual(before['items'],after['items']);self.assertEqual(saved['product_id'],'P002');self.assertEqual(saved['warehouse_id'],'WH-COMMON');self.assertEqual(saved['qty'],e['qty']);self.assertEqual(saved['amount_cents'],e['amount_cents']);self.assertEqual(saved['attribution_history'][0]['before']['product_id'],'P001')
            with self.assertRaisesRegex(ValueError,'已更新'):rc.Operations(c,fixture.erp.now,fixture.erp.audit).attribute(b,'会计')
        with fixture.erp.connect(True) as c:
            rc.Operations(c,fixture.erp.now,fixture.erp.audit).period({'month':'2026-10','state':'closed','version':0,'note':'结账'},'会计')
            with self.assertRaisesRegex(ValueError,'结账'):rc.Operations(c,fixture.erp.now,fixture.erp.audit).attribute({**b,'version':2,'revision':rc.revision(c)},'会计')
    def test_soy_attribution_cannot_bypass_source_or_edit_inventory(self):
        e=self.pool('tofu')
        with fixture.erp.connect(True) as c:
            with self.assertRaisesRegex(ValueError,'每日生产'):rc.Operations(c,fixture.erp.now,fixture.erp.audit).attribute({'id':e['id'],'version':1,'revision':rc.revision(c),'product_id':'P002','note':'试图直接归属'},'会计')
