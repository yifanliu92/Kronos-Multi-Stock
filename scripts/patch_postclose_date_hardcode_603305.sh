#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/wxo/Desktop/Kronos"
DIR="$BASE/scripts/postclose_pipeline"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BASE/guard_outputs/patch_postclose_date_hardcode_603305_${TS}.md"

mkdir -p "$BASE/guard_outputs"

exec > >(tee -a "$OUT") 2>&1

echo "# Patch postclose date hardcode 603305"
echo "- ts: $(date '+%Y-%m-%d %H:%M:%S')"
echo "- mode: patch active postclose wrappers"
echo "- boundary: 不改策略、不改 cron、不补跑、不生成正式交易 report"
echo

python3 - <<'PY'
from pathlib import Path
import shutil
import time
import re

base = Path("/Users/wxo/Desktop/Kronos")
d = base / "scripts" / "postclose_pipeline"
ts = time.strftime("%Y%m%d_%H%M%S")

files = sorted([
    p for p in d.glob("*.sh")
    if ".bak_" not in p.name
    and ".broken_" not in p.name
    and ".fix_" not in p.name
    and ".gatepatch_bak_" not in p.name
])

changed = []

def ensure_date_var(text: str) -> str:
    if "DATE_YYYYMMDD=" in text:
        return text

    lines = text.splitlines()
    out = []
    inserted = False

    for line in lines:
        out.append(line)
        if not inserted and line.startswith("BASE="):
            out.append('DATE_YYYYMMDD="${1:-$(date +%Y%m%d)}"')
            inserted = True

    if not inserted:
        # fallback: after set -euo pipefail
        out = []
        inserted2 = False
        for line in lines:
            out.append(line)
            if not inserted2 and "set -euo pipefail" in line:
                out.append('DATE_YYYYMMDD="${1:-$(date +%Y%m%d)}"')
                inserted2 = True
        if not inserted2:
            out.insert(0, 'DATE_YYYYMMDD="${1:-$(date +%Y%m%d)}"')

    return "\n".join(out) + "\n"

for p in files:
    text = p.read_text(encoding="utf-8", errors="ignore")
    original = text

    if "20260525" not in text:
        continue

    text = ensure_date_var(text)

    # Replace quoted date args first.
    text = text.replace('"20260525"', '"${DATE_YYYYMMDD}"')
    text = text.replace("'20260525'", '"${DATE_YYYYMMDD}"')

    # Replace remaining bare 20260525 only when still present.
    text = text.replace("20260525", "${DATE_YYYYMMDD}")

    if text != original:
        bak = p.with_name(p.name + f".bak_{ts}")
        shutil.copy2(p, bak)
        p.write_text(text, encoding="utf-8")
        changed.append((str(p), str(bak)))

print("Changed files:")
if not changed:
    print("  - none")
else:
    for p, bak in changed:
        print(f"  - {p}")
        print(f"    backup={bak}")

# Verify no active wrapper still contains 20260525.
remaining = []
for p in files:
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if "20260525" in txt:
        remaining.append(str(p))

if remaining:
    print("FAIL: active wrappers still contain 20260525")
    for x in remaining:
        print("  - " + x)
    raise SystemExit(1)

print("OK: active postclose wrappers contain no hardcoded 20260525")
PY

echo
echo "## bash -n active postclose wrappers"
FAIL=0
for f in "$DIR"/*.sh; do
  case "$f" in
    *.bak_*|*.broken_*|*.fix_*|*.gatepatch_bak_*) continue ;;
  esac
  if bash -n "$f"; then
    echo "OK bash -n: $f"
  else
    echo "FAIL bash -n: $f"
    FAIL=1
  fi
done

echo
echo "## final grep active wrappers"
if grep -RIn --exclude='*.bak*' --exclude='*.broken_*' --exclude='*.fix_*' --exclude='*.gatepatch_bak_*' "20260525" "$DIR"/*.sh 2>/dev/null; then
  echo "FAIL: 20260525 still found in active wrappers"
  FAIL=1
else
  echo "OK: no 20260525 in active wrappers"
fi

echo
echo "## output"
echo "$OUT"

if [[ "$FAIL" -eq 0 ]]; then
  echo "RESULT=PASS"
else
  echo "RESULT=FAIL"
  exit 1
fi
