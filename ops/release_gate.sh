#!/bin/bash
# 发版看门狗：全量验证 + 浏览器回归 + 发布包一致性，一条命令给结论。
# 用法：bash ops/release_gate.sh [--no-browser]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/release-gate-$(date +%Y%m%d-%H%M%S).log"
WITH_BROWSER=1
for arg in "$@"; do
  [ "$arg" = "--no-browser" ] && WITH_BROWSER=0
done
fail=0
run() {
  name="$1"; shift
  if "$@" >>"$LOG" 2>&1; then
    echo "ok   $name"
  else
    echo "FAIL $name（日志 $LOG）"
    fail=1
  fi
}

echo "== 发版看门狗 =="
echo "日志: $LOG"
run "全量验证（ops/verify.py）" bash "$ROOT/ops/quick_check.sh" --full
if [ "$WITH_BROWSER" -eq 1 ]; then
  run "浏览器回归（quick）" bash "$ROOT/ops/browser_check.sh" --quick
else
  echo "跳过 浏览器回归（--no-browser）"
fi

version="$(cat "$ROOT/VERSION" 2>/dev/null | tr -d '[:space:]')"
pkg="$ROOT/output/releases/yangfan-erp-$version.tar.gz"
if [ -f "$pkg" ]; then
  expect="$(cut -d' ' -f1 "${pkg}.sha256" 2>/dev/null)"
  actual="$(shasum -a 256 "$pkg" | cut -d' ' -f1)"
  if [ -n "$expect" ] && [ "$expect" = "$actual" ]; then
    echo "ok   当前版本包校验（$version）"
  else
    echo "FAIL 当前版本包校验（$version，sha256 不一致或缺少 .sha256，日志 $LOG）"
    fail=1
  fi
  inner="$(tar xzOf "$pkg" ./VERSION 2>/dev/null | tr -d '[:space:]')"
  if [ "$inner" = "$version" ]; then
    echo "ok   包内 VERSION（$version）"
  else
    echo "FAIL 包内 VERSION 为「${inner:-空}」，期望 $version（日志 $LOG）"
    fail=1
  fi
else
  echo "提示 尚无 v$version 发布包（打包后重跑本脚本可校验）"
fi

if [ "$fail" -ne 0 ]; then
  echo "结论: 不放行（查看 $LOG）"
  exit 1
fi
echo "结论: 放行"
