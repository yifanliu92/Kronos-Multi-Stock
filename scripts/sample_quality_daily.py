#!/usr/bin/env python3
"""sample_quality_daily.py (minimal real implementation)

Goal (P1):
- Minimal sample-quality scoring is implemented; no implementation-missing sentinel.
- Compute minimal, honest sample quality using only local artifacts.

Inputs (read-only):
- guard_outputs/report_YYYYMMDD_HHMMSS.txt (primary)
- guard_outputs/expected_slots_YYYYMMDD.json (if present)

Outputs:
- guard_outputs/sample_quality_daily_YYYYMMDD.json
- Prints a one-line status summary and the output path.

Never fabricate PASS when data is incomplete.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai


@dataclass
class Result:
    date: str
    generated_at: str
    expected_slots: int
    actual_reports: int
    missing_slots: int
    timeout_or_error_slots: int
    manual_triggered: int
    auto_cron_generated: int
    sample_status: str
    is_full_trading_day_sample: bool
    grade: str
    notes: list[str]


def _read_expected_slots(d: str) -> Optional[list[str]]:
    fp = GUARD / f'expected_slots_{d}.json'
    if not fp.exists():
        return None
    try:
        obj = json.loads(fp.read_text(encoding='utf-8'))
        # Accept both {slots:[...]} and plain list
        if isinstance(obj, dict) and 'slots' in obj and isinstance(obj['slots'], list):
            return [str(x) for x in obj['slots']]
        if isinstance(obj, list):
            return [str(x) for x in obj]
    except Exception:
        return None
    return None




def _read_expected_slots_contract() -> dict:
    """Read expected slots contract/schedule for 603305.

    Requirements:
    - MUST NOT infer expected slots from existing reports.
    - MUST include full intraday 10-min slots + mandatory 15:00 close snapshot.
    - If mandatory_close_snapshot missing in contract -> config error.

    Schedule (contract/schedule v1 for 603305):
      09:30, 09:40, 09:50
      10:00-10:50 every 10m
      11:00-11:30 every 10m
      13:00-13:50 every 10m
      14:00-14:50 every 10m
      15:00 close snapshot
    Total expected slots: 26
    """
    fp = BASE / 'config' / 'expected_slots_contract_603305.json'
    if not fp.exists():
        return {'ok': False, 'error_code': 'EXPECTED_SLOTS_CONTRACT_MISSING', 'slots': [], 'notes': ['expected_slots_source=contract_missing']}
    try:
        obj = json.loads(fp.read_text(encoding='utf-8'))
    except Exception:
        return {'ok': False, 'error_code': 'EXPECTED_SLOTS_CONTRACT_INVALID_JSON', 'slots': [], 'notes': ['expected_slots_source=contract_invalid_json']}

    mandatory = (((obj or {}).get('rules') or {}).get('mandatory_close_snapshot') or {})
    slot_close = mandatory.get('slot')
    if not slot_close:
        return {'ok': False, 'error_code': 'EXPECTED_SLOTS_CONTRACT_MISSING_MANDATORY_CLOSE_SNAPSHOT', 'slots': [], 'notes': ['expected_slots_source=contract_config_error']}

    slots = []
    slots += ['09:30', '09:40', '09:50']
    slots += [f"10:{m:02d}" for m in (0,10,20,30,40,50)]
    slots += [f"11:{m:02d}" for m in (0,10,20,30)]
    slots += [f"13:{m:02d}" for m in (0,10,20,30,40,50)]
    slots += [f"14:{m:02d}" for m in (0,10,20,30,40,50)]
    slots += [str(slot_close)]

    # de-dup while preserving order
    seen=set(); uniq=[]
    for x in slots:
        if x not in seen:
            uniq.append(x); seen.add(x)

    return {
        'ok': True,
        'error_code': '',
        'slots': uniq,
        'notes': ['expected_slots_source=contract/schedule'],
    }

def _scan_reports(d: str) -> list[Path]:
    return sorted(GUARD.glob(f'report_{d}_*.txt'))


def _extract_report_time(fp: Path) -> Optional[str]:
    # report_YYYYMMDD_HHMMSS.txt
    m = re.search(r'report_(\d{8})_(\d{6})\.txt$', fp.name)
    if not m:
        return None
    return f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:6]}"


def _slot_key_from_time(hhmmss: str) -> str:
    # Slot by 10-minute bucket: HH:MM (floor)
    hh, mm, ss = hhmmss.split(':')
    m10 = (int(mm) // 10) * 10
    return f"{hh}:{m10:02d}"


def _infer_expected_from_reports(reports: list[Path]) -> list[str]:
    slots=set()
    for fp in reports:
        rt = _extract_report_time(fp)
        if not rt:
            continue
        _, t = rt.split(' ')
        slots.add(_slot_key_from_time(t))
    return sorted(slots)


def _detect_manual(fp: Path) -> bool:
    # Heuristic: if report includes explicit manual markers
    try:
        txt = fp.read_text(errors='ignore')
    except Exception:
        return False
    markers = ['manual', '手动', 'MANUAL_TRIGGER']
    return any(m in txt for m in markers)


def _detect_timeout_or_error_slot(fp: Path) -> tuple[bool, str, str]:
    """Detect real timeout/error from report content.

    Rules:
    - Empty final_error_code= must NOT count as error.
    - run_status=ok must NOT count as error.
    - deliveryStatus=unknown / delivered=unknown / missing audit fields must NOT count as error.
    - Only count as error when:
        * 'Request timed out' present, OR
        * run_status=error, OR
        * error_code is present and non-empty, OR
        * explicit price invalid markers (e.g., EM_PRICE_ZERO/price=0) appear.

    Returns: (is_error, matched_error_pattern, matched_line)
    """
    try:
        txt = fp.read_text(errors='ignore').splitlines()
    except Exception:
        return False, '', ''

    for line in txt:
        l=line.strip()
        if 'Request timed out' in l:
            return True, 'Request timed out', line
        if 'run_status=error' in l:
            return True, 'run_status=error', line
        # error_code must be non-empty; reject placeholders like "error_code="
        m=re.search(r'error_code=([^\s]+)', l)
        if m:
            code=m.group(1).strip()
            if code and code not in ('', '""'):
                # ignore empty-like
                return True, 'error_code_nonempty', line
        # explicit market/price invalid
        if any(x in l for x in ['EM_PRICE_ZERO','price_invalid','PRICE_INVALID','行情缺失','MISSING_QUOTE']):
            return True, 'price_invalid_marker', line

    # If report explicitly says ok, consider it non-error
    for line in txt:
        if 'run_status=ok' in line:
            return False, '', ''

    return False, '', ''

def _grade(expected: int, missing: int, timeout_err: int, full_day: bool) -> str:
    """
    Grade D = 缺失>0，不管缺几个。
    只要有一天中任何一个时点缺失，当天就不算有效样本日。
    保留 full_day 概念仅供内部诊断，不参与评级门槛。
    """
    if expected <= 0:
        return 'D'
    if missing > 0:
        return 'D'
    # 走到这里说明 missing == 0
    if timeout_err == 0:
        return 'A'
    if timeout_err <= 1:
        return 'B'
    if timeout_err <= 2:
        return 'C'
    return 'D'


def main() -> int:
    if len(sys.argv) < 2:
        print('status=FAIL error_code=ARGS_REQUIRED usage: sample_quality_daily.py YYYYMMDD')
        return 2

    d = sys.argv[1]
    GUARD.mkdir(parents=True, exist_ok=True)

    reports = _scan_reports(d)
    expected_slots = _read_expected_slots(d)
    notes=[]

    # Expected slots MUST come from contract/schedule (or a generated expected_slots_YYYYMMDD.json), never inferred from reports.
    contract_info = _read_expected_slots_contract()
    if expected_slots is None:
        expected_slots = contract_info.get('slots') or []
        notes.extend(contract_info.get('notes') or [])
        if not contract_info.get('ok'):
            notes.append(f"config_error={contract_info.get('error_code')}")
    else:
        # expected_slots_YYYYMMDD.json is allowed, but still must comply with contract requirements
        notes.append('expected_slots_source=expected_slots_json(contract/schedule)')
        # enforce mandatory 15:00 slot from contract if available
        if contract_info.get('ok') and contract_info.get('slots'):
            for slot in contract_info['slots']:
                if slot not in expected_slots:
                    expected_slots.append(slot)

    expected_n = len(expected_slots)

    # actual slots based on distinct 10-min buckets
    actual_slots=set()
    manual=0
    timeout_err=0
    slot_details = []
    auto=0

    for fp in reports:
        rt = _extract_report_time(fp)
        if not rt:
            continue
        _, t = rt.split(' ')
        actual_slots.add(_slot_key_from_time(t))
        if _detect_manual(fp):
            manual += 1
        else:
            auto += 1
        is_err, pat, matched = _detect_timeout_or_error_slot(fp)
        if is_err:
            timeout_err += 1
        # collect per-slot evidence
        slot_details.append({'slot': _slot_key_from_time(t), 'report_file': str(fp), 'is_error': bool(is_err), 'matched_error_pattern': pat, 'matched_line': matched})

    actual_n = len(actual_slots)
    missing = max(expected_n - actual_n, 0)

    # Mandatory 15:00 close snapshot check (contract-driven)
    close_fp = GUARD / f'report_{d}_150000.txt'
    if not close_fp.exists():
        notes.append('error_code=MISSING_CLOSE_SNAPSHOT_1500')
        # Treat as missing expected slot, and force not-full-day
        if '15:00' not in actual_slots:
            missing = max(missing, 1)


    # Full trading day sample requires: expected_slots known from calendar/expected file AND no missing
    is_full = (('expected_slots_source=contract/schedule' in notes) or ('expected_slots_source=expected_slots_json(contract/schedule)' in notes) or ('expected_slots_source=expected_slots_json(contract/schedule)' in notes)) and (missing == 0) and ('error_code=MISSING_CLOSE_SNAPSHOT_1500' not in notes)

    sample_status = 'OK'
    if expected_n == 0:
        sample_status = 'WARN'
        notes.append('no_expected_slots_detected')
    elif missing > 0 or timeout_err > 0:
        sample_status = 'WARN'

    grade = _grade(expected_n, missing, timeout_err, is_full)

    out = GUARD / f'sample_quality_daily_{d}.json'
    payload = Result(
        date=d,
        generated_at=datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S'),
        expected_slots=expected_n,
        actual_reports=actual_n,
        missing_slots=missing,
        timeout_or_error_slots=timeout_err,
        manual_triggered=manual,
        auto_cron_generated=auto,
        sample_status=sample_status,
        is_full_trading_day_sample=is_full,
        grade=grade,
        notes=notes,
    )

    out.write_text(json.dumps(payload.__dict__, ensure_ascii=False, indent=2), encoding='utf-8')

    # Write per-slot error reasoning markdown
    md_fp = BASE / 'daily_reports' / f'sample_quality_error_reason_{d}.md'
    md_fp.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# sample_quality error reasoning {d}", "", f"expected_slots={expected_n} actual_reports={actual_n} missing_slots={missing} timeout_or_error_slots={timeout_err}", ""]
    lines.append("| slot | report_file | is_error | matched_error_pattern | matched_line |")
    lines.append("|---|---|---:|---|---|")
    for it in slot_details:
        lines.append(f"| {it.get(chr(39)+chr(115)+chr(108)+chr(111)+chr(116))} | {it.get(chr(39)+chr(114)+chr(101)+chr(112)+chr(111)+chr(114)+chr(116)+chr(95)+chr(102)+chr(105)+chr(108)+chr(101))} | {str(it.get(chr(39)+chr(105)+chr(115)+chr(95)+chr(101)+chr(114)+chr(114)+chr(111)+chr(114))).lower()} | {it.get(chr(39)+chr(109)+chr(97)+chr(116)+chr(99)+chr(104)+chr(101)+chr(100)+chr(95)+chr(101)+chr(114)+chr(114)+chr(111)+chr(114)+chr(95)+chr(112)+chr(97)+chr(116)+chr(116)+chr(101)+chr(114)+chr(110))} | {str(it.get(chr(39)+chr(109)+chr(97)+chr(116)+chr(99)+chr(104)+chr(101)+chr(100)+chr(95)+chr(108)+chr(105)+chr(110)+chr(101))).replace(chr(124), chr(92)+chr(124))} |")
    md_fp.write_text('\n'.join(lines)+"\n", encoding='utf-8')
    notes.append(f"error_reason_md={md_fp}")


    print(
        f"status={sample_status} date={d} expected_slots={expected_n} actual_reports={actual_n} "
        f"missing_slots={missing} timeout_or_error_slots={timeout_err} is_full_trading_day_sample={is_full} grade={grade} "
        f"output={out}"
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
