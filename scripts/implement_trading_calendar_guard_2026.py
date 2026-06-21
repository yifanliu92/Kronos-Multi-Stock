#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
CFG_DIR = BASE / 'config'
SCRIPTS = BASE / 'scripts'
DAILY = BASE / 'daily_reports'
GUARD = BASE / 'guard_outputs'

CAL_PATH = CFG_DIR / 'cn_a_share_trading_calendar_2026.json'
TC_PATH = SCRIPTS / 'trading_calendar.py'

HOLIDAY_RANGES = [
    ('2026-01-01','2026-01-03','元旦'),
    ('2026-02-15','2026-02-23','春节'),
    ('2026-04-04','2026-04-06','清明节'),
    ('2026-05-01','2026-05-05','劳动节'),
    ('2026-06-19','2026-06-21','端午节'),
    ('2026-09-25','2026-09-27','中秋节'),
    ('2026-10-01','2026-10-07','国庆节'),
]


def parse(d: str) -> date:
    return date.fromisoformat(d)


def daterange(a: date, b: date):
    cur=a
    while cur<=b:
        yield cur
        cur += timedelta(days=1)


def build_calendar_2026():
    year=2026
    start=date(year,1,1)
    end=date(year,12,31)

    weekend_days=[]
    for d in daterange(start,end):
        if d.weekday()>=5:
            weekend_days.append(d.isoformat())

    holiday_days=set()
    holiday_ranges=[]
    for s,e,name in HOLIDAY_RANGES:
        sd,ed=parse(s),parse(e)
        holiday_ranges.append({'name':name,'start':s,'end':e})
        for d in daterange(sd,ed):
            holiday_days.add(d.isoformat())

    non_trading=set(weekend_days) | holiday_days

    trading_days=[]
    non_trading_days=[]
    for d in daterange(start,end):
        ds=d.isoformat()
        if ds in non_trading:
            non_trading_days.append(ds)
        else:
            trading_days.append(ds)

    payload={
        'year': year,
        'market': 'CN_A_SHARE',
        'source': 'SSE/SZSE annual holiday schedule (user-provided known ranges) + weekend rule',
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'holiday_ranges': holiday_ranges,
        'special_closed_days': [],
        'weekend_days': weekend_days,
        'trading_days': trading_days,
        'non_trading_days': non_trading_days,
    }
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    CAL_PATH.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')


def write_trading_calendar_py():
    SCRIPTS.mkdir(parents=True, exist_ok=True)
    code=f'''#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

BASE = Path("/Users/wxo/Desktop/Kronos")
CAL_PATH = BASE / "config" / "cn_a_share_trading_calendar_2026.json"

EXPECTED_SLOTS_603305 = [
  "0930","0940","0950","1000","1010","1020","1030","1040","1050","1100","1110","1120","1130",
  "1300","1310","1320","1330","1340","1350","1400","1410","1420","1430","1440","1450","1500",
]


def _load():
  d=json.loads(CAL_PATH.read_text(encoding='utf-8'))
  return d


def is_trading_day(d: str|date) -> bool:
  ds = d.isoformat() if isinstance(d, date) else str(d)
  cal=_load()
  return ds in set(cal.get("trading_days",[]))


def explain_non_trading_day(d: str|date) -> str:
  ds = d.isoformat() if isinstance(d, date) else str(d)
  cal=_load()
  if ds in set(cal.get('weekend_days', [])):
    return 'non_trading_day_weekend'
  for r in cal.get('holiday_ranges', []):
    if r.get('start') <= ds <= r.get('end'):
      return 'non_trading_day_holiday'
  if ds in set(cal.get('non_trading_days', [])):
    return 'non_trading_day'
  return 'trading_day'


def get_expected_slots(d: str|date) -> list[str]:
  return EXPECTED_SLOTS_603305 if is_trading_day(d) else []


def next_trading_day(d: str|date) -> str:
  cur = d if isinstance(d, date) else date.fromisoformat(str(d))
  cur += timedelta(days=1)
  while not is_trading_day(cur):
    cur += timedelta(days=1)
  return cur.isoformat()


def previous_trading_day(d: str|date) -> str:
  cur = d if isinstance(d, date) else date.fromisoformat(str(d))
  cur -= timedelta(days=1)
  while not is_trading_day(cur):
    cur -= timedelta(days=1)
  return cur.isoformat()
'''
    TC_PATH.write_text(code, encoding='utf-8')


