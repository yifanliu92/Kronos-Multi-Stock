#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


def parse_args():
    p = argparse.ArgumentParser(description="Pick best validated params from latest validation summary")
    p.add_argument("--symbol", required=True)
    p.add_argument("--outputs-root", default="outputs")
    p.add_argument("--prefer", choices=["green-first", "best-mape"], default="green-first")
    p.add_argument("--print-meta", action="store_true")
    return p.parse_args()


def find_latest_summary(symbol: str, outputs_root: Path) -> Path:
    candidates = sorted(outputs_root.glob(f"*_validation_{symbol}/{symbol}_validation_summary.csv"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No validation summary found under {outputs_root} for symbol={symbol}")
    return candidates[-1]


def main():
    args = parse_args()
    root = Path(args.outputs_root)
    summary_path = find_latest_summary(args.symbol, root)

    df = pd.read_csv(summary_path)
    need_cols = {"lookback", "pred_len", "mae", "mape", "dir_acc_pct", "baseline_mae", "baseline_mape", "decision"}
    if not need_cols.issubset(df.columns):
        missing = sorted(need_cols - set(df.columns))
        raise ValueError(f"summary file missing cols: {missing}")

    if args.prefer == "green-first":
        green = df[df["decision"] == "GREEN"].copy()
        if not green.empty:
            best = green.sort_values(["mape", "mae"], ascending=[True, True]).iloc[0]
        else:
            best = df.sort_values(["mape", "mae"], ascending=[True, True]).iloc[0]
    else:
        best = df.sort_values(["mape", "mae"], ascending=[True, True]).iloc[0]

    lookback = int(best["lookback"])
    pred_len = int(best["pred_len"])

    if args.print_meta:
        print(f"REC_LOOKBACK={lookback}")
        print(f"REC_PRED_LEN={pred_len}")
        print(f"DECISION={best['decision']}")
        print(f"SOURCE_SUMMARY={summary_path}")
    else:
        print(f"{lookback},{pred_len}")


if __name__ == "__main__":
    main()
