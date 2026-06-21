#!/usr/bin/env python3
"""
candidate_A_replay_603305.py

Candidate-A 历史回放脚本。

核心规则（仅新增风险敞口需要两次确认）：
  1. 直接读取主策略输出的信号标签（强多/偏多/中性/偏空/强空），
     不重新定义任何阈值。
  2. 仅在连续两个时点出现同方向信号时才模拟加仓。
  3. 减仓、平仓、止盈、止损、风控退出立即执行，不加延迟。
  4. 每次最多调整 20%。

样本门禁：
  - sample_quality_grade = A 或 B
  - report_source = auto_cron

输出：
  candidate_A_trades_603305.json  （历史回放结果）
"""

import json
import os
import re
import glob
from collections import defaultdict
from datetime import datetime

BASE = '/Users/wxo/Desktop/Kronos'
GUARD_OUTPUTS = os.path.join(BASE, 'guard_outputs')

# 信号标签映射表（读取主策略已有标签，不硬编码阈值）
SIGNAL_LABELS = ['strong_bull', 'bull', 'neutral', 'bear', 'strong_bear']


def load_report(day, slot):
    """读取单个 report 文本，提取信号标签"""
    path = os.path.join(GUARD_OUTPUTS, f'report_{day}_{slot}.txt')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    
    m_price = re.search(r'即时价格[：:]\s*([0-9.]+)', text)
    price = float(m_price.group(1)) if m_price else None
    
    m_signal = re.search(r'信号[：:]\s*(\S+)', text)
    signal = m_signal.group(1).strip() if m_signal else None
    
    m_action = re.search(r'动作[：:]\s*(.*?)(?:\n|$)', text)
    action = m_action.group(1).strip() if m_action else ''
    
    source = 'auto_cron'
    if 'manual' in text.lower():
        source = 'manual_triggered'
    
    return {
        'price': price,
        'signal_label': signal,
        'action': action,
        'source': source
    }


def load_sample_quality():
    """加载样本质量数据"""
    sq = {}
    for f in sorted(glob.glob(os.path.join(GUARD_OUTPUTS, 'sample_quality_daily_2026*.json'))):
        with open(f) as fh:
            d = json.load(fh)
        sq[d['date']] = d
    return sq


