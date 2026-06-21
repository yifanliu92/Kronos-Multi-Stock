#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
factor_score_observer_postclose.py

Post-close factor observer summary for 603305.

Policy:
- Do not affect position.
- Do not produce parameter suggestions.
- Parse [FACTOR_OBSERVER] blocks from actual intraday reports.
- 15:00 close_snapshot is excluded because it is not a normal intraday report.
"""

from pathlib import Path
import argparse
import json
import re
import time

BASE = Path("/Users/wxo/Desktop/Kronos")
GUARD = BASE / "guard_outputs"
DAILY = BASE / "daily_reports"
DAILY.mkdir(parents=True, exist_ok=True)

INTRADAY_HHMMSS = {
    "093000", "094000", "095000",
    "100000", "101000", "102000", "103000", "104000", "105000",
    "110000", "111000", "112000", "113000",
    "130000", "131000", "132000", "133000", "134000", "135000",
    "140000", "141000", "142000", "143000", "144000", "145000",
}

def _bool(v):
    return str(v).strip().lower() == "true"

def _float_or_none(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None

def _slot_from_name(path: Path, date: str):
    m = re.match(rf"report_{date}_(\d{{6}})\.txt$", path.name)
    return m.group(1) if m else ""

def parse_factor_block(report: Path, date: str):
    slot = _slot_from_name(report, date)
    if slot not in INTRADAY_HHMMSS:
        return None

    txt = report.read_text(encoding="utf-8", errors="replace")
    if "[FACTOR_OBSERVER]" not in txt:
        return None

    block = txt.split("[FACTOR_OBSERVER]", 1)[1]
    # Stop before next section if any.
    block = block.split("\n[", 1)[0]

    kv = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        kv[k.strip()] = v.strip()

    item = {
        "slot": slot[:4],
        "slot_ts": f"{date}_{slot}",
        "report_file": str(report),
        "factor_score": _float_or_none(kv.get("factor_score")),
        "factor_grade": kv.get("factor_grade") or "neutral",
        "factor_hint": kv.get("factor_hint") or "insufficient_data",
        "factor_conflict_with_action": _bool(kv.get("factor_conflict_with_action")),
        "factor_weight_profile": kv.get("factor_weight_profile") or "",
        "observer_only": _bool(kv.get("observer_only", "true")),
        "affects_position": _bool(kv.get("affects_position", "false")),
        "source": "report_FACTOR_OBSERVER_block",
    }
    return item

def load_sample_quality_grade(date: str):
    p = GUARD / f"sample_quality_daily_{date}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("grade") or d.get("sample_quality_grade")
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--symbol", default="603305")
    ap.add_argument("--weight-profile", default="conservative")
    args = ap.parse_args()

    date = args.date
    reports = sorted(GUARD.glob(f"report_{date}_*.txt"))

    items = []
    for r in reports:
        item = parse_factor_block(r, date)
        if item:
            items.append(item)

    hint_counts = {"confirm": 0, "conflict": 0, "caution": 0, "insufficient_data": 0}
    grade_counts = {
        "strong_bull": 0,
        "mild_bull": 0,
        "neutral": 0,
        "mild_bear": 0,
        "strong_bear": 0,
    }

    for x in items:
        h = str(x.get("factor_hint") or "insufficient_data")
        if h in hint_counts:
            hint_counts[h] += 1
        else:
            hint_counts["caution"] += 1

        g = str(x.get("factor_grade") or "neutral")
        if g in grade_counts:
            grade_counts[g] += 1

    sample_quality_grade = load_sample_quality_grade(date)
    allow_factor_efficacy_judgement = sample_quality_grade in ("A", "B")

    # Even if sample quality is A/B, all insufficient_data means no efficacy judgement.
    can_judge_efficacy = (
        bool(items)
        and allow_factor_efficacy_judgement
        and hint_counts.get("insufficient_data", 0) < len(items)
    )

    daily_summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": args.symbol,
        "date": date,
        "weight_profile": args.weight_profile,
        "sample_quality_grade": sample_quality_grade,
        "allow_factor_efficacy_judgement": allow_factor_efficacy_judgement,
        "hint_counts": hint_counts,
        "grade_counts": grade_counts,
        "factor_score_forward_30m_relationship": "TODO(best-effort): compute when intraday forward return fields exist",
        "can_judge_efficacy": can_judge_efficacy,
        "items_count": len(items),
        "source_policy": "parse_FACTOR_OBSERVER_blocks_from_intraday_reports_excluding_1500_close_snapshot",
    }

    payload = {
        "ok": True,
        "observer_only": True,
        "affects_position": False,
        "symbol": args.symbol,
        "date": date,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input_path": None,
        "weight_profile": args.weight_profile,
        "items": items,
        "daily_summary": daily_summary,
        "notes": {
            "C_or_D_sample_quality": "governance_only (no factor efficacy judgement, no parameter suggestion, no shadow candidacy)",
            "A_or_B_sample_quality": "observe factor vs later performance allowed; still no auto parameter changes",
            "postclose_source": "actual report FACTOR_OBSERVER blocks",
        },
    }

    out_json = GUARD / f"factor_score_observer_{date}.json"
    out_md = DAILY / f"factor_score_observer_{date}.md"

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# factor_score_observer_603305 post-close ({date})",
        "",
        f"- sample_quality_grade: {sample_quality_grade or 'N/A'}",
        f"- allow_factor_efficacy_judgement: {allow_factor_efficacy_judgement}",
        f"- can_judge_efficacy: {can_judge_efficacy}",
        f"- items_count: {len(items)}",
        f"- source_policy: {daily_summary['source_policy']}",
        "",
        "## Hint counts",
    ]
    for k, v in hint_counts.items():
        lines.append(f"- {k}: {v}")

    lines += ["", "## Grade counts"]
    for k, v in grade_counts.items():
        lines.append(f"- {k}: {v}")

    lines += [
        "",
        "## factor_score vs forward 30m return",
        "- TODO(best-effort): compute when intraday forward return fields exist",
        "",
        "## Constraints",
        "- observer_only: true",
        "- affects_position: false",
        "- no auto parameter changes",
    ]

    if items and hint_counts.get("insufficient_data", 0) == len(items):
        lines += [
            "",
            "## Interpretation",
            "- All collected factor blocks are insufficient_data.",
            "- This means the post-close collector now works, but intraday factor inputs were still incomplete.",
            "- Do not judge factor efficacy from today's factor blocks.",
        ]

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"✅ 已生成: {out_json}")
    print(f"✅ 已生成: {out_md}")
    print(f"items_count={len(items)}")
    print(f"hint_counts={hint_counts}")
    print(f"grade_counts={grade_counts}")
    print(f"can_judge_efficacy={can_judge_efficacy}")

if __name__ == "__main__":
    main()
