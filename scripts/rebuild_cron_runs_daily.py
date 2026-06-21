#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'

SH_TZ = ZoneInfo('Asia/Shanghai') if ZoneInfo else None


def ms_to_timeslot(run_at_ms: int) -> str:
    dt = datetime.fromtimestamp(run_at_ms / 1000.0, tz=SH_TZ)
    return dt.strftime('%H%M')


def infer_model_provider(e: dict) -> tuple[str | None, str | None]:
    model = e.get('model')
    provider = e.get('provider')
    err = (e.get('error') or '')

    # Heuristics based on known error strings
    m = re.search(r"Model not found\s+([\w\-\.]+)", err)
    if m:
        model = model or m.group(1)

    m = re.search(r"gpt-[\d\.]+", err)
    if m:
        model = model or m.group(0)

    provider = provider or 'openai-codex'
    return model, provider


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument('date', help='YYYYMMDD')
    ap.add_argument('--infile', default=None, help='default: guard_outputs/cron_runs_<date>.json')
    ap.add_argument('--outfile', default=None, help='default: guard_outputs/cron_runs_<date>.json (overwrite)')
    args = ap.parse_args()

    d = args.date
    infile = Path(args.infile) if args.infile else (GUARD / f'cron_runs_{d}.json')
    outfile = Path(args.outfile) if args.outfile else (GUARD / f'cron_runs_{d}.json')

    raw = json.loads(infile.read_text(encoding='utf-8'))
    entries = raw.get('entries') or []

    out_entries = []
    for e in entries:
        run_at_ms = int(e['runAtMs'])
        timeslot = e.get('timeslot') or ms_to_timeslot(run_at_ms)

        model, provider = infer_model_provider(e)

        out_entries.append({
            'jobId': raw.get('jobId') or e.get('jobId'),
            'sessionId': e.get('sessionId'),
            'runAtMs': run_at_ms,
            'timeslot': timeslot,
            'status': e.get('status'),
            'summary': e.get('summary'),
            'error': e.get('error'),
            'lastError': e.get('lastError'),
            'model': model,
            'provider': provider,
            'delivered': e.get('delivered'),
            'deliveryStatus': e.get('deliveryStatus'),
            'report_file': e.get('report_file') or e.get('report_file_path') or e.get('report_file'),
            'raw_run_record_ref': e.get('raw_run_record_ref'),
        })

    out = {
        'jobId': raw.get('jobId'),
        'source': raw.get('source'),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': d,
        'entries': out_entries,
    }
    outfile.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(outfile)


if __name__ == '__main__':
    main()
