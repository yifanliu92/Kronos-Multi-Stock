#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
TZ="Asia/Shanghai"
MODEL="openai-codex/gpt-5.5"
TO="736532132"
CHANNEL="telegram"

echo "[TASK] postclose_cron_stagger_603305 start $(date '+%F %T')"

python3 - <<'PY'
import json, subprocess

TZ='Asia/Shanghai'
MODEL='openai-codex/gpt-5.5'
TO='736532132'
CHANNEL='telegram'
BASE='/Users/wxo/Desktop/Kronos'

# desired schedule (name, expr)
desired = {
  'postclose_603305_slot_coverage_1502': '2 15 * * 1-5',
  '603305_close_review': '5 15 * * 1-5',
  'postclose_603305_error_code_daily_1507': '7 15 * * 1-5',
  'postclose_603305_scorecard_daily_1510': '10 15 * * 1-5',
  '603305-self-audit-1513': '13 15 * * 1-5',
  'postclose_603305_sample_quality_1516': '16 15 * * 1-5',
  'postclose_603305_main_shadow_review_1518': '18 15 * * 1-5',
  'postclose_603305_factor_postclose_1520': '20 15 * * 1-5',
  'postclose_603305_strategy_param_proposal_1522': '22 15 * * 1-5',
  'postclose_603305_chatgpt_handoff_1524': '24 15 * * 1-5',
  'postclose_603305_regression_1526': '26 15 * * 1-5',
  'postclose_603305_close_stability_summary_1528': '28 15 * * 1-5',
}

# mapping from old postclose names to new names (rename + reschedule)
rename_map = {
  'postclose_603305_error_code_daily_1505': 'postclose_603305_error_code_daily_1507',
  'postclose_603305_scorecard_daily_1508': 'postclose_603305_scorecard_daily_1510',
  'postclose_603305_sample_quality_1510': 'postclose_603305_sample_quality_1516',
  'postclose_603305_main_shadow_review_1512': 'postclose_603305_main_shadow_review_1518',
  'postclose_603305_factor_postclose_1515': 'postclose_603305_factor_postclose_1520',
  'postclose_603305_strategy_param_proposal_1518': 'postclose_603305_strategy_param_proposal_1522',
  'postclose_603305_chatgpt_handoff_1520': 'postclose_603305_chatgpt_handoff_1524',
  'postclose_603305_regression_1525': 'postclose_603305_regression_1526',
}

wrapper_for = {
  'postclose_603305_slot_coverage_1502': f"bash {BASE}/scripts/postclose_pipeline/slot_coverage_603305.sh",
  'postclose_603305_error_code_daily_1507': f"bash {BASE}/scripts/postclose_pipeline/error_code_daily_603305.sh",
  'postclose_603305_scorecard_daily_1510': f"bash {BASE}/scripts/postclose_pipeline/scorecard_daily_603305.sh",
  'postclose_603305_sample_quality_1516': f"bash {BASE}/scripts/postclose_pipeline/sample_quality_603305.sh",
  'postclose_603305_main_shadow_review_1518': f"bash {BASE}/scripts/postclose_pipeline/main_shadow_review_603305.sh",
  'postclose_603305_factor_postclose_1520': f"bash {BASE}/scripts/postclose_pipeline/factor_postclose_603305.sh",
  'postclose_603305_strategy_param_proposal_1522': f"bash {BASE}/scripts/postclose_pipeline/strategy_param_proposal_603305.sh",
  'postclose_603305_chatgpt_handoff_1524': f"bash {BASE}/scripts/postclose_pipeline/chatgpt_handoff_603305.sh",
  'postclose_603305_regression_1526': f"bash {BASE}/scripts/postclose_pipeline/regression_603305.sh",
  'postclose_603305_close_stability_summary_1528': f"bash {BASE}/scripts/postclose_pipeline/close_stability_summary_603305.sh",
}


def sh(cmd):
    cp=subprocess.run(cmd, capture_output=True, text=True)
    return cp.returncode, (cp.stdout or ''), (cp.stderr or '')


def list_jobs():
    rc,out,err=sh(['openclaw','cron','list','--json'])
    if rc!=0:
        raise SystemExit(f'CRON_LIST_FAILED rc={rc} err={err.strip()}')
    j=json.loads(out)
    jobs=j.get('jobs') or []
    return {x.get('name'): x for x in jobs if x.get('name')}


def verify(name, expr_expected):
    m=list_jobs()
    j=m.get(name)
    if not j:
        raise SystemExit(f'VERIFY_FAIL_NOT_FOUND name={name}')
    if not j.get('enabled'):
        raise SystemExit(f'VERIFY_FAIL_DISABLED name={name}')
    sch=j.get('schedule') or {}
    if sch.get('kind')!='cron' or sch.get('expr')!=expr_expected or sch.get('tz')!=TZ:
        raise SystemExit(f'VERIFY_FAIL_SCHEDULE name={name} got={sch}')
    payload=j.get('payload') or {}
    if payload.get('model')!=MODEL:
        raise SystemExit(f'VERIFY_FAIL_MODEL name={name} got={payload.get("model")}')
    msg=(payload.get('message') or '')
    if 'run_with_model_guard.sh' not in msg:
        raise SystemExit(f'VERIFY_FAIL_GUARD name={name}')
    delivery=j.get('delivery') or {}
    if delivery.get('bestEffort')!=True:
        raise SystemExit(f'VERIFY_FAIL_BESTEFFORT name={name} got={delivery.get("bestEffort")}')


jobs=list_jobs()

