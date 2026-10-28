import unittest,uuid
import test_auth_http as fixture

class InventoryCheckHTTP(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def test_quantity_only_read_write_csrf_and_separate_accountant_access(self):
        wh,_=self.user();acc,_=self.user('accountant','会计');driver,_=self.user('driver','司机')
        day='2026-10-29';path='/api/inventory-check?date='+day
        code,r,_=wh.request(path);self.assertEqual(code,200,r);p=r['products'][0]
        body={'business_date':day,'version':0,'request_key':str(uuid.uuid4()),'source_fingerprint':r['source_fingerprint'],'sources_checked':True,'handler':'库管','note':'发货前后独立盘点','products':[{'product_id':p['product_id'],'unit':p['unit'],'pre_qty':'700','post_qty':'700','post_in_qty':'0','post_out_qty':'0'}]}
        self.assertEqual(wh.request('/api/inventory-check',body,csrf=False)[0],403)
        self.assertEqual(acc.request('/api/inventory-check',body)[0],403)
        self.assertEqual(wh.request('/api/inventory-check',body)[0],200)
        self.assertEqual(wh.request('/api/inventory-check',body)[0],200)
        code,r,_=acc.request(path);self.assertEqual(code,200,r);self.assertEqual(r['version'],1)
        self.assertNotIn('amount_cents',str(r));self.assertNotIn('price',str(r))
        bootstrap=acc.request('/api/bootstrap')[1]
        self.assertIn('inventory.reconciliation',bootstrap['permissions']['modules']);self.assertNotIn('inventory.operations',bootstrap['permissions']['modules'])
        self.assertEqual(driver.request(path)[0],403)
        self.assertEqual(acc.request('/api/inventory?date='+day)[0],403)
        self.assertEqual(wh.request('/api/inventory-check?date=bad')[0],400)

if __name__=='__main__':unittest.main()
