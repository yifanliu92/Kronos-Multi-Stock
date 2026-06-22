#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"

echo "[TASK] factor_observer_input_fields_603305 start $(date '+%F %T')"

# 1) Patch auto_report_guard_603305.py to pass richer feature fields into factor_score_observer.py light mode
python3 - <<'PY'
from pathlib import Path
import re
p = Path('/Users/wxo/Desktop/Kronos/auto_report_guard_603305.py')
text = p.read_text(encoding='utf-8')

# We will enrich the `feat` dict right before calling factor_score_observer.py.
# Insert fields from ctx + market snapshot that are already present in this script.
needle = "        # data quality fields best-effort\n        feat['provider_final'] = provider_final"
if needle not in text:
    raise SystemExit('PATCH_POINT_NOT_FOUND: provider_final block')

insert = """        # data quality fields best-effort\n        # --- factor observer input fields (P1) ---\n        try:\n            # market fields (best-effort)\n            feat['price'] = float((ctx or {}).get('price') or (ctx or {}).get('last') or 0) or None\n            feat['prev_close'] = (ctx or {}).get('prev_close')\n            feat['open_price'] = (ctx or {}).get('open')\n            feat['high'] = (ctx or {}).get('high')\n            feat['low'] = (ctx or {}).get('low')\n            feat['pct_change'] = (ctx or {}).get('pct')\n            feat['avg_price'] = (ctx or {}).get('avg_price')\n            feat['vwap_proxy'] = (ctx or {}).get('avg_price')\n\n            # strategy fields\n            feat['signal'] = (ctx or {}).get('signal')\n            feat['action'] = (ctx or {}).get('action')\n            feat['reason'] = (ctx or {}).get('reason')\n            feat['position_from'] = (ctx or {}).get('position_from')\n            feat['position_to'] = (ctx or {}).get('position_to')\n            feat['position_pct'] = (ctx or {}).get('position_to')\n            pos = int((ctx or {}).get('pos', 0) or 0)\n            feat['side'] = 'long' if pos>0 else ('short' if pos<0 else 'flat')\n            feat['full_lock'] = (abs(pos) >= 100)\n        except Exception:\n            pass\n\n        # audit fields\n        feat['timeslot'] = slot_dt.strftime('%H%M')\n        feat['report_file'] = str(OUTDIR / f'report_{slot_ts}.txt')\n        feat['factor_weight_profile'] = 'conservative'\n        feat['observer_only'] = True\n        feat['affects_position'] = False\n\n        feat['provider_final'] = provider_final"""

text2 = text.replace(needle, insert, 1)
p.write_text(text2, encoding='utf-8')
print('patched auto_report_guard_603305.py')
PY

# 2) Patch factor_score_observer.py light mode to compute a lightweight score when fields are present,
#    otherwise return insufficient_data with missing fields list (RC=0 always).
python3 - <<'PY'
from pathlib import Path
import re
p = Path('/Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py')
text = p.read_text(encoding='utf-8')

# Replace current _light_mode with a richer one (idempotent via a marker).
if 'LIGHT_MODE_V2' in text:
    print('factor_score_observer.py already LIGHT_MODE_V2')
    raise SystemExit(0)

pat = re.compile(r"def _light_mode\(txt_in: str, weight_profile: str = 'neutral'\) -> str:[\s\S]*?return json\.dumps\(out, ensure_ascii=False\)\n", re.M)
m = pat.search(text)
if not m:
    raise SystemExit('PATCH_POINT_NOT_FOUND: _light_mode')

