#!/usr/bin/env python3
"""
round_trip_trade_ledger_603305.py

从 Kronos 历史数据重建完整价差交易台账 (round_trip_trade_ledger)。

每笔完整价差交易字段：
  trade_id, strategy_version, direction, entry_time, exit_time,
  holding_minutes, entry_price, exit_price, gross_spread_pct,
  transaction_cost, net_spread_pct, is_win,
  signal_at_entry, signal_at_exit, confirmation_count,
  morning_or_afternoon, sample_quality_grade, report_source,
  entry_position_pct, exit_position_pct, close_reason, rule_version

样本门禁：
  - sample_quality_grade = A 或 B
  - report_source = auto_cron
  其余样本仅出现在 excluded_samples_summary 中。

成本口径：
  transaction_cost = commission(双向) + stamp_duty(卖出) + transfer_fee(双向) + short_borrow_interest(空头)
  多头 short_borrow_interest = 0
  空头 short_borrow_interest = 现有 Kronos 融券利率规则

输出：
  round_trip_trade_ledger_603305.json
  excluded_samples_summary.json
"""

import json
import os
import re
import glob
from collections import defaultdict
from datetime import datetime, timedelta

BASE = '/Users/wxo/Desktop/Kronos'
GUARD_OUTPUTS = os.path.join(BASE, 'guard_outputs')
SIM_LOGS = os.path.join(BASE, 'sim_logs_daily')

# --- 成本配置（复用 sim_costs_603305.json）---
COSTS_PATH = os.path.join(BASE, 'sim_costs_603305.json')
with open(COSTS_PATH) as f:
    costs = json.load(f)
COMMISSION_RATE = costs['commission_rate_one_way']       # 0.01%
STAMP_TAX_SELL = costs['stamp_tax_sell_rate']             # 0.05%
TRANSFER_FEE_RATE = costs['transfer_fee_rate_sh_rate']    # 0.001%
BASE_CAPITAL = costs['base_capital_cny']

# 融券利息（当前 Kronos 规则中无独立配置，暂设合理默认值）
# 按年化 8% / 365 * 持有天数
SHORT_INTEREST_ANNUAL = 0.08


def load_review_data():
    """加载所有 main_shadow_review JSON 文件"""
    reviews = {}
    for f in sorted(glob.glob(os.path.join(GUARD_OUTPUTS, 'main_shadow_review_2026*.json'))):
        with open(f) as fh:
            d = json.load(fh)
        reviews[d['date']] = d
    return reviews


def load_sample_quality():
    """加载所有 sample_quality_daily JSON 文件"""
    sq = {}
    for f in sorted(glob.glob(os.path.join(GUARD_OUTPUTS, 'sample_quality_daily_2026*.json'))):
        with open(f) as fh:
            d = json.load(fh)
        sq[d['date']] = d
    return sq


def load_report_text(day, slot):
    """读取单个 report 文本，提取 price 和 signal label"""
    path = os.path.join(GUARD_OUTPUTS, f'report_{day}_{slot}.txt')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    
    # 提取价格
    m_price = re.search(r'即时价格[：:]\s*([0-9.]+)', text)
    price = float(m_price.group(1)) if m_price else None
    
    # 提取信号标签（偏多/偏空等）
    m_signal = re.search(r'信号[：:]\s*(\S+)', text)
    signal = m_signal.group(1).strip() if m_signal else None
    
    # 确定 report_source
    if 'auto_cron' in text or 'AUTO_CRON' in text:
        source = 'auto_cron'
    elif 'manual' in text.lower() or 'MANUAL' in text:
        source = 'manual_triggered'
    else:
        source = 'auto_cron'  # 默认视为 auto_cron
    
    return {'price': price, 'signal': signal, 'source': source, 'raw_text': text}


