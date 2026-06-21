# Kronos 603305 下一阶段方案 v1.0-OpenClaw
> 方案状态：待投递 ChatGPTP 评审
> 方案版本：v1.0
> 方案来源：OpenClaw（基于 DeepSeek 两轮评审 + ChatGPTP 完整策略包 + Pacino 综合决策）

---

## 一、上一阶段的结论

### 已完成的三份评审文档

| 文档 | 来源 | 状态 |
|------|------|------|
| `strategy_review_ds_proposal_v1.md` | OpenClaw 对 DeepSeek 第一轮方案评审 | ✅ 已落盘 |
| `strategy_review_ds_proposal_v2.md` | OpenClaw 对 DeepSeek 第二轮方案评审 | ✅ 已落盘 |
| `strategy_review_chatgpt_v2_openclaw.md` | OpenClaw 对 ChatGPTP 完整策略包评审 | ✅ 已落盘 |
| `strategy_final_v1_deepseek_openclaw.md` | DeepSeek × OpenClaw 联合最终方案 | ✅ 已落盘 |

### 综合评审共识

| 结论 | 状态 |
|------|------|
| 现有主策略不应替换 | ✅ 一致 |
| v1.1-shadow 继续观察 | ✅ 一致 |
| cross-zero / cooldown 暂缓 | ✅ 一致（22 天仅 5 次 cross-zero，0 次 whipsaw） |
| candidate-A （两次确认）可开发 observer-only | ✅ 一致 |
| factor_score 保留 observer-only，不入交易层 | ✅ 一致 |
| **DeepSeek 参数优化不应排首位** | **⚠️ OpenClaw 原方案排首位，已被 Corrector 纠正。新顺序见下** |

---

## 二、纠正后的开发顺序

OpenClaw 原建议：`先 DeepSeek 参数优化 → factor_score 统计 → candidate-A`

**Pacino 综合决策，OpenClaw 接受纠正：**

```
第一优先：补齐 round_trip_trade_ledger（完整价差交易台账）
第二优先：开发 Candidate-A observer-only（两次确认观察层）
第三优先：factor_score 独立统计观察
第四优先：累积 A/B 样本后，再考虑参数优化（含 DeepSeek 方案）
```

理由：没有台账根基的调参 = 有限样本上的过拟合。

---

## 三、本次最小开发包

### 任务名称

```
build_round_trip_ledger_and_candidate_A_observer_603305
```

### 涉及文件

#### 新增文件

| 文件 | 说明 | 预计行数 |
|------|------|----------|
| `scripts/round_trip_trade_ledger_603305.py` | 完整价差交易台账计算脚本 | ~200行 |
| `scripts/candidate_A_observer_603305.py` | Candidate-A 观察层模拟脚本 | ~250行 |
| `scripts/candidate_A_daily_stats.py` | 盘后指标输出 | ~100行 |

#### 修改文件

| 文件 | 说明 | 改动量 |
|------|------|--------|
| 无 | 不修改主策略任何文件 | 0 |

#### 硬约束

| # | 约束 | 值 |
|---|------|-----|
| 1 | candidate_A observer_only | true |
| 2 | candidate_A affects_position | false |
| 3 | 修改主策略参数 | **否** |
| 4 | 修改 v1.1-shadow | **否** |
| 5 | 启用 v1.2-shadow | **否** |
| 6 | factor_score 入交易层 | **否** |
| 7 | 改变主策略 action/reason/position_pct | **否** |
| 8 | 自动切参 | **否** |
| 9 | 补跑历史时点 | **否** |
| 10 | 伪造 report | **否** |
| 11 | C/D 样本用于策略评审 | **否**（仅治理观察） |
| 12 | manual_triggered 计为 auto_cron 成功样本 | **否** |

### Candidate-A 信号定义

复用现有 `signal_rules_603305.json` 的方向信号定义：

