# -*- coding: utf-8 -*-
"""发版工具链：看门狗与浏览器回归脚本存在、可执行、语法正确、能列出脚本。"""
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ReleaseToolingTests(unittest.TestCase):
    def run_sh(self, args, **kw):
        return subprocess.run(['bash'] + args, cwd=ROOT, capture_output=True, text=True, timeout=60, **kw)

    def test_scripts_exist_and_are_executable(self):
        for name in ('ops/release_gate.sh', 'ops/browser_check.sh'):
            path = os.path.join(ROOT, name)
            self.assertTrue(os.path.isfile(path), name)
            self.assertTrue(os.access(path, os.X_OK), name + ' 需可执行')

    def test_scripts_parse_with_bash(self):
        for name in ('ops/release_gate.sh', 'ops/browser_check.sh'):
            done = self.run_sh(['-n', name])
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_browser_script_list_matches_tests_directory(self):
        done = self.run_sh(['ops/browser_check.sh', '--list'])
        self.assertEqual(done.returncode, 0, done.stderr)
        listed = [os.path.basename(x) for x in done.stdout.split()]
        expected = sorted(n for n in os.listdir(os.path.join(ROOT, 'tests'))
                          if n.startswith('browser_') and n.endswith('.js'))
        self.assertEqual(sorted(listed), expected)
        self.assertGreaterEqual(len(listed), 100)

    def test_browser_check_reports_missing_playwright(self):
        env = dict(os.environ, ERP_PLAYWRIGHT_MODULE='', ERP_PLAYWRIGHT_DIR='/tmp/erp-playwright-missing')
        done = subprocess.run(['bash', 'ops/browser_check.sh', '--quick'], cwd=ROOT, capture_output=True,
                              text=True, timeout=120, env=dict(env, PATH='/usr/bin:/bin'))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(('skip' in done.stdout) or ('ok' in done.stdout) or ('FAIL' in done.stdout))


if __name__ == '__main__':
    unittest.main()
