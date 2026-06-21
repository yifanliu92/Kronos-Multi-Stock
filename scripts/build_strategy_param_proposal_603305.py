#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_strategy_param_proposal_603305.py

Post-close strategy parameter proposal generator.

Hard rule:
- This script only generates proposal files.
- It must never modify live rules or parameters.
- If MTM / effective value series / main-shadow evaluation are not valid,
  parameter_switch_allowed and shadow_enable_allowed must stay false.
"""

from pathlib import Path
import json
import sys
import time

BASE = Path("/Users/wxo/Desktop/Kronos")
GUARD = BASE / "guard_outputs"
DAILY = BASE / "daily_reports"
DAILY.mkdir(parents=True, exist_ok=True)

def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _latest_eval_invalid(date: str) -> bool:
    files = sorted(DAILY.glob(f"main_shadow_eval_plain_{date}_*.json"))
    if not files:
        return True
    d = _load_json(files[-1]) or {}
    main_status = ((d.get("main") or {}).get("metric_status") or "").upper()
    shadow_status = ((d.get("shadow") or {}).get("metric_status") or "").upper()
    return main_status == "INVALID" or shadow_status == "INVALID"

def _factor_all_insufficient(date: str) -> bool:
    d = _load_json(GUARD / f"factor_score_observer_{date}.json") or {}
    ds = d.get("daily_summary") or {}
    hc = ds.get("hint_counts") or {}
    items_count = ds.get("items_count")
    try:
        items_count = int(items_count)
    except Exception:
        items_count = len(d.get("items") or [])
    return items_count > 0 and int(hc.get("insufficient_data") or 0) == items_count

def _sample_quality_ok(date: str) -> bool:
    d = _load_json(GUARD / f"sample_quality_daily_{date}.json") or {}

    def _int(v, default=0):
        try:
            if isinstance(v, list):
                return len(v)
            if isinstance(v, bool):
                return int(v)
            return int(v)
        except Exception:
            return default

    status_ok = str(d.get("status") or d.get("sample_status") or "").upper() == "OK"
    grade_ok = str(d.get("grade") or "").upper() == "A"

    expected = _int(d.get("expected_slots"), 0)
    actual = _int(d.get("actual_reports"), -1)
    missing = _int(d.get("missing_slots"), 0)
    timeout_or_error = _int(d.get("timeout_or_error_slots"), 0)

    full_day = d.get("is_full_trading_day_sample")
    if isinstance(full_day, str):
        full_day_ok = full_day.strip().lower() == "true"
    else:
        full_day_ok = bool(full_day)

    return (
        status_ok
        and grade_ok
        and expected > 0
        and expected == actual
        and missing == 0
        and timeout_or_error == 0
        and full_day_ok
    )

def build_safety_gate(date: str):
    sample_ok = _sample_quality_ok(date)
    eval_invalid = _latest_eval_invalid(date)
    factor_insufficient = _factor_all_insufficient(date)

    # Current governance policy:
    # Even if sample quality is A, strategy switching is blocked until MTM/effective value series are valid.
    parameter_switch_allowed = False
    shadow_enable_allowed = False
    performance_use_allowed = False

    reasons = []
    if sample_ok:
        reasons.append("sample_quality is OK/A, but this only proves full-day sample completeness")
    else:
        reasons.append("sample_quality is not confirmed OK/A")

    reasons.extend([
        "MTM avg_entry_price is not fixed",
        "effective value series is missing",
    ])

    if eval_invalid:
        reasons.append("main_shadow_eval metric_status is INVALID")
    if factor_insufficient:
        reasons.append("factor observer blocks are all insufficient_data")

    reasons.append("therefore no parameter switch or v1.2-shadow enablement is allowed today")

    return {
        "parameter_switch_allowed": parameter_switch_allowed,
        "shadow_enable_allowed": shadow_enable_allowed,
        "performance_use_allowed": performance_use_allowed,
        "proposal_only": True,
        "sample_quality_ok": sample_ok,
        "main_shadow_eval_invalid": eval_invalid,
        "factor_all_insufficient_data": factor_insufficient,
        "reason": reasons,
        "allowed_action": [
            "keep proposals for human review",
            "use Neutral only as a future candidate after MTM/value-series repair",
            "do not modify live rules",
            "do not enable v1.2-shadow from this proposal",
        ],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_by": "build_strategy_param_proposal_603305.py",
    }

def main():
    date = sys.argv[1] if len(sys.argv) >= 2 else time.strftime("%Y%m%d")

    payload = {
        "date": date,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "goal": "auditability/comparability first; no parameter change applied",
        "conservative": {
            "target": "降低波动，减少误触发",
            "fit_for": "链路刚稳定，优先保守观察",
            "params": {
                "bull_add_threshold_pct": 1.2,
                "bear_add_threshold_pct": -1.8,
                "take_profit_levels": "更少层级/更高门槛（减少频繁减仓）",
                "drawdown_triggers": "提高回撤阈值，避免轻微回撤触发大减仓",
                "full_position_lock": "保持启用",
                "cooldown_minutes": 20,
                "eod_restriction": "14:40后不再开新仓（仅止盈/减仓）",
            },
            "risk": "可能错过趋势早期；收益提升不明显",
        },
        "neutral": {
            "target": "兼顾收益和波动（作为 v1.2-shadow 候选）",
            "fit_for": "链路稳定后，用于影子策略验证",
            "params": {
                "bull_add_threshold_pct": 0.9,
                "bear_add_threshold_pct": -1.2,
                "take_profit_levels": "分级止盈（小步减仓）",
                "strong_rebuy": "止盈释放资金后，允许一次小幅回补（受冷静期限制）",
                "cooldown_minutes": 10,
                "eod_restriction": "14:50后禁止加仓/加空，仅允许风控减仓",
            },
            "risk": "需要更严格的一致性校验，避免动作/理由/仓位不一致",
        },
        "aggressive": {
            "target": "增强趋势收益（仅观察，不执行）",
            "fit_for": "研究趋势行情下的收益上限",
            "params": {
                "bull_add_threshold_pct": 0.6,
                "bear_add_threshold_pct": -0.9,
                "faster_add": "更快加仓/加空，允许更高仓位弹性",
                "replenish": "更频繁回补（仍需资金来源约束）",
                "cooldown_minutes": 0,
            },
            "risk": "交易频率上升，成本与回撤风险大；不适合刚稳定阶段",
        },
    }

    payload["safety_gate"] = build_safety_gate(date)

    out_json = GUARD / f"strategy_param_proposal_{date}.json"
    out_md = DAILY / f"strategy_param_proposal_{date}.md"

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# strategy_param_proposal {date}",
        f"- generated_at: {payload['generated_at']}",
        "- note: proposal-only (no rules changed)",
        "",
        "## Conservative",
        json.dumps(payload["conservative"], ensure_ascii=False, indent=2),
        "",
        "## Neutral",
        json.dumps(payload["neutral"], ensure_ascii=False, indent=2),
        "",
        "## Aggressive",
        json.dumps(payload["aggressive"], ensure_ascii=False, indent=2),
        "",
        "## Safety Gate",
        f"- parameter_switch_allowed: {str(payload['safety_gate']['parameter_switch_allowed']).lower()}",
        f"- shadow_enable_allowed: {str(payload['safety_gate']['shadow_enable_allowed']).lower()}",
        f"- performance_use_allowed: {str(payload['safety_gate']['performance_use_allowed']).lower()}",
        f"- proposal_only: {str(payload['safety_gate']['proposal_only']).lower()}",
        "",
        "### Reason",
    ]

    for i, r in enumerate(payload["safety_gate"]["reason"], 1):
        lines.append(f"{i}. {r}")

    lines += [
        "",
        "### Allowed Action",
    ]
    for a in payload["safety_gate"]["allowed_action"]:
        lines.append(f"- {a}")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"✅ 已生成: {out_json}")
    print(f"✅ 已生成: {out_md}")
    print(f"parameter_switch_allowed={payload['safety_gate']['parameter_switch_allowed']}")
    print(f"shadow_enable_allowed={payload['safety_gate']['shadow_enable_allowed']}")
    print(f"performance_use_allowed={payload['safety_gate']['performance_use_allowed']}")

if __name__ == "__main__":
    main()
