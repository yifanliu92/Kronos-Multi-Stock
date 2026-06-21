# Kronos 603305 下一阶段方案 v2.0-OpenClaw（修订版）
> 方案状态：已按 ChatGPT 评审意见修订
> 方案版本：v2.0
> 方案来源：OpenClaw（原始方案 v1.0）→ ChatGPT（评审意见）→ OpenClaw（修订版 v2.0）
> 对应 ChatGPT 评审：ChatGPT Review v1.0（日期 2026-06-07）

---

## 一、修订对照

| 讨论项 | OpenClaw v1.0 原方案 | ChatGPT 评审意见 | OpenClaw v2.0 修订 |
|--------|---------------------|-----------------|-------------------|
| 任务名 | `build_round_trip_ledger_and_candidate_A_observer_603305` | 改为 `build_round_trip_ledger_and_candidate_A_replay_603305` | ✅ 已改为 replay |
| Candidate-A 信号 | 硬编码阈值（偏多≥+0.6%） | 直接读取主策略输出标签，不硬编码阈值 | ✅ 改为读取标签 |
| 两次确认范围 | 未明确限定 | 仅限"新增风险敞口"，退出不减不延迟 | ✅ 已限定 |
| 第一阶段范围 | 直接入盘中 | 先仅做历史回放 | ✅ 改为 history replay only |
| report_source | 字段提及但未强制区分 | 强制 auto_cron / manual_triggered 区分 | ✅ 已加入强制规则 |
| 样本门禁 | A/B 档评审，C/D 排除 | 增加 auto_cron 门禁 | ✅ A/B + auto_cron 双门禁 |
| entry/exit position_pct | 无 | 新增字段 | ✅ 已加入 |
| close_reason | 无 | 新增字段 | ✅ 已加入 |
| avg_holding_minutes | 无 | 增加统计指标 | ✅ 已加入 |
| max_drawdown | 无 | 增加统计指标 | ✅ 已加入 |

---

## 二、任务定义

### 任务名称

```
build_round_trip_ledger_and_candidate_A_replay_603305
```

### 任务分类

C 类（模板化 task_queue）

### 执行状态

**pending**（不执行 worker --once，需用户确认后再执行）

---

## 三、涉及文件

### 新增文件

| 文件 | 说明 | 预计行数 |
|------|------|----------|
| `scripts/round_trip_trade_ledger_603305.py` | 完整价差交易台账计算脚本 | ~200行 |
| `scripts/candidate_A_replay_603305.py` | Candidate-A 历史回放脚本（读取已有报告） | ~300行 |
| `scripts/candidate_A_daily_stats_603305.py` | 盘后指标输出（含 Baseline/v1.1-shadow/Candidate-A 比较） | ~150行 |

### 修改文件

**0 个。** 不修改主策略、影子策略、cron、配置、盘中链路中的任何文件。

---

## 四、Candidate-A 核心规则（无硬编码阈值）

### 信号来源

直接读取现有主策略 `signal_router_603305.py` / `auto_report_guard_603305.py` 输出的方向信号标签：

```
强多     (strong_bull)
偏多     (bull)
中性     (neutral)
偏空     (bear)
强空     (strong_bear)
```

Candidate-A **不重新定义阈值**，只新增一个变量：

```
新增风险敞口前，必须连续两个时点出现同方向信号
```

### 新增风险敞口规则（仅这一部分需要两次确认）

```
Slot T:
  信号标签 = 偏多/强多：
    if pending_long is None:
      记录 pending_long（来自 T 时隙），不成交
  elif pending_long is not None:
    已确认：模拟加多 20%
    清 pending_long

  信号标签 = 偏空/强空：对称逻辑

  信号标签 = 中性、或与前一次反向：
    清所有 pending，不成交
```

### 减仓/平仓/止盈/止损/风控退出规则（立即执行，不等待）

```
以下动作不得延迟，必须立即执行：

- 减仓
- 平仓
- 止盈
- 止损
- 风险退出

两次确认机制只用于新增风险敞口，不得用于延迟退出。
```

---

## 五、第一阶段仅历史回放

### 回放数据源

使用已存在的 `guard_outputs/report_2026*.txt` 文件进行重建回放。

### 准入门禁

```
准入条件（两者必须同时满足）：
  1. sample_quality_grade = A 或 B
  2. report_source = auto_cron

排除条件（任一满足即排除）：
  - C/D 档样本
  - 限流中断样本
  - 缺报样本
  - 脚本错误样本
  - REPORT_INCONSISTENT 样本
  - 人工触发样本（manual_triggered）
```

### 回放输出

```
有效交易日数量
有效报告数量
排除样本数量
排除原因分布（按排除类型归类统计）
```

---

## 六、完整价差交易台账字段

