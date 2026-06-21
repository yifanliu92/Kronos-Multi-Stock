#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"

echo "[TASK] premarket_guard_603305 start $(date '+%F %T')"

# 1) Add premarket guard script
cat >"$BASE/scripts/premarket_guard_603305.py" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
OUT_JSON = BASE / 'guard_outputs'
OUT_MD = BASE / 'daily_reports'
OUT_JSON.mkdir(parents=True, exist_ok=True)
OUT_MD.mkdir(parents=True, exist_ok=True)

# Canonical job name set we expect to exist for intraday
INTRADAY_JOB_NAMES = [
    '603305-weekday-morning-every10-sim',
    '603305-weekday-morning-every10-sim-10to11',
    '603305-weekday-morning-every10-sim-11to1130',
    '603305-weekday-afternoon-every10-sim',
]

GUARD_SCRIPTS = {
    'auto_report_guard': str(BASE / 'auto_report_guard_603305.py'),
    'simulate_main': str(BASE / 'simulate_position_603305.py'),
    'simulate_shadow': str(BASE / 'simulate_position_603305_shadow.py'),
    'factor_score_observer': str(BASE / 'scripts' / 'factor_score_observer.py'),
    'trading_calendar': str(BASE / 'scripts' / 'trading_calendar.py'),
}


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return cp.returncode, (cp.stdout or ''), (cp.stderr or '')


def is_trading_day(date_str: str) -> tuple[bool, str]:
    try:
        from scripts.trading_calendar import is_trading_day as _is, explain_non_trading_day
        if _is(date_str):
            return True, 'trading_day'
        return False, explain_non_trading_day(date_str)
    except Exception as e:
        return False, f'trading_calendar_error: {e.__class__.__name__}'


def py_compile(path: str) -> tuple[bool, str]:
    rc, out, err = sh(['python3', '-m', 'py_compile', path], timeout=60)
    return (rc == 0), (err.strip() or out.strip())


def factor_light_smoke() -> tuple[bool, dict]:
    # empty JSON must be RC=0 and insufficient_data
    rc, out, err = sh(['python3', GUARD_SCRIPTS['factor_score_observer'], '--light-from-json', '--light-weight-profile', 'conservative'], timeout=60)
    if rc != 0:
        return False, {'rc': rc, 'stderr': err.strip(), 'stdout': out.strip()}
    try:
        j = json.loads((out or '').strip() or '{}')
    except Exception:
        j = {'raw': (out or '').strip()}
    ok = (j.get('factor_hint') == 'insufficient_data') and (j.get('observer_only') is True) and (j.get('affects_position') is False)
    return ok, j


def load_cron_jobs() -> list[dict]:
    # Prefer OpenClaw cron API via CLI JSON output.
    rc, out, err = sh(['openclaw', 'cron', 'list', '--json'], timeout=60)
    if rc != 0:
        return []
    try:
        j = json.loads(out)
        return j.get('jobs') or []
    except Exception:
        return []


