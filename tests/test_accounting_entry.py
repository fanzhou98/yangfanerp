"""Synthetic photo entry: gross/net isolation, yesterday returns and atomic updates."""
import copy,json,unittest,uuid
from decimal import Decimal
import test_delivery_trade as fixture
import accounting_entry as ae,billing,trade,assets,crate_accounting,resources_costs as rc

class AccountingEntryTests(unittest.TestCase):
    setUp=fixture.DeliveryTradeTests.setUp
    tearDown=fixture.DeliveryTradeTests.tearDown
    order=fixture.DeliveryTradeTests.order
    save=fixture.DeliveryTradeTests.save
    shipment=fixture.DeliveryTradeTests.shipment
    def update(self,o,**changes):return self.erp.mutate('order',{**copy.deepcopy(o),**changes},'管理员',o['id'],connection=self.c)
    def gross(self,o,gross='100',qty=10):
        lines=copy.deepcopy(o['lines']);lines[0].update(driver=[{'gross':gross,'count':str(qty),'tare':'0'}],driver_weight_basis='gross',crate_lines=[{'product_id':'P001','asset_id':'CR-WHITE','qty':qty,'tare':'2'}]);return self.update(o,lines=lines)
    def returned(self,o,source,qty,**extra):
        return self.update(o,accounting_returns={'version':o.get('accounting_returns',{}).get('version',0),'business_date':o['business_date'],'lines':[{'product_id':'P001','asset_id':'CR-WHITE','qty':qty,'source_order_id':source['id']}] if qty else [],**extra})
    def test_gross_deducts_snapshot_crates_and_legacy_net_is_unchanged(self):
        o=self.gross(self.order());l=o['lines'][0];self.assertEqual(l['driver_net'],'80');self.assertEqual(billing.settlement_net(l,'driver'),Decimal(80));self.assertEqual(l['driver'][0]['gross'],'100')
        r=self.erp.mutate('settle',{'version':o['version'],'mode':'driver'},'管理员',o['id'],connection=self.c);self.assertEqual(r['total_cents'],24000)
        self.c.execute("UPDATE products SET tare='9' WHERE id='P001'");self.assertEqual(billing.settlement_net(r['lines'][0],'driver'),80)
        legacy={**l,'driver_weight_basis':'legacy_net','driver_net':'100'};self.assertEqual(billing.settlement_net(legacy,'driver'),100)
    def test_gross_requires_full_frames_and_positive_net(self):
        o=self.order()
        with self.assertRaises(ValueError):self.gross(o,gross='10')
        with self.assertRaises(ValueError):self.gross(o,qty=11)
        lines=copy.deepcopy(o['lines']);lines[0].update(driver=[{'gross':'100','count':'10','tare':'0'}],driver_weight_basis='gross',crate_lines=[])
        with self.assertRaisesRegex(ValueError,'发出框型'):self.update(o,lines=lines)
    def test_single_frame_can_be_automatically_derived(self):
        o=self.order(pid='P002');self.assertEqual(len(crate_accounting.variants(self.c,'P002')),1)
        lines=copy.deepcopy(o['lines']);lines[0].update(auto_crate=True,driver_weight_basis='gross',driver=[{'gross':'200','count':'10','tare':'0'}]);r=self.update(o,lines=lines)
        self.assertEqual(sum(x['qty'] for x in r['lines'][0]['crate_lines']),10);self.assertLess(Decimal(r['lines'][0]['driver_net']),200)
    def test_returns_link_yesterday_and_update_or_void_one_physical_event(self):
        previous=self.order(day='2026-10-21');self.shipment(previous);today=self.order(day='2026-10-22')
        today=self.returned(today,previous,3);meta=today['accounting_returns'];event=json.loads(self.c.execute('SELECT payload FROM asset_records WHERE id=?',(next(iter(meta['event_versions'])),)).fetchone()[0]);self.assertEqual(event['business_date'],'2026-10-22');self.assertEqual(event['source_date'],'2026-10-21');self.assertEqual(event['order_id'],previous['id']);self.assertEqual(event['accounting_order_id'],today['id'])
        today=self.returned(today,previous,3);self.assertEqual(today['accounting_returns']['version'],1)
        today=self.returned(today,previous,4);self.assertEqual(len([r for r in assets.rows(self.c) if r.get('accounting_order_id')==today['id']]),1)
        before=trade.customer_crates(self.c,'C001','2026-10-21');after=trade.customer_crates(self.c,'C001','2026-10-22');self.assertEqual(sum(r['returned_qty'] for r in before['rows']),0);self.assertEqual(sum(r['returned_qty'] for r in after['rows']),4)
        today=self.returned(today,previous,0);events=[r for r in assets.rows(self.c) if r.get('accounting_order_id')==today['id']];self.assertEqual(len(events),1);self.assertTrue(events[0]['voided']);self.assertEqual(sum(r['returned_qty'] for r in trade.customer_crates(self.c,'C001','2026-10-22')['rows']),0)
        today=self.returned(today,previous,2);self.assertEqual(len([r for r in assets.rows(self.c) if r.get('accounting_order_id')==today['id']]),1)
    def test_wrong_customer_date_frame_stale_or_external_edit_rejected(self):
        previous=self.order(day='2026-10-21');self.shipment(previous);today=self.order(day='2026-10-22');other=self.order(day='2026-10-21',cid='C002');self.shipment(other)
        with self.assertRaisesRegex(ValueError,'同一客户昨日'):self.returned(today,other,2)
        with self.assertRaisesRegex(ValueError,'同一客户昨日'):self.returned(today,today,2)
        today=self.returned(today,previous,2)
        with self.assertRaisesRegex(ValueError,'已变化'):self.returned(today,previous,3,version=0)
        event=next(r for r in assets.rows(self.c) if r.get('accounting_order_id')==today['id']);assets.save(self.c,'void',{'id':event['id'],'version':event['version'],'request_key':str(uuid.uuid4()),'note':'现场重新核查'},'管理员',self.erp.now,self.erp.audit)
        with self.assertRaisesRegex(ValueError,'框子管理修改或作废'):self.returned(today,previous,3)
        with self.assertRaisesRegex(ValueError,'已有随配送回框'):self.update(today,business_date='2026-10-23')
    def test_failed_order_validation_does_not_leave_return_event(self):
        previous=self.order(day='2026-10-21');self.shipment(previous);today=self.order(day='2026-10-22');before=self.c.total_changes
        # Caller transaction/savepoint owns both order and asset writes.
        self.c.execute('SAVEPOINT photo_entry')
        with self.assertRaises(ValueError):
            try:self.update(today,accounting_returns={'version':0,'business_date':today['business_date'],'lines':[{'product_id':'P001','asset_id':'CR-WHITE','qty':2,'source_order_id':previous['id']},{'product_id':'P001','asset_id':'missing','qty':1,'source_order_id':previous['id']}]})
            except ValueError:self.c.execute('ROLLBACK TO photo_entry');raise
        self.c.execute('RELEASE photo_entry');self.assertFalse(any(r.get('accounting_order_id')==today['id'] for r in assets.rows(self.c)))
    def test_batch_failure_rolls_back_first_return_and_order(self):
        previous=self.order(day='2026-10-21');self.shipment(previous);first=self.order(day='2026-10-22');second=self.order(day='2026-10-22',cid='C002');self.c.commit()
        entry=lambda o,s:{**o,'accounting_returns':{'version':0,'business_date':o['business_date'],'lines':[{'product_id':'P001','asset_id':'CR-WHITE','qty':2,'source_order_id':s['id']}]}}
        with self.assertRaises(ValueError):self.erp.batch_mutate({'operations':[{'action':'order','order_id':first['id'],'body':entry(first,previous)},{'action':'order','order_id':second['id'],'body':entry(second,previous)}]},'管理员')
        self.assertEqual(self.erp.get_order(self.c,first['id'])['version'],first['version']);self.assertFalse(any(r.get('accounting_order_id')==first['id'] for r in assets.rows(self.c)))
    def test_auto_transport_confirmed_until_priced(self):
        o=self.order(day='2026-10-22');plan={'business_date':o['business_date'],'version':1,'trips':[{'id':'T-AUTO','name':'自动带入趟次','vehicle_name':'车A','driver':'司机'}],'assignments':[{'market_id':'M001','trip_id':'T-AUTO'}],'order_markets':{o['id']:'M001'}}
        self.c.execute('INSERT INTO dispatch_plans VALUES(?,?)',(o['business_date'],rc.dump(plan)))
        created=trade.ensure_dispatched_trips(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit);self.assertEqual(len(created),1);self.assertEqual(trade.ensure_dispatched_trips(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit),[]);self.assertIsNone(created[0]['amount_cents'])
        report=trade.transport_report(self.c,'2026-10');self.assertEqual(report['groups'][0]['pending_count'],1);self.assertEqual(report['groups'][0]['ready_count'],0)
        p=self.save('transport-provider',{'name':'运输公司'})
        self.assertEqual(created[0]['execution_state'],'confirmed')
        with self.assertRaises(ValueError):self.save('trip',{'id':created[0]['id'],'version':1,'business_date':o['business_date'],'trip_id':'T-AUTO','partner':'运输公司','rate':'100','note':'补齐结算资料'})
        self.save('transport-price',{'id':created[0]['id'],'version':created[0]['version'],'provider_id':p['id'],'rate':'100','note':'补齐结算资料'})
        report=trade.transport_report(self.c,'2026-10');self.assertEqual(report['groups'][0]['pending_count'],0);self.assertEqual(report['groups'][0]['ready_count'],1)
