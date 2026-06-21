#!/usr/bin/env bash
set -euo pipefail

# 用法示例：
#   bash run_pair.sh
#   SYMBOLS="603305 002049 600000" START_DATE=2020-01-01 bash run_pair.sh
#   bash run_pair.sh 603305 002049 600000

# 1) 标的：优先使用命令行参数，其次读取环境变量 SYMBOLS，最后用默认二标的
if [[ "$#" -gt 0 ]]; then
  SYMBOLS=("$@")
elif [[ -n "${SYMBOLS:-}" ]]; then
  # shellcheck disable=SC2206
  SYMBOLS=(${SYMBOLS})
else
  SYMBOLS=("603305" "002049")
fi

# 2) 日期区间
START_DATE="${START_DATE:-2020-01-01}"
END_DATE="${END_DATE:-}"

# 3) 输出目录（默认带时间戳）
OUT_ROOT="${OUT_ROOT:-outputs}"
RUN_TAG="${RUN_TAG:-$(date +%F_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${OUT_ROOT}/${RUN_TAG}}"

mkdir -p "$OUT_DIR"

# 4) 进入脚本所在目录，避免从别处调用时相对路径失效
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 5) 激活虚拟环境（兼容 .venv / kronos_venv）
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [[ -f "kronos_venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source kronos_venv/bin/activate
fi

PYTHON_BIN="${PYTHON_BIN:-python}"

# 6) 基础检查
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "❌ 未找到 Python: $PYTHON_BIN"
  exit 1
fi

if [[ ! -f "scripts/run_forecast.py" ]]; then
  echo "❌ 缺少 scripts/run_forecast.py"
  exit 1
fi

if [[ ! -f "scripts/run_eval.py" ]]; then
  echo "❌ 缺少 scripts/run_eval.py"
  exit 1
fi

echo "Output dir: $OUT_DIR"
echo "Symbols: ${SYMBOLS[*]}"
echo "Date range: ${START_DATE} ~ ${END_DATE:-latest}"
echo "Python: $($PYTHON_BIN -V 2>&1)"
echo

ok_count=0
fail_count=0

for s in "${SYMBOLS[@]}"; do
  echo "=== Running $s ==="

  if "$PYTHON_BIN" scripts/run_forecast.py \
    --symbol "$s" \
    --start "$START_DATE" \
    ${END_DATE:+--end "$END_DATE"} \
    --out "$OUT_DIR/${s}_forecast.csv" \
    --plot "$OUT_DIR/${s}_forecast.png"; then
    echo "✅ forecast ok: $s"
  else
    echo "❌ forecast failed: $s"
    ((fail_count+=1))
    continue
  fi

  if "$PYTHON_BIN" scripts/run_eval.py \
    --symbol "$s" \
    --start "$START_DATE" \
    ${END_DATE:+--end "$END_DATE"} \
    --out "$OUT_DIR/${s}_eval.csv"; then
    echo "✅ eval ok: $s"
    ((ok_count+=1))
  else
    echo "❌ eval failed: $s"
    ((fail_count+=1))
  fi

  echo

done

echo "===== Summary ====="
echo "Success symbols: $ok_count"
echo "Failed symbols:  $fail_count"
echo "Output dir:       $OUT_DIR"

if [[ "$fail_count" -gt 0 ]]; then
  exit 2
fi

echo "✅ done"
