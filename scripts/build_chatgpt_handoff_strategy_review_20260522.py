#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import datetime as dt


def main():
    base = Path('/Users/wxo/Desktop/Kronos')
    outdir = base / 'chatgpt_handoff'
    outdir.mkdir(parents=True, exist_ok=True)

    ms_path = base / 'daily_reports' / 'main_shadow_review_20260522.md'
    pp_path = base / 'daily_reports' / 'strategy_param_proposal_20260522.md'

    ms = ms_path.read_text(encoding='utf-8') if ms_path.exists() else '(missing main_shadow_review_20260522.md)'
    pp = pp_path.read_text(encoding='utf-8') if pp_path.exists() else '(missing strategy_param_proposal_20260522.md)'

    now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    body = f"""# ChatGPT Review Request (603305) — 20260522

- generated_at: {now}
- baseline: KRONOS_GOVERNANCE_v0.3_WARN0

## 当前禁止事项（必须遵守）
- 不启用 v1.2-shadow
- 不改主/影参数
- 不让 factor_observer 入交易层
- 不自动连跑 A/B/C/D

## 主影复盘核心结论（来自 main_shadow_review_20260522）
- 主策略 records=16
- 影子 records=15
- failed=0
- REPORT_INCONSISTENT=0
- full_lock_count=7
- 主/影 close_net_pnl_pct 均为 -2.26%
- support_parallel_observe=True

## 参数建议三档摘要（来自 strategy_param_proposal_20260522）
- 保守版：提高阈值、提高回撤触发门槛、冷静期20min、保持满仓锁定、14:40后不再开新仓
- 中性版（候选）：bull+0.9/bear-1.2、分级止盈+一次小幅回补、冷静期10min、14:50后禁止加仓/加空
- 激进版（仅观察）：更低阈值、加快加仓/回补、冷静期0（风险大）

## 需要 ChatGPT 评审的问题
1) 是否同意继续并行观察？
2) 是否同意中性版作为 v1.2-shadow 候选？（注意：当前仍禁止启用）
3) 是否应该先运行保守版 shadow（仅观察）？
4) full_lock_count=7 对参数设计有什么影响？
5) 当前是否允许改参数？

## 希望 ChatGPT 输出（固定格式）
- 是否通过（通过/不通过/仅观察）
- 风险点（最多5条）
- 下一步最小动作（最多3条，必须可落地可验证）
- 可直接发给 OpenClaw 的指令（不包含改参数/启用v1.2-shadow）

---

# 附件 1：main_shadow_review_20260522.md

{ms}

---

# 附件 2：strategy_param_proposal_20260522.md

{pp}
"""

    p1 = outdir / 'review_request_20260522_strategy.md'
    p2 = outdir / 'latest_review_request.md'
    p1.write_text(body, encoding='utf-8')
    p2.write_text(body, encoding='utf-8')

    print(str(p2))
    print(str(p1))


if __name__ == '__main__':
    main()
