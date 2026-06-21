#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BASE/guard_outputs/p0_603305_preflight_dryrun_safe_${TS}.md"

mkdir -p "$BASE/guard_outputs"

exec > >(tee -a "$OUT") 2>&1

echo "# P0 603305 Preflight Dry-run Safe"
echo "- ts: $(date '+%Y-%m-%d %H:%M:%S')"
echo "- mode: dry-run / read-only"
echo "- boundary: 不改 cron、不补跑、不改策略、不生成正式 report"
echo

FAIL=0

echo "## 1) trading_calendar tomorrow"
python3 - <<'PY'
import sys
from pathlib import Path
from datetime import date, timedelta

base = Path("/Users/wxo/Desktop/Kronos")
sys.path.insert(0, str(base))
sys.path.insert(0, str(base / "scripts"))

tomorrow = date.today() + timedelta(days=1)
print("tomorrow=", tomorrow)

try:
    import trading_calendar as tc
except Exception as e:
    print("FAIL import trading_calendar:", repr(e))
    raise SystemExit(1)

fn = None
for name in ["is_trading_day", "is_trade_day", "is_cn_trading_day"]:
    if hasattr(tc, name):
        fn = getattr(tc, name)
        break

if fn is None:
    print("FAIL no trading day function found")
    raise SystemExit(1)

ok = bool(fn(tomorrow))
print("is_trading_day=", ok)

if not ok:
    raise SystemExit(2)
PY

echo
echo "## 2) premarket_guard compile and check"
python3 -m py_compile "$BASE/scripts/premarket_guard_603305.py"
python3 "$BASE/scripts/premarket_guard_603305.py" --mode check
echo "OK premarket_guard check PASS"

echo
echo "## 3) bash syntax checks"
bash -n "$BASE/scripts/run_with_model_guard.sh"
bash -n "$BASE/scripts/postclose_pipeline/regression_603305.sh"
bash -n "$BASE/scripts/postclose_pipeline/close_stability_summary_603305.sh"
echo "OK bash -n PASS"

echo
echo "## 4) cron schedule check"
openclaw cron list --json | jq -r '
  ..
  | objects
  | select((.name // "") | test("premarket_guard_603305|603305-weekday-morning-every10-sim|603305-weekday-morning-every10-sim-10to11|603305-weekday-morning-every10-sim-11to1130|603305-weekday-afternoon-every10-sim|603305_close_review|postclose_603305_chatgpt_handoff_1524"))
  | [
      .name,
      ("enabled=" + ((.enabled // "-")|tostring)),
      ("expr=" + ((.schedule.expr // "-")|tostring)),
      ("tz=" + ((.schedule.tz // "-")|tostring)),
      ("lastStatus=" + ((.state.lastStatus // "-")|tostring)),
      ("nextRunAtMs=" + ((.state.nextRunAtMs // "-")|tostring)),
      ("payload_has_taskq=" + (((.payload.message // "") | contains("taskq_submit.sh"))|tostring))
    ]
  | @tsv
' | column -t -s $'\t'

echo
echo "## 5) hard gates"

if ! openclaw cron list --json | jq -e '
  ..
  | objects
  | select((.name // "") == "603305-weekday-morning-every10-sim")
  | select((.enabled == true) and (.state.nextRunAtMs != null))
' >/dev/null; then
  echo "FAIL: 09:30 every10 cron missing enabled=true or nextRunAtMs"
  FAIL=1
else
  echo "OK: 09:30 every10 cron enabled and scheduled"
fi

for name in 603305_close_review postclose_603305_chatgpt_handoff_1524; do
  if ! openclaw cron list --json | jq -e --arg name "$name" '
    ..
    | objects
    | select((.name // "") == $name)
    | select((.payload.message // "" | contains("taskq_submit.sh")))
  ' >/dev/null; then
    echo "FAIL: $name payload not using taskq_submit.sh"
    FAIL=1
  else
    echo "OK: $name payload uses taskq_submit.sh"
  fi
done

echo
echo "## 6) output"
echo "$OUT"

if [[ "$FAIL" -eq 0 ]]; then
  echo "RESULT=PASS"
else
  echo "RESULT=FAIL"
  exit 1
fi
