#!/usr/bin/env python3
import json
import subprocess
import time
import uuid
import datetime

KRONOS="/Users/wxo/Desktop/Kronos"
OPENCLAW="/Users/wxo/.npm-global/bin/openclaw"

def today():
    return datetime.datetime.now().strftime("%Y%m%d")

def session_key(agent):
    # 每天一个短 session，避免长期累积
    if agent == "main":
        return f"agent:main:router-trade-{today()}"
    return f"agent:reviewer:router-review-{today()}"

def gw(method, params, timeout=30):
    cmd = [
        OPENCLAW, "gateway", "call", method,
        "--json",
        "--params", json.dumps(params, ensure_ascii=False)
    ]
    p = subprocess.run(cmd, cwd=KRONOS, text=True, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return json.loads(p.stdout)

def extract_latest_assistant(data, after_ms):
    msgs = data.get("messages", [])
    for m in reversed(msgs):
        if m.get("role") != "assistant":
            continue
        ts = m.get("timestamp") or 0
        if ts < after_ms:
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
            text = "\n".join(parts).strip()
            if text:
                return text
    return ""

def gateway_agent(agent, message, wait_sec=60):
    sk = session_key(agent)
    run_id = f"router-v2-{agent}-{uuid.uuid4().hex[:10]}"
    start_ms = int(time.time() * 1000)

    gw("chat.send", {
        "sessionKey": sk,
        "idempotencyKey": run_id,
        "message": message
    })

    for _ in range(wait_sec):
        time.sleep(1)
        data = gw("sessions.get", {"key": sk})
        text = extract_latest_assistant(data, start_ms)
        if text:
            return text

    return "ERROR: timeout waiting assistant"

if __name__ == "__main__":
    print("=== main test ===")
    t0=time.time()
    print(gateway_agent("main", "你好，用一句话回复"))
    print("elapsed", round(time.time()-t0, 2), "s")

    print("\n=== reviewer test ===")
    t0=time.time()
    print(gateway_agent("reviewer", "hello, reply in one short sentence"))
    print("elapsed", round(time.time()-t0, 2), "s")