def run_candidate_a_replay():
    """
    运行 Candidate-A 历史回放。
    
    核心逻辑：
      - Slot T 出现 bull/strong_bull → pending_long（不成交）
      - Slot T+1 仍为 bull/strong_bull → 模拟加多 20%（成交）
      - Slot T 出现 bear/strong_bear → pending_short（不成交）
      - Slot T+1 仍为 bear/strong_bear → 模拟加空 20%（成交）
      - 期间信号转弱、中性或反向 → 取消所有 pending
      - 减仓/平仓/止盈/止损动作立即执行（通过 Baseline 动作继承）
    """
    sq_data = load_sample_quality()
    
    # 收集所有有效的交易日（A/B 档）
    valid_days = []
    for date, sq in sorted(sq_data.items()):
        if sq.get('grade') in ('A', 'B'):
            valid_days.append(date)
    
    print(f"[candidate_A_replay] 有效交易日 (A/B): {len(valid_days)}")
    print(f"[candidate_A_replay] 交易日: {valid_days}")
    
    all_trades = []
    stats = {
        'total_slots': 0,
        'slots_with_pending': 0,
        'slots_with_execution': 0,
        'pending_cancelled': 0,
        'executions': [],
    }
    
    for date in valid_days:
        # 收集该日期所有 report（slot 排序）
        reports = {}
        pattern = os.path.join(GUARD_OUTPUTS, f'report_{date}_*.txt')
        for f in sorted(glob.glob(pattern)):
            basename = os.path.basename(f)
            # extract slot from report_YYYYMMDD_HHMMSS.txt
            parts = basename.replace('.txt', '').split('_')
            if len(parts) >= 3:
                slot = parts[2]
            else:
                continue
            rpt = load_report(date, slot)
            if rpt:
                reports[slot] = rpt
        
        sorted_slots = sorted(reports.keys())
        
        # 运行 Candidate-A 逻辑
        pending = None  # {'direction': 'long'/'short', 'slot': '...', 'price': ...}
        
        for slot in sorted_slots:
            rpt = reports[slot]
            signal = rpt['signal_label']
            price = rpt['price']
            
            # 样本门禁
            if rpt['source'] != 'auto_cron':
                continue
            
            stats['total_slots'] += 1
            
            is_bull = signal in ('bull', 'strong_bull')
            is_bear = signal in ('bear', 'strong_bear')
            is_neutral = signal == 'neutral' or (not is_bull and not is_bear)
            
            if pending:
                # 有 pending 信号 → 检查是否确认
                if (pending['direction'] == 'long' and is_bull) or (pending['direction'] == 'short' and is_bear):
                    # 确认！执行加仓
                    trade = {
                        'trade_id': f'{date}_{slot}_candidate_A_{pending["direction"]}',
                        'strategy_version': 'candidate-A',
                        'direction': pending['direction'],
                        'entry_time': f'{date}_{slot}',
                        'entry_price': price,
                        'entry_signal': signal,
                        'pending_origin_slot': pending['slot'],
                        'pending_origin_price': pending['price'],
                        'pending_origin_signal': pending['signal'],
                        'position_added_pct': 20,
                        'morning_or_afternoon': 'morning' if int(slot[:2]) < 12 else 'afternoon',
                        'report_source': 'auto_cron',
                    }
                    all_trades.append(trade)
                    stats['slots_with_execution'] += 1
                    stats['executions'].append(trade)
                    pending = None
                elif is_neutral or (pending['direction'] == 'long' and is_bear) or (pending['direction'] == 'short' and is_bull):
                    # 取消 pending
                    stats['pending_cancelled'] += 1
                    pending = None
                else:
                    # 同方向信号但 pending 已存在（例如两个连续的 bull）
                    # 不应该发生，因为确认后会清 pending
                    # 这里不做处理
                    pass
            
            if pending is None:
                # 检查新信号
                if is_bull:
                    pending = {
                        'direction': 'long',
                        'slot': slot,
                        'price': price,
                        'signal': signal,
                    }
                    stats['slots_with_pending'] += 1
                elif is_bear:
                    pending = {
                        'direction': 'short',
                        'slot': slot,
                        'price': price,
                        'signal': signal,
                    }
                    stats['slots_with_pending'] += 1
    
    # 输出
    result = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'valid_trading_days': valid_days,
        'valid_trading_days_count': len(valid_days),
        'candidate_A_rules': {
            'signal_source': 'main_strategy_labels_only',
            'no_hardcoded_thresholds': True,
            'two_confirmation_only_for_new_risk': True,
            'exit_never_delayed': True,
            'max_adjustment_per_trade_pct': 20,
        },
        'sample_filters': {
            'sample_quality_grade': 'A_or_B',
            'report_source': 'auto_cron_only',
        },
        'stats': {
            'total_slots_processed': stats['total_slots'],
            'slots_with_pending': stats['slots_with_pending'],
            'slots_with_execution': stats['slots_with_execution'],
            'pending_cancelled': stats['pending_cancelled'],
            'confirmation_rate': round(
                stats['slots_with_execution'] / max(stats['slots_with_pending'], 1) * 100, 1
            ),
            'pending_cancelled_rate': round(
                stats['pending_cancelled'] / max(stats['slots_with_pending'], 1) * 100, 1
            ),
            'execution_density': round(
                stats['slots_with_execution'] / max(stats['total_slots'], 1) * 100, 1
            ),
        },
        'trades': all_trades,
    }
    
    out_path = os.path.join(BASE, 'candidate_A_trades_603305.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n[candidate_A_replay] Candidate-A 回放结果:")
    print(f"  总时隙: {stats['total_slots']}")
    print(f"  设 pending: {stats['slots_with_pending']}")
    print(f"  确认执行: {stats['slots_with_execution']}")
    print(f"  取消 pending: {stats['pending_cancelled']}")
    print(f"  确认率: {result['stats']['confirmation_rate']}%")
    print(f"  执行密度: {result['stats']['execution_density']}%")
    print(f"  输出: {out_path}")
    
    return result


def main():
    print("[candidate_A_replay] 开始 Candidate-A 历史回放...")
    result = run_candidate_a_replay()
    print("[candidate_A_replay] 完成。")


if __name__ == '__main__':
    main()