| 信号 | 定义（涨跌幅 vs 昨收） | 在 candidate-A 中的含义 |
|------|------------------------|------------------------|
| **偏多** | 涨跌幅 ≥ +0.6%（即 `bull`） | 第一次出现 → `pending_long`；第二次连续出现 → 模拟加多 20% |
| **强多** | 涨跌幅 ≥ +1.2%（即 `strong_bull`） | 同上（强多视为偏多的强化版本，触发逻辑相同） |
| **偏空** | 涨跌幅 ≤ -1.2%（即 `bear`） | 第一次出现 → `pending_short`；第二次连续出现 → 模拟加空 20% |
| **强空** | 涨跌幅 ≤ -2.4%（即 `strong_bear`） | 同上 |
| **中性** | -1.2% < 涨跌幅 < +0.6% | 取消所有 pending，不成交 |

### Candidate-A 核心逻辑

```
Slot T:
  信号 = 偏多/强多：
    if pending_long is None:
      pending_long = T（不成交）
    elif pending_long is not None:
      // 确认：第二次连续信号
      模拟加多 20%
      pending_long = None
  信号 = 中性/反向：
    清空 pending_long / pending_short
  信号 = 偏空/强空（同上逻辑）

Slot T+1（10 分钟后）:
  重复上述逻辑
```

### Round_trip_trade_ledger 字段

```
trade_id           : 自增 ID（格式：YYYYMMDD_HHMMSS_seq）
strategy_version   : "baseline" / "shadow" / "candidate-A"
direction          : "long" / "short"
entry_time         : ISO 时间戳
exit_time          : ISO 时间戳
holding_minutes    : 持有时间（分钟）
entry_price        : 成交价
exit_price         : 平仓价
gross_spread_pct   : 毛价差（未扣成本）
transaction_cost   : 交易成本（佣金+印花税+过户费）
net_spread_pct     : 净价差（gross - cost）
is_win             : net_spread_pct > 0
signal_at_entry    : "bull" / "bear" / "strong_bull" / "strong_bear"
signal_at_exit     : 同上
confirmation_count : 连续确认次数
morning_or_afternoon : "morning" / "afternoon"
sample_quality_grade  : "A" / "B" / "C" / "D"
report_source      : "auto_cron" / "manual_triggered"
```

### 盘后输出指标

```
round_trip_win_rate    : 完整价差交易胜率
avg_net_spread_pct     : 每笔平均净价差
profit_factor          : 总盈利 / 总亏损
avg_win_pct            : 平均盈利
avg_loss_pct           : 平均亏损
win_loss_ratio         : 盈亏比
trade_count            : 完整交易次数
transaction_cost_total : 累计成本
cost_to_gross_pnl      : 成本侵蚀比例
morning_pnl            : 早盘收益贡献
afternoon_pnl          : 午后收益贡献
```

### Factor_score 处理

```
角色：仅独立统计观察（observer-only）
不进入 candidate-A 成交逻辑
盘后补充输出：
  - factor_score_at_entry
  - factor_score_at_exit
  - factor_score 与未来 10/20/30 分钟收益的相关系数
```

### 事后评审门槛

```
至少 5 个 A/B 档完整交易日：
  判断方向是否值得继续

至少 10 个 A/B 档完整交易日：
  比较 Candidate-A 与 Baseline、v1.1-shadow

至少 20 个 A/B 档完整交易日：
  才讨论是否进入下一轮参数优化

Candidate-A 进入下一阶段的条件（需同时满足）：
  - round_trip_win_rate 提升
  - avg_net_spread_pct 改善
  - profit_factor 提升
  - 交易成本下降
  - 最大回撤不恶化
```

---

## 四、task_queue 提交信息

| 字段 | 值 |
|------|-----|
| 任务名称 | `build_round_trip_ledger_and_candidate_A_observer_603305` |
| 任务分类 | C 类（模板化 task_queue） |
| 执行状态 | **pending**（不执行 worker --once） |
| 预计新增文件 | 3 个（脚本）|
| 预计修改文件 | 0 个 |
| 会修改主策略参数 | ❌ 否 |
| 会修改 v1.1-shadow | ❌ 否 |
| 会影响主策略动作 | ❌ 否 |
| candidate_A observer_only | ✅ true |
| 是否需要用户确认后执行 worker | ✅ 是 |

---

## 签署

```
方案版本：  v1.0-OpenClaw
评审来源：  DeepSeek（两轮）+ ChatGPTP（完整策略包）
综合裁决：  Pacino（用户）
方案执行：  OpenClaw（task_queue pending）
投递对象：  ChatGPTP（下一轮评审）
```
