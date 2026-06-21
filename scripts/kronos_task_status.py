#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
Q = BASE / 'task_queue'


def now_ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def find_task(task_id: str) -> tuple[str, Path] | tuple[None, None]:
    for status in ['pending','running','done','failed']:
        p = Q / status / f'{task_id}.json'
        if p.exists():
            return status, p
    # fallback: search
    for status in ['pending','running','done','failed']:
        for p in (Q/status).glob(f'{task_id}*.json'):
            return status, p
    return None, None


def main() -> None:
    import sys
    if len(sys.argv) < 2:
        print('usage: kronos_task_status.py <task_id>')
        raise SystemExit(2)

    task_id = sys.argv[1]
    status, p = find_task(task_id)
    if not p:
        print(json.dumps({'task_id': task_id, 'status': 'not_found', 'next_action': 'check task_id'}, ensure_ascii=False, indent=2))
        return

    d = json.loads(p.read_text(encoding='utf-8'))
    start = d.get('start_time')
    elapsed = None
    if start and status == 'running':
        try:
            st = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
            elapsed = int((datetime.now() - st).total_seconds())
        except Exception:
            elapsed = None

    out = {
        'task_id': d.get('task_id'),
        'task_name': d.get('task_name'),
        'status': status,
        'start_time': d.get('start_time'),
        'elapsed_seconds': elapsed,
        'end_time': d.get('end_time'),
        'duration_seconds': d.get('duration_seconds'),
        'exit_code': d.get('exit_code'),
        'log_path': d.get('log_path'),
        'output_files': d.get('output_files', []),
        'error_message': d.get('error_message'),
        'next_action': d.get('next_action'),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
