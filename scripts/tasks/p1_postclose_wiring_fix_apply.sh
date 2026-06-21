#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
SCRIPTS="$BASE/scripts"
PIPE="$SCRIPTS/postclose_pipeline"
DATE_YYYYMMDD="${1:-$(date +%Y%m%d)}"

LOG_DIR="$BASE/guard_outputs"
mkdir -p "$LOG_DIR"
OUT_SUMMARY="$LOG_DIR/p1_postclose_wiring_fix_${DATE_YYYYMMDD}_$(date +%H%M%S).md"

say() { echo "$*" | tee -a "$OUT_SUMMARY"; }

say "# P1 postclose 接线修复（不改策略/不补跑）"
say "- ts: $(date '+%Y-%m-%d %H:%M:%S')"
say "- date: ${DATE_YYYYMMDD}"
say ""

say "## 1) 确认/生成兼容 shim（避免 exit code 2）"
for f in \
  slot_coverage_daily.py \
  error_code_daily.py \
  scorecard_daily.py \
  sample_quality_daily.py \
  main_shadow_review_603305.py \
  strategy_param_proposal_603305.py
  do
  p="$SCRIPTS/$f"
  if [[ -f "$p" ]]; then
    say "- OK exists: $p"
  else
    say "- FAIL missing: $p"
    exit 2
  fi
done
say ""

say "## 2) 修正 close_stability_summary_603305.sh gate 名单为 1502-1528（按授权固定列表）"
CS="$PIPE/close_stability_summary_603305.sh"
if [[ ! -f "$CS" ]]; then
  say "- FAIL missing file: $CS"; exit 2
fi

# Replace/insert POSTCLOSE_GATES block near top (idempotent)
python3 - <<'PY'
from pathlib import Path
p=Path('/Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/close_stability_summary_603305.sh')
t=p.read_text(encoding='utf-8')
lines=t.splitlines(True)
ins = """
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

check_postclose_gates() {
  python3 - <<'PYY'
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
PYY "${POSTCLOSE_GATES[@]}"
}
"""

# find insertion point after DATE_YYYYMMDD line
out=[]
i=0
inserted=False
while i < len(lines):
    out.append(lines[i])
    if (not inserted) and 'DATE_YYYYMMDD=' in lines[i]:
        out.append(ins.lstrip('\n'))
        inserted=True
    i+=1

# remove legacy gate checks by deleting old names if present (best-effort)
legacy = [
  'postclose_603305_error_code_daily_1505',
  'postclose_603305_scorecard_daily_1508',
  'postclose_603305_sample_quality_1510',
  'postclose_603305_main_shadow_review_1512',
  'postclose_603305_factor_postclose_1515',
  'postclose_603305_strategy_param_proposal_1518',
  'postclose_603305_chatgpt_handoff_1520',
  'postclose_603305_regression_1525',
]
new = ''.join(out)
for s in legacy:
    new = new.replace(s, '')

# ensure gate check runs (non-blocking) for this script
if 'check_postclose_gates' in new and 'check_postclose_gates || true' not in new:
    # put it just before case statement
    new = new.replace('\ncase "close_stability_summary" in\n', '\n# gate check (read-only)\ncheck_postclose_gates || true\n\ncase "close_stability_summary" in\n')

p.write_text(new, encoding='utf-8')
print(str(p))
PY | tee -a "$OUT_SUMMARY" >/dev/null
say ""

say "## 3) 验证（不补跑历史）"

say "### 3.1 bash -n（postclose_pipeline wrappers）"
bash -n "$PIPE"/*.sh && say "- PASS bash -n" || { say "- FAIL bash -n"; exit 2; }

say "### 3.2 py_compile（新增 shim）"
python3 -m py_compile \
  "$SCRIPTS/slot_coverage_daily.py" \
  "$SCRIPTS/error_code_daily.py" \
  "$SCRIPTS/scorecard_daily.py" \
  "$SCRIPTS/sample_quality_daily.py" \
  "$SCRIPTS/main_shadow_review_603305.py" \
  "$SCRIPTS/strategy_param_proposal_603305.py" \
  && say "- PASS py_compile shims" || { say "- FAIL py_compile shims"; exit 2; }

say "### 3.3 grep：旧 gate 名称是否仍存在（应为 0）"
LEGACY_RE='postclose_603305_error_code_daily_1505|postclose_603305_scorecard_daily_1508|postclose_603305_sample_quality_1510|postclose_603305_main_shadow_review_1512|postclose_603305_factor_postclose_1515|postclose_603305_strategy_param_proposal_1518|postclose_603305_chatgpt_handoff_1520|postclose_603305_regression_1525'
HIT=$(grep -R -n -E "$LEGACY_RE" "$BASE/scripts" 2>/dev/null | head -n 5 || true)
if [[ -n "$HIT" ]]; then
  say "- FAIL legacy gate names still present (showing first hits):"
  say "\n$HIT\n"
  exit 2
else
  say "- PASS legacy gate names cleared in scripts/ (no hits)"
fi

say ""
say "## 输出"
say "- summary: $OUT_SUMMARY"

echo "$OUT_SUMMARY"
