#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BASE/guard_outputs/verify_postclose_wiring_603305_${TS}.md"
CRON_JSON="$BASE/guard_outputs/cron_list_verify_postclose_${TS}.json"

mkdir -p "$BASE/guard_outputs"

exec > >(tee -a "$OUT") 2>&1

FAIL=0
WARN=0

echo "# Verify postclose wiring 603305"
echo "- ts: $(date '+%Y-%m-%d %H:%M:%S')"
echo "- mode: read-only verify"
echo "- boundary: 不改策略、不改 cron、不补跑、不生成正式交易 report"
echo

echo "## 1) Active script hardcoded date check: 20260525"
HITS="$(
  grep -RIn --exclude='*.bak*' --exclude='*.broken_*' --exclude='*.fix_*' --exclude='*.gatepatch_bak_*' "20260525" \
    "$BASE/scripts/postclose_pipeline" \
    "$BASE/scripts"/*daily*.py \
    "$BASE/scripts"/*603305*.py 2>/dev/null || true
)"

if [[ -n "$HITS" ]]; then
  echo "FAIL: active scripts still contain hardcoded 20260525"
  echo "$HITS"
  FAIL=1
else
  echo "OK: no active-script hardcoded 20260525 found"
fi

echo
echo "## 2) Syntax checks"
if bash -n "$BASE/scripts/postclose_pipeline/regression_603305.sh"; then
  echo "OK: bash -n regression_603305.sh"
else
  echo "FAIL: bash -n regression_603305.sh"
  FAIL=1
fi

if bash -n "$BASE/scripts/postclose_pipeline/close_stability_summary_603305.sh"; then
  echo "OK: bash -n close_stability_summary_603305.sh"
else
  echo "FAIL: bash -n close_stability_summary_603305.sh"
  FAIL=1
fi

if python3 -m py_compile "$BASE/scripts/sample_quality_daily.py"; then
  echo "OK: py_compile sample_quality_daily.py"
else
  echo "FAIL: py_compile sample_quality_daily.py"
  FAIL=1
fi

echo
echo "## 3) sample_quality shim status"
if grep -nE 'SAMPLE_QUALITY_IMPL_MISSING|status=ERROR' "$BASE/scripts/sample_quality_daily.py" >/tmp/sample_quality_static_check.txt 2>/dev/null; then
  echo "WARN: sample_quality_daily.py still contains ERROR / IMPL_MISSING marker"
  cat /tmp/sample_quality_static_check.txt
  WARN=$((WARN+1))
else
  echo "OK: sample_quality_daily.py does not expose ERROR / IMPL_MISSING marker"
fi

echo
echo "## 4) cron list snapshot with timeout guard"
python3 - "$CRON_JSON" <<'PY'
from pathlib import Path
import subprocess
import sys

out = Path(sys.argv[1])
try:
    cp = subprocess.run(
        ["openclaw", "cron", "list", "--json"],
        capture_output=True,
        text=True,
        timeout=20
    )
except subprocess.TimeoutExpired:
    print("FAIL: openclaw cron list --json timeout >20s")
    raise SystemExit(1)

if cp.returncode != 0:
    print("FAIL: openclaw cron list --json returncode", cp.returncode)
    print(cp.stderr)
    raise SystemExit(cp.returncode)

out.write_text(cp.stdout, encoding="utf-8")
print(f"OK: cron json saved to {out}")
PY

echo
echo "## 5) task_queue payload checks for long postclose crons"
for name in 603305_close_review postclose_603305_chatgpt_handoff_1524; do
  if jq -e --arg name "$name" '
    ..
    | objects
    | select((.name // "") == $name)
    | select((.enabled == true) and (.state.nextRunAtMs != null) and ((.payload.message // "") | contains("taskq_submit.sh")))
  ' "$CRON_JSON" >/dev/null; then
    echo "OK: $name enabled=true nextRunAtMs exists payload uses taskq_submit.sh"
  else
    echo "FAIL: $name missing enabled/nextRunAt/taskq_submit.sh"
    FAIL=1
  fi
done

echo
echo "## 6) regression unified-entry rule evidence"
REG_EVIDENCE="$(
  grep -RIn 'Cron unified entry\|taskq_submit.sh\|run_with_model_guard.sh' \
    "$BASE/scripts" 2>/dev/null | tail -80 || true
)"
echo "$REG_EVIDENCE"

if echo "$REG_EVIDENCE" | grep -q 'taskq_submit.sh'; then
  echo "OK: regression / governance scripts contain taskq_submit.sh evidence"
else
  echo "WARN: no taskq_submit.sh evidence found in regression/governance grep"
  WARN=$((WARN+1))
fi

echo
echo "## 7) Result"
echo "output=$OUT"

if [[ "$FAIL" -eq 0 && "$WARN" -eq 0 ]]; then
  echo "RESULT=PASS"
elif [[ "$FAIL" -eq 0 ]]; then
  echo "RESULT=PASS_WITH_WARNINGS"
  echo "WARN_COUNT=$WARN"
else
  echo "RESULT=FAIL"
  echo "FAIL_COUNT=$FAIL"
  echo "WARN_COUNT=$WARN"
  exit 1
fi
