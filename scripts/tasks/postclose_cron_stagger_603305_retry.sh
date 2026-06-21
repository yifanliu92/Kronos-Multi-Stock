#!/usr/bin/env bash
set -euo pipefail

# Retry: fix legacy self_audit stagger logic (do NOT require renamed job name).

TZ="Asia/Shanghai"
MODEL="openai-codex/gpt-5.2"
TO="736532132"
CHANNEL="telegram"
BASE="/Users/wxo/Desktop/Kronos"

echo "[TASK] postclose_cron_stagger_603305_retry start $(date '+%F %T')"

python3 - <<'PY' || exit 1
import json, subprocess

TZ='Asia/Shanghai'
MODEL='openai-codex/gpt-5.2'
TO='736532132'
CHANNEL='telegram'
BASE='/Users/wxo/Desktop/Kronos'

# Final desired schedules (minute staggering)
desired = {
  'postclose_603305_slot_coverage_1502': '2 15 * * 1-5',
  '603305_close_review': '5 15 * * 1-5',
  'postclose_603305_error_code_daily_1507': '7 15 * * 1-5',
  'postclose_603305_scorecard_daily_1510': '10 15 * * 1-5',
  # self_audit: accept either name; MUST be scheduled at 13 15
  'SELF_AUDIT_SCHEDULE': '13 15 * * 1-5',
  'postclose_603305_sample_quality_1516': '16 15 * * 1-5',
  'postclose_603305_main_shadow_review_1518': '18 15 * * 1-5',
  'postclose_603305_factor_postclose_1520': '20 15 * * 1-5',
  'postclose_603305_strategy_param_proposal_1522': '22 15 * * 1-5',
  'postclose_603305_chatgpt_handoff_1524': '24 15 * * 1-5',
  'postclose_603305_regression_1526': '26 15 * * 1-5',
  'postclose_603305_close_stability_summary_1528': '28 15 * * 1-5',
}

# Postclose cron renames (as before)
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
    if ('run_with_model_guard.sh' not in msg) and ('taskq_submit.sh' not in msg):
        raise SystemExit(f'VERIFY_FAIL_GUARD name={name}')
    delivery=j.get('delivery') or {}
    if delivery.get('bestEffort')!=True:
        raise SystemExit(f'VERIFY_FAIL_BESTEFFORT name={name} got={delivery.get("bestEffort")}')


def edit_job(jid: str, *, name=None, expr=None, message=None):
    cmd=['openclaw','cron','edit',jid,'--tz',TZ]
    if name:
        cmd += ['--name', name]
    if expr:
        cmd += ['--cron', expr]
    if message is not None:
        cmd += ['--session','isolated','--message',message,'--model',MODEL,'--announce','--channel',CHANNEL,'--to',TO,'--best-effort-deliver']
    rc,out,err=sh(cmd)
    if rc!=0:
        raise SystemExit(f'EDIT_FAILED jid={jid} rc={rc} err={err.strip()}')


jobs=list_jobs()

# 1) Rename/reschedule postclose jobs
for old, new in rename_map.items():
    if old not in jobs:
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
    edit_job(jid, name=new, expr=expr, message=message)
    verify(new, expr)

# refresh
jobs=list_jobs()

# 2) Self-audit stagger: locate legacy job name first, then reschedule.
# Accept either name if already renamed. Prefer old name.
self_candidates=['603305-self-audit-1510','603305-self-audit-1513']
self_name=None
for nm in self_candidates:
    if nm in jobs:
        self_name=nm
        break
if not self_name:
    raise SystemExit('MISSING_SELF_AUDIT none of candidates found')

jid=jobs[self_name].get('id') or jobs[self_name].get('jobId')
if not jid:
    raise SystemExit(f'NO_JOB_ID self_audit={self_name}')

# Keep name as-is by default; only change schedule to 15:13
edit_job(jid, expr=desired['SELF_AUDIT_SCHEDULE'])
# Verify by schedule (name-agnostic): re-fetch and check
jobs=list_jobs()
j=jobs.get(self_name)
if not j:
    raise SystemExit('VERIFY_FAIL_SELF_AUDIT_NOT_FOUND_AFTER_EDIT')
if not j.get('enabled'):
    raise SystemExit('VERIFY_FAIL_SELF_AUDIT_DISABLED')
sch=j.get('schedule') or {}
if sch.get('expr')!=desired['SELF_AUDIT_SCHEDULE'] or sch.get('tz')!=TZ:
    raise SystemExit(f'VERIFY_FAIL_SELF_AUDIT_SCHEDULE got={sch}')
payload=j.get('payload') or {}
if payload.get('model')!=MODEL:
    raise SystemExit(f'VERIFY_FAIL_SELF_AUDIT_MODEL got={payload.get("model")}')
msg = payload.get('message') or ''
    if ('run_with_model_guard.sh' not in msg) and ('taskq_submit.sh' not in msg):
    raise SystemExit('VERIFY_FAIL_SELF_AUDIT_GUARD')
delivery=j.get('delivery') or {}
if delivery.get('bestEffort')!=True:
    raise SystemExit('VERIFY_FAIL_SELF_AUDIT_BESTEFFORT')

