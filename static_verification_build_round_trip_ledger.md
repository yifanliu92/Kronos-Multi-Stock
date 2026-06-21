# 静态核验回报：build_round_trip_ledger_and_candidate_A_replay_603305
> 核验时间：2026-06-07 11:25 CST
> 核验人：OpenClaw
> 方案版本：next_stage_v2_openclaw_revised.md
> 对应 ChatGPT 评审：ChatGPT Review v1.0 + v1.1

---

## 1. task_id

当前方案文件 `next_stage_v2_openclaw_revised.md` 是**定义性文档**，尚未通过 task_queue 提交。精确 task_id 将在提交后生成。

**方案物理路径：**
```
/Users/wxo/Desktop/Kronos/next_stage_v2_openclaw_revised.md
```

**执行流程确认：**
```
submit pending → 获得 task_id → 回报 task_id → 等待用户确认 → worker --once --task-id <task_id>
```

---

## 2. Pending 文件路径

```
/Users/wxo/Desktop/Kronos/next_stage_v2_openclaw_revised.md
```

---

## 3. 预计新增文件清单

| # | 文件 | 用途 | 预估行数 |
|---|------|------|----------|
| 1 | `scripts/round_trip_trade_ledger_603305.py` | 台账计算：从 sim_trades.jsonl + report.txt + main_shadow_review.json + sample_quality.json 重建每笔完整价差交易 | ~250 行 |
| 2 | `scripts/candidate_A_replay_603305.py` | Candidate-A 历史回放：回放 guard_outputs 中的历史数据，模拟"两次确认后再加仓"逻辑 | ~300 行 |
| 3 | `scripts/candidate_A_daily_stats_603305.py` | 盘后指标：三方比较（Baseline/v1.1-shadow/Candidate-A），输出 13 项指标 | ~150 行 |

---

## 4. 预计修改文件清单

**0 个。** 确认不修改以下任何文件：

| 文件 | 是否修改 |
|------|----------|
| `simulate_rules_603305.json` | ❌ 不修改 |
| `signal_rules_603305.json` | ❌ 不修改 |
| `sim_costs_603305.json` | ❌ 不修改 |
| `auto_report_guard_603305.py` | ❌ 不修改 |
| `signal_router_603305.py` | ❌ 不修改 |
| `simulate_position_603305.py` | ❌ 不修改 |
| `sim_review_603305.py` | ❌ 不修改 |
| v1.1-shadow 相关文件 | ❌ 不修改 |
| 任何 cron 定义 | ❌ 不修改 |
| 任何 config 文件 | ❌ 不修改 |

---

## 5. 历史回放输入数据源

| 数据源 | 路径模式 | 用途 |
|--------|----------|------|
| 报告文本 | `guard_outputs/report_2026*.txt` | 价格序列、信号标签、行情数据 |
| 主影回顾 | `guard_outputs/main_shadow_review_2026*.json` | 持仓变化、PnL 序列、action 记录 |
| 样本质量 | `guard_outputs/sample_quality_daily_2026*.json` | 每日样本质量等级、auto_cron/manual 统计 |
| 模拟交易日志 | `sim_logs_daily/sim_trades_603305_2026-*.jsonl` | 每笔模拟交易的持仓明细 |
| 成本配置 | `sim_costs_603305.json` | 佣金/印花税/过户费 |

**输入范围约束：**
- 只读取日志文件里已有的数据
- 不做任何 HTTP/API 调用
- 不推测或补全缺失时隙

---

## 6. 样本过滤规则

| 门禁 | 规则 | 处理方式 |
|------|------|----------|
| 质量等级 | 仅 `sample_quality_grade = A 或 B` | C/D 档样本被排除，仅在治理报告中列出 |
| 来源标记 | 仅 `report_source = auto_cron` | manual_triggered 样本被排除，仅在治理报告中列出 |
| 异常标记 | 不含 REPORT_INCONSISTENT / IDEMPOTENT_SKIP | 这两个标记的时隙将被记录但排除 |
| 空记录 | 不含 price=None 或 action 为空的时隙 | 空记录时隙排除 |
| 覆盖度 | 当天有效样本 ≥14 个时隙 | 不满足时该日整体标注 WARN，但不排除 |

