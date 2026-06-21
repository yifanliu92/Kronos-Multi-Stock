# 603305 参数速查表（小白版）

对应配置文件：`simulate_rules_603305.json`

## 一、先看这4个最常改参数

1. `thresholds.bull_pct`
- 作用：决定“偏多”触发门槛（相对昨收涨跌幅）
- 现在：`0.6`
- 调小：更容易加仓（更敏感）
- 调大：更难加仓（更稳）

2. `thresholds.bear_pct`
- 作用：决定“偏空”触发门槛
- 现在：`-1.2`
- 绝对值调小（如 -1.0）：更容易触发偏空
- 绝对值调大（如 -1.5）：更难触发偏空

3. `long_side_actions.bull_add_pct`
- 作用：偏多时每次加仓比例
- 现在：`20`
- 调大：上仓更快
- 调小：上仓更慢

4. `take_profit.enabled`
- 作用：是否启用止盈模块
- 现在：`true`
- 设为 `false`：不启用自动止盈（不建议）

---

## 二、仓位管理参数（风控核心）

- `position_management.max_long = 100`
  - 最多只能到100%多仓

- `position_management.max_short = -100`
  - 最多只能到100%空仓

- `position_management.forbid_add_short_at_full_short = true`
  - 满空后禁止继续加空

- `neutral_when_short_cover_pct = 20`
  - 持空遇中性，减空20%

- `bull_when_short_cover_pct = 40`
  - 持空遇偏多，减空40%

- `strong_bull_when_short_cover_pct = 40`
  - 持空遇强多，优先平空/减空40%

---

## 三、止盈参数（建议按组调整）

### 回撤止盈（drawdown_levels）
- 1.0% 回撤 -> 减30%
- 1.8% 回撤 -> 再减30%
- 2.5% 回撤 -> 降到20%底仓

### 浮盈止盈（profit_levels）
- 浮盈3% -> 减30%
- 浮盈5% -> 再减30%
- 浮盈7% -> 再减20%

---

## 四、改参数前后怎么做（最稳流程）

1. 先备份原文件
2. 每次只改1~2个参数
3. 观察至少1个交易日
4. 再决定是否继续调整

---

## 五、口径统一（不要改）

- 涨跌幅统一按“昨收”计算
- 浮盈同时看：
  - 毛浮盈（未扣成本）
  - 净浮盈（已扣累计成本）