replacement = """def _light_mode(txt_in: str, weight_profile: str = 'neutral') -> str:\n    \"\"\"Light mode v2 (LIGHT_MODE_V2): never raises, never blocks trading. Always returns JSON.\n\n    If inputs sufficient, compute lightweight factor_score based on price action + position risk.\n    If insufficient, return factor_hint=insufficient_data and factor_missing_reason=[missing fields].\n    \"\"\"\n    try:\n        fields = json.loads(txt_in) if (txt_in or '').strip() else {}\n        if not isinstance(fields, dict):\n            fields = {}\n    except Exception:\n        fields = {}\n\n    def _f(k):\n        v = fields.get(k)\n        try:\n            return None if v is None else float(v)\n        except Exception:\n            return None\n\n    # required minimal set\n    required = ['price','prev_close','open_price','high','low','pct_change','position_pct','full_lock','action']\n    missing = [k for k in required if fields.get(k) in (None,'')]\n\n    # Base defaults\n    out = {\n        'factor_score': 0.0,\n        'factor_grade': 'neutral',\n        'factor_hint': 'insufficient_data',\n        'factor_missing_reason': missing,\n        'factor_conflict_with_action': False,\n        'factor_weight_profile': str(weight_profile or 'neutral'),\n        'observer_only': True,\n        'affects_position': False,\n    }\n\n    if missing:\n        return json.dumps(out, ensure_ascii=False)\n\n    price = _f('price')\n    prev_close = _f('prev_close')\n    open_price = _f('open_price')\n    high = _f('high')\n    low = _f('low')\n    pct_change = _f('pct_change')\n    pos = int(float(fields.get('position_pct') or 0))\n    full_lock = bool(fields.get('full_lock'))\n    action = str(fields.get('action') or '')\n\n    # lightweight components (clamped into [-100,100])\n    # 1) intraday momentum proxy: pct_change (in %) scaled\n    mom = max(-5.0, min(5.0, float(pct_change))) if pct_change is not None else 0.0\n    mom_score = mom * 10.0  # +/-50\n\n    # 2) range position: where price sits within [low,high]\n    rng = (high - low) if (high is not None and low is not None) else 0.0\n    if rng and price is not None and low is not None:\n        rel = (price - low) / rng  # 0..1\n        rel_score = (rel - 0.5) * 40.0  # +/-20\n    else:\n        rel_score = 0.0\n\n    # 3) position risk penalty when full_lock=true (observer only)\n    risk_pen = -10.0 if full_lock else 0.0\n\n    score = mom_score + rel_score + risk_pen\n    score = max(-100.0, min(100.0, score))\n\n    # grade\n    if score >= 60:\n        grade_s = 'strong_bull'\n    elif score >= 20:\n        grade_s = 'mild_bull'\n    elif score <= -60:\n        grade_s = 'strong_bear'\n    elif score <= -20:\n        grade_s = 'mild_bear'\n    else:\n        grade_s = 'neutral'\n\n    # conflict (very light): if action adds long but score negative, or adds short but score positive\n    conflict = False\n    if ('加仓' in action or '建多' in action) and score < -20:\n        conflict = True\n    if ('加空' in action or '建空' in action) and score > 20:\n        conflict = True\n\n    out.update({\n        'factor_score': float(score),\n        'factor_grade': grade_s,\n        'factor_hint': 'confirm' if not conflict else 'conflict',\n        'factor_missing_reason': [],\n        'factor_conflict_with_action': bool(conflict),\n    })\n    return json.dumps(out, ensure_ascii=False)\n"""

text2 = pat.sub(replacement, text, count=1)
p.write_text(text2, encoding='utf-8')
print('patched factor_score_observer.py _light_mode v2')
PY

# 3) Extend regression gates for factor light mode completeness
python3 - <<'PY'
from pathlib import Path
p = Path('/Users/wxo/Desktop/Kronos/scripts/run_kronos_regression.sh')
text = p.read_text(encoding='utf-8')

marker = 'factor_score_observer light completeness test'
if marker in text:
    print('run_kronos_regression.sh already has completeness test')
    raise SystemExit(0)

# Append after existing light smoke test block (we look for that pass label)
anchor = 'pass "factor_score_observer light smoke test"'
idx = text.find(anchor)
if idx < 0:
    raise SystemExit('PATCH_POINT_NOT_FOUND: light smoke test anchor')

append = """

# --- factor_score_observer light completeness test (should NOT be insufficient_data when fields complete) ---
complete_in='{"price":17.0,"prev_close":16.9,"open_price":17.2,"high":17.5,"low":16.7,"pct_change":0.6,"position_pct":20,"full_lock":false,"action":"持仓不变"}'
comp_out=$(echo "$complete_in" | python3 "$BASE/scripts/factor_score_observer.py" --light-from-json --light-weight-profile conservative 2>>"$LOG" || true)
if echo "$comp_out" | grep -q '"factor_hint"[[:space:]]*:[[:space:]]*"insufficient_data"'; then
  fail "factor_score_observer light completeness test"
  echo "COMPLETE_OUT=$comp_out" | tee -a "$LOG"
else
  pass "factor_score_observer light completeness test"
fi
"""

# insert after the smoke test block by simple concatenation at end (safe)
text2 = text + append
p.write_text(text2, encoding='utf-8')
print('patched run_kronos_regression.sh completeness gate')
PY

# 4) Compile checks (do not run worker here; worker will run full regression)
python3 -m py_compile "$BASE/auto_report_guard_603305.py"
python3 -m py_compile "$BASE/scripts/factor_score_observer.py"
python3 -m py_compile "$BASE/scripts/factor_observer_intraday_light.py"

echo "[TASK] factor_observer_input_fields_603305 done $(date '+%F %T')"