```
trade_id              : 自增 ID (YYYYMMDD_HHMMSS_seq)
strategy_version      : "baseline" / "shadow" / "candidate-A"
direction             : "long" / "short"
entry_time            : ISO 时间戳
exit_time             : ISO 时间戳
holding_minutes       : 持有时间（分钟）
entry_price           : 成交价
exit_price            : 平仓价
gross_spread_pct      : 毛价差（未扣成本）
transaction_cost      : 交易成本（佣金+印花税+过户费）
net_spread_pct        : 净价差（gross - cost）
is_win                : net_spread_pct > 0
signal_at_entry       : "strong_bull" / "bull" / "bear" / "strong_bear"
signal_at_exit        : 同上
confirmation_count    : 连续确认次数
morning_or_afternoon  : "morning" / "afternoon"
sample_quality_grade  : "A" / "B" / "C" / "D"
report_source         : "auto_cron" / "manual_triggered"
entry_position_pct    : 入场时仓位比例
exit_position_pct     : 退场时仓位比例
close_reason          : "take_profit" / "stop_loss" / "signal_reversal" / "time_exit" / "full_lock" / "market_close"
rule_version          : 规则版本号（如 "2026-06-07-v1"）
```

---

## 七、盘后统计指标

### 必须输出

```
round_trip_win_rate       : 完整价差交易胜率
avg_net_spread_pct        : 每笔平均净价差
profit_factor             : 总盈利 / 总亏损
avg_win_pct               : 平均盈利
avg_loss_pct              : 平均亏损
win_loss_ratio            : 盈亏比
trade_count               : 完整交易次数
transaction_cost_total    : 累计成本
cost_to_gross_pnl         : 成本侵蚀比例
morning_pnl               : 早盘收益贡献
afternoon_pnl             : 午后收益贡献
avg_holding_minutes       : 平均持有时间
max_drawdown              : 最大回撤
```

### 必须进行三方比较

```
Baseline      (现有主策略)
v1.1-shadow   (现有影子策略)
Candidate-A   (历史回放)
```

---

## 八、Factor_score 的处理方式

```
角色：仅独立统计观察（observer-only）

本阶段：
  factor_score 不进入 Candidate-A 成交逻辑
  factor_score_observer 继续保留现有配置
    - observer_only = true
    - affects_position = false

补充统计输出：
  - factor_score_at_entry
  - factor_score_at_exit
  - factor_score 与未来 10 / 20 / 30 分钟收益的相关系数

后续（Phase 2，非本阶段）：
  累积数据后决定是否将 factor_score 纳入下一版 Candidate-A2
```

---

## 九、硬约束清单

```
1.  不修改主策略参数
2.  不修改现有 v1.1-shadow
3.  不接入盘中交易层
4.  不改变主策略 action/reason/position_pct
5.  不启用 v1.2-shadow
6.  不自动切参
7.  不让 factor_score 进入成交逻辑
8.  不补跑历史时点
9.  不伪造 report
10. 不使用 C/D 样本评估策略优劣
11. manual_triggered 不得计入 auto_cron 成功
12. 未经用户确认，不进入 Phase 2
```

---

## 十、后续评审门槛

```
至少 5 个 A/B 档 + auto_cron 完整交易日：
  判断两次确认方向是否值得继续

至少 10 个 A/B 档 + auto_cron 完整交易日：
  比较 Candidate-A 与 Baseline、v1.1-shadow

至少 20 个 A/B 档 + auto_cron 完整交易日：
  才讨论是否进入下一轮参数优化

Candidate-A 进入下一阶段的条件（需同时满足）：
  - round_trip_win_rate 提升
  - avg_net_spread_pct 改善
  - profit_factor 提升
  - 交易成本下降
  - 最大回撤不恶化
```

---

## 十一、task_queue 提交信息

| 字段 | 值 |
|------|-----|
| 任务名称 | `build_round_trip_ledger_and_candidate_A_replay_603305` |
| 任务分类 | C 类（模板化 task_queue） |
| 执行状态 | **pending**（不执行 worker --once） |
| 预计新增文件 | 3 个 |
| 预计修改文件 | 0 个 |
| 是否改为 Candidate-A replay 优先 | ✅ 是 |
| 是否取消 Candidate-A 第一版硬编码阈值 | ✅ 是（改为读取主策略标签） |
| 是否明确"仅新增风险敞口需要两次确认" | ✅ 是（退出不加延迟） |
| 是否保留减仓/平仓/止盈/止损立即执行 | ✅ 是 |
| 是否加入 report_source 强制区分 | ✅ 是 |
| 是否只允许 A/B + auto_cron 入正式比较 | ✅ 是 |
| 是否会修改主策略参数 | ❌ 否 |
| 是否会修改 v1.1-shadow | ❌ 否 |
| 是否会影响盘中动作 | ❌ 否 |
| candidate_A observer_only | ✅ true（本阶段仅 history replay，不上链路） |
| 是否需要用户确认后再执行 worker --once | ✅ 是 |

---

## 签署

```
方案版本：    v2.0-OpenClaw（修订版）
原始方案：    v1.0-OpenClaw
评审方：      ChatGPT（ChatGPT Review v1.0）
修订方向：    全量采纳 ChatGPT 评审意见
综合裁决：    Pacino（用户）
方案执行：    OpenClaw（task_queue pending）
状态：        投递 ChatGPTP 最终确认
```
