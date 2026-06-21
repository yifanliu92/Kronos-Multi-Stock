#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
DIR="$BASE/scripts/postclose_pipeline"
TARGET="$DIR/regression_603305.sh"
CLOSE="$DIR/close_stability_summary_603305.sh"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BASE/guard_outputs/repair_regression_eof_603305_${TS}.md"

mkdir -p "$BASE/guard_outputs"

exec > >(tee -a "$OUT") 2>&1

echo "# Repair regression_603305.sh unexpected EOF"
echo "- ts: $(date '+%Y-%m-%d %H:%M:%S')"
echo "- boundary: 不改策略、不补跑、不伪造 report"
echo

echo "## 1) Current syntax check"
if bash -n "$TARGET"; then
  echo "CURRENT_OK: $TARGET"
else
  echo "CURRENT_BROKEN: $TARGET"
fi

echo
echo "## 2) Find latest valid backup"
VALID_BACKUP=""
while IFS= read -r bak; do
  if bash -n "$bak" 2>/dev/null; then
    VALID_BACKUP="$bak"
    break
  fi
done < <(ls -t "$TARGET".bak_* 2>/dev/null || true)

if [[ -z "$VALID_BACKUP" ]]; then
  echo "FAIL: no valid backup found for $TARGET"
  echo
  echo "Recent target tail:"
  nl -ba "$TARGET" | tail -80
  exit 1
fi

echo "VALID_BACKUP=$VALID_BACKUP"

echo
echo "## 3) Restore valid backup"
BROKEN_COPY="$TARGET.broken_${TS}"
cp "$TARGET" "$BROKEN_COPY"
cp "$VALID_BACKUP" "$TARGET"
chmod +x "$TARGET"
echo "BROKEN_COPY=$BROKEN_COPY"
echo "RESTORED_FROM=$VALID_BACKUP"

echo
echo "## 4) Re-apply current postclose gate names"
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

for p in targets:
    print(f"TARGET={p}")
    if not p.exists():
        print(f"FAIL missing: {p}")
        sys.exit(1)

    text = p.read_text(encoding="utf-8", errors="ignore")
    old_text = text
    hits = []

    for old, new in replace_map.items():
        if old in text:
            text = text.replace(old, new)
            hits.append(f"{old} -> {new}")

    if text != old_text:
        bak = p.with_name(p.name + ".gatepatch_bak_" + time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(p, bak)
        p.write_text(text, encoding="utf-8")
        print(f"UPDATED={p}")
        print(f"BACKUP={bak}")
        for h in hits:
            print("  " + h)
    else:
        print("NO_CHANGE")

combined = "\n".join(
    p.read_text(encoding="utf-8", errors="ignore")
    for p in targets
    if p.exists()
)

remaining = [old for old in replace_map if old in combined]
if remaining:
    print("FAIL old gate names remain:")
    for x in remaining:
        print("  " + x)
    sys.exit(1)

print("OK old gate names cleared")
PY

echo
echo "## 5) Verify bash syntax"
bash -n "$TARGET"
bash -n "$CLOSE"
echo "OK bash -n PASS"

echo
echo "## 6) Verify old gate names cleared"
if grep -RInE 'postclose_603305_error_code_daily_1505|postclose_603305_scorecard_daily_1508|postclose_603305_sample_quality_1510|postclose_603305_main_shadow_review_1512|postclose_603305_factor_postclose_1515|postclose_603305_strategy_param_proposal_1518|postclose_603305_chatgpt_handoff_1520|postclose_603305_regression_1525' "$TARGET" "$CLOSE"; then
  echo "FAIL old gate names still found"
  exit 1
else
  echo "OK old gate names not found"
fi

echo
echo "## 7) Output"
echo "$OUT"
echo "RESULT=PASS"
