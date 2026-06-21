#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'
CONFIG = BASE / 'config'
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

SYMBOL = '603305'


def _extract_price_from_quote(quote: dict) -> float | None:
    if not isinstance(quote, dict):
        return None
    data = quote.get('data') if isinstance(quote.get('data'), dict) else None
    if data:
        # common keys
        for k in ('price','last','last_price','f43'):
            v = data.get(k)
            if isinstance(v, (int,float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v)
                except Exception:
                    pass
    # sometimes router returns raw; no safe parse
    return None


def _extract_position_pct(state: dict) -> int | None:
    if not isinstance(state, dict):
        return None
    v = state.get('position_pct')
    if isinstance(v, (int,float)):
        return int(round(float(v)))
    return None


def _extract_net_pnl_pct(state: dict) -> float | None:
    if not isinstance(state, dict):
        return None
    for k in ('net_pnl_pct','net_pnl_percent','pnl_pct'):
        v = state.get(k)
        if isinstance(v, (int,float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except Exception:
                pass
    return None


def now_ts():
    return datetime.now(TZ)


def ymd():
    return now_ts().strftime('%Y%m%d')


def read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def last_factor_observer() -> Optional[dict]:
    # Prefer today’s factor observer json if present
    today = GUARD / f'factor_score_observer_{ymd()}.json'
    if today.exists():
        return read_json(today)
    # Otherwise pick latest matching file
    files = sorted(GUARD.glob('factor_score_observer_*.json'))
    if not files:
        return None
    return read_json(files[-1])


def fetch_quote_readonly() -> Dict[str, Any]:
    # Use existing signal_router (eastmoney) if available; treat as read-only.
    router = BASE / 'signal_router_603305.py'
    if not router.exists():
        return {'ok': False, 'error': 'signal_router_603305.py_not_found'}
    try:
        out = subprocess.check_output(['python3', str(router), '--mode', 'quote_json'], text=True, stderr=subprocess.STDOUT, timeout=25)
        # Expect JSON in output; if not, wrap raw
        out = out.strip()
        try:
            return {'ok': True, 'data': json.loads(out)}
        except Exception:
            return {'ok': True, 'data_raw': out}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'QUOTE_TIMEOUT'}
    except Exception as e:
        return {'ok': False, 'error': f'QUOTE_ERROR:{e}'}


@dataclass
class Snapshot:
    version: str
    ts: str
    date: str
    symbol: str
    readonly: bool
    quote: Dict[str, Any]
    main_state: Optional[dict]
    main_costs: Optional[dict]
    shadow_state: Optional[dict]
    shadow_costs: Optional[dict]
    factor_observer: Optional[dict]
    notes: list[str]


def main() -> int:
    GUARD.mkdir(parents=True, exist_ok=True)
    d = ymd()
    ts = now_ts().strftime('%Y-%m-%d %H:%M:%S')

    # Read-only state snapshots
    main_state = read_json(BASE / 'sim_state_603305.json')
    main_costs = read_json(BASE / 'sim_costs_603305.json')
    shadow_state = read_json(BASE / 'sim_state_603305_shadow.json')
    shadow_costs = read_json(BASE / 'sim_costs_603305_shadow.json')

    quote = fetch_quote_readonly()
    factor = last_factor_observer()

    snap = Snapshot(
        version='close_snapshot_603305_v0.1',
        ts=ts,
        date=d,
        symbol=SYMBOL,
        readonly=True,
        quote=quote,
        main_state=main_state,
        main_costs=main_costs,
        shadow_state=shadow_state,
        shadow_costs=shadow_costs,
        factor_observer=factor,
        notes=[
            'read-only snapshot; no trading action; no position changes',
            'factor_observer is observer_only (not used for trading decisions here)'
        ],
    )

    out_json = GUARD / f'close_snapshot_{d}_150000.json'
    out_md = GUARD / f'close_snapshot_{d}_150000.md'
    out_report = GUARD / f'report_{d}_150000.txt'

    out_json.write_text(json.dumps(asdict(snap), ensure_ascii=False, indent=2), encoding='utf-8')

    md_lines = [
        f"# 603305 Close Snapshot ({d} 15:00)",
        f"- ts: {ts}",
        f"- readonly: true",
        "",
        "## Quote (readonly)",
        f"```json\n{json.dumps(quote, ensure_ascii=False, indent=2)}\n```",
        "",
        "## Main state",
        f"```json\n{json.dumps(main_state, ensure_ascii=False, indent=2)}\n```",
        "",
        "## Shadow state",
        f"```json\n{json.dumps(shadow_state, ensure_ascii=False, indent=2)}\n```",
        "",
        "## Factor observer (observer-only)",
        f"```json\n{json.dumps(factor, ensure_ascii=False, indent=2)}\n```",
    ]
    out_md.write_text('\n'.join(md_lines) + '\n', encoding='utf-8')

    # report_YYYYMMDD_150000.txt: align with intraday report parse fields (read-only)
    price = _extract_price_from_quote(quote)
    main_pos = _extract_position_pct(main_state)
    shadow_pos = _extract_position_pct(shadow_state)
    main_net = _extract_net_pnl_pct(main_state)
    shadow_net = _extract_net_pnl_pct(shadow_state)

    # Use the same human-facing labels as intraday reports to keep parsers stable.
    out_report.write_text(
        f"时间：{ts}\n"
        f"标的：{SYMBOL}\n"
        f"即时价格：{'' if price is None else f'{price:.2f}'}\n"
        f"模拟仓位：{'' if main_pos is None else str(main_pos) + '%'}\n"
        f"净浮盈（含累计成本）：{'' if main_net is None else '约 ' + format(main_net, '.2f') + '%'}\n"
        f"\n【影子策略 v1.1-shadow（触发即模拟成交）】\n"
        f"• 持仓仓位：{'' if shadow_pos is None else str(shadow_pos) + '%'}\n"
        f"净浮盈（含累计成本）：{'' if shadow_net is None else '约 ' + format(shadow_net, '.2f') + '%'}\n"
        f"\n[AUDIT] run_status=ok\n"
        f"[AUDIT] report_file={out_report}\n"
        f"\njson={out_json}\nmd={out_md}\n"
        ,
        encoding='utf-8'
    )

    # NOTE: This change only affects future 15:00 snapshots; do NOT backfill historical 15:00 reports.

    print(f"OK wrote {out_report}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
