#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from kronos_local import ForecastConfig, fetch_data, forecast


def parse_args():
    p = argparse.ArgumentParser(description="Run Kronos forecast for one symbol")
    p.add_argument("--symbol", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", default=None)
    p.add_argument("--lookback", type=int, default=400)
    p.add_argument("--pred-len", type=int, default=20)
    p.add_argument("--source", choices=["auto", "akshare", "yfinance"], default="auto")
    p.add_argument("--model-name", default="NeoQuasar/Kronos-small")
    p.add_argument("--tokenizer-name", default="NeoQuasar/Kronos-Tokenizer-base")
    p.add_argument("--out", required=True)
    p.add_argument("--plot", default=None)
    return p.parse_args()


def main():
    args = parse_args()
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

    df = fetch_data(cfg.symbol, cfg.start, cfg.end, cfg.source)
    pred, used_model = forecast(df, cfg)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pred.to_csv(out_path, index=False)

    if args.plot:
        plot_path = Path(args.plot)
        plot_path.parent.mkdir(parents=True, exist_ok=True)

        tail = df.tail(80).copy()
        tail["date"] = pd.to_datetime(tail["date"])

        plt.figure(figsize=(10, 5))
        plt.plot(tail["date"], tail["close"], label="history_close")
        plt.plot(pd.to_datetime(pred["date"]), pred["close"], label=f"forecast_close ({used_model})")
        plt.title(f"{cfg.symbol} forecast")
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()

    print(f"[OK] symbol={cfg.symbol} rows={len(df)} pred_len={len(pred)} model={used_model} out={out_path}")


if __name__ == "__main__":
    main()
