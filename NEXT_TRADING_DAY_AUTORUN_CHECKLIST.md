# NEXT_TRADING_DAY_AUTORUN_CHECKLIST

## 目标
下个交易日自动执行主策略与影子策略，并在每次回报中可追踪“执行了什么、用的哪个版本、来源标签是什么”。

## 执行版本（开盘前锁定）
- 主策略：v1
- 影子策略：2026-04-30-v1.1-shadow
- 来源标签：
  - source_claude: claude_suggestion_2026-04-30
  - source_chatgpt: chatgpt_review_2026-04-30
  - source_deepseek: deepseek_review_2026-04-30
  - source_self: pacinoai_internal

## 开盘前检查
1. 配置与版本文件可读：
   - strategy_versions/live_version.txt
   - strategy_versions/shadow_version.txt
   - strategy_versions/simulate_rules_603305_v1.1-shadow.json
2. 状态与日志可写：
   - sim_state_603305.json
   - sim_trades_603305.jsonl
   - sim_logs_daily/
3. 输出模板字段检查：成本口径、持仓成本两位小数、影子交割字段。

## 盘中每10分钟自动执行
1. 运行主策略脚本：simulate_position_603305.py
2. 同步输出主策略固定模板字段：
   - 时间/标的/启动资金/即时价格/行情/信号/动作/模拟仓位/理由
   - 建仓明细/建仓均价
   - 毛浮盈/净浮盈（含累计成本）
3. 同步输出影子策略字段：
   - 是否触发
   - 交割时间、交割价格、仓位变化
   - 新增交易成本、累计交易成本
   - 影子持仓成本（两位小数）与净值差额

## 收盘复盘（15:00）
1. 运行复盘脚本：sim_review_603305.py
2. 输出主策略与影子策略对照（含来源标签）
3. 输出改进建议与次日执行重点

## 异常处理
- 数据源失败：输出兜底文案，不中断任务链路
- 长流程>3分钟：主动发送简短进度
- 出现阻塞：明确“卡点+所需协助”

## 回报规范
- 每日首条自动回报包含：
  - 今日执行版本
  - 任务清单编号：NEXT_TRADING_DAY_AUTORUN_CHECKLIST
  - 来源标签
