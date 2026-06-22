#!/usr/bin/env python3
"""
603305 盘中自循环模拟脚本（no-model 模式）
替代 24 个 every10 cron，彻底绕过 cron → agentTurn → model 链路。

工作方式：
1. 由 cron 09:20 启动一次，脚本一直运行到 14:50
2. 每10分钟执行 simulate_position_603305.py 一次
3. 结果通过 Telegram API 直接投递（curl）
4. 0 模型调用，0 timeout
5. 不在盘中就自动退出

用法：
  python3 /Users/wxo/Desktop/Kronos/scripts/intraday_looper_603305.py [--dry-run]

依赖：
  - /Users/wxo/Desktop/Kronos/simulate_position_603305.py
  - /Users/wxo/Desktop/Kronos/scripts/run_with_model_guard.sh
  - curl + Telegram bot token
"""

import subprocess
import time
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

# ── 配置 ─────────────────────────────────────
KRONOS_DIR = "/Users/wxo/Desktop/Kronos"
SIM_SCRIPT = os.path.join(KRONOS_DIR, "simulate_position_603305.py")
GUARD_SCRIPT = os.path.join(KRONOS_DIR, "scripts/run_with_model_guard.sh")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "866112…MBGw")
TELEGRAM_CHAT_ID = "736532132"

# A股交易时段（Asia/Shanghai）
MORNING_START = 9 * 60 + 30        # 09:30
MORNING_END = 11 * 60 + 30         # 11:30
AFTERNOON_START = 13 * 60          # 13:00
AFTERNOON_END = 14 * 60 + 50       # 14:50
INTERVAL_MINUTES = 10

RUN_LOCK = "/tmp/intraday_looper_603305.lock"
LOG_FILE = os.path.join(KRONOS_DIR, "logs/intraday_looper.log")

# ── 工具函数 ─────────────────────────────────

def tzshanghai():
    """返回 Asia/Shanghai 时区的当前 datetime"""
    return datetime.now(timezone(timedelta(hours=8)))

def minutes_today(dt=None):
    """返回当天凌晨以来的分钟数"""
    if dt is None:
        dt = tzshanghai()
    return dt.hour * 60 + dt.minute

def is_in_session(mins):
    """当前是否在交易时段内"""
    return (MORNING_START <= mins < MORNING_END) or (AFTERNOON_START <= mins <= AFTERNOON_END)

def is_after_trading_day(mins):
    """是否已经过了当天最后一个盘中运行时点。午休不算收盘。"""
    return mins > AFTERNOON_END

