import unittest,tempfile,uuid,json
from pathlib import Path
from decimal import Decimal
import server as erp,resources_costs as rc,purchasing as p,erp_access as access
from ops.business_check import check_database
class WarehouseLandedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=erp.DB;erp.DB=Path(self.temp.name)/'test.db';erp.init_db();self.ctx=erp.connect(True);self.c=self.ctx.__enter__();self.r=rc.Operations(self.c,erp.now,erp.audit);self.p=p.Operations(self.c,erp.now,erp.audit)
        self.s=self.p.supplier({'name':'大豆供应商','payment_days':0},'会计');self.carrier=self.p.supplier({'name':'运输装卸公司','payment_days':0},'会计')
    def tearDown(self):self.c.rollback();self.ctx.__exit__(None,None,None);erp.DB=self.old;self.temp.cleanup()
    def material(self,kind,q,amount='0',wh='WH-TOFU',**extras):
        self.c.execute('SAVEPOINT test_material')
        try:
            result=self.r.material({'material_id':'RM-SOY','warehouse_id':wh,'kind':kind,'qty':q,'amount':amount,'business_date':'2026-10-20','handler':'测试','note':'测试','request_key':str(uuid.uuid4()),'revision':rc.revision(self.c),**extras},'会计')
            self.c.execute('RELEASE test_material');return result
        except Exception:
            self.c.execute('ROLLBACK TO test_material');self.c.execute('RELEASE test_material');raise
    def stock(self,wh):return next(s for s in rc.material_ledger(self.c,warehouse_details=True)[2] if s['id']=='RM-SOY' and s['warehouse_id']==wh)
    def order(self):
        o=self.p.order({'supplier_id':self.s['id'],'business_date':'2026-10-20','expected_date':'2026-10-20','handler':'采购','request_key':str(uuid.uuid4()),'lines':[{'material_id':'RM-SOY','warehouse_id':'WH-TOFU','qty':'600','price':'4'},{'material_id':'RM-SOY','warehouse_id':'WH-SKIN','qty':'400','price':'5'}]},'会计')
        return self.p.confirm({'id':o['id'],'version':o['version']},'会计')
    def receipt(self,o,charges=None):return self.p.receipt({'id':o['id'],'version':o['version'],'business_date':'2026-10-20','lines':[{'line_id':'L1','qty':'600'},{'line_id':'L2','qty':'400'}],'charges':charges or [],'handler':'库管','note':'合格验收','request_key':str(uuid.uuid4()),'revision':rc.revision(self.c)},'会计')
    def fee(self,receipt,**extras):return self.p.charge({'receipt_id':receipt['id'],'business_date':'2026-10-20','kind':'freight','billing_qty':'1','billing_unit':'吨','rate':'200','supplier_id':self.carrier['id'],'handler':'会计','note':'运输费用','request_key':str(uuid.uuid4()),'revision':rc.revision(self.c),**extras},'会计')
    def test_warehouses_separate_quantity_cost_and_transfer(self):
        self.material('opening','10','40');self.material('opening','10','60',wh='WH-SKIN');self.material('consume','2');self.material('consume','2',wh='WH-SKIN')
        self.assertEqual(self.stock('WH-TOFU')['value_cents'],3200);self.assertEqual(self.stock('WH-SKIN')['value_cents'],4800)
        with self.assertRaisesRegex(ValueError,'库存不足'):self.material('consume','9')
        self.material('transfer','3',target_warehouse_id='WH-SKIN');self.assertEqual(self.stock('WH-TOFU')['qty'],'5');self.assertEqual(self.stock('WH-SKIN')['qty'],'11');self.assertEqual(self.stock('WH-SKIN')['value_cents'],6000)
        entries=rc.snapshot(self.c)['entries'];self.assertEqual(entries[-1]['cost_cents'],0);self.assertEqual(entries[-1]['transfer_value_cents'],1200)
        self.material('count','4');self.assertEqual(self.stock('WH-TOFU')['qty'],'4')
    def test_soy_requires_warehouse_and_cannot_use_management_or_delivery(self):
        with self.assertRaisesRegex(ValueError,'请选择'):self.material('receipt','1','5',wh='')
        with self.assertRaisesRegex(ValueError,'产线'):self.material('receipt','1','5',department='配送')
        with self.assertRaisesRegex(ValueError,'请选择'):self.p.order({'supplier_id':self.s['id'],'business_date':'2026-10-20','expected_date':'2026-10-20','handler':'采购','request_key':'none','lines':[{'material_id':'RM-SOY','qty':'1','price':'5'}]},'会计')
    def test_fees_by_ton_and_kg_allocate_by_weight_not_price(self):
        o=self.order();r=self.receipt(o);freight=self.fee(r);unload=self.fee(r,kind='unloading',billing_qty='1000',billing_unit='公斤',rate='0.1')
        self.assertEqual(freight['amount_cents'],20000);self.assertEqual(unload['amount_cents'],10000)
        self.assertEqual([a['amount_cents'] for a in freight['allocations']],[12000,8000])
        self.assertEqual(self.stock('WH-TOFU')['value_cents'],258000);self.assertEqual(self.stock('WH-SKIN')['value_cents'],212000)
        snap=p.projection(self.c);self.assertEqual(snap['orders'][0]['received_cents'],440000);self.assertEqual(snap['orders'][0]['outstanding_cents'],440000);self.assertEqual(snap['orders'][0]['inventory_cost_cents'],470000);self.assertEqual(sum(c['outstanding_cents'] for c in snap['charges']),30000)
        self.material('consume','100');self.assertEqual(rc.snapshot(self.c)['entries'][-1]['cost_cents'],43000);self.assertEqual(rc.rows(self.c,'indirect_expenses'),[])
        self.p.charge_payment({'charge_id':freight['id'],'business_date':'2026-10-20','amount':'200','method':'现金','handler':'出纳','note':'已付运费','request_key':'payfee'},'出纳')
        self.assertEqual(p.projection(self.c)['orders'][0]['outstanding_cents'],440000);self.assertEqual(p.projection(self.c)['charges'][0]['outstanding_cents'],0)
        self.c.commit();self.assertTrue(check_database(erp.DB)['ok'],check_database(erp.DB))
    def test_people_payees_separate_from_goods_and_retained_for_next_selection(self):
        r=self.receipt(self.order())
        driver=self.fee(r,payee_type='driver',payee_id='new',payee_name='采购司机王师傅')
        worker=self.fee(r,kind='unloading',billing_qty='1000',rate='0.1',billing_unit='公斤',payee_type='worker',payee_id='new',payee_name='装卸李师傅')
        self.assertEqual(driver['supplier_id'],'');self.assertEqual(worker['payee_type'],'worker')
        self.assertEqual(driver['payee_name'],'采购司机王师傅');self.assertNotEqual(driver['payee_id'],worker['payee_id'])
        self.assertEqual(len(rc.rows(self.c,'purchase_payees')),2)
        again=self.fee(r,payee_type='driver',payee_id=driver['payee_id'])
        self.assertEqual(again['payee_name'],driver['payee_name']);self.assertEqual(len(rc.rows(self.c,'purchase_payees')),2)
        same=self.fee(r,payee_type='driver',payee_id='new',payee_name='采购司机王师傅')
        self.assertEqual(same['payee_id'],driver['payee_id'])
        payment=self.p.charge_payment({'charge_id':worker['id'],'business_date':'2026-10-20','amount':'100','method':'现金','handler':'出纳','note':'直接交给搬运工','request_key':'worker-pay'},'出纳')
        self.assertEqual(payment['payee_id'],worker['payee_id']);self.assertEqual(payment['payee_name'],'装卸李师傅')
        self.assertEqual(p.projection(self.c)['orders'][0]['outstanding_cents'],440000)
        self.c.commit();self.assertTrue(check_database(erp.DB)['ok'],check_database(erp.DB))
    def test_payee_requires_explicit_selection_and_checks_type_and_active_driver(self):
        r=self.receipt(self.order())
        with self.assertRaisesRegex(ValueError,'请选择'):self.fee(r,supplier_id='')
        with self.assertRaisesRegex(ValueError,'请选择'):self.fee(r,payee_type='',payee_id='')
        with self.assertRaisesRegex(ValueError,'姓名'):self.fee(r,payee_type='worker',payee_id='new',payee_name=' ')
        self.c.execute("INSERT INTO delivery_drivers VALUES('D999','外聘运输司机',1)")
        fee=self.fee(r,payee_type='driver',payee_id='fleet:D999')
        self.assertEqual(fee['payee_name'],'外聘运输司机')
        with self.assertRaisesRegex(ValueError,'不存在'):self.fee(r,payee_type='driver',payee_id='fleet:missing')
        self.c.execute("UPDATE delivery_drivers SET active=0 WHERE id='D999'")
        with self.assertRaisesRegex(ValueError,'停用'):self.fee(r,payee_type='driver',payee_id='fleet:D999')
        worker=self.fee(r,payee_type='worker',payee_id='new',payee_name='搬运员')
        with self.assertRaisesRegex(ValueError,'类型'):self.fee(r,payee_type='driver',payee_id=worker['payee_id'])
    def test_actual_prices_use_received_quantity_per_warehouse_and_update_after_fees(self):
        o=self.order();initial=p.projection(self.c)['orders'][0]
        self.assertIsNone(initial['lines'][0]['actual_unit_price'])
        r=self.p.receipt({'id':o['id'],'version':o['version'],'business_date':'2026-10-20','lines':[{'line_id':'L1','qty':'300'},{'line_id':'L2','qty':'200'}],'handler':'库管','note':'分批入库','request_key':'partial','revision':rc.revision(self.c)},'会计')
        self.fee(r,billing_qty='0.5',rate='200');self.fee(r,kind='unloading',billing_qty='500',billing_unit='公斤',rate='0.1')
        snap=p.projection(self.c);lines=snap['orders'][0]['lines']
        self.assertEqual([l['actual_unit_price'] for l in lines],['4.3','5.3'])
        self.assertEqual([l['charges_cents'] for l in lines],[9000,6000]);self.assertEqual([l['inventory_cost_cents'] for l in lines],[129000,106000])
        self.assertEqual([l['actual_unit_price'] for l in snap['receipts'][0]['lines']],['4.3','5.3'])
        original=p.get(self.c,'purchase_orders',o['id']);self.assertNotIn('actual_unit_price',original['lines'][0])
        warehouse=p.scope(snap,access.defaults('库管'));self.assertNotIn('actual_unit_price',json.dumps(warehouse))
        self.assertEqual(p.scope(snap,access.defaults('老板'))['orders'][0]['lines'][0]['actual_unit_price'],'4.3')
    def test_fees_reprice_unclosed_consumption_and_block_closed_history(self):
        r=self.receipt(self.order());self.material('consume','100');self.fee(r);self.assertEqual(rc.snapshot(self.c)['entries'][-1]['cost_cents'],42000)
        self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',('2026-10',1,rc.dump({'state':'closed'})))
        with self.assertRaisesRegex(ValueError,'结账'):self.fee(r)
    def test_fee_idempotency_permission_and_projection(self):
        r=self.receipt(self.order());b={'receipt_id':r['id'],'business_date':'2026-10-20','kind':'freight','billing_qty':'1','billing_unit':'吨','rate':'200','supplier_id':self.carrier['id'],'handler':'会计','note':'运费','request_key':'fee','revision':rc.revision(self.c)}
        a=self.p.charge(b,'会计');self.assertEqual(a,self.p.charge(b,'会计'))
        with self.assertRaises(ValueError):self.p.charge({**b,'request_key':'bad'},'库管')
        projected=access.scope_resources(rc.snapshot(self.c),access.defaults('库管'));encoded=json.dumps(projected);self.assertNotIn('warehouse_balance_cents',encoded);self.assertNotIn('value_cents',json.dumps(projected['warehouse_stocks']));self.assertNotIn('purchase_charge_history',encoded)
        v=p.scope(p.projection(self.c),access.defaults('库管'));self.assertNotIn('"rate"',json.dumps(v));self.assertNotIn('_cents',json.dumps(v))
    def test_reference_targets_and_cold_power_not_in_inventory(self):
        self.assertEqual(rc.attribution({'id':'A-SALT'})['default_cost_target'],'素鸡');self.assertEqual(rc.attribution({'id':'A-GYPSUM'})['default_cost_target'],'共用')
        e=self.r.expense({'business_date':'2026-10-20','category':'cold-power','amount':'10','handler':'会计','note':'冷库电费','request_key':'cold'},'会计');self.assertEqual(e['cost_target'],'冻豆腐');self.assertEqual(len(rc.snapshot(self.c)['entries']),0);self.assertNotIn('冷库电费',[m['name'] for m in rc.snapshot(self.c)['items']])
    def test_legacy_stock_stays_pending_and_explicit_warehouse_confirmation(self):
        o=self.order();r=self.receipt(o)
        # Simulate a pre-warehouse order and receipt without inventing any split.
        original=p.get(self.c,'purchase_orders',o['id'])
        for l in original['lines']:l.pop('warehouse_id');l.pop('warehouse_name',None)
        self.c.execute('UPDATE purchase_orders SET payload=? WHERE id=?',(rc.dump(original),o['id']))
        for l in r['lines']:
            e=p.get(self.c,'material_entries',l['material_entry_id']);e.pop('warehouse_id');e.pop('warehouse_name',None);self.c.execute('UPDATE material_entries SET payload=? WHERE id=?',(rc.dump(e),e['id']));l.pop('warehouse_id');l.pop('warehouse_name',None)
        self.c.execute('UPDATE purchase_receipts SET payload=? WHERE id=?',(rc.dump(r),r['id']))
        self.assertEqual(self.stock('WH-UNASSIGNED')['qty'],'1000')
        self.p.warehouse({'id':o['id'],'version':original['version'],'lines':[{'line_id':'L1','warehouse_id':'WH-TOFU'},{'line_id':'L2','warehouse_id':'WH-SKIN'}]},'会计')
        self.assertEqual(self.stock('WH-TOFU')['qty'],'600');self.assertEqual(self.stock('WH-SKIN')['qty'],'400')
