#!/usr/bin/env python3
from __future__ import annotations
import json, math
import os
from pathlib import Path
from datetime import datetime
from statistics import pstdev

BASE = Path('/Users/wxo/Desktop/Kronos')
MAIN_DIR = BASE / 'sim_logs_daily'
SHADOW_DIR = BASE / 'shadow_logs_daily'
OUT_GUARD = BASE / 'guard_outputs'
OUT_DAILY = BASE / 'daily_reports'
OUT_GUARD.mkdir(parents=True, exist_ok=True)
OUT_DAILY.mkdir(parents=True, exist_ok=True)


def load_day_rows(day: str, strategy: str):
    folder = MAIN_DIR if strategy == 'main' else SHADOW_DIR
    p = folder / f'sim_trades_603305_{day}.jsonl'
    if not p.exists():
        return []
    rows = []
    for ln in p.read_text(encoding='utf-8').splitlines():
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    rows.sort(key=lambda r: r.get('ts', ''))
    return rows


def compute_rows(rows, strategy):
    out = []
    prices = []
    vols = []  # currently unavailable in source logs
    for i, r in enumerate(rows):
        price = r.get('price')
        price_signal = r.get('signal', 'na')

        # volume unavailable in current log schema
        volume_ratio = None
        volume_confirm = 'na'
        volume_available = False
        volume_method = 'unavailable'

        # volatility: price std/price over recent N prices if enough (NOT ATR)
        volatility_ratio = None
        volatility_filter = 'na'
        volatility_method = 'price_std_14_over_price'
        if isinstance(price, (int, float)):
            prices.append(float(price))
        if len(prices) >= 14 and price:
            window = prices[-14:]
            volatility_ratio = (pstdev(window) / float(price)) if float(price) != 0 else None
            if volatility_ratio is not None:
                volatility_filter = 'pass' if volatility_ratio < 0.02 else 'caution'

        # momentum 30m ~= 3 bars with 10m cadence
        momentum_30m = None
        momentum_confirm = 'na'
        momentum_method = 'price_t_over_price_t_minus_3bars_minus_1'
        if len(prices) >= 4 and prices[-4] != 0:
            momentum_30m = prices[-1] / prices[-4] - 1
            momentum_confirm = 'pass' if momentum_30m > 0 else 'fail'

        # observer-only caution/downgrade_candidate rules (no trading impact)
        if momentum_confirm == 'na' or volatility_filter == 'na':
            hint = 'insufficient_data'
        else:
            opposite_momentum = (
                (price_signal in ('偏多', '强多') and momentum_confirm == 'fail') or
                (price_signal in ('偏空', '强空') and momentum_confirm == 'pass')
            )
            if opposite_momentum:
                hint = 'caution'
            else:
                hint = 'keep'

            # volatility quantile proxy over last 20 bars
            if len(prices) >= 20 and volatility_ratio is not None:
                tail = prices[-20:]
                local_vols = []
                for j in range(14, len(tail)+1):
                    w = tail[j-14:j]
                    if w[-1] != 0:
                        local_vols.append(pstdev(w)/w[-1])
                if local_vols:
                    q80 = sorted(local_vols)[int(0.8*(len(local_vols)-1))]
                    if volatility_ratio > q80:
                        hint = 'caution'

        # downgrade_candidate: consecutive momentum_fail with extreme price signal
        downgrade_candidate = False
        if len(out) >= 2 and momentum_confirm == 'fail' and price_signal in ('强多', '强空'):
            prev1 = out[-1].get('momentum_confirm') == 'fail'
            prev2 = out[-2].get('momentum_confirm') == 'fail'
            if prev1 and prev2:
                downgrade_candidate = True

        row = {
            'ts': r.get('ts'),
            'strategy': strategy,
            'price': price,
            'price_signal': price_signal,
            'volume_ratio': volume_ratio,
            'volume_confirm': volume_confirm,
            'volume_method': volume_method,
            'volatility_ratio': volatility_ratio,
            'volatility_filter': volatility_filter,
            'volatility_method': volatility_method,
            'momentum_30m': momentum_30m,
            'momentum_confirm': momentum_confirm,
            'momentum_method': momentum_method,
            'factor_hint': hint,
            'downgrade_candidate': downgrade_candidate,
            'factor_available': (momentum_confirm != 'na' and volatility_filter != 'na'),
            'factor_missing_reason': None if (momentum_confirm != 'na' and volatility_filter != 'na') else 'insufficient_history_or_missing_volume',
            'volume_available': volume_available,
            'momentum_available': momentum_confirm != 'na',
            'volatility_available': volatility_filter != 'na',
        }
        out.append(row)
    return out


