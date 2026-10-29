import copy,json,unittest,uuid
import test_delivery_trade as fixture
import transport_closure as tc,trade,expense_parties as ep,resources_costs as rc,funds

class TransportClosureTests(unittest.TestCase):
    setUp=fixture.DeliveryTradeTests.setUp
    tearDown=fixture.DeliveryTradeTests.tearDown
    save=fixture.DeliveryTradeTests.save
    order=fixture.DeliveryTradeTests.order
    def setup_trip(self,quote=True):
        p=self.save('transport-provider',{'name':'闭环运输公司','phone':'0994-1234567'})
        if quote:self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-01','rate':'100','version':0})
        o=self.order(day='2026-10-22');self.c.execute("UPDATE delivery_markets SET city='昌吉' WHERE id='M001'")
        t={'id':'CLOSE-T','name':'昌吉配送','period':'下午','vehicle_id':'V001','vehicle_name':'车A','driver_ids':['TEST-D'],'driver':'测试司机','provider_id':p['id']}
        plan={'business_date':o['business_date'],'version':1,'trips':[t],'assignments':[{'market_id':'M001','trip_id':t['id'],'sequence':1}],'order_markets':{o['id']:'M001'}}
        self.c.execute('INSERT INTO dispatch_plans VALUES(?,?)',(o['business_date'],rc.dump(plan)));r=trade.ensure_dispatched_trips(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit)[0]
        return p,o,plan,r
    def issue(self,p):
        g=next(g for g in trade.transport_report(self.c,'2026-10')['groups'] if g['provider_id']==p['id']);return self.save('transport-issue',{'month':'2026-10','provider_id':p['id'],'partner':p['name'],'handler':'会计','source_fingerprint':g['source_fingerprint']})
    def test_provider_quote_snapshot_settle_and_pay(self):
        p,o,plan,r=self.setup_trip();self.assertEqual(r['execution_state'],'confirmed');self.assertEqual(r['amount_cents'],10000);self.assertFalse(r['pricing_pending']);self.assertEqual(tc.sync(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit),[])
        doc=self.issue(p);self.assertEqual(doc['trip_count'],1)
        e=next(e for e in rc.expense_projection(self.c) if e['id']==doc['expense_id']);self.assertEqual(e['counterparty_id'],p['id']);self.assertEqual(e['amount_cents'],10000)
        ops=rc.Operations(self.c,self.erp.now,self.erp.audit);ops.expense_review({'id':e['id'],'version':e['version'],'decision':'approve','evidence_checked':True,'handler':'出纳','request_key':str(uuid.uuid4())},'管理员');e=ops.expense_record({'id':e['id'],'version':e['version']+1})
        with self.assertRaisesRegex(ValueError,'收款方'):ops.expense_payment({'id':e['id'],'version':e['version'],'payee':'别的公司','request_key':str(uuid.uuid4())},'管理员')
        ops.expense_payment({'id':e['id'],'version':e['version'],'payee':p['name'],'business_date':'2026-10-31','amount':'40','method':'现金','handler':'出纳','reference':'合成付款凭据','note':'运输分次付款','request_key':str(uuid.uuid4())},'管理员')
        report=trade.transport_report(self.c,'2026-10');d=report['documents'][0];self.assertEqual(d['paid_cents'],4000);self.assertEqual(d['outstanding_cents'],6000);self.assertFalse(d['can_reopen']);self.assertTrue(any(m['amount_cents']==4000 for m in funds.movements(self.c)))
        with self.assertRaisesRegex(ValueError,'已有付款'):self.save('transport-reopen',{'id':d['id'],'version':d['version'],'expense_version':d['expense_version'],'note':'测试已付保护'})
    def test_unpaid_reopen_reprice_and_reissue_keeps_old_document(self):
        p,o,plan,r=self.setup_trip();d=self.issue(p);oldraw=copy.deepcopy(d)
        report=trade.transport_report(self.c,'2026-10');d=report['documents'][0]
        self.save('transport-reopen',{'id':d['id'],'version':d['version'],'expense_version':d['expense_version'],'note':'合成结算金额更正'})
        oldexpense=next(e for e in rc.expense_projection(self.c) if e['id']==d['expense_id']);self.assertTrue(oldexpense['voided']);self.assertEqual(oldexpense['outstanding_cents'],0)
        r=trade.records(self.c,'trip')[0];r=self.save('transport-price',{'id':r['id'],'version':r['version'],'provider_id':p['id'],'rate':'120','note':'临时绕行补费'});new=self.issue(p)
        self.assertNotEqual(new['id'],d['id']);self.assertEqual(new['amount_cents'],12000);prior=next(x for x in trade.records(self.c,'transport-document') if x['id']==d['id']);self.assertEqual(prior['lines'],oldraw['lines']);self.assertTrue(prior['voided'])
        effective=[e for e in rc.expense_projection(self.c) if not e.get('voided')];self.assertEqual(len(effective),1);self.assertEqual(effective[0]['amount_cents'],12000)
    def test_provider_and_quote_crud_use_customer_regions(self):
        p=self.save('transport-provider',{'name':'可维护服务商','phone':'0994-1000000','note':'初始备注'})
        p=self.save('transport-provider',{'id':p['id'],'version':p['version'],'name':'可维护服务商（改）','phone':'0994-2000000','note':'保留备注'})
        self.assertEqual(p['name'],'可维护服务商（改）');self.assertEqual(next(x for x in tc.providers(self.c) if x['id']==p['id'])['phone'],'0994-2000000')
        p=self.save('transport-provider-status',{'id':p['id'],'version':p['version'],'active':False});self.assertFalse(p['active'])
        with self.assertRaisesRegex(ValueError,'有效配送服务商'):tc.provider(self.c,p['id'])
        p=self.save('transport-provider-status',{'id':p['id'],'version':p['version'],'active':True});self.assertTrue(p['active'])
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-01','rate':'88','version':0})
        q=next(x for x in tc.quotes(self.c) if x['provider_id']==p['id'])
        self.save('transport-quote',{'id':q['id'],'version':q['version'],'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-01','rate':'99'})
        self.assertEqual(tc.quote(self.c,p['id'],'昌吉','2026-10-22')['amount_cents'],9900)
        with self.assertRaisesRegex(ValueError,'客户地区列表'):self.save('transport-quote',{'provider_id':p['id'],'area':'不存在的地区','effective_date':'2026-10-01','rate':'100','version':0})
        q=tc.quote(self.c,p['id'],'昌吉','2026-10-22');self.save('transport-quote-delete',{'id':q['id'],'version':q['version']})
        self.assertFalse(any(x['id']==q['id'] for x in tc.quotes(self.c)))
    def test_settled_trip_cannot_be_reassigned_or_edited(self):
        p,o,plan,r=self.setup_trip();self.issue(p)
        changed=copy.deepcopy(plan);changed['trips'][0]['vehicle_id']='V002'
        with self.assertRaisesRegex(ValueError,'已结算'):tc.guard_dispatch(self.c,plan,changed)
        o['lines'][0]['actual_qty']='9'
        with self.assertRaisesRegex(ValueError,'关联配送已结算'):self.erp.save(self.c,o)
        report=trade.transport_report(self.c,'2026-10');doc=report['documents'][0];self.save('transport-reopen',{'id':doc['id'],'version':doc['version'],'expense_version':doc['expense_version'],'note':'改派前撤销结算'})
        tc.guard_dispatch(self.c,plan,changed)
    def test_quotes_version_effective_dates_and_no_retroactive_price(self):
        p,o,plan,r=self.setup_trip();q=tc.quotes(self.c)[0]
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-23','rate':'200','version':0});self.assertEqual(tc.quote(self.c,p['id'],'昌吉','2026-10-22')['amount_cents'],10000)
        with self.assertRaisesRegex(ValueError,'报价已变化'):self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':q['effective_date'],'rate':'150','version':0})
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':q['effective_date'],'rate':'150','version':q['version']});tc.sync(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit);self.assertEqual(trade.records(self.c,'trip')[0]['amount_cents'],15000)
    def test_missing_quote_cannot_settle_until_accountant_prices(self):
        p,o,plan,r=self.setup_trip(False)
        with self.assertRaisesRegex(ValueError,'运费'):self.issue(p)
        r=self.save('transport-price',{'id':r['id'],'version':r['version'],'provider_id':p['id'],'rate':'130','note':'跨区域核对运输费'});self.assertEqual(self.issue(p)['amount_cents'],13000)
    def test_stale_duplicate_and_permissions_do_not_mutate(self):
        p,o,plan,r=self.setup_trip();body={'id':r['id'],'version':r['version'],'provider_id':p['id'],'rate':'150','note':'核对运费','request_key':'same-price'}
        first=trade.save(self.c,'transport-price',body,'管理员',self.erp.now,self.erp.audit);self.assertEqual(first,trade.save(self.c,'transport-price',body,'管理员',self.erp.now,self.erp.audit))
        with self.assertRaisesRegex(ValueError,'已变化'):trade.save(self.c,'transport-price',{**body,'request_key':'another-price'},'管理员',self.erp.now,self.erp.audit)
        with self.assertRaises(ValueError):self.save('transport-price',{'id':r['id'],'version':first['version'],'rate':'200','provider_id':p['id'],'note':'无权限'},'物流负责人')
        operational=tc.operations_only(trade.transport_report(self.c,'2026-10'));encoded=json.dumps(operational);self.assertNotIn('amount_cents',encoded);self.assertNotIn('quote',encoded);self.assertNotIn('payment',encoded)
    def test_provisional_costs_and_unknown_actual_fees_do_not_crash_reports(self):
        import reporting,product_profit,report_directory,erp_access
        p,o,plan,r=self.setup_trip(False);basis=tc.cost_basis(self.c,'2026-10');self.assertEqual(basis['amount_cents'],0);self.assertEqual(basis['pending_count'],0);self.assertEqual(basis['missing_count'],1);self.assertTrue(basis['gaps'])
        self.save('transport-price',{'id':r['id'],'version':r['version'],'provider_id':p['id'],'rate':'130','note':'补齐实际运费'});basis=tc.cost_basis(self.c,'2026-10');self.assertEqual(basis['missing_count'],0);self.assertFalse(basis['gaps'])
        self.assertIsInstance(reporting.management_month(self.c,'2026-10'),dict);self.assertIsInstance(product_profit.month(self.c,'2026-10'),dict);self.assertTrue(report_directory.catalog(self.c,'2026-10-22',erp_access.defaults('管理员'),'管理员')['topics'])
    def test_reopened_document_stays_in_history_but_not_effective_totals(self):
        import delivery_query as q
        p,o,plan,r=self.setup_trip();self.issue(p);d=trade.transport_report(self.c,'2026-10')['documents'][0]
        self.save('transport-reopen',{'id':d['id'],'version':d['version'],'expense_version':d['expense_version'],'note':'更正结算来源'})
        history=q.history(self.c,kind='documents',all_dates=True,financial=True);self.assertEqual(history['total'],1);self.assertTrue(history['rows'][0]['voided']);self.assertEqual(history['summary'],[])
        self.assertEqual(q.history(self.c,kind='documents',all_dates=True,financial=True,status='active')['total'],0)
    def test_removed_trip_retires_auto_record_and_flags_unplanned_order(self):
        p,o,plan,r=self.setup_trip()
        plan['trips']=[]
        self.c.execute('UPDATE dispatch_plans SET payload=? WHERE business_date=?',(rc.dump(plan),o['business_date']))
        tc.sync(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit)
        trips=trade.records(self.c,'trip');self.assertTrue(trips[0]['voided'])
        self.assertIn(o['id'],tc.unplanned(self.c,o['business_date']))
    def test_legacy_auto_pending_sync_upgrades_to_confirmed(self):
        p,o,plan,r=self.setup_trip();legacy={k:v for k,v in r.items() if k not in ('closure_version','execution_state','source_snapshot','provider_id')};legacy.update(partner='',pricing_pending=True,amount_cents=None);self.c.execute('UPDATE trade_records SET payload=? WHERE id=?',(rc.dump(legacy),r['id']))
        changed=tc.sync(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit);self.assertEqual(len(changed),1);self.assertEqual(changed[0]['execution_state'],'confirmed');self.assertEqual(changed[0]['provider_id'],p['id']);self.assertEqual(changed[0]['amount_cents'],10000)
        self.assertEqual(tc.sync(self.c,o['business_date'],'管理员',self.erp.now,self.erp.audit),[])
    def test_audit_rollback_cannot_split_transport_document_or_payable(self):
        import audit_rollback
        p,o,plan,r=self.setup_trip();d=self.issue(p)
        for entity in (d['id'],d['expense_id']):
            aid=self.c.execute('SELECT max(id) FROM audit WHERE entity=?',(entity,)).fetchone()[0];result=audit_rollback.plan(self.c,aid);self.assertTrue(result['blockers'])
    def test_invalid_version_and_types_are_rejected_without_writes(self):
        p=self.save('transport-provider',{'name':'类型校验服务商'})
        for version in (True,'1'):
            with self.assertRaises(ValueError):self.save('transport-provider-status',{'id':p['id'],'version':version,'active':False})
        q=self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-01','rate':'88','version':0})
        with self.assertRaises(ValueError):self.save('transport-quote-delete',{'id':q['id'],'version':True})
        self.assertEqual(next(x for x in tc.providers(self.c) if x['id']==p['id'])['version'],p['version'])
    def test_historical_bill_without_actual_quantity_can_receive_payment(self):
        old={'id':'SO-LEGACY-NO-ACTUAL','customer_id':'C001','business_date':'2026-10-21','lines':[{'product_id':'P003','bill_qty':20}],'paid_cents':0}
        updated={**old,'paid_cents':500};tc.guard_order(self.c,old,updated);self.assertEqual(tc.order_signature(old),tc.order_signature(updated))
        self.assertNotEqual(tc.order_signature(old),tc.order_signature({**old,'lines':[{'product_id':'P003','actual_qty':'0'}]}))

