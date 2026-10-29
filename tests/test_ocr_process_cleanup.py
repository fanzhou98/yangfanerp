"""OCR compiler timeouts must not leave CPU-consuming descendants behind."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import receipt_ocr


class OcrProcessCleanupTests(unittest.TestCase):
    def test_compiler_result_keeps_output_and_return_code(self):
        result = receipt_ocr._run_vision_compiler(
            [sys.executable, '-c', 'import sys;print("ok");sys.stderr.write("bad");sys.exit(2)'])
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, b'ok\n', b'bad'))

    @unittest.skipUnless(os.name == 'posix', 'Vision compilation uses POSIX process groups')
    def test_timeout_kills_compiler_child_process(self):
        with tempfile.TemporaryDirectory(prefix='erp-ocr-cleanup-') as temp:
            pidfile = Path(temp) / 'child.pid'
            code = ('import subprocess,sys,time,pathlib;'
                    'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
                    'pathlib.Path(sys.argv[1]).write_text(str(child.pid));time.sleep(60)')
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    receipt_ocr._run_vision_compiler([sys.executable, '-c', code, str(pidfile)], timeout=1)
                pid = int(pidfile.read_text())
                try:
                    state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True).stdout.strip()
                except (PermissionError, FileNotFoundError):
                    self.skipTest('当前沙箱不允许调用 ps，无法确认子进程状态')
                self.assertTrue(not state or state.startswith('Z'), 'compiler child still running: ' + state)
            finally:
                if pidfile.exists():
                    try:os.kill(int(pidfile.read_text()), 9)
                    except ProcessLookupError:pass
