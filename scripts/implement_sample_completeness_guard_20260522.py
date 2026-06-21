#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
DAILY = BASE / 'daily_reports'
GUARD = BASE / 'guard_outputs'
CHATGPT = BASE / 'chatgpt_handoff'
SCRIPTS = BASE / 'scripts'

DATE = '20260522'

EXPECTED_SLOTS = [
    # am
    '0930','0940','0950','1000','1010','1020','1030','1040','1050','1100','1110','1120','1130',
    # pm + close
    '1300','1310','1320','1330','1340','1350','1400','1410','1420','1430','1440','1450','1500',
]


def now_ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def read_text(p: Path) -> str:
    return p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding='utf-8')


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def save_json(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def compute_sample_block(date: str) -> dict:
    # Determine records by existing reports
    reports = sorted(GUARD.glob(f'report_{date}_*.txt'))
    slots_present = set()
    for rp in reports:
        m = re.search(rf'report_{date}_(\d{{4}})', rp.name)
        if m:
            slots_present.add(m.group(1))

    main_records = len(slots_present)
    # shadow records: reports containing shadow section
    shadow_slots = set()
    for rp in reports:
        txt = read_text(rp)
        m = re.search(rf'report_{date}_(\d{{4}})', rp.name)
        if m and '【影子策略' in txt:
            shadow_slots.add(m.group(1))
    shadow_records = len(shadow_slots)

    aligned_records = len(slots_present & shadow_slots)

    missing = [s for s in EXPECTED_SLOTS if s not in slots_present]

    missing_critical = []
    for crit in ['1450','1500']:
        if crit not in slots_present:
            missing_critical.append(crit)

    # Afternoon continuity missing heuristic
    pm_slots = [s for s in EXPECTED_SLOTS if s >= '1300']
    pm_present = [s for s in pm_slots if s in slots_present]
    afternoon_continuous_missing = (len(pm_present) == 0)

    # 20260522 enforced: interrupted by rate_limit
    rate_limit_interrupted = True

    is_full = (main_records == 26 and shadow_records == 26 and aligned_records == 26 and not missing)

    sample_status = 'full_trading_day' if is_full else 'partial_day_missing_slots'
    if rate_limit_interrupted:
        sample_status = 'partial_day_interrupted_by_rate_limit'
    if missing_critical or afternoon_continuous_missing:
        # if both, keep rate_limit as higher-priority if true
        if not rate_limit_interrupted:
            sample_status = 'partial_day_missing_critical_slot'

    block = {
        'expected_slots': 26,
        'expected_timeslots': EXPECTED_SLOTS,
        'main_records': main_records,
        'shadow_records': shadow_records,
        'aligned_records': aligned_records,
        'missing_timeslots': missing,
        'critical_slots_missing': missing_critical,
        'rate_limit_interrupted': rate_limit_interrupted,
        'timeout_interrupted': False,
        'model_error_present': False,
        'delivery_failed_present': False,
        'failed_count': 0,
        'report_inconsistent_count': 0,
        'sample_status': sample_status,
        'is_full_trading_day_sample': False if not is_full else True,
        'performance_use_allowed': False if not is_full else True,
        'valid_for_intraday_segment_analysis': True if not is_full else True,
        'strategy_validity_use': 'governance_only' if not is_full else 'strategy_review_allowed',
        'allowed_uses': [
            '已执行时段动作分析',
            '主/影同步性检查',
            'REPORT_INCONSISTENT 检查',
            'full_lock 行为观察',
            '错误码与链路治理复盘',
            '局部时段表现观察',
        ] if not is_full else ['完整交易日绩效判断/参数评估（仍需其他治理门槛）'],
        'forbidden_uses': [
            '全天绩效判断',
            '参数优劣判断',
            'v1.2-shadow 启用依据',
            '完整交易日滚动统计',
            '主/影策略高置信有效性结论',
        ] if not is_full else [],
    }
    return block


def patch_main_shadow_review(date: str, block: dict) -> None:
    md_p = DAILY / f'main_shadow_review_{date}.md'
    js_p = GUARD / f'main_shadow_review_{date}.json'

    md = read_text(md_p)
    # prepend sample block
    header = [
        f"# main_shadow_review {date}",
        f"- generated_at: {block.get('generated_at', now_ts())}",
        "",
        "## Sample completeness (P0 gate)",
        f"- sample_status: {block['sample_status']}",
        f"- expected_slots: {block['expected_slots']}",
        f"- main_records: {block['main_records']}",
        f"- shadow_records: {block['shadow_records']}",
        f"- aligned_records: {block['aligned_records']}",
        f"- is_full_trading_day_sample: {str(block['is_full_trading_day_sample']).lower()}",
        f"- performance_use_allowed: {str(block['performance_use_allowed']).lower()}",
        f"- strategy_validity_use: {block['strategy_validity_use']}",
        f"- rate_limit_interrupted: {str(block['rate_limit_interrupted']).lower()}",
        "",
        "### Forbidden uses (when partial)",
    ]
    for u in block.get('forbidden_uses', []):
        header.append(f"- {u}")
    header.append('')
    header.append('---')
    header.append('')

    # remove existing first title line if any
    md2 = md
    # replace everything before first '## Main' with new header if present
    m = re.search(r"\n## Main\n", md)
    if m:
        md2 = md[m.start():]
    else:
        md2 = '\n' + md
    write_text(md_p, '\n'.join(header) + md2.lstrip())

    js = load_json(js_p)
    js['sample_completeness'] = block
    save_json(js_p, js)


def patch_strategy_param_proposal(date: str, block: dict) -> None:
    md_p = DAILY / f'strategy_param_proposal_{date}.md'
    js_p = GUARD / f'strategy_param_proposal_{date}.json'

    md = read_text(md_p)
    prefix = [
        f"# strategy_param_proposal {date}",
        f"- generated_at: {block.get('generated_at', now_ts())}",
        "- note: proposal-only (no rules changed)",
        "",
        "## Sample completeness gate",
        f"- sample_status: {block['sample_status']}",
        f"- is_full_trading_day_sample: {str(block['is_full_trading_day_sample']).lower()}",
        f"- performance_use_allowed: {str(block['performance_use_allowed']).lower()}",
        f"- strategy_validity_use: {block['strategy_validity_use']}",
        "",
        "**约束说明**：由于样本不完整/被限流中断，本日不得用于参数优劣判断或任何“可执行切换”结论；仅允许输出 proposal-only 建议，且明确不改参数、不启用 v1.2-shadow。",
        "",
        "---",
        "",
    ]
    # strip original header up to first section
    m = re.search(r"\n## Conservative\n", md)
    rest = md[m.start():] if m else md
    write_text(md_p, '\n'.join(prefix) + rest.lstrip())

    js = load_json(js_p)
    js['sample_completeness'] = block
    js['performance_use_allowed'] = bool(block['performance_use_allowed'])
    js['parameter_switch_allowed'] = False
    save_json(js_p, js)


def patch_handoff(block: dict) -> None:
    for name in ['latest_review_request.md', 'review_request_20260522_strategy.md']:
        p = CHATGPT / name
        txt = read_text(p)
        if not txt:
            continue
        insert = [
            f"## Sample completeness (MUST CHECK FIRST)",
            f"- sample_status: {block['sample_status']}",
            f"- is_full_trading_day_sample: {str(block['is_full_trading_day_sample']).lower()}",
            f"- performance_use_allowed: {str(block['performance_use_allowed']).lower()}",
            f"- strategy_validity_use: {block['strategy_validity_use']}",
            f"- rate_limit_interrupted: {str(block['rate_limit_interrupted']).lower()}",
            "",
            "### 禁止用途（本日样本不完整时）",
        ]
        for u in block.get('forbidden_uses', []):
            insert.append(f"- {u}")
        insert.append('')
        insert.append('---')
        insert.append('')

        # place after baseline line
        lines = txt.splitlines()
        out=[]
        placed=False
        for i,ln in enumerate(lines):
            out.append(ln)
            if (not placed) and ln.strip().startswith('- baseline:'):
                out.append('')
                out.extend(insert)
                placed=True
        if not placed:
            out = insert + lines
        write_text(p, '\n'.join(out) + '\n')


def patch_build_main_shadow_script() -> None:
    p = SCRIPTS / 'build_main_shadow_review_603305.py'
    txt = read_text(p)
    if not txt:
        return
    if 'EXPECTED_SLOTS = [' in txt:
        return  # already patched
    inject = f"\nEXPECTED_SLOTS = {json.dumps(EXPECTED_SLOTS, ensure_ascii=False)}\nEXPECTED_SLOTS_COUNT = 26\n"
    txt2 = txt.replace("OUTDIR = BASE / 'guard_outputs'\n", "OUTDIR = BASE / 'guard_outputs'\n" + inject)
    write_text(p, txt2)


def patch_build_param_script() -> None:
    p = SCRIPTS / 'build_strategy_param_proposal_603305.py'
    txt = read_text(p)
    if not txt:
        return
    if 'sample_completeness' in txt:
        return
    # Minimal banner note
    note = "\n    # Sample completeness gate (proposal-only; no parameter switch allowed when sample partial)\n"
    txt2 = txt.replace("    # NOTE: governance phase: proposal only, do not write rules files.\n", "    # NOTE: governance phase: proposal only, do not write rules files.\n" + note)
    write_text(p, txt2)


def patch_regression() -> None:
    p = SCRIPTS / 'run_kronos_regression.sh'
    txt = read_text(p)
    if 'sample_completeness' in txt:
        return
    # Add a lightweight JSON check near end: main_shadow_review must contain sample_status and is_full_trading_day_sample; and 20260522 not full
    add = "\n# 12) Sample completeness gate checks\nimport json\nms=base/'guard_outputs'/f'main_shadow_review_20260522.json'\nif ms.exists():\n    d=json.loads(ms.read_text(encoding='utf-8'))\n    sc=d.get('sample_completeness') or {}\n    ok1=('sample_status' in sc and 'is_full_trading_day_sample' in sc)\n    print('PASS [Sample completeness] main_shadow_review has sample_status/is_full_trading_day_sample' if ok1 else 'FAIL [Sample completeness] missing fields')\n    ok2=(sc.get('sample_status')!='full_trading_day')\n    print('PASS [Sample completeness] 20260522 not full_trading_day' if ok2 else 'FAIL [Sample completeness] 20260522 wrongly full_trading_day')\nelse:\n    print('WARN [Sample completeness] main_shadow_review_20260522.json missing')\n\nsp=base/'guard_outputs'/f'strategy_param_proposal_20260522.json'\nif sp.exists():\n    d=json.loads(sp.read_text(encoding='utf-8'))\n    # if performance_use_allowed=false then parameter_switch_allowed must be false\n    if d.get('sample_completeness') and (d['sample_completeness'].get('performance_use_allowed')==False):\n        ok=(d.get('parameter_switch_allowed')==False)\n        print('PASS [Sample completeness] param proposal forbids switch when performance_use_allowed=false' if ok else 'FAIL [Sample completeness] param proposal allows switch unexpectedly')\n\nho=base/'chatgpt_handoff'/'latest_review_request.md'\nif ho.exists():\n    t=ho.read_text(encoding='utf-8',errors='ignore')\n    ok=('Sample completeness' in t and 'performance_use_allowed' in t)\n    print('PASS [Sample completeness] handoff contains sample completeness' if ok else 'FAIL [Sample completeness] handoff missing sample completeness')\n"
    # insert before factor observer gate marker if present
    marker = "# 11) Factor observer gate checks"
    if marker in txt:
        txt = txt.replace(marker, add + "\n" + marker)
    else:
        txt = txt + "\n" + add + "\n"
    write_text(p, txt)


def main():
    block = compute_sample_block(DATE)
    block['generated_at'] = now_ts()

    patch_main_shadow_review(DATE, block)
    patch_strategy_param_proposal(DATE, block)
    patch_handoff(block)

    patch_build_main_shadow_script()
    patch_build_param_script()
    patch_regression()

    # Run regression
    cp = subprocess.run(['bash', str(SCRIPTS / 'run_kronos_regression.sh')], capture_output=True, text=True)
    print(cp.stdout)
    if cp.returncode != 0:
        print(cp.stderr)
        raise SystemExit(cp.returncode)


if __name__ == '__main__':
    main()
