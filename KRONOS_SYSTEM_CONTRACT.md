# KRONOS_SYSTEM_CONTRACT.md

## 1. 系统定位
Kronos 是 603305 long-short 模拟策略研究系统。

允许做空，但做空必须作为正式空头策略处理，不能只让仓位变成负数。

做空必须完整记录：
- 空头仓位
- 空头建仓均价
- 空头持仓市值
- 空头浮盈浮亏
- 空头交易成本
- 空头回补动作
- 多空穿越动作
- 空头风控规则

## 2. 主策略 / 影子策略原则
- 主策略保持稳定运行；
- 影子策略用于并行观察和验证；
- 不因 1～2 天表现切换主策略；
- 主/影对比必须基于同一交易日、同一资金口径、同一统计口径；
- 未经用户确认，不得把影子策略升级为主策略；
- 未经用户确认，不得启用 v1.2-shadow 或更激进版本。

## 3. 行情源规则
行情源顺序固定为：
1) 东财 push2 primary
2) 东财 push2his fallback
3) 腾讯 qt.gtimg third fallback

要求：
- 禁止旧快照冒充实时行情；
- 三源全部失败时必须不调仓；
- raw_length=0 必须输出 EM_RAW_EMPTY；
- HTTP 非 200 输出 EM_HTTP_STATUS；
- 超时输出 EM_TIMEOUT；
- 字段缺失输出 EM_FIELD_MISSING；
- 类型转换失败输出 EM_TYPE_CAST；
- 腾讯兜底成功时必须明确输出 provider_final=tencent；
- report 中必须透出 primary/fallback/third 的结果。

## 4. 资金规则
- base_capital_cny 默认 100000；
- 满仓后不得追加新资金；
- 只能使用仓位释放出的资金再交易；
- report 必须输出：
  - base_capital_cny
  - available_cash_before
  - available_cash_after
  - position_market_value
  - new_capital_injected

## 5. 仓位规则
- position_pct > 0：多头；
- position_pct = 0：空仓；
- position_pct < 0：空头；
- 禁止把负仓位显示为空仓；
- curr > 0 且 target < 0 时，必须标记 cross_zero_action=true；
- 多空穿越必须记录：
  - cross_zero_from
  - cross_zero_to
  - cross_zero_reason

## 6. 空头计量规则
空头浮盈率公式：
(short_avg_entry_price - current_price) / short_avg_entry_price

空头 report 必须输出：
- short_avg_entry_price
- short_position_pct
- short_market_value
- short_unrealized_pnl
- short_cost
- short_cover_action

## 7. report 规则
禁止出现：
- 信号字段固定写“中性”；
- 本时点是否新增触发固定写“否”；
- action=持仓不变，但 reason=按规则加仓/减仓；
- position_pct<0，但显示为空仓；
- 三源失败，但仍输出旧价格作为实时行情；
- closed_trade 未严格定义，却把 action_to_next_action 称为闭环交易胜率。

## 8. 胜率口径规则
- next_tick：下一跳方向胜率；
- h30：30分钟方向胜率；
- close：收盘口径方向胜率；
- action_to_next_action：相邻有效动作方向胜率；
- action_to_next_action 不能叫 closed_trade；
- closed_trade 必须单独严格定义，必须扣成本，必须按完整交易闭环计算。

## 9. factor_observer 规则
factor_observer 永远先 observer-only。

在同时满足以下条件前，不得进入 v1.2-shadow：
- n_days >= 3（建议 5）；
- factor_available_ratio_5d >= 80%；
- valid_relation_sample_count_5d >= 50；
- hint_keep_vs_caution_spread 稳定为正；
- downgrade_candidate_hit_rate > 0.5；
- 用户明确确认。

未满足前：
- 禁止因子影响主/影交易动作；
- 禁止因子改变 position_pct；
- 禁止把 caution 当作减仓信号；
- 禁止把 downgrade_candidate 当作正式降级信号；
- 禁止把 momentum_pass 当作加仓确认。

## 10. 自审计规则
每日 15:10 生成：
- error_code_daily_YYYYMMDD.json
- compliance_daily_YYYYMMDD.json
- data_auth_daily_YYYYMMDD.json
- scorecard_daily_YYYYMMDD.json
- self_audit_summary_YYYYMMDD.md

score < 80 或任一 FAIL 时，必须触发告警和修复建议。

## 11. 交付纪律
每次修改后必须输出：
- 修改文件清单
- 每文件改动点
- 是否已验证
- 验证命令
- 验证结果
- 未完成项
- 下一步最小动作
- 记忆落盘路径
