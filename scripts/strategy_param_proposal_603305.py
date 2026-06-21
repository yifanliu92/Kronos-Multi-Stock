#!/usr/bin/env python3
"""Compatibility shim (P1 postclose wiring).

Old wrappers call scripts/strategy_param_proposal_603305.py <YYYYMMDD>.
The real implementation lives in scripts/build_strategy_param_proposal_603305.py.

This shim only delegates; it does NOT change any strategy parameters.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
SCRIPTS = BASE / 'scripts'


def main() -> int:
    sys.path.insert(0, str(SCRIPTS))

    if len(sys.argv) != 2:
        print('usage: strategy_param_proposal_603305.py YYYYMMDD', file=sys.stderr)
        return 2

    date = sys.argv[1]
    try:
        import build_strategy_param_proposal_603305
        sys.argv = ['build_strategy_param_proposal_603305.py', date]
        build_strategy_param_proposal_603305.main()
        return 0
    except SystemExit as e:
        return int(getattr(e, 'code', 1) or 0)
    except Exception as e:
        print(f'error_code=SHIM_DELEGATE_ERROR detail={e.__class__.__name__}: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
