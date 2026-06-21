#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def grade(score: float) -> str:
    if score >= 60:
        return 'strong_bull'
    if score >= 20:
        return 'mild_bull'
    if score <= -60:
        return 'strong_bear'
    if score <= -20:
        return 'mild_bear'
    return 'neutral'

def main() -> int:
    try:
        txt = sys.stdin.read()
        fields = json.loads(txt) if txt.strip() else {}
    except Exception:
        fields = {}

    score = safe_float(fields.get('factor_score'))
    grade_s = fields.get('factor_grade')
    hint = fields.get('factor_hint')
    conflict = bool(fields.get('factor_conflict_with_action'))
    profile = str(fields.get('factor_weight_profile') or 'neutral')

    if score is None:
        score = 0.0
        grade_s = 'neutral'
        hint = 'insufficient_data'
        conflict = False

    score = clamp(float(score), -100.0, 100.0)
    grade_s = str(grade_s or grade(score))
    hint = str(hint or 'insufficient_data')

    out = [
        '[FACTOR_OBSERVER]',
        f'* factor_score={score:.2f}',
        f'* factor_grade={grade_s}',
        f'* factor_hint={hint}',
        f'* factor_conflict_with_action={str(conflict).lower()}',
        f'* factor_weight_profile={profile}',
        '* observer_only=true',
        '* affects_position=false',
    ]
    sys.stdout.write('\n'.join(out) + '\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
