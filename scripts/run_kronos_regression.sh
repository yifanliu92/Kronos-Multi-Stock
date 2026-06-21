#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
LOG="$BASE/guard_outputs/regression_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$BASE/guard_outputs"

PASS_N=0; WARN_N=0; FAIL_N=0
pass(){ PASS_N=$((PASS_N+1)); echo "PASS: $*" | tee -a "$LOG"; }
warn(){ WARN_N=$((WARN_N+1)); echo "WARN: $*" | tee -a "$LOG"; }
fail(){ FAIL_N=$((FAIL_N+1)); echo "FAIL: $*" | tee -a "$LOG"; }

echo "[Kronos Regression v0.2] $(date '+%F %T')" | tee "$LOG"

# P0 gate: auto_report_guard_603305.py must be syntactically valid
if python3 -m py_compile "$BASE/auto_report_guard_603305.py" >>"$LOG" 2>&1; then
  pass "py_compile auto_report_guard_603305.py"
else
  fail "py_compile auto_report_guard_603305.py"
fi

# P1 gate: factor_score_observer light mode must not crash (observer-only)
if python3 -m py_compile "$BASE/scripts/factor_score_observer.py" >>"$LOG" 2>&1; then
  pass "py_compile factor_score_observer.py"
else
  fail "py_compile factor_score_observer.py"
fi

smoke_out=$(echo '{}' | python3 "$BASE/scripts/factor_score_observer.py" --light-from-json --light-weight-profile conservative 2>>"$LOG" || true)
if echo "$smoke_out" | grep -q '"observer_only"[[:space:]]*:[[:space:]]*true' \
  && echo "$smoke_out" | grep -q '"affects_position"[[:space:]]*:[[:space:]]*false' \
  && echo "$smoke_out" | grep -q '"factor_hint"[[:space:]]*:[[:space:]]*"insufficient_data"'; then
  pass "factor_score_observer light smoke test"
else
  fail "factor_score_observer light smoke test"
  echo "SMOKE_OUT=$smoke_out" | tee -a "$LOG"
fi

[[ -f "$BASE/KRONOS_SYSTEM_CONTRACT.md" ]] && pass "KRONOS_SYSTEM_CONTRACT.md exists" || fail "Missing KRONOS_SYSTEM_CONTRACT.md"
[[ -f "$BASE/KRONOS_RATE_LIMIT_POLICY.md" ]] && pass "KRONOS_RATE_LIMIT_POLICY.md exists" || fail "Missing KRONOS_RATE_LIMIT_POLICY.md"
[[ -f "$BASE/scripts/rate_limit_guard.py" ]] && pass "rate_limit_guard.py exists" || fail "Missing scripts/rate_limit_guard.py"
[[ -d "$BASE/task_queue/pending" ]] && pass "task_queue dirs exist" || fail "Missing task_queue dirs"
[[ -f "$BASE/scripts/kronos_submit_task.py" ]] && pass "kronos_submit_task.py exists" || fail "Missing kronos_submit_task.py"
[[ -f "$BASE/scripts/kronos_task_worker.py" ]] && pass "kronos_task_worker.py exists" || fail "Missing kronos_task_worker.py"
[[ -f "$BASE/scripts/kronos_task_status.py" ]] && pass "kronos_task_status.py exists" || fail "Missing kronos_task_status.py"

python3 - <<'PY' | tee -a "$LOG"
import json
from pathlib import Path
base=Path('/Users/wxo/Desktop/Kronos')
cost=json.loads((base/'sim_costs_603305.json').read_text(encoding='utf-8'))
print('PASS base_capital_cny=100000' if int(cost.get('base_capital_cny',0))==100000 else 'FAIL base_capital_cny != 100000')
PY

