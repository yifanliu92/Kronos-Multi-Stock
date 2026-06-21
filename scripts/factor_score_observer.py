#!/usr/bin/env python3
"""factor_score_observer_603305 (observer-only)

Hard constraints (must hold):
- Observer-only: MUST NOT modify trading actions/position_pct.
- MUST NOT modify main/shadow strategy parameters.
- MUST NOT enable v1.2-shadow.

This script reads existing logs/quote fields (best-effort) and produces:
- guard_outputs/factor_score_observer_YYYYMMDD.json
- daily_reports/factor_score_observer_YYYYMMDD.md

Scoring range: [-100, +100]
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

BASE = Path("/Users/wxo/Desktop/Kronos")


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        return float(v)
    except Exception:
        return None


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def load_weights(p: Path, profile: str) -> dict[str, float]:
    d = json.loads(p.read_text(encoding="utf-8"))
    profiles = d.get("profiles") or {}
    w = profiles.get(profile)
    if not isinstance(w, dict):
        raise SystemExit(f"WEIGHTS_PROFILE_NOT_FOUND: {profile}")
    out: dict[str, float] = {}
    for k, v in w.items():
        fv = safe_float(v)
        if fv is None:
            raise SystemExit(f"WEIGHTS_INVALID_FLOAT: {profile}.{k}={v!r}")
        out[str(k)] = float(fv)
    return out


def weight_sum_ok(w: dict[str, float], eps: float = 1e-9) -> bool:
    s = sum(w.values())
    return abs(s - 1.0) <= eps


@dataclass
class FactorResult:
    score: float
    available_ratio: float
    missing_reason: list[str]
    group_scores: dict[str, float]
    group_details: dict[str, dict[str, Any]]


def compute_group_trend_momentum(fields: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    missing: list[str] = []

    # Inputs (best-effort):
    # - momentum_3bars / momentum_6bars (already computed by upstream if present)
    # - price_vs_open / price_vs_prev_close
    m3 = safe_float(fields.get("momentum_3bars"))
    m6 = safe_float(fields.get("momentum_6bars"))
    pvo = safe_float(fields.get("price_vs_open"))
    pvpc = safe_float(fields.get("price_vs_prev_close"))

    # Normalization: treat as pct values when present; clamp contribution.
    comps = []
    if m3 is None:
        missing.append("momentum_3bars")
    else:
        comps.append(clamp(m3 * 40.0, -100, 100))

    if m6 is None:
        missing.append("momentum_6bars")
    else:
        comps.append(clamp(m6 * 30.0, -100, 100))

    if pvo is None:
        missing.append("price_vs_open")
    else:
        comps.append(clamp(pvo * 50.0, -100, 100))

    if pvpc is None:
        missing.append("price_vs_prev_close")
    else:
        comps.append(clamp(pvpc * 50.0, -100, 100))

    if not comps:
        return 0.0, {"note": "no_inputs"}, missing

    score = sum(comps) / len(comps)
    details = {
        "momentum_3bars": m3,
        "momentum_6bars": m6,
        "price_vs_open": pvo,
        "price_vs_prev_close": pvpc,
        "norm_components": comps,
    }
    return clamp(score, -100, 100), details, missing


def compute_group_reversal_overheat(fields: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    missing: list[str] = []

    # Distances are expected in [0,1] or pct; treat closer-to-high as overheat risk.
    dfh = safe_float(fields.get("distance_from_intraday_high"))
    dfl = safe_float(fields.get("distance_from_intraday_low"))
    pull = safe_float(fields.get("short_term_pullback"))
    acc = safe_float(fields.get("last_3bar_acceleration"))

    comps = []

    if dfh is None:
        missing.append("distance_from_intraday_high")
    else:
        # if distance small => overheat risk => bearish contribution
        comps.append(clamp((0.10 - dfh) * 500.0, -100, 100))

    if dfl is None:
        missing.append("distance_from_intraday_low")
    else:
        # if distance small to low => bearish risk; if far from low => less risk
        comps.append(clamp((dfl - 0.10) * 300.0, -100, 100))

    if pull is None:
        missing.append("short_term_pullback")
    else:
        # pullback positive => bearish
        comps.append(clamp(-pull * 60.0, -100, 100))

    if acc is None:
        missing.append("last_3bar_acceleration")
    else:
        # high positive acceleration => potential overheat => bearish; negative => easing
        comps.append(clamp(-acc * 40.0, -100, 100))

    if not comps:
        return 0.0, {"note": "no_inputs"}, missing

    score = sum(comps) / len(comps)
    details = {
        "distance_from_intraday_high": dfh,
        "distance_from_intraday_low": dfl,
        "short_term_pullback": pull,
        "last_3bar_acceleration": acc,
        "norm_components": comps,
    }
    return clamp(score, -100, 100), details, missing


def compute_group_volatility_risk(fields: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    missing: list[str] = []

    v3 = safe_float(fields.get("volatility_3bars"))
    v6 = safe_float(fields.get("volatility_6bars"))
    hl = safe_float(fields.get("high_low_range_pct"))
    mdd = safe_float(fields.get("max_intraday_drawdown"))

    comps = []

    # Higher volatility => higher risk => bearish contribution
    if v3 is None:
        missing.append("volatility_3bars")
    else:
        comps.append(clamp(-v3 * 80.0, -100, 100))

    if v6 is None:
        missing.append("volatility_6bars")
    else:
        comps.append(clamp(-v6 * 60.0, -100, 100))

    if hl is None:
        missing.append("high_low_range_pct")
    else:
        comps.append(clamp(-hl * 30.0, -100, 100))

    if mdd is None:
        missing.append("max_intraday_drawdown")
    else:
        comps.append(clamp(-mdd * 50.0, -100, 100))

    if not comps:
        return 0.0, {"note": "no_inputs"}, missing

    score = sum(comps) / len(comps)
    details = {
        "volatility_3bars": v3,
        "volatility_6bars": v6,
        "high_low_range_pct": hl,
        "max_intraday_drawdown": mdd,
        "norm_components": comps,
    }
    return clamp(score, -100, 100), details, missing


def compute_group_position_risk_control(fields: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    missing: list[str] = []

    pos = safe_float(fields.get("position_pct"))
    full_lock = fields.get("full_lock")
    cooldown = fields.get("cooldown_active")
    bars_ago = safe_float(fields.get("last_action_bars_ago"))
    cost_impact = safe_float(fields.get("cost_impact"))

    comps = []

    if pos is None:
        missing.append("position_pct")
    else:
        # Higher exposure => riskier => slightly bearish
        comps.append(clamp(-(pos - 50.0) * 0.6, -100, 100))

    if full_lock is None:
        missing.append("full_lock")
    else:
        # full_lock active => restrict actions => neutral->bearish bias for "flexibility"
        comps.append(-10.0 if bool(full_lock) else 0.0)

    if cooldown is None:
        missing.append("cooldown_active")
    else:
        comps.append(-5.0 if bool(cooldown) else 0.0)

    if bars_ago is None:
        missing.append("last_action_bars_ago")
    else:
        # very recent action => risk of churn
        comps.append(-10.0 if bars_ago <= 1 else 0.0)

    if cost_impact is None:
        missing.append("cost_impact")
    else:
        # Higher cost impact => bearish
        comps.append(clamp(-abs(cost_impact) * 100.0, -100, 100))

    if not comps:
        return 0.0, {"note": "no_inputs"}, missing

    score = sum(comps) / len(comps)
    details = {
        "position_pct": pos,
        "full_lock": full_lock,
        "cooldown_active": cooldown,
        "last_action_bars_ago": bars_ago,
        "cost_impact": cost_impact,
        "norm_components": comps,
    }
    return clamp(score, -100, 100), details, missing


def compute_group_data_quality(fields: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    missing: list[str] = []

    is_td = fields.get("is_trading_day")
    provider_final = fields.get("provider_final")
    final_error_code = fields.get("final_error_code")
    model_guard_pass = fields.get("model_guard_pass")
    sample_grade = fields.get("sample_quality_grade")
    rate_limit_interrupted = fields.get("rate_limit_interrupted")

    # Score here is *not* bullish/bearish; it's confidence-like, but mapped to [-100,+100]
    # We map good quality => +50, poor => -50
    quality = 0.0
    reasons = []

    if is_td is None:
        missing.append("is_trading_day")
    else:
        quality += 10.0 if bool(is_td) else -20.0

    if provider_final is None:
        missing.append("provider_final")
        reasons.append("provider_final_missing")
    else:
        quality += 5.0

    if final_error_code is None:
        missing.append("final_error_code")
    else:
        quality += 10.0 if str(final_error_code) in ("", "OK", "0", "none", "None") else -30.0

    if model_guard_pass is None:
        missing.append("model_guard_pass")
    else:
        quality += 10.0 if bool(model_guard_pass) else -30.0

    if sample_grade is None:
        missing.append("sample_quality_grade")
    else:
        # A/B good, C/D poor
        g = str(sample_grade).upper()
        if g in ("A", "B"):
            quality += 20.0
        elif g in ("C", "D"):
            quality -= 40.0
        else:
            quality -= 10.0

    if rate_limit_interrupted is None:
        missing.append("rate_limit_interrupted")
    else:
        quality += -40.0 if bool(rate_limit_interrupted) else 5.0

    details = {
        "is_trading_day": is_td,
        "provider_final": provider_final,
        "final_error_code": final_error_code,
        "model_guard_pass": model_guard_pass,
        "sample_quality_grade": sample_grade,
        "rate_limit_interrupted": rate_limit_interrupted,
        "quality_components_note": reasons,
    }
    # center quality to [-100,100]
    return clamp(quality, -100, 100), details, missing


def factor_grade(score: float) -> str:
    if score >= 60:
        return "strong_bull"
    if score >= 20:
        return "mild_bull"
    if score <= -60:
        return "strong_bear"
    if score <= -20:
        return "mild_bear"
    return "neutral"


def factor_hint(available_ratio: float, conflict: bool) -> str:
    if available_ratio < 0.6:
        return "insufficient_data"
    return "conflict" if conflict else "confirm"


def detect_conflict_with_action(fields: dict[str, Any], score: float) -> bool:
    # Observer-only: compare with existing action text if available.
    action = (fields.get("action") or fields.get("动作") or fields.get("action_taken") or "")
    action = str(action)
    if not action:
        return False

    bullish = score >= 20
    bearish = score <= -20

    # Heuristic: if action contains keywords opposite to score.
    if bullish and any(k in action for k in ["减仓", "做空", "空", "观望"]):
        return True
    if bearish and any(k in action for k in ["加仓", "买", "做多", "多"]):
        return True
    return False


def compute_factor_score(fields: dict[str, Any], weights: dict[str, float]) -> FactorResult:
    group_scores: dict[str, float] = {}
    group_details: dict[str, dict[str, Any]] = {}
    missing_all: list[str] = []

    g1, d1, m1 = compute_group_trend_momentum(fields)
    g2, d2, m2 = compute_group_reversal_overheat(fields)
    g3, d3, m3 = compute_group_volatility_risk(fields)
    g4, d4, m4 = compute_group_position_risk_control(fields)
    g5, d5, m5 = compute_group_data_quality(fields)

    group_scores["trend_momentum"] = g1
    group_scores["reversal_overheat"] = g2
    group_scores["volatility_risk"] = g3
    group_scores["position_risk_control"] = g4
    group_scores["data_quality"] = g5

    group_details["trend_momentum"] = d1
    group_details["reversal_overheat"] = d2
    group_details["volatility_risk"] = d3
    group_details["position_risk_control"] = d4
    group_details["data_quality"] = d5

    missing_all = sorted(list(dict.fromkeys(m1 + m2 + m3 + m4 + m5)))

    # availability ratio: based on presence of required keys in spec (25 keys total)
    required = [
        # trend
        "momentum_3bars", "momentum_6bars", "price_vs_open", "price_vs_prev_close",
        # reversal
        "distance_from_intraday_high", "distance_from_intraday_low", "short_term_pullback", "last_3bar_acceleration",
        # vol
        "volatility_3bars", "volatility_6bars", "high_low_range_pct", "max_intraday_drawdown",
        # position
        "position_pct", "full_lock", "cooldown_active", "last_action_bars_ago", "cost_impact",
        # quality
        "is_trading_day", "provider_final", "final_error_code", "model_guard_pass", "sample_quality_grade", "rate_limit_interrupted",
    ]
    present = 0
    for k in required:
        if fields.get(k) is not None:
            present += 1
    available_ratio = present / len(required)

    # Weighted sum, still clamp to [-100,100]
    score = 0.0
    for k, w in weights.items():
        score += float(w) * float(group_scores.get(k, 0.0))

    score = clamp(score, -100, 100)
    return FactorResult(
        score=score,
        available_ratio=available_ratio,
        missing_reason=missing_all,
        group_scores=group_scores,
        group_details=group_details,
    )


def load_latest_jsonl(patterns: list[Path]) -> Path | None:
    files: list[Path] = []
    for p in patterns:
        files.extend(sorted(p.parent.glob(p.name)))
    files = [f for f in files if f.exists()]
    if not files:
        return None
    return max(files, key=lambda x: x.stat().st_mtime)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _light_mode(txt_in: str, weight_profile: str = 'neutral') -> str:
    """Light mode v2 (LIGHT_MODE_V2): never raises, never blocks trading. Always returns JSON.

    If inputs sufficient, compute lightweight factor_score based on price action + position risk.
    If insufficient, return factor_hint=insufficient_data and factor_missing_reason=[missing fields].
    """
    try:
        fields = json.loads(txt_in) if (txt_in or '').strip() else {}
        if not isinstance(fields, dict):
            fields = {}
    except Exception:
        fields = {}

    def _f(k):
        v = fields.get(k)
        try:
            return None if v is None else float(v)
        except Exception:
            return None

    # required minimal set
    required = ['price','prev_close','open_price','high','low','pct_change','position_pct','full_lock','action']
    missing = [k for k in required if fields.get(k) in (None,'')]

    # Base defaults
    out = {
        'factor_score': 0.0,
        'factor_grade': 'neutral',
        'factor_hint': 'insufficient_data',
        'factor_missing_reason': missing,
        'factor_conflict_with_action': False,
        'factor_weight_profile': str(weight_profile or 'neutral'),
        'observer_only': True,
        'affects_position': False,
    }

    if missing:
        return json.dumps(out, ensure_ascii=False)

    price = _f('price')
    prev_close = _f('prev_close')
    open_price = _f('open_price')
    high = _f('high')
    low = _f('low')
    pct_change = _f('pct_change')
    pos = int(float(fields.get('position_pct') or 0))
    full_lock = bool(fields.get('full_lock'))
    action = str(fields.get('action') or '')

    # lightweight components (clamped into [-100,100])
    # 1) intraday momentum proxy: pct_change (in %) scaled
    mom = max(-5.0, min(5.0, float(pct_change))) if pct_change is not None else 0.0
    mom_score = mom * 10.0  # +/-50

    # 2) range position: where price sits within [low,high]
    rng = (high - low) if (high is not None and low is not None) else 0.0
    if rng and price is not None and low is not None:
        rel = (price - low) / rng  # 0..1
        rel_score = (rel - 0.5) * 40.0  # +/-20
    else:
        rel_score = 0.0

    # 3) position risk penalty when full_lock=true (observer only)
    risk_pen = -10.0 if full_lock else 0.0

    score = mom_score + rel_score + risk_pen
    score = max(-100.0, min(100.0, score))

    # grade
    if score >= 60:
        grade_s = 'strong_bull'
    elif score >= 20:
        grade_s = 'mild_bull'
    elif score <= -60:
        grade_s = 'strong_bear'
    elif score <= -20:
        grade_s = 'mild_bear'
    else:
        grade_s = 'neutral'

    # conflict (very light): if action adds long but score negative, or adds short but score positive
    conflict = False
    if ('加仓' in action or '建多' in action) and score < -20:
        conflict = True
    if ('加空' in action or '建空' in action) and score > 20:
        conflict = True

    out.update({
        'factor_score': float(score),
        'factor_grade': grade_s,
        'factor_hint': 'confirm' if not conflict else 'conflict',
        'factor_missing_reason': [],
        'factor_conflict_with_action': bool(conflict),
    })
    return json.dumps(out, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYYMMDD (default: today)")
    ap.add_argument("--symbol", default="603305")
    ap.add_argument("--weight-profile", default="neutral", choices=["conservative", "neutral", "aggressive_observer"])
    ap.add_argument("--light-from-json", action="store_true", help="read JSON dict from stdin and print compact factor JSON")
    ap.add_argument("--light-weight-profile", default="neutral", choices=["conservative","neutral","aggressive_observer"], help="weight profile for light mode")
    ap.add_argument("--input-jsonl", default=None, help="explicit jsonl file to read (main/shadow merged)")
    args = ap.parse_args()

    if getattr(args, 'light_from_json', False):
        import sys as _sys
        txt_in = _sys.stdin.read()
        print(_light_mode(txt_in, args.light_weight_profile))
        return 0

    dt = datetime.now()
    if args.date:
        dt = datetime.strptime(args.date, "%Y%m%d")

    weights_path = BASE / "config" / "factor_weights_603305.json"
    weights = load_weights(weights_path, args.weight_profile)
    if not weight_sum_ok(weights):
        raise SystemExit("WEIGHTS_SUM_NOT_1.0")

    # Locate input
    input_path: Path | None
    if args.input_jsonl:
        input_path = Path(args.input_jsonl)
    else:
        # best-effort: look for merged logs in review bundles or guard outputs
        patterns = [
            BASE / "review_bundle_603305_*" / f"merged_{args.symbol}_*.jsonl",
            BASE / "guard_outputs" / f"merged_{args.symbol}_*.jsonl",
            BASE / "guard_outputs" / f"report_{args.symbol}_*.jsonl",
        ]
        input_path = load_latest_jsonl(patterns)

    rows: list[dict[str, Any]] = []
    if input_path and input_path.exists():
        rows = read_jsonl(input_path)

    # If no rows, still emit a governance-only report
    out_dir_json = BASE / "guard_outputs"
    out_dir_md = BASE / "daily_reports"
    out_dir_json.mkdir(parents=True, exist_ok=True)
    out_dir_md.mkdir(parents=True, exist_ok=True)

    out_json = out_dir_json / f"factor_score_observer_{yyyymmdd(dt)}.json"
    out_md = out_dir_md / f"factor_score_observer_{yyyymmdd(dt)}.md"

    results: list[dict[str, Any]] = []

    for r in rows:
        fields = dict(r)
        # hard guarantee: do not modify position/action
        before_pos = fields.get("position_pct")

        fr = compute_factor_score(fields, weights)
        conflict = detect_conflict_with_action(fields, fr.score)

        hint = factor_hint(fr.available_ratio, conflict)
        grade = factor_grade(fr.score)

        # sample quality gate
        sample_grade = (fields.get("sample_quality_grade") or "").__str__().upper()
        governance_only = sample_grade in ("C", "D")

        item = {
            "ts": fields.get("ts") or fields.get("time") or fields.get("report_time") or now_ts(),
            "symbol": args.symbol,
            "factor_score": float(fr.score),
            "factor_grade": grade,
            "factor_hint": hint,
            "factor_conflict_with_action": bool(conflict),
            "factor_available_ratio": round(float(fr.available_ratio), 4),
            "factor_missing_reason": fr.missing_reason,
            "factor_weight_profile": args.weight_profile,
            "sample_quality_grade": sample_grade or None,
            "governance_only": governance_only,
            "group_scores": fr.group_scores,
            "group_details": fr.group_details,
        }

        # enforce observer-only: ensure we did not mutate fields
        after_pos = fields.get("position_pct")
        if before_pos != after_pos:
            raise SystemExit("OBSERVER_VIOLATION_POSITION_MUTATED")

        # score bounds gate
        if not (-100.0 <= float(fr.score) <= 100.0):
            raise SystemExit("FACTOR_SCORE_OUT_OF_RANGE")

        results.append(item)

    payload = {
        "ok": True,
        "observer_only": True,
        "symbol": args.symbol,
        "date": yyyymmdd(dt),
        "generated_at": now_ts(),
        "input_path": str(input_path) if input_path else None,
        "weight_profile": args.weight_profile,
        "weights": weights,
        "notes": {
            "C_or_D_sample_quality": "governance_only (no factor efficacy judgement, no parameter suggestion, no shadow candidacy)",
            "A_or_B_sample_quality": "observe factor vs later performance allowed; still no auto parameter changes",
        },
        "items": results,
    }

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown summary
    lines = []
    lines.append(f"# factor_score_observer_603305 ({payload['date']})")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {args.symbol}")
    lines.append(f"- observer_only: true")
    lines.append(f"- input_path: {payload['input_path'] or 'N/A'}")
    lines.append(f"- weight_profile: {args.weight_profile}")
    lines.append("")

    if not results:
        lines.append("## Summary")
        lines.append("- No input rows found. This is governance-only output.")
    else:
        scores = [x["factor_score"] for x in results]
        avg = sum(scores) / len(scores)
        lines.append("## Summary")
        lines.append(f"- rows: {len(results)}")
        lines.append(f"- avg_score: {avg:.2f}")
        lines.append(f"- min_score: {min(scores):.2f}")
        lines.append(f"- max_score: {max(scores):.2f}")

        # Count grades
        cnt = {}
        for x in results:
            cnt[x["factor_grade"]] = cnt.get(x["factor_grade"], 0) + 1
        lines.append("- grade_counts:")
        for k in ["strong_bull","mild_bull","neutral","mild_bear","strong_bear"]:
            if k in cnt:
                lines.append(f"  - {k}: {cnt[k]}")

        # sample gate count
        gov_only = sum(1 for x in results if x.get("governance_only"))
        lines.append(f"- governance_only_rows (C/D): {gov_only}")

    lines.append("")
    lines.append("## Hard constraints")
    lines.append("- Observer-only: factor_score does not change actions/position_pct")
    lines.append("- C/D sample_quality_grade => governance-only (no efficacy judgement / no parameter suggestion / no shadow candidacy)")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Print outputs for worker discovery
    print(str(out_json))
    print(str(out_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# --- light mode for intraday sidecar (observer-only) ---
def _light_mode(stdin_text: str, weight_profile: str) -> str:
    import json as _json
    fields = _json.loads(stdin_text) if stdin_text.strip() else {}
    weights_path = BASE / 'config' / 'factor_weights_603305.json'
    weights = load_weights(weights_path, weight_profile)
    if not weight_sum_ok(weights):
        raise SystemExit('WEIGHTS_SUM_NOT_1.0')
    before_pos = fields.get('position_pct')
    fr = compute_factor_score(fields, weights)
    conflict = detect_conflict_with_action(fields, fr.score)
    if not (-100.0 <= float(fr.score) <= 100.0):
        raise SystemExit('FACTOR_SCORE_OUT_OF_RANGE')
    after_pos = fields.get('position_pct')
    if before_pos != after_pos:
        raise SystemExit('OBSERVER_VIOLATION_POSITION_MUTATED')
    hint = 'insufficient_data' if fr.available_ratio < 0.6 else factor_hint(fr.available_ratio, conflict)
    out = {
        'factor_score': float(fr.score),
        'factor_grade': factor_grade(fr.score),
        'factor_hint': hint,
        'factor_conflict_with_action': bool(conflict),
        'factor_weight_profile': weight_profile,
    }
    return _json.dumps(out, ensure_ascii=False)

