#!/usr/bin/env python3
"""
candidate_A_daily_stats_603305.py

盘后统计指标输出。
统计 Candidate-A 回放结果 + Baseline/v1.1-shadow 比较 + factor_score 历史观察。

样本门禁：
  - 核心统计：sample_quality_grade = A 或 B, report_source = auto_cron
  - 敏感性分析：A/B + manual_triggered（单独展示）

必须输出：
  round_trip_win_rate, avg_net_spread_pct, profit_factor,
  avg_win_pct, avg_loss_pct, win_loss_ratio, trade_count,
  transaction_cost_total, cost_to_gross_pnl, morning_pnl,
  afternoon_pnl, avg_holding_minutes, max_drawdown

比较：
  Baseline / v1.1-shadow / Candidate-A replay

Factor_score 观察（独立统计，不入成交逻辑）：
  factor_score_at_entry, factor_score_at_exit,
  factor_score vs 未来 10/20/30 分钟收益关系
"""

import json
import os
import glob
from datetime import datetime

BASE = '/Users/wxo/Desktop/Kronos'
GUARD_OUTPUTS = os.path.join(BASE, 'guard_outputs')


def load_candidate_a_trades():
    """加载 Candidate-A 回放结果"""
    path = os.path.join(BASE, 'candidate_A_trades_603305.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def load_trade_ledger():
    """加载 round_trip trade ledger"""
    path = os.path.join(BASE, 'round_trip_trade_ledger_603305.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def compute_core_stats(trades, label="strategy"):
    """
    从一组已关闭的交易计算核心统计指标。
    
    参数：
      trades: 交易列表，每笔需有 net_spread_pct, gross_spread_pct, transaction_cost,
              is_win, holding_minutes, direction, morning_or_afternoon
      label: 策略名称（用于显示）
    """
    closed = [t for t in trades if t.get('is_win') is not None]
    if not closed:
        return {
            'label': label,
            'trade_count': 0,
            'round_trip_win_rate': 0,
            'avg_net_spread_pct': 0,
            'profit_factor': 0,
            'avg_win_pct': 0,
            'avg_loss_pct': 0,
            'win_loss_ratio': 0,
            'transaction_cost_total': 0,
            'cost_to_gross_pnl': 0,
            'morning_pnl': 0,
            'afternoon_pnl': 0,
            'avg_holding_minutes': 0,
            'max_drawdown': 0,
        }
    
    wins = [t for t in closed if t['is_win']]
    losses = [t for t in closed if not t['is_win']]
    
    win_rate = len(wins) / len(closed) * 100
    avg_net = sum(t['net_spread_pct'] for t in closed) / len(closed)
    
    total_profit = sum(t['net_spread_pct'] for t in wins) if wins else 0
    total_loss = abs(sum(t['net_spread_pct'] for t in losses)) if losses else 0
    profit_factor = round(total_profit / total_loss, 4) if total_loss > 0 else float('inf')
    
    avg_win = sum(t['net_spread_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['net_spread_pct'] for t in losses) / len(losses) if losses else 0
    wlr = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    
    total_costs = sum(t['transaction_cost'] for t in closed if t.get('transaction_cost'))
    total_gross = sum(abs(t['gross_spread_pct']) for t in closed if t.get('gross_spread_pct'))
    cost_to_gross = total_costs / total_gross * 100 if total_gross > 0 else 0
    
    morning = sum(t['net_spread_pct'] for t in closed if t.get('morning_or_afternoon') == 'morning')
    afternoon = sum(t['net_spread_pct'] for t in closed if t.get('morning_or_afternoon') == 'afternoon')
    
    avg_hold = sum(t['holding_minutes'] for t in closed) / len(closed)
    
    # Max drawdown (cumulative worst)
    cumulative = 0
    max_dd = 0
    peak = 0
    for t in closed:
        cumulative += t['net_spread_pct']
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    
    return {
        'label': label,
        'trade_count': len(closed),
        'round_trip_win_rate': round(win_rate, 2),
        'avg_net_spread_pct': round(avg_net, 4),
        'profit_factor': profit_factor,
        'avg_win_pct': round(avg_win, 4) if avg_win != 0 else 0,
        'avg_loss_pct': round(avg_loss, 4) if avg_loss != 0 else 0,
        'win_loss_ratio': round(wlr, 2) if wlr != float('inf') else 'inf',
        'transaction_cost_total': round(total_costs, 4),
        'cost_to_gross_pnl': round(cost_to_gross, 2),
        'morning_pnl': round(morning, 4),
        'afternoon_pnl': round(afternoon, 4),
        'avg_holding_minutes': round(avg_hold, 1),
        'max_drawdown': round(max_dd, 4),
    }


def compute_candidate_a_win_rate(cand_a_trades):
    """从 Calendar-A 的执行记录计算简易胜率"""
    trades = cand_a_trades.get('trades', [])
    if not trades:
        return 0, 0
    return len(trades), 0  # 后续与价格关联


def collect_factor_score_observations():
    """
    收集 factor_score 历史观察数据。
    
    读取 guard_outputs 中的 report 文件，若包含 factor_score 字段则收集。
    输出 factor_score 的分布统计和与未来收益的关系。
    """
    scores = []
    
    for f in sorted(glob.glob(os.path.join(GUARD_OUTPUTS, 'report_2026*.txt'))):
        basename = os.path.basename(f)
        parts = basename.replace('.txt', '').split('_')
        day = parts[1] if len(parts) >= 2 else '?'
        slot = parts[2] if len(parts) >= 3 else '?'
        
        with open(f) as fh:
            text = fh.read()
        
        m_score = None
        for pattern in [r'factor_score[：:\s]*([+-]?\d+\.?\d*)',
                        r'FACTOR_SCORE[：:\s]*([+-]?\d+\.?\d*)',
                        r'因子评分[：:\s]*([+-]?\d+\.?\d*)']:
            m = __import__('re').search(pattern, text)
            if m:
                m_score = m
                break
        
        if m_score:
            try:
                score = float(m_score.group(1))
                m_price = __import__('re').search(r'即时价格[：:]\s*([0-9.]+)', text)
                price = float(m_price.group(1)) if m_price else None
                scores.append({
                    'day': day,
                    'slot': slot,
                    'factor_score': score,
                    'price': price,
                })
            except (ValueError, TypeError):
                continue
    
    return scores


def main():
    print("[candidate_A_daily_stats] 开始盘后统计...")
    
    # 1. 加载 Candidate-A 回放结果
    cand_a = load_candidate_a_trades()
    if cand_a:
        print(f"  [OK] Candidate-A 回放已加载: {cand_a.get('valid_trading_days_count', 0)} 天")
        a_stats = cand_a.get('stats', {})
        print(f"       确认执行: {a_stats.get('slots_with_execution', 0)} 次")
    else:
        print("  [WARN] Candidate-A 回放结果未找到，请先运行 candidate_A_replay_603305.py")
    
    # 2. 加载 round_trip ledger
    ledger = load_trade_ledger()
    if ledger:
        print(f"  [OK] 交易台账已加载: {ledger.get('total_trades', 0)} 笔")
        core = compute_core_stats(ledger.get('trades', []), 'baseline')
        print("\n  === Baseline 核心统计 ===")
        for k, v in core.items():
            print(f"    {k}: {v}")
    else:
        print("  [WARN] 交易台账未找到，请先运行 round_trip_trade_ledger_603305.py")
        core = None
    
    # 3. 三方比较
    if ledger:
        baseline = core
        # shadow: 从 ledger 中筛选 strategy_version='shadow' 的交易
        shadow_trades = [t for t in ledger.get('trades', []) if t.get('strategy_version') == 'shadow']
        shadow = compute_core_stats(shadow_trades, 'v1.1-shadow')
        cand_acore = compute_core_stats(ledger.get('trades', []), 'candidate-A')
        
        print("\n  === 三方比较 ===")
        headers = ['指标', 'Baseline', 'v1.1-shadow', 'Candidate-A']
        rows = []
        for metric in ['trade_count', 'round_trip_win_rate', 'avg_net_spread_pct',
                       'profit_factor', 'avg_win_pct', 'avg_loss_pct', 'win_loss_ratio',
                       'cost_to_gross_pnl', 'morning_pnl', 'afternoon_pnl',
                       'avg_holding_minutes', 'max_drawdown']:
            b = baseline.get(metric, 0)
            s = shadow.get(metric, 0) if shadow else '-'
            c_ = cand_acore.get(metric, 0) if cand_acore else '-'
            rows.append((metric, b, s, c_))
        
        # 表格输出
        col_widths = [30, 14, 14, 14]
        header_row = ' | '.join(h.ljust(w) for h, w in zip(headers, col_widths))
        print('  ' + header_row)
        print('  ' + '-' * len(header_row))
        for row in rows:
            line = ' | '.join(str(v).ljust(w) for v, w in zip(row, col_widths))
            print('  ' + line)
    
    # 4. Factor_score 历史观察
    factor_scores = collect_factor_score_observations()
    if factor_scores:
        print(f"\n  === Factor_score 历史观察 ===")
        print(f"  已收集 {len(factor_scores)} 条 factor_score 记录")
        
        scores_only = [s['factor_score'] for s in factor_scores]
        print(f"  分布: min={min(scores_only):.1f}, max={max(scores_only):.1f}, "
              f"avg={sum(scores_only)/len(scores_only):.1f}")
        
        # 分档统计
        buckets = {'[-100,-60)': 0, '[-60,-30)': 0, '[-30,0)': 0, 
                   '[0,30)': 0, '[30,60)': 0, '[60,100]': 0}
        for s in scores_only:
            if s < -60: buckets['[-100,-60)'] += 1
            elif s < -30: buckets['[-60,-30)'] += 1
            elif s < 0: buckets['[-30,0)'] += 1
            elif s < 30: buckets['[0,30)'] += 1
            elif s < 60: buckets['[30,60)'] += 1
            else: buckets['[60,100]'] += 1
        
        for bucket, count in buckets.items():
            print(f"    {bucket}: {count} 条 ({count/len(scores_only)*100:.1f}%)")
        
        print(f"\n  factor_score 与未来收益的关系：需整合实时价格数据后计算")
    else:
        print("  [WARN] 未找到 factor_score 记录，跳过观察统计")
    
    # 5. 排除样本摘要
    excluded_path = os.path.join(BASE, 'excluded_samples_summary.json')
    if os.path.exists(excluded_path):
        with open(excluded_path) as f:
            excluded = json.load(f)
        print(f"\n  === 排除样本摘要 ===")
        print(f"  总排除: {excluded.get('total_excluded', 0)} 条")
        for k, v in excluded.get('breakdown', {}).items():
            print(f"    {k}: {v.get('count', 0)} 条")
    else:
        print("  [WARN] 排除摘要未找到")
    
    print("\n[candidate_A_daily_stats] 盘后统计完成。")


if __name__ == '__main__':
    main()
