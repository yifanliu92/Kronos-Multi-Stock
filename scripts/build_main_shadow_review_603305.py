#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_main_shadow_review_603305.py

Build post-close main/shadow review.

Important policy:
- 15:00 report is close_snapshot, not a normal intraday strategy report.
- Main pnl = first "净浮盈（含累计成本）" occurrence in each complete intraday report.
- Shadow pnl = second "净浮盈（含累计成本）" occurrence in each complete intraday report.
- If MTM is INVALID, keep support_parallel_observe=true but do not use this as a strategy switch basis.
"""

from pathlib import Path
from collections import Counter
import json
import re
import sys
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

def _extract_slot(path: Path, date: str):
    m = re.match(rf"report_{date}_(\d{{6}})\.txt$", path.name)
    return m.group(1) if m else ""

def _parse_report(path: Path, date: str):
    txt = path.read_text(encoding="utf-8", errors="replace")
    slot = _extract_slot(path, date)
    is_intraday = slot in INTRADAY_HHMMSS

    pnl_matches = re.findall(r"净浮盈（含累计成本）：约\s*([+-]?\d+(?:\.\d+)?)%", txt)
    main_pnl = float(pnl_matches[0]) if len(pnl_matches) >= 1 and is_intraday else None
    shadow_pnl = float(pnl_matches[1]) if len(pnl_matches) >= 2 and is_intraday else None

    action = ""
    m_action = re.search(r"动作：([^\n\r]+)", txt)
    if m_action:
        action = m_action.group(1).strip()

    full_lock = None
    m_lock = re.search(r"满仓锁定:\s*(true|false)", txt, flags=re.I)
    if m_lock:
        full_lock = m_lock.group(1).lower() == "true"

    mtm_status = ""
    m_mtm = re.search(r"mtm_metric_status:\s*([A-Z_]+)", txt)
    if m_mtm:
        mtm_status = m_mtm.group(1).strip()

    return {
        "slot": slot,
        "slot_type": "intraday" if is_intraday else "close_snapshot_or_other",
        "report_file": str(path),
        "success": "run_status=ok" in txt or path.exists(),
        "report_inconsistent": "REPORT_INCONSISTENT" in txt,
        "action": action,
        "full_lock": full_lock,
        "main_net_pnl_pct": main_pnl,
        "shadow_net_pnl_pct": shadow_pnl,
        "mtm_metric_status": mtm_status,
        "has_main_pnl": main_pnl is not None,
        "has_shadow_pnl": shadow_pnl is not None,
    }

def _side_summary(rows, side: str):
    key = "main_net_pnl_pct" if side == "main" else "shadow_net_pnl_pct"
    vals = [r[key] for r in rows if r.get("slot_type") == "intraday" and r.get(key) is not None]
    close = vals[-1] if vals else None

    return {
        "records": len(rows),
        "success": sum(1 for r in rows if r.get("success")),
        "failed": sum(1 for r in rows if not r.get("success")),
        "close_net_pnl_pct": close,
        "max_net_pnl_pct": max(vals) if vals else None,
        "min_net_pnl_pct": min(vals) if vals else None,
        "pnl_records": len(vals),
        "full_lock_count": sum(1 for r in rows if r.get("full_lock") is True),
        "report_inconsistent_count": sum(1 for r in rows if r.get("report_inconsistent")),
        "action_dist": dict(Counter(r.get("action", "") for r in rows)),
        "pnl_source_policy": "first_pnl_for_main_second_pnl_for_shadow_excluding_1500_close_snapshot",
    }

def main():
    date = sys.argv[1] if len(sys.argv) >= 2 else time.strftime("%Y%m%d")

    report_files = sorted(GUARD.glob(f"report_{date}_*.txt"))
    rows = [_parse_report(p, date) for p in report_files]

    main_sum = _side_summary(rows, "main")
    shadow_sum = _side_summary(rows, "shadow")

    aligned_records = len(rows)
    compare = {
        "aligned_records": aligned_records,
        "main_close_net_pnl_pct": main_sum["close_net_pnl_pct"],
        "shadow_close_net_pnl_pct": shadow_sum["close_net_pnl_pct"],
        "advantage_shadow_minus_main": (
            shadow_sum["close_net_pnl_pct"] - main_sum["close_net_pnl_pct"]
            if main_sum["close_net_pnl_pct"] is not None and shadow_sum["close_net_pnl_pct"] is not None
            else None
        ),
        "support_parallel_observe": True,
        "performance_use_allowed": False,
        "performance_use_block_reason": "MTM avg_entry_price/effective value series not fixed yet; text pnl is review-only, not strategy-switch basis.",
    }

    payload = {
        "date": date,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "main": main_sum,
        "shadow": shadow_sum,
        "compare": compare,
        "rows": rows,
    }

    out_json = GUARD / f"main_shadow_review_{date}.json"
    out_md = DAILY / f"main_shadow_review_{date}.md"

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        f"# main_shadow_review {date}",
        f"- generated_at: {payload['generated_at']}",
        "",
        "## Main",
        f"- records: {main_sum['records']} | success: {main_sum['success']} | failed: {main_sum['failed']}",
        f"- close_net_pnl_pct: {main_sum['close_net_pnl_pct']} (max: {main_sum['max_net_pnl_pct']}, min: {main_sum['min_net_pnl_pct']})",
        f"- pnl_records: {main_sum['pnl_records']}",
        f"- full_lock_count: {main_sum['full_lock_count']} | REPORT_INCONSISTENT: {main_sum['report_inconsistent_count']}",
        f"- action_dist: {main_sum['action_dist']}",
        "",
        "## Shadow",
        f"- records: {shadow_sum['records']} | success: {shadow_sum['success']} | failed: {shadow_sum['failed']}",
        f"- close_net_pnl_pct: {shadow_sum['close_net_pnl_pct']} (max: {shadow_sum['max_net_pnl_pct']}, min: {shadow_sum['min_net_pnl_pct']})",
        f"- pnl_records: {shadow_sum['pnl_records']}",
        f"- full_lock_count: {shadow_sum['full_lock_count']} | REPORT_INCONSISTENT: {shadow_sum['report_inconsistent_count']}",
        f"- action_dist: {shadow_sum['action_dist']}",
        "",
        "## Compare",
        f"- aligned_records: {compare['aligned_records']}",
        f"- main_close_net_pnl_pct: {compare['main_close_net_pnl_pct']} | shadow_close_net_pnl_pct: {compare['shadow_close_net_pnl_pct']}",
        f"- advantage_shadow_minus_main: {compare['advantage_shadow_minus_main']}",
        f"- support_parallel_observe: {compare['support_parallel_observe']}",
        f"- performance_use_allowed: {compare['performance_use_allowed']}",
        f"- performance_use_block_reason: {compare['performance_use_block_reason']}",
        "",
        "## Note",
        "- This review separates main and shadow pnl by the first/second 净浮盈 occurrence in complete intraday reports.",
        "- 15:00 close_snapshot is excluded from pnl extraction.",
        "- Until MTM avg_entry_price and effective value series are fixed, this is review-only and not a strategy-switch basis.",
    ]
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"✅ 已生成: {out_json}")
    print(f"✅ 已生成: {out_md}")
    print(f"main_close_net_pnl_pct={compare['main_close_net_pnl_pct']}")
    print(f"shadow_close_net_pnl_pct={compare['shadow_close_net_pnl_pct']}")
    print(f"advantage_shadow_minus_main={compare['advantage_shadow_minus_main']}")
    print(f"performance_use_allowed={compare['performance_use_allowed']}")

if __name__ == "__main__":
    main()
