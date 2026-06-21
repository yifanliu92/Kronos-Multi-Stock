#!/usr/bin/env python3
"""Compatibility shim.

Old wrappers call slot_coverage_daily.py, but the real implementation lives in
build_slot_coverage_daily.py.

This shim does NOT change strategy parameters and does NOT fabricate results.
It delegates to the existing builder.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
TARGET = BASE / 'scripts' / 'build_slot_coverage_daily.py'


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR error_code=SHIM_TARGET_MISSING target={TARGET}")
        return 1
    # Keep argv contract: slot_coverage_daily.py YYYYMMDD
    sys.argv = [str(TARGET)] + sys.argv[1:]
    runpy.run_path(str(TARGET), run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
