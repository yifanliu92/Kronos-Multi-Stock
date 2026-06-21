#!/bin/bash
# kronos_session_cleanup.sh
# 按预算清理旧 session
# 使用: bash kronos_session_cleanup.sh [days] [max_mb]
#
# 默认: 保留最近 7 天, 总大小不超过 200 MB
set -euo pipefail

DAYS="${1:-7}"
MAX_MB="${2:-200}"
SESSION_DIR="$HOME/.openclaw/agents"
LOG="/Users/wxo/Desktop/Kronos/router_logs/session_cleanup.log"
NOW=$(date +%s)
CUTOFF=$((NOW - DAYS * 86400))

log() {
    mkdir -p "$(dirname "$LOG")"
    echo "$(date '+%F %T') $*" >> "$LOG"
}

echo "===== Session Cleanup $(date '+%F %T') ====="
echo "保留最近 ${DAYS} 天, 最大 ${MAX_MB} MB"
log "start days=${DAYS} max_mb=${MAX_MB}"

for AGENT in main reviewer codex; do
    SDIR="$SESSION_DIR/$AGENT/sessions"
    [ -d "$SDIR" ] || continue

    # 统计当前大小
    SIZE_MB=$(du -sm "$SDIR" 2>/dev/null | awk '{print $1}')
    echo "Agent $AGENT: ${SIZE_MB}MB / ${MAX_MB}MB 预算"

    # 按 mtime 清理过旧的 session 文件
    while IFS= read -r -d '' f; do
        MTIME=$(stat -f "%m" "$f" 2>/dev/null || echo "0")
        if [ "$MTIME" -lt "$CUTOFF" ]; then
            rm -f "$f" 2>/dev/null || true
            log "cleanup_old $AGENT $(basename "$f")"
        fi
    done < <(find "$SDIR" -name "*.jsonl" -o -name "*.json" 2>/dev/null -print0)

    # 如果仍然超过预算, 从最旧的文件开始继续清理
    while true; do
        SIZE_MB=$(du -sm "$SDIR" 2>/dev/null | awk '{print $1}')
        [ "${SIZE_MB:-0}" -le "$MAX_MB" ] && break

        OLDEST=$(find "$SDIR" \( -name "*.jsonl" -o -name "*.json" \) -type f -print0 \
            | xargs -0 ls -t 2>/dev/null | tail -1)
        [ -z "$OLDEST" ] && break

        rm -f "$OLDEST" 2>/dev/null || true
        log "cleanup_budget $AGENT $(basename "$OLDEST")"
    done

    FINAL_MB=$(du -sm "$SDIR" 2>/dev/null | awk '{print $1}')
    echo "  → 清理后: ${FINAL_MB:-0}MB"
done

echo "===== Done ====="