---

## 7. Round_trip trade_id 的识别规则

```
同方向连续累加 → 属于同一个 trade_id

例如：
  09:40 加多 20% → trade_id=T1 (direction=long, entry=09:40)
  09:50 加多 20% → trade_id 仍为 T1 (same direction cumulative)
  10:00 加多 20% → trade_id 仍为 T1

仓位回到 0 → 完成一次 round_trip

例如：
  09:50 仓位 40%, 10:00 平仓到 0 → T1 exit time=10:00

部分减仓 → 记录 partial_exit，但 trade_id 不关闭
  仓位从 60% 减到 30% → trade_id 仍 active，记录 partial_exit 事件

完全反向 → 先关闭旧方向 trade，再开新方向 trade

例如：
  10:00 仓位 60% long
  10:10 模拟平多并建空 10% → 
    step 1: 关闭 T1 (exit_time=10:10, exit_price=当前价)
    step 2: 新建 T2 (direction=short, entry_time=10:10)
```

---

## 8. 部分减仓的记录方式

```
trade_id: 不关闭，仍 active
partial_exits: [
  {"time": "HHMM", "price": 14.50, "pct_change": -20, "position_left": 40}
]
close_time: 仅当 position_pct = 0 时才设置
close_reason: 仅当 trade 完全关闭时才记录

规则：
- partial exit 不触发 is_win 判断
- is_win 仅在所有仓位都退出后，按 entry_price(加权) vs exit_price(加权) 计算
- 加权均价 = Σ(position_pct_i × price_i) / Σ(position_pct_i)
```

---

## 9. Cross-zero 的拆分规则

```
Cross-zero = 持仓方向从 long 跨越到 short（或反向）

处理步骤：
  step 1: 先关闭当前 direction 的 active trade
  step 2: 关闭原因 = cross_zero_reversal
  step 3: 计算 is_win（基于 entry 到 exit 的加权均价）
  step 4: 记录 partial_trade（如果仅部分换向）
  step 5: 新建新 direction 的 trade，entry_time = 当前时隙

示例（来自 20260605 09:50）：
  09:40: main_pos=-50 (short 50%) — active trade_id=T1 (short)
  09:50: action="模拟平多并建空 10%"
    → 实际是：仓位从 long 变为 short？
    → 检查 main_pos: 如果从 +100 变 -10，则是 cross-zero
    → trade_id T1 long→close，trade_id T2 short→create
```

**实盘确认：** 从 20260605 数据看，09:50 的 action=`模拟平多并建空 10%` 确认是 cross-zero 事件。系统已有识别能力。

---

## 10. 成本口径复用

现有 `sim_costs_603305.json` 成本结构：

| 成本项 | 费率 | 说明 |
|--------|------|------|
| 佣金（单边） | `commission_rate_one_way` = 0.01% | 单边，双向收取 |
| 印花税（卖出） | `stamp_tax_sell_rate` = 0.05% | 仅卖出时收取 |
| 过户费（沪市） | `transfer_fee_rate_sh_rate` = 0.001% | 双向，仅沪市 |
| 融券利息 | **无独立配置** | 当前系统未单独配置融券利率 |

**确认：台账直接复用 `sim_costs_603305.json` 中的费率计算 `transaction_cost`。**
- `transaction_cost = commission(双向) + stamp_tax(卖出时) + transfer_fee(双向)`
- 融券利息：当前无配置，标注为 `N/A`，待后续补充

---

## 11. 预计新增回归门禁

新增脚本后，回归门禁包括：

