#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

from lot_ledger_603305 import apply_trade, ensure_ledger

BASE = Path('/Users/wxo/Desktop/Kronos')
COSTS = BASE / 'sim_costs_603305.json'
MAIN_DIR = BASE / 'sim_logs_daily'
SHADOW_DIR = BASE / 'shadow_logs_daily'
OUT_DIR = BASE / 'strategy_compare_reports'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_base_capital() -> float:
    if COSTS.exists():
        try:
            d = json.loads(COSTS.read_text(encoding='utf-8'))
            return float(d.get('base_capital_cny', 100000))
        except Exception:
            pass
    return 100000.0


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def collect_rows(folder: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in sorted(folder.glob('sim_trades_603305_*.jsonl')):
        for r in read_jsonl(p):
            r['_source'] = str(p)
            rows.append(r)
    rows.sort(key=lambda x: x.get('ts', ''))
    return rows


def backfill(rows: List[Dict[str, Any]], base_capital: float, book_name: str):
    state: Dict[str, Any] = ensure_ledger({'lot_seq': 0, 'lot_book_long': [], 'lot_book_short': []})
    out_rows = []
    for r in rows:
        curr = int(r.get('position_from', 0) or 0)
        target = int(r.get('position_to', 0) or 0)
        price = float(r.get('price', 0) or 0)
        ts = str(r.get('ts') or '')
        state, ev = apply_trade(state, curr, target, price, base_capital, ts)
        out_rows.append({
            'ts': ts,
            'book': book_name,
            'source_file': r.get('_source'),
            'price': price,
            'position_from': curr,
            'position_to': target,
            'signal': r.get('signal'),
            'action': r.get('action'),
            'cost': r.get('cost', {}),
            'lot_event': ev,
            'lot_book_long': state.get('lot_book_long', []),
            'lot_book_short': state.get('lot_book_short', []),
            'backfill_mode': 'estimated'
        })
    return out_rows


def write_jsonl(path: Path, rows: List[Dict[str, Any]]):
    with path.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def main():
    base_cap = load_base_capital()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    main_rows = collect_rows(MAIN_DIR)
    shadow_rows = collect_rows(SHADOW_DIR)

    main_out = backfill(main_rows, base_cap, 'main')
    shadow_out = backfill(shadow_rows, base_cap, 'shadow')

    p_main = OUT_DIR / f'historical_lot_backfill_main_603305_{ts}.jsonl'
    p_shadow = OUT_DIR / f'historical_lot_backfill_shadow_603305_{ts}.jsonl'
    p_summary = OUT_DIR / f'historical_lot_backfill_summary_603305_{ts}.json'

    write_jsonl(p_main, main_out)
    write_jsonl(p_shadow, shadow_out)

    summary = {
        'base_capital_cny': base_cap,
        'main_rows': len(main_out),
        'shadow_rows': len(shadow_out),
        'out_main': str(p_main),
        'out_shadow': str(p_shadow),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    p_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    print(str(p_main))
    print(str(p_shadow))
    print(str(p_summary))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
