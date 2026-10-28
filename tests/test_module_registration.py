"""Guard the module boundaries that used to silently omit new entry points."""
import ast
import json
import re
import unittest
from pathlib import Path
import erp_access
from ops.build_release import release_files

ROOT = Path(__file__).resolve().parents[1]


class ModuleRegistrationTests(unittest.TestCase):
    def test_every_browser_entry_is_served_and_packaged(self):
        html = (ROOT / 'web/index.html').read_text()
        tree = ast.parse((ROOT / 'server.py').read_text())
        files = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'files' for t in n.targets) and isinstance(n.value, ast.Dict))
        package = {str(p) for p in release_files()}
        for url in re.findall(r'<script src="([^"]+)"', html):
            self.assertIn(url, files, '新脚本遗漏HTTP静态入口')
            self.assertIn('web/' + files[url], package, '新脚本遗漏发布包')

    def test_bookmark_assets_are_served_and_packaged(self):
        html = (ROOT / 'web/index.html').read_text()
        tree = ast.parse((ROOT / 'server.py').read_text())
        files = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'files' for t in n.targets) and isinstance(n.value, ast.Dict))
        package = {str(p) for p in release_files()}
        linked = [href.split('?')[0] for href in re.findall(r'<link[^>]+href="([^"]+)"', html)
                  if Path(href.split('?')[0]).suffix in ('.ico', '.svg', '.png', '.webmanifest')]
        self.assertIn('/favicon.ico', linked)
        self.assertIn('/apple-touch-icon.png', linked)
        self.assertIn('/site.webmanifest', linked)
        for url in linked:
            self.assertIn(url, files, '新图标遗漏HTTP静态入口')
            self.assertIn('web/' + files[url], package, '新图标遗漏发布包')
        manifest = json.loads((ROOT / 'web/site.webmanifest').read_text())
        self.assertEqual(manifest['name'], '洋帆豆制品厂 ERP 系统')
        self.assertEqual(manifest['start_url'], '/')
        self.assertEqual(manifest['display'], 'browser')
        self.assertEqual({icon['sizes'] for icon in manifest['icons']}, {'192x192', '512x512'})
        for icon in manifest['icons']:
            url = icon['src'].split('?')[0]
            self.assertIn(url, files, 'manifest 图标遗漏HTTP静态入口')
            self.assertIn('web/' + files[url], package, 'manifest 图标遗漏发布包')
            self.assertEqual(icon['type'], 'image/png')

    def test_every_local_backend_import_is_packaged(self):
        package = {str(p) for p in release_files()}
        for name in list(package):
            if not name.endswith('.py'): continue
            for node in ast.walk(ast.parse((ROOT / name).read_text())):
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
                for module in modules:
                    path = (module or '').split('.')[0] + '.py'
                    if (ROOT / path).is_file(): self.assertIn(path, package, name + ' 引用了未打包模块')

    def test_every_permission_page_has_renderer(self):
        source = (ROOT / 'web/app.js').read_text()
        renderers = source[source.index("+({'system-settings':"):source.index('[page])();')]
        keys = {a or b for a, b in re.findall(r"(?:'([^']+)'|\b([A-Za-z][\w]*))\s*:", renderers)}
        keys.update(re.findall(r'(?:[,{])\s*([A-Za-z_]\w*)\s*(?=,|})',renderers))
        for m in erp_access.module_definitions():
            self.assertIn(m['page'], keys, m['id'] + ' 缺少页面渲染入口')

    def test_parameter_dialogs_have_explicit_leave_policies(self):
        source = (ROOT / 'web/navigation.js').read_text()
        for form in ('parameter-request-form', 'parameter-review-form', 'production-config-form'):
            self.assertIn(form, source)
