#!/bin/zsh
export PATH="$HOME/.npm-global/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd /Users/wxo/Desktop/Kronos || exit 1

ts=$(date "+%Y%m%d_%H%M%S")
log="/Users/wxo/Desktop/Kronos/local_cron_logs/local_intraday_603305_${ts}.log"

echo "===== local_intraday_603305 start $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$log"
python3 /Users/wxo/Desktop/Kronos/auto_report_guard_603305.py >> "$log" 2>&1
rc=$?
echo "===== local_intraday_603305 end rc=$rc $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$log"
exit $rc
