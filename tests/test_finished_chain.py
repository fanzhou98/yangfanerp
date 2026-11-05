"""Quantity-first procurement, per-receipt accounting, returns and cash reconciliation."""
import json
import unittest
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
import test_accounting_supply as base
import finished_goods as fg
import purchasing
import inventory
import trade
import funds
import resources_costs as rc
import erp_access


class FinishedChainTests(unittest.TestCase):
    def setUp(self):
        base.AccountingSupplyTests.setUp(self)
        self.future_month=(datetime.strptime(self.day,'%Y-%m-%d')+timedelta(days=31)).strftime('%Y-%m')
    tearDown=base.AccountingSupplyTests.tearDown
    product=base.AccountingSupplyTests.product
    supplier=base.AccountingSupplyTests.supplier
    plan=base.AccountingSupplyTests.plan
    order=base.AccountingSupplyTests.order
    save=base.AccountingSupplyTests.save

    def prepare(self,kind='purchased'):
        self.product('OIL','油豆腐')
        if kind=='mixed':
            cfg=trade.metadata(self.c,'product_trade');cfg['OIL']['supply_kind']='mixed';self.c.execute("UPDATE meta SET value=? WHERE key='product_trade'",(rc.dump(cfg),))
        self.plan();return self.supplier()
    def receive(self,qty='8',expected='10',**extras):
        b={'business_date':self.day,'supplier_id':self.supplier()['id'],'product_id':'OIL','qty':qty,'expected_qty':expected,'handler':'库管','note':'现场到货核对','inventory_revision':inventory.revision(self.c),**extras}
        return self.save('stock-receipt',b,'库管')
    def price(self,r,price='2',**extras):
        return self.save('price',{'receipt_id':r['id'],'version':r['version'],'business_date':r['business_date'],'billing_unit':'盒','price':price,'evidence_checked':True,'note':'逐笔确认采购单价',**extras},'会计')
    def current(self,r):return next(v for v in fg.records(self.c,'receipt') if v['id']==r['id'])
    def pay(self,r,amount,account=''):
        return self.save('payment',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'amount':amount,'method':'现金','handler':'出纳','note':'实际现金付款','account_id':account},'出纳')
    def ret(self,r,qty,**extras):
        return self.save('stock-return',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'qty':qty,'inventory_revision':inventory.revision(self.c),'handler':'库管','note':'不接受多发实际退回',**extras},'库管')
    def account(self):
        return funds.save(self.c,'account',{'name':'采购银行户','kind':'银行账户','opening_date':self.day,'opening_balance':'100','note':'实盘期初','request_key':str(uuid.uuid4())},'管理员',self.erp.now,self.erp.audit)

    def test_category_crud_search_labels_and_eligibility(self):
        ops=purchasing.Operations(self.c,self.erp.now,self.erp.audit)
        cat=ops.category({'name':'合作成品','kind':'finished'},'会计')
        s=ops.supplier({'name':'综合供应商','category_ids':['SC-RAW',cat['id']]},'会计')
        self.assertTrue(purchasing.finished_supplier(self.c,s))
        self.assertEqual(set(s['category_ids']),{'SC-RAW',cat['id']})
        with self.assertRaisesRegex(ValueError,'使用'):ops.category({'id':cat['id'],'version':1,'action':'delete'},'会计')
        cat=ops.category({**cat,'name':'定制成品'},'会计');self.assertEqual(cat['version'],2)
        ops.supplier({**s,'category_ids':['SC-RAW']},'会计')
        ops.category({'id':cat['id'],'version':2,'action':'delete'},'会计')
        self.assertNotIn(cat['id'],[c['id'] for c in purchasing.categories(self.c)])
        with self.assertRaises(ValueError):self.erp.master({'kind':'product','create':True,'id':'BAD','name':'原料商不能供成品','unit':'盒','billing_unit':'盒','price':'1','tare':'0','supply_kind':'purchased','supplier_ids':[s['id']]},'管理员',connection=self.c)

    def test_shortage_additional_receipt_and_idempotency(self):
        self.prepare();r=self.receive();self.assertTrue(r['pricing_pending']);self.assertEqual(r['amount_cents'],0)
        self.assertEqual(fg.stock_cost(self.c,self.day,self.day)[0]['ending_unvalued_qty'],'8')
        order=fg.inventory_projection(self.c)['orders'][0];self.assertEqual(order['remaining_qty'],'2')
        more=self.receive('2',order_id=order['id']);self.assertEqual(len(fg.records(self.c,'order')),1)
        self.assertEqual(fg.supplied(self.c,self.day,'OIL'),10)
        self.assertEqual(fg.inventory_projection(self.c)['orders'][0]['remaining_qty'],'0')
        with self.assertRaisesRegex(ValueError,'多发'):self.receive('1',order_id=order['id'])
        self.assertEqual(len(fg.records(self.c,'receipt')),2)  # rejected write is atomic
        extra=self.receive('1',order_id=order['id'],accept_over=True)
        self.assertEqual(fg.inventory_projection(self.c)['orders'][0]['over_qty'],'1')
        self.ret(extra,'1');self.assertEqual(fg.supplied(self.c,self.day,'OIL'),10)
        self.assertEqual(fg.inventory_projection(self.c)['orders'][0]['over_qty'],'0')
        self.price(r,'2');self.price(more,'3')
        self.assertEqual(fg.projection(self.c,self.month)['totals']['outstanding_cents'],2200)

    def test_unpriced_projection_suggests_supplier_price(self):
        s=self.prepare()
        purchasing.Operations(self.c,self.erp.now,self.erp.audit).supplier({**s,'product_prices':{'OIL':'1.25'}},'管理员')
        r=self.receive()
        receipt=next(x for x in fg.projection(self.c,self.month)['receipts'] if x['id']==r['id'])
        self.assertEqual(receipt['lines'][0]['suggested_price'],'1.25')
        self.price(r,'2')
        receipt=next(x for x in fg.projection(self.c,self.month)['receipts'] if x['id']==r['id'])
        self.assertNotIn('suggested_price',receipt['lines'][0])

    def test_unpriced_edit_stock_and_permissions_no_money_leak(self):
        self.prepare();r=self.receive()
        updated=self.save('stock-edit',{'receipt_id':r['id'],'version':1,'business_date':self.day,'qty':'9','handler':'库管','note':'重新清点9盒','inventory_revision':inventory.revision(self.c)},'库管')
        self.assertEqual(fg.supplied(self.c,self.day,'OIL'),9)
        with self.assertRaisesRegex(ValueError,'更新'):self.save('stock-edit',{'receipt_id':r['id'],'version':1,'business_date':self.day,'qty':'8','handler':'库管','note':'旧页面','inventory_revision':inventory.revision(self.c)},'库管')
        with self.assertRaises(ValueError):self.price(updated,evidence_checked=False)
        self.price(updated)
        with self.assertRaisesRegex(ValueError,'已计价'):self.save('stock-edit',{'receipt_id':r['id'],'version':3,'business_date':self.day,'qty':'7','handler':'库管','note':'不能覆盖','inventory_revision':inventory.revision(self.c)},'库管')
        for doc in [fg.quantity_only(fg.projection(self.c,self.month)),fg.inventory_projection(self.c)]:
            text=rc.dump(doc)
            for key in ('amount_cents','price','paid_cents','fingerprint','pricing_history','due_date'):self.assertNotIn('"'+key+'"',text)
        with self.assertRaises(ValueError):self.save('price',{'receipt_id':r['id']},'库管')
        self.c.commit();payload=self.erp.bootstrap()
        scoped=erp_access.scope_bootstrap(payload,{'role':'库管','permissions':erp_access.defaults('库管')})
        self.assertEqual(len(scoped['finished_goods_inventory']['receipts']),1)
        self.assertNotIn('amount_cents',rc.dump(scoped['finished_goods_inventory']))

    def test_cash_payment_return_repricing_and_refund_preserve_archives(self):
        self.prepare();r=self.price(self.receive('10'));a=self.account()
        with self.assertRaisesRegex(ValueError,'资金账户'):self.pay(r,'20')
        self.pay(r,'20',a['id']);r=self.current(r)
        preview=fg.statement_preview(self.c,r['supplier_id'],self.month)
        doc=self.save('statement',{'supplier_id':r['supplier_id'],'month':self.month,'source_fingerprint':preview['source_fingerprint'],'handler':'会计'})
        frozen=rc.dump(doc)
        self.ret(r,'2');r=self.current(r)
        p=fg.projection(self.c,self.month);orig=next(x for x in p['receipts'] if x['id']==r['id']);self.assertEqual(orig['outstanding_cents'],-400)
        back=self.save('price-return',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'note':'供应商确认单价应为1.5'},'会计')
        with self.assertRaisesRegex(ValueError,'未计价'):fg.statement_preview(self.c,r['supplier_id'],self.month)
        r=self.price(back,'1.5');self.assertEqual(len(r['pricing_history']),2)
        before=funds.report(self.c,self.day);self.assertEqual(before['accounts'][0]['balance_cents'],8000)
        self.assertEqual(fg.projection(self.c,self.month)['totals']['outstanding_cents'],-800)
        self.save('refund',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'amount':'8','account_id':a['id'],'handler':'出纳','note':'供应商原路退款'},'出纳')
        self.assertEqual(funds.report(self.c,self.day)['accounts'][0]['balance_cents'],8800)
        self.assertEqual(fg.projection(self.c,self.month)['totals']['outstanding_cents'],0)
        self.assertEqual(rc.dump(fg.records(self.c,'statement')[0]),rc.dump({k:v for k,v in doc.items() if k!='fingerprint'}))
        self.assertEqual(frozen,rc.dump(doc))
        self.assertEqual(fg.stock_cost(self.c,self.day,self.day)[0]['ending_value_cents'],1200)

    def test_refund_cannot_backdate_into_closed_month(self):
        self.prepare(); r = self.price(self.receive('10')); a = self.account()
        self.pay(r, '20', a['id']); r = self.current(r)
        self.ret(r, '2'); r = self.current(r)
        back = self.save('price-return', {'receipt_id': r['id'], 'version': r['version'],
                                          'business_date': self.day, 'note': '供应商确认单价应为1.5'}, '会计')
        r = self.price(back, '1.5')
        body = {'receipt_id': r['id'], 'version': r['version'], 'business_date': self.day,
                'amount': '8', 'account_id': a['id'], 'handler': '出纳', 'note': '供应商原路退款'}
        self.c.execute("INSERT OR REPLACE INTO resource_periods VALUES(?,?,?)",
                       (self.month, 1, rc.dump({'month': self.month, 'state': 'closed', 'version': 1, 'at': self.day, 'role': '管理员'})))
        with self.assertRaisesRegex(ValueError, '已结账'):
            self.save('refund', dict(body), '出纳')
        self.c.execute('DELETE FROM resource_periods')
        self.save('refund', dict(body), '出纳')
        self.assertEqual(fg.projection(self.c, self.month)['totals']['outstanding_cents'], 0)

    def test_returns_cannot_remove_shipped_stock_and_errors_rollback(self):
        self.prepare();r=self.price(self.receive('10'));self.order('OIL','9')
        before=rc.dump(fg.records(self.c));revision=inventory.revision(self.c)
        with self.assertRaises(ValueError):self.ret(r,'2')
        self.assertEqual(rc.dump(fg.records(self.c)),before);self.assertEqual(inventory.revision(self.c),revision)
        self.ret(r,'1');self.assertEqual(fg.supplied(self.c,self.day,'OIL'),9)

    def test_mixed_source_external_cost_does_not_treat_self_as_unpriced_purchase(self):
        self.prepare('mixed');r=self.price(self.receive('3','3'))
        plan=json.loads(self.c.execute('SELECT payload FROM warehouse_plans WHERE business_date=?',(self.day,)).fetchone()[0]);next(p for p in plan['stock'] if p['product_id']=='OIL')['produced_qty']='2';self.c.execute('UPDATE warehouse_plans SET payload=? WHERE business_date=?',(rc.dump(plan),self.day));self.order('OIL','5')
        cost=fg.stock_cost(self.c,self.day,self.day)[0]
        self.assertEqual(cost['sales_cost_cents'],600);self.assertEqual(cost['sold_qty'],'3');self.assertEqual(cost['unvalued_qty'],'0')
        self.assertFalse(fg.is_purchased(self.c,'OIL'))

    def test_close_order_balance_and_reopen(self):
        self.prepare();r=self.receive();o=fg.records(self.c,'order')[0]
        closed=self.save('order-edit',{'order_id':o['id'],'version':1,'expected_qty':'10','state':'closed','business_date':self.day,'note':'供应商确认不再补发'},'库管')
        with self.assertRaisesRegex(ValueError,'关闭'):self.receive('2',order_id=o['id'])
        self.save('order-edit',{'order_id':o['id'],'version':closed['version'],'expected_qty':'10','state':'open','business_date':self.day,'note':'重新安排补到'},'库管')
        self.receive('2',order_id=o['id'])
        self.assertEqual(fg.inventory_projection(self.c)['orders'][0]['remaining_qty'],'0')

    def test_closed_stock_date_allows_price_but_not_quantity_rewrite(self):
        self.prepare();r=self.receive()
        self.c.execute('INSERT INTO stock_closings VALUES(?,?)',(self.day,rc.dump({'id':'CLOSE','business_date':self.day,'state':'closed','version':1,'products':[]})))
        with self.assertRaisesRegex(ValueError,'日结'):self.receive('2')
        self.price(r)
        self.assertEqual(len(fg.records(self.c,'receipt')),1)

    def test_future_closed_cost_period_blocks_repricing(self):
        self.prepare();r=self.price(self.receive())
        self.c.execute('INSERT INTO resource_periods VALUES(?,?,?)',(self.future_month,1,rc.dump({'month':self.future_month,'state':'closed'})))
        with self.assertRaisesRegex(ValueError,'结账'):self.save('price-return',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'note':'不能越过结账'},'会计')

    def test_pending_purchase_blocks_cost_close_and_supplier_can_be_corrected(self):
        self.prepare();r=self.receive()
        self.c.execute("UPDATE material_entries SET payload=json_set(payload,'$.amount_cents',100,'$.cost_cents',100) WHERE json_extract(payload,'$.amount_cents')=0")
        with self.assertRaisesRegex(ValueError,'外购成品'):rc.Operations(self.c,self.erp.now,self.erp.audit).period({'month':self.month,'state':'closed','version':0,'note':'尚未算票不能结账'},'会计')
        supplier=purchasing.Operations(self.c,self.erp.now,self.erp.audit).supplier({'name':'真实成品供应商','category_ids':['SC-FINISHED']},'会计')
        cfg=trade.metadata(self.c,'product_trade');cfg['OIL']['supplier_ids'].append(supplier['id']);self.c.execute("UPDATE meta SET value=? WHERE key='product_trade'",(rc.dump(cfg),))
        changed=self.save('stock-edit',{'receipt_id':r['id'],'version':r['version'],'supplier_id':supplier['id'],'business_date':self.day,'qty':'8','handler':'库管','note':'纠正供应商选择','inventory_revision':inventory.revision(self.c)},'库管')
        self.assertEqual(changed['supplier_id'],supplier['id']);self.assertEqual(fg.records(self.c,'order')[0]['supplier_id'],supplier['id'])
        self.price(changed)
        result=rc.Operations(self.c,self.erp.now,self.erp.audit).period({'month':self.month,'state':'closed','version':0,'note':'全部算票后结账'},'会计')
        self.assertEqual(result['state'],'closed')

    def test_legacy_multi_product_order_can_reprice_and_return_one_product(self):
        self.prepare();self.product('OIL2','外购成品2');self.plan()
        r=self.save('receipt',{'business_date':self.day,'supplier_id':self.supplier()['id'],'inventory_revision':inventory.revision(self.c),'handler':'会计','note':'历史多产品到货','lines':[{'product_id':pid,'qty':'3','billing_unit':'盒','price':'0.333'} for pid in ['OIL','OIL2']]})
        back=self.save('price-return',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'note':'逐产品修正历史采购价'},'会计')
        r=self.price(back,lines=[{'product_id':pid,'billing_unit':'盒','price':price} for pid,price in [('OIL','0.333'),('OIL2','2')]])
        self.assertEqual(len(r['lines']),2);self.assertEqual(r['amount_cents'],700)
        for _ in range(3):
            self.ret(self.current(r),'1',product_id='OIL')
        self.assertEqual(fg.supplied(self.c,self.day,'OIL'),0)
        cost=next(x for x in fg.stock_cost(self.c,self.day,self.day) if x['product_id']=='OIL');self.assertEqual(cost['ending_value_cents'],0)
        self.assertEqual(fg.projection(self.c,self.month)['totals']['outstanding_cents'],600)

    def test_void_blocks_when_purchased_batch_already_shipped(self):
        self.prepare();r=self.price(self.receive('8'))
        self.c.execute('INSERT INTO orders VALUES(?,?)',('SO-FG',rc.dump({'id':'SO-FG','customer_id':'C001','business_date':self.day,'state':'reviewed','total_cents':300,'paid_cents':0,'return_credit_cents':0,'lines':[{'product_id':'OIL','product_name':'油豆腐','unit':'盒','billing_unit':'盒','actual_qty':'3','bill_qty':'3','amount_cents':300}]})))
        with self.assertRaisesRegex(ValueError,'已有发货'):
            self.save('void',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'note':'误登记'},'会计')
        self.c.execute("DELETE FROM orders WHERE id='SO-FG'")
        voided=self.save('void',{'receipt_id':r['id'],'version':r['version'],'business_date':self.day,'note':'误登记'},'会计')
        self.assertTrue(voided['voided'])
