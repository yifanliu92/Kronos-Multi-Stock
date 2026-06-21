#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

CRON_JOBS = Path('/Users/wxo/.openclaw/cron/jobs.json')
OUT = Path('/Users/wxo/Desktop/Kronos/guard_outputs')
OUT.mkdir(parents=True, exist_ok=True)


def parse_field(field: str, min_v: int, max_v: int):
    """Parse a single cron field supporting: '*', 'a', 'a-b', '*/n', 'a-b/n'."""
    field = field.strip()
    out=set()
    if field == '*':
        return list(range(min_v, max_v+1))
    parts = field.split(',')
    for part in parts:
        part=part.strip()
        if not part:
            continue
        if part == '*':
            out.update(range(min_v, max_v+1));
            continue
        if '/' in part:
            base, step_s = part.split('/',1)
            step=int(step_s)
            if base == '*':
                start=min_v; end=max_v
            elif '-' in base:
                a,b=base.split('-',1)
                start=int(a); end=int(b)
            else:
                start=int(base); end=max_v
            out.update(range(start, end+1, step))
        elif '-' in part:
            a,b=part.split('-',1)
            out.update(range(int(a), int(b)+1))
        else:
            out.add(int(part))
    return sorted([x for x in out if min_v <= x <= max_v])


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('date', help='YYYYMMDD')
    ap.add_argument('--jobId', default='fe1bd245-0f04-41c6-a91b-1903af58bf6a')
    args=ap.parse_args()

    date=args.date
    jobs=json.loads(CRON_JOBS.read_text(encoding='utf-8'))['jobs']
    job=next((j for j in jobs if j.get('id')==args.jobId), None)
    if not job:
        raise SystemExit(f'job not found: {args.jobId}')
    if not job.get('enabled', False):
        raise SystemExit(f'job disabled: {args.jobId}')
    sch=job.get('schedule',{})
    expr=sch.get('expr','')
    tz=sch.get('tz','')
    if sch.get('kind')!='cron':
        raise SystemExit('only cron kind supported')

    fields=expr.split()
    if len(fields)!=5:
        raise SystemExit(f'bad cron expr: {expr}')
    minute_f, hour_f, dom_f, mon_f, dow_f = fields

    # For this audit we only expand minute+hour; assume date already within dow range.
    minutes=parse_field(minute_f,0,59)
    hours=parse_field(hour_f,0,23)

    expected=[]
    for h in hours:
        for m in minutes:
            expected.append(f"{h:02d}{m:02d}")
    expected=sorted(set(expected))

    payload={
        'date': date,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'expected_timeslots': expected,
        'source_job_id': job.get('id'),
        'source_job_name': job.get('name'),
        'source_cron_expression': expr,
        'timezone': tz,
        'parse_method': 'custom_cron_field_parser_v1',
    }

    out=OUT/f'expected_slots_{date}.json'
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out)

if __name__=='__main__':
    main()
