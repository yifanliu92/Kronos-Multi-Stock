#!/usr/bin/env python3
import json, subprocess, time, uuid

SESSION_KEY = "agent:main:main"
MSG = "你好，用一句话回复"
RUN_ID = "gw-test-" + uuid.uuid4().hex[:8]

def gw(method, params):
    cmd = [
        "openclaw", "gateway", "call", method,
        "--json",
        "--params", json.dumps(params, ensure_ascii=False)
    ]
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(p.stderr or p.stdout)
    return json.loads(p.stdout)

print("run_id =", RUN_ID)

print(gw("chat.send", {
    "sessionKey": SESSION_KEY,
    "idempotencyKey": RUN_ID,
    "message": MSG
}))

last = ""
for i in range(30):
    time.sleep(1)
    data = gw("sessions.get", {"key": SESSION_KEY})
    msgs = data.get("messages", [])
    for m in reversed(msgs):
        if m.get("role") == "assistant":
            content = m.get("content")
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        parts.append(c.get("text", ""))
                text = "\n".join(parts).strip()
            if text and text != last:
                print("assistant =", text)
                raise SystemExit(0)
    print("waiting", i + 1)

raise SystemExit("timeout waiting assistant")
