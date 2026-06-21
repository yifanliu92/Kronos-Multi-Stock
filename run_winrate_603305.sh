#!/usr/bin/env bash
set -euo pipefail
cd /Users/wxo/Desktop/Kronos
if [[ -x ./kronos_venv/bin/python ]]; then
  PY=./kronos_venv/bin/python
else
  PY=python3
fi
"$PY" scripts/calc_winrate_603305.py
