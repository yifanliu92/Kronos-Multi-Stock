# Kronos 能力梳理（修订版）

> 口径：以当前 **KRONOS_GOVERNANCE_v0.3_WARN0** 基线为准；所有“可用/可改/可评估”均受回归与门禁约束。

## 总览（含“当前最大限制”）

**当前最大限制（必须显式声明）**
- 缺少连续 **A/B 档**“完整交易日”样本（用于全天绩效辅助判断的样本不足）。
- **不允许启用 v1.2-shadow**（仍处于禁止状态）。
- **不允许改主/影参数**（治理基线冻结；除非走“按契约修复→跑回归→FAIL/WARN=0→人工确认”流程）。
- **不允许 factor_observer 入交易层**（observer-only）。

**full_lock 口径**
- 结论：**执行一致性已治理，但收益影响仍需观察**（不能表述为“策略已有效/收益已确认”）。

**盘后复盘门禁（sample_quality_grade）**
- **A/B 样本：**允许用于“全天绩效”辅助判断（例如：方向胜率、日内收益曲线、策略优劣对比的参考）。
- **C/D 样本：**仅允许用于“治理与局部观察”（例如：数据完整性、报表一致性、错误码分布、局部时段行为），**禁止**用于策略优劣/参数优劣/启用 v1.2-shadow 的依据。
- 明确标注：**20260522 = D 档事故样本**（partial_day_interrupted_by_rate_limit），不得用于策略优劣结论。

---

## 1) 行情源（Quote Provider）

**功能模块**
- 行情抓取与解析、失败降级、provider 字段标准化透出。

**文件路径**
- 主要抓取/路由：`/Users/wxo/Desktop/Kronos/signal_router_603305.py`
- 诊断脚本：`/Users/wxo/.openclaw/workspace/scripts/diagnose_quote_sources.sh`
-（若存在）主/影模拟脚本会在日志中记录 provider 字段：`/Users/wxo/Desktop/Kronos/simulate_position_603305.py`、`/Users/wxo/Desktop/Kronos/simulate_position_603305_shadow.py`

**当前状态（按你要求补齐“腾讯兜底状态”）**
- 当前是否只用 Eastmoney：**是**（当前执行口径为 Eastmoney 单源；不再把 Sina 当作生产兜底）。
- push2 / push2his 是否为同源备份：**是**（同为 Eastmoney 同源备用域名/接口，用于同源 failover）。
- Tencent 第三源：**当前不作为生产兜底**；如保留则仅用于 **诊断/比对**（避免引入新的不确定性与策略口径漂移）。
- `provider_final` 字段记录方式：
  - 记录 **最终实际使用的行情提供方**（例如 `eastmoney_push2` / `eastmoney_push2his`；若仅记录到 `eastmoney` 也需在代码/文档中明确“final 仅到 provider 级别、未细分域名”的现状）。
  - 同时保留 primary/fallback/third/final 的 result/error_code/raw_length 等字段（用于审计与回归门禁）。

**回归是否通过**
- 口径：以 `run_kronos_regression.sh` 为准；在 v0.3 基线下曾达成 **WARN=0**（详见治理基线记录）。

**是否影响策略参数**
- **否（原则上）**：行情源属于执行/数据层，目标是“稳定取数+可审计”。
- 但：行情源变更可能导致价格/成交额字段差异，进而影响触发；因此任何 provider 行为变化都应视为 **执行层变更**，需回归通过后再上线。

**风险/未完成项**
- “单源 Eastmoney”带来的系统性风险：HTTP 403/限流/字段变更会直接影响可用性。
- Tencent 若仅诊断：需要明确“诊断触发条件/不进入交易层”的开关与日志标记，避免误用。

---

## 2) 自动化执行（Cron / Slot 调度）

**功能模块**
- 交易日盘中定时运行（每10分钟等），收盘复盘；期望时隙（expected_slots）生成与覆盖率审计。

**文件路径**
- 任务调度配置/生成脚本（示例）：`/Users/wxo/.openclaw/workspace/scripts/schedule_kronos_cn_market.sh`
- 时隙覆盖/审计输出（产物目录口径）：`/Users/wxo/Desktop/Kronos/guard_outputs/`

**当前状态**
- 具备“按交易日历门禁跳过非交易日”的能力；非交易日 expected_slots=0。
- 具备“时隙幂等去重（slot done 标记）”能力，避免重复回报。

**回归是否通过**
- 以 v0.3 baseline 回归为准（应为 PASS 且 WARN=0 才允许上线）。

**是否影响策略参数**
- **不直接影响**；但调度缺报/重复会影响样本质量与复盘可信度。

**风险/未完成项**
- 仍可能出现“计划触发但未执行/投递失败”等运行时风险，需要完善“告警→人工确认闭环”。

---

## 3) 报告守卫（auto_report_guard）与一致性治理（full_lock）

