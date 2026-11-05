"""静态资源缓存策略：只有带当前版本号的 JS/CSS 允许长缓存，页面与接口保持不缓存。"""
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

spec=importlib.util.spec_from_file_location('erp',Path(__file__).resolve().parents[1]/'server.py')
erp=importlib.util.module_from_spec(spec);spec.loader.exec_module(erp)

IMMUTABLE='public, max-age=31536000, immutable'

class CacheHeaderTests(unittest.TestCase):
    def setUp(self):
        self.previous_db=erp.DB
        self.tmp=tempfile.TemporaryDirectory()
        erp.DB=Path(self.tmp.name)/'cache.db'
        erp.init_db()
        self.server=erp.ThreadingHTTPServer(('127.0.0.1',0),erp.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        erp.DB=self.previous_db;self.tmp.cleanup()
    def fetch(self,path):
        try:response=urllib.request.urlopen(self.base+path,timeout=15)
        except urllib.error.HTTPError as error:response=error
        with response:
            return response.status,response.headers.get('Cache-Control',''),response.read()
    def test_versioned_scripts_and_styles_are_immutable(self):
        for path in ('/app.js','/style.css','/charts.css'):
            status,cache,body=self.fetch(path+'?v='+erp.APP_VERSION)
            self.assertEqual(status,200,path)
            self.assertEqual(cache,IMMUTABLE,path)
            self.assertTrue(body,path)
    def test_versioned_icons_and_manifest_are_immutable(self):
        for path in ('/favicon.ico','/favicon.svg','/favicon-16x16.png','/apple-touch-icon.png',
                     '/site.webmanifest'):
            status,cache,body=self.fetch(path+'?v='+erp.APP_VERSION)
            self.assertEqual(status,200,path)
            self.assertEqual(cache,IMMUTABLE,path)
            self.assertTrue(body,path)
    def test_index_links_assets_with_current_version(self):
        status,cache,body=self.fetch('/')
        self.assertEqual(status,200)
        self.assertEqual(cache,'no-store')
        text=body.decode('utf-8')
        for name in ('favicon.ico','favicon.svg','apple-touch-icon.png','site.webmanifest'):
            self.assertIn('/'+name+'?v='+erp.APP_VERSION,text)
        self.assertNotIn('?v=0.54.3',text)
    def test_unversioned_or_stale_assets_stay_uncached(self):
        for path in ('/app.js','/style.css','/app.js?v='+erp.APP_VERSION+'-old','/print.css',
                     '/favicon.svg','/site.webmanifest','/',
                     '/api/health'):
            status,cache,_=self.fetch(path)
            self.assertEqual(cache,'no-store',path)
    def test_index_serves_single_bundle(self):
        status,_,body=self.fetch('/')
        text=body.decode('utf-8')
        self.assertEqual(status,200)
        self.assertEqual(text.count('<script src="/bundle.js?v='+erp.APP_VERSION+'"'),1)
        self.assertEqual(text.count('<link rel="stylesheet" href="/bundle.css?v='+erp.APP_VERSION+'">'),1)
        self.assertIn('/bundle.js?v='+erp.APP_VERSION,text)
        self.assertNotIn('/forms.js?v=',text)
        self.assertNotIn('/style.css?v=',text)
    def test_bundles_follow_index_order(self):
        status,cache,body=self.fetch('/bundle.js?v='+erp.APP_VERSION)
        self.assertEqual((status,cache),(200,IMMUTABLE))
        text=body.decode('utf-8')
        self.assertTrue(text.startswith('/* forms.js */'),text[:40])
        self.assertIn('/* app.js */',text)
        self.assertIn('/* receipt-evidence.js */',text)
        status,cache,body=self.fetch('/bundle.css?v='+erp.APP_VERSION)
        self.assertEqual((status,cache),(200,IMMUTABLE))
        text=body.decode('utf-8')
        self.assertIn('/* style.css */',text)
        self.assertIn('/* charts.css */',text)
    def test_bundles_without_current_version_stay_uncached(self):
        for path in ('/bundle.js','/bundle.css','/bundle.js?v='+erp.APP_VERSION+'-old'):
            status,cache,body=self.fetch(path)
            self.assertEqual(status,200,path)
            self.assertEqual(cache,'no-store',path)
            self.assertTrue(body,path)
    def test_service_worker_is_served_and_versioned(self):
        status,cache,body=self.fetch('/sw.js?v='+erp.APP_VERSION)
        self.assertEqual((status,cache),(200,IMMUTABLE))
        text=body.decode('utf-8')
        self.assertIn("const CACHE = 'erp-shell-' + VERSION",text)
        self.assertIn("url.pathname.startsWith('/api/')",text)
        self.assertIn("request.mode === 'navigate'",text)
        status,cache,_=self.fetch('/sw.js')
        self.assertEqual((status,cache),(200,'no-store'))
    def test_bundle_registers_versioned_service_worker(self):
        status,_,body=self.fetch('/bundle.js?v='+erp.APP_VERSION)
        self.assertEqual(status,200)
        text=body.decode('utf-8')
        self.assertIn("navigator.serviceWorker.register('/sw.js?v='",text)
        self.assertIn('script[src^="/bundle.js?v="]',text)
        _,_,page=self.fetch('/')
        self.assertNotIn('serviceWorker',page.decode('utf-8'))

    def test_api_responses_stay_uncached(self):
        status,cache,_=self.fetch('/api/bootstrap')
        self.assertIn(status,(200,401,403))
        self.assertEqual(cache,'no-store')

if __name__=='__main__':unittest.main()
