#!/usr/bin/env bash
set -euo pipefail

PY=python3
if [[ -x "/Users/wxo/Desktop/Kronos/kronos_venv/bin/python" ]]; then
  PY="/Users/wxo/Desktop/Kronos/kronos_venv/bin/python"
fi

"$PY" /Users/wxo/Desktop/Kronos/signal_router_603305.py --next-check "${1:-10:30}"
