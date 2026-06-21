#!/bin/bash
# fix_router_reviewer_errors.sh
# 修复 kronos_telegram_router.py：
#  1. Telegram API 重试机制（指数退避）
#  2. reviewer 超时缩短 + 快速健康检查
# 使用：bash fix_router_reviewer_errors.sh

set -euo pipefail
cd "$(dirname "$0")"

ROUTER_PY="kronos_telegram_router.py"
BACKUP="${ROUTER_PY}.bak_$(date +%Y%m%d_%H%M%S)"

echo "[1/5] 备份当前 router..."
cp "$ROUTER_PY" "$BACKUP"
echo "    备份至 $BACKUP"

echo "[2/5] 停止运行中的 router..."
ROUTER_PID=$(pgrep -f "python.*kronos_telegram_router" 2>/dev/null || true)
if [ -n "$ROUTER_PID" ]; then
    kill "$ROUTER_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$ROUTER_PID" 2>/dev/null; then
        kill -9 "$ROUTER_PID" 2>/dev/null || true
    fi
    echo "    已停止 PID $ROUTER_PID"
else
    echo "    router 未在运行"
fi

echo "[3/5] 编写新版 router (增强健壮性)..."

cat > "$ROUTER_PY" << 'PYEOF'
#!/usr/bin/env python3
"""kronos_telegram_router.py — Enhanced with retry & faster reviewer fallback"""

import json, os, subprocess, time, urllib.parse, urllib.request, urllib.error, ssl, uuid, threading, datetime
import certifi

CONFIG = os.path.expanduser("~/.openclaw/openclaw.json")
KRONOS = "/Users/wxo/Desktop/Kronos"
LOG = os.path.join(KRONOS, "router_logs", "telegram_router.log")

def log(s):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%F %T ") + s + "\n")

data = json.load(open(CONFIG))
tg = data["channels"]["telegram"]
TOKEN = tg["botToken"]
ALLOW = set(str(x) for x in tg.get("allowFrom", []))
if not ALLOW:
    ALLOW = {"736532132"}

API = f"https://api.telegram.org/bot{TOKEN}"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


# ─── Retry wrapper ──────────────────────────────────────────────

def api(method, params=None):
    qs = urllib.parse.urlencode(params or {})
    url = f"{API}/{method}" + (f"?{qs}" if qs else "")
    with urllib.request.urlopen(url, timeout=60, context=SSL_CONTEXT) as r:
        return json.loads(r.read().decode())


_RETRYABLE_ERRORS = (
    urllib.error.URLError,
    urllib.error.HTTPError,
    ssl.SSLError,
    OSError,
    TimeoutError,
)


