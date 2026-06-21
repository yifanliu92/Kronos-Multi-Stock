#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "sim_trades_603305.jsonl"


def load_today_records() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    today = dt.datetime.now().strftime("%Y-%m-%d")
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if str(obj.get("ts", "")).startswith(today):
            rows.append(obj)
    return rows


def main() -> None:
    rows = load_today_records()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not rows:
        print(f"【603305 模拟复盘 {now}】")
        print("今日无模拟调仓记录")
        print("命中率：N/A")
        print("回撤：N/A")
        print("可改进点：明日继续按规则采样")
        return

    adds = sum(1 for r in rows if "加仓" in r.get("action", ""))
    cuts = sum(1 for r in rows if "减仓" in r.get("action", ""))
    holds = len(rows) - adds - cuts

    # 简化命中率：强多/偏多视为多头预测，强空/偏空视为空头预测，中性不计
    directional = [r for r in rows if r.get("signal") in ("强多", "偏多", "强空", "偏空")]
    hit = 0
    for r in directional:
        pct = float(r.get("pct", 0))
        s = r.get("signal")
        if s in ("强多", "偏多") and pct > 0:
            hit += 1
        if s in ("强空", "偏空") and pct < 0:
            hit += 1
    hit_rate = (hit / len(directional) * 100.0) if directional else None

    # 简化“回撤”近似：用当日记录里的最小pct近似不利波动
    worst_pct = min(float(r.get("pct", 0)) for r in rows)
    last_pos = rows[-1].get("position_to")

    print(f"【603305 模拟复盘 {now}】")
    print(f"记录数：{len(rows)}（加仓{adds}/减仓{cuts}/不变{holds}）")
    print("命中率：" + (f"{hit_rate:.1f}%" if hit_rate is not None else "N/A"))
    print(f"回撤：盘中最弱涨跌幅 {worst_pct:+.2f}%（简化口径）")
    print(f"可改进点：若中性信号过多，考虑把阈值从±1.2%微调到±1.0%或叠加量能条件；当前收盘模拟仓位 {last_pos}%")


if __name__ == "__main__":
    main()
