#!/usr/bin/env python3
"""融券成本计算器。

V2 口径：
1. 实际交易费用仅在 turnover > 0 时产生；
2. 未平仓融券利息按 lot 的 open_ts 动态应计；
3. 平仓融券利息按 close_short fills 逐 lot 结算；
4. short_holding_days 全局计数器不再作为真实利息依据。

当前模拟约定：
- 按自然日差计算持有天数；
- 同日开仓和平仓的 days_held=0；
- 年化利率按 360 天折算。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List


def calculate_short_pnl(
    entry_price: float,
    current_price: float,
    position_pct: float,
    base_capital: float,
) -> tuple[float, float]:
    """计算空头浮动盈亏（收益率, 金额）。"""

    if position_pct >= 0:
        return 0.0, 0.0

    if (
        not entry_price
        or entry_price <= 0
        or not current_price
        or current_price <= 0
    ):
        return 0.0, 0.0

    abs_pos_pct = abs(float(position_pct))
    notional = float(base_capital) * abs_pos_pct / 100.0
    pnl_pct = (
        float(entry_price) - float(current_price)
    ) / float(entry_price)
    pnl_amount = notional * pnl_pct

    return pnl_pct, pnl_amount


def _parse_ts(value: str) -> datetime:
    if not value:
        raise ValueError("timestamp is empty")

    return datetime.strptime(
        str(value).strip(),
        "%Y-%m-%d %H:%M:%S",
    )


def calculate_calendar_days_held(
    open_ts: str,
    as_of_ts: str,
) -> int:
    """按自然日日期差计算持有天数。"""

    opened = _parse_ts(open_ts)
    as_of = _parse_ts(as_of_ts)

    return max((as_of.date() - opened.date()).days, 0)


def _zero_trade_cost(comment: str) -> Dict[str, Any]:
    return {
        "stamp_tax": 0.0,
        "commission": 0.0,
        "transfer_fee": 0.0,
        "interest": 0.0,
        "total": 0.0,
        "_comment": comment,
    }


def calculate_short_sell_cost(
    turnover: float,
    days_held: int,
    interest_rate: float = 0.10,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
) -> Dict[str, Any]:
    """旧接口兼容函数。

    注意：
    - turnover <= 0 时，所有费用必须为 0；
    - 新代码不应再使用这一函数作为逐 lot 利息结算依据；
    - 新代码应优先使用 calculate_settled_short_interest() 与
      calculate_accrued_short_interest()。
    """

    turnover = max(float(turnover), 0.0)
    days_held = max(int(days_held), 0)

    if turnover <= 1e-9:
        return _zero_trade_cost(
            "无真实成交，融券交易费用与结算利息均为 0"
        )

    stamp_tax = turnover * float(stamp_tax_rate)
    commission = max(turnover * float(commission_rate), 5.0)
    transfer_fee = turnover * 0.00001
    interest = (
        turnover
        * float(interest_rate)
        / 360.0
        * days_held
    )

    total = stamp_tax + commission + transfer_fee + interest

    return {
        "stamp_tax": round(stamp_tax, 2),
        "commission": round(commission, 2),
        "transfer_fee": round(transfer_fee, 2),
        "interest": round(interest, 2),
        "total": round(total, 2),
        "_comment": "旧接口兼容：融券交易费用与持有期间利息",
    }


def calculate_settled_short_interest(
    fills: Iterable[Dict[str, Any]],
    close_ts: str,
    interest_rate: float = 0.10,
) -> Dict[str, Any]:
    """对本次 close_short fills 逐 lot 计算已结算融券利息。"""

    breakdown: List[Dict[str, Any]] = []
    total_interest = 0.0

    for fill in fills or []:
        if fill.get("type") != "close_short":
            continue

        lot_id = str(fill.get("lot_id") or "")
        open_ts = str(fill.get("open_ts") or "")
        take_notional = float(fill.get("take_notional") or 0.0)

        if not open_ts:
            raise ValueError(
                f"close_short fill missing open_ts: lot_id={lot_id}"
            )

        if take_notional <= 0:
            continue

        days_held = calculate_calendar_days_held(
            open_ts=open_ts,
            as_of_ts=close_ts,
        )

        interest = (
            take_notional
            * float(interest_rate)
            / 360.0
            * days_held
        )

        total_interest += interest

        breakdown.append(
            {
                "lot_id": lot_id,
                "take_notional": round(take_notional, 6),
                "open_ts": open_ts,
                "close_ts": close_ts,
                "days_held": days_held,
                "interest": round(interest, 2),
            }
        )

    return {
        "settled_interest": round(total_interest, 2),
        "closed_lot_count": len(breakdown),
        "breakdown": breakdown,
    }


def calculate_accrued_short_interest(
    lots: Iterable[Dict[str, Any]],
    as_of_ts: str,
    interest_rate: float = 0.10,
) -> Dict[str, Any]:
    """对当前未平仓空头 lots 逐笔计算应计融券利息。"""

    breakdown: List[Dict[str, Any]] = []
    total_interest = 0.0

    for lot in lots or []:
        lot_id = str(lot.get("lot_id") or "")
        open_ts = str(lot.get("open_ts") or "")
        notional = float(lot.get("notional") or 0.0)

        if not open_ts:
            raise ValueError(
                f"open short lot missing open_ts: lot_id={lot_id}"
            )

        if notional <= 0:
            continue

        days_held = calculate_calendar_days_held(
            open_ts=open_ts,
            as_of_ts=as_of_ts,
        )

        interest = (
            notional
            * float(interest_rate)
            / 360.0
            * days_held
        )

        total_interest += interest

        breakdown.append(
            {
                "lot_id": lot_id,
                "notional": round(notional, 6),
                "open_ts": open_ts,
                "as_of_ts": as_of_ts,
                "days_held": days_held,
                "interest": round(interest, 2),
            }
        )

    return {
        "accrued_interest": round(total_interest, 2),
        "open_lot_count": len(breakdown),
        "breakdown": breakdown,
    }


def calculate_oldest_open_short_days(
    lots: Iterable[Dict[str, Any]],
    as_of_ts: str,
) -> int:
    """仅用于展示：返回最早未平仓空头 lot 的自然日持有天数。"""

    lot_list = list(lots or [])

    if not lot_list:
        return 0

    values = []

    for lot in lot_list:
        open_ts = str(lot.get("open_ts") or "")

        if not open_ts:
            continue

        values.append(
            calculate_calendar_days_held(
                open_ts=open_ts,
                as_of_ts=as_of_ts,
            )
        )

    return max(values) if values else 0
