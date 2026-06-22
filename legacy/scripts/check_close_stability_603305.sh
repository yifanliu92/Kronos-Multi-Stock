#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
GUARD="$BASE/guard_outputs"
DATE="$(date +%Y%m%d)"

MODEL_GUARD="$GUARD/model_guard_daily_${DATE}.json"
SCORECARD="$GUARD/scorecard_daily_${DATE}.json"
SLOT_COV="$GUARD/slot_coverage_daily_${DATE}.json"
CRON_RUNS="$GUARD/cron_runs_${DATE}.json"

now() { date '+%F %T'; }

echo "[close_stability_check] ts=$(now) date=${DATE}"

# 1) model not found / not supported
if [[ -f "$CRON_RUNS" ]]; then
  echo "--- model errors in cron_runs_${DATE}.json"
  python3 - <<PY
import json
from pathlib import Path
p=Path("$CRON_RUNS")
d=json.loads(p.read_text(encoding='utf-8'))
errs=[]
for e in d.get('entries',[]):
    s=str(e.get('error') or '') + ' ' + str(e.get('summary') or '')
    if ('Model not found' in s) or ('not supported' in s):
        errs.append({'timeslot':e.get('timeslot'), 'model':e.get('model'), 'error':(e.get('error') or e.get('summary'))})
print('count=', len(errs))
for x in errs[:20]:
    print(x)
PY
else
  echo "WARN: missing $CRON_RUNS (cron runs not rebuilt yet)"
fi

# 2) timeout
echo "--- timeout scan (cron runs raw errors)"
if [[ -f "$CRON_RUNS" ]]; then
  python3 - <<PY
import json
from pathlib import Path
p=Path("$CRON_RUNS")
d=json.loads(p.read_text(encoding='utf-8'))
outs=[]
for e in d.get('entries',[]):
    s=str(e.get('error') or '') + ' ' + str(e.get('summary') or '')
    if 'Request timed out before a response was generated' in s:
        outs.append({'timeslot':e.get('timeslot'), 'jobId':e.get('jobId'), 'model':e.get('model'), 'durationMs':e.get('durationMs'), 'error':e.get('error') or e.get('summary')})
print('count=', len(outs))
for x in outs[:20]:
    print(x)
PY
else
  echo "WARN: missing $CRON_RUNS"
fi

# 3) model_guard_daily present + last entry sample
echo "--- model_guard_daily"
if [[ -f "$MODEL_GUARD" ]]; then
  python3 - <<PY
import json
from pathlib import Path
p=Path("$MODEL_GUARD")
d=json.loads(p.read_text(encoding='utf-8'))
print('entries=', len(d.get('entries',[])))
if d.get('entries'):
    e=d['entries'][-1]
    keys=['ts','jobId','task_name','original_model','allowlist_pass','fallback_attempted','fallback_result','final_model','final_status']
    print({k:e.get(k) for k in keys})
PY
else
  echo "FAIL: missing $MODEL_GUARD"
fi

# 4/5) 603305 sim + self_audit/scorecard existence
echo "--- required outputs existence"
[[ -f "$SLOT_COV" ]] && echo "OK slot_coverage_daily" || echo "WARN missing slot_coverage_daily"
[[ -f "$SCORECARD" ]] && echo "OK scorecard_daily" || echo "WARN missing scorecard_daily"

# 6) run regression
echo "--- run regression"
bash "$BASE/scripts/run_kronos_regression.sh"
