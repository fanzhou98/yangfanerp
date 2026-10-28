#!/usr/bin/env python3
"""Repeatable release checks; does not start the real service or use the real DB."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-only', action='store_true', help='explicitly skip JS checks when Node is unavailable')
    args = parser.parse_args()
    checks = [('python-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])]
    if not args.python_only:
        node = shutil.which('node')
        if not node:
            print(json.dumps({'ok': False, 'error': '缺少 Node；安装测试运行时后重试，或明确使用 --python-only'}, ensure_ascii=False))
            return 1
        checks += [('syntax:' + file.name, [node, '--check', str(file)]) for file in sorted((ROOT / 'web').glob('*.js'))]
        checks += [('logic:' + file.name, [node, str(file)]) for file in sorted((ROOT / 'tests').glob('test_*.cjs'))]
    results = []
    for name, command in checks:
        start = time.monotonic()
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600 if name=='python-tests' else 180)
            passed = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            passed = False
        # Test outputs stay in memory: a failed assertion could contain a secret.
        # Run the named test interactively for diagnosis in an authorized session.
        results.append({'check': name, 'ok': passed, 'elapsed_ms': round((time.monotonic() - start) * 1000)})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    ok = all(row['ok'] for row in results)
    print(json.dumps({'ok': ok, 'checks': len(results), 'python_only': args.python_only,
                      'browser_tests': '需另按上线清单运行；不会自动安装或下载浏览器'}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
