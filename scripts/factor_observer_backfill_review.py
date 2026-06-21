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
    for s in stats_list:
        keys.update((s or {}).keys())
    out={}
    for k in sorted(keys):
        n=0; ws=0.0
        for s in stats_list:
            x=(s or {}).get(k,{})
            nx=int(x.get('n',0) or 0)
            rv=x.get('avg_next30_ret')
            if isinstance(rv,(int,float)) and nx>0:
                ws += rv*nx
                n += nx
        out[k]={'n':n,'avg_next30_ret':(ws/n if n else None)}
    return out


def load_daily_json(path: Path):
    d=json.loads(path.read_text(encoding='utf-8'))
    # normalize
    d.setdefault('generated_at', '')
    d.setdefault('records', 0)
    d.setdefault('relation_stats_next30m', {})
    return d


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--start', default='20260511')
    ap.add_argument('--end', default='20260521')
    ap.add_argument('--version', default='v0.3')
    args=ap.parse_args()

    start=args.start; end=args.end
    v=args.version

    # live: factor_observer_daily_YYYYMMDD.json (no _backfill)
    live_files=sorted(GUARD.glob('factor_observer_daily_*.json'))
    live_by_day={}
    for p in live_files:
        name=p.name
        if '_backfill' in name: continue
        if name.count('_')!=2:  # factor_observer_daily_YYYYMMDD.json only
            continue
        day=name.split('_')[-1].split('.')[0]
        if len(day)!=8: continue
        if day<start or day>end: continue
        d=load_daily_json(p)
        # keep latest generated_at if duplicates exist (shouldn't for live)
        live_by_day.setdefault(day, (p,d))

    # backfill: factor_observer_daily_YYYYMMDD_v0.3_backfill.json
    bf_files=sorted(GUARD.glob(f'factor_observer_daily_*_{v}_backfill.json'))
    bf_by_day={}
    for p in bf_files:
        day=p.name.split('_')[3]  # factor observer daily YYYYMMDD ...
        if day<start or day>end: continue
        d=load_daily_json(p)
        cur=bf_by_day.get(day)
        if not cur:
            bf_by_day[day]=(p,d)
        else:
            # prefer latest generated_at lexicographically
            if str(d.get('generated_at','')) >= str(cur[1].get('generated_at','')):
                bf_by_day[day]=(p,d)

    def summarize(by_day: dict):
        days=sorted(by_day.keys())
        rows=[by_day[k][1] for k in days]
        rel=merge_rel([r.get('relation_stats_next30m',{}) for r in rows])
        total_records=sum(int(r.get('records',0) or 0) for r in rows)
        factor_avail_ratio=avg([r.get('factor_available_ratio',0) for r in rows])
        vol_ratio=avg([r.get('volume_available_ratio',0) for r in rows])
        mom_ratio=avg([r.get('momentum_available_ratio',0) for r in rows])
        vola_ratio=avg([r.get('volatility_available_ratio',0) for r in rows])

        keep=rel.get('hint_keep',{})
        caution=rel.get('hint_caution',{})
        dgc=rel.get('downgrade_candidate',{})
        mp=rel.get('mom_pass',{})
        mf=rel.get('mom_fail',{})

        keep_avg=keep.get('avg_next30_ret')
        caution_avg=caution.get('avg_next30_ret')
        dgc_avg=dgc.get('avg_next30_ret')
        mp_avg=mp.get('avg_next30_ret')
        mf_avg=mf.get('avg_next30_ret')

        insufficient_n=int(rel.get('hint_insufficient_data',{}).get('n',0) or 0)
        valid_relation_n=int(keep.get('n',0) or 0)+int(caution.get('n',0) or 0)+int(rel.get('hint_downgrade',{}).get('n',0) or 0)
        denom=valid_relation_n + insufficient_n
        insufficient_ratio=(insufficient_n/denom) if denom else 0.0

        return {
            'n_days': len(days),
            'days': days,
            'total_records': total_records,
            'factor_available_ratio': factor_avail_ratio,
            'volume_available_ratio': vol_ratio,
            'momentum_available_ratio': mom_ratio,
            'volatility_available_ratio': vola_ratio,
            'relation_stats_next30m': rel,
            'valid_relation_sample_count': valid_relation_n,
            'insufficient_data_ratio': insufficient_ratio,
            'hint_keep_vs_caution_spread': (None if keep_avg is None or caution_avg is None else keep_avg-caution_avg),
            'caution_hit_rate': (None if int(caution.get('n',0) or 0)==0 else (1.0 if caution_avg is not None and caution_avg<0 else 0.0)),
            'downgrade_candidate_hit_rate': (None if int(dgc.get('n',0) or 0)==0 else (1.0 if dgc_avg is not None and dgc_avg<0 else 0.0)),
            'mom_pass_vs_fail_spread': (None if mp_avg is None or mf_avg is None else mp_avg-mf_avg),
            'hint_keep_avg_next30_ret': keep_avg,
            'hint_caution_avg_next30_ret': caution_avg,
            'downgrade_candidate_avg_next30_ret': dgc_avg,
            'mom_pass_avg_next30_ret': mp_avg,
            'mom_fail_avg_next30_ret': mf_avg,
        }

    live = summarize(live_by_day)
    bf = summarize(bf_by_day)

    combined_days=sorted(set(live['days']) | set(bf['days']))

    payload={
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'range': {'start': start, 'end': end, 'version': v},
        'live': live,
        'backfill': bf,
        'combined_n_days': len(combined_days),
        'combined_days': combined_days,
        'note': 'observer-only; backfill rows are retrospective_backfill=true'
    }

    out_json=GUARD / f'factor_observer_backfill_{start}_{end}_{v}.json'
    out_md=DAILY / f'factor_observer_backfill_{start}_{end}_{v}.md'
    out_json.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')

    md=[
        f"# factor_observer_backfill {start}-{end} ({v})",
        f"- generated_at: {payload['generated_at']}",
        f"- live_n_days: {live['n_days']}",
        f"- backfill_n_days: {bf['n_days']}",
        f"- combined_n_days: {payload['combined_n_days']}",
        f"- live_days: {', '.join(live['days']) if live['days'] else 'none'}",
        f"- backfill_days: {', '.join(bf['days']) if bf['days'] else 'none'}",
        f"- combined_days: {', '.join(payload['combined_days']) if payload['combined_days'] else 'none'}",
        "",
        "## Backfill summary",
        f"- total_records: {bf['total_records']}",
        f"- factor_available_ratio: {bf['factor_available_ratio']:.2%}",
        f"- volume_available_ratio: {bf['volume_available_ratio']:.2%}",
        f"- momentum_available_ratio: {bf['momentum_available_ratio']:.2%}",
        f"- volatility_available_ratio: {bf['volatility_available_ratio']:.2%}",
        f"- hint_keep_vs_caution_spread: {bf['hint_keep_vs_caution_spread']}",
        f"- caution_hit_rate: {bf['caution_hit_rate']}",
        f"- downgrade_candidate_hit_rate: {bf['downgrade_candidate_hit_rate']}",
        f"- mom_pass_vs_fail_spread: {bf['mom_pass_vs_fail_spread']}",
        f"- valid_relation_sample_count: {bf['valid_relation_sample_count']}",
        f"- insufficient_data_ratio: {bf['insufficient_data_ratio']:.2%}",
    ]
    out_md.write_text('\n'.join(md)+'\n',encoding='utf-8')

    print(out_json)
    print(out_md)

if __name__=='__main__':
    main()
