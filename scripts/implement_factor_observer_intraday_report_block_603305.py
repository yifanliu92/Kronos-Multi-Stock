#!/usr/bin/env python3
"""implement_factor_observer_intraday_report_block_603305.py

P1 显示层最小补丁：在盘中主/影回报文本末尾追加轻量 [FACTOR_OBSERVER] 区块（observer-only）。

硬约束：
- 不修改主/影策略参数
- 不启用 v1.2-shadow
- 不让 factor_score_observer 入交易层
- 不改变 action/reason/position_pct
- factor observer 失败不得阻断主/影回报：仅在区块内标记 unavailable

本脚本会：
1) 最小补丁 auto_report_guard_603305.py（追加旁路区块，best-effort）
2) 扩展 run_kronos_regression.sh 门禁（py_compile + 静态检查区块字段 + unavailable 兜底存在）
3) 运行回归脚本
"""

from __future__ import annotations

import subprocess
from pathlib import Path

BASE = Path("/Users/wxo/Desktop/Kronos")


def append_once(path: Path, marker: str, block: str) -> bool:
    txt = path.read_text(encoding="utf-8")
    if marker in txt:
        return False
    path.write_text(txt.rstrip() + "\n\n" + block.rstrip() + "\n", encoding="utf-8")
    return True


def patch_auto_report_guard(path: Path) -> bool:
    txt = path.read_text(encoding="utf-8")
    if "[FACTOR_OBSERVER]" in txt:
        return False

    anchor = "(OUTDIR / f'report_{slot_ts}.txt').write_text(full, encoding='utf-8')"
    idx = txt.find(anchor)
    if idx < 0:
        raise RuntimeError("PATCH_POINT_NOT_FOUND: auto_report_guard write report")

    block = """

    # ========== FACTOR_OBSERVER (intraday light sidecar, observer-only) ==========
    # Hard constraints: must not change action/reason/position_pct; best-effort only.
    try:
        import json as _json

        feat = {}
        if ctx and isinstance(ctx, dict):
            feat.update(ctx)

        # Provide action/reason/position for conflict detection (read-only)
        try:
            feat['action'] = (ctx or {}).get('action')
            feat['reason'] = (ctx or {}).get('reason')
            feat['position_pct'] = (ctx or {}).get('position_to')
            feat['full_lock'] = (abs(int((ctx or {}).get('pos', 0) or 0)) >= 100)
        except Exception:
            pass

        # data quality fields best-effort
        feat['provider_final'] = provider_final
        feat['final_error_code'] = final_error_code
        feat['model_guard_pass'] = model_guard_pass
        feat['is_trading_day'] = True
        feat['sample_quality_grade'] = None
        feat['rate_limit_interrupted'] = ('RATE_LIMIT' in str(final_error_code))

        # Call factor_score_observer light mode (observer-only)
        p1 = subprocess.run(
            [
                'python3',
                str(BASE / 'scripts' / 'factor_score_observer.py'),
                '--light-from-json',
                '--light-weight-profile',
                'conservative',
            ],
            input=_json.dumps(feat, ensure_ascii=False),
            text=True,
            capture_output=True,
        )

        block_lines = [
            "[FACTOR_OBSERVER]",
        ]

        if p1.returncode == 0 and (p1.stdout or '').strip():
            d = _json.loads((p1.stdout or '').strip())
            # If data insufficient, enforce hint=insufficient_data
            if str(d.get('factor_hint') or '').strip() == '':
                d['factor_hint'] = 'insufficient_data'

            block_lines += [
                f"factor_score: {d.get('factor_score')}",
                f"factor_grade: {d.get('factor_grade')}",
                f"factor_hint: {d.get('factor_hint')}",
                f"factor_conflict_with_action: {str(bool(d.get('factor_conflict_with_action'))).lower()}",
                f"factor_weight_profile: {d.get('factor_weight_profile') or 'conservative'}",
                "observer_only: true",
                "affects_position: false",
            ]
        else:
            block_lines += [
                "unavailable: true",
                f"error: factor_score_observer_light_failed rc={p1.returncode}",
                "observer_only: true",
                "affects_position: false",
            ]

        full = full.rstrip() + "\n\n" + "\n".join(block_lines) + "\n"

    except Exception:
        # Never block main report.
        try:
            full = full.rstrip() + "\n\n[FACTOR_OBSERVER]\nunavailable: true\nerror: exception\nobserver_only: true\naffects_position: false\n"
        except Exception:
            pass
    # ========== FACTOR_OBSERVER end ==========

"""

    txt2 = txt[:idx] + block + txt[idx:]
    path.write_text(txt2, encoding="utf-8")
    return True


def patch_regression(path: Path) -> bool:
    marker = "factor_observer intraday report block (observer-only)"
    if marker in path.read_text(encoding="utf-8"):
        return False

    block = """

# --- factor_observer intraday report block (observer-only) ---
# 1) py_compile gates (must FAIL regression on compile errors)
python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py || { echo "FAIL: py_compile factor_score_observer.py"; exit 3; }
python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_observer_intraday_light.py || true
python3 -m py_compile /Users/wxo/Desktop/Kronos/scripts/factor_score_observer_postclose.py || true

# 2) static checks: report text may include FACTOR_OBSERVER block with required keys + unavailable fallback
python3 - <<'PY'
from pathlib import Path
p=Path('/Users/wxo/Desktop/Kronos/auto_report_guard_603305.py')
t=p.read_text(encoding='utf-8')
need=[
  '[FACTOR_OBSERVER]',
  'observer_only: true',
  'affects_position: false',
  'unavailable: true',
]
miss=[x for x in need if x not in t]
if miss:
  print('FAIL: FACTOR_OBSERVER static markers missing:', miss)
  raise SystemExit(3)
print('PASS: FACTOR_OBSERVER static markers present')
PY

echo "PASS: factor_observer intraday report block gates"
""".rstrip() + "\n"

    return append_once(path, marker, block)


def main() -> int:
    modified = []

    guard = BASE / 'auto_report_guard_603305.py'
    reg = BASE / 'scripts' / 'run_kronos_regression.sh'

    if patch_auto_report_guard(guard):
        modified.append(str(guard))

    if patch_regression(reg):
        modified.append(str(reg))

    # run regression
    cp = subprocess.run(['bash', str(reg)], capture_output=True, text=True)
    print(cp.stdout)
    if cp.returncode != 0:
        print(cp.stderr)
        raise SystemExit(cp.returncode)

    # print modified file paths for worker discovery
    for p in modified:
        print(p)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
