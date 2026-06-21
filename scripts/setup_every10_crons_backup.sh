#!/bin/bash
# 重建24个 every10 cron（备用，创建后默认disabled）
# 说"恢复cron"时我执行：bash this_script.sh enable

ACTION="${1:-create}"  # create 或 enable

if [ "$ACTION" = "enable" ]; then
  echo "=== 启用全部24个 every10 cron ==="
  openclaw cron list 2>/dev/null | awk 'NR>2' | grep "603305-every10-" | while read line; do
    uid=$(echo "$line" | awk '{print $1}')
    name=$(echo "$line" | awk '{print $3}')
    openclaw cron update "$uid" --enabled=true 2>/dev/null
    echo "  enabled: $name"
  done
  echo "done"
  exit 0
fi

# ─── Create mode ───

MODEL="deepseek/deepseek-v4-flash"
MSG_PREFIX="立即执行并仅返回结果：bash /Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh --task-name JOBNAME --jobId JOBNAME -- python3 /Users/wxo/Desktop/Kronos/simulate_position_603305.py --mode auto 。要求：原样返回脚本输出，不要二次改写。若失败10秒后自动重试一次。若重试仍失败，返回失败码和时间。"

add_cron() {
  local name="$1" expr="$2"
  local msg="${MSG_PREFIX//JOBNAME/$name}"
  openclaw cron add --name "$name" --cron "$expr" --tz "Asia/Shanghai" --session isolated --model "$MODEL" --timeout-seconds 60 --announce --to "736532132" --message "$msg" 2>/dev/null | grep -c '"ok": true\|"id":' >/dev/null
  if [ $? -eq 0 ]; then
    echo "  + $name  ($expr)"
  else
    echo "  ! $name  FAILED"
  fi
}

echo "=== 创建盘中每10分钟模拟任务 (24个) ==="

# 早盘 09:30-09:50
for m in 30 40 50; do add_cron "603305-every10-09$m" "$m 9 * * 1-5"; done

# 早盘 10:00-10:50
for m in 00 10 20 30 40 50; do add_cron "603305-every10-10$m" "$m 10 * * 1-5"; done

# 早盘 11:00-11:20
for m in 00 10 20; do add_cron "603305-every10-11$m" "$m 11 * * 1-5"; done

# 午盘 13:00-14:50
for h in 13 14; do for m in 00 10 20 30 40 50; do add_cron "603305-every10-$h$m" "$m $h * * 1-5"; done; done

echo ""
echo "=== 创建完成，现在禁用全部（备用） ==="
openclaw cron list 2>/dev/null | awk 'NR>2' | grep "603305-every10-" | while read line; do
  uid=$(echo "$line" | awk '{print $1}')
  name=$(echo "$line" | awk '{print $3}')
  openclaw cron update "$uid" --enabled=false 2>/dev/null
  echo "  disabled: $name"
done

echo ""
echo "=== 校验 ==="
total=$(openclaw cron list 2>/dev/null | awk 'NR>2' | grep "603305-every10-" | wc -l | tr -d ' ')
echo "在列: $total 个 (全部disabled备用)"
