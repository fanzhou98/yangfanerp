import json, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import patch
import test_workflow as fixture
import owner_analysis as owner
import resources_costs as rc
import production_management as fm

erp = fixture.erp

class OwnerAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.mock=patch.object(erp,'DB',Path(self.temp.name)/'owner.db');self.mock.start();erp.init_db()
    def tearDown(self):self.mock.stop();self.temp.cleanup()
    def material(self,c,kind,q,amount='0',wid='WH-TOFU',**extra):
        return rc.Operations(c,erp.now,erp.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'business_date':'2026-10-20','material_id':'RM-SOY','warehouse_id':wid,'kind':kind,'qty':q,'amount':amount,'handler':'测试','note':'测试',**extra},'管理员')
    def test_quality_validates_enum_and_preserves_unknown(self):
        self.assertEqual(rc.quality({})['origin'],'')
        self.assertEqual(rc.quality({'quality':{'origin':'伊犁','sowing_type':'春播'}})['sowing_type'],'春播')
        for field,value in [('origin','未知省'),('sowing_type','夏播')]:
            with self.assertRaisesRegex(ValueError,'无效'):rc.quality({field:value})
    def test_fifo_transfer_composition_uses_remaining_lots(self):
        with erp.connect(True) as c:
            self.material(c,'receipt','100','400',quality={'origin':'伊犁','sowing_type':'春播','protein_pct':'40','moisture_pct':'10'})
            self.material(c,'receipt','200','1000',quality={'origin':'东北','sowing_type':'复播','protein_pct':'42','moisture_pct':'12'})
            self.material(c,'consume','50')
            self.material(c,'transfer','100',target_warehouse_id='WH-SKIN')
            _,_,ws=rc.material_ledger(c,warehouse_details=True)
            rows={w['warehouse_id']:w for w in owner.soy_composition([w for w in ws if w['id']=='RM-SOY'])}
            self.assertEqual(rows['WH-TOFU']['origins']['东北'],'150')
            self.assertEqual(rows['WH-SKIN']['sowing'],{'春播':'50','复播':'50','未登记':'0'})
            self.assertEqual(rows['WH-SKIN']['average_price'],'4.5')
            self.assertEqual(rows['WH-SKIN']['average_protein'],'41')
    def test_quality_supplement_changes_no_quantities_or_values_and_is_versioned(self):
        with erp.connect(True) as c:
            entry=self.material(c,'receipt','100','400');before=rc.material_ledger(c)[0]
            body={'id':entry['id'],'version':1,'revision':rc.revision(c),'quality':{'sowing_type':'复播','origin':'河南'},'note':'检测单补录'}
            with self.assertRaises(ValueError):rc.Operations(c,erp.now,erp.audit).quality(body,'库管')
            updated=rc.Operations(c,erp.now,erp.audit).quality(body,'会计')
            self.assertEqual(updated['version'],2);self.assertEqual(updated['amount_cents'],entry['amount_cents'])
            self.assertEqual(rc.material_ledger(c)[0],before)
            self.assertEqual(updated['quality_history'][0]['before']['origin'],'')
            with self.assertRaisesRegex(ValueError,'变更'):rc.Operations(c,erp.now,erp.audit).quality(body,'会计')
    def test_cost_net_returns_monthly_allocation_and_unknowns(self):
        with erp.connect(True) as c:
            self.material(c,'receipt','1000','4000');self.material(c,'consume','100');self.material(c,'return','10')
            rc.Operations(c,erp.now,erp.audit).expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','period':'2026-10','category':'electricity','amount':'310','handler':'测试','note':'电费'},'管理员')
            r=owner.report(c,'2026-10-20');cost=r['cost']
            self.assertEqual(cost['material_cents'],36000);self.assertEqual(cost['allocated_expense_cents'],1000)
            self.assertEqual(cost['total_cents'],37000)
            self.assertTrue(any('生产工资' in m['field'] for m in cost['missing_data']))
            self.assertIsNone(r['accounts']['overdue_receivable_cents'])
    def test_transport_trips_enter_daily_cost_without_double_counting(self):
        with erp.connect(True) as c:
            self.material(c,'receipt','1000','4000');self.material(c,'consume','100')
            rc.Operations(c,erp.now,erp.audit).expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','period':'2026-10','category':'transport','amount':'620','handler':'测试','note':'运输月结','source_document_id':'YS-TEST'},'管理员',_system_source='transport-settlement')
            c.execute('INSERT INTO trade_records VALUES(?,?)',('TRIP-COST',json.dumps({'id':'TRIP-COST','kind':'trip','business_date':'2026-10-20','amount_cents':12000,'partner':'运输公司','voided':False})))
            cost=owner.report(c,'2026-10-20')['cost']
            self.assertEqual(cost['transport_cents'],12000)
            self.assertEqual(cost['allocated_expense_cents'],0)
            self.assertEqual(cost['material_cents'],40000)
            self.assertEqual(cost['total_cents'],40000+12000)
            self.assertIsNone(cost['difference_cents']) # 没有已复核收入，不能把无单据冒充0收入
            self.assertEqual(cost['bridge']['points'],[])

    def test_driver_home_history_does_not_include_other_drivers(self):
        import driver_portal,auth,time
        with erp.connect(True) as c:
            admin=auth.create_initial_admin(c,'admin','测试','Owner-Scope-Test-2026!',int(time.time()))
            user=auth.create_user(c,admin,{'username':'driver','display_name':'测试司机','role':'司机','password':'Owner-Scope-Test-2026!'},int(time.time()))
            r=driver_portal.report(c,user,'2026-10-21')
            self.assertEqual(r['home_work'],{'weight_items':[],'weight_completed':0})
            self.assertNotIn('cents',json.dumps(r['home_work']))
    def test_confirmed_wages_and_byproduct_receivables_are_in_balances(self):
        with erp.connect(True) as c:
            for ident,record in [('S',{'kind':'sheet','state':'confirmed','month':'2026-09','rows':[{'net_cents':10000}]}),('P',{'kind':'payment','month':'2026-09','amount_cents':3000})]:
                c.execute('INSERT INTO payroll_records VALUES(?,?,?)',(ident,ident,rc.dump(record)))
            c.execute('INSERT INTO byproduct_sales VALUES(?,?,?)',('B','B',rc.dump({'business_date':'2026-10-01','buyer':'测试豆渣客户','amount_cents':5000,'received_cents':2000})))
            r=owner.accounts(c,'2026-10-20');self.assertEqual(r['undated_payable_cents'],7000);self.assertEqual(r['byproduct_receivable_cents'],3000)
            self.assertEqual(sum(x['cents'] for x in r['aging']),r['receivable_cents'])
    def test_legacy_combined_attendance_is_not_reported_as_zero_schedule(self):
        with erp.connect(True) as c:
            old={'business_date':'2026-10-20','state':'confirmed','format':'group-day-v2','groups':[{'group_id':'G-TOFU','start_time':'08:00'}],'entries':[{'employee_id':'E1','employee_name':'测试员工','group_id':'G-TOFU','status':'full'}]}
            c.execute('INSERT INTO factory_attendance VALUES(?,?,?)',('A','A',rc.dump(old)))
            people=owner.people(c,'2026-10-20');self.assertEqual(people['schedule_source'],'legacy-combined')
            self.assertEqual(people['rows'][0]['planned_status'],'full');self.assertEqual(people['rows'][0]['planned_start'],'08:00')

    def test_people_group_sort_uses_actual_group_and_handles_unplanned_staff(self):
        with erp.connect(True) as c:
            planned={'business_date':'2026-10-20','state':'confirmed','entries':[{'employee_id':'A','employee_name':'甲','group_id':'G-TOFU','status':'full'},{'employee_id':'B','employee_name':'乙','group_id':'G-SKIN','status':'full'},{'employee_id':'C','employee_name':'丙','group_id':'G-TOFU','status':'full'}]}
            actual={'business_date':'2026-10-20','state':'confirmed','workflow':'separate-v1','entries':[{'employee_id':'C','employee_name':'丙','group_id':'G-SKIN','status':'full'},{'employee_id':'D','employee_name':'丁','group_id':'G-DRY','status':'full'}]}
            for table,record in [('factory_schedules',planned),('factory_attendance',actual)]:c.execute('INSERT INTO '+table+' VALUES(?,?,?)',('SORT','SORT',rc.dump(record)))
            before=c.total_changes;rows=owner.people(c,'2026-10-20')['rows'];self.assertEqual(c.total_changes,before)
            self.assertEqual([r['group_id'] for r in rows],['G-SKIN','G-SKIN','G-TOFU','G-DRY'])
            moved=next(r for r in rows if r['employee_name']=='丙');self.assertEqual(moved['planned_group'],'豆腐组');self.assertEqual(moved['group_name'],'豆皮组')

    def test_report_does_not_write_or_expose_payroll_profiles(self):
        with erp.connect(True) as c:
            before=c.total_changes;r=owner.report(c,'2026-10-21');self.assertEqual(c.total_changes,before)
            self.assertNotIn('monthly_cents',json.dumps(r));self.assertEqual(len(r['trend']),14)
            self.assertTrue(all('missing_data' in p for p in r['products']))
    def test_payable_due_priority_and_current_balance_are_explicit(self):
        projection={'orders':[{'id':'O'}],'payments':[{'order_id':'O','amount_cents':150}], 'receipts':[
            {'id':'R1','order_id':'O','supplier_name':'测试甲','business_date':'2026-10-01','due_date':'2026-10-10','amount_cents':100},
            {'id':'R2','order_id':'O','supplier_name':'测试甲','business_date':'2026-10-01','due_date':'2026-10-25','amount_cents':200}], 'charges':[{'business_date':'2026-10-01','due_date':'2026-10-19','payee_name':'运费','outstanding_cents':50}]}
        with erp.connect() as c,patch.object(owner.purchasing,'projection',return_value=projection):
            r=owner.accounts(c,'2026-10-20');self.assertEqual(r['payable_cents'],200);self.assertEqual(r['overdue_payable_cents'],50)

if __name__=='__main__':unittest.main()
