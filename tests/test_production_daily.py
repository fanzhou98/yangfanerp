import unittest,tempfile,uuid,json
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
import test_workflow as fixture
import production_management as fm
import production_daily as daily
import resources_costs as rc
import erp_access as access

erp=fixture.erp
class DailyFactoryTests(unittest.TestCase):
    def setUp(self):
        self.old=erp.DB;self.temp=tempfile.TemporaryDirectory();erp.DB=Path(self.temp.name)/'daily.db';erp.init_db()
    def tearDown(self):erp.DB=self.old;self.temp.cleanup()
    def call(self,kind,body,role='厂长'):
        with erp.connect(True) as c:return fm.save(c,kind,{'request_key':str(uuid.uuid4()),**body},role,erp.now,erp.audit)
    def material(self,kind,q,amount='0',warehouse='WH-TOFU',**extra):
        with erp.connect(True) as c:return rc.Operations(c,erp.now,erp.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':'RM-SOY','business_date':'2026-10-20','kind':kind,'qty':q,'amount':amount,'warehouse_id':warehouse,'note':'测试','handler':'测试',**extra},'管理员')
    def record(self,**extra):
        return self.call('daily',{'business_date':'2026-10-20','systems':{'tofu':{'soak_tanks':'0.6'},'skin':{'soak_tanks':'1'}},'products':[{'product_id':'P001','large_tanks':'10','small_tanks':'0','skin_tanks':'0'},{'product_id':'P004','large_tanks':'0','small_tanks':'0','skin_tanks':'5'}],**extra})
    def attendance(self,entries,when='2026-10-20',**extra):
        return self.call('attendance',{'format':'group-day-v2','business_date':when,'state':'confirmed','groups':[{'group_id':'G-TOFU','start_time':'22:00','end_time':'06:00'},{'group_id':'G-SKIN','start_time':'21:00','end_time':'05:00'}],'entries':entries,**extra})
    def test_one_day_both_systems_no_duplicate_or_output_entry(self):
        record=self.record();self.assertEqual(set(record['systems']),{'tofu','skin'})
        self.assertNotIn('receivable_days',record['settings_snapshot']);self.assertNotIn('qty',record['products'][0]);self.assertNotIn('dry_kg',record)
        with self.assertRaisesRegex(ValueError,'当天已有'):self.record()
        with self.assertRaisesRegex(ValueError,'同时登记'):self.record(business_date='2026-10-21',systems={'tofu':{'soak_tanks':'1'}})
        with self.assertRaisesRegex(ValueError,'每日生产'):self.call('run',{})
    def test_group_attendance_notice_moves_and_start_only(self):
        a=self.call('employee',{'name':'甲','group_id':'G-TOFU'});b=self.call('employee',{'name':'乙','group_id':'G-SKIN'})
        old=[{'employee_id':a['id'],'group_id':'G-TOFU','status':'full'},{'employee_id':b['id'],'group_id':'G-SKIN','status':'full'}]
        self.attendance(old,when='2026-10-19')
        r=self.attendance([{**old[0],'group_id':'G-SKIN','status':'half'},old[1]],groups=[{'group_id':'G-SKIN','start_time':'20:30','end_time':'05:30'}])
        self.assertEqual(r['entries'][0]['days'],'0.5');self.assertNotIn('hours',r['entries'][0]);self.assertNotIn('start',r['entries'][0])
        self.assertIn('甲：豆腐组→豆皮组',r['notice']);self.assertIn('21:00→20:30',r['notice']);self.assertIn('甲（半天）',r['notice']);self.assertNotIn('05:30',r['notice']);self.assertNotIn('下班',r['notice'])
        with self.assertRaisesRegex(ValueError,'当天已有'):self.attendance(old)
    def test_attendance_confirm_requires_start_and_employee_unique(self):
        a=self.call('employee',{'name':'甲','group_id':'G-TOFU'});entry={'employee_id':a['id'],'group_id':'G-TOFU','status':'full'}
        with self.assertRaisesRegex(ValueError,'上班时间'):self.attendance([entry],groups=[])
        with self.assertRaisesRegex(ValueError,'只能归属'):self.attendance([entry,entry])
        r=self.attendance([{**entry,'status':'absent'}],groups=[]);self.assertEqual(r['entries'][0]['days'],'0')
    def test_shared_issue_ledger_and_note_only_scrap(self):
        self.material('receipt','1000','4000');self.material('consume','330');self.material('return','10')
        with erp.connect() as c:self.assertEqual(daily.issue_kg(c,'2026-10-20')['tofu'],'320');before=erp.inventory.stock(c,'2026-10-20')
        self.call('scrap',{'format':'note-v2','business_date':'2026-10-20','kg':'12','product_id':'P005','note':'做素鸡'})
        with erp.connect() as c:
            self.assertEqual(erp.inventory.stock(c,'2026-10-20'),before);self.assertEqual(fm.scrap_ledger(c)['balance_kg'],'0')
    def test_output_formula_ignores_entered_production_and_waits_for_counts(self):
        p={'product_id':'P001','product_name':'大豆腐','unit':'筐','opening_qty':'5','production_qty':'999','shipped_qty':'40','loss_qty':'2','processing_input_qty':'3','processing_output_qty':'4','counted_qty':'10'}
        with erp.connect() as c,patch.object(daily.inventory,'stock',return_value={'products':[p],'closing':None}):
            r=daily.inferred_outputs(c,'2026-10-20')[0];self.assertEqual(r['derived_qty'],'46');self.assertEqual(r['output_status'],'待日结确认')
        with erp.connect() as c,patch.object(daily.inventory,'stock',return_value={'products':[{**p,'counted_qty':''}],'closing':None}):self.assertIsNone(daily.inferred_outputs(c,'2026-10-20')[0]['derived_qty'])
        with erp.connect() as c,patch.object(daily.inventory,'stock',return_value={'products':[{**p,'opening_qty':'100'}],'closing':None}):self.assertEqual(daily.inferred_outputs(c,'2026-10-20')[0]['output_status'],'库存勾稽异常')
    def test_report_reverse_and_skin_yield_both_bases(self):
        self.material('receipt','1000','4000');self.material('consume','330');self.material('receipt','1000','4000',warehouse='WH-SKIN');self.material('consume','500',warehouse='WH-SKIN');self.record()
        self.call('scrap',{'format':'note-v2','business_date':'2026-10-20','kg':'20','product_id':'P005'})
        def p(pid,name,q):return {'product_id':pid,'product_name':name,'unit':'筐' if pid=='P001' else '包','opening_qty':'0','production_qty':'999','shipped_qty':q,'loss_qty':'0','processing_input_qty':'0','processing_output_qty':'0','counted_qty':'0'}
        with erp.connect() as c,patch.object(daily.inventory,'stock',return_value={'products':[p('P001','大豆腐','40'),p('P004','豆皮','100')],'closing':None}):r=fm.daily_report(c,'2026-10-20')
        tofu=r['products'][0];skin=r['products'][1];self.assertEqual(tofu['slurry_bean_kg'],'330');self.assertEqual(tofu['reverse_bean_kg'],'330');self.assertEqual(skin['yield_kg_per_kg'],'2');self.assertEqual(skin['yield_with_scrap'],'2.04');self.assertEqual(r['systems'][0]['issued_kg'],'330');self.assertIsNone(r['systems'][1]['methods'][2]['kg'])
    def test_finance_permissions_and_nested_projection(self):
        with self.assertRaises(ValueError):self.call('finance-settings',{'version':1,'receivable_days':'7'})
        with self.assertRaisesRegex(ValueError,'财务预警'):self.call('settings',{'version':1,'receivable_days':'7'})
        self.record()
        with erp.connect() as c:r=fm.scope(fm.snapshot(c),access.defaults('厂长'))
        self.assertNotIn('receivable_days',json.dumps(r));self.assertNotIn('finance.alert-settings',access.defaults('厂长')['actions'])
    def test_protein_bands_and_weighted_remaining_stock(self):
        qualities=[('10','39','10'),('20','40','11'),('30','41','12'),('40','42','13'),('50',None,None)]
        r=daily.soybean_analysis([{'warehouse_id':'WH-TOFU','warehouse_name':'豆腐','qty':'150','lots':[{'qty':q,'quality':{'protein_pct':p,'moisture_pct':m}} for q,p,m in qualities]}])[0]
        self.assertEqual(r['bands'],{'lt40':'10','40to41':'50','gt41':'40','unknown':'50'});self.assertEqual(r['average_protein'],'41');self.assertEqual(r['average_moisture'],'12');self.assertEqual(r['protein_known_kg'],'100')
    def test_only_two_grinding_lines_can_issue_soybeans(self):
        self.material('receipt','100','400')
        for department in ('素鸡线','共用','豆干线'):
            with self.assertRaisesRegex(ValueError,'仅支持豆腐线、豆皮线'):self.call('issue',{'department':department})
        for warehouse in ('WH-MAIN','WH-EXTERNAL'):
            with self.assertRaisesRegex(ValueError,'请先调入'):self.material('consume','1',warehouse=warehouse)
        with erp.connect() as c:rev=rc.revision(c)
        result=self.call('issue',{'department':'豆腐线','material_id':'RM-SOY','warehouse_id':'WH-TOFU','business_date':'2026-10-20','qty':'10','revision':rev,'handler':'厂长','note':'上豆'})
        self.assertEqual(result['department'],'豆腐线')
    def test_incoming_requires_value_and_auto_return_valuation(self):
        with self.assertRaisesRegex(ValueError,'必须有金额'):self.material('receipt','10')
        with self.assertRaisesRegex(ValueError,'必须有金额'):self.material('return','10')
        self.material('receipt','10','40');self.material('consume','10');r=self.material('return','2');self.assertEqual(r['amount_cents'],800)
        with erp.connect() as c:self.assertTrue(all(e['amount_cents']>0 for e in rc.snapshot(c)['entries'] if e['kind'] in ('receipt','return')))

    def test_smoked_tofu_uses_white_tofu_and_migration_is_idempotent(self):
        with erp.connect(True) as c:
            row=c.execute("SELECT value FROM meta WHERE key='product_main_materials'").fetchone();data=json.loads(row[0]) if row else {};data['P006']='黄豆'
            c.execute("INSERT INTO meta VALUES('product_main_materials',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(data),));c.execute("DELETE FROM meta WHERE key='smoked_tofu_material_v0361'");c.execute("DELETE FROM schema_migrations WHERE id='047-product-materials'")
        erp.init_db()
        with erp.connect() as c:
            self.assertEqual(daily.main_material(c,{'id':'P006','name':'熏干'}),'白干')
            before=c.execute("SELECT COUNT(*) FROM audit WHERE action='修正熏干主要原料'").fetchone()[0]
            saved=daily.production_day(c,{'business_date':'2020-01-01','systems':{'tofu':{},'skin':{}},'products':[{'product_id':'P006','large_tanks':'2','small_tanks':'0'}]},None,fm.settings(c));self.assertEqual(saved['products'],[])
        erp.init_db()
        with erp.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='修正熏干主要原料'").fetchone()[0],before)

    def test_two_tank_form_omits_skin_tanks_without_losing_tofu_calculation(self):
        saved=self.record(products=[{'product_id':'P001','system':'tofu','large_tanks':'10','small_tanks':'0'}])
        self.assertEqual(saved['products'][0]['skin_tanks'],'0')
        with erp.connect() as c:report=fm.daily_report(c,'2026-10-20')
        tofu=next(p for p in report['products'] if p['product_id']=='P001')
        self.assertEqual(tofu['slurry_bean_kg'],'330')
        self.assertEqual(saved['systems']['skin']['soak_tanks'],'1')


    def test_each_bean_registration_keeps_own_warehouse_and_can_be_voided_or_restored(self):
        self.material('receipt','1000','4000');self.material('receipt','1000','4000',warehouse='WH-SKIN')
        with erp.connect() as c:rev=rc.revision(c)
        key=str(uuid.uuid4())
        b={'business_date':'2026-10-20','entries':[{'production_system_id':'tofu','warehouse_id':'WH-TOFU','qty':'100'},
            {'production_system_id':'tofu','warehouse_id':'WH-SKIN','qty':'50'},
            {'production_system_id':'skin','warehouse_id':'WH-SKIN','qty':'200'}],
            'revision':rev,'handler':'测试厂长','note':'两个库房同时上豆','soak_tanks':{'tofu':'2','skin':'1'},'request_key':key}
        first=self.call('beans',b);self.assertEqual(self.call('beans',b),first)
        self.assertEqual(len(first['entry_ids']),3)
        with erp.connect() as c:
            saved=next(json.loads(r[0]) for r in c.execute('SELECT payload FROM factory_daily'))
            self.assertEqual(saved['systems']['tofu']['soak_tanks'],'2')
            self.assertEqual(saved['systems']['skin']['soak_tanks'],'1')
        with erp.connect() as c:
            self.assertEqual(daily.issue_kg(c,'2026-10-20'),{'tofu':'150','skin':'200'})
            registered=[r for r in fm.bean_registrations(c) if r['business_date']=='2026-10-20']
            self.assertEqual(len(registered),3)
            self.assertEqual({r['warehouse_id'] for r in registered if r['production_system_id']=='tofu'},{'WH-TOFU','WH-SKIN'})
            tofu_extra=next(r for r in registered if r['warehouse_id']=='WH-TOFU')
        deleted=self.call('bean-void',{'id':tofu_extra['id'],'version':tofu_extra['version'],'reason':'重复登记','revision':rev,'request_key':str(uuid.uuid4())})
        self.assertTrue(deleted['voided'])
        with erp.connect() as c:
            self.assertEqual(daily.issue_kg(c,'2026-10-20'),{'tofu':'50','skin':'200'})
            self.assertTrue(next(r for r in fm.bean_registrations(c) if r['id']==tofu_extra['id'])['voided'])
            rev=rc.revision(c)
        restored=self.call('bean-restore',{'id':tofu_extra['id'],'version':deleted['version'],'reason':'撤销误删','revision':rev,'request_key':str(uuid.uuid4())})
        self.assertFalse(restored['voided'])
        with erp.connect() as c:self.assertEqual(daily.issue_kg(c,'2026-10-20'),{'tofu':'150','skin':'200'})
        with erp.connect() as c:rev=rc.revision(c)
        with self.assertRaisesRegex(ValueError,'同一库房'):self.call('beans',{'business_date':'2026-10-20','entries':[{'production_system_id':'tofu','warehouse_id':'WH-TOFU','qty':'1'},{'production_system_id':'tofu','warehouse_id':'WH-TOFU','qty':'2'}],'revision':rev,'handler':'测试','request_key':str(uuid.uuid4())})
        with self.assertRaisesRegex(ValueError,'有效库房'):self.call('beans',{'business_date':'2026-10-20','entries':[{'production_system_id':'tofu','warehouse_id':'WH-COMMON','qty':'1'}],'revision':rev,'handler':'测试','request_key':str(uuid.uuid4())})
        with self.assertRaises(ValueError):self.call('bean-void',{'id':tofu_extra['id'],'version':1,'reason':'旧版本','revision':rev,'request_key':str(uuid.uuid4())})
        with self.assertRaises(ValueError):self.call('bean-restore',{'id':tofu_extra['id'],'version':restored['version'],'reason':'误操作','revision':rev,'request_key':str(uuid.uuid4())})

    def test_report_missing_fields_name_responsible_roles(self):
        with erp.connect() as c:
            report=fm.daily_report(c,'2026-10-20');row=next(p for p in report['products'] if p['product_id']=='P001')
            missing={m['field']:m['owner'] for m in row['missing_data']}
            self.assertEqual(missing['期初库存'],'库管');self.assertEqual(missing['盘库结存'],'库管')
            self.assertEqual(missing['该产品所用大豆腐 / 中豆腐浆缸数'],'厂长')
            self.assertEqual(row['unit_net_kg'],'18');self.assertIsNone(row['net_kg'])

    def test_partial_soak_registration_preserves_unfilled_system_and_pending_state(self):
        self.material('receipt','100','400')
        with erp.connect() as c:rev=rc.revision(c)
        self.call('beans',{'business_date':'2026-10-20','entries':[{'production_system_id':'tofu','warehouse_id':'WH-TOFU','qty':'10'}],
            'soak_tanks':{'tofu':'1'},'revision':rev,'handler':'厂长'})
        with erp.connect() as c:
            record=rc.rows(c,'factory_daily')[0]
            self.assertEqual(record['systems'],{'tofu':{'soak_tanks':'1','state':'pending'},'skin':{'soak_tanks':'','state':'pending'}})
            self.assertEqual(daily.issue_kg(c,'2026-10-20')['tofu'],'10')
            self.assertEqual(fm.daily_report(c,'2026-10-20')['record'],record)

    def test_stopped_system_blocks_positive_beans_or_soak_without_changing_records(self):
        record=self.record(systems={'tofu':{'state':'stopped','soak_tanks':'0'},'skin':{'state':'running','soak_tanks':''}},products=[])
        self.material('receipt','100','400');self.material('receipt','100','400',warehouse='WH-SKIN')
        with erp.connect() as c:rev=rc.revision(c)
        for sid,soak in [('tofu',{}),('tofu',{'tofu':'1'}),('skin',{'tofu':'1'})]:
            with self.assertRaisesRegex(ValueError,'确认开机状态'):
                self.call('beans',{'business_date':'2026-10-20','entries':[{'production_system_id':sid,'warehouse_id':'WH-TOFU' if sid=='tofu' else 'WH-SKIN','qty':'10'}],
                    'soak_tanks':soak,'revision':rev,'handler':'厂长'})
        with erp.connect() as c:
            self.assertEqual(rc.rows(c,'factory_daily')[0],record)
            self.assertFalse(any(e['kind']=='consume' for e in rc.rows(c,'material_entries')))

    def test_future_closed_cost_month_blocks_bean_void_and_restore(self):
        self.material('receipt','100','400')
        with erp.connect() as c:rev=rc.revision(c)
        saved=self.call('beans',{'business_date':'2026-10-20','entries':[{'production_system_id':'tofu','warehouse_id':'WH-TOFU','qty':'10'}],
            'revision':rev,'handler':'厂长'})
        eid=saved['entry_ids'][0]
        with erp.connect(True) as c:
            rc.Operations(c,erp.now,erp.audit).period({'month':'2026-11','state':'closed','version':0,'note':'后续月结账'},'会计')
            before=rc.material_ledger(c,'2026-11-30')
        with self.assertRaisesRegex(ValueError,'后续成本月份已结账'):
            self.call('bean-void',{'id':eid,'version':1,'reason':'误录'})
        with erp.connect(True) as c:
            self.assertEqual(rc.material_ledger(c,'2026-11-30'),before)
            rc.Operations(c,erp.now,erp.audit).period({'month':'2026-11','state':'open','version':1,'note':'重开'},'会计')
        voided=self.call('bean-void',{'id':eid,'version':1,'reason':'误录'})
        with erp.connect(True) as c:
            rc.Operations(c,erp.now,erp.audit).period({'month':'2026-11','state':'closed','version':2,'note':'重新结账'},'会计')
            before=rc.material_ledger(c,'2026-11-30')
        with self.assertRaisesRegex(ValueError,'后续成本月份已结账'):
            self.call('bean-restore',{'id':eid,'version':voided['version'],'reason':'误删'})
        with erp.connect() as c:self.assertEqual(rc.material_ledger(c,'2026-11-30'),before)

class SelectedTankConversionTests(unittest.TestCase):
    def test_all_products_use_selected_tanks_and_mix_by_counts(self):
        cfg={'large_slurry_crates':'4','large_slurry_kg':'33','small_slurry_crates':'10','small_slurry_kg':'40'}
        value,formula=daily.selected_tank_conversion({'large_tanks':'2'},cfg,Decimal('8'),'筐');self.assertEqual(value,Decimal('66'))
        value,formula=daily.selected_tank_conversion({'large_tanks':'2','small_tanks':'1'},cfg,Decimal('18'),'筐');self.assertEqual(value,Decimal('106'));self.assertIn('加权',formula)
        self.assertIsNone(daily.selected_tank_conversion({'skin_tanks':'1'},cfg,Decimal('10'),'包')[0])
        self.assertIsNone(daily.selected_tank_conversion({},cfg,Decimal('10'),'筐')[0])

    def test_non_soy_products_are_excluded_from_slurry_registration(self):
        temp=tempfile.TemporaryDirectory();old=erp.DB;erp.DB=Path(temp.name)/'materials.db'
        try:
            erp.init_db()
            with erp.connect(True) as c:
                c.execute("INSERT INTO products VALUES('KONJAC','魔芋','筐','1','0',NULL)");c.execute("INSERT INTO products VALUES('JELLY','凉粉','筐','1','0',NULL)")
                self.assertEqual(daily.main_material(c,{'id':'KONJAC','name':'魔芋'}),'魔芋')
                self.assertEqual(daily.main_material(c,{'id':'JELLY','name':'凉粉'}),'淀粉')
                result=daily.production_day(c,{'business_date':'2020-01-01','systems':{'tofu':{},'skin':{}},'products':[{'product_id':pid,'large_tanks':'2','small_tanks':'0','skin_tanks':'0'} for pid in ['P001','KONJAC','JELLY']]},None,fm.settings(c))
                self.assertEqual([r['product_id'] for r in result['products']],['P001']);self.assertEqual(result['products'][0]['main_material'],'黄豆')
        finally:erp.DB=old;temp.cleanup()

    def test_sales_region_summary_and_filters(self):
        temp=tempfile.TemporaryDirectory();old=erp.DB;erp.DB=Path(temp.name)/'region.db'
        try:
            erp.init_db()
            with erp.connect(True) as c:
                c.execute("UPDATE customers SET region='地区甲',route='同名市场' WHERE id='C001'");c.execute("UPDATE customers SET region='地区乙',route='同名市场' WHERE id='C002'")
                allrows=fm.sales_report(c,'2000-01-01','2099-01-01');selected=fm.sales_report(c,'2000-01-01','2099-01-01','地区甲')
                self.assertIn('地区甲',allrows['region_options']);self.assertTrue(selected['customers']);self.assertTrue(all(r['region']=='地区甲' for r in selected['customers']));self.assertTrue(all(r['region']=='地区甲' for r in selected['markets']));self.assertEqual([r['region'] for r in selected['regions']],['地区甲'])
                self.assertTrue(all(r['region']=='地区甲' for r in selected['receivable_alerts']))
        finally:erp.DB=old;temp.cleanup()

