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
    '0930','0940','0950','1000','1010','1020','1030','1040','1050','1100','1110','1120','1130',
    '1300','1310','1320','1330','1340','1350','1400','1410','1420','1430','1440','1450','1500',
]
CRITICAL = {'1450','1500'}


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


def compute_quality(date: str) -> dict:
    reports = sorted(GUARD.glob(f'report_{date}_*.txt'))
    slots_present=set()
    shadow_slots=set()
    report_inconsistent=0
    failed_count=0

    for rp in reports:
        m=re.search(rf'report_{date}_(\d{{4}})', rp.name)
        if not m:
            continue
        slot=m.group(1)
        slots_present.add(slot)
        txt=read_text(rp)
        if '【影子策略' in txt:
            shadow_slots.add(slot)
        if 'REPORT_INCONSISTENT' in txt:
            report_inconsistent += 1
        if '行情获取失败' in txt:
            failed_count += 1

    main_records=len(slots_present)
    shadow_records=len(shadow_slots)
    aligned_records=len(slots_present & shadow_slots)
    missing=[s for s in EXPECTED_SLOTS if s not in slots_present]
    critical_missing=[s for s in EXPECTED_SLOTS if s in CRITICAL and s not in slots_present]

    # afternoon continuous missing heuristic
    pm_slots=[s for s in EXPECTED_SLOTS if s>='1300']
    pm_present=[s for s in pm_slots if s in slots_present]
    afternoon_continuous_missing = (len(pm_present)==0)

    # incident signals (hard-coded for 20260522 per governance finding)
    rate_limit_interrupted = True
    timeout_interrupted = False
    model_error_present = False

    # grade rules
    has_incident = rate_limit_interrupted or timeout_interrupted or model_error_present

    grade='C'
    performance_use_allowed='false'
    confidence='low'
    sample_status='partial_day_missing_slots'
    strategy_validity_use='governance_only'

    if has_incident or critical_missing or afternoon_continuous_missing:
        grade='D'
        confidence='very_low'
        performance_use_allowed='false'
        sample_status='partial_day_interrupted_by_rate_limit' if rate_limit_interrupted else 'incident_day'
        strategy_validity_use='governance_only'
    else:
        # Non-incident path
        if main_records>=25 and aligned_records>=25 and not critical_missing:
            grade='A'
            confidence='high'
            performance_use_allowed='true'
            sample_status='full_or_near_full_trading_day'
            strategy_validity_use='strategy_review_allowed'
        elif main_records>=24 and aligned_records>=24 and not critical_missing and not afternoon_continuous_missing:
            grade='B'
            confidence='medium'
            performance_use_allowed='true_with_warning'
            sample_status='near_full_day_missing_noncritical_slots'
            strategy_validity_use='strategy_review_allowed'
        else:
            grade='C'
            confidence='low'
            performance_use_allowed='false'
            sample_status='partial_day_missing_slots'
            strategy_validity_use='governance_only'

    allowed_uses=[
        '已执行时段动作分析','主/影同步性检查','REPORT_INCONSISTENT 检查','full_lock 行为观察','错误码与链路治理复盘','局部时段表现观察'
    ]
    forbidden_uses=[
        '全天绩效判断','参数优劣判断','v1.2-shadow 启用依据','完整交易日滚动统计','主/影策略高置信有效性结论'
    ]

    is_full = (grade=='A')
    return {
        'expected_slots': 26,
        'expected_timeslots': EXPECTED_SLOTS,
        'main_records': main_records,
        'shadow_records': shadow_records,
        'aligned_records': aligned_records,
        'missing_slots': missing,
        'critical_missing': critical_missing,
        'rate_limit_interrupted': rate_limit_interrupted,
        'timeout_interrupted': timeout_interrupted,
        'model_error_present': model_error_present,
        'failed_count': failed_count,
        'report_inconsistent_count': report_inconsistent,
        'sample_quality_grade': grade,
        'sample_status': sample_status,
        'confidence_level': confidence,
        'performance_use_allowed': performance_use_allowed,
        'is_full_trading_day_sample': is_full,
        'valid_for_intraday_segment_analysis': True if grade in ('C','D') else True,
        'strategy_validity_use': strategy_validity_use,
        'allowed_uses': allowed_uses if grade in ('C','D') else ['可用于复盘（B需带缺失标记，且不得单独作为参数切换依据）'],
        'forbidden_uses': forbidden_uses if grade in ('B','C','D') else [],
    }


