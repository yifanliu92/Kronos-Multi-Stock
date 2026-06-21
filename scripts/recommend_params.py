#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


def parse_args():
    p = argparse.ArgumentParser(description="Recommend lookback/pred_len from validation summary")
    p.add_argument("--symbol", required=True)
    p.add_argument("--summary-csv", required=True)
    p.add_argument("--prefer", choices=["green", "yellow"], default="green")
    return p.parse_args()


def choose_row(df: pd.DataFrame, prefer: str) -> pd.Series:
    # 优先 GREEN；没有就退到 YELLOW；还没有就全体里最优
    if prefer == "green":
        cand = df[df["decision"] == "GREEN"]
        if not cand.empty:
            return cand.sort_values(["mape", "mae"], ascending=[True, True]).iloc[0]
    cand = df[df["decision"].isin(["GREEN", "YELLOW"])]
    if not cand.empty:
        return cand.sort_values(["mape", "mae"], ascending=[True, True]).iloc[0]
    return df.sort_values(["mape", "mae"], ascending=[True, True]).iloc[0]


def main():
    args = parse_args()
    path = Path(args.summary_csv)
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)
    df = df[df["symbol"].astype(str) == str(args.symbol)]
    if df.empty:
        raise ValueError(f"No rows for symbol={args.symbol} in {path}")

    row = choose_row(df, args.prefer)
    lb = int(row["lookback"])
    pl = int(row["pred_len"])
    dec = str(row.get("decision", "NA"))

    # shell-friendly 输出
    print(f"RECO_LOOKBACK={lb}")
    print(f"RECO_PRED_LEN={pl}")
    print(f"RECO_DECISION={dec}")
    print(f"RECO_SRC_FILE={path}")


if __name__ == "__main__":
    main()
