#!/usr/bin/env bash
# ============================================================================
# run_postclose_pipeline_603305_shadow.sh
# Shadow combined postclose runner — 603305
#
# Purpose:
#   Chain-execute the same Python steps as the individual postclose crons,
#   but redirect ALL outputs to guard_outputs/shadow_combined_YYYYMMDD/.
#   Does NOT send Telegram. Does NOT replace the official pipeline.
#
# Outputs: guard_outputs/shadow_combined_YYYYMMDD/
# Source:  shadow_postclose_combined
# Record:  not_for_official_record=true
#
# Usage:
#   bash run_postclose_pipeline_603305_shadow.sh [YYYYMMDD]
#
# Output redirect method:
#   Creates a temp scripts dir with sed'd copies of ALL relevant Python build
#   scripts, then runs them via PYTHONPATH. This ensures that every build_*.py
#   module writes outputs to the shadow dir, regardless of whether the entry
#   point calls runpy, import, or subprocess.
#
# Steps (matches run_postclose_pipeline_603305.sh minus taskq steps):
#   1. build_slot_coverage_daily
#   2. build_error_code_daily
#   3. build_scorecard_daily
#   4. sample_quality_daily (not a shim — standalone)
#   5. build_main_shadow_review_603305
#   6. factor_score_observer_postclose
#   7. build_strategy_param_proposal_603305
# ============================================================================

set -uo pipefail
# NOTE: No set -e. Each step is wrapped so a single failure does not abort
# the rest of the pipeline.

BASE="/Users/wxo/Desktop/Kronos"
DATE_YYYYMMDD="${1:-${DATE_YYYYMMDD:-$(date +%Y%m%d)}}"
RUNDIR="$BASE/scripts"
SHADOW_DIR="$BASE/guard_outputs/shadow_combined_${DATE_YYYYMMDD}"

echo "[shadow_postclose_combined] date=${DATE_YYYYMMDD}"
echo "[shadow_postclose_combined] shadow_dir=${SHADOW_DIR}"
echo "[shadow_postclose_combined] source=shadow_postclose_combined"
echo "[shadow_postclose_combined] does_not_replace_existing_postclose=true"
echo "[shadow_postclose_combined] not_for_official_record=true"

mkdir -p "$SHADOW_DIR"

# ------------------------------------------------------------------
# Prepare sed'd script copies so that all output path references
# (guard_outputs and daily_reports) redirect to the shadow dir.
#
# All entry-point scripts are shims that delegate to build_*.py via
# import, runpy.run_path, or subprocess. The build_*.py files are the
# ones with hardcoded output paths. By sed'ing both entry and build
# scripts and running from PYTHONPATH, we catch all write paths.
# ------------------------------------------------------------------
PREP_DIR=$(mktemp -d) || { echo "[shadow] ERROR: mktemp failed" >&2; exit 1; }

# Scripts needed by the shadow pipeline (entry shims + build scripts)
SHADOW_SCRIPTS=(
  # Entry shim    →  Build script (the actual logic)
  slot_coverage_daily.py    build_slot_coverage_daily.py
  error_code_daily.py       build_error_code_daily.py
  scorecard_daily.py        build_scorecard_daily.py
  sample_quality_daily.py
  main_shadow_review_603305.py  build_main_shadow_review_603305.py
  factor_score_observer_postclose.py
  strategy_param_proposal_603305.py  build_strategy_param_proposal_603305.py
)

echo "[shadow] preparing sed'd scripts in ${PREP_DIR}"
for script in "${SHADOW_SCRIPTS[@]}"; do
  [[ -z "$script" ]] && continue
  src="$RUNDIR/$script"
  dst="$PREP_DIR/$script"
  if [[ -f "$src" ]]; then
    sed \
      -e "s|guard_outputs|guard_outputs/shadow_combined_${DATE_YYYYMMDD}|g" \
      -e "s|daily_reports|guard_outputs/shadow_combined_${DATE_YYYYMMDD}|g" \
      "$src" > "$dst" || {
        echo "[shadow] WARN: sed failed for ${script}" >&2
        cp "$src" "$dst"
      }
  else
    echo "[shadow] WARN: script not found ${script}" >&2
  fi