# 3) Verify other required jobs exist and match desired schedule (including close_review)
verify('603305_close_review', desired['603305_close_review'])
for nm in [
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
]:
    if nm not in jobs:
        raise SystemExit(f'MISSING_POSTCLOSE_CRON name={nm}')
    verify(nm, desired[nm])

print('cron stagger edit+verify OK')
PY

# Patch regression to be schedule-based for self_audit name, and enforce concurrency/order gates
python3 - <<'PY'
from pathlib import Path

p=Path('/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh')
text=p.read_text(encoding='utf-8')
marker='postclose_cron_stagger_603305_retry gates'
if marker in text:
    print('regression already has retry stagger gates')
    raise SystemExit(0)

append = """

# --- postclose_cron_stagger_603305_retry gates ---
python3 - <<'PY2'
import json, subprocess
TZ='Asia/Shanghai'
MODEL='openai-codex/gpt-5.2'

# expected schedules (name->expr). self_audit is schedule-based, name-agnostic.
need={
 'postclose_603305_slot_coverage_1502':'2 15 * * 1-5',
 '603305_close_review':'5 15 * * 1-5',
 'postclose_603305_error_code_daily_1507':'7 15 * * 1-5',
 'postclose_603305_scorecard_daily_1510':'10 15 * * 1-5',
 'postclose_603305_sample_quality_1516':'16 15 * * 1-5',
 'postclose_603305_main_shadow_review_1518':'18 15 * * 1-5',
 'postclose_603305_factor_postclose_1520':'20 15 * * 1-5',
 'postclose_603305_strategy_param_proposal_1522':'22 15 * * 1-5',
 'postclose_603305_chatgpt_handoff_1524':'24 15 * * 1-5',
 'postclose_603305_regression_1526':'26 15 * * 1-5',
 'postclose_603305_close_stability_summary_1528':'28 15 * * 1-5',
}
self_audit_expr='13 15 * * 1-5'

cp=subprocess.run(['openclaw','cron','list','--json'],capture_output=True,text=True)
if cp.returncode!=0:
    print('FAIL [postclose stagger retry] cron list failed')
    raise SystemExit(0)
j=json.loads(cp.stdout)
jobs=j.get('jobs') or []
name2={x.get('name'):x for x in jobs if x.get('name')}

# 1) existence + property checks
for nm, expr in need.items():
    x=name2.get(nm)
    if not x:
        print(f'FAIL [postclose stagger retry] missing {nm}')
        continue
    if not x.get('enabled'):
        print(f'FAIL [postclose stagger retry] disabled {nm}')
    sch=x.get('schedule') or {}
    if sch.get('expr')!=expr or sch.get('tz')!=TZ:
        print(f'FAIL [postclose stagger retry] schedule mismatch {nm}')
    payload=x.get('payload') or {}
    if payload.get('model')!=MODEL:
        print(f'FAIL [postclose stagger retry] model mismatch {nm}')
    msg = payload.get('message') or ''
    if ('run_with_model_guard.sh' not in msg) and ('taskq_submit.sh' not in msg):
        print(f'FAIL [postclose stagger retry] guard missing {nm}')
    if not (x.get('delivery') or {}).get('bestEffort'):
        print(f'FAIL [postclose stagger retry] bestEffort missing {nm}')

# 2) self_audit schedule-based check (accept either name)
self_jobs=[x for x in jobs if x.get('name') in ('603305-self-audit-1510','603305-self-audit-1513')]
if not self_jobs:
    print('FAIL [postclose stagger retry] missing self_audit job')
else:
    sj=self_jobs[0]
    sch=sj.get('schedule') or {}
    if sch.get('expr')!=self_audit_expr or sch.get('tz')!=TZ:
        print('FAIL [postclose stagger retry] self_audit schedule mismatch')
    payload=sj.get('payload') or {}
    if payload.get('model')!=MODEL:
        print('FAIL [postclose stagger retry] self_audit model mismatch')
    msg = payload.get('message') or ''
    if ('run_with_model_guard.sh' not in msg) and ('taskq_submit.sh' not in msg):
        print('FAIL [postclose stagger retry] self_audit guard missing')
    if not (sj.get('delivery') or {}).get('bestEffort'):
        print('FAIL [postclose stagger retry] self_audit bestEffort missing')

# 3) concurrency check within 15:00-15:35 for selected jobs
minutes={}
for nm,expr in need.items():
    minutes.setdefault(int(expr.split()[0]),[]).append(nm)
minutes.setdefault(int(self_audit_expr.split()[0]),[]).append('self_audit')
conf=[(m,nms) for m,nms in minutes.items() if len(nms)>1 and m<=35]
if conf:
    print('FAIL [postclose stagger retry] concurrent minute', conf)
else:
    print('PASS [postclose stagger retry] no concurrent minute in 15:00-15:35')

# 4) order gates
if int('16')>int('13'):
    print('PASS [postclose stagger retry] sample_quality after self_audit')
else:
    print('FAIL [postclose stagger retry] sample_quality not after self_audit')
if int('22')>int('16'):
    print('PASS [postclose stagger retry] strategy_param_proposal after sample_quality')
else:
    print('FAIL [postclose stagger retry] strategy_param_proposal not after sample_quality')
PY2
"""

p.write_text(text+append, encoding='utf-8')
print('patched regression with retry stagger gates')
PY

echo "[TASK] postclose_cron_stagger_603305_retry done $(date '+%F %T')"
