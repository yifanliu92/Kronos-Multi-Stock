#!/bin/zsh
export PATH="$HOME/.npm-global/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd /Users/yifliu/Kronos-603305 || exit 1

ts=$(date "+%Y%m%d_%H%M%S")
log="/Users/yifliu/Kronos-603305/local_cron_logs/local_intraday_603305_${ts}.log"

echo "===== local_intraday_603305 start $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$log"
python3 /Users/yifliu/Kronos-603305/auto_report_guard_603305.py >> "$log" 2>&1
rc=$?
echo "===== local_intraday_603305 end rc=$rc $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$log"
exit $rc
