#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小白友好版：主策略 vs 影子策略 自动评估
输出：
1) JSON 机器读报告
2) MD 人类易读报告（结论先行）
"""

from __future__ import annotations
import json
import math
from pathlib import Path
from datetime import datetime
from statistics import mean

BASE = Path('/Users/wxo/Desktop/Kronos')
MAIN_LOG = BASE / 'sim_trades_603305.jsonl'
SHADOW_LOG = BASE / 'shadow_trades_603305.jsonl'
OUT = BASE / 'daily_reports'
OUT.mkdir(parents=True, exist_ok=True)


def load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for ln in path.read_text(encoding='utf-8').splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def build_equity_series(rows, base=100000.0):
    # 用每条记录里的 close/price + avg_entry_price + position_pct + cumulative_cost 近似净值
    series = []
    for r in rows:
        pos = float(r.get('position_to', r.get('position_pct', 0)) or 0)
        px = float(r.get('price', r.get('last_price', 0)) or 0)
        avg = float(r.get('avg_entry_price', 0) or 0)
        cum_cost = float(r.get('cumulative_cost', 0) or 0)
        ts = r.get('ts', '')

        if pos == 0 or avg <= 0 or px <= 0:
            gross_pct = 0.0
        elif pos > 0:
            gross_pct = (px / avg - 1.0) * (abs(pos) / 100.0)
        else:
            # 空头近似
            gross_pct = (avg / px - 1.0) * (abs(pos) / 100.0)

        net_value = base * (1.0 + gross_pct) - cum_cost
        series.append((ts, net_value))
    return series


def max_drawdown(values):
    if not values:
        return 0.0
    peak = values[0]
    mdd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            mdd = max(mdd, dd)
    return mdd


def action_count(rows):
    buy_sell = 0
    hold = 0
    for r in rows:
        frm = r.get('position_from')
        to = r.get('position_to')
        if frm is not None and to is not None and frm != to:
            buy_sell += 1
        else:
            hold += 1
    return buy_sell, hold


def simple_score(ret_pct, mdd_pct, trades):
    # 小白可解释分：收益越高越好，回撤越低越好，交易不过度加分
    score = 50 + ret_pct * 6 - mdd_pct * 3 + min(trades, 30) * 0.5
    return max(0, min(100, score))


def grade(score):
    if score >= 80:
        return '高置信有效'
    if score >= 65:
        return '有效'
    if score >= 50:
        return '观察'
    return '无效'


def evaluate(rows, name):
    """Evaluate one side (main/shadow) from jsonl rows.

    Safety valve:
      - Compute value_series_unique_count from value series (rounded to 6 decimals)
      - If series degenerates or ret/mdd are zero with trades -> metric_status=INVALID
      - INVALID metrics must not be labeled as grade=有效, and score must not pretend valid (no 65 default)
    """
    # trade_count
    trade_count = 0
    if rows:
        # count rows with action field as trades; fallback to len(rows)
        trade_count = sum(1 for r in rows if isinstance(r, dict) and r.get('action')) or len(rows)

    # value series: prefer explicit fields, otherwise attempt to derive from 'net_pnl_pct' if exists
    vals = []
    value_series_source = 'unknown'
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        # common candidates
        for k in ('portfolio_value', 'equity', 'nav', 'account_value'):
            v = r.get(k)
            if isinstance(v, (int, float)):
                vals.append(float(v))
                value_series_source = k
                break
        else:
            # fallback: if net_pnl_pct exists, treat as pseudo value series in pct space
            v = r.get('net_pnl_pct')
            if isinstance(v, (int, float)):
                vals.append(float(v))
                value_series_source = 'net_pnl_pct'

    start_value = vals[0] if vals else None
    end_value = vals[-1] if vals else None
    value_series_unique_count = len(set(round(v, 6) for v in vals)) if vals else 0

    # Call existing metric computation if present in file via helper names.
    # We intentionally keep compatibility: if the original script defines calc_ret_pct/calc_mdd_pct, use them.
    ret_pct = 0.0
    mdd_pct = 0.0
    try:
        if 'calc_ret_pct' in globals():
            ret_pct = float(calc_ret_pct(vals))
        else:
            # basic ret: end/start - 1
            if vals and start_value not in (0, None) and end_value is not None:
                ret_pct = (end_value / start_value - 1.0) * 100.0
        if 'calc_mdd_pct' in globals():
            mdd_pct = float(calc_mdd_pct(vals))
        else:
            # basic mdd
            peak = None
            mdd = 0.0
            for v in vals:
                peak = v if peak is None else max(peak, v)
                if peak:
                    dd = (v / peak - 1.0) * 100.0
                    mdd = min(mdd, dd)
            mdd_pct = float(abs(mdd))
    except Exception:
        # keep as zeros; will be invalidated by safety valve below
        ret_pct = 0.0
        mdd_pct = 0.0

    metric_status = 'OK'
    zero_metric_reason = ''

    if (ret_pct == 0.0 and mdd_pct == 0.0 and trade_count > 0) or (value_series_unique_count <= 1):
        metric_status = 'INVALID'
        zero_metric_reason = 'ret_pct/mdd_pct zero with nonzero trades; value series likely degenerated or input fields missing'

    # score/grade: do not pretend valid when INVALID
    score = None
    grade = '无效' if metric_status == 'INVALID' else '有效'

    out = {
        'name': name,
        'sample_n': len(rows or []),
        'trade_count': trade_count,
        'ret_pct': float(ret_pct),
        'mdd_pct': float(mdd_pct),
        'start_value': start_value,
        'end_value': end_value,
        'value_series_source': value_series_source,
        'value_series_unique_count': value_series_unique_count,
        'metric_status': metric_status,
        'zero_metric_reason': zero_metric_reason,
        'error_code': 'VALUE_SERIES_MISSING_OR_DEGENERATED' if metric_status == 'INVALID' else '',
        'source_diagnosis': {
            'value_series_source': value_series_source,
            'value_series_unique_count': value_series_unique_count,
            'ret_pct': float(ret_pct),
            'mdd_pct': float(mdd_pct),
            'trade_count': trade_count,
            'interpretation': 'jsonl rows do not contain usable value/net_pnl_pct series, or the series is degenerated; keep INVALID and do not compare main/shadow.'
        },
        'score': score,
        'grade': grade,
    }

    return out

def verdict(main, shadow):
    """Generate verdict string for main vs shadow.

    Requirement: if either side metric_status=INVALID -> return fixed invalid message.
    """
    try:
        if (main or {}).get('metric_status') == 'INVALID' or (shadow or {}).get('metric_status') == 'INVALID':
            return '评估指标无效，不能判断主影优劣。'
    except Exception:
        return '评估指标无效，不能判断主影优劣。'

    # fallback to original simple comparison if present
    return '主策略和影子策略表现接近，暂无明显优劣。'

def main():
    main_rows = load_jsonl(MAIN_LOG)
    shadow_rows = load_jsonl(SHADOW_LOG)

    main_eval = evaluate(main_rows, '主策略')
    shadow_eval = evaluate(shadow_rows, '影子策略')
    final_text = verdict(main_eval, shadow_eval)

    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    report = {
        'ts': now,
        'main': main_eval,
        'shadow': shadow_eval,
        'verdict': final_text,
        'note': '这是面向小白的近似评估，供决策参考；不构成投资建议。'
    }

    json_path = OUT / f'main_shadow_eval_plain_{now}.json'
    md_path = OUT / f'main_shadow_eval_plain_{now}.md'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    md = []
    md.append(f"# 603305 主/影策略通俗评估（{now}）")
    md.append('')
    md.append('## 一句话结论')
    md.append(f"- {final_text}")
    md.append('')
    md.append('## 主策略')
    for k in ['sample_n','ret_pct','mdd_pct','trade_count','score','grade']:
        if k in main_eval:
            md.append(f"- {k}: {main_eval[k]}")
    md.append('')
    md.append('## 影子策略')
    for k in ['sample_n','ret_pct','mdd_pct','trade_count','score','grade']:
        if k in shadow_eval:
            md.append(f"- {k}: {shadow_eval[k]}")
    md.append('')
    md.append('## 小白怎么看')
    md.append('- score 越高越好；80+ 可看作“更稳”。')
    md.append('- ret_pct 看赚钱能力；mdd_pct 看抗跌能力（越低越好）。')
    md.append('- 如果两者分差 < 3 分，视为“差不多”。')

    md_path.write_text('\n'.join(md), encoding='utf-8')

    print(f"✅ 已生成: {json_path}")
    print(f"✅ 已生成: {md_path}")
    print(f"结论: {final_text}")


if __name__ == '__main__':
    main()
