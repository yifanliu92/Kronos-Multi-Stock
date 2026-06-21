#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

BASE=Path('/Users/wxo/Desktop/Kronos')
GUARD=BASE/'guard_outputs'
DAILY=BASE/'daily_reports'


def slot_from_run_ms(runAtMs: int, tz: str='Asia/Shanghai') -> str:
    dt=datetime.fromtimestamp(runAtMs/1000.0, tz=ZoneInfo(tz))
    return dt.strftime('%H%M')


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('date', help='YYYYMMDD')
    ap.add_argument('--expected', default=None)
    ap.add_argument('--runs', default=None)
    ap.add_argument('--reportDir', default=str(GUARD))
    args=ap.parse_args()

    d=args.date
    expected_p=Path(args.expected or (GUARD/f'expected_slots_{d}.json'))
    runs_p=Path(args.runs or (GUARD/f'cron_runs_{d}.json'))

    if not expected_p.exists():
        raise SystemExit(f'missing expected: {expected_p}')

    expected=json.loads(expected_p.read_text(encoding='utf-8'))
    expected_slots=expected.get('expected_timeslots',[])
    tz=expected.get('timezone','Asia/Shanghai')
    expr=expected.get('source_cron_expression','')
    jobId=expected.get('source_job_id','')

    # runs file optional; if missing, we can still classify by report existence only
    runs=[]
    if runs_p.exists():
        runs=json.loads(runs_p.read_text(encoding='utf-8')).get('entries',[])

    # build map slot -> best run
    runs_by_slot={}
    for r in runs:
        runAtMs=r.get('runAtMs')
        if not isinstance(runAtMs,(int,float)):
            continue
        slot=slot_from_run_ms(int(runAtMs), tz)
        # only consider same day
        # compare YYYYMMDD from local time
        dt=datetime.fromtimestamp(int(runAtMs)/1000.0, tz=ZoneInfo(tz))
        if dt.strftime('%Y%m%d')!=d:
            continue
        # keep latest runAtMs for the slot
        cur=runs_by_slot.get(slot)
        if not cur or int(runAtMs) >= int(cur.get('runAtMs',0)):
            runs_by_slot[slot]=r

    # reports present
    report_dir=Path(args.reportDir)
    reports=list(report_dir.glob(f'report_{d}_*.txt'))
    actual_report_slots=set()
    for p in reports:
        # report_YYYYMMDD_HHMMSS.txt
        s=p.stem.split('_')[-1]
        if len(s)>=4:
            actual_report_slots.add(s[:4])

    rows=[]
    for slot in expected_slots:
        row={
            'timeslot': slot,
            'scheduled': True,
            'cron_triggered': slot in runs_by_slot,
            'run_status': None,
            'report_generated': slot in actual_report_slots,
            'delivered': None,
            'deliveryStatus': None,
            'error_code': None,
            'final_reason': None,
            'status': None,
            'source_job_id': jobId,
            'source_cron_expression': expr,
            'timezone': tz,
        }
        r=runs_by_slot.get(slot)
        if r:
            row['run_status']=r.get('status')
            row['delivered']=r.get('delivered')
            row['deliveryStatus']=r.get('deliveryStatus')
            # error extraction
            err=r.get('error') or r.get('summary')
            err_s=str(err) if err is not None else ''
            # classify model errors: explicit 'model', 'gpt-' patterns, or codex unsupported messages
            if r.get('status')=='error' and (
                'model' in err_s.lower() or
                'gpt-' in err_s.lower() or
                'not supported' in err_s.lower()
            ):
                row['error_code']='MODEL_ERROR'
            elif r.get('status')=='error':
                row['error_code']='EXEC_ERROR'
            else:
                row['error_code']='OK'

        # classify
        if slot not in expected_slots:
            row['final_reason']='NOT_SCHEDULED'
        else:
            if not row['cron_triggered']:
                row['final_reason']='SCHEDULED_NOT_TRIGGERED'
            else:
                if row['run_status']=='error':
                    if row['error_code']=='MODEL_ERROR':
                        row['final_reason']='MODEL_ERROR'
                    else:
                        row['final_reason']='EXEC_ERROR'
                else:
                    if not row['report_generated']:
                        row['final_reason']='TRIGGERED_NO_REPORT'
                    else:
                        if row['delivered'] is False:
                            row['final_reason']='DELIVERY_FAILED'
                        elif row['delivered'] is True:
                            row['final_reason']='SUCCESS'
                        else:
                            row['final_reason']='UNKNOWN_MISSING_SLOT'

        row['status']=row['final_reason']
        rows.append(row)

    out_json=GUARD/f'slot_coverage_daily_{d}.json'
    out_md=DAILY/f'slot_coverage_summary_{d}.md'
    out_json.write_text(json.dumps({'date':d,'generated_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'expected_slots':expected_slots,'slots':rows},ensure_ascii=False,indent=2),encoding='utf-8')

    missing=[r for r in rows if r['final_reason']!='SUCCESS']
    critical={'1450'}
    crit=[r['timeslot'] for r in missing if r['timeslot'] in critical]
    md=[
        f"# slot_coverage_summary {d}",
        f"- generated_at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- source_job_id: {jobId}",
        f"- source_cron_expression: {expr}",
        f"- timezone: {tz}",
        f"- expected_slots: {len(expected_slots)}",
        f"- missing_slots: {len(missing)}",
        f"- critical_missing: {', '.join(crit) if crit else 'none'}",
        "",
        "## Missing detail",
    ]
    for r in missing:
        md.append(f"- {r['timeslot']}: {r['final_reason']} run={r['run_status']} delivered={r['delivered']} report={r['report_generated']} err={r['error_code']}")
    out_md.write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(out_json)
    print(out_md)

if __name__=='__main__':
    main()
