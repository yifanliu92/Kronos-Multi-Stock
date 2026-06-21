#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
DATE_YYYYMMDD="${1:-${DATE_YYYYMMDD:-$(date +%Y%m%d)}}"

mkdir -p "$BASE/guard_outputs" "$BASE/daily_reports"

LOG_OUT="$BASE/guard_outputs/close_stability_summary_${DATE_YYYYMMDD}.log"
MD_OUT="$BASE/daily_reports/close_stability_summary_${DATE_YYYYMMDD}.md"
JSON_OUT="$BASE/guard_outputs/close_stability_summary_${DATE_YYYYMMDD}.json"

TMP_OUT="$(mktemp)"

{
  echo "[close_stability_check] ts=$(date '+%F %T') date=${DATE_YYYYMMDD}"

  if [[ ! -f "$BASE/guard_outputs/cron_runs_${DATE_YYYYMMDD}.json" ]]; then
    echo "WARN: missing $BASE/guard_outputs/cron_runs_${DATE_YYYYMMDD}.json (cron runs not rebuilt yet)"
  fi

  echo "--- timeout scan (cron runs raw errors)"
  if [[ -f "$BASE/guard_outputs/cron_runs_${DATE_YYYYMMDD}.json" ]]; then
    grep -i "timeout\|error" "$BASE/guard_outputs/cron_runs_${DATE_YYYYMMDD}.json" || true
  else
    echo "WARN: missing $BASE/guard_outputs/cron_runs_${DATE_YYYYMMDD}.json"
  fi

  echo "--- model_guard_daily"
  python3 <<PY2
import json
from pathlib import Path
p=Path("$BASE/guard_outputs/model_guard_daily_${DATE_YYYYMMDD}.json")
if not p.exists():
    print("WARN: missing", p)
else:
    d=json.loads(p.read_text(encoding="utf-8"))
    entries=d.get("entries", [])
    print("entries=", len(entries))
    if entries:
        print(entries[-1])
PY2

  echo "--- required outputs existence"
  [[ -f "$BASE/guard_outputs/slot_coverage_daily_${DATE_YYYYMMDD}.json" ]] && echo "OK slot_coverage_daily" || echo "WARN missing slot_coverage_daily"
  [[ -f "$BASE/guard_outputs/scorecard_daily_${DATE_YYYYMMDD}.json" ]] && echo "OK scorecard_daily" || echo "WARN missing scorecard_daily"

  echo "--- run regression"
  bash "$BASE/scripts/run_kronos_regression.sh"
} | tee "$TMP_OUT"

cp "$TMP_OUT" "$LOG_OUT"

RESULT_LINE="$(grep -E '^RESULT=' "$TMP_OUT" | tail -1 || true)"
SUMMARY_LINE="$(grep -E '^SUMMARY ' "$TMP_OUT" | tail -1 || true)"

{
  echo "# close_stability_summary ${DATE_YYYYMMDD}"
  echo
  echo "- generated_at: $(date '+%F %T')"
  echo "- result: ${RESULT_LINE:-UNKNOWN}"
  echo "- summary: ${SUMMARY_LINE:-UNKNOWN}"
  echo "- log: $LOG_OUT"
  echo
  echo "## Tail"
  echo '```text'
  tail -80 "$TMP_OUT"
  echo '```'
} > "$MD_OUT"

python3 <<PY3
import json, re
from pathlib import Path

txt=Path("$TMP_OUT").read_text(encoding="utf-8", errors="replace")
summary=re.findall(r"^SUMMARY PASS=(\d+) WARN=(\d+) FAIL=(\d+)", txt, flags=re.M)
result=re.findall(r"^RESULT=(\w+)", txt, flags=re.M)

payload={
  "date": "$DATE_YYYYMMDD",
  "generated_at": "$(date '+%F %T')",
  "result": result[-1] if result else None,
  "summary": {
    "pass": int(summary[-1][0]) if summary else None,
    "warn": int(summary[-1][1]) if summary else None,
    "fail": int(summary[-1][2]) if summary else None,
  },
  "log_path": "$LOG_OUT",
  "md_path": "$MD_OUT",
}
Path("$JSON_OUT").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY3

rm -f "$TMP_OUT"

echo "WROTE $LOG_OUT"
echo "WROTE $MD_OUT"
echo "WROTE $JSON_OUT"
