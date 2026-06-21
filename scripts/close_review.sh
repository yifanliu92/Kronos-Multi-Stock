#!/bin/bash
# 收盘后自动执行：摘要生成 + 优势监控
cd /Users/wxo/Desktop/Kronos || exit 1

# P1.1: model allowlist guard
python3 scripts/model_allowlist_guard.py --task-name close_review --jobId "${OPENCLAW_CRON_JOB_ID:-${JOB_ID:-}}" --model "${OPENCLAW_MODEL:-${MODEL:-}}" --provider "${OPENCLAW_PROVIDER:-${PROVIDER:-}}" >/dev/null || true

python3 scripts/daily_summary_603305.py
python3 scripts/advantage_watch.py

echo "收盘复盘完成"
