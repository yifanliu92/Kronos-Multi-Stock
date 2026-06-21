#!/usr/bin/env bash
set -euo pipefail
BASE="/Users/wxo/Desktop/Kronos"
V="v0.3"
START=${1:-2026-05-11}
END=${2:-2026-05-21}

python3 - <<PY
import datetime as dt
from pathlib import Path
import subprocess, sys
start=dt.datetime.strptime("$START","%Y-%m-%d").date()
end=dt.datetime.strptime("$END","%Y-%m-%d").date()
script="/Users/wxo/Desktop/Kronos/scripts/factor_observer_603305.py"
v="$V"
base=Path("/Users/wxo/Desktop/Kronos")
out=[]
d=start
while d<=end:
    day=d.strftime('%Y-%m-%d')
    # run backfill; safe even if no logs exist (will write 0 records)
    cmd=[sys.executable, script, '--day', day, '--mode', 'backfill', '--version', v]
    subprocess.run(cmd, check=True)
    out.append(day)
    d+=dt.timedelta(days=1)
print('DONE', out[0], out[-1], 'days', len(out))
PY

echo "WROTE backfill daily outputs to: $BASE/guard_outputs and $BASE/daily_reports"