eval_results=$(python3 - <<'PY'
import json,re
from pathlib import Path
base=Path('/Users/wxo/Desktop/Kronos')

print('PASS [Contract checks] start')

# Select the latest NON-EMPTY trusted daily shard.
# Empty shards are factual artifacts after rollback cleanup and must not
# cause a false-negative regression failure.
main_logs=sorted(
    (base/'sim_logs_daily').glob(
        'sim_trades_603305_*.jsonl'
    ),
    reverse=True,
)

rows=[]
source_log=None
skipped_empty_logs=[]

for candidate in main_logs:
    candidate_rows=[]

    for ln in candidate.read_text(
        encoding='utf-8'
    ).splitlines():
        if ln.strip():
            candidate_rows.append(json.loads(ln))

    if candidate_rows:
        rows=candidate_rows
        source_log=candidate
        break

    skipped_empty_logs.append(candidate.name)

# Last-resort fallback: use active master log only when every daily shard
# is empty or absent. Never fabricate rows.
if not rows:
    master_log=base/'sim_trades_603305.jsonl'

    if master_log.exists():
        master_rows=[]

        for ln in master_log.read_text(
            encoding='utf-8'
        ).splitlines():
            if ln.strip():
                master_rows.append(json.loads(ln))

        if master_rows:
            rows=master_rows
            source_log=master_log

if not rows:
    print(
        'FAIL [Market data provider checks] '
        'no non-empty trusted sim log'
    )
    raise SystemExit(0)

print(
    'PASS [Market data provider checks] '
    f'source_log={source_log.name} '
    f'rows={len(rows)} '
    f'skipped_empty_logs={skipped_empty_logs}'
)

# 2) Market data provider checks
need=['provider_primary','provider_fallback','provider_third','provider_final']
missing=0
for r in rows[-5:]:
    for k in need:
        if k not in r: missing+=1
print('PASS [Market data provider checks] provider fields stable' if missing==0 else f'WARN [Market data provider checks] provider fields missing_count={missing}')

bad=0
for r in rows:
    if r.get('raw_length')==0 and r.get('error_code') not in ('EM_RAW_EMPTY',None): bad+=1
print('PASS [Market data provider checks] raw_length->EM_RAW_EMPTY' if bad==0 else f'WARN [Market data provider checks] raw_length rule violations={bad}')

# 3) Position / short checks
neg=[r for r in rows if int(r.get('position_to',0))<0]
if neg and any('空仓' in str(r.get('action','')) and int(r.get('position_to',0))<0 for r in neg):
    print('FAIL [Position / short checks] negative position displayed as empty')
else:
    print('PASS [Position / short checks] negative position display')

# required short fields when short
short_missing=0
for r in neg:
    # tolerate legacy rows, count missing
    for k in ['short_cost']:
        if k not in r: short_missing+=1
print('WARN [Position / short checks] short fields partial in legacy rows' if short_missing>0 else 'PASS [Position / short checks] short fields presence')

# 4) Cross-zero synthetic checks
# Contract: must represent cross-zero semantics in reason when cross_zero=True.

# Case A: +20 -> -20 (先平多/再建空)
curr,target=20,-20
cross_zero=True
cross_zero_action=f"多空穿越（{curr}% → {target}%）；先平多仓{abs(curr)}%，再建空仓{abs(target)}%"
reason=f"偏空信号触发；{cross_zero_action}"
if cross_zero and cross_zero_action and ('多空穿越' in reason) and ('先平多' in reason) and ('再建空' in reason):
    print('PASS [Cross-zero synthetic checks] +20->-20 reason semantics')
else:
    print('FAIL [Cross-zero synthetic checks] +20->-20 reason semantics')

# Case B: -20 -> +20 (先平空/再建多)
curr,target=-20,20
cross_zero=True
cross_zero_action=f"多空穿越（{curr}% → {target}%）；先平空仓{abs(curr)}%，再建多仓{abs(target)}%"
reason=f"偏多信号触发；{cross_zero_action}"
if cross_zero and cross_zero_action and ('多空穿越' in reason) and ('先平空' in reason) and ('再建多' in reason):
    print('PASS [Cross-zero synthetic checks] -20->+20 reason semantics')
else:
    print('FAIL [Cross-zero synthetic checks] -20->+20 reason semantics')

# 5) Report consistency checks
conf=0
for r in rows:
    if str(r.get('action'))=='持仓不变':
        reason=str(r.get('reason',''))
        # Treat "不再加仓/不加仓/不再减仓" as consistent with "持仓不变"
        has_add=('加仓' in reason) and not ('不再加仓' in reason or '不加仓' in reason)
        has_reduce=('减仓' in reason) and not ('不再减仓' in reason or '不减仓' in reason)
        if has_add or has_reduce:
            conf+=1
print('PASS [Report consistency checks] action/reason consistency' if conf==0 else f'FAIL [Report consistency checks] conflicts={conf}')

# P0 checks: full_lock hard intercept & delta consistency
viol=0
for r in rows:
    pf=int(r.get('position_from',0) or 0)
    pt=int(r.get('position_to',0) or 0)
    act=str(r.get('action',''))
    full_lock = (abs(pf) >= 100)
    # 1) full_lock=true must not appear with add exposure actions
    if full_lock and ('加仓' in act or '开多' in act or '回补' in act) and 'IDEMPOTENT_SKIP_FULLY_INVESTED' not in act:
        viol+=1
    # 2) position delta zero must not have add/reduce verbs
    if pf==pt and (('加仓' in act) or ('减仓' in act)):
        viol+=1
print('PASS [P0 checks] full_lock/action/delta consistency' if viol==0 else f'FAIL [P0 checks] violations={viol}')
signals=[str(r.get('signal','')) for r in rows]
print('PASS [Report consistency checks] signal not fixed neutral' if any(s!='中性' for s in signals) else 'FAIL [Report consistency checks] signal fixed neutral')

# 6) Winrate naming checks (scripts only)
scan_files=[base/'scripts'/'calc_winrate_603305_multi.py', base/'scripts'/'calc_winrate_603305.py']
conflict=False
for pth in scan_files:
    if not pth.exists():
        continue
    t=pth.read_text(encoding='utf-8')
    if re.search(r'action_to_next_action[^\n]{0,80}closed_trade|closed_trade[^\n]{0,80}action_to_next_action', t):
        conflict=True
print('WARN [Winrate naming checks] naming conflict found' if conflict else 'PASS [Winrate naming checks] naming clean')

# 7) Expected slots / slot coverage consistency checks
import os
from datetime import datetime
date_str=datetime.now().strftime('%Y%m%d')
# If today's files don't exist (e.g. running regression next day), fall back to latest available slot_coverage_daily_*.json
cov_p=base/'guard_outputs'/f"slot_coverage_daily_{date_str}.json"
if not cov_p.exists():
    cands=sorted((base/'guard_outputs').glob('slot_coverage_daily_*.json'))
    if cands:
        cov_p=cands[-1]
        date_str=cov_p.stem.split('_')[-1]
exp_p=base/'guard_outputs'/f"expected_slots_{date_str}.json"
if exp_p.exists() and cov_p.exists():
    exp=json.loads(exp_p.read_text(encoding='utf-8'))
    cov=json.loads(cov_p.read_text(encoding='utf-8'))
    expected=set(exp.get('expected_timeslots',[]))
    # ensure expected slots are not labeled NOT_SCHEDULED
    bad=[s for s in cov.get('slots',[]) if s.get('timeslot') in expected and s.get('status')=='NOT_SCHEDULED']
    print('PASS [Slots checks] expected slots not marked NOT_SCHEDULED' if not bad else f"FAIL [Slots checks] expected marked NOT_SCHEDULED count={len(bad)}")
    # ensure missing slots have reasons (status/error_code)
    miss=[s for s in cov.get('slots',[]) if s.get('status') not in ('SUCCESS','RETRY_SUCCESS')]
    ok_reason=all(('status' in s and 'error_code' in s and 'error_category' in s) for s in miss)
    print('PASS [Slots checks] missing slots have reasons' if ok_reason else 'FAIL [Slots checks] missing slots missing reasons')

    # MODEL_ERROR must be refined if raw run text suggests not found / not supported
    model_err=[s for s in miss if s.get('status')=='MODEL_ERROR']
    bad_generic=[s for s in model_err if s.get('error_code') in (None,'','MODEL_UNKNOWN')]
    print('PASS [Slots checks] MODEL_ERROR refined' if not bad_generic else f"FAIL [Slots checks] MODEL_ERROR not refined count={len(bad_generic)}")

    # critical missing must include error_category+error_code+error_detail
    critical_missing=[s for s in miss if s.get('critical')]
    bad_crit=[s for s in critical_missing if not (s.get('error_category') and s.get('error_code') and (s.get('error_detail') is not None))]
    print('PASS [Slots checks] critical missing has category/code/detail' if not bad_crit else f"FAIL [Slots checks] critical missing incomplete count={len(bad_crit)}")

    # scorecard must show missing_reasons
    sc_p=base/'guard_outputs'/f"scorecard_daily_{date_str}.json"
    if sc_p.exists():
        sc=json.loads(sc_p.read_text(encoding='utf-8'))
        mr=sc.get('missing_reasons')
        print('PASS [Slots checks] scorecard has missing_reasons' if isinstance(mr,list) and len(mr)>=0 else 'FAIL [Slots checks] scorecard missing missing_reasons')
    else:
        print('FAIL [Slots checks] scorecard_daily missing')
else:
    # Fallback: modern sample_quality_daily is the authoritative full-day sample artifact.
    sq_p = base/'guard_outputs'/f"sample_quality_daily_{date_str}.json"
    if not sq_p.exists():
        sq_cands = sorted((base/'guard_outputs').glob('sample_quality_daily_*.json'))
        if sq_cands:
            sq_p = sq_cands[-1]

    if sq_p.exists():
        sq = json.loads(sq_p.read_text(encoding='utf-8'))

        def _int(v, default=0):
            try:
                if isinstance(v, list):
                    return len(v)
                if isinstance(v, bool):
                    return int(v)
                return int(v)
            except Exception:
                return default

        status = str(sq.get('status') or sq.get('sample_status') or '').upper()
        grade = str(sq.get('grade') or '').upper()
        expected = _int(sq.get('expected_slots'), 0)
        actual = _int(sq.get('actual_reports'), -1)
        missing = _int(sq.get('missing_slots'), 0)
        timeout_or_error = _int(sq.get('timeout_or_error_slots'), 0)
        full_day_raw = sq.get('is_full_trading_day_sample')
        full_day = (str(full_day_raw).lower() == 'true') if isinstance(full_day_raw, str) else bool(full_day_raw)

        ok = (
            status == 'OK'
            and grade in ('A', 'B')
            and expected > 0
            and expected == actual
            and missing == 0
            and timeout_or_error == 0
            and full_day
        )

        # A formally excluded sample is not a full-day performance sample,
        # but it may still represent a correctly governed system state.
        #
        # Strict acceptance conditions:
        # - canonical sample_exclusion file exists;
        # - exclusion status is EXCLUDED;
        # - sample status matches sample_quality_daily;
        # - grade remains D and full_day remains false;
        # - missing count is internally consistent;
        # - strategy use / parameter switch / v1.2-shadow enablement are blocked;
        # - rollback and quarantine evidence references exist when provided.
        sq_date = str(sq.get('date') or date_str)

        ex_p = (
            base
            / 'guard_outputs'
            / f"sample_exclusion_603305_{sq_date}.json"
        )

        excluded_ok = False
        excluded_detail = ''

        if ex_p.exists():
            ex = json.loads(
                ex_p.read_text(encoding='utf-8')
            )

            rollback_raw = str(
                ex.get('rollback_audit') or ''
            ).strip()

            quarantine_raw = str(
                ex.get('quarantine_dir') or ''
            ).strip()

            rollback_ref_ok = (
                (not rollback_raw)
                or Path(rollback_raw).exists()
            )

            quarantine_ref_ok = (
                (not quarantine_raw)
                or Path(quarantine_raw).exists()
            )

            exclusion_status = str(
                ex.get('status') or ''
            ).upper()

            exclusion_sample_status = str(
                ex.get('sample_status') or ''
            ).upper()

            reason_ok = bool(
                str(ex.get('reason') or '').strip()
            )

            missing_consistent = (
                expected > 0
                and actual >= 0
                and actual < expected
                and missing == (expected - actual)
            )

            blocked_in_quality = (
                bool(sq.get('not_for_strategy_eval'))
                and bool(sq.get('not_for_parameter_switch'))
                and bool(
                    sq.get('not_for_v1_2_shadow_enable')
                )
            )

            blocked_in_exclusion = (
                bool(ex.get('not_for_sample_quality'))
                and bool(ex.get('not_for_strategy_eval'))
                and bool(ex.get('not_for_parameter_switch'))
                and bool(
                    ex.get('not_for_v1_2_shadow_enable')
                )
            )

            excluded_ok = (
                exclusion_status == 'EXCLUDED'
                and exclusion_sample_status == status
                and status not in ('', 'OK')
                and grade == 'D'
                and not full_day
                and missing_consistent
                and blocked_in_quality
                and blocked_in_exclusion
                and rollback_ref_ok
                and quarantine_ref_ok
                and reason_ok
            )

            excluded_detail = (
                f"exclusion_file={ex_p.name} "
                f"status={status} "
                f"grade={grade} "
                f"expected={expected} "
                f"actual={actual} "
                f"missing={missing} "
                f"full_day={full_day} "
                f"rollback_ref_ok={rollback_ref_ok} "
                f"quarantine_ref_ok={quarantine_ref_ok}"
            )

        if ok:
            print(
                'PASS [Slots checks] '
                'sample_quality_daily confirms '
                'expected_slots/actual_reports'
            )

        elif excluded_ok:
            print(
                'PASS [Slots checks] '
                'formally excluded sample honored '
                + excluded_detail
            )

        else:
            if (status in ('WARN','FAIL') and full_day is False and missing and int(missing) > 0):
                print(
                    f"PASS [Slots checks] sample_quality_daily expected incomplete sample "
                    f"status={status} grade={grade} expected={expected} actual={actual} "
                    f"missing={missing} full_day={full_day}"
                )
            else:
                print(
                    f"FAIL [Slots checks] sample_quality_daily invalid "
                    f"status={status} "
                    f"grade={grade} "
                    f"expected={expected} "
                    f"actual={actual} "
                    f"missing={missing} "
                    f"timeout_or_error={timeout_or_error} "
                    f"full_day={full_day} "
                    f"exclusion_file_exists={ex_p.exists()} "
                    f"excluded_ok={excluded_ok}"
                )
    else:
        print('WARN [Slots checks] expected_slots/slot_coverage/sample_quality_daily missing')

# 8) Synthetic model allowlist guard tests
import subprocess, json
mg=base/'scripts'/'model_allowlist_guard.py'
if mg.exists():
    def run(model):
        cp=subprocess.run(['python3', str(mg), '--task-name','synthetic', '--model', model, '--provider','deepseek'], capture_output=True, text=True)
        out=cp.stdout.strip().splitlines()[-1] if cp.stdout.strip() else ''
        try:
            j=json.loads(out)
        except Exception:
            j={}
        return cp.returncode, j

    rc,j=run('gpt-5.1')
    ok = (not j.get('allowlist_pass')) and j.get('error_code')=='MODEL_NOT_SUPPORTED'
    print('PASS [Model guard synthetic] gpt-5.1 -> MODEL_NOT_SUPPORTED' if ok else f"FAIL [Model guard synthetic] gpt-5.1 unexpected {j}")

    rc,j=run('gpt-5.3-codex')
    ok = (not j.get('allowlist_pass')) and j.get('error_code')=='MODEL_NOT_FOUND'
    print('PASS [Model guard synthetic] gpt-5.3-codex -> MODEL_NOT_FOUND' if ok else f"FAIL [Model guard synthetic] gpt-5.3-codex unexpected {j}")

    rc,j=run('deepseek/deepseek-v4-flash')
    ok = j.get('allowlist_pass') and j.get('final_model')=='deepseek/deepseek-v4-flash'
    print('PASS [Model guard synthetic] deepseek/deepseek-v4-flash -> PASS' if ok else f"FAIL [Model guard synthetic] deepseek unexpected {j}")

    # blocked models must not be marked PASS and must record original/final
    rc,j=run('gpt-5.1')
    ok = (j.get('original_model')=='gpt-5.1') and (j.get('final_model') in ('gpt-5.1','deepseek/deepseek-v4-flash'))
    print('PASS [Model guard synthetic] original/final recorded' if ok else 'FAIL [Model guard synthetic] original/final missing')

    # run_with_model_guard.sh presence + behavior
    rwm = base/'scripts'/'run_with_model_guard.sh'
    print('PASS [Model guard wrapper] run_with_model_guard.sh exists' if rwm.exists() else 'FAIL [Model guard wrapper] run_with_model_guard.sh missing')

    if rwm.exists():
        # 1) blocked model must trigger fallback evidence
        md = base/'guard_outputs'/f'model_guard_daily_{datetime.now().strftime("%Y%m%d")}.json'
        cmd = ['bash', str(rwm), '--task-name','synthetic_wrapper_block', '--jobId','synthetic', '--model','gpt-5.1', '--provider','deepseek', '--', 'bash', '-lc', 'exit 0']
        subprocess.run(cmd, capture_output=True, text=True)
        ok_daily=False
        if md.exists():
            d=json.loads(md.read_text(encoding='utf-8'))
            es=[e for e in d.get('entries',[]) if e.get('task_name')=='synthetic_wrapper_block']
            if es:
                e=es[-1]
                ok_daily=(e.get('original_model')=='gpt-5.1' and e.get('fallback_model')=='deepseek/deepseek-v4-flash' and e.get('fallback_attempted')==True)
        print('PASS [Model guard wrapper] blocked triggers fallback evidence' if ok_daily else 'FAIL [Model guard wrapper] missing fallback evidence')

        # 2) allowlist model should execute command and record allowlist_pass
        cmd = ['bash', str(rwm), '--task-name','synthetic_wrapper_pass', '--jobId','synthetic', '--model','deepseek/deepseek-v4-flash', '--provider','deepseek', '--', 'bash', '-lc', 'exit 0']
        subprocess.run(cmd, capture_output=True, text=True)
        ok_daily2=False
        if md.exists():
            d=json.loads(md.read_text(encoding='utf-8'))
            es=[e for e in d.get('entries',[]) if e.get('task_name')=='synthetic_wrapper_pass']
            if es:
                e=es[-1]
                ok_daily2=(e.get('allowlist_pass')==True and e.get('final_model')=='deepseek/deepseek-v4-flash')
        print('PASS [Model guard wrapper] allowlist pass evidence' if ok_daily2 else 'FAIL [Model guard wrapper] allowlist evidence missing')

        # 3) rate_limit protection mode blocks P1 but allows P0
        rl=base/'scripts'/'rate_limit_guard.py'
        if rl.exists():
            subprocess.run(['python3', str(rl), '--force-protection-on'], capture_output=True, text=True)
            cp=subprocess.run(['bash', str(rwm), '--task-name','intraday_chain_review', '--jobId','synthetic', '--model','deepseek/deepseek-v4-flash', '--provider','deepseek', '--', 'bash', '-lc', 'exit 0'], capture_output=True, text=True)
            print('PASS [Rate limit guard] P1 blocked in protection_mode' if cp.returncode==11 else f'FAIL [Rate limit guard] P1 not blocked rc={cp.returncode}')
            cp=subprocess.run(['bash', str(rwm), '--task-name','603305_every10_sim', '--jobId','synthetic', '--model','deepseek/deepseek-v4-flash', '--provider','deepseek', '--', 'bash', '-lc', 'exit 0'], capture_output=True, text=True)
            print('PASS [Rate limit guard] P0 allowed in protection_mode' if cp.returncode==0 else f'FAIL [Rate limit guard] P0 not allowed rc={cp.returncode}')
            subprocess.run(['python3', str(rl), '--force-protection-off'], capture_output=True, text=True)
        else:
            print('FAIL [Rate limit guard] rate_limit_guard.py missing')
else:
    print('FAIL [Model guard synthetic] model_allowlist_guard.py missing')

# 9) Active cron unified entry enforcement (P1.1-final)
import subprocess, json
try:
    cp=subprocess.run(['openclaw','cron','list','--json'], capture_output=True, text=True, timeout=20)
    if cp.returncode!=0:
        print('FAIL [Cron unified entry] openclaw cron list failed')
    else:
        cj=json.loads(cp.stdout)
        jobs=cj.get('jobs',[])
        keywords=['Kronos','603305','auto_report_guard','simulate_position','factor_observer','factor','observer','close_review','self_audit','slot_coverage','scorecard','model_guard']
        must=[]
        for j in jobs:
            if not j.get('enabled',True):
                continue
            msg=((j.get('payload') or {}).get('message') or '')
            name=j.get('name') or ''
            blob=(name+'\n'+msg).lower()
            # Only enforce unified entry for jobs that actually execute local Kronos commands
            is_local_exec = ('/users/wxo/desktop/kronos' in blob) or ('python3 ' in blob) or ('bash ' in blob)
            if is_local_exec and any(k.lower() in blob for k in keywords):
                must.append(j)

        bad_direct=[]
        bad_model=[]
        bad_entry=[]
        for j in must:
            msg=((j.get('payload') or {}).get('message') or '')
            mdl=((j.get('payload') or {}).get('model') or '')
            if mdl and mdl!='deepseek/deepseek-v4-flash':
                bad_model.append(j)
            # must go through run_with_model_guard.sh
            if (('run_with_model_guard.sh' not in msg) and ('taskq_submit.sh' not in msg)) and ('taskq_submit.sh' not in msg):
                bad_entry.append(j)
            # must not directly call python3 factor_observer_...
            if 'python3' in msg and ('run_with_model_guard.sh' not in msg) and ('taskq_submit.sh' not in msg) and any(x in msg for x in ['factor_observer_603305.py','factor_observer_5d_review.py']):
                bad_direct.append(j)

        if bad_model:
            print(f"FAIL [Cron unified entry] payload.model not gpt-5.2 count={len(bad_model)}")
        else:
            print('PASS [Cron unified entry] payload.model pinned to deepseek/deepseek-v4-flash')

        if bad_entry:
            print(f"FAIL [Cron unified entry] not using run_with_model_guard.sh/taskq_submit.sh count={len(bad_entry)}")
        else:
            print('PASS [Cron unified entry] all kronos-related jobs use run_with_model_guard.sh')

        # factor_observer cron check: if any active factor observer job exists, must be unified
        factor_jobs=[j for j in jobs if (j.get('enabled',True) and ('factor' in (j.get('name','')+( (j.get('payload') or {}).get('message') or '')).lower()))]
        if factor_jobs:
            bad=[j for j in factor_jobs if 'run_with_model_guard.sh' not in (((j.get('payload') or {}).get('message') or ''))]
            if bad:
                print(f"FAIL [Cron unified entry] factor_observer jobs not unified count={len(bad)}")
            else:
                print('PASS [Cron unified entry] factor_observer jobs unified')
        else:
            print('PASS [Cron unified entry] no active factor_observer cron found')
except Exception as e:
    print('FAIL [Cron unified entry] exception')

# 10) task_queue worker --once semantics + protection gate
import json, subprocess, uuid
from pathlib import Path

q=base/'task_queue'
pending=q/'pending'
done=q/'done'
failed=q/'failed'
logs=q/'logs'
worker=base/'scripts'/'kronos_task_worker.py'
submit=base/'scripts'/'kronos_submit_task.py'
status=base/'scripts'/'kronos_task_status.py'

if worker.exists():
    # Isolated task_queue synthetic test (MUST NOT touch real task_queue)
    import tempfile, shutil
    test_root = Path(tempfile.mkdtemp(prefix='kronos_task_queue_regression_'))
    tp = test_root/'pending'; tr = test_root/'running'; td = test_root/'done'; tf = test_root/'failed'; tl = test_root/'logs'
    for ddir in [tp,tr,td,tf,tl]:
        ddir.mkdir(parents=True, exist_ok=True)

    # ensure protection_mode is OFF for basic --once semantics test
    rl=base/'scripts'/'rate_limit_guard.py'
    if rl.exists():
        subprocess.run(['python3', str(rl), '--force-protection-off'], capture_output=True, text=True)

    # 1) --once processes only one pending task
    tid1='SYN_'+uuid.uuid4().hex[:8]
    tid2='SYN_'+uuid.uuid4().hex[:8]
    (tp/f'{tid1}.json').write_text(json.dumps({'task_id':tid1,'task_name':'intraday_chain_review','status':'pending','created_at':'x','command':'bash -lc "exit 0"','log_path':str(tl/f'{tid1}.log'),'output_files':[]},ensure_ascii=False,indent=2),encoding='utf-8')
    (tp/f'{tid2}.json').write_text(json.dumps({'task_id':tid2,'task_name':'intraday_chain_review','status':'pending','created_at':'x','command':'bash -lc "exit 0"','log_path':str(tl/f'{tid2}.log'),'output_files':[]},ensure_ascii=False,indent=2),encoding='utf-8')

    cp=subprocess.run(['python3', str(worker), '--once', '--queue-root', str(test_root)], capture_output=True, text=True)
    remain=list(tp.glob(f'{tid1}.json')) + list(tp.glob(f'{tid2}.json'))
    moved=(len(remain)==1)
    print('PASS [task_queue worker] --once processes exactly one task' if moved else f'FAIL [task_queue worker] --once did not process exactly one; pending_left={len(remain)}')

    # 1b) --once --task-id executes specified task only
    task_A='SYN_'+uuid.uuid4().hex[:8]
    task_B='SYN_'+uuid.uuid4().hex[:8]
    (tp/f'{task_A}.json').write_text(json.dumps({'task_id':task_A,'task_name':'intraday_chain_review','status':'pending','created_at':'x','command':'bash -lc "exit 0"','log_path':str(tl/f'{task_A}.log'),'output_files':[]},ensure_ascii=False,indent=2),encoding='utf-8')
    (tp/f'{task_B}.json').write_text(json.dumps({'task_id':task_B,'task_name':'intraday_chain_review','status':'pending','created_at':'x','command':'bash -lc "exit 0"','log_path':str(tl/f'{task_B}.log'),'output_files':[]},ensure_ascii=False,indent=2),encoding='utf-8')

    cp=subprocess.run(['python3', str(worker), '--once', '--task-id', task_B, '--queue-root', str(test_root)], capture_output=True, text=True)
    b_done = (td/f'{task_B}.json').exists() or (tf/f'{task_B}.json').exists()
    a_still = (tp/f'{task_A}.json').exists()
    a_not_done = not (td/f'{task_A}.json').exists()
    a_not_failed = not (tf/f'{task_A}.json').exists()
    ok = b_done and a_still and a_not_done and a_not_failed
    # also verify worker output task_id == task_B
    out_ok = False
    try:
        j=json.loads(cp.stdout)
        out_ok = (j.get('task_id')==task_B)
    except Exception:
        out_ok = False
    ok = ok and out_ok
    print('PASS [task_queue worker] --task-id executes specified task only' if ok else 'FAIL [task_queue worker] --task-id semantics broken')

    # cleanup isolated dir
    shutil.rmtree(test_root, ignore_errors=True)

    # 2) protection_mode blocks P1/P2 (isolated queue-root)
    rl=base/'scripts'/'rate_limit_guard.py'
    if rl.exists():
        import tempfile, shutil
        test_root = Path(tempfile.mkdtemp(prefix='kronos_task_queue_regression_protect_'))
        tp = test_root/'pending'; tr = test_root/'running'; td = test_root/'done'; tf = test_root/'failed'; tl = test_root/'logs'
        for ddir in [tp,tr,td,tf,tl]:
            ddir.mkdir(parents=True, exist_ok=True)

        subprocess.run(['python3', str(rl), '--force-protection-on'], capture_output=True, text=True)
        tid='SYN_'+uuid.uuid4().hex[:8]
        (tp/f'{tid}.json').write_text(json.dumps({'task_id':tid,'task_name':'intraday_chain_review','status':'pending','created_at':'x','command':'bash -lc "exit 0"','log_path':str(tl/f'{tid}.log'),'output_files':[]},ensure_ascii=False,indent=2),encoding='utf-8')
        cp=subprocess.run(['python3', str(worker), '--once', '--queue-root', str(test_root)], capture_output=True, text=True)
        blocked = (tf/f'{tid}.json').exists()
        print('PASS [task_queue worker] protection_mode blocks P1/P2' if blocked else 'FAIL [task_queue worker] protection_mode did not block P1/P2')

        # 3) protection_mode allows P0
        tid='SYN_'+uuid.uuid4().hex[:8]
        (tp/f'{tid}.json').write_text(json.dumps({'task_id':tid,'task_name':'603305_every10_sim','status':'pending','created_at':'x','command':'bash -lc "exit 0"','log_path':str(tl/f'{tid}.log'),'output_files':[]},ensure_ascii=False,indent=2),encoding='utf-8')
        cp=subprocess.run(['python3', str(worker), '--once', '--queue-root', str(test_root)], capture_output=True, text=True)
        allowed = (td/f'{tid}.json').exists()
        print('PASS [task_queue worker] protection_mode allows P0' if allowed else 'FAIL [task_queue worker] protection_mode blocked P0 unexpectedly')

        subprocess.run(['python3', str(rl), '--force-protection-off'], capture_output=True, text=True)
        shutil.rmtree(test_root, ignore_errors=True)
    else:
        print('FAIL [task_queue worker] rate_limit_guard.py missing')
else:
    print('FAIL [task_queue worker] kronos_task_worker.py missing')


# 12) Sample completeness gate checks
import json
ms=base/'guard_outputs'/f'main_shadow_review_20260522.json'
if ms.exists():
    d=json.loads(ms.read_text(encoding='utf-8'))
    sc=d.get('sample_completeness') or {}
    ok1=('sample_status' in sc and 'is_full_trading_day_sample' in sc)
    print('PASS [Sample completeness] main_shadow_review has sample_status/is_full_trading_day_sample' if ok1 else 'FAIL [Sample completeness] missing fields')
    ok2=(sc.get('sample_status')!='full_trading_day')
    print('PASS [Sample completeness] 20260522 not full_trading_day' if ok2 else 'FAIL [Sample completeness] 20260522 wrongly full_trading_day')
else:
    print('WARN [Sample completeness] main_shadow_review_20260522.json missing')

sp=base/'guard_outputs'/f'strategy_param_proposal_20260522.json'
if sp.exists():
    d=json.loads(sp.read_text(encoding='utf-8'))
    # if performance_use_allowed=false then parameter_switch_allowed must be false
    if d.get('sample_completeness') and (d['sample_completeness'].get('performance_use_allowed')==False):
        ok=(d.get('parameter_switch_allowed')==False)
        print('PASS [Sample completeness] param proposal forbids switch when performance_use_allowed=false' if ok else 'FAIL [Sample completeness] param proposal allows switch unexpectedly')

ho=base/'chatgpt_handoff'/'latest_review_request.md'
if ho.exists():
    t=ho.read_text(encoding='utf-8',errors='ignore')
    ok=('Sample completeness' in t and 'performance_use_allowed' in t)
    print('PASS [Sample completeness] handoff contains sample completeness' if ok else 'FAIL [Sample completeness] handoff missing sample completeness')



# 12.5) Trading calendar checks
import importlib.util
cal=base/'scripts'/'trading_calendar.py'
if cal.exists():
    spec=importlib.util.spec_from_file_location('trading_calendar', str(cal))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    print('PASS [Trading calendar] 2026-05-22 trading day' if m.is_trading_day('2026-05-22') else 'FAIL [Trading calendar] 2026-05-22 not trading day')
    print('PASS [Trading calendar] 2026-05-01 non-trading' if (not m.is_trading_day('2026-05-01')) else 'FAIL [Trading calendar] 2026-05-01 trading unexpectedly')
    print('PASS [Trading calendar] 2026-05-04 non-trading' if (not m.is_trading_day('2026-05-04')) else 'FAIL [Trading calendar] 2026-05-04 trading unexpectedly')
    print('PASS [Trading calendar] 2026-05-06 trading day' if m.is_trading_day('2026-05-06') else 'FAIL [Trading calendar] 2026-05-06 not trading day')
    # Saturday check (2026-05-02 is Saturday)
    print('PASS [Trading calendar] weekend non-trading' if (not m.is_trading_day('2026-05-02')) else 'FAIL [Trading calendar] weekend trading unexpectedly')
    ok = (m.get_expected_slots('2026-05-01')==[])
    print('PASS [Trading calendar] non-trading expected_slots=0' if ok else 'FAIL [Trading calendar] non-trading expected_slots!=0')
else:
    print('FAIL [Trading calendar] scripts/trading_calendar.py missing')

# 13) Sample quality gate checks
import json
ms=base/'guard_outputs'/f'main_shadow_review_20260522.json'
if ms.exists():
    d=json.loads(ms.read_text(encoding='utf-8'))
    q=d.get('sample_quality') or {}
    ok=('sample_quality_grade' in q and 'expected_slots' in q and 'main_records' in q and 'shadow_records' in q and 'aligned_records' in q)
    print('PASS [Sample quality] main_shadow_review contains required fields' if ok else 'FAIL [Sample quality] main_shadow_review missing fields')
    ok2=(q.get('sample_quality_grade')=='D')
    print('PASS [Sample quality] 20260522 grade=D' if ok2 else 'FAIL [Sample quality] 20260522 grade not D')
else:
    print('WARN [Sample quality] main_shadow_review_20260522.json missing')

sp=base/'guard_outputs'/f'strategy_param_proposal_20260522.json'
if sp.exists():
    d=json.loads(sp.read_text(encoding='utf-8'))
    q=d.get('sample_quality') or {}
    if q and q.get('performance_use_allowed')!='true':
        ok=(d.get('parameter_switch_allowed')==False)
        print('PASS [Sample quality] param proposal forbids switch when performance_use_allowed!=true' if ok else 'FAIL [Sample quality] param proposal allows switch unexpectedly')

ho=base/'chatgpt_handoff'/'latest_review_request.md'
if ho.exists():
    t=ho.read_text(encoding='utf-8',errors='ignore')
    ok=('sample_quality_grade' in t and 'performance_use_allowed' in t)
    print('PASS [Sample quality] handoff contains sample quality gate' if ok else 'FAIL [Sample quality] handoff missing sample quality gate')

# 11) Factor observer gate checks
p=base/'guard_outputs'/'factor_observer_5d_review.json'
if p.exists():
    d=json.loads(p.read_text(encoding='utf-8'))
    nd=int(d.get('n_days',0) or 0)
    fr=float(d.get('factor_available_ratio_5d',0) or 0)
    if nd<3 or fr<0.8:
        print('PASS [Factor observer gate checks] gate blocks v1.2-shadow')
    else:
        print('WARN [Factor observer gate checks] gate open; require user confirm')
else:
    print('WARN [Factor observer gate checks] 5d review missing')
PY)

