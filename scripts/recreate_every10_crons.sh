#!/bin/bash
# recreate_every10_crons.sh
# 用途：重建 603305 盘中 every10 模拟任务（全部24个）
# 触发条件：当盘中 every10 因意外丢失时执行此脚本恢复
# 用法：bash recreate_every10_crons.sh
# 依赖：openclaw CLI（需在 PATH 中）

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

echo "[$TIMESTAMP] $SCRIPT_NAME: 开始重建 603305 盘中 every10 cron..."

# 通用参数
PROJECT_ROOT="/Users/wxo/Desktop/Kronos"
MODEL="deepseek/deepseek-v4-flash"
TIMEOUT_SEC=60
DELIVERY_CHANNEL="telegram"
DELIVERY_TO="736532132"
DELIVERY_MODE="announce"
BEST_EFFORT=true

# Prompt 模板
PMT='立即执行并仅返回结果：bash ${PROJECT_ROOT}/scripts/run_with_model_guard.sh --task-name {{NAME}} --jobId {{NAME}} --model \"${OPENCLAW_MODEL:-${MODEL:-}}\" --provider \"${OPENCLAW_PROVIDER:-${PROVIDER:-}}\" -- python3 ${PROJECT_ROOT}/simulate_position_603305.py --mode auto 。要求：原样返回脚本输出，不要二次改写。若失败10秒后自动重试一次。若重试仍失败，返回失败码和时间。'

# 生成消息体（注入 NAME 占位符）
make_msg() {
  local name="$1"
  local msg="${PMT//\{\{NAME\}/$name}"
  echo "$msg"
}

# 早盘时点 09:30 ~ 11:20
MORNING_SLOTS=(
  "0930:30 9"
  "0940:40 9"
  "0950:50 9"
  "1000:0 10"
  "1010:10 10"
  "1020:20 10"
  "1030:30 10"
  "1040:40 10"
  "1050:50 10"
  "1100:0 11"
  "1110:10 11"
  "1120:20 11"
)

# 午盘时点 13:00 ~ 14:50
AFTERNOON_SLOTS=(
  "1300:0 13"
  "1310:10 13"
  "1320:20 13"
  "1330:30 13"
  "1340:40 13"
  "1350:50 13"
  "1400:0 14"
  "1410:10 14"
  "1420:20 14"
  "1430:30 14"
  "1440:40 14"
  "1450:50 14"
)

CREATED=0
SKIPPED=0
FAILED=0

create_one() {
  local slot="$1" minute="$2" hour="$3"
  local name="603305-every10-${slot}"
  local expr="${minute} ${hour} * * 1-5"
  local msg
  msg=$(make_msg "$name")

  # 检查是否已存在
  if openclaw cron list 2>/dev/null | python3 -c "
import json,sys
data = json.load(sys.stdin)
for job in data.get('jobs',[]):
    if job.get('name') == '$name' and job.get('enabled',False):
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
    echo "  ⏭️  $name 已存在且启用，跳过"
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  # 删除旧版（若存在且禁用）
  old_id=$(openclaw cron list 2>/dev/null | python3 -c "
import json,sys
data = json.load(sys.stdin)
for job in data.get('jobs',[]):
    if job.get('name') == '$name':
        print(job.get('id',''))
        sys.exit(0)
print('')
" 2>/dev/null)
  if [ -n "$old_id" ]; then
    openclaw cron remove "$old_id" 2>/dev/null || true
  fi

  # 创建
  if openclaw cron add --json "$(python3 -c "
import json
job = {
    'name': '$name',
    'enabled': True,
    'schedule': {
        'kind': 'cron',
        'expr': '$expr',
        'tz': 'Asia/Shanghai'
    },
    'sessionTarget': 'isolated',
    'payload': {
        'kind': 'agentTurn',
        'message': '''$msg''',
        'model': '$MODEL',
        'timeoutSeconds': $TIMEOUT_SEC
    },
    'delivery': {
        'mode': '$DELIVERY_MODE',
        'channel': '$DELIVERY_CHANNEL',
        'to': '$DELIVERY_TO',
        'bestEffort': $BEST_EFFORT
    }
}
print(json.dumps(job))
")" 2>&1; then
    echo "  ✅ $name (${hour}:${minute}) 创建成功"
    CREATED=$((CREATED + 1))
  else
    echo "  ❌ $name 创建失败"
    FAILED=$((FAILED + 1))
  fi
}

echo ""
echo "--- 早盘 ---"
for slot_entry in "${MORNING_SLOTS[@]}"; do
  slot="${slot_entry%%:*}"
  rest="${slot_entry#*:}"
  minute="${rest% *}"
  hour="${rest#* }"
  create_one "$slot" "$minute" "$hour"
done

echo ""
echo "--- 午盘 ---"
for slot_entry in "${AFTERNOON_SLOTS[@]}"; do
  slot="${slot_entry%%:*}"
  rest="${slot_entry#*:}"
  minute="${rest% *}"
  hour="${rest#* }"
  create_one "$slot" "$minute" "$hour"
done

echo ""
echo "========================================"
echo " 重建完成"
echo " 创建: $CREATED  |  跳过(已存在): $SKIPPED  |  失败: $FAILED"
echo "========================================"
echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] $SCRIPT_NAME: 完成"
