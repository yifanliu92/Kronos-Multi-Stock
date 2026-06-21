#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import sys
import uuid
from datetime import datetime
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
Q = BASE / 'task_queue'
PENDING = Q / 'pending'


def now_ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def main() -> None:
    if len(sys.argv) < 3:
        print('usage: kronos_submit_task.py <task_name> <command>')
        raise SystemExit(2)

    task_name = sys.argv[1]
    command = sys.argv[2]

    task_id = datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8]

    Q.mkdir(parents=True, exist_ok=True)
    PENDING.mkdir(parents=True, exist_ok=True)

    payload = {
        'task_id': task_id,
        'task_name': task_name,
        'status': 'pending',
        'created_at': now_ts(),
        'command': command,
        'start_time': None,
        'end_time': None,
        'duration_seconds': None,
        'exit_code': None,
        'log_path': str(Q / 'logs' / f'{task_id}.log'),
        'output_files': [],
        'error_message': None,
        'next_action': 'run worker: python3 scripts/kronos_task_worker.py --once'
    }

    out = PENDING / f'{task_id}.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print('任务已提交：')
    print(f'- task_id: {task_id}')
    print(f'- task_name: {task_name}')
    print(f'- status: pending')
    print(f'- 查询命令: python3 scripts/kronos_task_status.py {task_id}')


if __name__ == '__main__':
    main()