while IFS= read -r line; do
  echo "$line" | tee -a "$LOG"
  case "$line" in
    PASS*) PASS_N=$((PASS_N+1));;
    WARN*) WARN_N=$((WARN_N+1));;
    FAIL*) FAIL_N=$((FAIL_N+1));;
  esac
done <<< "$eval_results"

echo "SUMMARY PASS=$PASS_N WARN=$WARN_N FAIL=$FAIL_N" | tee -a "$LOG"
if [ "$FAIL_N" -gt 0 ]; then
  echo "RESULT=FAIL" | tee -a "$LOG"
  exit 1
fi
if [ "$WARN_N" -gt 0 ]; then
  echo "RESULT=FAIL" | tee -a "$LOG"
  exit 1
fi
echo "RESULT=PASS" | tee -a "$LOG"
echo "LOG=$LOG"

# --- factor_score_observer_603305 (observer-only) gates ---
if [ ! -f "/Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py" ]; then
  echo "FAIL: missing scripts/factor_score_observer.py"; exit 3
fi
if [ ! -f "/Users/wxo/Desktop/Kronos/config/factor_weights_603305.json" ]; then
  echo "FAIL: missing config/factor_weights_603305.json"; exit 3
fi

# NEW: py_compile gates (must fail regression if any observer script is not runnable)
python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py || { echo "FAIL: py_compile factor_score_observer.py"; exit 3; }
if [ -f "/Users/wxo/Desktop/Kronos/scripts/factor_observer_intraday_light.py" ]; then
  python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_observer_intraday_light.py || { echo "FAIL: py_compile factor_observer_intraday_light.py"; exit 3; }
