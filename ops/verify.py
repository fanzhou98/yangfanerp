#!/usr/bin/env python3
"""Repeatable release checks; does not start the real service or write the real DB."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SIZE_LIMIT = 125_000


def bootstrap_volume_check(limit=BOOTSTRAP_SIZE_LIMIT):
    """可选检查：只读复制本机 data/erp.db，实测登录态 bootstrap 体积上限。

    没有本机库时跳过（发布机/CI 常见），不影响其余检查。
    """
    source = ROOT / 'data' / 'erp.db'
    if not source.is_file():
        print(json.dumps({'check': 'volume:bootstrap', 'ok': True, 'skipped': '无本机 data/erp.db'}, ensure_ascii=False), flush=True)
        return True
    workdir = Path(tempfile.mkdtemp(prefix='erp-verify-volume-'))
    frozen = workdir / 'erp.db'
    try:
        with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as src, sqlite3.connect(frozen) as dst:
            src.backup(dst)
        sys.path.insert(0, str(ROOT))
        import server
        previous = server.DB
        server.DB = frozen
        try:
            snapshot = server.bootstrap(include_expense_history=False, include_byproduct_history=False,
                                        factory_light=True, include_audit=False)
        finally:
            server.DB = previous
        size = len(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode('utf-8'))
        ok = size <= limit
        print(json.dumps({'check': 'volume:bootstrap', 'ok': ok, 'bytes': size, 'limit': limit,
                          'db': 'data/erp.db（只读副本）'}, ensure_ascii=False), flush=True)
        return ok
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-only', action='store_true', help='explicitly skip JS checks when Node is unavailable')
    parser.add_argument('--skip-volume', action='store_true', help='skip the optional read-only bootstrap volume check against local data/erp.db')
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
    # 可选：登录态 bootstrap 体积上限，只读复制 data/erp.db，缺库时跳过。
    volume_ok = True if args.skip_volume else bootstrap_volume_check()
    ok = all(row['ok'] for row in results) and volume_ok
    print(json.dumps({'ok': ok, 'checks': len(results), 'python_only': args.python_only,
                      'browser_tests': '需另按上线清单运行；不会自动安装或下载浏览器'}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
