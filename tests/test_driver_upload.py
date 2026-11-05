"""Photo batches cross the WSGI boundary; oversized bodies never reach writes."""
import base64
import io
import json
from pathlib import Path
import unittest
import uuid
from wsgiref.util import setup_testing_defaults

import cloud_app
import driver_portal as dp
import test_driver_portal as fixture
from ops.cloud.driver_upload_limits import updated_config


class PhotoBatchTests(unittest.TestCase):
    setUp = fixture.DriverPortalTests.setUp
    tearDown = fixture.DriverPortalTests.tearDown

    def request(self, app, path, body, headers=None):
        raw=json.dumps(body).encode()
        env={};setup_testing_defaults(env)
        env.update(PATH_INFO=path,REQUEST_METHOD='POST',HTTP_HOST='erp.test',
                   REMOTE_ADDR='198.51.100.2',CONTENT_LENGTH=str(len(raw)),
                   CONTENT_TYPE='application/json',HTTP_X_ERP_CLIENT='local-pilot',
                   HTTP_ORIGIN='https://erp.test')
        env['wsgi.url_scheme']='https';env['wsgi.input']=io.BytesIO(raw)
        env.update(headers or {})
        response={}
        def start(status,values):response.update(status=int(status.split()[0]),headers=values)
        response['body']=json.loads(b''.join(app(env,start)))
        return response

    def test_batch_over_old_nginx_waitress_and_handler_limits_saves(self):
        o=json.loads(self.c.execute("SELECT payload FROM orders WHERE id='DRIVER-ORDER-0'").fetchone()[0])
        o.update(state='dispatched',weight_confirmation=None,paid_cents=0,discount_cents=0,rounding_cents=0,return_credit_cents=0)
        self.c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),o['id']));self.c.commit()
        app=cloud_app.create_application(fixture.fixture.erp.DB,'https://erp.test')
        login=self.request(app,'/api/auth/login',{'username':'drivera','password':'Driver-A-Password-2026!'})
        cookies=[v.split(';')[0] for k,v in login['headers'] if k=='Set-Cookie']
        csrf=next(v.split('=',1)[1] for v in cookies if v.startswith('erp_csrf='))
        headers={'HTTP_COOKIE':'; '.join(cookies),'HTTP_X_CSRF_TOKEN':csrf}
        # Initial accounts require a password change before business writes.
        self.c.execute('UPDATE auth_users SET must_change_password=0 WHERE id=?',(self.a['id'],));self.c.commit()
        line=next(l for l in o['lines'] if l['unit']=='筐')
        raw=b'\xff\xd8'+b'x'*(1200*1024)
        photo='data:image/jpeg;base64,'+base64.b64encode(raw).decode()
        body={'order_id':o['id'],'version':o['version'],'lines':[{'product_id':line['product_id'],'driver':[{'count':line['actual_qty'],'gross':'400','tare':'1'}]}],'photos':{line['product_id']:{'keep':[],'add':[photo,photo]}},'request_key':str(uuid.uuid4())}
        self.assertGreater(len(json.dumps(body)),2621440)
        result=self.request(app,'/api/driver/weights',body,headers)
        self.assertEqual(result['status'],200,result['body'])
        photos=self.c.execute('SELECT bytes,path FROM driver_photos WHERE order_id=?',(o['id'],)).fetchall()
        self.assertEqual([r['bytes'] for r in photos],[len(raw),len(raw)])
        self.assertTrue(all(Path(r['path']).read_bytes()==raw for r in photos))
        saved=json.loads(self.c.execute('SELECT payload FROM orders WHERE id=?',(o['id'],)).fetchone()[0])
        self.assertEqual(saved['version'],o['version']+1)

    def test_oversize_rejected_without_reading_body_or_writing(self):
        self.c.commit();app=cloud_app.create_application(fixture.fixture.erp.DB,'https://erp.test')
        before=self.c.execute('SELECT count(*) FROM driver_weight_submissions').fetchone()[0]
        for path,limit in [('/api/driver/weights',dp.PHOTO_REQUEST_MAX),('/api/driver/returns',dp.PHOTO_REQUEST_MAX),('/api/auth/login',2621440)]:
            response=self.request(app,path,{}, {'CONTENT_LENGTH':str(limit+1)})
            self.assertEqual(response['status'],413)
            self.assertIn('本次未保存',response['body']['error'])
        self.assertEqual(self.c.execute('SELECT count(*) FROM driver_weight_submissions').fetchone()[0],before)


class NginxLimitsTests(unittest.TestCase):
    def test_upgrade_preserves_existing_config_and_is_idempotent(self):
        template=(Path(__file__).resolve().parents[1]/'ops/cloud/nginx-https.conf.template').read_text()
        start=template.index('    # Driver photos:');end=template.index('    location = /api/auth/login {')
        old=(template[:start]+template[end:]).replace('__HOST__','erp.test')
        new=updated_config(old,template)
        self.assertEqual(new,template.replace('__HOST__','erp.test'))
        self.assertEqual(updated_config(new,template),new)
        self.assertIn('client_max_body_size 1m;',new)
        self.assertEqual(new.count('client_max_body_size 64m;'),2)
        with self.assertRaises(ValueError):updated_config(old+'\nlocation = /api/driver/weights {}',template)
