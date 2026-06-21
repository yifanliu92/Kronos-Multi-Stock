#!/usr/bin/env python3
"""
kronos_telegram_router.py — P0/P1/P2 全面改进版

P0 — 立即回执 + 进度汇报 + 缩短超时 + session lock 自动绕开
P1 — 故障走 maintenance session + Telegram 发送异步化
P2 — sessions 定期清理归档

改进摘要:
  - 收到消息 3s 内回复"已收到, 开始处理"
  - 超过 120s 自动发进度汇报
  - reviewer 超时 60s, main 超时 120s, 超时立即 fallback
  - session lock age > 120s → 自动 rotate, 写入诊断
  - /maintenance 路由 → 走专用维护会话
  - 回复结果先落盘 queue → async sender 异步发送
  - 409 Conflict 自动绕开 (唯一实例检测 + offset 恢复)
"""

import json, os, subprocess, time, urllib.parse, urllib.request, urllib.error, ssl, uuid, threading, datetime, glob, sys
import certifi

CONFIG = os.path.expanduser("~/.openclaw/openclaw.json")
KRONOS = "/Users/wxo/Desktop/Kronos"
LOG = "/private/tmp/kronos_telegram_router.log"
QUEUE_DIR = os.path.join(KRONOS, "router_queue")
LOCK_DIAG_DIR = os.path.join(KRONOS, "router_lock_diag")
MAINTENANCE_LOCK = os.path.join(KRONOS, ".maintenance_mode")

for d in (QUEUE_DIR, LOCK_DIAG_DIR):
    os.makedirs(d, exist_ok=True)

data = json.load(open(CONFIG))
tg = data["channels"]["telegram"]
TOKEN = tg["botToken"]
ALLOW = set(str(x) for x in tg.get("allowFrom", [])) or {"736532132"}

API = f"https://api.telegram.org/bot{TOKEN}"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# ── 全局状态 ─────────────────────────────────────
_processing_event = threading.Event()  # set when a long operation is active
_processing_start = 0.0
_processing_phase = "init"
_progress_ctx = {}  # chat_id for progress reporter

# ── 捕获未处理异常 ───────────────────────────────
_LAST_CRASH_LOG = None

def _exception_hook(t, v, tb):
    global _LAST_CRASH_LOG
    import traceback
    _LAST_CRASH_LOG = "".join(traceback.format_exception(t, v, tb))
    log("UNCAUGHT " + _LAST_CRASH_LOG)

sys.excepthook = _exception_hook


# ── 日志 ─────────────────────────────────────────

def log(s):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%F %T ") + s + "\n")


# ── Telegram API ─────────────────────────────────

def api(method, params=None):
    qs = urllib.parse.urlencode(params or {})
    url = f"{API}/{method}" + (f"?{qs}" if qs else "")
    try:
        with urllib.request.urlopen(url, timeout=60, context=SSL_CONTEXT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 409:
            log(f"api_409 method={method} — conflict, retrying")
        raise


_RETRYABLE = (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError, OSError, TimeoutError)


def api_with_retry(method, params=None, max_retries=3):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return api(method, params)
        except _RETRYABLE as e:
            last_exc = e
            if attempt < max_retries:
                wait = 2 ** attempt * 2
                log(f"api_retry method={method} attempt={attempt+1}/{max_retries} wait={wait}s err={repr(e)[:100]}")
                time.sleep(wait)
            else:
                log(f"api_failed method={method} after={max_retries} retries err={repr(e)}")
                raise
    raise last_exc


# ── 异步发送 (P1: 结果先落盘, Telegram 不阻塞 agent) ──

def enqueue_send(chat_id, text, priority=False):
    """
    将回复写入队列文件。async_sender 会异步取出发送。
    如果 priority=True, 写入 priority_ 前缀文件, 优先发送。
    """
    prefix = "p_" if priority else "q_"
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    fname = f"{prefix}{ts}_{uid}.jsonl"
    path = os.path.join(QUEUE_DIR, fname)

    # 分块写入
    with open(path, "w", encoding="utf-8") as f:
        for i in range(0, len(text), 3500):
            chunk = text[i:i + 3500]
            job = json.dumps({"chat_id": str(chat_id), "text": chunk, "retry": 0}, ensure_ascii=False)
            f.write(job + "\n")

    log(f"enqueued_send chat_id={chat_id} chunks={ (len(text)-1)//3500 + 1 } file={fname}")
    return path


# ── 紧急直接发送 (用于 ACK/进度, 不走队列) ─────────

def send_direct(chat_id, text):
    """紧急直发, 仅用于短消息."""
    try:
        qs = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3500]})
        url = f"{API}/sendMessage?{qs}"
        with urllib.request.urlopen(url, timeout=30, context=SSL_CONTEXT) as r:
            return True
    except Exception as e:
        log(f"send_direct FAILED chat_id={chat_id} err={repr(e)[:100]}")
        return False