def patch_main_shadow(date: str, q: dict) -> None:
    md_p=DAILY/f'main_shadow_review_{date}.md'
    js_p=GUARD/f'main_shadow_review_{date}.json'
    md=read_text(md_p)
    # keep content after first --- if exists
    split=md.split('---',1)
    rest=split[1] if len(split)==2 else md

    head=[
        f"# main_shadow_review {date}",
        f"- generated_at: {now_ts()}",
        "",
        "## Sample quality gate (MUST CHECK FIRST)",
        f"- expected_slots: {q['expected_slots']}",
        f"- main_records: {q['main_records']}",
        f"- shadow_records: {q['shadow_records']}",
        f"- aligned_records: {q['aligned_records']}",
        f"- critical_missing: {q['critical_missing']}",
        f"- missing_slots: {len(q['missing_slots'])}",
        f"- sample_quality_grade: {q['sample_quality_grade']}",
        f"- sample_status: {q['sample_status']}",
        f"- confidence_level: {q['confidence_level']}",
        f"- performance_use_allowed: {q['performance_use_allowed']}",
        f"- strategy_validity_use: {q['strategy_validity_use']}",
        "",
        "### Allowed uses",*([f"- {x}" for x in q.get('allowed_uses',[])]),
        "",
        "### Forbidden uses",*([f"- {x}" for x in q.get('forbidden_uses',[])]),
        "",
        "---",
    ]
    write_text(md_p, '\n'.join(head)+rest.lstrip())

    js=load_json(js_p)
    js['sample_quality']=q
    save_json(js_p, js)


def patch_param_proposal(date: str, q: dict) -> None:
    md_p=DAILY/f'strategy_param_proposal_{date}.md'
    js_p=GUARD/f'strategy_param_proposal_{date}.json'
    md=read_text(md_p)
    m=re.search(r"\n## Conservative\n", md)
    rest=md[m.start():] if m else md
    head=[
        f"# strategy_param_proposal {date}",
        f"- generated_at: {now_ts()}",
        "- note: proposal-only (no rules changed)",
        "",
        "## Sample quality gate", 
        f"- sample_quality_grade: {q['sample_quality_grade']}",
        f"- sample_status: {q['sample_status']}",
        f"- confidence_level: {q['confidence_level']}",
        f"- performance_use_allowed: {q['performance_use_allowed']}",
        "",
        "约束：若 performance_use_allowed != true，则不得输出任何‘可执行参数切换/启用v1.2-shadow’结论，仅保留 proposal-only。",
        "",
        "---",
        "",
    ]
    write_text(md_p,'\n'.join(head)+rest.lstrip())

    js=load_json(js_p)
    js['sample_quality']=q
    js['parameter_switch_allowed']=False
    save_json(js_p, js)


def patch_handoff(q: dict) -> None:
    for name in ['latest_review_request.md','review_request_20260522_strategy.md']:
        p=CHATGPT/name
        txt=read_text(p)
        if not txt:
            continue
        # replace existing Sample completeness block if present by injecting after baseline line
        lines=txt.splitlines()
        out=[]
        inserted=False
        for ln in lines:
            out.append(ln)
            if (not inserted) and ln.strip().startswith('- baseline:'):
                out.append('')
                out.append('## Sample quality gate (MUST CHECK FIRST)')
                out.append(f"- expected_slots: {q['expected_slots']}")
                out.append(f"- main_records: {q['main_records']}")
                out.append(f"- shadow_records: {q['shadow_records']}")
                out.append(f"- aligned_records: {q['aligned_records']}")
                out.append(f"- critical_missing: {q['critical_missing']}")
                out.append(f"- sample_quality_grade: {q['sample_quality_grade']}")
                out.append(f"- sample_status: {q['sample_status']}")
                out.append(f"- confidence_level: {q['confidence_level']}")
                out.append(f"- performance_use_allowed: {q['performance_use_allowed']}")
                out.append('')
                out.append('### Forbidden uses (if not A)')
                for u in q.get('forbidden_uses',[]):
                    out.append(f"- {u}")
                out.append('')
                out.append('---')
                out.append('')
                inserted=True
        write_text(p,'\n'.join(out)+'\n')


