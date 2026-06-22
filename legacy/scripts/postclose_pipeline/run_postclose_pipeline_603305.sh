#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
DATE_YYYYMMDD="${1:-${DATE_YYYYMMDD:-$(date +%Y%m%d)}}"

# Post-close unified pipeline.
# All executable steps must go through per-step wrappers.
# Each wrapper uses run_with_model_guard.sh, so model guard / audit / provider fallback are preserved.

echo "[postclose_pipeline] date=${DATE_YYYYMMDD}"

if [[ "${KRONOS_POSTCLOSE_DRY_RUN:-0}" == "1" ]]; then
  echo "[postclose_pipeline] dry_run=1"
  echo "slot_coverage_603305.sh ${DATE_YYYYMMDD}"
  echo "error_code_daily_603305.sh ${DATE_YYYYMMDD}"
  echo "scorecard_daily_603305.sh ${DATE_YYYYMMDD}"
  echo "sample_quality_603305.sh ${DATE_YYYYMMDD}"
  echo "main_shadow_review_603305.sh ${DATE_YYYYMMDD}"
  echo "factor_postclose_603305.sh ${DATE_YYYYMMDD}"
  echo "strategy_param_proposal_603305.sh ${DATE_YYYYMMDD}"
  echo "chatgpt_handoff_603305.sh ${DATE_YYYYMMDD}"
  echo "[postclose_pipeline] dry_run_done date=${DATE_YYYYMMDD}"
  exit 0
fi

bash "$BASE/scripts/postclose_pipeline/slot_coverage_603305.sh" "$DATE_YYYYMMDD"
bash "$BASE/scripts/postclose_pipeline/error_code_daily_603305.sh" "$DATE_YYYYMMDD"
bash "$BASE/scripts/postclose_pipeline/scorecard_daily_603305.sh" "$DATE_YYYYMMDD"
bash "$BASE/scripts/postclose_pipeline/sample_quality_603305.sh" "$DATE_YYYYMMDD"
bash "$BASE/scripts/postclose_pipeline/main_shadow_review_603305.sh" "$DATE_YYYYMMDD"
bash "$BASE/scripts/postclose_pipeline/factor_postclose_603305.sh" "$DATE_YYYYMMDD"
bash "$BASE/scripts/postclose_pipeline/strategy_param_proposal_603305.sh" "$DATE_YYYYMMDD"
bash "$BASE/scripts/postclose_pipeline/chatgpt_handoff_603305.sh" "$DATE_YYYYMMDD"

echo "[postclose_pipeline] done date=${DATE_YYYYMMDD}"
