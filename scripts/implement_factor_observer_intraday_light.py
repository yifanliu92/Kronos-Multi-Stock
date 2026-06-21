#!/usr/bin/env python3
"""implement_factor_observer_intraday_light.py

Observer-only 双层输出落地（603305）：
1) 盘中：在主/影回报文本末尾追加轻量 [FACTOR_OBSERVER] 区块（不改 action/reason/position_pct，不影响交易动作）
2) 盘后：生成完整统计框架脚本 factor_score_observer_postclose.py（仍 observer-only）

硬约束（必须满足）：
- 不修改主策略参数/影子策略参数
- 不启用 v1.2-shadow
- 不让 factor_score_observer 入交易层
- 不改变 action / reason / position_pct
- 不因 factor_score 触发加减仓/回补/做空

实现原则：
- 写文件仅用“行列表拼接”方式（"\n".join(lines)+"\n"）
- 禁止：嵌套三引号、python3 -c 长字符串、shell heredoc

注意：本脚本执行时会修改 Kronos 文件并运行回归脚本 run_kronos_regression.sh。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

BASE = Path("/Users/wxo/Desktop/Kronos")


@dataclass
class ChangeSet:
    added: list[str]
    modified: list[str]


def write_lines(path: Path, lines: list[str], executable: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if executable:
        path.chmod(0o700)
    return not existed


def append_once(path: Path, marker: str, block_lines: list[str]) -> bool:
    txt = path.read_text(encoding="utf-8")
    if marker in txt:
        return False
    add = "\n".join(block_lines).rstrip() + "\n"
    path.write_text(txt.rstrip() + "\n\n" + add, encoding="utf-8")
    return True


def patch_factor_score_observer_light_mode(path: Path) -> bool:
    """最小修改：给 factor_score_observer.py 增加 light mode。

    - 新增 args：--light-from-json / --light-weight-profile
    - light 模式：stdin 读 JSON dict -> 计算因子 -> 输出轻量 JSON（供盘中旁路区块使用）
    """
    txt = path.read_text(encoding="utf-8")
    if "--light-from-json" in txt:
        return False

    insert_point = txt.find('ap.add_argument("--input-jsonl"')
    if insert_point < 0:
        raise RuntimeError("PATCH_POINT_NOT_FOUND: --input-jsonl")

    args_block = (
        'ap.add_argument("--light-from-json", action="store_true", help="read JSON dict from stdin and print compact factor JSON")\n'
        '    ap.add_argument("--light-weight-profile", default="neutral", choices=["conservative","neutral","aggressive_observer"], help="weight profile for light mode")\n    '
    )
    txt2 = txt[:insert_point] + args_block + txt[insert_point:]

    # Replace the first 'args = ap.parse_args()' line with an injected handler.
    m = re.search(r"^\s*args\s*=\s*ap\.parse_args\(\)\s*$", txt2, flags=re.M)
    if not m:
        raise RuntimeError("PATCH_ARGS_NOT_FOUND")

    injected = "\n".join([
        "args = ap.parse_args()",
        "",
        "    if getattr(args, 'light_from_json', False):",
        "        import sys as _sys",
        "        txt_in = _sys.stdin.read()",
        "        print(_light_mode(txt_in, args.light_weight_profile))",
        "        return 0",
    ])

    start, end = m.span()
    txt3 = txt2[:start] + injected + txt2[end:]

    # Append helper function at end
    light_func_lines = [
        "",
        "# --- light mode for intraday sidecar (observer-only) ---",
        "def _light_mode(stdin_text: str, weight_profile: str) -> str:",
        "    import json as _json",
        "    fields = _json.loads(stdin_text) if stdin_text.strip() else {}",
        "    weights_path = BASE / 'config' / 'factor_weights_603305.json'",
        "    weights = load_weights(weights_path, weight_profile)",
        "    if not weight_sum_ok(weights):",
        "        raise SystemExit('WEIGHTS_SUM_NOT_1.0')",
        "    before_pos = fields.get('position_pct')",
        "    fr = compute_factor_score(fields, weights)",
        "    conflict = detect_conflict_with_action(fields, fr.score)",
        "    if not (-100.0 <= float(fr.score) <= 100.0):",
        "        raise SystemExit('FACTOR_SCORE_OUT_OF_RANGE')",
        "    after_pos = fields.get('position_pct')",
        "    if before_pos != after_pos:",
        "        raise SystemExit('OBSERVER_VIOLATION_POSITION_MUTATED')",
        "    hint = 'insufficient_data' if fr.available_ratio < 0.6 else factor_hint(fr.available_ratio, conflict)",
        "    out = {",
        "        'factor_score': float(fr.score),",
        "        'factor_grade': factor_grade(fr.score),",
        "        'factor_hint': hint,",
        "        'factor_conflict_with_action': bool(conflict),",
        "        'factor_weight_profile': weight_profile,",
        "    }",
        "    return _json.dumps(out, ensure_ascii=False)",
        "",
    ]

    txt4 = txt3.rstrip() + "\n" + "\n".join(light_func_lines) + "\n"
    path.write_text(txt4, encoding="utf-8")
    return True


def patch_auto_report_guard_append_factor_block(path: Path) -> bool:
    """最小修改：在 auto_report_guard_603305.py 最终落盘前 append [FACTOR_OBSERVER] 轻量区块。

    要求：
    - 只追加，不改原 action/reason/position_pct
    - best-effort，不允许因子失败导致主报表失败
    """
    txt = path.read_text(encoding="utf-8")
    if "[FACTOR_OBSERVER]" in txt:
        return False

    anchor = "(OUTDIR / f'report_{slot_ts}.txt').write_text(full, encoding='utf-8')"
    idx = txt.find(anchor)
    if idx < 0:
        raise RuntimeError("PATCH_POINT_NOT_FOUND_GUARD")

    block_lines = [
        "    # ========== FACTOR_OBSERVER (intraday light sidecar, observer-only) ==========	",
        "    try:",
        "        feat = {}",
        "        if ctx and isinstance(ctx, dict):",
        "            feat.update(ctx)",
        "        try:",
        "            feat['action'] = (ctx or {}).get('action')",
        "            feat['reason'] = (ctx or {}).get('reason')",
        "            feat['position_pct'] = (ctx or {}).get('position_to')",
        "            feat['full_lock'] = (abs(int((ctx or {}).get('pos', 0) or 0)) >= 100)",
        "        except Exception:",
        "            pass",
        "        feat['provider_final'] = provider_final",
        "        feat['final_error_code'] = final_error_code",
        "        feat['model_guard_pass'] = model_guard_pass",
        "        feat['is_trading_day'] = True",
        "        feat['sample_quality_grade'] = None",
        "        feat['rate_limit_interrupted'] = ('RATE_LIMIT' in str(final_error_code))",
        "",
        "        import json as _json",
        "        p1 = subprocess.run([",
        "            'python3', str(BASE / 'scripts' / 'factor_score_observer.py'),",
        "            '--light-from-json', '--light-weight-profile', 'neutral'",
        "        ], input=_json.dumps(feat, ensure_ascii=False), text=True, capture_output=True)",
        "        if p1.returncode == 0 and (p1.stdout or '').strip():",
        "            feat2 = _json.loads((p1.stdout or '').strip())",
        "            p2 = subprocess.run([",
        "                'python3', str(BASE / 'scripts' / 'factor_observer_intraday_light.py')",
        "            ], input=_json.dumps(feat2, ensure_ascii=False), text=True, capture_output=True)",
        "            if p2.returncode == 0 and (p2.stdout or '').strip():",
        "                full = full.rstrip() + '\\n\\n' + (p2.stdout.strip()) + '\\n'",
        "    except Exception:",
        "        pass",
        "    # ========== FACTOR_OBSERVER end ==========	",
    ]

    txt2 = txt[:idx] + "\n".join(["", ""] + block_lines + ["", ""]) + txt[idx:]
    path.write_text(txt2, encoding="utf-8")
    return True


def factor_observer_intraday_light_lines() -> list[str]:
    return [
        "#!/usr/bin/env python3",
        "from __future__ import annotations",
        "",
        "import json",
        "import sys",
        "",
        "def clamp(x: float, lo: float, hi: float) -> float:",
        "    return max(lo, min(hi, x))",
        "",
        "def safe_float(v):",
        "    try:",
        "        if v is None:",
        "            return None",
        "        return float(v)",
        "    except Exception:",
        "        return None",
        "",
        "def grade(score: float) -> str:",
        "    if score >= 60:",
        "        return 'strong_bull'",
        "    if score >= 20:",
        "        return 'mild_bull'",
        "    if score <= -60:",
        "        return 'strong_bear'",
        "    if score <= -20:",
        "        return 'mild_bear'",
        "    return 'neutral'",
        "",
        "def main() -> int:",
        "    try:",
        "        txt = sys.stdin.read()",
        "        fields = json.loads(txt) if txt.strip() else {}",
        "    except Exception:",
        "        fields = {}",
        "",
        "    score = safe_float(fields.get('factor_score'))",
        "    grade_s = fields.get('factor_grade')",
        "    hint = fields.get('factor_hint')",
        "    conflict = bool(fields.get('factor_conflict_with_action'))",
        "    profile = str(fields.get('factor_weight_profile') or 'neutral')",
        "",
        "    if score is None:",
        "        score = 0.0",
        "        grade_s = 'neutral'",
        "        hint = 'insufficient_data'",
        "        conflict = False",
        "",
        "    score = clamp(float(score), -100.0, 100.0)",
        "    grade_s = str(grade_s or grade(score))",
        "    hint = str(hint or 'insufficient_data')",
        "",
        "    out = [",
        "        '[FACTOR_OBSERVER]',",
        "        f'* factor_score={score:.2f}',",
        "        f'* factor_grade={grade_s}',",
        "        f'* factor_hint={hint}',",
        "        f'* factor_conflict_with_action={str(conflict).lower()}',",
        "        f'* factor_weight_profile={profile}',",
        "        '* observer_only=true',",
        "        '* affects_position=false',",
        "    ]",
        "    sys.stdout.write('\\n'.join(out) + '\\n')",
        "    return 0",
        "",
        "if __name__ == '__main__':",
        "    raise SystemExit(main())",
    ]


def factor_score_observer_postclose_lines() -> list[str]:
    # Framework only; forward-30m relation is placeholder until price series wiring exists.
    return [
        "#!/usr/bin/env python3",
        "from __future__ import annotations",
        "",
        "import argparse",
        "import json",
        "import subprocess",
        "from datetime import datetime",
        "from pathlib import Path",
        "from statistics import mean",
        "",
        "BASE = Path('/Users/wxo/Desktop/Kronos')",
        "",
        "def now_ts() -> str:",
        "    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')",
        "",
        "def load_json(p: Path) -> dict:",
        "    return json.loads(p.read_text(encoding='utf-8'))",
        "",
        "def dump_json(p: Path, d: dict) -> None:",
        "    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')",
        "",
        "def main() -> int:",
        "    ap = argparse.ArgumentParser()",
        "    ap.add_argument('--date', default=datetime.now().strftime('%Y%m%d'))",
        "    ap.add_argument('--symbol', default='603305')",
        "    ap.add_argument('--weight-profile', default='neutral', choices=['conservative','neutral','aggressive_observer'])",
        "    args = ap.parse_args()",
        "",
        "    cp = subprocess.run([",
        "        'python3', str(BASE/'scripts'/'factor_score_observer.py'),",
        "        '--date', args.date, '--symbol', args.symbol, '--weight-profile', args.weight_profile",
        "    ], capture_output=True, text=True)",
        "    if cp.returncode != 0:",
        "        raise SystemExit((cp.stdout or '') + '\\n' + (cp.stderr or ''))",
        "",
        "    out_json = BASE/'guard_outputs'/f'factor_score_observer_{args.date}.json'",
        "    out_md = BASE/'daily_reports'/f'factor_score_observer_{args.date}.md'",
        "",
        "    data = load_json(out_json)",
        "    items = data.get('items') or []",
        "",
        "    hint_counts = {'confirm':0,'conflict':0,'caution':0,'insufficient_data':0}",
        "    grade_counts = {'strong_bull':0,'mild_bull':0,'neutral':0,'mild_bear':0,'strong_bear':0}",
        "    avail = []",
        "",
        "    sample_grade = None",
        "    if items:",
        "        gs = [str(x.get('sample_quality_grade') or '').upper() for x in items if x.get('sample_quality_grade')]",
        "        if gs:",
        "            sample_grade = 'D' if 'D' in gs else ('C' if 'C' in gs else gs[0])",
        "",
        "    allow = True if sample_grade in ('A','B') else (False if sample_grade in ('C','D') else None)",
        "",
        "    for x in items:",
        "        h = str(x.get('factor_hint') or 'insufficient_data')",
        "        if h in hint_counts:",
        "            hint_counts[h] += 1",
        "        else:",
        "            hint_counts['caution'] += 1",
        "        g = str(x.get('factor_grade') or 'neutral')",
        "        if g in grade_counts:",
        "            grade_counts[g] += 1",
        "        try:",
        "            avail.append(float(x.get('factor_available_ratio'))) ",
        "        except Exception:",
        "            pass",
        "",
        "    forward_30m = 'TODO(best-effort): compute when intraday forward return fields exist'",
        "",
        "    data['daily_summary'] = {",
        "        'generated_at': now_ts(),",
        "        'symbol': args.symbol,",
        "        'date': args.date,",
        "        'weight_profile': args.weight_profile,",
        "        'sample_quality_grade': sample_grade,",
        "        'allow_factor_efficacy_judgement': allow,",
        "        'hint_counts': hint_counts,",
        "        'grade_counts': grade_counts,",
        "        'factor_score_forward_30m_relationship': forward_30m,",
        "        'can_judge_efficacy': allow,",
        "    }",
        "    dump_json(out_json, data)",
        "",
        "    lines = []",
        "    lines.append(f'# factor_score_observer_603305 post-close ({args.date})')",
        "    lines.append('')",
        "    lines.append(f\"- sample_quality_grade: {sample_grade or 'N/A'}\")",
        "    lines.append(f\"- allow_factor_efficacy_judgement: {str(allow).lower() if allow is not None else 'N/A'}\")",
        "    lines.append('')",
        "    lines.append('## Hint counts')",
        "    for k,v in hint_counts.items():",
        "        lines.append(f'- {k}: {v}')",
        "    lines.append('')",
        "    lines.append('## Grade counts')",
        "    for k,v in grade_counts.items():",
        "        lines.append(f'- {k}: {v}')",
        "    lines.append('')",
        "    lines.append('## factor_score vs forward 30m return')",
        "    lines.append(f'- {forward_30m}')",
        "    lines.append('')",
        "    lines.append('## Constraints')",
        "    lines.append('- observer_only: true')",
        "    lines.append('- affects_position: false')",
        "    out_md.parent.mkdir(parents=True, exist_ok=True)",
        "    out_md.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')",
        "    print(str(out_json))",
        "    print(str(out_md))",
        "    return 0",
        "",
        "if __name__ == '__main__':",
        "    raise SystemExit(main())",
    ]


def patch_regression_gates(path: Path) -> bool:
    marker = "factor_observer intraday light + postclose gates (observer-only)"
    block_lines = [
        "# --- factor_observer intraday light + postclose gates (observer-only) ---",
        'if [ ! -f "/Users/wxo/Desktop/Kronos/scripts/factor_observer_intraday_light.py" ]; then',
        '  echo "FAIL: missing scripts/factor_observer_intraday_light.py"; exit 3',
        "fi",
        'if [ ! -f "/Users/wxo/Desktop/Kronos/scripts/factor_score_observer_postclose.py" ]; then',
        '  echo "FAIL: missing scripts/factor_score_observer_postclose.py"; exit 3',
        "fi",
        'python3 -c "import pathlib; p=pathlib.Path(\'/Users/wxo/Desktop/Kronos/scripts/factor_score_observer.py\'); t=p.read_text(encoding=\'utf-8\'); import sys; sys.exit(3) if \'--light-from-json\' not in t else print(\'PASS: factor_score_observer light mode present\')"',
        'echo "PASS: factor_observer intraday/postclose gates"',
    ]
    return append_once(path, marker, block_lines)


def main() -> int:
    added: list[str] = []
    modified: list[str] = []

    # 1) add intraday light script
    p_light = BASE / "scripts" / "factor_observer_intraday_light.py"
    if write_lines(p_light, factor_observer_intraday_light_lines(), executable=True):
        added.append(str(p_light))
    else:
        modified.append(str(p_light))

    # 2) add postclose framework
    p_post = BASE / "scripts" / "factor_score_observer_postclose.py"
    if write_lines(p_post, factor_score_observer_postclose_lines(), executable=True):
        added.append(str(p_post))
    else:
        modified.append(str(p_post))

    # 3) patch factor_score_observer.py (light mode)
    p_obs = BASE / "scripts" / "factor_score_observer.py"
    if patch_factor_score_observer_light_mode(p_obs):
        modified.append(str(p_obs))

    # 4) patch report formatting (append FACTOR_OBSERVER block)
    p_guard = BASE / "auto_report_guard_603305.py"
    if patch_auto_report_guard_append_factor_block(p_guard):
        modified.append(str(p_guard))

    # 5) patch regression gates
    p_reg = BASE / "scripts" / "run_kronos_regression.sh"
    if patch_regression_gates(p_reg):
        modified.append(str(p_reg))

    # 6) run regression
    cp = subprocess.run(["bash", str(p_reg)], capture_output=True, text=True)
    print(cp.stdout)
    if cp.returncode != 0:
        print(cp.stderr)
        raise SystemExit(cp.returncode)

    # Print file paths for task_worker output discovery
    for p in added + modified:
        print(p)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
