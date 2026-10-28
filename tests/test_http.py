"""Exercise the browser-facing HTTP boundary with a temporary database."""
from test_workflow import erp
from pathlib import Path
import tempfile, threading, unittest, urllib.request, urllib.error, json, sqlite3

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();erp.DB=Path(self.tmp.name)/'http.db';erp.init_db()
        self.server=erp.ThreadingHTTPServer(('127.0.0.1',0),erp.Handler)
        self.server.test_pilot=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,body=None,role='accountant',origin=None,client='local-pilot'):
        headers={'X-ERP-Role':role,'X-ERP-Client':client,'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        request=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request) as r:return r.status,r.read(),r.headers
        except urllib.error.HTTPError as e:return e.code,e.read(),e.headers
    def test_assets_and_bootstrap(self):
        for path in ['/','/app.js','/customers.js','/style.css','/sheets.js','/forms.js','/dispatch.js','/operations.js','/warehouse.js','/inventory.js','/navigation.js','/autosave.js','/print.css','/print.js','/api/bootstrap']:
            status,body,headers=self.request(path);self.assertEqual(status,200);self.assertGreater(len(body),20)
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
    def test_bookmark_icons_and_manifest(self):
        expected={'/favicon.ico':'image/x-icon','/favicon.svg':'image/svg+xml','/favicon-16x16.png':'image/png','/favicon-32x32.png':'image/png','/apple-touch-icon.png':'image/png','/icon-192.png':'image/png','/icon-512.png':'image/png','/icon-maskable-512.png':'image/png','/site.webmanifest':'application/manifest+json; charset=utf-8'}
        for path,ctype in expected.items():
            status,body,headers=self.request(path)
            self.assertEqual(status,200,path);self.assertEqual(headers['Content-Type'],ctype,path);self.assertGreater(len(body),100,path)
        manifest=json.loads(self.request('/site.webmanifest')[1])
        self.assertEqual(manifest['short_name'],'洋帆 ERP')
        self.assertEqual(manifest['theme_color'],'#216c55')
        for icon in manifest['icons']:
            status,body,headers=self.request(icon['src'])
            self.assertEqual(status,200,icon['src']);self.assertEqual(headers['Content-Type'],'image/png');self.assertGreater(len(body),100)
        status,body,_=self.request('/apple-touch-icon.png?v=0.54.2')
        self.assertEqual(status,200);self.assertGreater(len(body),100)
    def test_cashier_return_recalculate_and_approve_http(self):
        body={'customer_id':'C001','business_date':'2026-10-21','batch':'复核退回验证','lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'2','price':'75','driver':[],'customer':[]}]}
        code,raw,_=self.request('/api/orders',body,'warehouse');self.assertEqual(code,200,raw);o=json.loads(raw)
        code,raw,_=self.request('/api/orders/'+o['id']+'/settle',{'version':o['version'],'mode':'customer'},'accountant');self.assertEqual(code,200,raw);o=json.loads(raw)
        code,raw,_=self.request('/api/orders/'+o['id']+'/return-review',{'version':o['version'],'reason':'原价需核对'},'accountant');self.assertEqual(code,400)
        code,raw,_=self.request('/api/orders/'+o['id']+'/return-review',{'version':o['version'],'reason':'原价需核对'},'cashier');self.assertEqual(code,200,raw);o=json.loads(raw);self.assertEqual(o['status'],'待重算')
        code,raw,_=self.request('/api/orders/'+o['id']+'/receipt',{'version':o['version'],'amount':'1'},'cashier');self.assertEqual(code,400)
        code,raw,_=self.request('/api/orders/'+o['id']+'/settle',{'version':o['version'],'mode':'customer','reason':'原价已对照凭据核实'},'accountant');self.assertEqual(code,200,raw);o=json.loads(raw)
        code,raw,_=self.request('/api/orders/'+o['id']+'/review',{'version':o['version'],'evidence_checked':True},'cashier');self.assertEqual(code,200,raw);o=json.loads(raw);self.assertEqual(o['state'],'reviewed');self.assertEqual(len(o['review_history']),2)

    def test_issue_statement_archive_http_permissions_and_snapshot(self):
        order={'customer_id':'C001','business_date':'2026-10-18','batch':'出具对账测试','lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'2','price':'75','driver':[],'customer':[]}]}
        code,raw,_=self.request('/api/orders',order,'warehouse');self.assertEqual(code,200,raw);o=json.loads(raw)
        code,raw,_=self.request('/api/orders/'+o['id']+'/settle',{'version':o['version'],'mode':'customer'},'accountant');self.assertEqual(code,200,raw)
        code,raw,_=self.request('/api/customer-statement?customer_id=C001&date=2026-10-18');self.assertEqual(code,200);draft=json.loads(raw)
        body={'request_key':'test-statement-issue-001','customer_id':'C001','business_date':'2026-10-18','seller_name':'测试工厂','seller_phone':'123','buyer_name':'测试客户','operator':'测试经办人','identity_checked':True,'source_fingerprint':draft['source_fingerprint']}
        code,raw,_=self.request('/api/statements/issue',body,'warehouse');self.assertEqual(code,400)
        code,raw,_=self.request('/api/statements/issue',body,'cashier');self.assertEqual(code,200,raw);issued=json.loads(raw);self.assertEqual(issued['document_state'],'待客户确认')
        code,raw,_=self.request('/api/statement-documents/'+issued['document_id']);self.assertEqual(code,200);self.assertEqual(json.loads(raw),issued)
        code,raw,_=self.request('/api/statement-documents?customer_id=C001');self.assertEqual(code,200);self.assertEqual(json.loads(raw)[0]['id'],issued['document_id'])

    def test_customer_statement_read_endpoint(self):
        code,raw,_=self.request('/api/customer-statement?customer_id=C001&date=2026-10-19');self.assertEqual(code,200,raw);s=json.loads(raw);self.assertEqual(s['customer']['id'],'C001');self.assertIn('history',s);self.assertIn('payable_cents',s['totals'])
        code,raw,_=self.request('/api/customer-statement?customer_id=missing&date=2026-10-19');self.assertEqual(code,403)

    def test_catalog_and_server_authorization_do_not_depend_on_menu_visibility(self):
        code,raw,_=self.request('/api/bootstrap');self.assertEqual(code,200)
        catalog=json.loads(raw)['access_catalog'];self.assertEqual(len(catalog['groups']),11);self.assertIn({'id':'hr','title':'人力资源'},catalog['groups'])
        for path,body,role in [('/api/warehouse',{'stage':'confirm_dispatch'},'cashier'),('/api/returns/action',{'action':'review'},'warehouse'),('/api/master',{'kind':'product'},'warehouse'),('/api/trial-data',{'action':'archive'},'cashier')]:
            code,raw,_=self.request(path,body,role);self.assertEqual(code,400,raw)
            self.assertIn('权限',json.loads(raw)['error'])
        code,raw,_=self.request('/api/batch',{'operations':[{'action':'order','body':{}},{'action':'settle','body':{}}]},'warehouse')
        self.assertEqual(code,400);self.assertIn('权限',json.loads(raw)['error'])

    def test_browser_ascii_role_header_full_workflow(self):
        order={'customer_id':'C001','business_date':'2026-10-18','batch':'HTTP验证','note':'虚构测试',
               'lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'2','price':'75','driver':[],'customer':[]}]}
        code,raw,_=self.request('/api/orders',order,role='warehouse');self.assertEqual(code,200,raw);o=json.loads(raw)
        for action,role,extra in [('settle','accountant',{'mode':'customer'}),('review','cashier',{'evidence_checked':True}),('receipt','cashier',{'amount':'150','received_date':'2026-10-18','method':'测试到账'})]:
            code,raw,_=self.request('/api/orders/'+o['id']+'/'+action,{'version':o['version'],**extra},role)
            self.assertEqual(code,200,raw);o=json.loads(raw)
        self.assertEqual(o['status'],'已收清');self.assertEqual(o['total_cents'],15000)
    def test_warehouse_allocation_http_keeps_order_quantities_separate(self):
        # Only the case's own orders participate, including when today is its business date.
        with erp.connect(True) as c:
            c.execute('DELETE FROM receipts');c.execute('DELETE FROM orders')
        order={'customer_id':'C001','business_date':'2026-10-21','batch':'分配验证','lines':[{'product_id':'P004','ordered_qty':'8','actual_qty':'0','price':'75','driver':[],'customer':[]}]}
        code,raw,_=self.request('/api/orders',order,role='warehouse');self.assertEqual(code,200);o=json.loads(raw)
        body={'business_date':'2026-10-21','version':0,'order_versions':{o['id']:o['version']},'stock':[{'product_id':'P004','existing_qty':'4','produced_qty':'2'}],'allocations':[{'order_id':o['id'],'product_id':'P004','qty':'6','ordered_qty':'8'}]}
        code,raw,_=self.request('/api/warehouse',body,role='cashier');self.assertEqual(code,400)
        code,raw,_=self.request('/api/warehouse',body,role='warehouse');self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['allocations'][0]['qty'],'6')
        code,raw,_=self.request('/api/bootstrap');d=json.loads(raw);saved=next(x for x in d['orders'] if x['id']==o['id'])
        self.assertEqual((saved['lines'][0]['ordered_qty'],saved['lines'][0]['actual_qty']),('8','0'))
    def test_batch_endpoint_preserves_customer_multi_product_order(self):
        body={'customer_id':'C001','business_date':'2026-10-18','batch':'整表录入','lines':[{'product_id':pid,'ordered_qty':'2','actual_qty':'0','price':'75','driver':[],'customer':[]} for pid in ['P004','P005']]}
        code,raw,_=self.request('/api/batch',{'operations':[{'action':'order','body':body}]},role='warehouse')
        self.assertEqual(code,200,raw);result=json.loads(raw);self.assertEqual(result['count'],1);self.assertEqual(len(result['orders'][0]['lines']),2)
    def test_http_validation_includes_customer_product_and_field(self):
        order={'customer_id':'C001','business_date':'2026-10-19','batch':'错误定位','lines':[{'product_id':'P004','ordered_qty':'1','actual_qty':'0','price':'0','driver':[],'customer':[]}]}
        code,raw,_=self.request('/api/batch',{'operations':[{'action':'order','body':order}]},role='warehouse')
        self.assertEqual(code,400);issues=json.loads(raw)['issues'];self.assertEqual(issues[0]['customer_id'],'C001');self.assertEqual(issues[0]['product_id'],'P004');self.assertEqual(issues[0]['field'],'price')
    def test_http_product_and_price_matrix_endpoints(self):
        code,raw,_=self.request('/api/master',{'kind':'product','create':True,'id':'P007','name':'试验产品','unit':'筐','price':'4.2','tare':'1.6'})
        self.assertEqual(code,200,raw)
        rules=[{'customer_id':cid,'product_id':'P007','price':'4.5','tare':'1.5','expected':None} for cid in ['C001','C002']]
        code,raw,_=self.request('/api/master/batch-rules',{'rules':rules});self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['count'],2)
        code,raw,_=self.request('/api/bootstrap');self.assertEqual(json.loads(raw)['api_version'],3)
    def test_new_customer_auto_number_http(self):
        code,raw,_=self.request('/api/master',{'kind':'customer','create':True,'name':'自动编号客户','route':'新联市场'})
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['id'],'C004')
        code,raw,_=self.request('/api/bootstrap');d=json.loads(raw)
        self.assertEqual(d['next_customer_id'],'C005')
        self.assertEqual(next(c['name'] for c in d['customers'] if c['id']=='C004'),'自动编号客户')
    def test_dispatch_plan_http(self):
        body={'business_date':'2026-10-19','version':0,'trips':[{'id':'T1','name':'昌吉下午','period':'下午','vehicle_id':'V001','driver':'测试司机'}],
              'assignments':[{'market_id':'M004','trip_id':'T1','sequence':1}]}
        code,raw,_=self.request('/api/dispatch',body,role='warehouse');self.assertEqual(code,200,raw)
        self.assertEqual(json.loads(raw)['version'],1)
        code,raw,_=self.request('/api/dispatch',body,role='warehouse');self.assertEqual(code,400,raw)
        code,raw,_=self.request('/api/bootstrap');self.assertEqual(len(json.loads(raw)['dispatch_plans']),1)
    def test_product_display_order_endpoint(self):
        code,raw,_=self.request('/api/bootstrap');ids=[p['id'] for p in json.loads(raw)['products']]
        code,raw,_=self.request('/api/master/product-order',{'product_ids':ids[::-1],'expected':ids});self.assertEqual(code,200,raw)
        code,raw,_=self.request('/api/bootstrap');self.assertEqual([p['id'] for p in json.loads(raw)['products']],ids[::-1])
        code,raw,_=self.request('/api/master/product-order',{'product_ids':ids,'expected':ids});self.assertEqual(code,400,raw)
    def test_pickup_customer_order_settles_without_driver_weighing(self):
        code,raw,_=self.request('/api/master',{'kind':'customer','create':True,'name':'自取客户','route':'五彩湾','delivery_method':'pickup'})
        self.assertEqual(code,200,raw);cid=json.loads(raw)['id']
        body={'customer_id':cid,'business_date':'2026-10-19','batch':'自提验证','lines':[{'product_id':'P001','ordered_qty':'2','actual_qty':'2','price':'3.6','driver':[],'customer':[{'gross':'23.6','count':'2','tare':'1.8'}]}]}
        code,raw,_=self.request('/api/orders',body,role='warehouse');self.assertEqual(code,200,raw);o=json.loads(raw)
        self.assertEqual(o['delivery_method'],'pickup')
        code,raw,_=self.request('/api/orders/'+o['id']+'/settle',{'version':o['version'],'mode':'customer'});self.assertEqual(code,200,raw)
        self.assertEqual(json.loads(raw)['total_cents'],7200)
    def test_fleet_and_warehouse_print_endpoints(self):
        code,raw,_=self.request('/api/fleet',{'kind':'driver','action':'create','name':'网页司机'},role='warehouse')
        self.assertEqual(code,200,raw);driver=json.loads(raw)
        code,raw,_=self.request('/api/fleet',{'kind':'driver','action':'delete','id':driver['id'],'expected':{'name':driver['name'],'active':1}},role='warehouse')
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['active'],0)
        code,raw,h=self.request('/print/orders?date=2026-10-19&mode=grouped')
        self.assertEqual(code,200,raw);self.assertIn('text/html',h['Content-Type']);self.assertIn('客户 × 产品数量总表',raw.decode())
    def test_export_date_range_matches_selected_business_dates(self):
        for day in ['2026-09-30','2026-10-01']:
            code,raw,_=self.request('/api/orders',{'customer_id':'C001','business_date':day,'batch':'范围导出验证','lines':[{'product_id':'P004','ordered_qty':'1','actual_qty':'0','price':'75','driver':[],'customer':[]}]},role='warehouse')
            self.assertEqual(code,200,raw)
        code,raw,_=self.request('/api/export?start=2026-10-01&end=2026-10-31&basis=business_date')
        self.assertEqual(code,200,raw);text=raw.decode('utf-8-sig');self.assertIn('2026-10-01',text);self.assertNotIn('2026-09-30',text)
    def test_cross_origin_and_missing_client_blocked(self):
        self.assertEqual(self.request('/api/orders',{},origin='https://example.com')[0],400)
        self.assertEqual(self.request('/api/orders',{},client='')[0],400)
    def test_database_backup_is_valid(self):
        code,raw,_=self.request('/api/backup',{});self.assertEqual(code,200,raw)
        p=Path(json.loads(raw)['path']);self.assertTrue(p.exists())
        with sqlite3.connect(p) as c:self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_csv_preserves_unicode_and_blocks_formula_injection(self):
        code,raw,_=self.request('/api/master',{'kind':'customer','id':'C004','name':'=FORMULA','route':'+线路','note':''});self.assertEqual(code,200,raw)
        order={'customer_id':'C004','business_date':'2026-10-18','batch':'测试','lines':[{'product_id':'P004','ordered_qty':'1','actual_qty':'0','price':'75','driver':[],'customer':[]}]}
        self.assertEqual(self.request('/api/orders',order,role='warehouse')[0],200)
        code,raw,h=self.request('/api/export');self.assertEqual(code,200)
        text=raw.decode('utf-8-sig');self.assertIn("'=FORMULA",text);self.assertIn("'+线路",text)
        self.assertIn('attachment',h['Content-Disposition'])


    def test_returns_inventory_http_link_and_financial_concurrency(self):
        body={'received_date':'2026-10-21','customer_id':'C001','product_id':'P001','qty':'1','net_kg':'10','condition':'spoiled','reason':'变质退货测试','source_note':'原单未找到','request_key':'http-test-return','received_checked':True}
        code,raw,_=self.request('/api/returns',body,'warehouse');self.assertEqual(code,200,raw);r=json.loads(raw)['record']
        code,raw,_=self.request('/api/inventory?date=2026-10-21');self.assertEqual(code,200,raw);p=json.loads(raw)['products'][0];self.assertEqual(p['quarantine_kg'],'10');self.assertIsNone(p['supply_qty'])
        account={'id':r['id'],'version':r['version'],'action':'account','account_date':'2026-10-21','account_qty':'9','price':'3.333','price_checked':True,'note':'原手机历史销售价核定'}
        code,raw,_=self.request('/api/returns/action',account,'warehouse');self.assertEqual(code,400)
        code,raw,_=self.request('/api/returns/action',account,'accountant');self.assertEqual(code,200,raw);r=json.loads(raw)['record'];self.assertEqual(r['finance']['amount_cents'],3000)
        code,raw,_=self.request('/api/returns/action',account,'accountant');self.assertEqual(code,400)
        code,raw,_=self.request('/api/returns/action',{'id':r['id'],'version':r['version'],'action':'review','evidence_checked':True},'cashier');self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['record']['finance']['state'],'posted')
        code,raw,_=self.request('/api/processing',{'business_date':'2026-10-21','product_id':'P001','origin':'customer_return'},'warehouse');self.assertEqual(code,400)


    def test_explicit_weight_handoff_http_routes(self):
        body={'workflow_version':1,'customer_id':'C001','business_date':'2026-10-22','batch':'交接HTTP测试','lines':[{'product_id':'P004','ordered_qty':'2','actual_qty':'2','price':'75','driver':[],'customer':[]}]}
        code,raw,_=self.request('/api/orders',body,'warehouse');self.assertEqual(code,200,raw);o=json.loads(raw);self.assertEqual(o['status'],'待确认称重')
        code,raw,_=self.request('/api/orders/'+o['id']+'/settle',{'version':o['version'],'mode':'driver'},'accountant');self.assertEqual(code,400)
        code,raw,_=self.request('/api/orders/'+o['id']+'/confirm-weight',{'version':o['version'],'evidence_checked':True},'warehouse');self.assertEqual(code,200,raw);o=json.loads(raw);self.assertEqual(o['status'],'待算票')
        code,raw,_=self.request('/api/orders/'+o['id']+'/settle',{'version':o['version'],'mode':'driver'},'accountant');self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['state'],'ready')

if __name__=='__main__':unittest.main(verbosity=2)
