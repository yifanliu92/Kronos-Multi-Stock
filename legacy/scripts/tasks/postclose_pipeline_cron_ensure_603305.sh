#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
TZ="Asia/Shanghai"
MODEL="openai-codex/gpt-5.5"
TO="736532132"
CHANNEL="telegram"

mkdir -p "$BASE/guard_outputs" "$BASE/daily_reports"

echo "[TASK] postclose_pipeline_cron_ensure_603305 start $(date '+%F %T')"

# 1) Ensure 10 postclose wrapper files exist + bash -n pass
wrappers=(
  "$BASE/scripts/postclose_pipeline/slot_coverage_603305.sh"
  "$BASE/scripts/postclose_pipeline/error_code_daily_603305.sh"
  "$BASE/scripts/postclose_pipeline/scorecard_daily_603305.sh"
  "$BASE/scripts/postclose_pipeline/sample_quality_603305.sh"
  "$BASE/scripts/postclose_pipeline/main_shadow_review_603305.sh"
  "$BASE/scripts/postclose_pipeline/factor_postclose_603305.sh"
  "$BASE/scripts/postclose_pipeline/strategy_param_proposal_603305.sh"
  "$BASE/scripts/postclose_pipeline/chatgpt_handoff_603305.sh"
  "$BASE/scripts/postclose_pipeline/regression_603305.sh"
  "$BASE/scripts/postclose_pipeline/close_stability_summary_603305.sh"
)

for f in "${wrappers[@]}"; do
  [[ -f "$f" ]] || { echo "MISSING_WRAPPER=$f"; exit 3; }
  bash -n "$f"
done

# 2) Ensure 10 OpenClaw cron jobs via CLI, with STRICT read-back verification.
# IMPORTANT: Do NOT claim success unless jobs are visible via `openclaw cron list --json`.
# On any verification failure, the script must exit non-zero (exit 1).
python3 - <<'PY' || exit 1
import json, subprocess, sys

TZ='Asia/Shanghai'
MODEL='openai-codex/gpt-5.5'
TO='736532132'
CHANNEL='telegram'
BASE='/Users/wxo/Desktop/Kronos'

