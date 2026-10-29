"""Real account boundaries for integrated crate settings and deletion."""
import json,unittest
import test_auth_http as fixture

class CrateSettingsHTTPTests(unittest.TestCase):
    initial_password=fixture.AuthHTTPFixture.initial_password
    personal_password=fixture.AuthHTTPFixture.personal_password
    setUp=fixture.AuthHTTPFixture.setUp
    tearDown=fixture.AuthHTTPFixture.tearDown
    user=fixture.AuthHTTPFixture.user

    def test_asset_only_editor_can_save_special_packaging_and_delete_unused(self):
        erp=fixture.erp
        with erp.connect(True) as c:
            grants=erp.erp_access.defaults('会计');grants['modules']=['asset.register','asset.crates'];grants['actions']=['assets.write']
            c.execute("INSERT INTO role_permissions(role,version,payload,updated_at) VALUES('会计',1,?,?) ON CONFLICT(role) DO UPDATE SET version=excluded.version,payload=excluded.payload",(json.dumps(grants),erp.now()))
        client,_=self.user('assetonly','会计')
        body={'name':'可删除新框','category':'周转筐','quantity':0,'request_key':'new-crate','default_tare':'2',
              'special_packaging':[{'id':'SPECIAL-FIBRE','name':'布包','tare':'2.5','active':True}]}
        code,asset,_=client.request('/api/assets/asset',body);self.assertEqual(code,200,asset)
        self.assertEqual(asset['special_packaging'][0]['tare'],'2.5')
        code,catalog,_=client.request('/api/crate-packaging');self.assertEqual(code,200,catalog)
        self.assertEqual(catalog['special_assets'][asset['id']][0]['name'],'布包')
        code,report,_=client.request('/api/assets?date=2020-01-01');self.assertEqual(code,200,report)
        self.assertTrue(next(a for a in report['assets'] if a['id']==asset['id'])['can_delete'])
        deletion={'id':asset['id'],'version':asset['version'],'request_key':'delete-crate'}
        warehouse,_=self.user('deletenotallowed','库管')
        self.assertEqual(warehouse.request('/api/assets/delete-asset',deletion)[0],403)
        self.assertEqual(client.request('/api/assets/delete-asset',{**deletion,'version':0})[0],400)
        code,result,_=client.request('/api/assets/delete-asset',deletion);self.assertEqual(code,200,result)
        self.assertTrue(result['deleted'])
        self.assertEqual(client.request('/api/assets/delete-asset',deletion)[1],result)
        with erp.connect() as c:self.assertIsNone(c.execute('SELECT id FROM asset_records WHERE id=?',(asset['id'],)).fetchone())
