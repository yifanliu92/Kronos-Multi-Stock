#!/usr/bin/env bash
set -uo pipefail

if [[ $# -lt 3 || "${2:-}" != "--" ]]; then
  echo "usage: $0 <job_name> -- <command> [args...]" >&2
  exit 64
fi

job_name="$1"
shift 2

safe_job="$(printf '%s' "$job_name" | tr -c 'A-Za-z0-9_.-' '_')"
ts="$(date '+%Y%m%d_%H%M%S')"
out_dir="/Users/wxo/Desktop/Kronos/cron_delivery_outputs"
out_file="${out_dir}/${safe_job}_${ts}.txt"
sender="/Users/wxo/openclaw-run/send_to_telegram.py"

mkdir -p "$out_dir"

{
  echo "job=${job_name}"
  echo "time=$(date '+%F %T %Z')"
  echo "command=$*"
  echo
  echo "----- output -----"
} > "$out_file"

"$@" >> "$out_file" 2>&1
cmd_rc=$?

{
  echo
  echo "----- exit -----"
  echo "exit_code=${cmd_rc}"
} >> "$out_file"

echo "CRON_DELIVERY_OUTPUT=${out_file}"
cat "$out_file"

if [[ "${CRON_TELEGRAM_DELIVERY_DRY_RUN:-0}" == "1" ]]; then
  echo "CRON_TELEGRAM_DELIVERY_DRY_RUN=1; skipped Telegram send"
  exit "$cmd_rc"
fi

python3 "$sender" --text "$out_file"
send_rc=$?
if [[ "$send_rc" -ne 0 ]]; then
  echo "CRON_TELEGRAM_DELIVERY_FAILED sender_exit=${send_rc}" >&2
  exit "$send_rc"
fi

exit "$cmd_rc"