def calc_transaction_cost(entry_price, exit_price, direction, position_pct,
                          holding_hours=0):
    """
    计算单笔完整价差交易的成本。
    
    成本 = 佣金(双向) + 印花税(仅卖出) + 过户费(双向, 沪市) + 融券利息(仅空头)
    
    参数：
      entry_price: 入场价
      exit_price: 出场价
      direction: 'long' 或 'short'
      position_pct: 仓位比例 (如 20 表示 20%)
    
    返回：
      cost_pct: 成本占名义本金的比例 (%)
    """
    # 名义本金 = position_pct% * BASE_CAPITAL
    notional = BASE_CAPITAL * (position_pct / 100.0)
    
    # 佣金（双向）
    commission_entry = notional * COMMISSION_RATE
    commission_exit = notional * COMMISSION_RATE
    
    # 印花税（仅卖出，即 long 的 exit 或 short 的 entry）
    if direction == 'long':
        stamp = notional * STAMP_TAX_SELL
    else:
        # 空头：开仓卖出时有印花税，平仓买入时无
        stamp = notional * STAMP_TAX_SELL
    
    # 过户费（双向，沪市 0.001%）
    transfer = notional * TRANSFER_FEE_RATE * 2
    
    # 融券利息（仅空头）
    if direction == 'short':
        interest = notional * SHORT_INTEREST_ANNUAL * (holding_hours / (365 * 24))
    else:
        interest = 0
    
    total_cost = commission_entry + commission_exit + stamp + transfer + interest
    
    # 转换为百分比（占名义本金）
    cost_pct = total_cost / notional * 100 if notional > 0 else 0
    return round(cost_pct, 4)


def detect_direction_from_action(action_text):
    """从 action 文本推测方向"""
    if not action_text:
        return None
    if any(kw in action_text for kw in ['加多', '建多', '平空', '多仓']):
        return 'long'
    if any(kw in action_text for kw in ['加空', '建空', '平多', '空仓']):
        return 'short'
    if '平多' in action_text and '建空' in action_text:
        return 'cross_zero_to_short'
    if '平空' in action_text and '建多' in action_text:
        return 'cross_zero_to_long'
    if '持仓不变' in action_text or '减' in action_text:
        return None  # 持仓不变或减仓，不独立判断方向
    return None


