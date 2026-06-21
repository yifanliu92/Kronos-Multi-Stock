#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')

# Default queue root (can be overridden by --queue-root)
Q = BASE / 'task_queue'
PENDING = Q / 'pending'
RUNNING = Q / 'running'
DONE = Q / 'done'
FAILED = Q / 'failed'
LOGS = Q / 'logs'


def set_queue_root(queue_root: Path) -> None:
    """Rebind module-level queue directories."""
    global Q, PENDING, RUNNING, DONE, FAILED, LOGS
    Q = queue_root
    PENDING = Q / 'pending'
    RUNNING = Q / 'running'
    DONE = Q / 'done'
    FAILED = Q / 'failed'
    LOGS = Q / 'logs'


def now_ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding='utf-8'))


def _save(p: Path, d: dict) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def run_one(task_path: Path) -> tuple[bool, Path]:
    task = _load(task_path)
    task_id = task['task_id']

    # Rate-limit protection gate: block P1/P2 when protection_mode=true
    try:
        cp = subprocess.run(
            ['python3', str(BASE / 'scripts' / 'rate_limit_guard.py'), '--check', '--task-name', task.get('task_name','unknown_task'), '--jobId', task_id],
            capture_output=True, text=True
        )
        if cp.returncode == 11:
            # blocked: move directly to failed without executing command
            RUNNING.mkdir(parents=True, exist_ok=True)
            FAILED.mkdir(parents=True, exist_ok=True)
            LOGS.mkdir(parents=True, exist_ok=True)
            running_path = RUNNING / task_path.name
            shutil.move(str(task_path), str(running_path))

            task['status'] = 'failed'
            task['start_time'] = now_ts()
            task['end_time'] = now_ts()
            task['duration_seconds'] = 0
            task['exit_code'] = 11
            task['error_message'] = 'RATE_LIMIT_PROTECTION'
            task['next_action'] = 'wait_for_user_confirm'

            log_path = Path(task.get('log_path') or (LOGS / f'{task_id}.log'))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open('w', encoding='utf-8') as f:
                f.write(f"[kronos_task_worker] blocked by rate_limit_guard task_id={task_id} task_name={task.get('task_name')}\n")
                f.write((cp.stdout or '') + (cp.stderr or ''))
            task['log_path'] = str(log_path)

            failed_path = FAILED / running_path.name
            _save(running_path, task)
            shutil.move(str(running_path), str(failed_path))
            return False, failed_path
    except Exception:
        # if guard fails, continue execution (best-effort)
        pass

    RUNNING.mkdir(parents=True, exist_ok=True)
    DONE.mkdir(parents=True, exist_ok=True)
    FAILED.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    running_path = RUNNING / task_path.name
    shutil.move(str(task_path), str(running_path))

    task['status'] = 'running'
    task['start_time'] = now_ts()
    _save(running_path, task)

    log_path = Path(task.get('log_path') or (LOGS / f'{task_id}.log'))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    try:
        with log_path.open('w', encoding='utf-8') as f:
            f.write(f"[kronos_task_worker] start {task_id} {task['task_name']} at {task['start_time']}\n")
            f.flush()
            cp = subprocess.run(task['command'], shell=True, cwd=str(BASE), stdout=f, stderr=subprocess.STDOUT)
        exit_code = int(cp.returncode)
    except Exception as e:
        exit_code = 1
        with log_path.open('a', encoding='utf-8') as f:
            f.write(f"\n[kronos_task_worker] exception: {type(e).__name__}: {e}\n")

    end = time.time()
    task['end_time'] = now_ts()
    task['duration_seconds'] = round(end - start, 3)
    task['exit_code'] = exit_code

    # best-effort output file discovery: read absolute paths printed in log (common pattern)
    out_files = []
    try:
        txt = log_path.read_text(encoding='utf-8', errors='ignore')
        for line in txt.splitlines():
            line=line.strip()
            if line.startswith('/Users/') and (line.endswith('.json') or line.endswith('.md') or line.endswith('.txt') or line.endswith('.csv')):
                out_files.append(line)
    except Exception:
        pass
    task['output_files'] = sorted(list(dict.fromkeys(out_files)))

    if exit_code == 0:
        task['status'] = 'done'
        task['error_message'] = None
        task['next_action'] = 'read outputs'
        done_path = DONE / running_path.name
        _save(running_path, task)
        shutil.move(str(running_path), str(done_path))
        return True, done_path

    task['status'] = 'failed'
    task['error_message'] = f'exit_code={exit_code}'
    task['next_action'] = 'inspect log; re-submit if needed'
    failed_path = FAILED / running_path.name
    _save(running_path, task)
    shutil.move(str(running_path), str(failed_path))
    return False, failed_path


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true', help='process a single task then exit')
    ap.add_argument('--task-id', default=None, help='execute specific pending/<task_id>.json only')
    ap.add_argument('--queue-root', default=str(BASE / 'task_queue'), help='override task_queue root for isolated tests')
    ap.add_argument('--loop', action='store_true', help='loop forever with sleep')
    ap.add_argument('--sleep', type=float, default=2.0)
    args = ap.parse_args()

    set_queue_root(Path(args.queue_root))

    Q.mkdir(parents=True, exist_ok=True)
    PENDING.mkdir(parents=True, exist_ok=True)

    def pick_one() -> Path | None:
        tasks = sorted(PENDING.glob('*.json'))
        return tasks[0] if tasks else None

    def emit(out_path: Path, ok: bool):
        try:
            d=_load(out_path)
            print(json.dumps({
                'task_id': d.get('task_id'),
                'task_name': d.get('task_name'),
                'status': d.get('status'),
                'exit_code': d.get('exit_code'),
                'log_path': d.get('log_path'),
                'output_files': d.get('output_files',[]),
                'error_message': d.get('error_message'),
            }, ensure_ascii=False, indent=2))
        except Exception:
            print(out_path)
        raise SystemExit(0 if ok else 1)

    if args.loop:
        while True:
            p = pick_one()
            if p:
                run_one(p)
            else:
                time.sleep(args.sleep)
        return

    # --once behavior
    if args.task_id:
        p = PENDING / f"{args.task_id}.json"
        if not p.exists():
            print(json.dumps({'task_id': args.task_id, 'status': 'TASK_NOT_FOUND'}, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        ok, out_path = run_one(p)
        emit(out_path, ok)

    # default: --once without --task-id -> process earliest pending only
    p = pick_one()
    if not p:
        print('no pending tasks')
        return
    ok, out_path = run_one(p)
    emit(out_path, ok)


if __name__ == '__main__':
    main()