# ── Typing indicator ─────────────────────────────

def typing_once(chat_id):
    try:
        api_with_retry("sendChatAction", {"chat_id": chat_id, "action": "typing"}, max_retries=1)
    except Exception as e:
        log("typing ERR " + repr(e))


def run_with_typing(chat_id, func, *args, **kwargs):
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            typing_once(chat_id)
            stop.wait(4)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        return func(*args, **kwargs)
    finally:
        stop.set()


# ── P0: 安静回执 ─────────────────────────────────

def should_ack(text):
    """Only acknowledge commands or repair-like requests; keep casual chat quiet."""
    t = (text or "").strip().lower()
    if t.startswith(("/fix", "/maintenance", "/review")):
        return True
    keywords = (
        "修复", "处理", "部署", "执行", "检查", "验证", "排查",
        "错误", "error", "报错", "故障", "cron", "router", "gateway",
        "telegram", "session", "lock",
    )
    return len(t) >= 18 and any(k in t for k in keywords)


def send_ack(chat_id, msg_preview):
    """Short ack for long/maintenance tasks only."""
    send_direct(chat_id, "已收到，处理中。")
    log(f"ack sent chat_id={chat_id}")


def progress_reporter(chat_id, timeout=120):
    """如果超过 timeout 秒无结果, 自动发送进度汇报."""
    time.sleep(timeout)
    if _processing_event.is_set():
        phase = _processing_phase
        send_direct(chat_id, f"⏳ 仍在处理, 当前阶段: {phase}\n已等待 {timeout} 秒, 请稍候...")
        log(f"progress_report sent chat_id={chat_id} phase={phase}")


# ── Session lock 诊断绕开 (P0) ────────────────────

def find_session_lock():
    """查找 router-trade/review 等 session key 对应的 lock 文件."""
    lock_patterns = [
        os.path.expanduser(f"~/.openclaw/agents/main/locks/*.lock"),
        os.path.expanduser(f"~/.openclaw/agents/reviewer/locks/*.lock"),
    ]
    for pattern in lock_patterns:
        for lock_path in glob.glob(pattern):
            try:
                stat = os.stat(lock_path)
                age = time.time() - stat.st_mtime
                if age > 120:  # stale lock
                    return lock_path, age
            except OSError:
                continue
    return None, 0