def build_trade_ledger():
    """
    遍历所有 review 行，合成完整价差交易台账。
    """
    reviews = load_review_data()
    sq_data = load_sample_quality()
    
    trades = []
    excluded = {
        'C_D_grade': [],
        'manual_triggered': [],
        'REPORT_INCONSISTENT': [],
        'IDEMPOTENT_SKIP': [],
        'missing_price': [],
        'empty_action': [],
    }
    
    for date, review in sorted(reviews.items()):
        grade = sq_data.get(date, {}).get('grade', 'D')
        auto_count = sq_data.get(date, {}).get('auto_cron_generated', 0)
        
        # 在当前 review 维度追踪 active trades
        active_trades = {}  # key: (strategy_version, direction) -> trade_state
        
        rows = review.get('rows', [])
        for i, row in enumerate(rows):
            slot = row.get('slot', '')
            action = row.get('action', '')
            main_pos = row.get('main_position_pct')
            shadow_pos = row.get('shadow_position_pct')
            main_pnl = row.get('main_net_pnl_pct')
            shadow_pnl = row.get('shadow_net_pnl_pct')
            # 读取 report 文本获取更精确的数据
            rpt = load_report_text(date, slot)
            
            # 过滤不合格样本
            if grade not in ('A', 'B'):
                excluded['C_D_grade'].append(f'{date}_{slot}')
                continue
            if rpt and rpt['source'] == 'manual_triggered':
                excluded['manual_triggered'].append(f'{date}_{slot}')
                continue
            if action == 'REPORT_INCONSISTENT':
                excluded['REPORT_INCONSISTENT'].append(f'{date}_{slot}')
                continue
            if 'SKIP' in action:
                excluded['IDEMPOTENT_SKIP'].append(f'{date}_{slot}')
                continue
            if rpt and rpt['price'] is None:
                excluded['missing_price'].append(f'{date}_{slot}')
                continue
            if not action or action == '':
                excluded['empty_action'].append(f'{date}_{slot}')
                continue
            
            price = rpt['price'] if rpt else None
            signal = row.get('signal', '') or (rpt['signal'] if rpt else '')
            report_source = rpt['source'] if rpt else 'auto_cron'
            
            # 核心统计仅限 A/B + auto_cron
            if report_source != 'auto_cron':
                excluded['manual_triggered'].append(f'{date}_{slot}')
                continue
            
            # 处理 cross-zero: 先关闭旧方向，再开新方向
            if '平多并建空' in action:
                # 关闭 long
                if ('main', 'long') in active_trades:
                    close_trade(active_trades, ('main', 'long'), date, slot, price,
                                'cross_zero_reversal', rpt)
                if ('shadow', 'long') in active_trades:
                    close_trade(active_trades, ('shadow', 'long'), date, slot, price,
                                'cross_zero_reversal', rpt)
                # 开 short
                open_trade(active_trades, trades, ('main', 'short'), date, slot, price,
                           signal, grade, report_source)
            elif '平空并建多' in action:
                # 关闭 short
                if ('main', 'short') in active_trades:
                    close_trade(active_trades, ('main', 'short'), date, slot, price,
                                'cross_zero_reversal', rpt)
                if ('shadow', 'short') in active_trades:
                    close_trade(active_trades, ('shadow', 'short'), date, slot, price,
                                'cross_zero_reversal', rpt)
                # 开 long
                open_trade(active_trades, trades, ('main', 'long'), date, slot, price,
                           signal, grade, report_source)
            
            # 根据 action 决定加仓/减仓
            elif '加' in action:
                direction = detect_direction_from_action(action)
                if direction:
                    # 加仓 → 如果已有 active trade 则累加，否则新建
                    if ('main', direction) in active_trades:
                        # 累加
                        t = active_trades[('main', direction)]
                        t['entry_price'] = (t['entry_price'] * t['entry_position_pct'] + 
                                            price * 20) / (t['entry_position_pct'] + 20)
                        t['entry_position_pct'] += 20
                        t['confirmation_count'] += 1
                    else:
                        open_trade(active_trades, trades, ('main', direction), date, slot,
                                   price, signal, grade, report_source)
            
            elif '减' in action:
                # 部分减仓 → 记录 partial_exit，不关闭 trade
                direction = detect_direction_from_action(action)
                if direction and ('main', direction) in active_trades:
                    t = active_trades[('main', direction)]
                    pct = 0
                    m_pct = re.search(r'减[多空]?\s*\+?(\d+)%', action)
                    if m_pct:
                        pct = int(m_pct.group(1))
                    t['partial_exits'].append({
                        'slot': slot,
                        'price': price,
                        'pct_reduced': pct,
                        'position_left': t['entry_position_pct'] - pct
                    })
                    t['entry_position_pct'] -= pct
            
            # 平仓（持仓归零或全平）
            elif '平' in action and '建' not in action:
                direction = detect_direction_from_action(action)
                if direction and ('main', direction) in active_trades:
                    close_trade(active_trades, ('main', direction), date, slot, price,
                                'manual_close', rpt)
            
            # 持仓不变 → 维持 active trades
            # 不做任何操作
    
    return trades, excluded


def open_trade(active_trades, trades, key, date, slot, price, signal, grade, source):
    """新建一笔 trade"""
    direction = key[1]
    t = {
        'trade_id': f'{date}_{slot}_{key[0][:4]}_{direction}',
        'strategy_version': key[0],  # 'main' or 'shadow'
        'direction': direction,
        'entry_time': f'{date}_{slot}',
        'exit_time': None,
        'holding_minutes': 0,
        'entry_price': price,
        'exit_price': None,
        'gross_spread_pct': None,
        'transaction_cost': None,
        'net_spread_pct': None,
        'is_win': None,
        'signal_at_entry': signal,
        'signal_at_exit': None,
        'confirmation_count': 1,
        'morning_or_afternoon': 'morning' if int(slot[:2]) < 12 else 'afternoon',
        'sample_quality_grade': grade,
        'report_source': source,
        'entry_position_pct': 20,
        'exit_position_pct': None,
        'close_reason': None,
        'rule_version': '2026-06-07-v1',
        'partial_exits': [],
    }
    active_trades[key] = t
    trades.append(t)


