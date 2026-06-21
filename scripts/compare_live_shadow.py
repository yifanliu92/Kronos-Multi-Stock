#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

BASE = Path('/Users/wxo/Desktop/Kronos')
LOG = BASE / 'sim_trades_603305.jsonl'
OUT_DIR = BASE / 'strategy_compare_reports'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_rows(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def main():
    rows = load_rows(LOG)
    if not rows:
        print('无数据：sim_trades_603305.jsonl 为空')
        return

    latest_day = rows[-1].get('ts', '')[:10]
    day_rows = [r for r in rows if str(r.get('ts', '')).startswith(latest_day)]

    adds = sum(1 for r in day_rows if r.get('position_to', 0) > r.get('position_from', 0))
    cuts = sum(1 for r in day_rows if r.get('position_to', 0) < r.get('position_from', 0))
    hold = len(day_rows) - adds - cuts

    prices = [float(r.get('price', 0.0)) for r in day_rows if r.get('price') is not None]
    max_p = max(prices) if prices else 0.0
    min_p = min(prices) if prices else 0.0

    report = {
        'date': latest_day,
        'records': len(day_rows),
        'actions': {'add': adds, 'cut': cuts, 'hold': hold},
        'price_range': {'max': max_p, 'min': min_p},
        'note': '当前仅生成主策略日报骨架。Shadow 对比位后续接入独立日志后自动补全。'
    }

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = OUT_DIR / f'compare_{latest_day}_{ts}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'已生成对比骨架报告: {out}')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