done

# ------------------------------------------------------------------
# Helper: run a Python step from sed'd copy via PYTHONPATH
# Force the CWD to RUNDIR so any implicit cwd-relative logic works.
# PYTHONPATH prepends before sys.path, so sed'd copies win over originals.
# ------------------------------------------------------------------
run_step() {
  local name="$1"
  local script="$2"
  shift 2

  local entry="$PREP_DIR/$script"
  if [[ ! -f "$entry" ]]; then
    echo "[shadow] ERROR: script not in prep dir: ${script}" >&2
    return 1
  fi

  echo "[shadow] step=${name} script=${script} args=$*"
  cd "$RUNDIR" && PYTHONPATH="$PREP_DIR" python3 "$entry" "$@" || {
    local rc=$?
    echo "[shadow] WARN: step=${name} failed (rc=${rc})" >&2
    return "$rc"
  }
  echo "[shadow] step=${name} OK"
}

# ------------------------------------------------------------------
# Step 1: slot_coverage — run build directly (shim uses runpy.run_path
#         with hardcoded absolute path, bypassing PYTHONPATH)
# ------------------------------------------------------------------
run_step "slot_coverage" "build_slot_coverage_daily.py" "$DATE_YYYYMMDD" || true

# ------------------------------------------------------------------
# Step 2: error_code_daily — run build directly (same reason as step 1)
# ------------------------------------------------------------------
run_step "error_code_daily" "build_error_code_daily.py" "$DATE_YYYYMMDD" || true

# ------------------------------------------------------------------
# Step 3: scorecard_daily — run build directly (shim uses sys.path.insert)
# ------------------------------------------------------------------
run_step "scorecard_daily" "build_scorecard_daily.py" "$DATE_YYYYMMDD" || true

# ------------------------------------------------------------------
# Step 4: sample_quality_daily (standalone, not a shim)
# ------------------------------------------------------------------
run_step "sample_quality" "sample_quality_daily.py" "$DATE_YYYYMMDD" || true

# ------------------------------------------------------------------
# Step 5: main_shadow_review — run build directly (shim uses sys.path.insert)
# ------------------------------------------------------------------
run_step "main_shadow_review" "build_main_shadow_review_603305.py" "$DATE_YYYYMMDD" || true

# ------------------------------------------------------------------
# Step 6: factor_score_observer_postclose
# ------------------------------------------------------------------
run_step "factor_postclose" "factor_score_observer_postclose.py" \
  --date "$DATE_YYYYMMDD" --symbol 603305 --weight-profile conservative || true

# ------------------------------------------------------------------
# Step 7: strategy_param_proposal — run build directly (shim uses sys.path.insert)
# ------------------------------------------------------------------
run_step "strategy_param_proposal" "build_strategy_param_proposal_603305.py" \
  "$DATE_YYYYMMDD" || true

# ------------------------------------------------------------------
# Cleanup and summary
# ------------------------------------------------------------------
rm -rf "$PREP_DIR"

echo "---"
echo "[shadow_postclose_combined] done date=${DATE_YYYYMMDD}"
echo "[shadow_postclose_combined] test the verify outputs by comparing:"
echo "  shadow: ${SHADOW_DIR}/"
echo "  vs"
echo "  originals: ${BASE}/guard_outputs/"
echo "---"
echo "[shadow_postclose_combined] outputs in ${SHADOW_DIR}:"
if ls -la "$SHADOW_DIR" 2>/dev/null; then
  echo "[shadow_postclose_combined] total_output_files=$(ls -1 "$SHADOW_DIR" 2>/dev/null | wc -l)"
else
  echo "[shadow_postclose_combined] WARN: no output files in ${SHADOW_DIR}"
fi
echo "[shadow_postclose_combined] source=shadow_postclose_combined"
echo "[shadow_postclose_combined] does_not_replace_existing_postclose=true"
echo "[shadow_postclose_combined] not_for_official_record=true"
