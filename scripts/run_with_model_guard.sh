#!/usr/bin/env bash
set -euo pipefail

# Unified execution entry for Kronos cron jobs.
# Usage:
#   bash run_with_model_guard.sh --task-name <name> --jobId <id> --model <model> --provider <provider> -- <cmd...>
# Behavior:
# - Always records a guard entry (allowlist_pass true/false)
# - If allowlist_pass=true: executes original command
# - If allowlist_pass=false: DOES NOT run original command; attempts exactly one fallback execution under model=deepseek/deepseek-v4-flash
#   via model_allowlist_guard.py --run-cmd ...

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD_PY="$SCRIPT_DIR/model_allowlist_guard.py"

TASK_NAME="${TASK_NAME:-}"
JOB_ID="${JOB_ID:-}"
MODEL="${MODEL:-}"
PROVIDER="${PROVIDER:-}"

# parse args until --
while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-name) TASK_NAME="$2"; shift 2;;
    --jobId) JOB_ID="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --provider) PROVIDER="$2"; shift 2;;
    --) shift; break;;
    *) echo "[run_with_model_guard] unknown arg: $1" >&2; exit 2;;
  esac
done

# Defaults (must not block execution due to missing metadata)
TASK_NAME=${TASK_NAME:-unknown_task}
PROVIDER=${PROVIDER:-deepseek}
MODEL=${MODEL:-deepseek/deepseek-v4-flash}
JOB_ID=${JOB_ID:-unknown_job}


if [[ $# -lt 1 ]]; then
  echo "[run_with_model_guard] missing command after --" >&2
  exit 2
fi

CMD=("$@")

# Rate-limit protection gate (P0 always allowed; P1/P2 blocked when protection_mode=true)
set +e
python3 "$SCRIPT_DIR/rate_limit_guard.py" --check --task-name "$TASK_NAME" --jobId "$JOB_ID" >/dev/null 2>&1
RATE_RC=$?
set -e

if [[ "$RATE_RC" == "11" ]]; then
  # Blocked: do not run command, do not call model. Evidence already written by rate_limit_guard.py
  echo "[RATE_LIMIT_GUARD] blocked task_name=$TASK_NAME jobId=$JOB_ID reason=RATE_LIMIT_PROTECTION"
  exit 11
fi

# Decide allowlist without recording (fail-closed):
# we intentionally avoid a first "check-only" record so that blocked cases produce a single entry
# with fallback_attempted=true (no ambiguous half-records).
ALLOW=$(python3 - "$MODEL" <<'PY'
import sys
m=(sys.argv[1] or '').strip()
allowed={'deepseek/deepseek-v4-flash'}
print('1' if (not m or m in allowed) else '0')
PY
)

if [[ "$ALLOW" == "1" ]]; then
  # record allowlist pass, then run
  python3 "$GUARD_PY" --task-name "$TASK_NAME" --jobId "$JOB_ID" --model "$MODEL" --provider "$PROVIDER" >/dev/null || true
  "${CMD[@]}"
fi

# blocked -> single guard record + exactly one fallback attempt inside guard; original command never runs under blocked model
python3 "$GUARD_PY" --task-name "$TASK_NAME" --jobId "$JOB_ID" --model "$MODEL" --provider "$PROVIDER" --run-cmd "${CMD[@]}"
exit $?