# 1) rename + reschedule postclose jobs
for old, new in rename_map.items():
    if old not in jobs:
        # if already renamed, skip
        continue
    jid=jobs[old].get('id') or jobs[old].get('jobId')
    if not jid:
        raise SystemExit(f'NO_JOB_ID old={old}')
    expr=desired[new]
    cmd=wrapper_for[new]
    message=(
        f"立即执行并仅返回结果：bash {BASE}/scripts/run_with_model_guard.sh --task-name {new} --jobId {new} "
        f"--model \"${{OPENCLAW_MODEL:-${{MODEL:-}}}}\" --provider \"${{OPENCLAW_PROVIDER:-${{PROVIDER:-}}}}\" -- {cmd}"
    )
    rc,out,err=sh([
        'openclaw','cron','edit',jid,
        '--name',new,
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
        raise SystemExit(f'EDIT_FAILED old={old} new={new} rc={rc} err={err.strip()}')
    verify(new, expr)

# refresh
jobs=list_jobs()

# 2) ensure static ones: slot_coverage / close_stability_summary already exist; if missing, fail (we do not create new here)
required_postclose=[
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
for nm in required_postclose:
    if nm not in jobs:
        raise SystemExit(f'MISSING_POSTCLOSE_CRON name={nm}')
    verify(nm, desired[nm])

# 3) reschedule legacy jobs
for legacy, expr in [('603305_close_review', desired['603305_close_review']), ('603305-self-audit-1513', desired['603305-self-audit-1513'])]:
    j=jobs.get(legacy)
    if not j:
        raise SystemExit(f'MISSING_LEGACY name={legacy}')
    jid=j.get('id') or j.get('jobId')
    if not jid:
        raise SystemExit(f'NO_JOB_ID legacy={legacy}')
    # keep payload untouched except schedule/name already same; just edit schedule
    rc,out,err=sh(['openclaw','cron','edit',jid,'--cron',expr,'--tz',TZ])
    if rc!=0:
        raise SystemExit(f'EDIT_FAILED legacy={legacy} rc={rc} err={err.strip()}')

print('cron stagger edit+verify OK')
PY

# Update regression gates (textual + schedule ordering checks)
python3 - <<'PY'
from pathlib import Path

p=Path('/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh')
text=p.read_text(encoding='utf-8')
marker='postclose_cron_stagger_603305 gates'
if marker in text:
    print('regression already has stagger gates')
    raise SystemExit(0)

append = """

# --- postclose_cron_stagger_603305 gates ---
python3 - <<'PY2'
import json, subprocess

need={
 'postclose_603305_slot_coverage_1502':'2 15 * * 1-5',
 'postclose_603305_error_code_daily_1507':'7 15 * * 1-5',
 'postclose_603305_scorecard_daily_1510':'10 15 * * 1-5',
 'postclose_603305_sample_quality_1516':'16 15 * * 1-5',
 'postclose_603305_main_shadow_review_1518':'18 15 * * 1-5',
 'postclose_603305_factor_postclose_1520':'20 15 * * 1-5',
 'postclose_603305_strategy_param_proposal_1522':'22 15 * * 1-5',
 'postclose_603305_chatgpt_handoff_1524':'24 15 * * 1-5',
 'postclose_603305_regression_1526':'26 15 * * 1-5',
 'postclose_603305_close_stability_summary_1528':'28 15 * * 1-5',
 '603305_close_review':'5 15 * * 1-5',
 '603305-self-audit-1513':'13 15 * * 1-5',
}

cp=subprocess.run(['openclaw','cron','list','--json'],capture_output=True,text=True)
if cp.returncode!=0:
    print('FAIL [postclose stagger] cron list failed')
    raise SystemExit(0)
j=json.loads(cp.stdout)
jobs=[x for x in (j.get('jobs') or []) if x.get('name') in need]
name2={x['name']:x for x in jobs}
# existence + minute uniqueness check for 15:00-15:35 window
minutes={}
for nm, expr in need.items():
    x=name2.get(nm)
    if not x:
        print(f'FAIL [postclose stagger] missing {nm}')
        continue
    sch=x.get('schedule') or {}
    if sch.get('expr')!=expr or sch.get('tz')!='Asia/Shanghai':
        print(f'FAIL [postclose stagger] schedule mismatch {nm}')
    minute=int(expr.split()[0])
    minutes.setdefault(minute,[]).append(nm)

conf=[(m,nms) for m,nms in minutes.items() if len(nms)>1 and m<=35]
if conf:
    print('FAIL [postclose stagger] concurrent minute', conf)
else:
    print('PASS [postclose stagger] no concurrent minute in 15:00-15:35')

# ordering gates: sample_quality after self_audit; strategy_param_proposal after sample_quality
order={'603305-self-audit-1513':13,'postclose_603305_sample_quality_1516':16,'postclose_603305_strategy_param_proposal_1522':22}
if order['postclose_603305_sample_quality_1516']>order['603305-self-audit-1513']:
    print('PASS [postclose stagger] sample_quality after self_audit')
else:
    print('FAIL [postclose stagger] sample_quality not after self_audit')
if order['postclose_603305_strategy_param_proposal_1522']>order['postclose_603305_sample_quality_1516']:
    print('PASS [postclose stagger] strategy_param_proposal after sample_quality')
else:
    print('FAIL [postclose stagger] strategy_param_proposal not after sample_quality')
PY2
"""

p.write_text(text+append, encoding='utf-8')
print('patched regression with stagger gates')
PY

echo "[TASK] postclose_cron_stagger_603305 done $(date '+%F %T')"
