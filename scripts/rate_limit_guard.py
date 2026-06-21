#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'
STATE_PATH = GUARD / 'rate_limit_state.json'


def now_ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def today() -> str:
    return datetime.now().strftime('%Y%m%d')


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            'version': 'rate_limit_guard_v0.1',
            'protection_mode': False,
            'entered_at': None,
            'last_notice_at': None,
            'events': []  # last N events
        }
    try:
        return json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {
            'version': 'rate_limit_guard_v0.1',
            'protection_mode': False,
            'entered_at': None,
            'last_notice_at': None,
            'events': []
        }


def save_state(st: dict) -> None:
    GUARD.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')


def append_daily(entry: dict) -> Path:
    GUARD.mkdir(parents=True, exist_ok=True)
    p = GUARD / f'rate_limit_daily_{today()}.json'
    payload = {
        'date': today(),
        'generated_at': now_ts(),
        'model_call_count_estimate': 0,
        'cron_trigger_count': 0,
        'telegram_reply_count': 0,
        'failed_call_count': 0,
        'rate_limit_count': 0,
        'entries': []
    }
    if p.exists():
        try:
            payload = json.loads(p.read_text(encoding='utf-8'))
            if 'entries' not in payload or not isinstance(payload['entries'], list):
                payload['entries'] = []
        except Exception:
            pass

    payload['generated_at'] = now_ts()
    payload['entries'].append(entry)

    # best-effort counters
    payload['model_call_count_estimate'] = int(payload.get('model_call_count_estimate') or 0) + (1 if entry.get('kind')=='model_call' else 0)
    payload['cron_trigger_count'] = int(payload.get('cron_trigger_count') or 0) + (1 if entry.get('kind')=='cron_trigger' else 0)
    payload['telegram_reply_count'] = int(payload.get('telegram_reply_count') or 0) + (1 if entry.get('kind')=='telegram_reply' else 0)
    payload['failed_call_count'] = int(payload.get('failed_call_count') or 0) + (1 if entry.get('kind') in ('model_error','timeout','blocked') else 0)
    payload['rate_limit_count'] = int(payload.get('rate_limit_count') or 0) + (1 if entry.get('kind')=='rate_limit' else 0)

    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return p


def classify_grade(task_name: str) -> str:
    t = (task_name or '').lower()
    # P0 allowlist
    if any(k in t for k in ['603305_every10', 'auto_report_guard', 'model_guard', 'heal', 'close_review', 'sim_review']):
        return 'P0'
    # P1 governance
    if any(k in t for k in ['intraday_chain_review', 'main_shadow_review', 'template_enhancement', 'strategy_param_proposal', 'regression', 'scorecard', 'slot_coverage']):
        return 'P1'
    # default conservative
    return 'P1'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='Check whether task is allowed')
    ap.add_argument('--task-name', default='unknown_task')
    ap.add_argument('--jobId', default='unknown_job')
    ap.add_argument('--force-protection-on', action='store_true')
    ap.add_argument('--force-protection-off', action='store_true')
    args = ap.parse_args()

    st = load_state()

    if args.force_protection_on:
        st['protection_mode'] = True
        st['entered_at'] = now_ts()
        save_state(st)
        print(json.dumps({'ok': True, 'protection_mode': True}, ensure_ascii=False))
        return

    if args.force_protection_off:
        st['protection_mode'] = False
        st['entered_at'] = None
        save_state(st)
        print(json.dumps({'ok': True, 'protection_mode': False}, ensure_ascii=False))
        return

    grade = classify_grade(args.task_name)

    allowed = True
    blocked_reason = ''
    protection = bool(st.get('protection_mode'))

    if protection and grade in ('P1','P2'):
        allowed = False
        blocked_reason = 'RATE_LIMIT_PROTECTION'

    entry = {
        'ts': now_ts(),
        'kind': 'blocked' if not allowed else 'check',
        'task_name': args.task_name,
        'task_grade': grade,
        'jobId': args.jobId,
        'protection_mode': protection,
        'blocked_reason': blocked_reason,
        'next_allowed_action': 'wait_for_user_confirm' if (not allowed) else 'execute'
    }
    append_daily(entry)

    out = {
        'allowed': allowed,
        'task_grade': grade,
        'protection_mode': protection,
        'blocked_reason': blocked_reason,
    }
    print(json.dumps(out, ensure_ascii=False))
    raise SystemExit(0 if allowed else 11)


if __name__ == '__main__':
    main()
