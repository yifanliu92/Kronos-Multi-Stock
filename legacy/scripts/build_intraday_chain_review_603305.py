#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
GUARD = BASE / 'guard_outputs'
DAILY = BASE / 'daily_reports'


def load_expected(date: str) -> list[str]:
    # Prefer slot_coverage_daily if exists (it already contains expected slots)
    cov = GUARD / f'slot_coverage_daily_{date}.json'
    if cov.exists():
        try:
            d = json.loads(cov.read_text(encoding='utf-8'))
            return [s['timeslot'] for s in d.get('slots', [])]
        except Exception:
            pass

    # Fallback: morning + expected_slots + close
    morning = ["0930","0940","0950","1000","1010","1020","1030","1040","1050","1100","1110","1120","1130"]
    close = ["1500"]
    exp_p = GUARD / f"expected_slots_{date}.json"
    mid = []
    if exp_p.exists():
        try:
            exp = json.loads(exp_p.read_text(encoding='utf-8'))
            mid = [x for x in exp.get('expected_timeslots', []) if x]
        except Exception:
            mid = []
    return sorted(set(morning + mid + close))


def parse_audit_block(text: str) -> dict:
    out = {}
    for ln in text.splitlines():
        if ln.startswith('[AUDIT]'):
            kv = ln.replace('[AUDIT]','',1).strip()
            if '=' in kv:
                k,v = kv.split('=',1)
                out[k.strip()] = v.strip()
    return out


def cron_list() -> dict:
    cp = subprocess.run(['openclaw','cron','list','--json'], capture_output=True, text=True)
    if cp.returncode != 0:
        return {'jobs': []}
    return json.loads(cp.stdout)


def cron_runs(job_id: str, limit: int = 200) -> list[dict]:
    # openclaw cron runs outputs JSON by default
    cp = subprocess.run(['openclaw','cron','runs','--id', job_id, '--limit', str(limit)], capture_output=True, text=True)
    if cp.returncode != 0:
        return []
    try:
        d = json.loads(cp.stdout)
    except Exception:
        return []
    return d.get('entries', [])


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('date', help='YYYYMMDD')
    args=ap.parse_args()
    date=args.date

    expected = load_expected(date)

    jobs = cron_list().get('jobs', [])
    # focus on 603305 intraday sim jobs (auto_report_guard)
    target_jobs = [j for j in jobs if j.get('enabled', True) and '603305' in (j.get('name','')+((j.get('payload') or {}).get('message','')))]

    # build index of runs by timeslot
    runs_by_slot: dict[str, dict] = {}
    for j in target_jobs:
        jid = j.get('id')
        if not jid:
            continue
        for r in cron_runs(jid, limit=300):
            run_at_ms = int(r.get('runAtMs') or 0)
            if not run_at_ms:
                continue
            dt = datetime.fromtimestamp(run_at_ms/1000.0)
            slot = dt.strftime('%H%M')
            if dt.strftime('%Y%m%d') != date:
                continue
            prev = runs_by_slot.get(slot)
            if (not prev) or int(r.get('runAtMs') or 0) >= int(prev.get('runAtMs') or 0):
                r2 = dict(r)
                r2['jobName'] = j.get('name')
                runs_by_slot[slot] = r2

    rows=[]
    for slot in expected:
        report_path = GUARD / f'report_{date}_{slot}00.txt'
        # some reports may include seconds 07/08 etc; match by glob
        matches = sorted(GUARD.glob(f'report_{date}_{slot}*.txt'))
        report_file = str(matches[-1]) if matches else ''
        report_generated = bool(matches)
        delivered = None
        deliveryStatus = None
        run_status = None
        sessionId = None
        durationMs = None
        model = None
        provider = None
        summary = None
        error = None
        jobId = None
        provider_final = ''
        final_error_code = ''
        model_guard = None
        fallback_attempted = None

        run = runs_by_slot.get(slot)
        if run:
            run_status = run.get('status')
            delivered = run.get('delivered')
            deliveryStatus = run.get('deliveryStatus')
            sessionId = run.get('sessionId')
            durationMs = run.get('durationMs')
            model = run.get('model')
            provider = run.get('provider')
            summary = run.get('summary')
            error = run.get('error')
            jobId = run.get('jobId')

        audit = {}
        if report_generated:
            try:
                txt = Path(report_file).read_text(encoding='utf-8', errors='ignore')
                audit = parse_audit_block(txt)
            except Exception:
                audit = {}

        provider_final = audit.get('provider_final','')
        final_error_code = audit.get('final_error_code','')
        model_guard = audit.get('model_guard_pass','')
        fallback_attempted = audit.get('fallback_attempted','')

        # quick flags
        has_shadow = False
        if report_generated:
            try:
                txt = Path(report_file).read_text(encoding='utf-8', errors='ignore')
                has_shadow = ('【影子策略' in txt)
            except Exception:
                pass

        rows.append({
            'date': date,
            'timeslot': slot,
            'expected': True,
            'triggered': bool(run),
            'run_status': run_status or '',
            'jobId': jobId or '',
            'sessionId': sessionId or '',
            'durationMs': durationMs,
            'delivered': delivered,
            'deliveryStatus': deliveryStatus,
            'report_generated': report_generated,
            'report_file': report_file,
            'shadow_present': has_shadow,
            'provider_final': provider_final or 'unknown',
            'final_error_code': final_error_code or '',
            'model_guard_pass': model_guard or 'unknown',
            'model_used': model or '',
            'provider_runtime': provider or '',
            'timeout': bool(error and 'timed out' in str(error)),
            'old_model_error': bool(error and ('gpt-5.1' in str(error) or 'gpt-5.3' in str(error))),
            'report_inconsistent': bool(report_generated and 'REPORT_INCONSISTENT' in Path(report_file).read_text(encoding='utf-8',errors='ignore')),
        })

    out_json = GUARD / f'intraday_chain_review_{date}.json'
    out_md = DAILY / f'intraday_chain_review_{date}.md'

    payload = {
        'date': date,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'slots': rows,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    # markdown summary
    total=len(rows)
    triggered=sum(1 for r in rows if r['triggered'])
    report_ok=sum(1 for r in rows if r['report_generated'])
    delivered_ok=sum(1 for r in rows if r.get('delivered') is True)
    timeouts=sum(1 for r in rows if r.get('timeout'))
    old_model=sum(1 for r in rows if r.get('old_model_error'))

    md=[
        f"# intraday_chain_review {date}",
        f"- generated_at: {payload['generated_at']}",
        f"- expected_slots: {total}",
        f"- triggered_runs: {triggered}",
        f"- reports_generated: {report_ok}",
        f"- telegram_delivered_true: {delivered_ok}",
        f"- timeout_count: {timeouts}",
        f"- old_model_error_count: {old_model}",
        "",
        "## Slots",
    ]
    for r in rows:
        md.append(f"- {r['timeslot']}: triggered={r['triggered']} run_status={r['run_status']} report={r['report_generated']} delivered={r.get('delivered')} provider_final={r['provider_final']} error_code={r['final_error_code']}")
    out_md.write_text('\n'.join(md)+'\n', encoding='utf-8')

    print(out_json)
    print(out_md)


if __name__=='__main__':
    main()