def next_run_minute(mins):
    """找到应该执行的下一个时刻。
    如果当前分钟是10的倍数且在交易时段，返回当前（立即执行）。
    """
    if mins < MORNING_START:
        return MORNING_START
    if mins > AFTERNOON_END:
        return None
    
    # 如果当前已经是整10分钟且在交易时段 → 立即执行
    if mins % 10 == 0:
        if (MORNING_START <= mins < MORNING_END) or (AFTERNOON_START <= mins <= AFTERNOON_END):
            return mins
    
    next_slot = ((mins // 10) + 1) * 10
    
    if mins < MORNING_END:
        if next_slot >= MORNING_END:
            return AFTERNOON_START
        return next_slot
    
    if mins < AFTERNOON_START:
        return AFTERNOON_START
    
    if mins <= AFTERNOON_END:
        if next_slot > AFTERNOON_END:
            return None
        return next_slot
    
    return None

def send_telegram(text):
    """通过 Telegram Bot API 发送消息"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception as e:
        log(f"Telegram 投递失败: {e}")
        return None

def log(msg):
    ts = tzshanghai().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")

def run_simulation():
    """执行模拟策略并返回输出文本"""
    task_name = f"603305-every10-{tzshanghai().strftime('%H%M')}"
    
    cmd = [
        "bash", GUARD_SCRIPT,
        "--task-name", task_name,
        "--jobId", f"intraday-looper-{task_name}",
        "--", "python3", SIM_SCRIPT, "--mode", "auto"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=KRONOS_DIR)
        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            output = "(脚本无输出)"
        return output, result.returncode
    except subprocess.TimeoutExpired:
        return "(脚本执行超时)", -1
    except Exception as e:
        return f"(脚本执行异常: {e})", -1

def send_failure_report(task_name, returncode, output):
    """脚本失败时发送详细汇报"""
    now = tzshanghai().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"⏰ <b>603305 盘中模拟 - 自循环模式</b>\n"
        f"📅 时间: {now}\n"
        f"⚠️ 状态: <b>脚本失败</b>\n"
        f"🔖 任务: {task_name}\n"
        f"⬇️ 返回码: {returncode}\n"
        f"📄 输出:\n<code>{output[:1000]}</code>"
    )
    send_telegram(msg)

def send_normal_report(task_name, output):
    """脚本成功时发送结果"""
    now = tzshanghai().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"⏰ <b>603305 盘中模拟 - 自循环模式</b>\n"
        f"📅 时间: {now}\n"
        f"✅ 状态: <b>{task_name}</b>\n"
        f"📄 结果:\n<code>{output[:3000]}</code>"
    )
    send_telegram(msg)

# ── 主循环 ───────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    
    # 防重复启动
    if os.path.exists(RUN_LOCK):
        pid = open(RUN_LOCK).read().strip()
        try:
            os.kill(int(pid), 0)
            log(f"已有实例运行中 (PID={pid})，退出")
            return
        except:
            pass
    
    with open(RUN_LOCK, "w") as f:
        f.write(str(os.getpid()))
    
    log("=" * 40)
    log("603305 盘中自循环模拟启动")
    log(f"PID: {os.getpid()}")
    log(f"DRY-RUN: {dry_run}")
    
    try:
        loop(dry_run)
    finally:
        os.unlink(RUN_LOCK)
        log("进程退出，锁已释放")

def loop(dry_run):
    while True:
        now = tzshanghai()
        mins = minutes_today(now)
        
        if not is_in_session(mins):
            if mins > AFTERNOON_END:
                # 收盘了，退出
                log(f"当前 {now.hour:02d}:{now.minute:02d}，已收盘，退出")
                return
            # 午休或盘前，等待
            next_m = next_run_minute(mins)
            if next_m is None:
                log("收盘时间已过，退出")
                return
            next_h = next_m // 60
            next_mn = next_m % 60
            wait_s = (next_h - now.hour) * 3600 + (next_mn - now.minute) * 60 - now.second
            if wait_s > 0:
                log(f"当前 {now.hour:02d}:{now.minute:02d}，非交易时段，等待 {wait_s} 秒后到 {next_h:02d}:{next_mn:02d}")
                time.sleep(min(wait_s, 600))  # 最多等10分钟，醒一次检查
            continue
        
        next_mins = next_run_minute(mins)
        if next_mins is None:
            log("收盘时间已过，退出")
            return
        
        # 计算到下次运行的等待秒数
        now_hour = mins // 60
        now_min = mins % 60
        next_hour = next_mins // 60
        next_min = next_mins % 60
        
        wait_seconds = (next_hour - now_hour) * 3600 + (next_min - now_min) * 60 - now.second
        if wait_seconds <= 0:
            # 已经到了执行时刻
            task_name = f"intraday-looper-{now.strftime('%H%M')}"
            log(f"▶️ 运行 {task_name}")
            
            output, rc = run_simulation()
            
            log(f"返回码={rc}, 输出长度={len(output)}")
            
            if not dry_run:
                if rc == 0:
                    send_normal_report(task_name, output)
                else:
                    send_failure_report(task_name, rc, output)
            else:
                log(f"[DRY-RUN] 跳过投递")
            
            # 执行完毕后睡到下一个10分钟点
            wait_seconds = 60  # 至少休息60秒
        else:
            if wait_seconds > 60:
                log(f"⏳ 等待 {wait_seconds} 秒后到 {(next_hour):02d}:{next_min:02d} 运行")
        
        # 如果等待时间少于10秒，直接等（精细到秒级）
        if wait_seconds < 10:
            time.sleep(wait_seconds)
        else:
            # 每30秒醒一次，检查是否到了交易时段边界
            slept = 0
            while slept < wait_seconds:
                time.sleep(min(30, wait_seconds - slept))
                slept += 30
                mins_now = minutes_today(tzshanghai())
                if is_after_trading_day(mins_now):
                    log(f"等待期间发现已过收盘时点，退出")
                    return

if __name__ == "__main__":
    main()
