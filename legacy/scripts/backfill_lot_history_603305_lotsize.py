#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

BASE = Path('/Users/wxo/Desktop/Kronos')
COSTS = BASE / 'sim_costs_603305.json'
MAIN_DIR = BASE / 'sim_logs_daily'
SHADOW_DIR = BASE / 'shadow_logs_daily'
OUT_DIR = BASE / 'strategy_compare_reports'
OUT_DIR.mkdir(parents=True, exist_ok=True)

LOT_SIZE = 100  # A股一手100股


def load_base_capital() -> float:
    if COSTS.exists():
        try:
            d = json.loads(COSTS.read_text(encoding='utf-8'))
            return float(d.get('base_capital_cny', 100000))
        except Exception:
            pass
    return 100000.0


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def collect_rows(folder: Path) -> List[Dict[str, Any]]:
    rows = []
    for p in sorted(folder.glob('sim_trades_603305_*.jsonl')):
        for r in read_jsonl(p):
            r['_source'] = str(p)
            rows.append(r)
    rows.sort(key=lambda x: x.get('ts', ''))
    return rows


def round_to_lot_shares(shares: float) -> int:
    if shares <= 0:
        return 0
    return int(round(shares / LOT_SIZE) * LOT_SIZE)


def new_state():
    return {
        'lot_seq': 0,
        'long_lots': [],  # [{lot_id, shares, price, open_ts}]
        'short_lots': [],
    }


def next_id(state: Dict[str, Any], prefix: str) -> str:
    state['lot_seq'] += 1
    return f"{prefix}-{state['lot_seq']:06d}"


def open_lot(book: List[Dict[str, Any]], lot_id: str, shares: int, price: float, ts: str):
    if shares > 0:
        book.append({'lot_id': lot_id, 'shares': shares, 'price': price, 'open_ts': ts})


def close_fifo(book: List[Dict[str, Any]], close_shares: int, close_price: float, is_long: bool):
    remain = close_shares
    fills = []
    realized = 0.0
    while remain > 0 and book:
        lot = book[0]
        take = min(remain, int(lot['shares']))
        if take <= 0:
            break
        if is_long:
            pnl = take * (close_price - float(lot['price']))
            ftype = 'close_long'
        else:
            pnl = take * (float(lot['price']) - close_price)
            ftype = 'close_short'
        fills.append({
            'type': ftype,
            'lot_id': lot['lot_id'],
            'take_shares': take,
            'open_price': float(lot['price']),
            'close_price': close_price,
            'pnl': round(pnl, 6)
        })
        realized += pnl
        lot['shares'] -= take
        remain -= take
        if lot['shares'] <= 0:
            book.pop(0)
    return fills, realized, remain


