#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from kronos_local import ForecastConfig, fetch_data, forecast


def parse_args():
    p = argparse.ArgumentParser(description="Rolling evaluation for one symbol")
    p.add_argument("--symbol", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", default=None)
    p.add_argument("--lookback", type=int, default=400)
    p.add_argument("--pred-len", type=int, default=20)
    p.add_argument("--stride", type=int, default=20)
    p.add_argument("--max-windows", type=int, default=12)
    p.add_argument("--source", choices=["auto", "akshare", "yfinance"], default="auto")
    p.add_argument("--model-name", default="NeoQuasar/Kronos-small")
    p.add_argument("--tokenizer-name", default="NeoQuasar/Kronos-Tokenizer-base")
    p.add_argument("--out", required=True)
    return p.parse_args()


def _mape(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.where(np.abs(y_true) < 1e-9, np.nan, np.abs(y_true))
    return float(np.nanmean(np.abs((y_true - y_pred) / denom)) * 100)


def main():
    args = parse_args()

    df = fetch_data(args.symbol, args.start, args.end, args.source)
    df = df.sort_values("date").reset_index(drop=True)

    n = len(df)
    min_need = args.lookback + args.pred_len
    if n < min_need:
        raise ValueError(f"Not enough rows for eval: n={n}, need>={min_need}")

    starts = list(range(args.lookback, n - args.pred_len + 1, args.stride))
    if args.max_windows > 0:
        starts = starts[-args.max_windows:]

    rows = []
    model_used_set = set()

    for cut in starts:
        hist = df.iloc[:cut].copy()
        future = df.iloc[cut : cut + args.pred_len].copy()

        cfg = ForecastConfig(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            lookback=args.lookback,
            pred_len=args.pred_len,
            source=args.source,
            model_name=args.model_name,
            tokenizer_name=args.tokenizer_name,
        )
        pred, used_model = forecast(hist, cfg)
        model_used_set.add(used_model)

        y_true = future["close"].to_numpy(dtype=float)
        y_pred = pred["close"].to_numpy(dtype=float)[: len(y_true)]

        last_close = float(hist.iloc[-1]["close"])
        y_base = np.full_like(y_true, fill_value=last_close, dtype=float)

        mae = float(np.mean(np.abs(y_true - y_pred)))
        mape = _mape(y_true, y_pred)
        base_mae = float(np.mean(np.abs(y_true - y_base)))
        base_mape = _mape(y_true, y_base)

        d_true = np.sign(np.diff(np.r_[last_close, y_true]))
        d_pred = np.sign(np.diff(np.r_[last_close, y_pred]))
        dir_acc = float(np.mean(d_true == d_pred) * 100)

        rows.append(
            {
                "symbol": args.symbol,
                "cut_date": str(pd.to_datetime(hist.iloc[-1]["date"]).date()),
                "horizon": len(y_true),
                "mae": mae,
                "mape": mape,
                "dir_acc_pct": dir_acc,
                "baseline_mae": base_mae,
                "baseline_mape": base_mape,
                "model_used": used_model,
            }
        )

    res = pd.DataFrame(rows)
    summary = {
        "symbol": args.symbol,
        "cut_date": "SUMMARY",
        "horizon": int(res["horizon"].mean()),
        "mae": float(res["mae"].mean()),
        "mape": float(res["mape"].mean()),
        "dir_acc_pct": float(res["dir_acc_pct"].mean()),
        "baseline_mae": float(res["baseline_mae"].mean()),
        "baseline_mape": float(res["baseline_mape"].mean()),
        "model_used": ",".join(sorted(model_used_set)),
    }
    res = pd.concat([res, pd.DataFrame([summary])], ignore_index=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out_path, index=False)

    print(f"[OK] symbol={args.symbol} windows={len(rows)} out={out_path}")
    print(res.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
