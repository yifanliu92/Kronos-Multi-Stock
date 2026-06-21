# 603305 参数对照表（主策略 vs 影子策略 v1.1-shadow）

更新时间：2026-05-08  
主策略规则：`simulate_rules_603305.json`（`2026-04-29-v1`）  
影子策略规则：`strategy_versions/simulate_rules_603305_v1.1-shadow.json`（`2026-04-30-v1.1-shadow`）

---

## 1) 结论先看

- **参数数量与功能维度**：影子策略 > 主策略
- **共同部分**：阈值、基础仓位管理、多空加减仓比例基本一致
- **主要差异**：
  1. 影子策略止盈阈值更“日内化/更早触发”
  2. 影子策略新增两类过滤器：量能确认、止盈后回补

---

## 2) 逐模块对照

## A. thresholds（信号阈值）
- bull_pct：主 0.6｜影 0.6（相同）
- bear_pct：主 -1.2｜影 -1.2（相同）

结论：信号阈值一致。

## B. position_management（仓位管理）
以下字段主/影一致：
- max_long = 100
- max_short = -100
- neutral_when_short_cover_pct = 20
- bull_when_short_cover_pct = 40
- strong_bull_when_short_cover_pct = 40
- strong_bull_when_short_cover_first = true
- forbid_add_short_at_full_short = true

结论：基础仓位框架一致。

## C. take_profit（止盈模块）

### C1 回撤止盈 drawdown_levels
- 主：1.0% / 1.8% / 2.5%
- 影：0.9% / 1.6% / 2.2%

解读：影子策略回撤阈值更紧，更早触发减仓。

### C2 浮盈止盈 profit_levels
- 主：3.0%(-30) / 5.0%(-30) / 7.0%(-20)
- 影：1.2%(-15) / 2.0%(-15) / 3.0%(-20)

解读：影子策略更偏“早止盈、分小步减仓”。

## D. long/short side actions（多空动作）
- bull_add_pct：主 20｜影 20（相同）
- strong_bull_add_pct：主 30｜影 30（相同）
- bear_add_pct：主 20｜影 20（相同）
- strong_bear_add_pct：主 30｜影 30（相同）

结论：多空基础动作一致。

## E. filters（仅影子策略新增）

### E1 volume_confirm_for_add（量能确认）
- enabled: true
- lookback_bars: 5
- ratio_gt: 1.2
- apply_to: bull/strong_bull
- session_ratio: am=1.25, pm=1.15

作用：多头加仓前先看量能是否达标。

### E2 reentry_after_take_profit（止盈后回补）
- enabled: true
- reentry_pct: 10
- max_reentries_per_day: 2
- condition: 价格回收接近高位 + 量能确认

作用：止盈后允许有限度回补，减少“卖飞”。

---

## 3) 实操含义

1. **影子策略更灵敏**：更早止盈、更多过滤、允许受控回补。  
2. **主策略更稳健朴素**：规则更直，噪声敏感度相对低。  
3. **为什么要并行**：用同一时点样本验证“影子的复杂度是否真的带来净收益提升”。

---

## 4) 升级建议（用于后续切换判断）

建议继续沿用你当前口径：
- 样本数达标后（例如 >=30 有效样本），比较：
  - 交易胜率
  - 盈亏比
  - 最大回撤
  - 净值差额
- 仅当影子策略在核心指标上稳定优于主策略，再考虑替换主策略。
