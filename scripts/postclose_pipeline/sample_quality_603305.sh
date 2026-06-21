#!/usr/bin/env bash
set -euo pipefail
DATE_YYYYMMDD="${1:-$(date +%Y%m%d)}"

# __SAMPLE_QUALITY_SHIM__
# P1: sample_quality_daily 实现缺失时仅标记WARN，不阻断postclose全链路
IMPL_HINT="${IMPL_HINT:-/Users/wxo/Desktop/Kronos/scripts/sample_quality_daily.py}"
if [[ ! -f "$IMPL_HINT" ]]; then
  echo "status=WARN error_code=SAMPLE_QUALITY_IMPL_MISSING date=${DATE_YYYYMMDD} note=\"compatibility shim; real daily sample quality script not found; no grade generated\" output=/Users/wxo/Desktop/Kronos/guard_outputs/sample_quality_daily_${DATE_YYYYMMDD}.json"
  # 写一个最小可审计JSON，避免下游找不到文件
  python3 - <<'PY2'
import json, os, time
d=os.environ.get('DATE_YYYYMMDD') or time.strftime('%Y%m%d')
out=f'/Users/wxo/Desktop/Kronos/guard_outputs/sample_quality_daily_{d}.json'
payload={'date': d, 'status':'WARN', 'error_code':'SAMPLE_QUALITY_IMPL_MISSING', 'note':'shim: impl missing'}
with open(out,'w',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2)
print(out)
PY2
  exit 0
fi

BASE="/Users/wxo/Desktop/Kronos"

case "sample_quality" in
  slot_coverage)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_slot_coverage --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_slot_coverage}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/slot_coverage_daily.py" "${DATE_YYYYMMDD}" ;;
  error_code_daily)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_error_code_daily --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_error_code_daily}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/error_code_daily.py" "${DATE_YYYYMMDD}" ;;
  scorecard_daily)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_scorecard_daily --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_scorecard_daily}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/scorecard_daily.py" "${DATE_YYYYMMDD}" ;;
  sample_quality)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_sample_quality --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_sample_quality}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/sample_quality_daily.py" "${DATE_YYYYMMDD}" ;;
  main_shadow_review)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_main_shadow_review --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_main_shadow_review}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/main_shadow_review_603305.py" "${DATE_YYYYMMDD}" ;;
  factor_postclose)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_factor_postclose --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_factor_postclose}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/factor_score_observer_postclose.py" --date "${DATE_YYYYMMDD}" --symbol 603305 --weight-profile conservative ;;
  strategy_param_proposal)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_strategy_param_proposal --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_strategy_param_proposal}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/strategy_param_proposal_603305.py" "${DATE_YYYYMMDD}" ;;
  chatgpt_handoff)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_chatgpt_handoff --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_chatgpt_handoff}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- python3 "/Users/wxo/Desktop/Kronos/scripts/chatgpt_handoff_603305.py" "${DATE_YYYYMMDD}" ;;
  regression)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_regression --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_regression}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- bash "/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh" ;;
  close_stability_summary)
    exec bash "/Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh" --task-name postclose_close_stability_summary --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-postclose_close_stability_summary}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" -- bash "/Users/wxo/Desktop/Kronos/scripts/check_close_stability_603305.sh" ;;
  *)
    echo "unknown step"; exit 2;;
esac