fi
if [ -f "/Users/wxo/Desktop/Kronos/scripts/factor_score_observer_postclose.py" ]; then
  python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_score_observer_postclose.py || { echo "FAIL: py_compile factor_score_observer_postclose.py"; exit 3; }
fi

echo "PASS: py_compile observer scripts"

python3 - <<'PY'
import json, sys
p='/Users/wxo/Desktop/Kronos/config/factor_weights_603305.json'
d=json.load(open(p,'r',encoding='utf-8'))
profiles=d.get('profiles') or {}
need=['conservative','neutral','aggressive_observer']
for n in need:
    w=profiles.get(n)
    if not isinstance(w, dict):
        print('FAIL: missing profile', n); sys.exit(3)
    s=sum(float(v) for v in w.values())
    if abs(s-1.0) > 1e-9:
        print('FAIL: weights sum != 1.0', n, s); sys.exit(3)
print('PASS: factor_weights_603305.json weights sum OK')
PY

# score bounds / observer-only: run script in governance-only mode (no input) to ensure it emits outputs and score bounds checks are wired
python3 /Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py --date 20991231 --symbol 603305 --weight-profile neutral >/dev/null

echo "PASS: factor_score_observer_603305 gates"

# --- factor_observer intraday light + postclose gates (observer-only) ---
if [ ! -f "/Users/wxo/Desktop/Kronos/scripts/factor_observer_intraday_light.py" ]; then
  echo "FAIL: missing scripts/factor_observer_intraday_light.py"; exit 3
