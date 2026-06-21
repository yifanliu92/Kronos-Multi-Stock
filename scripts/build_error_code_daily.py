#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

BASE=Path('/Users/wxo/Desktop/Kronos')
GUARD=BASE/'guard_outputs'


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('date', help='YYYYMMDD')
    args=ap.parse_args()
    d=args.date

    cov_p = GUARD / f'slot_coverage_daily_{d}.json'
    if not cov_p.exists():
        raise SystemExit(f'missing {cov_p}')
    cov=json.loads(cov_p.read_text(encoding='utf-8'))
    slots=cov.get('slots',[])

    total=len(slots)
    success=sum(1 for s in slots if s.get('status') in ('SUCCESS','RETRY_SUCCESS'))
    missing=sum(1 for s in slots if s.get('status') not in ('SUCCESS','RETRY_SUCCESS'))
    failed=sum(1 for s in slots if s.get('status')=='FAIL')
    delivery_failed=sum(1 for s in slots if s.get('status')=='DELIVERY_FAILED')
    retry_success=sum(1 for s in slots if s.get('status')=='RETRY_SUCCESS')

    codes={}
    for s in slots:
        code=str(s.get('error_code') or '')
        if not code:
            continue
        codes[code]=codes.get(code,0)+1

    critical_missing=[s.get('timeslot') for s in slots if s.get('critical') and s.get('status') not in ('SUCCESS','RETRY_SUCCESS')]

    payload={
        'version':'error_code_daily_v0.3',
        'date': d,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_slots': total,
        'success_slots': success,
        'missing_slots': missing,
        'failed_slots': failed,
        'delivery_failed_count': delivery_failed,
        'retry_success_count': retry_success,
        'critical_slots_missing': critical_missing,
        'error_codes': codes,
    }
    out=GUARD/f'error_code_daily_{d}.json'
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out)

if __name__=='__main__':
    main()