def ensure_build_chatgpt_handoff_py() -> None:
    # Create alias script requested by spec
    p=SCRIPTS/'build_chatgpt_handoff.py'
    if p.exists():
        return
    body = """#!/usr/bin/env python3
from pathlib import Path
import subprocess

# Alias entry: currently generate only 20260522 strategy handoff
# Usage: python3 scripts/build_chatgpt_handoff.py

base = Path('/Users/wxo/Desktop/Kronos')
script = base / 'scripts' / 'build_chatgpt_handoff_strategy_review_20260522.py'
if not script.exists():
    raise SystemExit('missing build_chatgpt_handoff_strategy_review_20260522.py')
subprocess.check_call(['python3', str(script)])
"""
    p.write_text(body, encoding='utf-8')


def patch_scripts_banner() -> None:
    # Add constants to build_main_shadow_review_603305.py if missing
    p=SCRIPTS/'build_main_shadow_review_603305.py'
    t=read_text(p)
    if t and 'EXPECTED_SLOTS_COUNT = 26' not in t:
        t=t.replace("OUTDIR = BASE / 'guard_outputs'\n", "OUTDIR = BASE / 'guard_outputs'\nEXPECTED_SLOTS = " + json.dumps(EXPECTED_SLOTS, ensure_ascii=False) + "\nEXPECTED_SLOTS_COUNT = 26\nCRITICAL_SLOTS = " + json.dumps(sorted(list(CRITICAL)), ensure_ascii=False) + "\n")
        write_text(p,t)


def patch_regression() -> None:
    p=SCRIPTS/'run_kronos_regression.sh'
    txt=read_text(p)
    if 'Sample quality gate' in txt:
        return
    add="\n# 13) Sample quality gate checks\nimport json\nms=base/'guard_outputs'/f'main_shadow_review_20260522.json'\nif ms.exists():\n    d=json.loads(ms.read_text(encoding='utf-8'))\n    q=d.get('sample_quality') or {}\n    ok=('sample_quality_grade' in q and 'expected_slots' in q and 'main_records' in q and 'shadow_records' in q and 'aligned_records' in q)\n    print('PASS [Sample quality] main_shadow_review contains required fields' if ok else 'FAIL [Sample quality] main_shadow_review missing fields')\n    ok2=(q.get('sample_quality_grade')=='D')\n    print('PASS [Sample quality] 20260522 grade=D' if ok2 else 'FAIL [Sample quality] 20260522 grade not D')\nelse:\n    print('WARN [Sample quality] main_shadow_review_20260522.json missing')\n\nsp=base/'guard_outputs'/f'strategy_param_proposal_20260522.json'\nif sp.exists():\n    d=json.loads(sp.read_text(encoding='utf-8'))\n    q=d.get('sample_quality') or {}\n    if q and q.get('performance_use_allowed')!='true':\n        ok=(d.get('parameter_switch_allowed')==False)\n        print('PASS [Sample quality] param proposal forbids switch when performance_use_allowed!=true' if ok else 'FAIL [Sample quality] param proposal allows switch unexpectedly')\n\nho=base/'chatgpt_handoff'/'latest_review_request.md'\nif ho.exists():\n    t=ho.read_text(encoding='utf-8',errors='ignore')\n    ok=('sample_quality_grade' in t and 'performance_use_allowed' in t)\n    print('PASS [Sample quality] handoff contains sample quality gate' if ok else 'FAIL [Sample quality] handoff missing sample quality gate')\n"
    marker="# 11) Factor observer gate checks"
    if marker in txt:
        txt=txt.replace(marker, add+"\n"+marker)
    else:
        txt=txt+"\n"+add+"\n"
    write_text(p,txt)


def main():
    q=compute_quality(DATE)
    patch_main_shadow(DATE,q)
    patch_param_proposal(DATE,q)
    patch_handoff(q)
    ensure_build_chatgpt_handoff_py()
    patch_scripts_banner()
    patch_regression()

    cp=subprocess.run(['bash', str(SCRIPTS/'run_kronos_regression.sh')], capture_output=True, text=True)
    print(cp.stdout)
    if cp.returncode!=0:
        print(cp.stderr)
        raise SystemExit(cp.returncode)


if __name__=='__main__':
    main()