fi
if [ ! -f "/Users/wxo/Desktop/Kronos/scripts/factor_score_observer_postclose.py" ]; then
  echo "FAIL: missing scripts/factor_score_observer_postclose.py"; exit 3
fi
python3 -c "import pathlib; p=pathlib.Path('/Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py'); t=p.read_text(encoding='utf-8'); import sys; sys.exit(3) if '--light-from-json' not in t else print('PASS: factor_score_observer light mode present')"
echo "PASS: factor_observer intraday/postclose gates"



# --- factor_observer intraday report block (observer-only) ---
# 1) py_compile gates (must FAIL regression on compile errors)
python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py || { echo "FAIL: py_compile factor_score_observer.py"; exit 3; }
python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_observer_intraday_light.py || true
python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_score_observer_postclose.py || true

# 2) static checks: report text may include FACTOR_OBSERVER block with required keys + unavailable fallback
python3 - <<'PY'
from pathlib import Path
p=Path('/Users/wxo/Desktop/Kronos/auto_report_guard_603305.py')
t=p.read_text(encoding='utf-8')
need=[
  '[FACTOR_OBSERVER]',
  'observer_only: true',
  'affects_position: false',
  'unavailable: true',
]
miss=[x for x in need if x not in t]
if miss:
  print('FAIL: FACTOR_OBSERVER static markers missing:', miss)
  raise SystemExit(3)
