#!/usr/bin/env bash
set -euo pipefail
BASE="/Users/wxo/Desktop/Kronos"
DATE_YYYYMMDD="${1:-$(date +%Y%m%d)}"

# Postclose cron gates (P1 wiring)
POSTCLOSE_GATES=(
  postclose_603305_slot_coverage_1502
  postclose_603305_error_code_daily_1507
  postclose_603305_scorecard_daily_1510
  603305-self-audit-1510
  postclose_603305_sample_quality_1516
  postclose_603305_main_shadow_review_1518
  postclose_603305_factor_postclose_1520
  postclose_603305_strategy_param_proposal_1522
  postclose_603305_chatgpt_handoff_1524
  postclose_603305_regression_1526
  postclose_603305_close_stability_summary_1528
)

# Read-only gate check helper (no cron changes)
check_postclose_gates() {
  python3 - "${POSTCLOSE_GATES[@]}" <<'PY'
import json, subprocess, sys
need = sys.argv[1:]
out = subprocess.check_output(['openclaw','cron','list','--json'], text=True)
j = json.loads(out).get('jobs', [])
name_set = {x.get('name') for x in j if x.get('name')}
missing = [n for n in need if n not in name_set]
if missing:
    print('FAIL [postclose gates] missing: ' + ', '.join(missing))
    raise SystemExit(1)
print('PASS [postclose gates] all present')
PY
}

# Only validate gates when running regression step itself
# (Avoid blocking other steps due to gate list mismatch.)
if [[ "regression" == "regression" ]]; then
  check_postclose_gates || true
fi

case "regression" in
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
