# ROUND3 FIX REPORT (2026-05-08)

## 已完成（P0）

1. 资金口径默认值统一为 100000（10万元）
- 文件：`auto_report_guard_603305.py`
- 修改：
  - `base = float(st.get('base_capital_cny', 100000) or 100000)`
  - `shadow_base = float(shadow.get('base_capital_cny', 100000) or 100000)`
- 状态文件已写入：
  - `sim_state_603305.json -> base_capital_cny = 100000`
  - `shadow_state_603305.json -> base_capital_cny = 100000`

2. 触发标记拆分为主/影两条
- 文件：`auto_report_guard_603305.py`
- 修改：
  - 新增 `main_trigger_flag`
  - 新增 `shadow_trigger_flag`
  - 输出字段改为：
    - `• 主策略本时点是否新增触发：...`
    - `• 影子策略本时点是否新增触发：...`

3. action/reason 一致性修正（报告层兜底）
- 文件：`auto_report_guard_603305.py`
- 规则：当 `action=持仓不变` 且 `reason` 含“加仓/减仓”时，改写为“已达仓位上限，当前时点持仓不变”。

4. 模板校验项同步
- 文件：`auto_report_guard_603305.py`
- `TEMPLATE_KEYS` 已同步新增主/影两条触发标记字段。

## 可审计文件
- `scripts/calc_winrate_603305_multi.py`
- `strategy_compare_reports/winrate_multi_603305_20260508_181820.json`

## 待下一轮（P1）
1. trigger_id/snapshot_ts 注入主影流水并配对
2. closed_trade 胜率改为严格闭环（含成本）
3. 胜率样本去重（秒级/同分钟重复、满仓强多持仓不变剔除）