def backfill(rows: List[Dict[str, Any]], base_capital: float, book_name: str):
    st = new_state()
    out = []
    for r in rows:
        ts = str(r.get('ts') or '')
        p = float(r.get('price', 0) or 0)
        pf = int(r.get('position_from', 0) or 0)
        pt = int(r.get('position_to', 0) or 0)
        delta = pt - pf

        event = {
            'ts': ts,
            'price': p,
            'position_from': pf,
            'position_to': pt,
            'fills': [],
            'realized_pnl_long': 0.0,
            'realized_pnl_short': 0.0,
            'unfilled_shares_warning': 0,
        }

        # 目标交易名义金额 -> 股数（按100股离散）
        trade_notional = base_capital * abs(delta) / 100.0
        shares = round_to_lot_shares(trade_notional / p) if p > 0 else 0

        if delta == 0 or shares == 0:
            pass
        elif pf >= 0 and pt >= 0:
            if delta > 0:  # 加多
                lot_id = next_id(st, 'L')
                open_lot(st['long_lots'], lot_id, shares, p, ts)
                event['fills'].append({'type': 'open_long', 'lot_id': lot_id, 'shares': shares, 'open_price': p})
            else:  # 减多
                fills, realized, remain = close_fifo(st['long_lots'], shares, p, True)
                event['fills'].extend(fills)
                event['realized_pnl_long'] = round(realized, 6)
                event['unfilled_shares_warning'] = remain
        elif pf <= 0 and pt <= 0:
            if delta < 0:  # 加空
                lot_id = next_id(st, 'S')
                open_lot(st['short_lots'], lot_id, shares, p, ts)
                event['fills'].append({'type': 'open_short', 'lot_id': lot_id, 'shares': shares, 'open_price': p})
            else:  # 减空
                fills, realized, remain = close_fifo(st['short_lots'], shares, p, False)
                event['fills'].extend(fills)
                event['realized_pnl_short'] = round(realized, 6)
                event['unfilled_shares_warning'] = remain
        else:
            # 穿越0轴：先平旧方向，再开新方向
            close_pct = abs(pf)
            close_notional = base_capital * close_pct / 100.0
            close_shares = round_to_lot_shares(close_notional / p) if p > 0 else 0
            if pf > 0:
                fills, realized, remain = close_fifo(st['long_lots'], close_shares, p, True)
                event['fills'].extend(fills)
                event['realized_pnl_long'] = round(realized, 6)
                if remain > 0:
                    event['unfilled_shares_warning'] = remain
                open_pct = abs(pt)
                open_notional = base_capital * open_pct / 100.0
                open_shares_n = round_to_lot_shares(open_notional / p) if p > 0 else 0
                if open_shares_n > 0:
                    lot_id = next_id(st, 'S')
                    open_lot(st['short_lots'], lot_id, open_shares_n, p, ts)
                    event['fills'].append({'type': 'open_short', 'lot_id': lot_id, 'shares': open_shares_n, 'open_price': p})
            else:
                fills, realized, remain = close_fifo(st['short_lots'], close_shares, p, False)
                event['fills'].extend(fills)
                event['realized_pnl_short'] = round(realized, 6)
                if remain > 0:
                    event['unfilled_shares_warning'] = remain
                open_pct = abs(pt)
                open_notional = base_capital * open_pct / 100.0
                open_shares_n = round_to_lot_shares(open_notional / p) if p > 0 else 0
                if open_shares_n > 0:
                    lot_id = next_id(st, 'L')
                    open_lot(st['long_lots'], lot_id, open_shares_n, p, ts)
                    event['fills'].append({'type': 'open_long', 'lot_id': lot_id, 'shares': open_shares_n, 'open_price': p})

        out.append({
            'ts': ts,
            'book': book_name,
            'source_file': r.get('_source'),
            'signal': r.get('signal'),
            'action': r.get('action'),
            'cost': r.get('cost', {}),
            'lot_event': event,
            'lot_book_long': st['long_lots'],
            'lot_book_short': st['short_lots'],
            'backfill_mode': 'estimated_lotsize_100'
        })

    return out


def write_jsonl(path: Path, rows: List[Dict[str, Any]]):
    with path.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def main():
    base_cap = load_base_capital()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    main_rows = collect_rows(MAIN_DIR)
    shadow_rows = collect_rows(SHADOW_DIR)

    out_main = backfill(main_rows, base_cap, 'main')
    out_shadow = backfill(shadow_rows, base_cap, 'shadow')

    p1 = OUT_DIR / f'historical_lot_backfill_main_603305_lotsize100_{ts}.jsonl'
    p2 = OUT_DIR / f'historical_lot_backfill_shadow_603305_lotsize100_{ts}.jsonl'
    ps = OUT_DIR / f'historical_lot_backfill_summary_603305_lotsize100_{ts}.json'

    write_jsonl(p1, out_main)
    write_jsonl(p2, out_shadow)

    summary = {
        'base_capital_cny': base_cap,
        'lot_size': LOT_SIZE,
        'main_rows': len(out_main),
        'shadow_rows': len(out_shadow),
        'out_main': str(p1),
        'out_shadow': str(p2),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    ps.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    print(str(p1))
    print(str(p2))
    print(str(ps))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
