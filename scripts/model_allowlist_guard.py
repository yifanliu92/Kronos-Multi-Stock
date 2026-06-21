#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'

ALLOWED = {
    'deepseek/deepseek-chat',
    'deepseek/deepseek-v4-flash',
}

# Explicitly blocked model spellings we have seen in cron runs.
BLOCKED_NOT_SUPPORTED = {
    'gpt-5.1',
    'openai-codex/gpt-5.1',
}

BLOCKED_NOT_FOUND = {
    'gpt-5.3-codex',
    'openai-codex/gpt-5.3-codex',
}

FALLBACK_MODEL = 'deepseek/deepseek-v4-flash'


def _now_ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y%m%d')


def normalize_model(model: str | None) -> str:
    if not model:
        return ''
    return str(model).strip()


def detect_provider() -> str:
    # Prefer explicit env if present
    for k in ('OPENCLAW_PROVIDER', 'OC_PROVIDER', 'provider'):
        v = os.environ.get(k)
        if v:
            return v.strip()
    # As a fallback, infer from process env context
    return os.environ.get('OPENCLAW_MODEL_PROVIDER', 'deepseek').strip() or 'deepseek'


def detect_model() -> str:
    # Try common env keys (cron runtime may set one of these)
    for k in (
        'OPENCLAW_MODEL',
        'OC_MODEL',
        'MODEL',
        'model',
    ):
        v = os.environ.get(k)
        if v:
            return v.strip()
    return ''


def classify_block(model: str) -> tuple[bool, str, str]:
    """Return: (allowlist_pass, blocked_reason, error_code)

    blocked_reason: '' when pass
    error_code: MODEL_NOT_SUPPORTED / MODEL_NOT_FOUND / ''
    """
    m = normalize_model(model)
    if m in ALLOWED:
        return True, '', ''

    # If model is empty, treat as pass (cannot enforce).
    if not m:
        return True, '', ''

    if m in BLOCKED_NOT_SUPPORTED or re.search(r"\bgpt-5\.1\b", m):
        return False, 'blocked_model', 'MODEL_NOT_SUPPORTED'

    if m in BLOCKED_NOT_FOUND or re.search(r"\bgpt-5\.3-codex\b", m):
        return False, 'blocked_model', 'MODEL_NOT_FOUND'

    # Unknown model: default block (fail-closed) to prevent silent drift.
    return False, 'model_not_in_allowlist', 'MODEL_NOT_SUPPORTED'


def append_daily_record(rec: dict) -> Path:
    GUARD.mkdir(parents=True, exist_ok=True)
    p = GUARD / f'model_guard_daily_{_today()}.json'

    payload = {'date': _today(), 'generated_at': _now_ts(), 'entries': []}
    if p.exists():
        try:
            payload = json.loads(p.read_text(encoding='utf-8'))
            if 'entries' not in payload or not isinstance(payload['entries'], list):
                payload['entries'] = []
        except Exception:
            payload = {'date': _today(), 'generated_at': _now_ts(), 'entries': []}

    payload['generated_at'] = _now_ts()
    payload['entries'].append(rec)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return p


def run_guard(task_name: str, job_id: str = '', model: str = '', provider: str = '', run_cmd: list[str] | None = None) -> dict:
    model = normalize_model(model)
    provider = (provider or '').strip() or detect_provider()

    allow_pass, blocked_reason, error_code = classify_block(model)

    rec = {
        'ts': _now_ts(),
        'jobId': job_id,
        'task_name': task_name,
        'original_model': model,
        'provider': provider,
        'allowlist_pass': bool(allow_pass),
        'blocked_reason': blocked_reason,
        'fallback_model': FALLBACK_MODEL,
        'fallback_attempted': False,
        'fallback_result': '',
        'final_model': model,
        'final_status': 'PASS' if allow_pass else 'BLOCKED',
    }

    # If blocked, attempt one controlled fallback execution of run_cmd (if provided)
    if (not allow_pass) and run_cmd:
        rec['fallback_attempted'] = True
        env = os.environ.copy()
        env['OPENCLAW_MODEL'] = FALLBACK_MODEL
        env['OC_MODEL'] = FALLBACK_MODEL
        env['MODEL'] = FALLBACK_MODEL

        try:
            cp = subprocess.run(run_cmd, env=env, capture_output=True, text=True)
            rec['fallback_result'] = f"exit={cp.returncode}"
            rec['final_model'] = FALLBACK_MODEL
            rec['final_status'] = 'FALLBACK_OK' if cp.returncode == 0 else 'FALLBACK_ERROR'
            # Pipe through stdout/stderr so caller gets normal output
            if cp.stdout:
                sys.stdout.write(cp.stdout)
            if cp.stderr:
                sys.stderr.write(cp.stderr)
        except Exception as e:
            rec['fallback_result'] = f"exception:{type(e).__name__}"
            rec['final_model'] = FALLBACK_MODEL
            rec['final_status'] = 'FALLBACK_EXCEPTION'

    append_daily_record(rec)

    # Also emit a compact JSON line to stdout for debugging / synthetic tests
    out = {
        'allowlist_pass': rec['allowlist_pass'],
        'error_code': error_code if not rec['allowlist_pass'] else '',
        'original_model': rec['original_model'],
        'final_model': rec['final_model'],
        'fallback_attempted': rec['fallback_attempted'],
        'fallback_result': rec['fallback_result'],
        'final_status': rec['final_status'],
    }
    rec['_guard_output'] = out
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-name', required=True)
    ap.add_argument('--jobId', default='')
    ap.add_argument('--model', default='')
    ap.add_argument('--provider', default='')
    ap.add_argument('--run-cmd', nargs=argparse.REMAINDER, help='Command to run after --run-cmd (optional)')
    args = ap.parse_args()

    model = args.model or detect_model()
    provider = args.provider or detect_provider()

    run_cmd = None
    if args.run_cmd:
        # argparse includes the leading "--" sometimes; strip if present
        run_cmd = [x for x in args.run_cmd if x != '--']
        if not run_cmd:
            run_cmd = None

    rec = run_guard(task_name=args.task_name, job_id=args.jobId, model=model, provider=provider, run_cmd=run_cmd)

    out = rec.get('_guard_output', {})
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")

    # Exit code convention for integration:
    # - 0: allowlist pass OR fallback succeeded
    # - 2: blocked and no fallback executed
    # - 3: blocked and fallback attempted but failed
    if out.get('allowlist_pass'):
        raise SystemExit(0)
    if out.get('fallback_attempted') and out.get('final_status') == 'FALLBACK_OK':
        raise SystemExit(0)
    if out.get('fallback_attempted'):
        raise SystemExit(3)
    raise SystemExit(2)


if __name__ == '__main__':
    main()