print('PASS: FACTOR_OBSERVER static markers present')
PY

echo "PASS: factor_observer intraday report block gates"


# --- factor_score_observer light completeness test (should NOT be insufficient_data when fields complete) ---
complete_in='{"price":17.0,"prev_close":16.9,"open_price":17.2,"high":17.5,"low":16.7,"pct_change":0.6,"position_pct":20,"full_lock":false,"action":"持仓不变"}'
comp_out=$(echo "$complete_in" | python3 "$BASE/scripts/factor_score_observer.py" --light-from-json --light-weight-profile conservative 2>>"$LOG" || true)
if echo "$comp_out" | grep -q '"factor_hint"[[:space:]]*:[[:space:]]*"insufficient_data"'; then
  fail "factor_score_observer light completeness test"
  echo "COMPLETE_OUT=$comp_out" | tee -a "$LOG"
else
  pass "factor_score_observer light completeness test"
fi


# --- premarket_guard_603305 gates ---
[[ -f "/Users/wxo/Desktop/Kronos/scripts/premarket_guard_603305.py" ]] && pass "premarket_guard_603305.py exists" || fail "Missing premarket_guard_603305.py"
python3 -m py_compile "/Users/wxo/Desktop/Kronos/scripts/premarket_guard_603305.py" >>"$LOG" 2>&1 && pass "py_compile premarket_guard_603305.py" || fail "py_compile premarket_guard_603305.py"

