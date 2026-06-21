#!/usr/bin/env python3
from pathlib import Path
import subprocess

# Alias entry: currently generate only 20260522 strategy handoff
# Usage: python3 scripts/build_chatgpt_handoff.py

base = Path('/Users/wxo/Desktop/Kronos')
script = base / 'scripts' / 'build_chatgpt_handoff_strategy_review_20260522.py'
if not script.exists():
    raise SystemExit('missing build_chatgpt_handoff_strategy_review_20260522.py')
subprocess.check_call(['python3', str(script)])
