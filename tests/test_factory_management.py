import unittest,tempfile,uuid,json
from pathlib import Path
from decimal import Decimal
import test_workflow as fixture
import production_management as fm
import resources_costs as rc
import erp_access as access

erp=fixture.erp
class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.old=erp.DB;self.temp=tempfile.TemporaryDirectory();erp.DB=Path(self.temp.name)/'factory.db';erp.init_db()
    def tearDown(self):erp.DB=self.old;self.temp.cleanup()
    def call(self,kind,body,role='管理员'):
        with erp.connect(True) as c:return fm.save(c,kind,{'request_key':str(uuid.uuid4()),**body},role,erp.now,erp.audit)
    def employee(self):return self.call('employee',{'name':'测试员工','group_id':'G-TOFU'})
    def attendance(self,e,**extra):return self.call('attendance',{'business_date':'2026-10-20','name':'夜班','entries':[{'employee_id':e['id'],'group_id':'G-TOFU','start':'2026-10-20T22:00','end':'2026-10-21T02:00','break_minutes':'30'}],**extra})
    def production_run(self,**extra):return self.call('run',{'business_date':'2026-10-20','system':'tofu','batch_name':'测试批次','dry_kg':'330','bags':'11','bag_kg':'30','soak_tanks':'0.6','outputs':[{'product_id':'P001','qty':'40','net_kg':'800','tank_type':'large','slurry_tanks':'10','conversion_confirmed':True}],**extra})
    def material(self,kind,q,cost='0',warehouse='WH-TOFU',**extra):
        with erp.connect(True) as c:return rc.Operations(c,erp.now,erp.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':'RM-SOY','business_date':'2026-10-20','kind':kind,'qty':q,'amount':cost,'warehouse_id':warehouse,'note':'测试','handler':'测试',**extra},'管理员')
    def test_cross_midnight_dynamic_groups_overlap_and_plan(self):
        e=self.employee();r=self.attendance(e);self.assertEqual(r['entries'][0]['hours'],'3.5')
        with self.assertRaisesRegex(ValueError,'重叠'):self.attendance(e)
        entries=[{'employee_id':e['id'],'group_id':'G-TOFU','start':'2026-10-21T08:00','end':'2026-10-21T10:00'},{'employee_id':e['id'],'group_id':'G-SKIN','start':'2026-10-21T10:00','end':'2026-10-21T12:00'}]
        actual=self.attendance(e,entries=entries);self.assertEqual(sum(Decimal(r['hours']) for r in actual['entries']),4)
        entries[1]['start']='2026-10-21T09:00'
        with self.assertRaisesRegex(ValueError,'重复分组'):self.attendance(e,entries=entries)
    def test_calculation_snapshots_and_unknown_skin_are_not_zero(self):
        run=self.production_run();a=fm.run_analysis(run);self.assertTrue(all(m['kg']=='330' for m in a['methods']));self.assertEqual(a['yield_kg_per_kg'],str(Decimal(800)/330))
        skin=self.production_run(system='skin',outputs=[{'product_id':'P003','qty':'20','net_kg':'40','tank_type':'skin','slurry_tanks':'2'}]);a=fm.run_analysis(skin)
        self.assertIsNone(a['methods'][3]['kg']);self.assertIsNone(a['methods'][4]['kg'])
        with erp.connect(True) as c:
            cfg=fm.settings(c);fm.save(c,'settings',{**cfg,'large_slurry_kg':'35'},'管理员',erp.now,erp.audit)
        self.assertEqual(fm.run_analysis(run)['methods'][3]['kg'],'330')
    def test_fifo_four_warehouses_quality_transfer_and_cents(self):
        self.material('receipt','10','40',warehouse='WH-MAIN',quality={'batch_no':'A','protein_pct':'42','soluble_protein_pct':'8','moisture_pct':'12'})
        self.material('receipt','10','60',warehouse='WH-MAIN',quality={'batch_no':'B'})
        self.material('transfer','12',warehouse='WH-MAIN',target_warehouse_id='WH-TOFU');self.material('consume','11')
        with erp.connect() as c:
            snapshot=rc.snapshot(c);last=snapshot['entries'][-1];stock=next(s for s in snapshot['warehouse_stocks'] if s['id']=='RM-SOY' and s['warehouse_id']=='WH-TOFU')
        self.assertEqual(last['cost_cents'],4600);self.assertEqual(stock['value_cents'],600)
        self.assertEqual(last['fifo_allocations'][0]['quality']['batch_no'],'A');self.assertEqual(last['fifo_allocations'][1]['quality']['batch_no'],'B')
        with self.assertRaisesRegex(ValueError,'库存不足'):self.material('consume','2')
        with self.assertRaisesRegex(ValueError,'100%'):self.material('receipt','1','4',quality={'protein_pct':'101'})
    def test_post_is_explicit_atomic_idempotent_and_reversible(self):
        run=self.production_run()
        with erp.connect() as c:revision=erp.inventory.revision(c);before=erp.inventory.stock(c,'2026-10-20')
        body={'kind':'run','id':run['id'],'version':run['version'],'inventory_revision':revision,'evidence_checked':True}
        posted=self.call('post-output',body);self.assertTrue(posted['posted']);self.assertEqual(self.call('post-output',body),posted)
        with erp.connect() as c:
            stock=erp.inventory.stock(c,'2026-10-20');self.assertEqual(next(p for p in stock['products'] if p['product_id']=='P001')['production_qty'],'40');revision=erp.inventory.revision(c)
        undone=self.call('undo-output',{**body,'version':posted['version'],'inventory_revision':revision});self.assertFalse(undone['posted'])
        with erp.connect() as c:self.assertEqual(next(p for p in erp.inventory.stock(c,'2026-10-20')['products'] if p['product_id']=='P001')['production_qty'],'0')
    def test_scrap_cannot_go_negative_or_double_count_in_main_yield(self):
        with self.assertRaisesRegex(ValueError,'可用量不足'):self.call('scrap',{'business_date':'2026-10-20','action':'process','kg':'10','outputs':[{'product_id':'P004','qty':'2'}],'note':'转素鸡'})
        self.call('scrap',{'business_date':'2026-10-20','action':'in','kg':'20','note':'当日产出烂豆皮'})
        self.call('scrap',{'business_date':'2026-10-20','action':'process','kg':'12','outputs':[{'product_id':'P004','qty':'2'}],'note':'转素鸡'})
        with erp.connect() as c:self.assertEqual(fm.scrap_ledger(c)['balance_kg'],'8');self.assertEqual(fm.sales_report(c,'2026-10-20','2026-10-20')['yields'],[])
    def test_director_permissions_and_staff_privacy(self):
        grants=access.defaults('厂长');self.assertIn('厂长',erp.auth.ROLES);self.assertIn('production.record',grants['actions']);self.assertNotIn('finance.receipt',grants['actions'])
        self.employee()
        with erp.connect() as c:result=fm.scope(fm.snapshot(c),access.defaults('老板'))
        self.assertEqual(result['employees'],[]);self.assertEqual(result['attendance'],[])
        with self.assertRaises(ValueError):self.call('run',{},'出纳')
    def test_fifo_cutover_preserves_legacy_cost_and_mixed_uncosted(self):
        with erp.connect(True) as c:c.execute("DELETE FROM meta WHERE key='material_fifo_start'");c.execute("DELETE FROM schema_migrations WHERE id='032-material-fifo'")
        self.material('receipt','10','40');legacy=self.material('receipt','10','40')
        # Simulate an imported pre-upgrade unpriced receipt; new receipts require a value.
        with erp.connect(True) as c:
            legacy['amount_cents']=0;c.execute('UPDATE material_entries SET payload=? WHERE id=?',(rc.dump(legacy),legacy['id']))
        self.material('consume','4')
        with erp.connect(True) as c:
            old=rc.snapshot(c);rc.init_schema(c)
            self.assertEqual(rc.snapshot(c)['entries'][-1]['cost_cents'],old['entries'][-1]['cost_cents'])
        self.material('receipt','4','24');self.material('consume','8')
        with erp.connect() as c:
            stock=next(w for w in rc.snapshot(c)['warehouse_stocks'] if w['id']=='RM-SOY' and w['warehouse_id']=='WH-TOFU')
            self.assertEqual(stock['uncosted_qty'],'4');self.assertTrue(stock['lots'][0]['legacy'])

    def test_trial_archive_restores_production_records_with_request_keys(self):
        run=self.production_run()
        with erp.connect() as c:
            rev=erp.inventory.revision(c);epoch=erp.business_epoch(c)
            counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('orders','receipts','archived_orders')}
        self.call('post-output',{'kind':'run','id':run['id'],'version':run['version'],'inventory_revision':rev,'evidence_checked':True})
        archived=erp.trial_data({'action':'archive','reason':'测试整轮归档','expected':counts,'_data_epoch':epoch},'会计')
        with erp.connect() as c:self.assertEqual(fm.rows(c,'run'),[])
        erp.trial_data({'action':'restore','id':archived['id'],'_data_epoch':archived['business_data_epoch']},'会计')
        with erp.connect() as c:self.assertTrue(fm.get(c,'run',run['id'])['posted'])

    def test_role_upgrade_preserves_sessions_and_activity(self):
        import sqlite3,auth,time
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        auth.init_schema(c);u=auth.create_initial_admin(c,'admin','测试','Factory-Test-Password!',int(time.time()));token=auth.login(c,'admin','Factory-Test-Password!','test',int(time.time()))
        # Reinitializing current schema must preserve every account/session/activity value.
        before={t:[dict(r) for r in c.execute('SELECT * FROM '+t)] for t in ['auth_users','auth_sessions','auth_session_activity']}
        auth.init_schema(c)
        self.assertEqual(before,{t:[dict(r) for r in c.execute('SELECT * FROM '+t)] for t in before});c.close()

    def test_ar_threshold_strict_and_weight_count_is_weighted(self):
        with erp.connect(True) as c:
            for i,qty,gross in [(1,'2','100'),(2,'8','320')]:
                o={'id':'T'+str(i),'customer_id':'C001','customer_name':'测试客户','business_date':'2026-10-10','state':'reviewed','total_cents':1000001,'lines':[{'product_id':'P001','product_name':'大豆腐','unit':'筐','actual_qty':qty,'driver':[{'gross':gross,'count':qty,'tare':'0'}],'customer':[]}]}
                c.execute('INSERT INTO orders VALUES(?,?)',(o['id'],rc.dump(o)))
            report=fm.weight_report(c,'2026-10-10');self.assertEqual(report[0]['driver_average'],'42')
            alert=next(r for r in fm.ar_alerts(c,'2026-10-20') if r['customer_id']=='C001');self.assertTrue(alert['amount_alert']);self.assertTrue(alert['days_alert'])

    def test_weight_reference_and_missing_weights_do_not_create_fake_averages(self):
        with erp.connect(True) as c:
            c.execute('DELETE FROM orders')
            for i,qty,driver in [(1,'2',[{'gross':'36','count':'2','tare':'0'}]),(2,'8',[])]:
                o={'id':'REF'+str(i),'customer_id':'C001','customer_name':'测试客户','business_date':'2026-10-10','state':'dispatched','lines':[{'product_id':'P001','product_name':'大豆腐','unit':'筐','actual_qty':qty,'driver':driver,'customer':[]}]}
                c.execute('INSERT INTO orders VALUES(?,?)',(o['id'],rc.dump(o)))
            row=fm.weight_report(c,'2026-10-10')[0]
            self.assertEqual(row['qty'],'10');self.assertIsNone(row['net_kg']);self.assertIsNone(row['average'])
            self.assertEqual(row['day_average'],'18');self.assertIsNone(row['trip_average']);self.assertTrue(row['alert'])
            self.assertEqual(row['default_average_kg'],'18');self.assertTrue(any('未登记完整' in n for n in row['notes']))
            c.execute("DELETE FROM orders WHERE id='REF2'")
            c.execute("INSERT INTO meta VALUES('product_average_weights',?)",(json.dumps({'P001':'10'}),))
            row=fm.weight_report(c,'2026-10-10')[0]
            self.assertEqual(row['net_kg'],'36');self.assertEqual(row['average'],'18');self.assertTrue(row['alert'])
            self.assertTrue(any('每筐多于标准 8kg' in n for n in row['notes']))