def close_trade(active_trades, key, date, slot, price, reason, rpt):
    """关闭一笔 active trade"""
    if key not in active_trades:
        return
    t = active_trades[key]
    t['exit_time'] = f'{date}_{slot}'
    t['exit_price'] = price
    
    # 计算持有时间
    try:
        entry_dt = datetime.strptime(t['entry_time'], '%Y%m%d_%H%M%S')
    except ValueError:
        entry_dt = datetime.strptime(t['entry_time'], '%Y%m%d_%H%M')
    try:
        exit_dt = datetime.strptime(t['exit_time'], '%Y%m%d_%H%M%S')
    except ValueError:
        exit_dt = datetime.strptime(t['exit_time'], '%Y%m%d_%H%M')
    t['holding_minutes'] = int((exit_dt - entry_dt).total_seconds() / 60)
    
    # 计算毛价差
    if t['direction'] == 'long':
        t['gross_spread_pct'] = round((t['exit_price'] - t['entry_price']) / t['entry_price'] * 100, 4)
    else:
        t['gross_spread_pct'] = round((t['entry_price'] - t['exit_price']) / t['entry_price'] * 100, 4)
    
    # 计算成本
    holding_hours = t['holding_minutes'] / 60.0
    cost = calc_transaction_cost(t['entry_price'], t['exit_price'], t['direction'],
                                 t['entry_position_pct'], holding_hours)
    t['transaction_cost'] = cost
    t['net_spread_pct'] = round(t['gross_spread_pct'] - cost, 4)
    t['is_win'] = t['net_spread_pct'] > 0
    t['close_reason'] = reason
    t['signal_at_exit'] = rpt['signal'] if rpt else None
    
    del active_trades[key]


def main():
    print("[round_trip_trade_ledger] 开始重建完整价差交易台账...")
    
    trades, excluded = build_trade_ledger()
    
    # 输出台账
    ledger_path = os.path.join(BASE, 'round_trip_trade_ledger_603305.json')
    with open(ledger_path, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_trades': len(trades),
            'trades': trades
        }, f, ensure_ascii=False, indent=2)
    print(f"  [OK] 台账写入: {ledger_path}")
    print(f"  [OK] 交易笔数: {len(trades)}")
    
    # 输出排除摘要
    summary_path = os.path.join(BASE, 'excluded_samples_summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_excluded': sum(len(v) for v in excluded.values()),
            'breakdown': {k: {'count': len(v), 'samples': v[:20]} for k, v in excluded.items()}
        }, f, ensure_ascii=False, indent=2)
    print(f"  [OK] 排除摘要: {summary_path}")
    
    # 输出核心统计
    core_trades = [t for t in trades if t['is_win'] is not None]
    wins = [t for t in core_trades if t['is_win']]
    losses = [t for t in core_trades if not t['is_win']]
    
    if core_trades:
        win_rate = len(wins) / len(core_trades) * 100
        avg_net = sum(t['net_spread_pct'] for t in core_trades) / len(core_trades)
        total_costs = sum(t['transaction_cost'] for t in core_trades if t['transaction_cost'])
        total_gross = sum(abs(t['gross_spread_pct']) for t in core_trades if t['gross_spread_pct'])
        cost_ratio = total_costs / total_gross * 100 if total_gross > 0 else 0
        
        print(f"\n  核心统计（A/B + auto_cron, {len(core_trades)} 笔已关闭交易）:")
        print(f"    Round-trip win rate: {len(wins)}/{len(core_trades)} ({win_rate:.1f}%)")
        print(f"    Avg net spread: {avg_net:.4f}%")
        if wins:
            print(f"    Avg win: {sum(t['net_spread_pct'] for t in wins)/len(wins):.4f}%")
        if losses:
            print(f"    Avg loss: {sum(t['net_spread_pct'] for t in losses)/len(losses):.4f}%")
        print(f"    Cost/Gross ratio: {cost_ratio:.1f}%")
    
    print(f"\n  排除样本: {sum(len(v) for v in excluded.values())} 条")
    for k, v in excluded.items():
        if v:
            print(f"    {k}: {len(v)} 条")
    
    print("[round_trip_trade_ledger] 完成。")


if __name__ == '__main__':
    main()