def api_with_retry(method, params=None, max_retries=3):
    """Call api() with exponential backoff on transient errors."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return api(method, params)
        except _RETRYABLE_ERRORS as e:
            last_exc = e
            if attempt < max_retries:
                wait = 2 ** attempt * 2  # 2s, 4s, 8s
                log(f"api_retry method={method} attempt={attempt+1}/{max_retries} wait={wait}s err={repr(e)[:100]}")
                time.sleep(wait)
            else:
                log(f"api_failed method={method} after={max_retries} retries err={repr(e)}")
                raise
    raise last_exc  # pragma: no cover


# ─── File download (one-off, no retry needed) ───────────────────

def download_telegram_file(file_id):
    """Download a Telegram file by file_id. Use api_with_retry for the getFile call."""
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


# ─── Image description ──────────────────────────────────────────

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
        data = json.loads(out)
        outputs = data.get("outputs") or []
        if outputs and outputs[0].get("text"):
            return outputs[0]["text"].strip()
        return "图片识别未返回正文。"
    except Exception as e:
        return "图片识别结果解析失败：" + repr(e) + "\n" + out[-1500:]


# ─── Typing indicator + send (retry-aware) ──────────────────────

def typing_once(chat_id):
    """Send typing indicator; errors are logged but non-fatal."""
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


def send(chat_id, text):
    """Send message with retry; splits long messages."""
    for i in range(0, len(text), 3500):
        chunk = text[i:i + 3500]
        try:
            api_with_retry("sendMessage", {"chat_id": chat_id, "text": chunk})
        except Exception as e:
            log(f"send FAILED chat_id={chat_id} chunk_len={len(chunk)} err={repr(e)}")
            # Try once more without retry as last resort
            try:
                api("sendMessage", {"chat_id": chat_id, "text": chunk[:3500]})
            except Exception as e2:
                log(f"send LAST_RESORT_FAILED err={repr(e2)}")


# ─── Routing ────────────────────────────────────────────────────

def route(text):
    t = text.strip()
    if t.startswith("/trade"):
        return "main", t[len("/trade"):].strip() or "进入交易/常规模式。"
    if t.startswith("/review"):
        return "reviewer", t[len("/review"):].strip() or "请对最新 Kronos 603305 报告进行盘后评审。"
    return "main", t


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


def router_session_key(agent):
    today = datetime.datetime.now().strftime("%Y%m%d")
    if agent == "main":
        return f"router-trade-{today}"
    return f"router-review-{today}"


# ─── Reviewer health pre-check ──────────────────────────────────

def reviewer_codex_alive():
    """Quick check: is the OpenClaw-managed codex app-server process running?"""
    try:
        r = subprocess.run(
            ["pgrep", "-f", r"openclaw.*codex.*app-server"],
            capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


# ─── OpenClaw agent call ────────────────────────────────────────

def call_openclaw(agent, msg):
    sk = router_session_key(agent)
    is_reviewer = (agent == "reviewer")

    # --- Pre-check for reviewer ---
    if is_reviewer and not reviewer_codex_alive():
        log("precheck: reviewer codex app-server NOT running — fast fallback to main")
        return "reviewer 不可用（codex app-server 未运行），已自动切到 main 处理。\n\n" + call_openclaw("main", (
            "reviewer codex app-server is NOT running. "
            "Use main agent to answer this request directly, in Chinese. "
            "Do not call reviewer.\n\nOriginal request:\n" + msg
        ))

    # --- Timeout: shorter for reviewer ---
    cli_timeout = "90" if is_reviewer else "180"
    subprocess_timeout = 120 if is_reviewer else 240
    model = "openai/gpt-5.5" if is_reviewer else "deepseek/deepseek-v4-flash"

    cmd = [
        "/Users/wxo/.npm-global/bin/openclaw", "agent",
        "--agent", agent,
        "--session-key", sk,
        "--model", model,
        "--message", msg,
        "--timeout", cli_timeout,
    ]
    log("call_openclaw start agent=" + agent + " session_key=" + sk + " timeout=" + cli_timeout + "s" + " msg=" + repr(msg[:80]))
    try:
        p = subprocess.run(cmd, cwd=KRONOS, text=True, capture_output=True, timeout=subprocess_timeout)
    except subprocess.TimeoutExpired as e:
        log("call_openclaw timeout agent=" + agent + " seconds=" + str(e.timeout))
        if is_reviewer:
            return "reviewer 暂时不可用（超时），已自动切到 main 处理。\n\n" + call_openclaw("main", (
                "reviewer/codex app-server timed out. "
                "Use main agent to answer this request directly, in Chinese. "
                "Do not call reviewer.\n\nOriginal request:\n" + msg
            ))
        return f"ERROR calling {agent}\n\nTimeout after {e.timeout}s"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    log("call_openclaw done agent=" + agent + " returncode=" + str(p.returncode) + " stdout_len=" + str(len(out)) + " stderr_len=" + str(len(err)))
    if p.returncode != 0:
        if is_reviewer:
            return "reviewer 暂时不可用（进程错误），已自动切到 main 处理。\n\n" + call_openclaw("main", (
                "reviewer/codex app-server failed. "
                "Use main agent to answer this request directly, in Chinese. "
                "Do not call reviewer.\n\n"
                "reviewer stderr:\n" + (err[-1500:] or out[-1500:]) + "\n\n"
                "Original request:\n" + msg
            ))
        return f"ERROR calling {agent}\n\n{err[-1500:] or out[-1500:]}"
    cleaned = clean_openclaw_output(out)
    return cleaned or "(empty response)"


# ─── Main loop ──────────────────────────────────────────────────

offset = 0
log("router started (enhanced: retry + faster reviewer fallback)")
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
                send(chat_id, "unauthorized")
                log(f"deny user={user_id}")
                continue

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
                    send(chat_id, "图片处理失败：" + repr(e))
                    continue

            if not text:
                continue

            agent, msg = route(text)
            log(f"route user={user_id} agent={agent} text={text[:80]!r}")
            reply = run_with_typing(chat_id, call_openclaw, agent, msg)
            send(chat_id, reply)
    except Exception as e:
        log("ERR " + repr(e))
        time.sleep(5)
PYEOF

echo "    Done."

echo "[4/5] 语法验证..."
python3 -m py_compile "$ROUTER_PY"
echo "    通过 ✓"

echo "[5/5] 启动新 router..."
nohup python3 "$ROUTER_PY" >> /dev/null 2>&1 &
sleep 2
NEW_PID=$(pgrep -f "python.*kronos_telegram_router" 2>/dev/null || true)
if [ -n "$NEW_PID" ]; then
    echo "    新 router PID $NEW_PID 已启动 ✓"
else
    echo "    ❌ router 启动失败，请检查脚本"
    exit 1
fi

echo ""
echo "===== 修复完成 ====="
echo "改动摘要："
echo "  1. api_with_retry() — 所有 Telegram API 调用增加指数退避重试"
echo "  2. reviewer 超时缩短: CLI 180→90s, subprocess 240→120s"
echo "  3. reviewer codex 健康预检 — 调用前快速 pgrep，挂则立即回退 main"
echo "  4. send() 增加重试 + 末次保底直发"
echo "备份: $(basename "$BACKUP")"
echo "新 PID: $NEW_PID"
