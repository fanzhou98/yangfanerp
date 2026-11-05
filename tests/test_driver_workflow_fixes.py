import base64,json,uuid
from pathlib import Path
import unittest
from unittest.mock import patch
import test_driver_portal as fixture
import driver_portal as dp,billing,resources_costs as rc

erp=fixture.fixture.erp

class DriverWorkflowFixTests(unittest.TestCase):
    setUp=fixture.DriverPortalTests.setUp
    tearDown=fixture.DriverPortalTests.tearDown

    def test_required_return_photo_and_retry_are_enforced_by_server(self):
        self.c.execute("UPDATE factory_settings SET payload=json_set(payload,'$.driver_crate_photo_required','1') WHERE id='default'")
        oid='DRIVER-ORDER-1'
        body={'request_key':'first-return','business_date':'2020-01-03','source_date':'2020-01-02','source_trip_id':'TB','vehicle_id':'V002','by_order':True,'lines':[{'order_id':oid,'asset_id':'P-LARGE','qty':3}]}
        with self.assertRaisesRegex(ValueError,'拍摄回框照片'):dp.submit(self.c,self.a,body,erp.now,erp.audit)
        self.assertEqual(len(dp.pending(self.c)),0)
        photo='data:image/jpeg;base64,'+base64.b64encode(b'crate-photo').decode()
        body['photos']={oid:{'keep':[],'add':[photo]}}
        with patch.object(dp,'PHOTO_ROOT',Path(self.tmp.name)/'driver-photos'):
            first=dp.submit(self.c,self.a,body,erp.now,erp.audit)
            self.assertEqual(dp.submit(self.c,self.a,body,erp.now,erp.audit),first)
            self.assertEqual(dp.photo(self.c,self.a,oid,'crate')['data'],b'crate-photo')
            self.assertEqual(len(dp.pending(self.c)),1)
        self.assertEqual(first['business_date'],'2020-01-03')

    def test_driver_gross_uses_confirmed_crates_and_driver_priority(self):
        o=json.loads(self.c.execute("SELECT payload FROM orders WHERE id='DRIVER-ORDER-0'").fetchone()[0])
        l=next(l for l in o['lines'] if l['unit']=='筐')
        l.update(actual_qty='3',ordered_qty='3',customer=[{'gross':'59','count':'3','tare':'2'}],customer_net='53',crate_lines=[{'asset_id':'CR-WHITE','qty':3,'tare':'2'}])
        l.pop('driver_weight_basis',None)
        o.update(lines=[l],state='dispatched',weight_confirmation=None,paid_cents=0,discount_cents=0,rounding_cents=0,return_credit_cents=0)
        self.c.execute('UPDATE orders SET payload=? WHERE id=?',(rc.dump(o),o['id']))
        dp.save_weights(self.c,self.a,{'order_id':o['id'],'version':o['version'],'request_key':str(uuid.uuid4()),'lines':[{'product_id':l['product_id'],'driver':[{'count':'3','gross':'60','tare':'1'}]}]},erp.now,erp.audit,erp.weights,erp.save)
        line=json.loads(self.c.execute('SELECT payload FROM orders WHERE id=?',(o['id'],)).fetchone()[0])['lines'][0]
        self.assertEqual(line['driver_weight_basis'],'gross');self.assertEqual(line['driver_net'],'54')
        self.assertEqual(billing.default_weight_mode(line),'driver')

    def test_photo_failure_and_later_rollback_preserve_original_file(self):
        with patch.object(dp,'PHOTO_ROOT',Path(self.tmp.name)/'driver-photos'):
            oid='DRIVER-ORDER-0';path=dp.save_photo(self.c,self.a,oid,'weight',b'original','image/jpeg',erp.now());self.c.commit()
            token=dp.begin_photo_transaction();self.c.execute('SAVEPOINT photo_upload')
            try:
                dp.apply_photo_set(self.c,self.a,oid,'weight',{'keep':[],'add':['invalid']},erp.now())
            except ValueError:pass
            self.assertEqual(Path(path).read_bytes(),b'original')
            photo='data:image/jpeg;base64,'+base64.b64encode(b'new-photo').decode()
            dp.apply_photo_set(self.c,self.a,oid,'weight',{'keep':[],'add':[photo]},erp.now())
            replacement=self.c.execute('SELECT path FROM driver_photos WHERE order_id=?',(oid,)).fetchone()[0]
            self.c.execute('ROLLBACK TO photo_upload');dp.finish_photo_transaction(self.c,token)
            self.assertEqual(Path(path).read_bytes(),b'original');self.assertFalse(Path(replacement).exists())
            self.assertEqual(self.c.execute('SELECT path FROM driver_photos WHERE order_id=?',(oid,)).fetchone()[0],path)

    def test_void_only_material_can_correct_unit_preserving_history(self):
        ops=rc.Operations(self.c,erp.now,erp.audit)
        item=ops.item({'name':'误录测试辅料','category':'辅料','unit':'公斤','reorder_qty':'0'},'管理员')
        e=ops.material({'material_id':item['id'],'business_date':'2020-01-02','kind':'opening','qty':'1','amount':'2','warehouse_id':'WH-COMMON','note':'误录测试','handler':'测试','revision':rc.revision(self.c),'request_key':str(uuid.uuid4())},'管理员')
        with self.assertRaises(ValueError):ops.item({**item,'unit':'包'},'管理员')
        ops.void({'ledger':'material','id':e['id'],'version':e['version'],'reason':'误录撤销'},'管理员')
        corrected=ops.item({**item,'unit':'包'},'管理员');self.assertEqual(corrected['unit'],'包')
        history=json.loads(self.c.execute('SELECT payload FROM material_entries WHERE id=?',(e['id'],)).fetchone()[0])
        self.assertTrue(history['voided']);self.assertEqual(history['unit'],'公斤')
