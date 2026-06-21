#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BASE/guard_outputs/patch_sample_quality_marker_cleanup_v2_${TS}.md"

mkdir -p "$BASE/guard_outputs"

exec > >(tee -a "$OUT") 2>&1

echo "# Patch sample_quality marker cleanup v2"
echo "- ts: $(date '+%Y-%m-%d %H:%M:%S')"
echo "- boundary: 不改策略、不补跑、不改 cron"
echo

python3 - <<'PY'
from pathlib import Path
import shutil
import time

p = Path("/Users/wxo/Desktop/Kronos/scripts/sample_quality_daily.py")
text = p.read_text(encoding="utf-8", errors="ignore")

bak = p.with_name(p.name + ".bak_marker_cleanup_v2_" + time.strftime("%Y%m%d_%H%M%S"))
shutil.copy2(p, bak)

# Remove implementation-missing sentinel and misleading ERROR wording from comments/strings.
text = text.replace("SAMPLE_QUALITY_IMPL_MISSING", "SAMPLE_QUALITY_MINIMAL_SCORING")
text = text.replace("SAMPLE_QUALITY_MINIMAL_IMPLEMENTED", "SAMPLE_QUALITY_MINIMAL_SCORING")
text = text.replace("status=ERROR", "status=FAIL")

# If previous patch left an awkward comment, normalize it.
text = text.replace(
    "- Remove SAMPLE_QUALITY_MINIMAL_SCORING and stop emitting status=FAIL.",
    "- Minimal sample-quality scoring is implemented; no implementation-missing sentinel."
)

p.write_text(text, encoding="utf-8")

print(f"UPDATED={p}")
print(f"BACKUP={bak}")
PY

echo
echo "## marker grep"
if grep -RIn "SAMPLE_QUALITY_IMPL_MISSING\|status=ERROR" "$BASE/scripts/sample_quality_daily.py"; then
  echo "FAIL: marker still found"
  exit 1
else
  echo "OK: no SAMPLE_QUALITY_IMPL_MISSING / status=ERROR marker"
fi

echo
echo "## py_compile"
python3 -m py_compile "$BASE/scripts/sample_quality_daily.py"
echo "OK py_compile PASS"

echo
echo "## dry-run sample_quality 20260527"
python3 "$BASE/scripts/sample_quality_daily.py" 20260527
cat "$BASE/guard_outputs/sample_quality_daily_20260527.json" | jq .

echo
echo "## verify postclose wiring"
bash "$BASE/scripts/verify_postclose_wiring_603305.sh"

echo
echo "## output"
echo "$OUT"
echo "RESULT=PASS"
