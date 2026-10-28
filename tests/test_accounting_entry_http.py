import unittest,json
import test_auth_http as fixture

erp=fixture.erp
class AccountingEntryHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPTests.initial_password
    personal_password=fixture.AuthHTTPTests.personal_password
    setUp=fixture.AuthHTTPTests.setUp
    tearDown=fixture.AuthHTTPTests.tearDown
    user=fixture.AuthHTTPTests.user
    def seed(self):
        with erp.connect(True) as c:
            previous=erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-20','batch':'回框原单','lines':[{'product_id':'P001','ordered_qty':'8','actual_qty':'8','price':'3','driver':[],'customer':[],'crate_lines':[{'product_id':'P001','asset_id':'CR-WHITE','qty':8,'tare':'2'}]}]},'管理员',connection=c)
            today=erp.mutate('order',{'customer_id':'C001','business_date':'2026-10-21','batch':'本日配送','lines':[{'product_id':'P001','ordered_qty':'8','actual_qty':'0','price':'3','driver':[],'customer':[]}]},'管理员',connection=c)
        body={**today,'accounting_returns':{'version':0,'business_date':today['business_date'],'lines':[{'product_id':'P001','asset_id':'CR-WHITE','qty':3,'source_order_id':previous['id']}]}}
        return today,body
    def test_accountant_saves_current_return_for_yesterday_without_driver(self):
        today,body=self.seed();accountant,_=self.user('photoacc','会计');code,r,_=accountant.request('/api/orders/'+today['id']+'/order',body);self.assertEqual(code,200,r)
        with erp.connect() as c:
            event=json.loads(c.execute("SELECT payload FROM asset_records WHERE json_extract(payload,'$.accounting_order_id')=?",(today['id'],)).fetchone()[0]);self.assertEqual(event['qty'],3);self.assertEqual(event['business_date'],'2026-10-21');self.assertEqual(event['source_date'],'2026-10-20')
    def test_missing_crate_permission_denies_direct_and_batch(self):
        today,body=self.seed();accountant,_=self.user('photono','会计')
        with erp.connect(True) as c:
            grants=erp.erp_access.defaults('会计');grants['actions']=[a for a in grants['actions'] if a!='crates.write'];c.execute("INSERT INTO role_permissions VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET version=excluded.version,payload=excluded.payload,updated_at=excluded.updated_at",('会计',1,json.dumps(grants),erp.now()))
        self.assertEqual(accountant.request('/api/orders/'+today['id']+'/order',body)[0],403)
        self.assertEqual(accountant.request('/api/batch',{'operations':[{'action':'order','order_id':today['id'],'body':body}]})[0],403)
        with erp.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM asset_records WHERE json_extract(payload,'$.accounting_order_id')=?",(today['id'],)).fetchone()[0],0)
