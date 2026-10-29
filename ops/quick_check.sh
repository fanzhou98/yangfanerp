#!/usr/bin/env bash
# 快速自检：只跑 git 改动涉及的测试，目标 60 秒内。
# 用法：ops/quick_check.sh [--full] [--files "a.py b.js"] [--list]
#   --full   全量验证（转交 ops/verify.py，保留原 600 秒上限）
#   --files  不读 git，直接检查指定文件
#   --list   只列出改动与将运行的测试，不执行
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

MODE=quick
CUSTOM_FILES=""
SKIP_VOLUME=false
while [ $# -gt 0 ]; do
  case "$1" in
    --full) MODE=full; shift ;;
    --skip-volume) SKIP_VOLUME=true; shift ;;
    --files) CUSTOM_FILES="${2:-}"; shift 2 ;;
    --list) MODE=list; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [ "$MODE" = full ]; then
  echo "== 全量验证：ops/verify.py =="
  if [ "$SKIP_VOLUME" = true ]; then exec python3 ops/verify.py --skip-volume; fi
  exec python3 ops/verify.py
fi

if [ -n "$CUSTOM_FILES" ]; then
  CHANGED="$CUSTOM_FILES"
else
  CHANGED=$(git status --porcelain 2>/dev/null | cut -c4- | sed -E 's/^.* -> //' | tr '\n' ' ')
fi

if [ -z "${CHANGED// /}" ]; then
  echo "工作区无改动，跳过（交付前请跑 ops/quick_check.sh --full）"
  exit 0
fi

echo "== 改动文件 =="
for f in $CHANGED; do echo "  $f"; done

PY_FILES=()
JS_FILES=()
TESTS=()
for f in $CHANGED; do
  case "$f" in
    *.py) PY_FILES+=("$f") ;;
    web/*.js) JS_FILES+=("$f") ;;
  esac
  case "$f" in
    tests/test_*.py)
      m=$(basename "$f" .py)
      TESTS+=("$m")
      ;;
  esac
done

# 源模块 → 对应测试：先精确匹配，再前缀匹配，最后按 import 反查
for f in "${PY_FILES[@]+"${PY_FILES[@]}"}"; do
  case "$f" in tests/*) continue ;; esac
  m=$(basename "$f" .py)
  found=""
  if [ -f "tests/test_${m}.py" ]; then
    found="test_${m}"
  else
    hit=$(ls tests/test_"${m}"_*.py 2>/dev/null | head -5)
    if [ -n "$hit" ]; then
      found=$(for h in $hit; do basename "$h" .py; done | tr '\n' ' ')
    fi
  fi
  if [ -z "$found" ]; then
    found=$(grep -lE "^import ${m}\$|^from ${m} import" tests/test_*.py 2>/dev/null \
      | head -6 | xargs -I{} basename {} .py 2>/dev/null | tr '\n' ' ')
  fi
  for t in $found; do TESTS+=("$t"); done
done

# 去重保序（macOS 自带 bash 3.2 没有 mapfile）
if [ ${#TESTS[@]} -gt 0 ]; then
  _dedup=$(printf '%s\n' "${TESTS[@]}" | awk '!seen[$0]++')
  TESTS=()
  while IFS= read -r _t; do TESTS+=("$_t"); done <<< "$_dedup"
fi

echo "== 计划 =="
echo "  语法检查: ${#PY_FILES[@]} 个 .py, ${#JS_FILES[@]} 个 web/*.js"
if [ ${#TESTS[@]} -gt 0 ]; then
  echo "  单元测试: ${TESTS[*]}"
else
  echo "  单元测试: 未匹配到，仅做语法检查；交付前仍需 --full"
fi

if [ "$MODE" = list ]; then
  exit 0
fi

START=$(date +%s)
FAILED=0

echo "== 语法检查 =="
for f in "${PY_FILES[@]+"${PY_FILES[@]}"}"; do
  if python3 -m py_compile "$f" 2>/tmp/qc_py.err; then
    echo "  ok   $f"
  else
    echo "  FAIL $f"; sed 's/^/       /' /tmp/qc_py.err; FAILED=1
  fi
done
if command -v node >/dev/null 2>&1; then
  for f in "${JS_FILES[@]+"${JS_FILES[@]}"}"; do
    if node --check "$f" 2>/tmp/qc_js.err; then
      echo "  ok   $f"
    else
      echo "  FAIL $f"; sed 's/^/       /' /tmp/qc_js.err; FAILED=1
    fi
  done
else
  [ ${#JS_FILES[@]} -gt 0 ] && echo "  skip Node 不可用，跳过 JS 语法检查"
fi

if [ ${#TESTS[@]} -gt 0 ]; then
  echo "== 单元测试 =="
  ( cd tests && PYTHONPATH=.. perl -e 'alarm 300; exec @ARGV' python3 -m unittest -v "${TESTS[@]}" ) \
    || FAILED=1
fi

ELAPSED=$(( $(date +%s) - START ))
if [ "$FAILED" -eq 0 ]; then
  echo "结果: ok (${ELAPSED}s)"
else
  echo "结果: 失败 (${ELAPSED}s)"
fi
exit "$FAILED"
