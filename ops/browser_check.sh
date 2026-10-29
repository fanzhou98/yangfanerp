#!/bin/bash
# 浏览器回归：按需把 Playwright 装到 /tmp，用本机 Chrome 跑浏览器脚本。
# --quick 只跑当前版本维护的 tests/browser_smoke.js；--all 连历史 browser_*.js 一起跑（旧脚本绑定当年业务规则，可能已过时）。
# 用法：bash ops/browser_check.sh [--quick|--all|--list|<脚本名…>]
# 没有 Playwright / Chrome / 网络时明确跳过（退出 0），由 ops/release_gate.sh 记录为跳过项。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${ERP_PLAYWRIGHT_DIR:-/tmp/erp-playwright}"
MODE="${1:---quick}"
export ERP_PYTHON="${ERP_PYTHON:-python3}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/pyc-browser}"

if [ "$MODE" = "--list" ]; then
  ls "$ROOT"/tests/browser_*.js
  exit 0
fi

if [ -z "${ERP_PLAYWRIGHT_MODULE:-}" ]; then
  if [ ! -d "$DIR/node_modules/playwright-core" ] && [ ! -d "$DIR/node_modules/playwright" ]; then
    mkdir -p "$DIR"
    (cd "$DIR" && npm_config_cache=/tmp/npm-cache npm install --silent --no-audit --no-fund playwright-core >/dev/null 2>&1) || true
  fi
  if [ -d "$DIR/node_modules/playwright-core" ]; then
    export ERP_PLAYWRIGHT_MODULE="$DIR/node_modules/playwright-core"
  elif [ -d "$DIR/node_modules/playwright" ]; then
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
ALL="$(ls "$ROOT"/tests/browser_*.js | xargs -n1 basename)"

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
