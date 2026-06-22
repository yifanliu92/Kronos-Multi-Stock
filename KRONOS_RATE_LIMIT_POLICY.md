# KRONOS_RATE_LIMIT_POLICY (v0.1)

> 目标：在 **ChatGPT/Codex OAuth 通道**（非 OpenAI API 订阅）额度/限流场景下，优先保证盘中 P0 任务准点运行；避免治理任务连跑导致触发限流。

## 0. 术语

- **限流/额度提示**：包括但不限于：
  - "You have hit your ChatGPT usage limit"
  - "API rate limit reached"
  - "Request timed out before a response was generated"（视为风险信号，需记录但不等同于限流）
- **通道解释口径**：
  - 不解释为 OpenAI API 余额/订阅问题
  - 统一解释为：**ChatGPT/Codex OAuth 通道限流/额度限制**

## 1. 全局防限流原则（强制）

1) 禁止 A/B/C/D 自动连跑（必须逐步执行，且每步完成后等待用户确认，除 P0 盘中保运行外）。
2) 除 P0 盘中保运行任务外，不得自动连续发起新模型调用。
3) 失败不得无限重试：同一任务最多自动重试 1 次。
4) 非盘中任务一律低频执行；长任务必须拆分为短任务，但 **不能拆成连续轰炸模型**。
5) **所有预计 >30 秒的 P1/P2 治理任务必须走 task_queue**（提交→确认→`kronos_task_worker.py --once`→查状态/读产物）。
6) **禁止在 Telegram/OpenClaw 对话回合中直接跑长命令**（避免 timeout 与通道限流叠加）。
7) **worker 默认只允许 `--once`；禁止常驻 worker（禁止 `--loop`）**。

## 2. 任务分级

### P0（允许盘中自动运行）
- 主/影策略 every10 输出（auto_report_guard）
- model_guard
- 行情失败报码 / 兜底
- Telegram 投递失败处理
- 满仓锁定违规拦截
- 关键 report 不落盘修复

### P1（休市后人工确认执行）
- intraday_chain_review
- main_shadow_review
- template_enhancement
- factor_observer backfill
- strategy_param_proposal
- regression 全量回归

### P2（低优先级，禁止自动连续运行）
- 历史回算
- 大规模全库扫描
- 多文件重构
- 长报告生成

## 3. cron 限流策略

1) 盘中 every10（P0）保留。
2) 治理类 cron（P1/P2）默认 disabled 或必须显式人工确认后启用。
3) close_review / self_audit 可保留，但不得自动串长链路治理。
4) factor_observer 只允许盘后一次（工作日 15:15），不得盘中 every10。
5) 新增 cron 必须声明：任务等级 P0/P1/P2、是否允许自动运行、最大频率、是否需用户确认。

## 4. 状态回执限流（Telegram 防刷屏）

1) 任务开始：允许回执 1 次。
2) 运行超过 90 秒：允许回执 1 次。
3) 不允许每分钟连续心跳刷屏；若仍未完成，写本地日志即可。
4) 任务完成：回执 1 次。
5) 任务失败：回执 1 次。

## 5. daily_usage_guard（保护模式）

### 5.1 记录字段（日文件）
- model_call_count_estimate
- cron_trigger_count
- telegram_reply_count
- failed_call_count
- rate_limit_count

输出：`guard_outputs/rate_limit_daily_YYYYMMDD.json`

### 5.2 自动进入保护模式条件
任一满足则进入 protection_mode=true：
- 10 分钟内连续 3 次模型错误
- 10 分钟内连续 3 次 rate limit
- 任一任务重复触发失败（同一任务窗口内）
- Telegram 连续返回 rate limit

### 5.3 保护模式动作（强制）
1) 禁止所有 P1/P2 任务执行
2) 只保留 P0 盘中保运行任务
3) 停止自动 A/B/C/D
4) 不再发送连续状态心跳
5) 仅允许输出 1 条通知："已进入限流保护模式"

## 6. run_with_model_guard.sh 接入（强制）

- 每次执行前先调用 `scripts/rate_limit_guard.py --check`。
- 若 task_grade=P0：允许执行。
- 若 task_grade=P1/P2 且 protection_mode=true：阻断，不触发模型；仅落盘 blocked 证据。

## 7. task_queue + worker --once（强制）

- 目录：`/Users/yifliu/Kronos-Multi-Stock/task_queue/`
- 提交：`python3 scripts/kronos_submit_task.py <task_name> "<command>"`（立即返回 task_id，不等待执行）
- 执行：用户确认后执行一次 `python3 scripts/kronos_task_worker.py --once`（只处理一个 pending 任务，执行完退出）
- 查询：`python3 scripts/kronos_task_status.py <task_id>`（只读状态文件，不触发长任务）

强制规则：
1) P1/P2 长任务（>30秒）必须走 task_queue。
2) 禁止自动连跑 A/B/C/D。
3) protection_mode=true 时，worker 不得执行 P1/P2（会被直接阻断并落盘）。
4) 任务 done/failed 后必须等待用户确认再提交下一步。