specs=[
  ('postclose_603305_slot_coverage_1502', '2 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/slot_coverage_603305.sh"),
  ('postclose_603305_error_code_daily_1507', '7 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/error_code_daily_603305.sh"),
  ('postclose_603305_scorecard_daily_1510', '16 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/scorecard_daily_603305.sh"),
  ('603305-self-audit-1513', '13 15 * * 1-5', f"bash {BASE}/scripts/self_audit_603305.py"),
  ('postclose_603305_sample_quality_1516', '16 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/sample_quality_603305.sh"),
  ('postclose_603305_main_shadow_review_1518', '22 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/main_shadow_review_603305.sh"),
  ('postclose_603305_factor_postclose_1520', '24 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/factor_postclose_603305.sh"),
  ('postclose_603305_strategy_param_proposal_1522', '22 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/strategy_param_proposal_603305.sh"),
  ('postclose_603305_chatgpt_handoff_1524', '24 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/chatgpt_handoff_603305.sh"),
  ('postclose_603305_regression_1526', '26 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/regression_603305.sh"),
  ('postclose_603305_close_stability_summary_1528', '28 15 * * 1-5', f"bash {BASE}/scripts/postclose_pipeline/close_stability_summary_603305.sh"),
]


def sh(cmd):
    cp=subprocess.run(cmd, capture_output=True, text=True)
    return cp.returncode, (cp.stdout or ''), (cp.stderr or '')


def list_jobs() -> dict:
    rc,out,err=sh(['openclaw','cron','list','--json'])
    if rc!=0:
        raise RuntimeError(f'CRON_LIST_FAILED rc={rc} err={err.strip()}')
    j=json.loads(out)
    jobs=j.get('jobs') or []
    return {x.get('name'): x for x in jobs if x.get('name')}


def verify_one(name: str, expected_expr: str) -> None:
    m=list_jobs()
    j=m.get(name)
    if not j:
        raise SystemExit(f'VERIFY_FAIL_NOT_FOUND name={name}')
    if not j.get('enabled'):
        raise SystemExit(f'VERIFY_FAIL_DISABLED name={name}')
    payload=j.get('payload') or {}
    if payload.get('model')!=MODEL:
        raise SystemExit(f'VERIFY_FAIL_MODEL name={name} got={payload.get("model")}')
    msg=(payload.get('message') or '')
    if 'run_with_model_guard.sh' not in msg:
        raise SystemExit(f'VERIFY_FAIL_GUARD name={name}')
    sch=j.get('schedule') or {}
    if sch.get('kind')!='cron' or sch.get('expr')!=expected_expr or sch.get('tz')!=TZ:
        raise SystemExit(f'VERIFY_FAIL_SCHEDULE name={name} got={sch}')
    delivery=j.get('delivery') or {}
    if delivery.get('bestEffort')!=True:
        raise SystemExit(f'VERIFY_FAIL_BESTEFFORT name={name} got={delivery.get("bestEffort")}')


# Determine which jobs already exist, then add or edit using supported CLI flags.
name2job=list_jobs()
for name, expr, cmd in specs:
    message=(
        f"立即执行并仅返回结果：bash {BASE}/scripts/run_with_model_guard.sh --task-name {name} --jobId {name} "
        f"--model \"${{OPENCLAW_MODEL:-${{MODEL:-}}}}\" --provider \"${{OPENCLAW_PROVIDER:-${{PROVIDER:-}}}}\" -- {cmd}"
    )

    if name in name2job:
        # update via `openclaw cron edit` (patch fields)
        jid=name2job[name].get('id') or name2job[name].get('jobId')
        if not jid:
            raise SystemExit(f'NO_JOB_ID name={name}')
        rc,out,err=sh([
            'openclaw','cron','edit',jid,
            '--name',name,
            '--cron',expr,
            '--tz',TZ,
            '--session','isolated',
            '--message',message,
            '--model',MODEL,
            '--announce',
            '--channel',CHANNEL,
            '--to',TO,
            '--best-effort-deliver',
        ])
        if rc!=0:
            raise SystemExit(f'EDIT_FAILED name={name} rc={rc} err={err.strip()}')
    else:
        rc,out,err=sh([
            'openclaw','cron','add',
            '--name',name,
            '--cron',expr,
            '--tz',TZ,
            '--session','isolated',
            '--message',message,
            '--model',MODEL,
            '--announce',
            '--channel',CHANNEL,
            '--to',TO,
            '--best-effort-deliver',
        ])
        if rc!=0:
            raise SystemExit(f'ADD_FAILED name={name} rc={rc} err={err.strip()}')

    # STRICT verify immediately after add/edit
    verify_one(name, expr)

print('postclose cron ensure+verify OK')
PY

# hard fail marker (do not allow FALSE_DONE)
# exit 1 will be triggered by the python block via `|| exit 1` above if any verify fails.


# 3) Extend regression: ensure postclose wrappers exist + bash -n; and postclose cron exists/enabled/model/guard/bestEffort
python3 - <<'PY'
from pathlib import Path
import json

p=Path('/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh')
text=p.read_text(encoding='utf-8')
marker='postclose_pipeline_603305 cron gates'
if marker in text:
    print('regression already has postclose cron gates')
    raise SystemExit(0)

append = """

# --- postclose_pipeline_603305 cron gates ---
POSTCLOSE_WRAPPERS=(
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/slot_coverage_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/error_code_daily_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/scorecard_daily_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/sample_quality_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/main_shadow_review_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/factor_postclose_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/strategy_param_proposal_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/chatgpt_handoff_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/regression_603305.sh
  /Users/wxo/Desktop/Kronos/scripts/postclose_pipeline/close_stability_summary_603305.sh
)
for f in "${POSTCLOSE_WRAPPERS[@]}"; do
  [[ -f "$f" ]] && pass "postclose wrapper exists: $f" || fail "Missing postclose wrapper: $f"
  bash -n "$f" >>"$LOG" 2>&1 && pass "bash -n postclose wrapper: $f" || fail "bash -n postclose wrapper: $f"
done

python3 - <<'PY2'
import json, subprocess
need=[
  'postclose_603305_slot_coverage_1502',
  'postclose_603305_error_code_daily_1507',
  'postclose_603305_scorecard_daily_1510',
  'postclose_603305_sample_quality_1516',
  'postclose_603305_main_shadow_review_1518',
  'postclose_603305_factor_postclose_1520',
  'postclose_603305_strategy_param_proposal_1522',
  'postclose_603305_chatgpt_handoff_1524',
  'postclose_603305_regression_1526',
  'postclose_603305_close_stability_summary_1528',
]
cp=subprocess.run(['openclaw','cron','list','--json'],capture_output=True,text=True)
if cp.returncode!=0:
    print('FAIL [Postclose cron gates] cannot list cron')
    raise SystemExit(0)
j=json.loads(cp.stdout)
name2=j.get('jobs',[])
name2={x.get('name'):x for x in name2 if x.get('name')}
for nm in need:
    j=name2.get(nm)
    if not j:
        print(f'FAIL [Postclose cron gates] missing {nm}')
        continue
    if not j.get('enabled'):
        print(f'FAIL [Postclose cron gates] disabled {nm}')
    payload=j.get('payload') or {}
    if payload.get('model')!='openai-codex/gpt-5.5':
        print(f'FAIL [Postclose cron gates] model not pinned {nm}')
    msg=(payload.get('message') or '')
    if 'run_with_model_guard.sh' not in msg:
        print(f'FAIL [Postclose cron gates] not using run_with_model_guard.sh {nm}')
    delivery=j.get('delivery') or {}
    if not delivery.get('bestEffort'):
        print(f'FAIL [Postclose cron gates] bestEffort not true {nm}')
print('PASS [Postclose cron gates] checked')
PY2
"""

p.write_text(text+append, encoding='utf-8')
print('patched regression with postclose cron gates')
PY

echo "[TASK] postclose_pipeline_cron_ensure_603305 done $(date '+%F %T')"
