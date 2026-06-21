#!/usr/bin/env python3
"""Compatibility shim.

Delegates to existing build_error_code_daily.py.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
TARGET = BASE / 'scripts' / 'build_error_code_daily.py'


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR error_code=SHIM_TARGET_MISSING target={TARGET}")
        return 1
    sys.argv = [str(TARGET)] + sys.argv[1:]
    runpy.run_path(str(TARGET), run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
