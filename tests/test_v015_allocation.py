import unittest,copy
import test_inventory as fixture
import inventory as inv
erp=fixture.erp
class AllocationFlowTests(unittest.TestCase):
    setUp=fixture.InventoryTests.setUp
    tearDown=fixture.InventoryTests.tearDown
    snapshot=fixture.InventoryTests.snapshot
    ops=fixture.InventoryTests.ops
    def order(self,cid='C001',qty='8',actual='0',weights=False):
        return erp.mutate('order',{'dispatch_required':actual=='0','workflow_version':1,'customer_id':cid,'business_date':'2026-10-21','batch':'默认预分配测试','lines':[{'product_id':'P001','ordered_qty':qty,'actual_qty':actual,'price':'3','driver':[{'gross':'90','count':actual,'tare':'1'}] if weights else [],'customer':[]}]},'库管')
    def body(self,stock='10',allocations=None,stage='stock'):
        d=erp.bootstrap();old=next((p for p in d['warehouse_plans'] if p['business_date']=='2026-10-21'),{})
        return {'business_date':'2026-10-21','version':old.get('version',0),'inventory_revision':d['inventory_revision'],'stage':stage,'evidence_checked':stage=='confirm_dispatch','order_versions':{o['id']:o['version'] for o in d['orders'] if o['business_date']=='2026-10-21'},'stock':[{'product_id':p['id'],'existing_qty':stock if p['id']=='P001' else '0','produced_qty':'0'} for p in d['products']],'allocations':old.get('allocations',[]) if allocations is None else allocations,'customers':[]}
    def allocate(self,*pairs):return [{'order_id':o['id'],'product_id':'P001','ordered_qty':o['lines'][0]['ordered_qty'],'qty':qty,'mode':'manual'} for o,qty in pairs]
    def test_defaults_to_order_without_inventing_actual_and_stock_can_be_saved_short(self):
        a=self.order();b=self.order('C002');before=erp.bootstrap()
        with erp.connect() as c:defaults=inv.proposed_allocations({},before['orders'])
        self.assertEqual([x['qty'] for x in defaults],['8','8'])
        plan=erp.save_warehouse(self.body(),'库管');self.assertEqual(plan['allocation_state'],'draft');self.assertEqual([x['qty'] for x in plan['allocations']],['8','8'])
        p=self.snapshot()['products'][0];self.assertEqual((p['ordered_qty'],p['proposed_qty'],p['shortage_qty'],p['adjustment_qty'],p['reserved_qty']),('16','16','6','6','0'))
        self.assertEqual([o['lines'][0]['actual_qty'] for o in erp.bootstrap()['orders']],['0','0'])
    def test_adjusted_dispatch_sets_actual_atomically_and_keeps_ordered_demand(self):
        a=self.order();b=self.order('C002');erp.save_warehouse(self.body(),'库管')
        with self.assertRaisesRegex(ValueError,'超过可用库存'):erp.save_warehouse(self.body(stage='confirm_dispatch'),'库管')
        self.assertEqual([o['lines'][0]['actual_qty'] for o in erp.bootstrap()['orders']],['0','0'])
        result=erp.save_warehouse(self.body(allocations=self.allocate((a,'6'),(b,'4')),stage='confirm_dispatch'),'库管');self.assertEqual(result['plan']['allocation_state'],'confirmed')
        self.assertEqual(sorted(o['lines'][0]['actual_qty'] for o in result['orders']),['4','6']);self.assertEqual([o['lines'][0]['ordered_qty'] for o in result['orders']],['8','8'])
        p=self.snapshot()['products'][0];self.assertEqual((p['shipped_qty'],p['book_qty'],p['adjustment_qty']),('10','0','0'))
    def test_dispatch_after_data_reset_passes_epoch_to_internal_order_updates(self):
        a=self.order()
        with erp.connect(True) as c:
            c.execute("INSERT INTO meta VALUES('business_data_epoch','new-round') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        body=self.body(allocations=self.allocate((a,'6')),stage='confirm_dispatch')
        body['_data_epoch']='new-round'
        result=erp.save_warehouse(body,'库管')
        self.assertEqual(result['orders'][0]['lines'][0]['actual_qty'],'6')
        stale=self.body(stage='confirm_dispatch');stale['_data_epoch']='0'
        with self.assertRaisesRegex(ValueError,'已经清理或恢复'):
            erp.save_warehouse(stale,'库管')

    def test_no_increase_without_confirmed_allocation_or_above_quota(self):
        a=self.order();update=copy.deepcopy(a);update['lines'][0]['actual_qty']='1'
        with self.assertRaisesRegex(ValueError,'发货分配页确认'):erp.mutate('order',update,'库管',a['id'])
        erp.save_warehouse(self.body(),'库管')
        with self.assertRaises(ValueError):erp.mutate('order',update,'库管',a['id'])
        result=erp.save_warehouse(self.body(allocations=self.allocate((a,'5')),stage='confirm_dispatch'),'库管');o=result['orders'][0];o['lines'][0]['actual_qty']='6'
        with self.assertRaisesRegex(ValueError,'超过已确认分配'):erp.mutate('order',o,'库管',o['id'])
    def test_existing_unweighed_actual_can_be_corrected_together_from_deficit(self):
        a=self.order(actual='8');b=self.order('C002',actual='8');erp.save_warehouse(self.body(),'库管')
        self.assertEqual(self.snapshot()['products'][0]['book_qty'],'-6')
        result=erp.save_warehouse(self.body(allocations=self.allocate((a,'5'),(b,'5')),stage='confirm_dispatch'),'库管')
        self.assertEqual([o['lines'][0]['actual_qty'] for o in result['orders']],['5','5']);self.assertEqual(self.snapshot()['products'][0]['book_qty'],'0')
    def test_weighed_or_confirmed_actual_is_locked_and_rolls_back_whole_batch(self):
        a=self.order(actual='8',weights=True);b=self.order('C002');erp.save_warehouse(self.body(stock='20'),'库管')
        with self.assertRaisesRegex(ValueError,'已有称重'):erp.save_warehouse(self.body(stock='20',allocations=self.allocate((a,'7'),(b,'4')),stage='confirm_dispatch'),'库管')
        orders={o['id']:o for o in erp.bootstrap()['orders']};self.assertEqual(orders[a['id']]['lines'][0]['actual_qty'],'8');self.assertEqual(orders[b['id']]['lines'][0]['actual_qty'],'0')
    def test_confirmation_requires_stock_checkbox_and_current_order_and_inventory(self):
        a=self.order();body=self.body(stock='',stage='confirm_dispatch')
        with self.assertRaisesRegex(ValueError,'尚未盘点'):erp.save_warehouse(body,'库管')
        body=self.body(stage='confirm_dispatch');body['evidence_checked']=False
        with self.assertRaisesRegex(ValueError,'明确确认'):erp.save_warehouse(body,'库管')
        stale=self.body();erp.mutate('order',{**a,'note':'并行修改'},'库管',a['id'])
        with self.assertRaisesRegex(ValueError,'已有变化'):erp.save_warehouse(stale,'库管')
    def test_demand_can_exceed_stock_then_auto_default_tracks_order_change(self):
        a=self.order();erp.save_warehouse(self.body(),'库管');a['lines'][0]['ordered_qty']='20';a=erp.mutate('order',a,'库管',a['id'])
        p=self.snapshot()['products'][0];self.assertEqual((p['ordered_qty'],p['proposed_qty'],p['adjustment_qty']),('20','20','10'))
        new=self.order('C002',qty='30');self.assertEqual(self.snapshot()['products'][0]['ordered_qty'],'50')
    def test_manual_reduction_stays_manual_and_draft_cannot_day_close(self):
        a=self.order();erp.save_warehouse(self.body(allocations=self.allocate((a,'4'))),'库管');a['lines'][0]['ordered_qty']='12';a=erp.mutate('order',a,'库管',a['id']);self.assertEqual(self.snapshot()['products'][0]['proposed_qty'],'4')
        d=erp.bootstrap();plan=d['warehouse_plans'][0]
        with self.assertRaisesRegex(ValueError,'拟实发未确认'):self.ops('close',{'business_date':'2026-10-21','version':0,'inventory_revision':d['inventory_revision'],'plan_version':plan['version'],'evidence_checked':True,'counts':[]})

    def test_new_demand_invalidates_confirmed_plan_and_cannot_bypass_day_close(self):
        a=self.order();erp.save_warehouse(self.body(stage='confirm_dispatch'),'库管');self.order('C002',qty='4')
        d=erp.bootstrap();plan=d['warehouse_plans'][0];self.assertEqual(plan['allocation_state'],'draft')
        with self.assertRaisesRegex(ValueError,'未确认'):self.ops('close',{'business_date':'2026-10-21','version':0,'inventory_revision':d['inventory_revision'],'plan_version':plan['version'],'evidence_checked':True,'counts':[]})
