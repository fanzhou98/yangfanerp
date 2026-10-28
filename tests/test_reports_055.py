import json,uuid,unittest
from decimal import Decimal
import test_production_daily as fixture
import resources_costs as rc
import production_management as fm
import reporting
import product_profit

erp=fixture.erp
class ReportBatchTests(unittest.TestCase):
    def setUp(self):
        fixture.DailyFactoryTests.setUp(self)
        with erp.connect(True) as c:
            for table in ('orders','sales_returns','indirect_expenses','byproduct_sales','trade_records'):c.execute('DELETE FROM '+table)
    tearDown=fixture.DailyFactoryTests.tearDown
    material=fixture.DailyFactoryTests.material
    record=fixture.DailyFactoryTests.record
    call=fixture.DailyFactoryTests.call
    def bean(self,lot,qty='3',warehouse='WH-TOFU',**extra):
        with erp.connect(True) as c:return fm.bean_register(c,{'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','revision':rc.revision(c),'handler':'厂长','entries':[{'production_system_id':'tofu','warehouse_id':warehouse,'source_lot_id':lot,'qty':qty}],**extra},'厂长',erp.now,erp.audit)
    def order(self,oid,day='2026-10-20',state='reviewed',unit='筐',kg='10',amount=10000):
        line={'product_id':'P001','product_name':'大豆腐','unit':unit,'actual_qty':'1','amount_cents':amount,'billing_unit':'公斤','bill_qty':kg}
        o={'id':oid,'business_date':day,'state':state,'customer_id':'C001','customer_name':'测试客户','total_cents':amount,'lines':[line]}
        with erp.connect(True) as c:c.execute('INSERT INTO orders VALUES(?,?)',(oid,json.dumps(o)))
        return o
    def test_variety_independent_from_origin_and_exact_lot_cost(self):
        a=self.material('receipt','10','40',quality={'soy_variety':'春豆','origin':'天津','protein_pct':'40','moisture_pct':'12'})
        b=self.material('receipt','10','60',quality={'soy_variety':'天津豆','origin':'东北','protein_pct':'42','moisture_pct':'10'})
        self.bean(b['id'])
        with erp.connect() as c:
            _,entries,stocks=rc.material_ledger(c,warehouse_details=True);last=entries[-1];stock=next(w for w in stocks if w['id']=='RM-SOY' and w['warehouse_id']=='WH-TOFU')
            self.assertEqual(last['cost_cents'],1800);self.assertEqual({l['lot_id']:l['qty'] for l in stock['lots']},{a['id']:'10',b['id']:'7'})
            self.assertEqual(fm.bean_registrations(c)[0]['source_quality']['soy_variety'],'天津豆')
            data=fm.bean_stock(c,'2026-10-20');self.assertNotIn('_cents',json.dumps(data))
            self.assertNotIn('price',json.dumps(data))
    def test_reject_selected_lot_shortage_cross_warehouse_and_missing(self):
        a=self.material('receipt','2','8');self.material('receipt','10','60')
        for lot,warehouse in [(a['id'],'WH-TOFU'),(a['id'],'WH-SKIN'),('','WH-TOFU'),('missing','WH-TOFU')]:
            with self.assertRaises(ValueError):self.bean(lot,warehouse=warehouse)
        with erp.connect() as c:self.assertFalse(fm.bean_registrations(c))
    def test_transfer_keeps_lot_and_same_warehouse_can_use_two_batches(self):
        a=self.material('receipt','10','40',warehouse='WH-MAIN');b=self.material('receipt','10','60',warehouse='WH-MAIN')
        self.material('transfer','15',warehouse='WH-MAIN',target_warehouse_id='WH-TOFU')
        rows=[{'production_system_id':'tofu','warehouse_id':'WH-TOFU','qty':'2','source_lot_id':r['id']} for r in (a,b)]
        self.bean(a['id'],entries=rows)
        with erp.connect() as c:self.assertEqual(len(fm.bean_registrations(c)),2)
    def test_missing_is_null_and_confirmed_zero_is_zero(self):
        self.order('ZERO',amount=0);self.order('PENDING',day='2026-10-21',state='ready')
        with erp.connect() as c:r=reporting.sales(c,'2026-10-20','2026-10-22')
        self.assertEqual([p['value'] for p in r['charts'][0]['points']],[0,None,None]);self.assertEqual(r['pending_orders'],1)
        self.assertEqual([p['state'] for p in r['charts'][0]['points']],['已复核','待复核','无单据'])
    def test_returns_by_received_day_and_original_order_do_not_mix(self):
        self.order('OLD',day='2026-09-30');self.order('NEW')
        ret={'id':'R1','customer_id':'C001','product_id':'P001','product_name':'大豆腐','received_date':'2026-10-20','order_id':'OLD','qty':'1','unit':'筐','finance':{'state':'posted','amount_cents':2000}}
        with erp.connect(True) as c:c.execute('INSERT INTO sales_returns VALUES(?,?)',('R1',json.dumps(ret)))
        with erp.connect() as c:
            october=reporting.sales(c,'2026-10-01','2026-10-31');september=reporting.sales(c,'2026-09-01','2026-09-30')
        self.assertEqual((october['received_return_cents'],october['original_return_cents'],october['net_cents']),(2000,0,10000));self.assertEqual(september['original_return_cents'],2000)
    def test_report_does_not_add_different_product_units(self):
        self.order('O1');self.order('O2',unit='袋')
        with erp.connect() as c:r=reporting.sales(c,'2026-10-20','2026-10-20')
        self.assertEqual(len(r['products']),2);self.assertNotIn('total_qty',r)
    def test_product_estimate_uses_fifo_cost_and_actual_slurry_allocation(self):
        self.order('O1');self.material('receipt','100','400');self.material('consume','100');self.record(products=[{'product_id':'P001','system':'tofu','large_tanks':'1','small_tanks':'0'}])
        with erp.connect() as c:r=product_profit.month(c,'2026-10')
        self.assertEqual(r['costs']['bean_cost_cents'],40000);self.assertEqual(r['rows'][0]['soy_cost_cents'],40000);self.assertEqual(r['rows'][0]['net_cents'],-30000)
    def test_product_estimate_missing_production_cannot_imply_zero_cost_profit(self):
        self.order('O1');self.material('receipt','100','400');self.material('consume','100')
        with erp.connect() as c:r=product_profit.month(c,'2026-10')
        self.assertIsNone(r['rows'][0]['net_cents']);self.assertTrue(r['rows'][0]['missing_data']);self.assertEqual(r['costs']['unallocated_bean_cents'],40000)
    def test_supplier_expense_review_partial_payment_updates_account_and_payable(self):
        import purchasing,funds,owner_analysis
        with erp.connect(True) as c:
            supplier=purchasing.Operations(c,erp.now,erp.audit).supplier({'name':'维修供应商'},'管理员')
            account=funds.save(c,'account',{'name':'付款户','kind':'银行账户','opening_date':'2026-10-01','opening_balance':'1000','active':True},'管理员',erp.now,erp.audit)
            op=rc.Operations(c,erp.now,erp.audit)
            expense=op.expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','category':'maintenance','amount':'100','supplier_id':supplier['id'],'partner':'不能覆盖真实供应商','handler':'会计','note':'维修凭据'},'管理员')
            self.assertEqual(expense['partner'],'维修供应商')
            before=reporting.expense_summary(c)['suppliers'][0];self.assertEqual((before['recognized_cents'],before['pending_cents']),(0,10000))
            op.expense_review({'request_key':str(uuid.uuid4()),'id':expense['id'],'version':1,'decision':'approve','evidence_checked':True,'handler':'出纳'},'管理员')
            op.expense_payment({'request_key':str(uuid.uuid4()),'id':expense['id'],'version':2,'business_date':'2026-10-21','amount':'30','method':'银行转账','payee':supplier['name'],'account_id':account['id'],'handler':'出纳','note':'实付回单'},'管理员')
            summary=reporting.expense_summary(c);self.assertEqual(summary['total_cents'],10000)
            self.assertEqual((summary['suppliers'][0]['recognized_cents'],summary['suppliers'][0]['paid_cents']),(7000,3000))
            self.assertEqual(next(a['balance_cents'] for a in funds.report(c,'2026-10-21')['accounts'] if a['id']==account['id']),97000)
            self.assertTrue(any(r['name']=='维修供应商' and r['cents']==7000 for r in owner_analysis.accounts(c,'2026-10-21')['payables']))

    def test_protein_quality_empty_and_tianjin_variety(self):
        quality=rc.quality({'soy_variety':'天津豆','origin':'河南'})
        self.assertEqual(quality['soy_variety'],'天津豆');self.assertEqual(quality['protein_pct'],'');self.assertEqual(quality['origin'],'河南')

if __name__=='__main__':unittest.main()
