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
        for path in ('/app.js','/style.css'):
            status,cache,body=self.fetch(path+'?v='+erp.APP_VERSION)
            self.assertEqual(status,200,path)
            self.assertEqual(cache,IMMUTABLE,path)
            self.assertTrue(body,path)
    def test_index_links_assets_with_current_version(self):
        status,cache,body=self.fetch('/')
        self.assertEqual(status,200)
        self.assertEqual(cache,'no-store')
        text=body.decode('utf-8')
        for name in ('app.js','style.css'):
            self.assertIn('/'+name+'?v='+erp.APP_VERSION,text)
    def test_unversioned_or_stale_assets_stay_uncached(self):
        for path in ('/app.js','/style.css','/app.js?v='+erp.APP_VERSION+'-old','/print.css',
                     '/','/api/health'):
            status,cache,_=self.fetch(path)
            self.assertEqual(cache,'no-store',path)
    def test_api_responses_stay_uncached(self):
        status,cache,_=self.fetch('/api/bootstrap')
        self.assertIn(status,(200,401,403))
        self.assertEqual(cache,'no-store')

if __name__=='__main__':unittest.main()
