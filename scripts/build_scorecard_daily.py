#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument('date', help='YYYYMMDD')
    args = ap.parse_args()
    d = args.date

    cov_p = GUARD / f'slot_coverage_daily_{d}.json'
    if not cov_p.exists():
        raise SystemExit(f'missing {cov_p}')

    cov = json.loads(cov_p.read_text(encoding='utf-8'))
    slots = cov.get('slots', [])

    total = len(slots)
    ok = [s for s in slots if s.get('status') == 'SUCCESS']
    bad = [s for s in slots if s.get('status') != 'SUCCESS']

    missing_reasons = []
    for s in bad:
        missing_reasons.append({
            'timeslot': s.get('timeslot'),
            'status': s.get('status'),
            'error_category': s.get('error_category'),
            'error_code': s.get('error_code'),
            'error_detail': s.get('error_detail'),
            'model_used': s.get('model_used'),
            'provider_used': s.get('provider_used'),
            'report_file': s.get('report_file'),
            'deliveryStatus': s.get('deliveryStatus'),
            'reason': s.get('reason'),
            'critical': bool(s.get('critical')),
        })

    critical_missing = [s for s in missing_reasons if s.get('critical')]

    payload = {
        'version': 'scorecard_daily_v0.4',
        'date': d,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_slots': total,
        'success_slots': len(ok),
        'missing_slots': len(bad),
        'critical_missing_slots': [s.get('timeslot') for s in critical_missing],
        'missing_reasons': missing_reasons,
    }

    out = GUARD / f'scorecard_daily_{d}.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out)


if __name__ == '__main__':
    main()