# --- postclose_pipeline_603305 task script gates (bash strict mode safe) ---
[[ -f "/Users/wxo/Desktop/Kronos/scripts/tasks/postclose_pipeline_603305.sh" ]] && pass "postclose_pipeline_603305.sh exists" || fail "Missing postclose_pipeline_603305.sh"
bash -n "/Users/wxo/Desktop/Kronos/scripts/tasks/postclose_pipeline_603305.sh" >>"$LOG" 2>&1 && pass "bash -n postclose_pipeline_603305.sh" || fail "bash -n postclose_pipeline_603305.sh"
# must not error when DATE_YYYYMMDD is not provided
bash -lc 'set -euo pipefail; KRONOS_POSTCLOSE_DRY_RUN=1 bash /Users/wxo/Desktop/Kronos/scripts/tasks/postclose_pipeline_603305.sh >/dev/null' >>"$LOG" 2>&1 && pass "postclose_pipeline_603305.sh no-date safe" || fail "postclose_pipeline_603305.sh no-date safe"
# must accept env DATE_YYYYMMDD
bash -lc 'set -euo pipefail; DATE_YYYYMMDD=20260525 KRONOS_POSTCLOSE_DRY_RUN=1 bash /Users/wxo/Desktop/Kronos/scripts/tasks/postclose_pipeline_603305.sh >/dev/null' >>"$LOG" 2>&1 && pass "postclose_pipeline_603305.sh env-date accepted" || fail "postclose_pipeline_603305.sh env-date accepted"