def main():
    # P1.1: model allowlist guard
    try:
        from scripts.model_allowlist_guard import run_guard
        run_guard(task_name='factor_observer_603305', job_id=os.environ.get('OPENCLAW_CRON_JOB_ID','') or os.environ.get('JOB_ID',''), model=os.environ.get('OPENCLAW_MODEL') or os.environ.get('MODEL') or '', provider=os.environ.get('OPENCLAW_PROVIDER') or os.environ.get('PROVIDER') or '')
    except Exception:
        pass

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', help='YYYY-MM-DD (default: today)')
    ap.add_argument('--mode', choices=['live','backfill'], default='live')
    ap.add_argument('--version', default='v0.3', help='tag for backfill outputs')
    args = ap.parse_args()

    day_file = args.day or datetime.now().strftime('%Y-%m-%d')
    day = day_file.replace('-','')

    main_rows = load_day_rows(day_file, 'main')
    shadow_rows = load_day_rows(day_file, 'shadow')
    factor_rows = compute_rows(main_rows, 'main') + compute_rows(shadow_rows, 'shadow')
    factor_rows.sort(key=lambda x: (x.get('ts') or '', x.get('strategy') or ''))

    n = len(factor_rows)
    vol_ok = sum(1 for r in factor_rows if r['volume_available'])
    mom_ok = sum(1 for r in factor_rows if r['momentum_available'])
    vola_ok = sum(1 for r in factor_rows if r['volatility_available'])
    avail = sum(1 for r in factor_rows if r['factor_available'])
    caution = sum(1 for r in factor_rows if r['factor_hint'] == 'caution')
    downgrade = sum(1 for r in factor_rows if r['factor_hint'] == 'downgrade')

    # simple relation stats vs next 30m return proxy (3 bars)
    def next30_stats(fr):
        by = {
            'hint_keep': [], 'hint_insufficient_data': [], 'hint_caution': [], 'hint_downgrade': [],
            'mom_pass': [], 'mom_fail': [], 'vol_pass': [], 'vol_caution': [], 'downgrade_candidate': []
        }
        for i, x in enumerate(fr):
            p = x.get('price')
            if not isinstance(p, (int, float)) or i + 3 >= len(fr):
                continue
            p2 = fr[i+3].get('price')
            if not isinstance(p2, (int, float)) or p == 0:
                continue
            r = p2 / p - 1
            by[f"hint_{x.get('factor_hint')}"] = by.get(f"hint_{x.get('factor_hint')}", []) + [r]
            if x.get('downgrade_candidate') is True: by['downgrade_candidate'].append(r)
            if x.get('momentum_confirm') == 'pass': by['mom_pass'].append(r)
            if x.get('momentum_confirm') == 'fail': by['mom_fail'].append(r)
            if x.get('volatility_filter') == 'pass': by['vol_pass'].append(r)
            if x.get('volatility_filter') == 'caution': by['vol_caution'].append(r)
        def avg(v): return (sum(v)/len(v)) if v else None
        return {k:{'n':len(v),'avg_next30_ret':avg(v)} for k,v in by.items()}

    relation_stats = next30_stats(factor_rows)

    payload = {
        'date': day,
        'symbol': '603305',
        'records': n,
        'factor_available': avail > 0,
        'factor_available_ratio': (avail / n if n else 0),
        'volume_available': vol_ok > 0,
        'volume_available_ratio': (vol_ok / n if n else 0),
        'momentum_available': mom_ok > 0,
        'momentum_available_ratio': (mom_ok / n if n else 0),
        'volatility_available': vola_ok > 0,
        'volatility_available_ratio': (vola_ok / n if n else 0),
        'downgrade_count': downgrade,
        'caution_count': caution,
        'relation_stats_next30m': relation_stats,
        'factor_rows': factor_rows,
        'retrospective_backfill': (args.mode == 'backfill'),
        'mode': args.mode,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source_range': day_file,
    }

    if args.mode == 'live':
        out_json = OUT_GUARD / f'factor_observer_daily_{day}.json'
        out_md = OUT_DAILY / f'factor_observer_summary_{day}.md'
    else:
        out_json = OUT_GUARD / f'factor_observer_daily_{day}_{args.version}_backfill.json'
        out_md = OUT_DAILY / f'factor_observer_summary_{day}_{args.version}_backfill.md'

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    md = [
        f"# Factor Observer Summary {day}",
        f"- symbol: 603305",
        f"- records: {n}",
        f"- factor_available_ratio: {payload['factor_available_ratio']:.2%}",
        f"- volume_available_ratio: {payload['volume_available_ratio']:.2%}",
        f"- momentum_available_ratio: {payload['momentum_available_ratio']:.2%}",
        f"- volatility_available_ratio: {payload['volatility_available_ratio']:.2%}",
        f"- downgrade_count: {downgrade}",
        f"- caution_count: {caution}",
        "- note: observer-only, no trade action changed."
    ]
    out_md.write_text('\n'.join(md) + '\n', encoding='utf-8')

    print(out_json)
    print(out_md)
    print(f"factor_available_ratio={(avail/n if n else 0):.4f}")


if __name__ == '__main__':
    main()
