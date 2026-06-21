#!/usr/bin/env bash
set -u

cd /Users/wxo/Desktop/Kronos || exit 1

LATEST_REPORT=$(python3 - <<'PY'
import glob, os
files=glob.glob("guard_outputs/report_*.txt")
if files:
    print(max(files, key=os.path.getmtime))
PY
)

if [ -z "${LATEST_REPORT:-}" ]; then
  echo "ERROR: no report_*.txt found"
  exit 1
fi

TS="$(date '+%Y%m%d_%H%M%S')"
OUT="guard_outputs/review_${TS}.md"
ERR="guard_outputs/review_${TS}.err"

PROMPT_FILE="/tmp/kronos_review_prompt_${TS}.txt"

{
  echo "You are Kronos 603305 post-close Reviewer."
  echo "Please review the following report in Chinese."
  echo
  echo "Required sections:"
  echo "1. sample completeness"
  echo "2. whether it can be used for strategy evaluation"
  echo "3. main strategy action consistency"
  echo "4. risk / position / signal consistency"
  echo "5. data source / MTM / missing fields"
  echo "6. read-only suggestions; do not request intraday rerun; do not modify cron"
  echo
  echo "- source_report: ${LATEST_REPORT}"
  echo "- review_time: ${TS}"
  echo "- reviewer_model: openai/gpt-5.5"
  echo
  echo "===== REPORT BEGIN ====="
  cat "$LATEST_REPORT"
  echo
  echo "===== REPORT END ====="
} > "$PROMPT_FILE"

echo "LATEST_REPORT=$LATEST_REPORT"
echo "OUT=$OUT"

openclaw agent \
  --agent reviewer \
  --model openai/gpt-5.5 \
  --message "$(cat "$PROMPT_FILE")" \
  --timeout 180 > "$OUT" 2> "$ERR"

RC=$?
echo "openclaw_rc=$RC"

if [ "$RC" -eq 0 ]; then
  echo "review_saved=$OUT"
  echo "stderr_saved=$ERR"
  rm -f "$PROMPT_FILE"
  exit 0
else
  echo "ERROR: review failed"
  echo "out=$OUT"
  echo "err=$ERR"
  tail -80 "$ERR" || true
  exit "$RC"
fi