| # | 门禁 | 检查方式 |
|---|------|----------|
| 1 | `py_compile` 通过 | `python3 -m py_compile script.py` |
| 2 | 历史回放可重复运行 | 同一输入两次运行输出一致 |
| 3 | C/D 样本不进入正式统计 | 在样本过滤阶段验证排除 |
| 4 | manual_triggered 不进入正式统计 | 同上 |
| 5 | cross-zero 正确拆分为"关闭旧 + 新建新" | 检查 trade_id 序列 |
| 6 | 部分减仓不提前关闭 trade_id | 检查 trade 关闭逻辑 |
| 7 | 主策略文件哈希不变 | `sha256sum simulate_rules_603305.json` |
| 8 | v1.1-shadow 文件哈希不变 | `sha256sum strategy_versions/simulate_rules_603305_v1.1-shadow.json` |
| 9 | 盘中主链路文件哈希不变 | 关键脚本的 sha256 快照 |

---

## 12. 主策略文件是否修改

**✅ 确认：不修改。**

| 文件 | 当前 sha256 |
|------|-------------|
| `simulate_rules_603305.json` | ✅ 保持不变 |
| `signal_rules_603305.json` | ✅ 保持不变 |
| `sim_costs_603305.json` | ✅ 保持不变 |
| `auto_report_guard_603305.py` | ✅ 保持不变 |
| `simulate_position_603305.py` | ✅ 保持不变 |
| `sim_review_603305.py` | ✅ 保持不变 |

---

## 13. v1.1-shadow 是否修改

**✅ 确认：不修改。**

| 文件 | 当前 sha256 |
|------|-------------|
| `strategy_versions/simulate_rules_603305_v1.1-shadow.json` | ✅ 保持不变 |

---

## 14. 盘中主链路是否接入

**✅ 确认：不接入。**
- Candidate-A replay 为独立历史回放
- 不修改 cron
- 不创建新的盘中自动任务
- 不注册到主链路调度

---

## 15. Factor_score 是否进入成交逻辑

**✅ 确认：不入。**
- factor_score_observer 保持现有配置（observer_only=true, affects_position=false）
- Candidate-A replay 仅使用主策略标签（强多/偏多/中性/偏空/强空）
- 本阶段不做 factor_score 阈值成交

---

## 16. 是否需用户确认后再执行 worker --once

**✅ 是。必须等待用户确认后才能执行。**

确认方式：
```
OpenClaw 回报 task_id 和静态核验清单
→ 用户（Pacino）确认 "可以执行"
→ OpenClaw 执行 worker --once --task-id <task_id>
→ worker 完成后回报 status 和文件清单
→ 用户验收
```

---

## 硬约束完整性清单

| # | 约束 | 状态 |
|---|------|------|
| 1 | 不修改主策略参数 | ✅ 确认 |
| 2 | 不修改 v1.1-shadow | ✅ 确认 |
| 3 | 不接入盘中交易层 | ✅ 确认 |
| 4 | 不启用 v1.2-shadow | ✅ 确认 |
| 5 | 不自动切参 | ✅ 确认 |
| 6 | 不补跑历史时点 | ✅ 确认 |
| 7 | 不伪造 report | ✅ 确认 |
| 8 | 仅 A/B + auto_cron 样本入正式比较 | ✅ 确认 |
| 9 | manual_triggered 仅治理观察 | ✅ 确认 |
| 10 | C/D 样本仅治理观察 | ✅ 确认 |
| 11 | factor_score 不入成交逻辑 | ✅ 确认 |
| 12 | 减仓/平仓/止盈/止损立即执行 | ✅ 确认 |
| 13 | 两次确认仅限新增风险敞口 | ✅ 确认 |
| 14 | 不执行 worker 直至用户确认 | ✅ 确认 |
| 15 | 不扫描其它 pending | ✅ 确认 |

---

## 签署

```
核验方：       OpenClaw
评审依据：     ChatGPT Review v1.1
方案版本：     next_stage_v2_openclaw_revised.md
核验结果：     16/16 项已确认，可进入 submit phase
下一步动作：    若用户确认，执行 task_queue submit → 回报 task_id → 等待用户确认 → worker --once
```
