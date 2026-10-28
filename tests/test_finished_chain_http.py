import json
import unittest
import uuid
import test_auth_http as fixture


class FinishedChainHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def test_quantity_only_replay_prices_accounts_and_pure_production_guard(self):
        accountant,_=self.user('chain-accountant','会计');warehouse,_=self.user('chain-warehouse','库管');cashier,_=self.user('chain-cashier','出纳')
        day=self.order_test_day
        status,supplier,_=accountant.request('/api/purchasing/supplier',{'name':'HTTP成品供货人','category_ids':['SC-FINISHED']});self.assertEqual(status,200,supplier);sid=supplier['id']
        status,product,_=accountant.request('/api/master',{'kind':'product','create':True,'id':'HFG','name':'HTTP外购产品','unit':'盒','billing_unit':'盒','price':'3','tare':'0','supply_kind':'purchased','supplier_ids':[sid]});self.assertEqual(status,200,product)
        boot=warehouse.request('/api/bootstrap')[1];revision=boot['inventory_revision']
        bad={'business_date':day,'version':0,'stage':'stock','stock':[{'product_id':'HFG','existing_qty':'0','produced_qty':'1'}],'allocations':[],'customers':[],'order_versions':{},'inventory_revision':revision}
        status,error,_=warehouse.request('/api/warehouse',bad);self.assertEqual(status,400,error);self.assertIn('纯外购',error['error'])
        receipt={'request_key':'http-one','business_date':day,'inventory_revision':revision,'supplier_id':sid,'product_id':'HFG','qty':'5','expected_qty':'6','handler':'库管','note':'到货5盒'}
        self.assertEqual(warehouse.request('/api/finished-goods/stock-receipt',receipt,csrf=False)[0],403)
        status,r,_=warehouse.request('/api/finished-goods/stock-receipt',receipt);self.assertEqual(status,200,r)
        status,replay,_=warehouse.request('/api/finished-goods/stock-receipt',receipt);self.assertEqual(status,200,replay);self.assertEqual(replay,r)
        for value in (r,replay,warehouse.request('/api/bootstrap')[1]['finished_goods_inventory']):
            raw=json.dumps(value)
            for key in ('amount_cents','price','due_date','fingerprint','pricing_history'):self.assertNotIn('"'+key+'"',raw)
        self.assertEqual(warehouse.request('/api/finished-goods?month='+day[:7])[0],403)
        body={'receipt_id':r['id'],'version':r['version'],'business_date':day,'request_key':str(uuid.uuid4()),'price':'2','billing_unit':'盒','note':'逐单核对','evidence_checked':True}
        self.assertEqual(warehouse.request('/api/finished-goods/price',body)[0],403)
        status,priced,_=accountant.request('/api/finished-goods/price',body);self.assertEqual(status,200,priced);self.assertEqual(priced['amount_cents'],1000)
        status,account,_=accountant.request('/api/fund-accounts',{'action':'account','name':'成品付款户','kind':'银行账户','opening_date':day,'opening_balance':'100'});self.assertEqual(status,200,account)
        pay={'receipt_id':r['id'],'version':priced['version'],'business_date':day,'amount':'10','method':'银行转账','handler':'出纳','note':'已实际转账','request_key':str(uuid.uuid4())}
        status,error,_=cashier.request('/api/finished-goods/payment',pay);self.assertEqual(status,400,error);self.assertIn('资金账户',error['error'])
        status,paid,_=cashier.request('/api/finished-goods/payment',{**pay,'account_id':account['id']});self.assertEqual(status,200,paid)
        report=cashier.request('/api/fund-accounts?date='+day)[1];self.assertEqual(next(a for a in report['accounts'] if a['id']==account['id'])['balance_cents'],9000)
