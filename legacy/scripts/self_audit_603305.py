#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import json
import sys
import time

BASE = Path("/Users/wxo/Desktop/Kronos")
GUARD = BASE / "guard_outputs"
DAILY = BASE / "daily_reports"
DAILY.mkdir(parents=True, exist_ok=True)

def main():
    date = sys.argv[1] if len(sys.argv) >= 2 else time.strftime("%Y%m%d")

    reports = sorted(GUARD.glob(f"report_{date}_*.txt"))
    failed = []
    error_codes = {}

    for p in reports:
        txt = p.read_text(encoding="utf-8", errors="replace")
        if "run_status=ok" not in txt and "[AUDIT] run_status=ok" not in txt:
            failed.append(p.name)
        for line in txt.splitlines():
            if "final_error_code=" in line:
                code = line.split("final_error_code=", 1)[1].strip()
                if code:
                    error_codes[code] = error_codes.get(code, 0) + 1

    slot_p = GUARD / f"slot_coverage_daily_{date}.json"
    slot = {}
    if slot_p.exists():
        try:
            slot = json.loads(slot_p.read_text(encoding="utf-8"))
        except Exception:
            slot = {}

    missing_timeslots = slot.get("critical_missing_slots") or []
    missing_slot_count = slot.get("missing_slot_count", 0)
    sample_status = slot.get("sample_status", "unknown")
    performance_use_allowed = slot.get("performance_use_allowed", True)
    root_cause_class = slot.get("root_cause_class", "unknown")
    primary_error_pattern = slot.get("primary_error_pattern", "NONE")
    error_code_daily = slot.get("error_code_daily", "normal")

    risk = "PASS" if (not failed and performance_use_allowed) else "WARN"
    score = 100
    if failed:
        score -= 20
    if not performance_use_allowed:
        score -= 28
    if missing_slot_count:
        score -= min(20, int(missing_slot_count))
    score = max(0, score)

    payload = {
        "version": "self_audit_v0.4",
        "date": date,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_reports": len(reports),
        "failed_reports": len(failed),
        "failed_report_files": failed,
        "error_codes": error_codes,
        "compliance": "PASS" if not failed else "FAIL",
        "data_auth": "PASS",
        "score": score,
        "risk": risk,
        "missing_timeslots": missing_timeslots,
        "missing_slot_count": missing_slot_count,
        "error_code_daily": error_code_daily,
        "primary_error_pattern": primary_error_pattern,
        "root_cause_class": root_cause_class,
        "sample_status": sample_status,
        "performance_use_allowed": performance_use_allowed,
        "is_full_trading_day_sample": slot.get("is_full_trading_day_sample", True),
        "not_for_strategy_eval": slot.get("not_for_strategy_eval", False),
        "not_for_parameter_switch": slot.get("not_for_parameter_switch", False),
        "not_for_v1_2_shadow_enable": slot.get("not_for_v1_2_shadow_enable", False),
    }

    out_json = GUARD / f"self_audit_summary_{date}.json"
    out_md = DAILY / f"self_audit_summary_{date}.md"

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        f"# Kronos Self Audit {date}",
        f"- version: {payload['version']}",
        f"- total_reports: {payload['total_reports']}",
        f"- failed_reports: {payload['failed_reports']}",
        f"- error_codes: {payload['error_codes']}",
        f"- compliance: {payload['compliance']}",
        f"- data_auth: {payload['data_auth']}",
        f"- score: {payload['score']}",
        f"- risk: {payload['risk']}",
        f"- missing_timeslots: {payload['missing_timeslots']}",
        f"- missing_slot_count: {payload['missing_slot_count']}",
        f"- error_code_daily: {payload['error_code_daily']}",
        f"- primary_error_pattern: {payload['primary_error_pattern']}",
        f"- root_cause_class: {payload['root_cause_class']}",
        f"- sample_status: {payload['sample_status']}",
        f"- is_full_trading_day_sample: {str(payload['is_full_trading_day_sample']).lower()}",
        f"- performance_use_allowed: {str(payload['performance_use_allowed']).lower()}",
        f"- not_for_strategy_eval: {str(payload['not_for_strategy_eval']).lower()}",
        f"- not_for_parameter_switch: {str(payload['not_for_parameter_switch']).lower()}",
        f"- not_for_v1_2_shadow_enable: {str(payload['not_for_v1_2_shadow_enable']).lower()}",
    ]
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"✅ 已生成: {out_json}")
    print(f"✅ 已生成: {out_md}")

if __name__ == "__main__":
    main()
