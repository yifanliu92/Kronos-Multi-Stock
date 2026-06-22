#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
MAIN_LOG = BASE / 'sim_trades_603305.jsonl'
SHADOW_LOG = BASE / 'shadow_trades_603305.jsonl'
OUT_DIR = BASE / 'strategy_compare_reports'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
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


def direction_winrate(rows):
    """非中性信号，与下一条记录价格方向一致记为胜。"""
    wins = 0
    losses = 0
    neutral = 0
    for i in range(len(rows) - 1):
        cur, nxt = rows[i], rows[i + 1]
        sig = str(cur.get('signal', ''))
        p0 = float(cur.get('price', 0) or 0)
        p1 = float(nxt.get('price', 0) or 0)
        if p0 <= 0 or p1 <= 0:
            continue
        if '中性' in sig:
            neutral += 1
            continue
        is_bull = ('多' in sig)
        if p1 > p0 and is_bull:
            wins += 1
        elif p1 < p0 and (not is_bull):
            wins += 1
        elif p1 == p0:
            # 平盘不计输赢
            pass
        else:
            losses += 1
    total = wins + losses
    return {
        'wins': wins,
        'losses': losses,
        'samples': total,
        'winrate': round(wins / total * 100, 2) if total else None,
        'neutral_count': neutral,
    }


def summarize(name, rows):
    actionable = [r for r in rows if str(r.get('action', '')).strip() not in ('', '持仓不变')]
    return {
        'strategy': name,
        'records': len(rows),
        'actionable_records': len(actionable),
        'direction_next_tick': direction_winrate(rows),
        'first_ts': rows[0].get('ts') if rows else None,
        'last_ts': rows[-1].get('ts') if rows else None,
    }


def main():
    main_rows = load_jsonl(MAIN_LOG)
    shadow_rows = load_jsonl(SHADOW_LOG)
    report = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'symbol': '603305',
        'method_version': 'winrate_spec_603305_v1',
        'note': '当前自动统计为“下一条记录方向胜率（非中性）”；交易闭环胜率需成交闭环样本进一步补齐。',
        'main': summarize('main', main_rows),
        'shadow': summarize('shadow', shadow_rows),
    }
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = OUT_DIR / f'winrate_603305_{ts}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
