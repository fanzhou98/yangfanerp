#!/usr/bin/env python3
"""Repeatable release checks; does not start the real service or write the real DB."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SIZE_LIMIT = 160_000  # 2026-11-02：导入 83 户历史客户后本机实测 141,439B，预留增长余量
FAIL_PATTERN = re.compile(r'^(?:FAIL|ERROR): (\S+) \(([^)]+)\)', re.M)
# Keep the desktop responsive; higher concurrency is an explicit opt-in.
DEFAULT_JOBS = max(1, min(2, __import__('os').cpu_count() or 2))


def parse_failures(text):
    """Only test ids are kept: assertion text may contain customer data."""
    found = set()
    for test, group in FAIL_PATTERN.findall(text or ''):
        found.add(group if group.endswith('.' + test) else group + '.' + test)
    return sorted(found)


def test_env():
    env = dict(os.environ)
    env.setdefault('PYTHONPYCACHEPREFIX', str(Path(tempfile.gettempdir()) / 'erp-verify-pyc'))
    return env


def python_test_command(pattern=None):
    command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']
    if pattern:
        command += ['-p', pattern]
    return command


def run_serial(start):
    try:
        result = subprocess.run(python_test_command(), cwd=ROOT, capture_output=True, text=True,
                                timeout=600, env=test_env())
        ok = result.returncode == 0
        row = {'check': 'python-tests', 'ok': ok, 'elapsed_ms': round((time.monotonic() - start) * 1000), 'jobs': 1}
        if not ok:
            row['failed_cases'] = parse_failures(result.stdout + result.stderr)
        return row
    except subprocess.TimeoutExpired:
        return {'check': 'python-tests', 'ok': False, 'elapsed_ms': round((time.monotonic() - start) * 1000),
                'jobs': 1, 'failed_cases': ['<timeout>']}


def run_module(module):
    started = time.monotonic()
    try:
        result = subprocess.run(python_test_command(module), cwd=ROOT, capture_output=True, text=True,
                                timeout=300, env=test_env())
        return {'module': module, 'ok': result.returncode == 0, 'seconds': round(time.monotonic() - started, 1),
                'failed': [] if result.returncode == 0 else parse_failures(result.stdout + result.stderr)}
    except subprocess.TimeoutExpired:
        return {'module': module, 'ok': False, 'seconds': round(time.monotonic() - started, 1), 'failed': [module + ':<timeout>']}
    except OSError as exc:
        return {'module': module, 'ok': False, 'seconds': round(time.monotonic() - started, 1), 'failed': [module + ':' + str(exc)]}


def run_parallel(start, jobs):
    modules = sorted(path.name for path in (ROOT / 'tests').glob('test_*.py'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        rows = list(pool.map(run_module, modules))
    failed = sorted({case for row in rows for case in row['failed']})
    slowest = sorted(({'module': row['module'], 'seconds': row['seconds']} for row in rows), key=lambda item: -item['seconds'])[:5]
    return {'check': 'python-tests', 'ok': all(row['ok'] for row in rows),
            'elapsed_ms': round((time.monotonic() - start) * 1000), 'jobs': jobs, 'modules': len(modules),
            'slowest': slowest, 'failed_cases': failed}


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
            server.init_db(demo=False)
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


def inline_style_check():
    """CSP 守卫：web/*.js、web/*.html 里不允许出现 style 属性（会被 style-src self 丢弃）。"""
    script = ROOT / 'ops' / 'check_inline_style.py'
    start = time.monotonic()
    try:
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True, timeout=60)
        passed = result.returncode == 0
        detail = (result.stdout or result.stderr).strip().splitlines()
    except (OSError, subprocess.TimeoutExpired) as exc:
        passed, detail = False, [f'{exc}']
    row = {'check': 'style:inline', 'ok': passed, 'elapsed_ms': round((time.monotonic() - start) * 1000)}
    if not passed and detail:
        row['detail'] = detail[:6]
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-only', action='store_true', help='explicitly skip JS checks when Node is unavailable')
    parser.add_argument('--skip-volume', action='store_true', help='skip the optional read-only bootstrap volume check against local data/erp.db')
    parser.add_argument('--jobs', type=int, default=DEFAULT_JOBS, help='run python test modules in N parallel processes (default %(default)s)')
    args = parser.parse_args()
    jobs = max(1, min(args.jobs, 16))
    results = []
    started = time.monotonic()
    results.append(inline_style_check())
    row = run_serial(started) if jobs == 1 else run_parallel(started, jobs)
    results.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
    if row.get('failed_cases'):
        print(json.dumps({'failed_cases': row['failed_cases']}, ensure_ascii=False), flush=True)
    if not args.python_only:
        node = shutil.which('node')
        if not node:
            print(json.dumps({'ok': False, 'error': '缺少 Node；安装测试运行时后重试，或明确使用 --python-only'}, ensure_ascii=False))
            return 1
        checks = [('syntax:' + file.name, [node, '--check', str(file)]) for file in sorted((ROOT / 'web').glob('*.js'))]
        checks += [('logic:' + file.name, [node, str(file)]) for file in sorted((ROOT / 'tests').glob('test_*.cjs'))]
        for name, command in checks:
            start = time.monotonic()
            try:
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
                passed = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                passed = False
            results.append({'check': name, 'ok': passed, 'elapsed_ms': round((time.monotonic() - start) * 1000)})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    # 可选：登录态 bootstrap 体积上限，只读复制 data/erp.db，缺库时跳过。
    volume_ok = True if args.skip_volume else bootstrap_volume_check()
    ok = all(row['ok'] for row in results) and volume_ok
    print(json.dumps({'ok': ok, 'checks': len(results), 'jobs': jobs, 'python_only': args.python_only,
                      'browser_tests': '需另按上线清单运行；不会自动安装或下载浏览器'}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