**功能模块**
- 报告结构一致性检查、满仓锁定（full_lock）硬拦截、一致性降级、错误码透出。

**文件路径**
- 报告守卫：`/Users/wxo/Desktop/Kronos/auto_report_guard_603305.py`
- 回归脚本：`/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh`

**当前状态（按你要求降级表述）**
- **“部分自愈/自动降级/人工确认闭环”**：
  - 能自动识别部分错误并降级输出（例如 REPORT_INCONSISTENT / PROVIDER_* / PARSE_*）。
  - 能在部分情形做受控重试/跳过/幂等处理。
  - 但不能表述为“系统可自动解决所有问题”；涉及数据源封禁、字段变化、环境证书等仍需要人工确认与修复闭环。
- `full_lock`：**执行一致性已治理，但收益影响仍需观察**。

**回归是否通过**
- v0.3 baseline 口径下：一致性/满仓锁定/slot coverage 等已纳入回归门禁；必须 PASS+WARN=0。

**是否影响策略参数**
- **否**（治理层的目标是“行为一致、可审计、可复现”）；但治理层会影响“是否允许执行动作/是否降级为观察”。

**风险/未完成项**
- full_lock 的“收益影响”需要连续 A/B 样本日验证后才能下结论。

---

## 4) 盘后复盘（含 sample_quality_grade 门禁）

**功能模块**
- 收盘复盘、优势监控、样本质量分级与门禁。

**文件路径**
- 复盘脚本：`/Users/wxo/Desktop/Kronos/close_review.sh`
- 样本质量：`/Users/wxo/Desktop/Kronos/.../sample_quality_grade`（以实际落地文件为准）
- 优势监控：`/Users/wxo/Desktop/Kronos/advantage_watch.py`、产物：`/Users/wxo/Desktop/Kronos/guard_outputs/advantage_alert.json`

**当前状态**
- 复盘输出必须先判断 `sample_quality_grade` 再决定“可用结论范围”。
- 明确：20260522 为 D 档事故样本，仅允许治理/局部观察，不得用于策略优劣。

**回归是否通过**
- sample_quality_grade 已接入回归门禁（v0.3 基线口径）。

**是否影响策略参数**
- **间接影响**：仅 A/B 样本的“全天绩效”结论才允许进入参数建议讨论；C/D 禁止用于参数优劣判断。

**风险/未完成项**
- 当前最大风险是“缺少足够的连续 A/B 样本日”，导致策略优劣判断仍不稳健。

---

## 5) 自愈与运维（Healthcheck / Auto-heal）

**功能模块**
- 定时健康检查、有限范围的自动修复、失败后告警与审计日志。

**文件路径**
- 安全自愈入口：`/Users/wxo/Desktop/Kronos/auto_heal_603305_safe.sh`
- 日志：`/Users/wxo/Desktop/Kronos/guard_outputs/auto_heal.log`
- 查看脚本：`/Users/wxo/Desktop/Kronos/view_heal_log.sh`

**当前状态（按你要求）**
- 表述必须为：**部分自愈 / 自动降级 / 人工确认闭环**。
- 自动修复覆盖的是“已知、可控、低风险”的问题（例如脚本依赖/权限/输出结构检查等），不覆盖数据源封禁、系统级网络问题等。

**回归是否通过**
- 自愈脚本本身属于运维层：应有自检/审计输出；如纳入回归，则以回归结果为准。

**是否影响策略参数**
- **不影响策略参数**；只影响“执行链路是否健康、是否允许继续自动运行”。

**风险/未完成项**
- 需要持续完善“告警触发→人工确认→修复→回归→再上线”的闭环 SOP；不能用“可自愈”掩盖人工介入必要性。

---

## 6) Governance 基线与禁止事项

**功能模块**
- 契约约束、治理基线、回归门禁、禁止事项清单。

**文件路径**
- 系统契约：`/Users/wxo/Desktop/Kronos/KRONOS_SYSTEM_CONTRACT.md`
- 治理基线：`/Users/wxo/Desktop/Kronos/KRONOS_GOVERNANCE_BASELINE_v0.3.md`
- 回归脚本：`/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh`

**当前状态**
- 基线有效：**KRONOS_GOVERNANCE_v0.3_WARN0**；任何改动必须先过回归门禁。
- 禁止事项（再确认）：
  - 禁止启用 v1.2-shadow
  - 禁止改主/影参数
  - 禁止 factor_observer 入交易层

**回归是否通过**
- 以每次变更后的回归结果为准；上线门禁：**FAIL=0 且 WARN=0**。

**是否影响策略参数**
- **直接约束**（冻结/禁止/门禁决定“能不能动参数”）。

**风险/未完成项**
- 当前最关键未完成项：补齐连续 A/B 档完整交易日样本，用于“收益影响/策略优劣”的可信评估。