class TransportBillingTests(unittest.TestCase):
    setUp=fixture.DeliveryTradeTests.setUp
    tearDown=fixture.DeliveryTradeTests.tearDown
    save=fixture.DeliveryTradeTests.save
    order=fixture.DeliveryTradeTests.order
    setup_trip=TransportClosureTests.setup_trip
    issue=TransportClosureTests.issue
    def test_monthly_contract_covers_delivery_trips_and_charges_once(self):
        p,o,plan,r=self.setup_trip(quote=False)
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-01','rate':'220','mode':'monthly','version':0})
        tc.sync(self.c,'2026-10-22','管理员',self.erp.now,self.erp.audit)
        r=next(t for t in trade.records(self.c,'trip') if t['trip_id']=='CLOSE-T')
        self.assertEqual(r['amount_cents'],0);self.assertFalse(r['pricing_pending'])
        self.assertEqual(r['covered_by_monthly'],tc.quotes(self.c)[0]['id'])
        doc=self.issue(p);self.assertEqual(doc['amount_cents'],22000);self.assertEqual(doc['contract_count'],1)
        with self.assertRaisesRegex(ValueError,'已生成结算单'):self.issue(p)
    def test_vehicle_specific_trip_quotes_fall_back_to_unrestricted(self):
        p,o,plan,r=self.setup_trip(quote=False)
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-01','rate':'200','vehicle':'依维柯','version':0})
        self.assertEqual(tc.quote(self.c,p['id'],'昌吉','2026-10-22','依维柯')['amount_cents'],20000)
        self.assertIsNone(tc.quote(self.c,p['id'],'昌吉','2026-10-22','大车'))
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-01','rate':'1000','vehicle':'大车','version':0})
        self.assertEqual(tc.quote(self.c,p['id'],'昌吉','2026-10-22','大车')['amount_cents'],100000)
        self.save('transport-quote',{'provider_id':p['id'],'area':'乌鲁木齐','effective_date':'2026-10-01','rate':'300','version':0})
        self.assertEqual(tc.quote(self.c,p['id'],'乌鲁木齐','2026-10-22','依维柯')['amount_cents'],30000)
    def test_temp_task_enters_settlement_and_is_locked_after(self):
        p,o,plan,r=self.setup_trip()
        t=self.save('transport-task',{'provider_id':p['id'],'business_date':'2026-10-25','task':'crate','rate':'150','note':'收框子三套'})
        self.assertEqual(t['task'],'crate');self.assertEqual(t['task_label'],'收框');self.assertEqual(t['amount_cents'],15000)
        report=trade.transport_report(self.c,'2026-10');self.assertEqual(len(report['tasks']),1)
        doc=self.issue(p);self.assertEqual(doc['amount_cents'],25000);self.assertEqual(doc['task_count'],1)
        with self.assertRaisesRegex(ValueError,'已结算|已变化'):self.save('transport-task-void',{'id':t['id'],'version':1,'note':'测试'})
    def test_monthly_price_change_uses_new_effective_contract(self):
        p,o,plan,r=self.setup_trip(quote=False)
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-09-01','rate':'200','mode':'monthly','version':0})
        self.save('transport-quote',{'provider_id':p['id'],'area':'昌吉','effective_date':'2026-10-15','rate':'220','mode':'monthly','version':0})
        charges=tc.monthly_charges(self.c,'2026-10')
        self.assertEqual([x['amount_cents'] for x in charges], [22000])
