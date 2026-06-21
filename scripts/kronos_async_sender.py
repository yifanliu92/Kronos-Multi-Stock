#!/usr/bin/env python3
"""
kronos_async_sender.py — 异步 Telegram 发送器

职责:
  1. 监听 queue_dir 中的待发送消息
  2. 从队列读取, 发送到 Telegram
  3. 失败时移入 retry_dir 等待重试
  4. 重试队列以指数退避回拉

queue 文件格式 (每行一个 JSON):
  {"chat_id": "123", "text": "...", "retry": 0}

queue_dir:     /Users/wxo/Desktop/Kronos/router_queue
retry_dir:     /Users/wxo/Desktop/Kronos/router_queue/retry
sent_dir:      /Users/wxo/Desktop/Kronos/router_queue/sent
max_retries:   5
"""
import json, os, time, urllib.parse, urllib.request, urllib.error, ssl
import certifi

KRONOS = "/Users/wxo/Desktop/Kronos"
CONFIG = os.path.expanduser("~/.openclaw/openclaw.json")
QUEUE_DIR = os.path.join(KRONOS, "router_queue")
RETRY_DIR = os.path.join(QUEUE_DIR, "retry")
SENT_DIR  = os.path.join(QUEUE_DIR, "sent")
LOG = "/private/tmp/kronos_async_sender.log"
MAX_RETRIES = 5

for d in (QUEUE_DIR, RETRY_DIR, SENT_DIR):
    os.makedirs(d, exist_ok=True)

data = json.load(open(CONFIG))
tg = data["channels"]["telegram"]
TOKEN = tg["botToken"]
API = f"https://api.telegram.org/bot{TOKEN}"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def log(s):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%F %T ") + s + "\n")


def send_one(chat_id, text):
    """Send a single chunk to Telegram; return True on success."""
    qs = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3500]})
    url = f"{API}/sendMessage?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=60, context=SSL_CONTEXT) as r:
            return True
    except Exception as e:
        log(f"send_fail chat_id={chat_id} err={repr(e)[:120]}")
        return False


def process_file(path):
    """Process one queue file. Each line is a JSON job."""
    chat_id_texts = {}
    failed = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    job = json.loads(line)
                    cid = str(job["chat_id"])
                    txt = str(job.get("text", ""))
                    retry = int(job.get("retry", 0))
                    if cid not in chat_id_texts:
                        chat_id_texts[cid] = []
                    chat_id_texts[cid].append((txt, retry))
                except Exception:
                    continue
    except Exception:
        return  # malformed file, skip

    all_ok = True
    for cid, chunks in chat_id_texts.items():
        for txt, retry in chunks:
            ok = send_one(cid, txt)
            if not ok:
                all_ok = False
                if retry < MAX_RETRIES:
                    failed.append({"chat_id": cid, "text": txt, "retry": retry + 1})
                else:
                    log(f"drop chat_id={cid} retries_exhausted text={txt[:80]!r}")

    if all_ok:
        # Move to sent
        dest = os.path.join(SENT_DIR, os.path.basename(path))
        os.rename(path, dest)
        log(f"sent ok -> {os.path.basename(path)}")
    elif failed:
        # Move to retry
        retry_path = os.path.join(
            RETRY_DIR,
            f"retry_{int(time.time())}_{os.path.basename(path)}"
        )
        with open(retry_path, "w", encoding="utf-8") as f:
            for job in failed:
                f.write(json.dumps(job, ensure_ascii=False) + "\n")
        os.remove(path)
        log(f"retry enqueued {len(failed)} jobs -> {os.path.basename(retry_path)}")
    else:
        os.remove(path)
        log(f"removed (no retryable) {os.path.basename(path)}")


def process_retry_dir():
    """Process retry files. Retry with backoff."""
    for fname in sorted(os.listdir(RETRY_DIR)):
        if not fname.startswith("retry_"):
            continue
        path = os.path.join(RETRY_DIR, fname)
        process_file(path)


def main():
    log("async_sender started")
    while True:
        try:
            # Process retry queue first
            process_retry_dir()

            # Process fresh queue
            files = sorted(os.listdir(QUEUE_DIR))
            for fname in files:
                if fname.startswith("retry_") or fname.startswith("sent_"):
                    continue
                path = os.path.join(QUEUE_DIR, fname)
                process_file(path)

            time.sleep(3)
        except Exception as e:
            log(f"ERR {repr(e)}")
            time.sleep(10)


if __name__ == "__main__":
    main()
