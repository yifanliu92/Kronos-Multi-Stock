# KRONOS_GOVERNANCE_BASELINE_v0.3

## 当前版本状态
- 治理版本：v0.3
- 回归状态：FAIL=0, WARN=0（通过）
- 基线目标：在不触发策略功能变更的前提下，固化治理约束与执行入口。

## 已通过的治理项
1. 建立系统契约：`KRONOS_SYSTEM_CONTRACT.md`
2. 建立回归入口：`scripts/run_kronos_regression.sh`
3. 回归分区化输出（Contract / Provider / Position-Short / Cross-zero synthetic / Report / Winrate naming / Factor gate）
4. provider 字段稳定透出（primary/fallback/third/final 全字段）
5. 因子层保持 observer-only，且 gate 生效（不允许自动进入 v1.2-shadow）
6. **task_queue 机制（长任务脱离对话回合）**：新增 `task_queue/` + `kronos_submit_task.py` + `kronos_task_worker.py --once` + `kronos_task_status.py`；用于避免长任务在 Telegram/OpenClaw 对话回合中触发 timeout。
7. **rate_limit_guard 保护模式**：protection_mode=true 时阻断 P1/P2，仅放行 P0。

## 当前允许事项
- 继续治理阶段
- 继续 observer-only 数据积累
- **P0 盘中保运行任务可自动执行**（every10 主/影输出、模型/行情/投递/P0修复）
- **P1/P2 治理任务必须人工确认 + task_queue 执行**（提交→确认→worker --once→查询状态→读取产物）

## 当前禁止事项
- 启用 v1.2-shadow
- 修改主策略参数
- 修改影子策略参数
- 启用 closed_trade
- 让 factor_observer 进入交易层
- 因单日表现切换主策略
- **禁止在 Telegram/OpenClaw 对话回合中直接跑 >30 秒的本地长任务（P1/P2）**
- **禁止常驻 worker（禁止 kronos_task_worker.py --loop）**
- **禁止 A/B/C/D 自动连跑：每一步完成后必须等待用户确认**
- **protection_mode=true 时禁止执行 P1/P2（仅 P0 放行）**

## 进入策略功能阶段的准入条件
在用户明确确认前，禁止进入策略功能阶段。即使后续进入评估，也必须先满足：
1. 回归先行：执行 `bash /Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh`
2. 回归门槛：`FAIL=0` 且 `WARN=0`
3. 契约一致：改动不违反 `KRONOS_SYSTEM_CONTRACT.md`
4. 因子策略门槛（如涉及）：仍需满足 observer-only 升级条件并经用户确认

## 当前关键文件清单
- `/Users/wxo/Desktop/Kronos/KRONOS_SYSTEM_CONTRACT.md`
- `/Users/wxo/Desktop/Kronos/KRONOS_GOVERNANCE_BASELINE_v0.3.md`
- `/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh`
- `/Users/wxo/Desktop/Kronos/signal_router_603305.py`
- `/Users/wxo/Desktop/Kronos/simulate_position_603305.py`
- `/Users/wxo/Desktop/Kronos/simulate_position_603305_shadow.py`
- `/Users/wxo/Desktop/Kronos/scripts/factor_observer_603305.py`
- `/Users/wxo/Desktop/Kronos/scripts/factor_observer_5d_review.py`

## 最近一次回归日志
- `/Users/wxo/Desktop/Kronos/guard_outputs/regression_20260521_000637.log`

## 执行前置（固定）
后续任何功能开发前，必须先执行：

```bash
bash /Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh
```

且必须满足：
- FAIL=0
- WARN=0
