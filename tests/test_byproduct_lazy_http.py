"""Byproduct history is initialized on demand; summary and original records stay fresh."""
import unittest
import uuid
from decimal import Decimal

import test_auth_http as fixture
import resources_costs as rc

erp=fixture.erp


class ByproductLazyHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user

    def customer(self,name='豆渣历史客户'):
        status,value,_=self.admin.request('/api/master',{'kind':'customer','create':True,'name':name,'legal_name':name+'养殖场',
            'phone':'123456789','route':'豆渣自取','delivery_method':'pickup','business_kind':'byproduct'})
        self.assertEqual(status,200,value);return value['id']

    def sale(self,cid,day,qty,price,received):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).byproduct({'customer_id':cid,'business_date':day,'qty':qty,'price':price,
                'received':received,'handler':'会计','note':'豆渣历史','request_key':str(uuid.uuid4())},'管理员')

    def summary(self,query='?month=2026-10'):
        return self.admin.request('/api/byproduct-summary'+query)

    def test_bootstrap_defers_history_and_summary_replaces_it(self):
        cid=self.customer()
        open_sale=self.sale(cid,'2026-10-20','100','0.5','10')
        self.sale(cid,'2026-09-15','60','0.5','30')
        status,legacy,_=self.admin.request('/api/bootstrap');self.assertEqual(status,200)
        self.assertEqual(len(legacy['resources']['byproducts']),2)
        self.assertFalse(legacy['resources']['byproduct_history_deferred'])
        status,deferred,_=self.admin.request('/api/bootstrap',headers={'X-ERP-Byproduct-History':'deferred'});self.assertEqual(status,200)
        self.assertTrue(deferred['resources']['byproduct_history_deferred'])
        self.assertEqual(deferred['resources']['byproducts'],[])
        self.assertEqual(deferred['resources']['revision'],legacy['resources']['revision'])
        self.assertEqual(self.admin.request('/api/bootstrap',headers={'X-ERP-Byproduct-History':'bad'})[0],400)
        status,value,_=self.summary();self.assertEqual(status,200,value)
        self.assertEqual(value['month'],'2026-10');self.assertEqual(value['month_cents'],5000)
        self.assertEqual(value['month_received_cents'],1000);self.assertEqual(Decimal(value['month_qty_kg']),Decimal(100))
        self.assertEqual(value['outstanding_cents'],4000)
        self.assertEqual([r['id'] for r in value['outstanding']],[open_sale['id']])
        self.assertEqual(value['outstanding_total'],1)
        row=next(r for r in value['customers'] if r['customer_id']==cid)
        self.assertEqual((row['month_cents'],row['outstanding_cents']),(5000,4000))
        status,empty,_=self.summary('?month=2026-08');self.assertEqual(status,200)
        self.assertEqual(empty['month_cents'],0)
        self.assertEqual(next(r for r in empty['customers'] if r['customer_id']==cid)['outstanding_cents'],4000)
        status,sales,_=self.admin.request('/api/byproduct-sales?customer_id='+cid);self.assertEqual(status,200,sales)
        self.assertEqual(len(sales['rows']),2)
        self.assertEqual([r['business_date'] for r in sales['rows']],['2026-09-15','2026-10-20'])
        for path in ('/api/byproduct-summary?month=2026-10&month=2026-11','/api/byproduct-summary?month=bad',
                     '/api/byproduct-sales','/api/byproduct-sales?customer_id=missing'):
            self.assertEqual(self.admin.request(path)[0],400,(path,self.admin.request(path)[1]))
        self.assertEqual(self.admin.request('/api/byproduct-summary')[0],200)

    def test_permissions_and_voided_original_record(self):
        cid=self.customer('豆渣权限客户')
        sale=self.sale(cid,'2026-10-21','20','0.5','0')
        accountant,_=self.user('bean-accountant','会计');warehouse,_=self.user('bean-warehouse','库管')
        self.assertEqual(accountant.request('/api/byproduct-summary?month=2026-10')[0],200)
        self.assertEqual(accountant.request('/api/byproduct-sales?customer_id='+cid)[0],200)
        self.assertEqual(warehouse.request('/api/byproduct-summary?month=2026-10')[0],403)
        self.assertEqual(warehouse.request('/api/byproduct-sales?customer_id='+cid)[0],403)
        status,ledger,_=self.admin.request('/api/resource-ledger?kind=byproducts&all=1&record_id='+sale['id']+'&page_size=1')
        self.assertEqual(status,200,ledger);self.assertEqual(ledger['rows'][0]['id'],sale['id'])
        with erp.connect(True) as c:
            rc.Operations(c,erp.now,erp.audit).void({'ledger':'byproduct','id':sale['id'],'version':sale['version'],'reason':'登记有误'},'管理员')
        self.assertEqual(self.admin.request('/api/resource-ledger?kind=byproducts&all=1&record_id='+sale['id'])[1]['total'],0)
        status,voided,_=self.admin.request('/api/resource-ledger?kind=byproducts&all=1&stage=voided&record_id='+sale['id'])
        self.assertEqual(status,200);self.assertEqual(voided['rows'][0]['id'],sale['id'])
        self.assertEqual(self.admin.request('/api/byproduct-sales?customer_id='+cid)[1]['rows'],[])
        self.assertEqual(self.summary()[1]['outstanding_cents'],0)
