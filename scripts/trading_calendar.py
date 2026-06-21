#!/usr/bin/env python3
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
