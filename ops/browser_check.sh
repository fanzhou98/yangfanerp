#!/bin/bash
# 浏览器回归：按需把 Playwright 装到 /tmp，用本机 Chrome 跑浏览器脚本。
# --quick 只跑当前版本维护的 tests/browser_smoke.js；--all 连历史 browser_*.js 一起跑（旧脚本绑定当年业务规则，可能已过时）。
# 用法：bash ops/browser_check.sh [--quick|--all|--list|--inventory|<脚本名…>]
#   --quick      只跑 tests/browser_smoke.js（当前维护的冒烟，作为发版依据）
#   --all        维护脚本 + tests/legacy_browser/ 历史脚本
#   --inventory  并行盘点 tests/legacy_browser/ 历史脚本通过率，明细写 /tmp/erp-browser-inventory-*.json
# 没有 Playwright / Chrome / 网络时明确跳过（退出 0），由 ops/release_gate.sh 记录为跳过项。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${ERP_PLAYWRIGHT_DIR:-/tmp/erp-playwright}"
MODE="${1:---quick}"
export ERP_PYTHON="${ERP_PYTHON:-python3}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/pyc-browser}"

if [ "$MODE" = "--list" ]; then
  ls "$ROOT"/tests/browser_*.js
  ls "$ROOT"/tests/legacy_browser/browser_*.js 2>/dev/null
  exit 0
fi

if [ -z "${ERP_PLAYWRIGHT_MODULE:-}" ]; then
  # 目录存在不等于安装完整：中断的 npm install 会留下空目录。
  if [ ! -f "$DIR/node_modules/playwright-core/package.json" ] && [ ! -f "$DIR/node_modules/playwright/package.json" ]; then
    rm -rf "$DIR/node_modules/playwright-core" "$DIR/node_modules/playwright"
    mkdir -p "$DIR"
    (cd "$DIR" && npm_config_cache=/tmp/npm-cache npm install --silent --no-audit --no-fund playwright-core >/dev/null 2>&1) || true
  fi
  if [ -f "$DIR/node_modules/playwright-core/package.json" ]; then
    export ERP_PLAYWRIGHT_MODULE="$DIR/node_modules/playwright-core"
  elif [ -f "$DIR/node_modules/playwright/package.json" ]; then
    export ERP_PLAYWRIGHT_MODULE="$DIR/node_modules/playwright"
  fi
fi
if [ -z "${ERP_PLAYWRIGHT_MODULE:-}" ]; then
  echo "skip: 未安装 Playwright（联网后自动安装，或设置 ERP_PLAYWRIGHT_MODULE 指向 playwright-core）"
  exit 0
fi
if [ ! -d "/Applications/Google Chrome.app" ] && ! command -v google-chrome >/dev/null 2>&1; then
  echo "skip: 未找到 Chrome，浏览器回归不执行"
  exit 0
fi

QUICK="browser_smoke.js"
ALL="$( (ls "$ROOT"/tests/browser_*.js; ls "$ROOT"/tests/legacy_browser/browser_*.js 2>/dev/null) | xargs -n1 basename)"

if [ "$MODE" = "--inventory" ]; then
  "$ERP_PYTHON" - "$ROOT" <<'PY'
import concurrent.futures as cf, json, os, subprocess, sys, time
root = sys.argv[1]
folder = os.path.join(root, 'tests', 'legacy_browser')
names = sorted(n for n in os.listdir(folder) if n.startswith('browser_') and n.endswith('.js'))
out = os.environ.get('ERP_INVENTORY_OUT') or '/tmp/erp-browser-inventory-%s.json' % time.strftime('%Y%m%d-%H%M%S')
env = dict(os.environ)

def run(name):
    t0 = time.time()
    try:
        done = subprocess.run(['node', os.path.join(folder, name)], capture_output=True, text=True,
                              timeout=int(env.get('ERP_BROWSER_TIMEOUT', '420')), env=env, cwd=root)
        tail = [l for l in (done.stdout + done.stderr).strip().splitlines() if l.strip()][-1:] or ['']
        return {'script': name, 'ok': done.returncode == 0, 'secs': round(time.time() - t0, 1), 'tail': tail[0][:200]}
    except subprocess.TimeoutExpired:
        return {'script': name, 'ok': False, 'secs': round(time.time() - t0, 1), 'tail': 'TIMEOUT'}

with cf.ThreadPoolExecutor(max_workers=int(env.get('ERP_BROWSER_JOBS', '2'))) as pool:
    results = list(pool.map(run, names))
ok = [r for r in results if r['ok']]
json.dump(results, open(out, 'w'), ensure_ascii=False, indent=1)
print('历史浏览器脚本盘点: %d/%d 通过' % (len(ok), len(results)))
for r in ok:
    print('  ok   %s (%ss)' % (r['script'], r['secs']))
print('明细: %s' % out)
PY
  exit $?
fi

case "$MODE" in
  --quick) scripts="$QUICK" ;;
  --all) scripts="$ALL" ;;
  *) scripts="$*" ;;
esac
if [ -z "$scripts" ]; then echo "skip: 没有匹配的浏览器脚本"; exit 0; fi

fail=0
total=0
for name in $scripts; do
  path="$ROOT/tests/$name"
  if [ ! -f "$path" ]; then echo "skip: 找不到 $name"; continue; fi
  total=$((total + 1))
  if "$ERP_PYTHON" - "$path" <<'PY'
import os, subprocess, sys
script = sys.argv[1]
env = dict(os.environ)
try:
    done = subprocess.run(['node', script], capture_output=True, text=True, timeout=int(env.get('ERP_BROWSER_TIMEOUT', '600')))
except subprocess.TimeoutExpired:
    print('TIMEOUT', os.path.basename(script))
    raise SystemExit(124)
tail = (done.stdout or '').strip().splitlines()[-3:] + (done.stderr or '').strip().splitlines()[-6:]
for line in tail:
    print('  ' + line[:300])
raise SystemExit(done.returncode)
PY
  then
    echo "ok   浏览器 $name"
  else
    echo "FAIL 浏览器 $name（日志 /tmp/erp-browser-$(echo "$name" | tr -c 'a-z0-9\n' '-').log）"
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "结果: 浏览器回归失败"
  exit 1
fi
echo "结果: 浏览器回归通过（$total 个脚本）"
