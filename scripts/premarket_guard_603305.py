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
    # every10 cron (new naming, 24 slots)
    '603305-every10-0930',
    '603305-every10-0940',
    '603305-every10-0950',
    '603305-every10-1000',
    '603305-every10-1010',
    '603305-every10-1020',
    '603305-every10-1030',
    '603305-every10-1040',
    '603305-every10-1050',
    '603305-every10-1100',
    '603305-every10-1110',
    '603305-every10-1120',
    '603305-every10-1300',
    '603305-every10-1310',
    '603305-every10-1320',
    '603305-every10-1330',
    '603305-every10-1340',
    '603305-every10-1350',
    '603305-every10-1400',
    '603305-every10-1410',
    '603305-every10-1420',
    '603305-every10-1430',
    '603305-every10-1440',
    '603305-every10-1450',
]

GUARD_SCRIPTS = {
    'auto_report_guard': str(BASE / 'auto_report_guard_603305.py'),
    'simulate_main': str(BASE / 'simulate_position_603305.py'),
    'simulate_shadow': str(BASE / 'simulate_position_603305_shadow.py'),
    'factor_score_observer': str(BASE / 'scripts' / 'factor_score_observer.py'),
    'trading_calendar': str(BASE / 'scripts' / 'trading_calendar.py'),
}


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input='')
    return cp.returncode, (cp.stdout or ''), (cp.stderr or '')


def is_trading_day(date_str: str) -> tuple[bool, str, str | None]:
    """Return (is_trading_day, non_trading_reason, error_code).

    IMPORTANT: calendar import/runtime errors must NOT be treated as non-trading days.
    """
    try:
        import sys
        # Stabilize import paths for both "scripts.trading_calendar" and "trading_calendar".
        for p in (str(BASE / 'scripts'), str(BASE)):
            if p not in sys.path:
                sys.path.insert(0, p)

        try:
            # Preferred: import from scripts package-like path
            from scripts.trading_calendar import is_trading_day as _is, explain_non_trading_day
        except Exception:
            # Fallback: direct module import when scripts/ isn't a package
            from trading_calendar import is_trading_day as _is, explain_non_trading_day

        if _is(date_str):
            return True, 'trading_day', None
        return False, explain_non_trading_day(date_str), None
    except Exception as e:
        return False, f'trading_calendar_error: {e.__class__.__name__}', 'TRADING_CALENDAR_IMPORT_ERROR'


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


# Resolve the correct OpenClaw CLI binary once at module load.
# The old /usr/local/bin/openclaw (2026.3.2) is protocol-incompatible
# with the current gateway (2026.5.28).
_OC_CLI: str = ''
def _resolve_openclaw_cli() -> str:
    global _OC_CLI
    if _OC_CLI:
        return _OC_CLI
    import os
    candidates = [
        os.path.expanduser('~/.npm-global/bin/openclaw'),
        '/usr/local/bin/openclaw',
    ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                rc, out, err = sh([c, 'cron', 'list', '--json'], timeout=30)
                if rc == 0 and ('"jobs"' in (out or '')):
                    _OC_CLI = c
                    return _OC_CLI
            except Exception:
                continue
    _OC_CLI = candidates[0]  # fallback, may also fail
    return _OC_CLI


def load_cron_jobs() -> list[dict]:
    # Prefer OpenClaw cron API via CLI JSON output.
    # OpenClaw may print Config warnings before JSON; strip prefix safely.
    cli = _resolve_openclaw_cli()
    rc, out, err = sh([cli, 'cron', 'list', '--json'], timeout=60)
    if rc != 0:
        return []

    txt = out.strip()
    if not txt:
        return []

    starts = [i for i in (txt.find('{'), txt.find('[')) if i >= 0]
    if starts:
        txt = txt[min(starts):]

    try:
        j = json.loads(txt)
        if isinstance(j, dict):
            return j.get('jobs') or []
        if isinstance(j, list):
            return j
        return []
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

    trading, reason, cal_err = is_trading_day(today)

    # Calendar import/runtime errors MUST block (P0). Do not downgrade to non-trading day.
    if cal_err:
        payload['is_trading_day'] = None
        payload['non_trading_reason'] = None
        payload['trading_calendar_error'] = reason
        payload['error_code'] = cal_err
        payload['result'] = 'PREMARKET_BLOCKED_CALENDAR_ERROR'
        write_outputs(yyyymmdd, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0

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
                    cli = _resolve_openclaw_cli()
                    cmd = [
                        cli,'cron','update',jid,
                        '--patch',
                        json.dumps({'enabled': True, 'delivery': {'mode':'announce','channel':'telegram','to':'736532132','bestEffort': True}}, ensure_ascii=False)
                    ]
                    rc, out, err = sh(cmd, timeout=60)
                    if rc == 0:
                        changed += 1
                        payload['actions'].append(f'ENABLED {nm} jobId={jid}')

            # ensure model pinned is gpt-5.2
            jid = j.get('id') or j.get('jobId')
            if jid and ((j.get('payload') or {}).get('model') != 'openai-codex/gpt-5.2'):
                cli = _resolve_openclaw_cli()
                cmd = [
                    cli,'cron','update',jid,
                    '--patch',
                    json.dumps({'payload': {'model':'openai-codex/gpt-5.2'}}, ensure_ascii=False)
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
