#!/usr/bin/env bash
set -euo pipefail

# 多参数验证套件（小白可直接执行）
# 目标：判断 Kronos 是否稳定优于 baseline，而不是看单次运气
# 用法：
#   cd /Users/wxo/Desktop/Kronos
#   bash run_validation_suite.sh
# 可选：
#   SYMBOL=603305 START_DATE=2020-01-01 SOURCE=auto bash run_validation_suite.sh

SYMBOL="${SYMBOL:-603305}"
START_DATE="${START_DATE:-2020-01-01}"
END_DATE="${END_DATE:-}"
SOURCE="${SOURCE:-auto}"
MAX_WINDOWS="${MAX_WINDOWS:-12}"
STRIDE="${STRIDE:-5}"

LOOKBACKS=(200 300 400 500)
PRED_LENS=(5 10 20)

OUT_ROOT="${OUT_ROOT:-outputs}"
RUN_TAG="${RUN_TAG:-$(date +%F_%H%M%S)_validation_${SYMBOL}}"
OUT_DIR="${OUT_DIR:-${OUT_ROOT}/${RUN_TAG}}"
mkdir -p "$OUT_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [[ -f "kronos_venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source kronos_venv/bin/activate
fi

PYTHON_BIN="${PYTHON_BIN:-python}"

echo "=== Validation Suite ==="
echo "Symbol:     $SYMBOL"
echo "Date range: $START_DATE ~ ${END_DATE:-latest}"
echo "Source:     $SOURCE"
echo "MaxWindows: $MAX_WINDOWS"
echo "Stride:     $STRIDE"
echo "Out dir:    $OUT_DIR"
echo

for lb in "${LOOKBACKS[@]}"; do
  for pl in "${PRED_LENS[@]}"; do
    echo "--- eval lb=$lb pl=$pl ---"
    "$PYTHON_BIN" scripts/run_eval.py \
      --symbol "$SYMBOL" \
      --start "$START_DATE" \
      ${END_DATE:+--end "$END_DATE"} \
      --lookback "$lb" \
      --pred-len "$pl" \
      --stride "$STRIDE" \
      --max-windows "$MAX_WINDOWS" \
      --source "$SOURCE" \
      --out "$OUT_DIR/${SYMBOL}_eval_lb${lb}_pl${pl}.csv"
  done
done

"$PYTHON_BIN" scripts/validation_suite.py \
  --symbol "$SYMBOL" \
  --input-dir "$OUT_DIR" \
  --out-csv "$OUT_DIR/${SYMBOL}_validation_summary.csv" \
  --out-md "$OUT_DIR/${SYMBOL}_validation_report.md"

echo
echo "✅ done: $OUT_DIR"
echo "- summary: $OUT_DIR/${SYMBOL}_validation_summary.csv"
echo "- report:  $OUT_DIR/${SYMBOL}_validation_report.md"
