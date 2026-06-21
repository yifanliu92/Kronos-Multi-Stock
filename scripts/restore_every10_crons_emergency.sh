#!/bin/bash
# 恢复24个 every10 cron（emergency 备案）
# 用于自循环脚本异常时一键切回旧的 cron 模式
# 用法: bash /Users/wxo/Desktop/Kronos/scripts/restore_every10_crons_emergency.sh

set -e

MODEL="deepseek/deepseek-v4-flash"
SHELL_CMD="bash /Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh"

# 早盘 09:30-11:20
for m in 30 40 50 00 10 20; do
  h=9
  [[ $m -ge 00 ]] && h=10
  name="603305-every10-$h$m"
  expr="$m $h * * 1-5"
  msg="立即执行并仅返回结果：$SHELL_CMD --task-name $name --jobId $name --model \"\${OPENCLAW_MODEL:-\${MODEL:-}}\" --provider \"\${OPENCLAW_PROVIDER:-\${PROVIDER:-}}\" -- python3 /Users/wxo/Desktop/Kronos/simulate_position_603305.py --mode auto 。要求：原样返回脚本输出，不要二次改写。若失败10秒后自动重试一次。若重试仍失败，返回失败码和时间。"

  openclaw cron add --name "$name" --schedule-cron "$expr" --schedule-tz "Asia/Shanghai" --session-target isolated --payload agentTurn --message "$msg" --model "$MODEL" --timeout-seconds 60 --delivery-mode announce --delivery-channel telegram --delivery-to "736532132" --enable 2>/dev/null
  echo "Created: $name ($expr)"
done

# 早盘 11:00-11:20
for m in 00 10 20; do
  name="603305-every10-11$m"
  expr="$m 11 * * 1-5"
  msg="立即执行并仅返回结果：$SHELL_CMD --task-name $name --jobId $name --model \"\${OPENCLAW_MODEL:-\${MODEL:-}}\" --provider \"\${OPENCLAW_PROVIDER:-\${PROVIDER:-}}\" -- python3 /Users/wxo/Desktop/Kronos/simulate_position_603305.py --mode auto 。要求：原样返回脚本输出，不要二次改写。若失败10秒后自动重试一次。若重试仍失败，返回失败码和时间。"

  openclaw cron add --name "$name" --schedule-cron "$expr" --schedule-tz "Asia/Shanghai" --session-target isolated --payload agentTurn --message "$msg" --model "$MODEL" --timeout-seconds 60 --delivery-mode announce --delivery-channel telegram --delivery-to "736532132" --enable 2>/dev/null
  echo "Created: $name ($expr)"
done

# 午盘 13:00-14:50
for h in 13 14; do
  for m in 00 10 20 30 40 50; do
    name="603305-every10-$h$m"
    expr="$m $h * * 1-5"
    msg="立即执行并仅返回结果：$SHELL_CMD --task-name $name --jobId $name --model \"\${OPENCLAW_MODEL:-\${MODEL:-}}\" --provider \"\${OPENCLAW_PROVIDER:-\${PROVIDER:-}}\" -- python3 /Users/wxo/Desktop/Kronos/simulate_position_603305.py --mode auto 。要求：原样返回脚本输出，不要二次改写。若失败10秒后自动重试一次。若重试仍失败，返回失败码和时间。"

    openclaw cron add --name "$name" --schedule-cron "$expr" --schedule-tz "Asia/Shanghai" --session-target isolated --payload agentTurn --message "$msg" --model "$MODEL" --timeout-seconds 60 --delivery-mode announce --delivery-channel telegram --delivery-to "736532132" --enable 2>/dev/null
    echo "Created: $name ($expr)"
  done
done

echo ""
echo "=== 全部24个 every10 cron 恢复完成 ==="
openclaw cron list 2>/dev/null | awk 'NR>2' | grep "603305-every10-" | wc -l | tr -d ' ' | xargs -I{} echo "在列cron总数: {}个"
