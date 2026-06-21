#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'
DAILY = BASE / 'daily_reports'


def avg(vals):
    vals=[v for v in vals if isinstance(v,(int,float))]
    return (sum(vals)/len(vals)) if vals else 0.0


def merge_rel(stats_list):
    keys=set()
    for s in stats_list: keys.update(s.keys())
    out={}
    for k in sorted(keys):
        n=0; ws=0.0
        for s in stats_list:
            x=s.get(k,{})
            nx=int(x.get('n',0) or 0)
            rv=x.get('avg_next30_ret')
            if isinstance(rv,(int,float)) and nx>0:
                ws += rv*nx
                n += nx
        out[k]={'n':n,'avg_next30_ret':(ws/n if n else None)}
    return out


def _pick_latest_per_day(paths):
    by={}
    for p in paths:
        try:
            d=json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        day=str(d.get('date') or '')
        if not day:
            # fallback: try parse from filename
            day=p.name.split('_')[-1].split('.')[0]
        ga=str(d.get('generated_at',''))
        if day not in by:
            by[day]=(p,d,ga)
        else:
            if ga >= by[day][2]:
                by[day]=(p,d,ga)
    # return in day order
    out=[by[k][1] for k in sorted(by.keys()) if k]
    return out


def main():
    # Live-only 5d review (do not mix backfill)
    live_paths=[]
    for p in GUARD.glob('factor_observer_daily_*.json'):
        name=p.name
        if '_backfill' in name:
            continue
        # only accept canonical live daily: factor_observer_daily_YYYYMMDD.json
        if name.count('_')==3 and name.endswith('.json'):
            live_paths.append(p)
    live_rows=_pick_latest_per_day(live_paths)
    rows=live_rows[-5:]
    rel=[d.get('relation_stats_next30m',{}) for d in rows]

    rel5 = merge_rel(rel)
    keep = rel5.get('hint_keep', {})
    caution = rel5.get('hint_caution', {})
    dgc = rel5.get('downgrade_candidate', {})
    mom_pass = rel5.get('mom_pass', {})
    mom_fail = rel5.get('mom_fail', {})

    keep_avg = keep.get('avg_next30_ret')
    caution_avg = caution.get('avg_next30_ret')
    dgc_avg = dgc.get('avg_next30_ret')
    mp_avg = mom_pass.get('avg_next30_ret')
    mf_avg = mom_fail.get('avg_next30_ret')

    days_raw = [r.get('date') for r in rows]
    days = []
    for x in days_raw:
        if x and x not in days:
            days.append(x)

    total_records = sum(int(r.get('records',0) or 0) for r in rows)
    payload={
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'days': days,
        'n_days': len(days),
        'total_records': total_records,
        'mode': 'live_only',
        'factor_available_ratio_5d': avg([r.get('factor_available_ratio',0) for r in rows]),
        'volume_available_ratio_5d': avg([r.get('volume_available_ratio',0) for r in rows]),
        'momentum_available_ratio_5d': avg([r.get('momentum_available_ratio',0) for r in rows]),
        'volatility_available_ratio_5d': avg([r.get('volatility_available_ratio',0) for r in rows]),
        'relation_stats_next30m_5d': rel5,
        'hint_keep_vs_caution_spread': (None if keep_avg is None or caution_avg is None else keep_avg - caution_avg),
        'caution_hit_rate': (None if caution.get('n',0)==0 else (1.0 if caution_avg is not None and caution_avg < 0 else 0.0)),
        'downgrade_candidate_hit_rate': (None if dgc.get('n',0)==0 else (1.0 if dgc_avg is not None and dgc_avg < 0 else 0.0)),
        'mom_pass_vs_fail_spread': (None if mp_avg is None or mf_avg is None else mp_avg - mf_avg),
    }

    out_json=GUARD / 'factor_observer_5d_review.json'
    out_md=DAILY / 'factor_observer_5d_review.md'
    out_json.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')

    md=[
        '# factor_observer_5d_review',
        f"- n_days: {payload['n_days']}",
        f"- days: {', '.join(payload['days']) if payload['days'] else 'none'}",
        f"- factor_available_ratio_5d: {payload['factor_available_ratio_5d']:.2%}",
        f"- volume_available_ratio_5d: {payload['volume_available_ratio_5d']:.2%}",
        f"- momentum_available_ratio_5d: {payload['momentum_available_ratio_5d']:.2%}",
        f"- volatility_available_ratio_5d: {payload['volatility_available_ratio_5d']:.2%}",
        '- relation_stats_next30m_5d: see JSON',
        f"- hint_keep_vs_caution_spread: {payload['hint_keep_vs_caution_spread']}",
        f"- caution_hit_rate: {payload['caution_hit_rate']}",
        f"- downgrade_candidate_hit_rate: {payload['downgrade_candidate_hit_rate']}",
        f"- mom_pass_vs_fail_spread: {payload['mom_pass_vs_fail_spread']}",
        '- decision_gate: observer-only unless user confirms + thresholds met.'
    ]
    out_md.write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(out_json)
    print(out_md)

if __name__=='__main__':
    main()