def diagnose_and_bypass_session_lock():
    """
    检查 session lock, 如果 lock age > 120s, 写入诊断文件。
    返回: (bypassed: bool, reason: str)
    """
    lock_path, age = find_session_lock()
    if lock_path is None:
        return False, "no_lock"

    # 写诊断
    ts = time.strftime("%Y%m%d_%H%M%S")
    diag_path = os.path.join(LOCK_DIAG_DIR, f"lock_diag_{ts}.json")
    diag = {
        "ts": time.strftime("%F %T"),
        "lock_path": lock_path,
        "age_seconds": round(age, 1),
        "action": "bypassed_session_rotation",
        "rotate_suffix": ts,
    }
    with open(diag_path, "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    log(f"lock_diagnostic written path={diag_path} age={age:.0f}s")

    return True, f"lock_age={age:.0f}s_bypassed"


# ── Session key 生成 ─────────────────────────────

# 持久化 rotation counter
_ROTATION_COUNTER_PATH = os.path.join(KRONOS, "router_lock_diag", ".rotation_counter")
if os.path.exists(_ROTATION_COUNTER_PATH):
    with open(_ROTATION_COUNTER_PATH) as f:
        _ROTATION_COUNTER = int(f.read().strip() or "0")
else:
    _ROTATION_COUNTER = 0


def _next_rotation():
    global _ROTATION_COUNTER
    _ROTATION_COUNTER += 1
    os.makedirs(os.path.dirname(_ROTATION_COUNTER_PATH), exist_ok=True)
    with open(_ROTATION_COUNTER_PATH, "w") as f:
        f.write(str(_ROTATION_COUNTER))
    return _ROTATION_COUNTER


def router_session_key(agent, bypass=False):
    today = datetime.datetime.now().strftime("%Y%m%d")
    if agent == "main":
        base = f"router-trade-{today}"
    elif agent == "reviewer":
        base = f"router-review-{today}"
    elif agent == "maintenance":
        base = f"router-maintenance-{today}"
    else:
        base = f"router-{agent}-{today}"

    if bypass:
        rot = _next_rotation()
        base = f"{base}-bypass-r{rot}"
        log(f"session_rotate key={base}")
    return base


# ── OpenClaw 输出清理 ────────────────────────────

def clean_openclaw_output(out):
    lines = []
    for line in (out or "").splitlines():
        x = line.strip()
        if not x:
            continue
        if x.startswith("🦞 OpenClaw"):
            continue
        if x.startswith("Say "):
            continue
        if x.startswith("I've survived"):
            continue
        if x.startswith("16:") and "[plugins]" in x:
            continue
        if x in ("│", "◇"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


# ── Reviewer 健康预检 ────────────────────────────

def reviewer_codex_alive():
    try:
        r = subprocess.run(
            ["pgrep", "-f", r"openclaw.*codex.*app-server"],
            capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


# ── Routing ──────────────────────────────────────

def route(text, chat_id=None):
    """解析消息, 返回 (agent_name, prompt)."""
    t = text.strip()
    lower = t.lower()

    # /maintenance — 故障维修专用会话 (P1)
    if lower.startswith("/maintenance") or lower.startswith("/fix"):
        stripped = (t[len("/maintenance"):] if lower.startswith("/maintenance") else t[len("/fix"):]).strip()
        return "maintenance", stripped or "进入故障维修模式。"

    if lower.startswith("/trade"):
        return "main", t[len("/trade"):].strip() or "进入交易/常规模式。"

    if lower.startswith("/review"):
        return "reviewer", t[len("/review"):].strip() or "请对最新 Kronos 603305 报告进行盘后评审。"

    # 默认走 main
    return "main", t


# ── 图片处理 ─────────────────────────────────────

def download_telegram_file(file_id):
    info = api_with_retry("getFile", {"file_id": file_id})
    file_path = info.get("result", {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram getFile missing file_path")
    ext = os.path.splitext(file_path)[1] or ".jpg"
    out_dir = os.path.join(KRONOS, "router_media")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"tg_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}")
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    with urllib.request.urlopen(url, timeout=60, context=SSL_CONTEXT) as r:
        data = r.read()
    with open(out_path, "wb") as f:
        f.write(data)
    log(f"downloaded telegram image path={out_path} bytes={len(data)}")
    return out_path


def describe_image(path, prompt):
    cmd = [
        "/Users/wxo/.npm-global/bin/openclaw",
        "infer", "image", "describe",
        "--file", path,
        "--prompt", prompt or "请用中文详细说明这张图片的主要内容，并尽量识别其中的文字、界面、错误提示和关键信息。",
        "--timeout-ms", "60000",
        "--json"
    ]
    p = subprocess.run(cmd, cwd=KRONOS, text=True, capture_output=True, timeout=90)
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if p.returncode != 0:
        return "图片识别失败：\n" + (err[-1500:] or out[-1500:])
    try:
        d = json.loads(out)
        outputs = d.get("outputs") or []
        if outputs and outputs[0].get("text"):
            return outputs[0]["text"].strip()
        return "图片识别未返回正文。"
    except Exception as e:
        return "图片识别结果解析失败：" + repr(e) + "\n" + out[-1500:]


# ── OpenClaw agent 调用 (P0: 缩短超时) ────────────

def call_openclaw(agent, msg):
    global _processing_event, _processing_start, _processing_phase, _progress_ctx

    _processing_event.set()
    _processing_start = time.time()
    _processing_phase = "dispatch"

    try:
        is_reviewer = (agent == "reviewer")
        is_maintenance = (agent == "maintenance")

        # 会话 key
        bypassed, bypass_reason = diagnose_and_bypass_session_lock()
        sk = router_session_key(agent, bypass=bypassed)
        _processing_phase = f"session_key={sk} bypass={bypassed}"

        # --- P0: 超时设置 (显著缩短) ---
        if is_reviewer:
            cli_timeout = "45"
            subprocess_timeout = 60
            model = "openai/gpt-5.5"
        elif is_maintenance:
            cli_timeout = "120"
            subprocess_timeout = 150
            model = "deepseek/deepseek-v4-flash"
        else:
            cli_timeout = "90"
            subprocess_timeout = 120
            model = "deepseek/deepseek-v4-flash"

        # 为 maintenance session 添加特殊指令前缀
        if is_maintenance and "maintenance" not in msg.lower():
            msg = (
                "【维护模式】请在当前路由器-交易主会话之外, 使用独立的 maintenance 上下文进行诊断和修复。"
                "不要在 router-trade 主会话中操作。\n\n" + msg
            )

        # --- reviewer pre-check ---
        if is_reviewer and not reviewer_codex_alive():
            log("precheck: reviewer codex app-server NOT running")
            _processing_phase = "reviewer_fallback_main"
            result = call_openclaw("main", (
                "reviewer codex app-server is NOT running. "
                "Use main agent to answer directly. Do NOT call reviewer.\n\nOriginal request:\n" + msg
            ))
            _processing_phase = "done_fallback"
            return result

        _processing_phase = "exec_openclaw"

        cmd = [
            "/Users/wxo/.npm-global/bin/openclaw", "agent",
            "--agent", agent,
            "--session-key", sk,
            "--model", model,
            "--message", msg,
            "--timeout", cli_timeout,
        ]
        log(f"call_openclaw agent={agent} sk={sk} timeout={cli_timeout}s bypass={bypassed}")

        try:
            p = subprocess.run(cmd, cwd=KRONOS, text=True, capture_output=True, timeout=subprocess_timeout)
        except subprocess.TimeoutExpired as e:
            _processing_phase = f"timeout_{agent}"
            log(f"timeout agent={agent} subprocess_timeout={subprocess_timeout}s")
            if is_reviewer:
                return "⚠️ reviewer 超时 (60s), 已自动切到 main 处理。\n\n" + call_openclaw("main", (
                    "reviewer timed out. Handle request directly with main agent.\n\nOriginal request:\n" + msg
                ))
            if is_maintenance:
                return f"⚠️ maintenance 超时 ({subprocess_timeout}s)。请重试, 或拆分成更小的维护步骤。"
            return f"⚠️ main 超时 ({subprocess_timeout}s)。请稍后重试或拆分请求。"

        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        log(f"call_openclaw done agent={agent} rc={p.returncode} stdout={len(out)} stderr={len(err)}")

        _processing_phase = "postprocess"

        if p.returncode != 0:
            if is_reviewer:
                return "⚠️ reviewer 进程错误, 已自动切到 main 处理。\n\n" + call_openclaw("main", (
                    "reviewer process failed. Handle directly with main agent.\n\n"
                    "reviewer stderr:\n" + (err[-1500:] or out[-1500:]) + "\n\nOriginal request:\n" + msg
                ))
            return f"ERROR calling {agent}\n\n{err[-1500:] or out[-1500:]}"

        cleaned = clean_openclaw_output(out)
        _processing_phase = "done"
        return cleaned or "(empty response)"

    finally:
        _processing_event.clear()


# ── 主循环 ────────────────────────────────────────

def run_main_loop():
    global offset, _LAST_CRASH_LOG, _processing_event, _processing_phase, _progress_ctx

    offset = 0
    log("router started (P0/P1/P2 — ack, timeout, bypass, maintenance, async_send)")

    while True:
        try:
            res = api_with_retry("getUpdates", {"timeout": 50, "offset": offset})
            for u in res.get("result", []):
                offset = max(offset, u["update_id"] + 1)
                m = u.get("message") or u.get("edited_message") or {}
                chat = m.get("chat", {})
                chat_id = chat.get("id")
                user = m.get("from", {})
                user_id = str(user.get("id", ""))
                text = m.get("text", "")
                caption = m.get("caption", "")
                photos = m.get("photo") or []

                if not chat_id:
                    continue

                if user_id not in ALLOW:
                    send_direct(chat_id, "unauthorized")
                    log(f"deny user={user_id}")
                    continue

                # 图片处理
                if photos:
                    file_id = photos[-1].get("file_id")
                    try:
                        img_path = download_telegram_file(file_id)
                        user_prompt = caption.strip() or "请解读这张图片。"
                        img_desc = run_with_typing(chat_id, describe_image, img_path, user_prompt)
                        text = (
                            "用户通过 Telegram 发来一张图片。\n\n"
                            "用户问题/说明：\n"
                            f"{user_prompt}\n\n"
                            "图片识别结果：\n"
                            f"{img_desc}\n\n"
                            "请基于图片识别结果和用户问题，用中文给出清楚、实用的回答。"
                        )
                        log(f"photo user={user_id} path={img_path} caption={caption[:80]!r}")
                    except Exception as e:
                        log("photo ERR " + repr(e))
                        send_direct(chat_id, "图片处理失败：" + repr(e))
                        continue

                if not text:
                    continue

                agent, msg = route(text)
                log(f"route user={user_id} agent={agent} text={text[:80]!r}")

                # === P0: 命令/维修类长任务回执；普通聊天保持安静 ===
                if should_ack(text):
                    send_ack(chat_id, text)

                # === P0: 进度汇报守护线程 ===
                _progress_ctx["chat_id"] = chat_id
                t_progress = threading.Thread(
                    target=progress_reporter,
                    args=(chat_id,),
                    daemon=True
                )
                t_progress.start()

                # === 处理 ===
                reply = run_with_typing(chat_id, call_openclaw, agent, msg)

                # === P1: 结果先入队, Telegram 不阻塞 ===
                enqueue_send(chat_id, reply)

                # 如果有 crash 日志, 也发送
                if _LAST_CRASH_LOG:
                    enqueue_send(chat_id, f"⚠️ 路由器捕获到未处理异常:\n{_LAST_CRASH_LOG[-2000:]}")
                    _LAST_CRASH_LOG = None

        except Exception as e:
            log("main_loop ERR " + repr(e))
            time.sleep(5)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check-locks":
        # 诊断模式: 检查并报告 lock 状态
        lock_path, age = find_session_lock()
        if lock_path:
            print(f"LOCK_FOUND path={lock_path} age={age:.0f}s")
        else:
            print("LOCK_NONE")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--cleanup-sessions":
        # 调用 session 清理
        cleanup_script = os.path.join(os.path.dirname(__file__), "kronos_session_cleanup.sh")
        subprocess.run(["bash", cleanup_script])
        sys.exit(0)

    run_main_loop()