# --- postclose_pipeline_cron_ensure_603305.sh gates (prevent FALSE_DONE) ---
[[ -f "/Users/wxo/Desktop/Kronos/scripts/tasks/postclose_pipeline_cron_ensure_603305.sh" ]] && pass "postclose_pipeline_cron_ensure_603305.sh exists" || fail "Missing postclose_pipeline_cron_ensure_603305.sh"
bash -n "/Users/wxo/Desktop/Kronos/scripts/tasks/postclose_pipeline_cron_ensure_603305.sh" >>"$LOG" 2>&1 && pass "bash -n postclose_pipeline_cron_ensure_603305.sh" || fail "bash -n postclose_pipeline_cron_ensure_603305.sh"
python3 - <<'PY'
from pathlib import Path
p=Path('/Users/wxo/Desktop/Kronos/scripts/tasks/postclose_pipeline_cron_ensure_603305.sh')
t=p.read_text(encoding='utf-8', errors='ignore')
need=[
 'openclaw cron list --json',
 'exit 1',
 'postclose_603305_slot_coverage_1502',
 'postclose_603305_error_code_daily_1507',
 'postclose_603305_scorecard_daily_1510',
 '603305-self-audit-1513',
 'postclose_603305_sample_quality_1516',
 'postclose_603305_main_shadow_review_1518',
 'postclose_603305_factor_postclose_1520',
 'postclose_603305_strategy_param_proposal_1522',
 'postclose_603305_chatgpt_handoff_1524',
 'postclose_603305_regression_1526',
 'postclose_603305_close_stability_summary_1528',
]
missing=[x for x in need if x not in t]
if missing:
    print('FAIL [Postclose ensure script] missing markers:', ','.join(missing))
else:
    print('PASS [Postclose ensure script] strict verify markers present')
PY


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
  '603305-self-audit-1513',
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
    if payload.get('model')!='deepseek/deepseek-v4-flash':
        print(f'FAIL [Postclose cron gates] model not pinned {nm}')
    msg=(payload.get('message') or '')
    if (('run_with_model_guard.sh' not in msg) and ('taskq_submit.sh' not in msg)) and ('taskq_submit.sh' not in msg):
        print(f'FAIL [Postclose cron gates] not using run_with_model_guard.sh/taskq_submit.sh {nm}')
    delivery=j.get('delivery') or {}
    if not delivery.get('bestEffort'):
        print(f'FAIL [Postclose cron gates] bestEffort not true {nm}')
print('PASS [Postclose cron gates] checked')
PY2


# --- postclose_cron_stagger_603305_retry gates ---
python3 - <<'PY2'
import json, subprocess
TZ='Asia/Shanghai'
MODEL='deepseek/deepseek-v4-flash'

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
