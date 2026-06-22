#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime
import csv

BASE = Path('/Users/wxo/Desktop/Kronos')
state_path = BASE / 'sim_state_603305.json'
cost_path = BASE / 'sim_costs_603305.json'
trades_path = BASE / 'sim_logs_daily' / f"sim_trades_603305_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
out_dir = BASE / 'strategy_compare_reports'
out_dir.mkdir(parents=True, exist_ok=True)
out_csv = out_dir / f"reconcile_603305_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
out_json = out_dir / f"reconcile_603305_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"


def load_json(p: Path):
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)


def load_jsonl(p: Path):
    rows = []
    if not p.exists():
        return rows
    with p.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    state = load_json(state_path)
    costs = load_json(cost_path)
    trades = load_jsonl(trades_path)

    base_capital = float(costs.get('base_capital_cny') or state.get('base_capital_cny') or 0)
    if base_capital <= 0:
        raise SystemExit('base_capital_cny invalid')

    avg_entry = float(state.get('avg_entry_price') or 0)
    last_price = float(state.get('last_price') or 0)
    pos_pct = float(state.get('position_pct') or 0)

    position_notional = base_capital * pos_pct / 100.0
    unrealized_amt = position_notional * ((last_price / avg_entry) - 1.0) if avg_entry > 0 and position_notional > 0 else 0.0

    sell_cost_total = 0.0
    realized_est_total = 0.0
    rows = []

    for t in trades:
        p_from = float(t.get('position_from', 0) or 0)
        p_to = float(t.get('position_to', 0) or 0)
        delta = p_to - p_from
        trade_price = float(t.get('price', 0) or 0)
        c = t.get('cost') or {}
        trade_cost = float(c.get('total_cost', 0) or 0)

        realized_est = 0.0
        side = 'hold'
        if delta < 0:  # reduce long
            side = 'sell'
            sold_pct = -delta
            sold_notional = base_capital * sold_pct / 100.0
            if avg_entry > 0 and trade_price > 0:
                realized_est = sold_notional * ((trade_price / avg_entry) - 1.0)
            sell_cost_total += trade_cost
            realized_est_total += realized_est
        elif delta > 0:
            side = 'buy'

        rows.append({
            'ts': t.get('ts'),
            'price': trade_price,
            'signal': t.get('signal'),
            'action': t.get('action'),
            'position_from': p_from,
            'position_to': p_to,
            'delta_pct': delta,
            'side': side,
            'trade_cost_total': round(trade_cost, 6),
            'realized_pnl_est': round(realized_est, 6),
        })

    net_est = unrealized_amt + realized_est_total - sell_cost_total

    summary = {
        'symbol': '603305',
        'asof': state.get('updated_at'),
        'base_capital_from_costs': costs.get('base_capital_cny'),
        'base_capital_from_state': state.get('base_capital_cny'),
        'position_pct': pos_pct,
        'last_price': last_price,
        'avg_entry_price': avg_entry,
        'unrealized_pnl_est': round(unrealized_amt, 6),
        'realized_pnl_est_total': round(realized_est_total, 6),
        'trade_cost_total': round(sell_cost_total, 6),
        'net_pnl_est': round(net_est, 6),
        'net_return_est_pct': round((net_est / base_capital) * 100.0, 6),
        'today_trades_count': len(trades),
        'today_rows_used': len(rows),
        'source_trades_file': str(trades_path),
    }

    with out_csv.open('w', newline='', encoding='utf-8') as f:
        fieldnames = list(rows[0].keys()) if rows else ['ts','price','signal','action','position_from','position_to','delta_pct','side','trade_cost_total','realized_pnl_est']
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    with out_json.open('w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'rows': rows}, f, ensure_ascii=False, indent=2)

    print(str(out_csv))
    print(str(out_json))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