def write_outputs(date_yyyymmdd: str, payload: dict) -> tuple[str, str]:
    p_json = OUT_JSON / f'premarket_guard_{date_yyyymmdd}.json'
    p_md = OUT_MD / f'premarket_guard_{date_yyyymmdd}.md'
    p_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = []
    lines.append(f'# premarket_guard_603305 {date_yyyymmdd}')
    lines.append('')
    lines.append(f"- mode: {payload.get('mode')}")
    lines.append(f"- is_trading_day: {payload.get('is_trading_day')}")
    if payload.get('non_trading_reason'):
        lines.append(f"- non_trading_reason: {payload.get('non_trading_reason')}")
    lines.append('')
    lines.append('## Checks')
    for k,v in (payload.get('checks') or {}).items():
        lines.append(f"- {k}: {v}")
    if payload.get('actions'):
        lines.append('')
        lines.append('## Actions')
        for a in payload.get('actions'):
            lines.append(f"- {a}")
    p_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(p_json), str(p_md)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True, choices=['check','auto_heal','verify_0930'])
    ap.add_argument('--date', default=None, help='YYYY-MM-DD (default today)')
    ap.add_argument('--tz', default='Asia/Shanghai')
    args = ap.parse_args()

    today = args.date or dt.datetime.now().strftime('%Y-%m-%d')
    yyyymmdd = today.replace('-','')

    payload = {
        'task': 'premarket_guard_603305',
        'mode': args.mode,
        'date': today,
        'ts': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'is_trading_day': None,
        'non_trading_reason': None,
        'checks': {},
        'actions': [],
        'result': 'UNKNOWN',
    }

    trading, reason = is_trading_day(today)
    payload['is_trading_day'] = trading
    if not trading:
        payload['non_trading_reason'] = reason
        payload['result'] = 'SKIP_NON_TRADING_DAY'
        write_outputs(yyyymmdd, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    # --- common checks ---
    ok, err = py_compile(GUARD_SCRIPTS['auto_report_guard'])
    payload['checks']['py_compile:auto_report_guard_603305.py'] = 'PASS' if ok else f'FAIL {err}'
    ok2, err2 = py_compile(GUARD_SCRIPTS['simulate_main'])
    payload['checks']['py_compile:simulate_position_603305.py'] = 'PASS' if ok2 else f'FAIL {err2}'
    ok3, err3 = py_compile(GUARD_SCRIPTS['simulate_shadow'])
    payload['checks']['py_compile:simulate_position_603305_shadow.py'] = 'PASS' if ok3 else f'FAIL {err3}'

    f_ok, f_j = factor_light_smoke()
    payload['checks']['factor_light_empty_json_smoke'] = 'PASS' if f_ok else f'FAIL {f_j}'

    jobs = load_cron_jobs()
    name_to_job = {j.get('name'): j for j in jobs if j.get('name')}

    # cron existence/enabled/model/entry checks
    for nm in INTRADAY_JOB_NAMES:
        j = name_to_job.get(nm)
        payload['checks'][f'cron_exists:{nm}'] = bool(j)
        payload['checks'][f'cron_enabled:{nm}'] = (bool(j) and bool(j.get('enabled')))
        if j:
            model = (j.get('payload') or {}).get('model')
            msg = (j.get('payload') or {}).get('message','')
            payload['checks'][f'cron_model:{nm}'] = model
            payload['checks'][f'cron_entry_guard:{nm}'] = ('run_with_model_guard.sh' in msg and 'auto_report_guard_603305.py' in msg)

    # mode-specific behavior
    if args.mode == 'auto_heal':
        # Block if scripts invalid
        if not (ok and ok2 and ok3):
            payload['result'] = 'PREMARKET_BLOCKED_SCRIPT_ERROR'
            write_outputs(yyyymmdd, payload)
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        changed = 0
        for nm in INTRADAY_JOB_NAMES:
            j = name_to_job.get(nm)
            if not j:
                continue
            if not j.get('enabled'):
                # auto enable via openclaw cron update
                jid = j.get('id') or j.get('jobId')
                if jid:
                    cmd = [
                        'openclaw','cron','update',jid,
                        '--patch',
                        json.dumps({'enabled': True, 'delivery': {'mode':'announce','channel':'telegram','to':'736532132','bestEffort': True}}, ensure_ascii=False)
                    ]
                    rc, out, err = sh(cmd, timeout=60)
                    if rc == 0:
                        changed += 1
                        payload['actions'].append(f'ENABLED {nm} jobId={jid}')

            # ensure model pinned is gpt-5.3-codex
            jid = j.get('id') or j.get('jobId')
            if jid and ((j.get('payload') or {}).get('model') != 'openai-codex/gpt-5.5'):
                cmd = [
                    'openclaw','cron','update',jid,
                    '--patch',
                    json.dumps({'payload': {'model':'openai-codex/gpt-5.5'}}, ensure_ascii=False)
                ]
                rc, out, err = sh(cmd, timeout=60)
                if rc == 0:
                    changed += 1
                    payload['actions'].append(f'PIN_MODEL {nm} jobId={jid}')

        payload['result'] = 'PREMARKET_AUTO_HEAL_DONE' if changed else 'PREMARKET_AUTO_HEAL_NO_CHANGE'
        write_outputs(yyyymmdd, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.mode == 'verify_0930':
        # Do not backfill. Only verify existence.
        rp = BASE / 'guard_outputs' / f'report_{yyyymmdd}_093000.txt'
        payload['checks']['report_0930_exists'] = rp.exists()
        if rp.exists():
            t = rp.read_text(encoding='utf-8', errors='ignore')
            payload['checks']['report_0930_has_main'] = (('建仓明细（主策略' in t) or ('主策略持仓口径' in t))
            payload['checks']['report_0930_has_shadow'] = ('影子策略' in t)
            payload['checks']['report_0930_has_factor'] = ('[FACTOR_OBSERVER]' in t)
        else:
            payload['checks']['timeslot_0930_status'] = 'CRON_NOT_TRIGGERED'
            payload['checks']['sample_quality_forbid_A'] = True
        payload['result'] = 'VERIFY_DONE'
        write_outputs(yyyymmdd, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    # default: check
    payload['result'] = 'CHECK_DONE'
    write_outputs(yyyymmdd, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
PY
chmod +x "$BASE/scripts/premarket_guard_603305.py"

# 2) Add cron jobs (09:20 check, 09:27 auto-heal, 09:31 verify)
# Use OpenClaw cron add via gateway API wrapper in config environment: we patch via openclaw CLI JSON if available.
# We will *not* delete/modify strategy parameters; only cron scaffolding around checks.

# Create/Update cron jobs idempotently: if name exists, update; else add.
python3 - <<'PY'
import json
import subprocess

TZ='Asia/Shanghai'
BASE='/Users/wxo/Desktop/Kronos'
MODEL='openai-codex/gpt-5.5'

def sh(cmd):
    cp=subprocess.run(cmd, capture_output=True, text=True)
    return cp.returncode, (cp.stdout or ''), (cp.stderr or '')

rc,out,err=sh(['openclaw','cron','list','--json'])
jobs=[]
if rc==0:
    try:
        jobs=json.loads(out).get('jobs',[])
    except Exception:
        jobs=[]
name2id={j.get('name'): (j.get('id') or j.get('jobId')) for j in jobs if j.get('name')}

specs=[
  {
    'name':'premarket_guard_603305_check_0920',
    'expr':'20 9 * * 1-5',
    'message':f"立即执行并仅返回结果：bash {BASE}/scripts/run_with_model_guard.sh --task-name premarket_guard_603305_check --jobId premarket_guard_603305_check_0920 --model \"${{OPENCLAW_MODEL:-${{MODEL:-}}}}\" --provider \"${{OPENCLAW_PROVIDER:-${{PROVIDER:-}}}}\" -- python3 {BASE}/scripts/premarket_guard_603305.py --mode check",
  },
  {
    'name':'premarket_guard_603305_auto_heal_0927',
    'expr':'27 9 * * 1-5',
    'message':f"立即执行并仅返回结果：bash {BASE}/scripts/run_with_model_guard.sh --task-name premarket_guard_603305_auto_heal --jobId premarket_guard_603305_auto_heal_0927 --model \"${{OPENCLAW_MODEL:-${{MODEL:-}}}}\" --provider \"${{OPENCLAW_PROVIDER:-${{PROVIDER:-}}}}\" -- python3 {BASE}/scripts/premarket_guard_603305.py --mode auto_heal",
  },
  {
    'name':'premarket_guard_603305_verify_0930_0931',
    'expr':'31 9 * * 1-5',
    'message':f"立即执行并仅返回结果：bash {BASE}/scripts/run_with_model_guard.sh --task-name premarket_guard_603305_verify_0930 --jobId premarket_guard_603305_verify_0930_0931 --model \"${{OPENCLAW_MODEL:-${{MODEL:-}}}}\" --provider \"${{OPENCLAW_PROVIDER:-${{PROVIDER:-}}}}\" -- python3 {BASE}/scripts/premarket_guard_603305.py --mode verify_0930",
  },
]

for s in specs:
    job={
      'name':s['name'],
      'schedule':{'kind':'cron','expr':s['expr'],'tz':TZ},
      'payload':{'kind':'agentTurn','message':s['message'],'model':MODEL},
      'sessionTarget':'isolated',
      'enabled':True,
      'delivery':{'mode':'announce','channel':'telegram','to':'736532132','bestEffort':True}
    }
    if s['name'] in name2id and name2id[s['name']]:
        jid=name2id[s['name']]
        patch={'schedule':job['schedule'],'payload':job['payload'],'enabled':True,'delivery':job['delivery'],'sessionTarget':'isolated'}
        sh(['openclaw','cron','update',jid,'--patch',json.dumps(patch,ensure_ascii=False)])
    else:
        sh(['openclaw','cron','add','--json',json.dumps(job,ensure_ascii=False)])

print('premarket guard cron ensured')
PY

# 3) Extend regression gate (existence checks only; behavior tests are synthetic and non-destructive)
python3 - <<'PY'
from pathlib import Path
p=Path('/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh')
text=p.read_text(encoding='utf-8')
marker='premarket_guard_603305 gates'
if marker in text:
    print('run_kronos_regression.sh already has premarket guard gates')
    raise SystemExit(0)

append=f"""

# --- premarket_guard_603305 gates ---
[[ -f "/Users/wxo/Desktop/Kronos/scripts/premarket_guard_603305.py" ]] && pass "premarket_guard_603305.py exists" || fail "Missing premarket_guard_603305.py"
python3 -m py_compile "/Users/wxo/Desktop/Kronos/scripts/premarket_guard_603305.py" >>"$LOG" 2>&1 && pass "py_compile premarket_guard_603305.py" || fail "py_compile premarket_guard_603305.py"
"""

p.write_text(text+append, encoding='utf-8')
print('patched run_kronos_regression.sh (premarket guard gates)')
PY

# 4) Compile sanity for new file
python3 -m py_compile "$BASE/scripts/premarket_guard_603305.py"

echo "[TASK] premarket_guard_603305 done $(date '+%F %T')"