def patch_auto_report_guard():
    p = BASE / 'auto_report_guard_603305.py'
    txt = p.read_text(encoding='utf-8')
    if 'SKIP_NON_TRADING_DAY' in txt:
        return
    # Insert after slot_dt, slot_ts computed line
    needle = 'slot_dt, slot_ts = _slot_ts()'
    insert = '''slot_dt, slot_ts = _slot_ts()

    # Trading calendar gate: skip non-trading day (do NOT run main/shadow, do NOT generate failure)
    try:
        from scripts.trading_calendar import is_trading_day, explain_non_trading_day
        today = slot_dt.strftime('%Y-%m-%d')
        if not is_trading_day(today):
            reason = explain_non_trading_day(today)
            msg = f"status=SKIP_NON_TRADING_DAY\nreason={reason}\ndate={today}"
            (OUTDIR / f'report_{slot_ts}.txt').write_text(msg, encoding='utf-8')
            (OUTDIR / f'check_{slot_ts}.json').write_text(json.dumps({'errors': [], 'status': 'SKIP_NON_TRADING_DAY', 'reason': reason, 'slot_ts': slot_ts}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(msg)
            return
    except Exception:
        pass
'''
    txt = txt.replace(needle, insert)
    p.write_text(txt, encoding='utf-8')


def patch_build_slot_coverage():
    p = BASE / 'scripts' / 'build_slot_coverage_daily.py'
    txt = p.read_text(encoding='utf-8')
    if 'is_trading_day' in txt and 'SKIP_NON_TRADING_DAY' in txt:
        return
    # Near start of main(), after args parsed and d defined
    needle = 'd = args.date'
    insert = '''d = args.date

    # Trading calendar gate
    try:
        from scripts.trading_calendar import is_trading_day, explain_non_trading_day
        dd = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if not is_trading_day(dd):
            reason = explain_non_trading_day(dd)
            out = {
                'date': d,
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'is_trading_day': False,
                'expected_slots': [],
                'slots': [],
                'sample_status': 'non_trading_day',
                'sample_quality_grade': 'N/A',
                'performance_use_allowed': False,
                'reason': reason,
            }
            out_path = GUARD / f"slot_coverage_daily_{d}.json"
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
            md_path = BASE / 'daily_reports' / f"slot_coverage_summary_{d}.md"
            md_path.write_text(f"# slot_coverage_summary {d}\n- is_trading_day: false\n- reason: {reason}\n", encoding='utf-8')
            print(out_path)
            print(md_path)
            return
    except Exception:
        pass
'''
    txt = txt.replace(needle, insert)
    p.write_text(txt, encoding='utf-8')


def patch_regression():
    p = BASE / 'scripts' / 'run_kronos_regression.sh'
    txt = p.read_text(encoding='utf-8')
    if '[Trading calendar]' in txt:
        return
    marker = '# 13) Sample quality gate checks'
    add = r'''
# 12.5) Trading calendar checks
import importlib.util
cal=base/'scripts'/'trading_calendar.py'
if cal.exists():
    spec=importlib.util.spec_from_file_location('trading_calendar', str(cal))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    print('PASS [Trading calendar] 2026-05-22 trading day' if m.is_trading_day('2026-05-22') else 'FAIL [Trading calendar] 2026-05-22 not trading day')
    print('PASS [Trading calendar] 2026-05-01 non-trading' if (not m.is_trading_day('2026-05-01')) else 'FAIL [Trading calendar] 2026-05-01 trading unexpectedly')
    print('PASS [Trading calendar] 2026-05-04 non-trading' if (not m.is_trading_day('2026-05-04')) else 'FAIL [Trading calendar] 2026-05-04 trading unexpectedly')
    print('PASS [Trading calendar] 2026-05-06 trading day' if m.is_trading_day('2026-05-06') else 'FAIL [Trading calendar] 2026-05-06 not trading day')
    # Saturday check (2026-05-02 is Saturday)
    print('PASS [Trading calendar] weekend non-trading' if (not m.is_trading_day('2026-05-02')) else 'FAIL [Trading calendar] weekend trading unexpectedly')
    ok = (m.get_expected_slots('2026-05-01')==[])
    print('PASS [Trading calendar] non-trading expected_slots=0' if ok else 'FAIL [Trading calendar] non-trading expected_slots!=0')
else:
    print('FAIL [Trading calendar] scripts/trading_calendar.py missing')
'''

    if marker in txt:
        txt = txt.replace(marker, add + "\n" + marker)
    else:
        txt += "\n" + add
    p.write_text(txt, encoding='utf-8')


def main():
    build_calendar_2026()
    write_trading_calendar_py()
    patch_auto_report_guard()
    patch_build_slot_coverage()
    patch_regression()

    # smoke check
    subprocess.check_call(['python3','-m','py_compile', str(TC_PATH)])

    # run regression
    cp = subprocess.run(['bash', str(BASE / 'scripts' / 'run_kronos_regression.sh')], capture_output=True, text=True)
    print(cp.stdout)
    if cp.returncode != 0:
        print(cp.stderr)
        raise SystemExit(cp.returncode)


if __name__=='__main__':
    main()
