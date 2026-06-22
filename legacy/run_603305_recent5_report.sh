#!/usr/bin/env bash
set -euo pipefail

# 目标：只跑 603305，生成“最近5天”预测+评估+分析报告+图表
# 用法：
#   cd /Users/wxo/Desktop/Kronos
#   bash run_603305_recent5_report.sh
# 可选：
#   START_DATE=2020-01-01 SOURCE=auto bash run_603305_recent5_report.sh
#   AUTO_BEST=0 bash run_603305_recent5_report.sh                 # 关闭自动最优参数
#   VALIDATION_SUMMARY=outputs/.../603305_validation_summary.csv bash run_603305_recent5_report.sh

SYMBOL="603305"
START_DATE="${START_DATE:-2020-01-01}"
END_DATE="${END_DATE:-}"
LOOKBACK_DEFAULT="400"
PRED_LEN_DEFAULT="5"             # 最近5天预测
LOOKBACK_SET_BY_USER="${LOOKBACK+x}"
PRED_LEN_SET_BY_USER="${PRED_LEN+x}"
LOOKBACK="${LOOKBACK:-$LOOKBACK_DEFAULT}"
PRED_LEN="${PRED_LEN:-$PRED_LEN_DEFAULT}"
STRIDE="${STRIDE:-5}"
MAX_WINDOWS="${MAX_WINDOWS:-1}" # 只看最近一个评估窗口
SOURCE="${SOURCE:-auto}"
AUTO_BEST="${AUTO_BEST:-1}"     # 1=自动应用验证过的最优参数

OUT_ROOT="${OUT_ROOT:-outputs}"
RUN_TAG="${RUN_TAG:-$(date +%F_%H%M%S)_603305_recent5}"
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

# 自动寻找最近 validation summary 并推荐参数
if [[ "$AUTO_BEST" == "1" ]]; then
  VALIDATION_SUMMARY="${VALIDATION_SUMMARY:-}"

  if [[ -z "$VALIDATION_SUMMARY" ]]; then
    VALIDATION_SUMMARY="$(ls -1dt outputs/*_validation_${SYMBOL}/${SYMBOL}_validation_summary.csv 2>/dev/null | head -n 1 || true)"
  fi

  if [[ -n "$VALIDATION_SUMMARY" && -f "$VALIDATION_SUMMARY" ]]; then
    echo "[info] found validation summary: $VALIDATION_SUMMARY"
    # shellcheck disable=SC2046
    eval "$($PYTHON_BIN scripts/recommend_params.py --symbol "$SYMBOL" --summary-csv "$VALIDATION_SUMMARY" --prefer green)"

    # 若用户未显式传 LOOKBACK/PRED_LEN，则采用推荐值
    if [[ -z "$LOOKBACK_SET_BY_USER" && -n "${RECO_LOOKBACK:-}" ]]; then
      LOOKBACK="$RECO_LOOKBACK"
    fi
    if [[ -z "$PRED_LEN_SET_BY_USER" && -n "${RECO_PRED_LEN:-}" ]]; then
      PRED_LEN="$RECO_PRED_LEN"
    fi

    echo "[info] recommendation: lookback=${RECO_LOOKBACK:-NA} pred_len=${RECO_PRED_LEN:-NA} decision=${RECO_DECISION:-NA}"
    echo "[info] final params used: lookback=$LOOKBACK pred_len=$PRED_LEN"
  else
    echo "[info] no validation summary found, keep defaults lookback=$LOOKBACK pred_len=$PRED_LEN"
  fi
fi

echo "=== Kronos recent5 report run ==="
echo "Symbol:     $SYMBOL"
echo "Date range: $START_DATE ~ ${END_DATE:-latest}"
echo "Source:     $SOURCE"
echo "Params:     lookback=$LOOKBACK pred_len=$PRED_LEN stride=$STRIDE max_windows=$MAX_WINDOWS"
echo "Out dir:    $OUT_DIR"
echo "Python:     $($PYTHON_BIN -V 2>&1)"
echo

"$PYTHON_BIN" scripts/run_forecast.py \
  --symbol "$SYMBOL" \
  --start "$START_DATE" \
  ${END_DATE:+--end "$END_DATE"} \
  --lookback "$LOOKBACK" \
  --pred-len "$PRED_LEN" \
  --source "$SOURCE" \
  --out "$OUT_DIR/${SYMBOL}_forecast.csv" \
  --plot "$OUT_DIR/${SYMBOL}_forecast.png"

"$PYTHON_BIN" scripts/run_eval.py \
  --symbol "$SYMBOL" \
  --start "$START_DATE" \
  ${END_DATE:+--end "$END_DATE"} \
  --lookback "$LOOKBACK" \
  --pred-len "$PRED_LEN" \
  --stride "$STRIDE" \
  --max-windows "$MAX_WINDOWS" \
  --source "$SOURCE" \
  --out "$OUT_DIR/${SYMBOL}_eval.csv"

"$PYTHON_BIN" scripts/report_recent5.py \
  --symbol "$SYMBOL" \
  --start "$START_DATE" \
  ${END_DATE:+--end "$END_DATE"} \
  --source "$SOURCE" \
  --forecast-csv "$OUT_DIR/${SYMBOL}_forecast.csv" \
  --eval-csv "$OUT_DIR/${SYMBOL}_eval.csv" \
  --out-dir "$OUT_DIR"

echo
echo "✅ done: $OUT_DIR"
echo "- report: $OUT_DIR/${SYMBOL}_recent5_report.md"
echo "- chart1: $OUT_DIR/${SYMBOL}_recent5_trend.png"
echo "- chart2: $OUT_DIR/${SYMBOL}_recent5_returns.png"
