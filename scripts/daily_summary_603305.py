#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
daily_summary_603305.py

Purpose:
- Generate daily_review_603305_YYYYMMDD.json after market close.
- IMPORTANT: use the last complete intraday report as PnL source.
- Do NOT use 15:00 close_snapshot report as the primary PnL source, because
  close_snapshot_603305.py has a different schema and may have empty pnl fields.
"""

from pathlib import Path
import json
import re
import time
from datetime import datetime

BASE = Path("/Users/wxo/Desktop/Kronos")
GUARD = BASE / "guard_outputs"
OUTPUT_DIR = BASE / "daily_reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INTRADAY_HHMM = {
    "093000", "094000", "095000",
    "100000", "101000", "102000", "103000", "104000", "105000",
    "110000", "111000", "112000", "113000",
    "130000", "131000", "132000", "133000", "134000", "135000",
    "140000", "141000", "142000", "143000", "144000", "145000",
}

def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")

def pick_pnl_source_report(target_date: str) -> Path | None:
    """
    Pick latest complete intraday report.
    Exclude 15:00 close_snapshot from PnL extraction.
    """
    candidates = []
    for p in sorted(GUARD.glob(f"report_{target_date}_*.txt")):
        m = re.match(rf"report_{target_date}_(\d{{6}})\.txt$", p.name)
        if not m:
            continue
        hhmmss = m.group(1)
        if hhmmss in INTRADAY_HHMM:
            candidates.append((hhmmss, p))
    if candidates:
        return sorted(candidates)[-1][1]

    # Fallback only if no intraday report exists.
    all_reports = sorted(GUARD.glob(f"report_{target_date}_*.txt"))
    return all_reports[-1] if all_reports else None

def parse_net_pct_from_report(report_file: Path):
    text = report_file.read_text(encoding="utf-8", errors="replace")

    # Expect two occurrences:
    # 1) main strategy net pnl
    # 2) shadow strategy net pnl
    matches = re.findall(r"净浮盈（含累计成本）：约\s*([+-]?\d+(?:\.\d+)?)%", text)
    main_net_pct = float(matches[0]) if len(matches) >= 1 else None
    shadow_net_pct = float(matches[1]) if len(matches) >= 2 else None

    # Main report has a cost line like: 成本明细（累计）：...合计 5827.60 元
    total_cost = 0.0
    m_cost = re.search(r"成本明细（累计）：.*?合计\s*([+-]?\d+(?:\.\d+)?)\s*元", text)
    if m_cost:
        try:
            total_cost = float(m_cost.group(1))
        except Exception:
            total_cost = 0.0

    return {
        "report_file": report_file.name,
        "main_net_pct": main_net_pct,
        "shadow_net_pct": shadow_net_pct,
        "total_cost": total_cost,
    }

def build_error_summary(target_date: str):
    reports = sorted(GUARD.glob(f"report_{target_date}_*.txt"))
    reports_with_errors = 0
    error_codes = []

    for p in reports:
        text = p.read_text(encoding="utf-8", errors="replace")
        bad = False

        # Explicit non-empty final_error_code.
        for m in re.finditer(r"final_error_code=([^\n\r]*)", text):
            code = (m.group(1) or "").strip()
            if code:
                bad = True
                error_codes.append(code)

        # Hard runtime failures.
        if "Traceback" in text or "run_status=error" in text or "report_generation_failed\": true" in text:
            bad = True

        if bad:
            reports_with_errors += 1

    return {
        "total_reports": len(reports),
        "reports_with_errors": reports_with_errors,
        "error_codes": sorted(set(error_codes)),
    }

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today_yyyymmdd(), help="YYYYMMDD, default today")
    args = ap.parse_args()

    target_date = args.date
    report = pick_pnl_source_report(target_date)

    if report is None:
        payload = {
            "date": target_date,
            "report_file": None,
            "source_policy": "latest_complete_intraday_report_excluding_1500_close_snapshot",
            "main_net_pct": None,
            "shadow_net_pct": None,
            "total_cost": 0.0,
            "advantage": None,
            "error_summary": build_error_summary(target_date),
            "error": "NO_REPORT_FOUND",
        }
    else:
        stats = parse_net_pct_from_report(report)
        main_net_pct = stats["main_net_pct"]
        shadow_net_pct = stats["shadow_net_pct"]
        advantage = (
            shadow_net_pct - main_net_pct
            if main_net_pct is not None and shadow_net_pct is not None
            else None
        )

        payload = {
            "date": target_date,
            "report_file": stats["report_file"],
            "source_policy": "latest_complete_intraday_report_excluding_1500_close_snapshot",
            "main_net_pct": main_net_pct,
            "shadow_net_pct": shadow_net_pct,
            "total_cost": stats["total_cost"],
            "advantage": advantage,
            "error_summary": build_error_summary(target_date),
        }

    output_file = OUTPUT_DIR / f"daily_review_603305_{target_date}.json"
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 已生成: {output_file}")
    print(f"source_report: {payload.get('report_file')}")
    print(f"主策略净浮盈: {payload.get('main_net_pct')}%")
    print(f"影子策略净浮盈: {payload.get('shadow_net_pct')}%")
    print(f"优势差值 shadow-main: {payload.get('advantage')}%")

if __name__ == "__main__":
    main()
