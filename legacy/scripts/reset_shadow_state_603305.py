#!/usr/bin/env python3
from pathlib import Path
import json, datetime as dt

BASE=Path('/Users/wxo/Desktop/Kronos')
STATE=BASE/'sim_state_603305.json'
MARK=BASE/'shadow_state_603305.json'
now=dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# reset dedicated shadow state
shadow={
  'symbol':'603305',
  'position_pct':0,
  'avg_entry_price':None,
  'entry_time':None,
  'entry_price':None,
  'cumulative_cost':0.0,
  'last_trade':None,
  'updated_at':now,
  'base_capital_cny':1000000
}
MARK.write_text(json.dumps(shadow,ensure_ascii=False,indent=2),encoding='utf-8')

print('reset shadow state done', now)
