#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE = Path('/Users/wxo/Desktop/Kronos')
MAIN_STATE = BASE / 'sim_state_603305.json'
SHADOW_STATE = BASE / 'shadow_state_603305.json'


def _new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def ensure_ledger(state: Dict[str, Any]) -> Dict[str, Any]:
    state.setdefault('lot_book_long', [])
    state.setdefault('lot_book_short', [])
    state.setdefault('lot_seq', 0)
    return state


def _next_id(state: Dict[str, Any], side: str) -> str:
    state['lot_seq'] = int(state.get('lot_seq', 0)) + 1
    return f"{side}-{state['lot_seq']:06d}"


def apply_trade(state: Dict[str, Any], curr_pct: int, target_pct: int, price: float, base_capital: float, ts: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    state = ensure_ledger(state)
    long_lots: List[Dict[str, Any]] = state['lot_book_long']
    short_lots: List[Dict[str, Any]] = state['lot_book_short']

    event = {
        'ts': ts,
        'price': price,
        'curr_pct': curr_pct,
        'target_pct': target_pct,
        'fills': [],
        'realized_pnl_long': 0.0,
        'realized_pnl_short': 0.0,
    }

    delta = target_pct - curr_pct
    if delta == 0:
        return state, event

    def close_long(notional: float):
        remain = notional
        while remain > 1e-9 and long_lots:
            lot = long_lots[0]
            take = min(remain, lot['notional'])
            pnl = take * ((price / lot['price']) - 1.0)
            event['realized_pnl_long'] += pnl
            event['fills'].append({'type': 'close_long', 'lot_id': lot['lot_id'], 'take_notional': round(take, 6), 'open_price': lot['price'], 'close_price': price, 'pnl': round(pnl, 6)})
            lot['notional'] -= take
            remain -= take
            if lot['notional'] <= 1e-9:
                long_lots.pop(0)

    def close_short(notional: float):
        remain = notional
        while remain > 1e-9 and short_lots:
            lot = short_lots[0]
            take = min(remain, lot['notional'])
            pnl = take * ((lot['price'] / price) - 1.0)
            event['realized_pnl_short'] += pnl
            event['fills'].append({
                'type': 'close_short',
                'lot_id': lot['lot_id'],
                'take_notional': round(take, 6),
                'open_price': lot['price'],
                'open_ts': lot.get('open_ts'),
                'close_price': price,
                'close_ts': ts,
                'pnl': round(pnl, 6),
            })
            lot['notional'] -= take
            remain -= take
            if lot['notional'] <= 1e-9:
                short_lots.pop(0)

    if curr_pct >= 0 and target_pct >= 0:
        if delta > 0:
            add_notional = base_capital * (delta / 100.0)
            lot_id = _next_id(state, 'L')
            long_lots.append({'lot_id': lot_id, 'notional': add_notional, 'price': price, 'open_ts': ts})
            event['fills'].append({'type': 'open_long', 'lot_id': lot_id, 'notional': round(add_notional, 6), 'open_price': price})
        else:
            close_long(base_capital * ((-delta) / 100.0))

    elif curr_pct <= 0 and target_pct <= 0:
        if delta < 0:  # more short
            add_notional = base_capital * ((-delta) / 100.0)
            lot_id = _next_id(state, 'S')
            short_lots.append({'lot_id': lot_id, 'notional': add_notional, 'price': price, 'open_ts': ts})
            event['fills'].append({'type': 'open_short', 'lot_id': lot_id, 'notional': round(add_notional, 6), 'open_price': price})
        else:
            close_short(base_capital * (delta / 100.0))
    else:
        # cross zero: close one side then open the other
        if curr_pct > 0:
            close_long(base_capital * (curr_pct / 100.0))
            open_notional = base_capital * ((-target_pct) / 100.0)
            if open_notional > 0:
                lot_id = _next_id(state, 'S')
                short_lots.append({'lot_id': lot_id, 'notional': open_notional, 'price': price, 'open_ts': ts})
                event['fills'].append({'type': 'open_short', 'lot_id': lot_id, 'notional': round(open_notional, 6), 'open_price': price})
        else:
            close_short(base_capital * ((-curr_pct) / 100.0))
            open_notional = base_capital * (target_pct / 100.0)
            if open_notional > 0:
                lot_id = _next_id(state, 'L')
                long_lots.append({'lot_id': lot_id, 'notional': open_notional, 'price': price, 'open_ts': ts})
                event['fills'].append({'type': 'open_long', 'lot_id': lot_id, 'notional': round(open_notional, 6), 'open_price': price})

    state['lot_book_long'] = long_lots
    state['lot_book_short'] = short_lots
    return state, event
