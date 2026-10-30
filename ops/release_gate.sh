#!/bin/bash
# 发版看门狗：全量验证 + 浏览器回归 + 发布包一致性，一条命令给结论。
# 用法：bash ops/release_gate.sh [--no-browser]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/release-gate-$(date +%Y%m%d-%H%M%S).log"
WITH_BROWSER=1
for arg in "$@"; do
  if [ "$arg" = "--no-browser" ]; then WITH_BROWSER=0
  else echo "未知参数: $arg"; exit 2; fi
done
fail=0
run() {
  name="$1"; shift
  if "$@" >>"$LOG" 2>&1; then
    echo "ok   $name"
  else
    echo "FAIL ${name}（日志 ${LOG}）"
    fail=1
  fi
}

echo "== 发版看门狗 =="
echo "日志: $LOG"
run "全量验证（ops/verify.py）" bash "$ROOT/ops/quick_check.sh" --full
if [ "$WITH_BROWSER" -eq 1 ]; then
  browser_log="${LOG%.log}-browser.log"
  if bash "$ROOT/ops/browser_check.sh" --quick >"$browser_log" 2>&1 && ! grep -qi 'skip:' "$browser_log" && grep -q '浏览器回归通过' "$browser_log"; then
    echo "ok   浏览器回归（quick）"
  else
    echo "FAIL 浏览器回归未完成（日志 ${browser_log}）"
    fail=1
  fi
  cat "$browser_log" >>"$LOG"
else
  echo "未放行 浏览器回归未验收（--no-browser仅执行其他检查）"
  fail=1
fi

run "发布包版本、清单、SHA与源码一致性" python3 "$ROOT/ops/check_release.py"

if [ "$fail" -ne 0 ]; then
  echo "结论: 不放行（查看 ${LOG}）"
  exit 1
fi
echo "结论: 放行"
