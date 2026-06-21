#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BASE/guard_outputs/p1_postclose_gate_patch_${TS}.md"

mkdir -p "$BASE/guard_outputs"

exec > >(tee -a "$OUT") 2>&1

echo "# P1 postclose gate patch 603305"
echo "- ts: $(date '+%Y-%m-%d %H:%M:%S')"
echo "- boundary: 不改策略、不补跑、不伪造 report"
echo

echo "## 1) Patch old postclose cron gate names"
python3 - <<'PY'
from pathlib import Path
import shutil, time, sys

base = Path("/Users/wxo/Desktop/Kronos")
targets = [
    base / "scripts/postclose_pipeline/regression_603305.sh",
    base / "scripts/postclose_pipeline/close_stability_summary_603305.sh",
]

replace_map = {
    "postclose_603305_error_code_daily_1505": "postclose_603305_error_code_daily_1507",
    "postclose_603305_scorecard_daily_1508": "postclose_603305_scorecard_daily_1510",
    "postclose_603305_sample_quality_1510": "postclose_603305_sample_quality_1516",
    "postclose_603305_main_shadow_review_1512": "postclose_603305_main_shadow_review_1518",
    "postclose_603305_factor_postclose_1515": "postclose_603305_factor_postclose_1520",
    "postclose_603305_strategy_param_proposal_1518": "postclose_603305_strategy_param_proposal_1522",
    "postclose_603305_chatgpt_handoff_1520": "postclose_603305_chatgpt_handoff_1524",
    "postclose_603305_regression_1525": "postclose_603305_regression_1526",
}

failed = False
for p in targets:
    print(f"TARGET: {p}")
    if not p.exists():
        print(f"FAIL missing file: {p}")
        failed = True
        continue

    text = p.read_text(encoding="utf-8", errors="ignore")
    original = text

    hits = []
    for old, new in replace_map.items():
        if old in text:
            text = text.replace(old, new)
            hits.append(f"{old} -> {new}")

    if text != original:
        bak = p.with_name(p.name + ".bak_" + time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(p, bak)
        p.write_text(text, encoding="utf-8")
        print(f"UPDATED: {p}")
        print(f"BACKUP: {bak}")
        for h in hits:
            print(f"  - {h}")
    else:
        print("NO_CHANGE: no old gate names found in this file")

combined = "\n".join(
    p.read_text(encoding="utf-8", errors="ignore")
    for p in targets
    if p.exists()
)

remaining = [old for old in replace_map if old in combined]
if remaining:
    print("FAIL old gate names still remain:")
    for x in remaining:
        print(f"  - {x}")
    failed = True
else:
    print("OK old gate names cleared from target files")

present_new = [new for new in replace_map.values() if new in combined]
print("NEW gate names present:")
for x in present_new:
    print(f"  - {x}")

if failed:
    sys.exit(1)
PY

echo
echo "## 2) Verify bash syntax"
bash -n "$BASE/scripts/postclose_pipeline/regression_603305.sh"
bash -n "$BASE/scripts/postclose_pipeline/close_stability_summary_603305.sh"
echo "OK bash -n PASS"

echo
echo "## 3) Verify shim python compile"
python3 -m py_compile \
  "$BASE/scripts/slot_coverage_daily.py" \
  "$BASE/scripts/error_code_daily.py" \
  "$BASE/scripts/scorecard_daily.py" \
  "$BASE/scripts/sample_quality_daily.py" \
  "$BASE/scripts/main_shadow_review_603305.py" \
  "$BASE/scripts/strategy_param_proposal_603305.py"
echo "OK py_compile PASS"

echo
echo "## 4) Final grep old gate names"
if grep -RInE 'postclose_603305_error_code_daily_1505|postclose_603305_scorecard_daily_1508|postclose_603305_sample_quality_1510|postclose_603305_main_shadow_review_1512|postclose_603305_factor_postclose_1515|postclose_603305_strategy_param_proposal_1518|postclose_603305_chatgpt_handoff_1520|postclose_603305_regression_1525' \
  "$BASE/scripts/postclose_pipeline/regression_603305.sh" \
  "$BASE/scripts/postclose_pipeline/close_stability_summary_603305.sh"
then
  echo "FAIL old gate names still found"
  exit 1
else
  echo "OK old gate names not found"
fi

echo
echo "## 5) Output"
echo "$OUT"
echo
echo "RESULT=PASS"
