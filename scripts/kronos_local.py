#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd


OHLCV = ["open", "high", "low", "close", "volume"]


@dataclass
class ForecastConfig:
    symbol: str
    start: str
    end: Optional[str] = None
    lookback: int = 400
    pred_len: int = 20
    model_name: str = "NeoQuasar/Kronos-small"
    tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base"
    source: str = "auto"  # auto|akshare|yfinance


def _to_yf_symbol(symbol: str) -> str:
    if symbol.endswith((".SS", ".SZ")):
        return symbol
    return f"{symbol}.SS" if symbol.startswith("6") else f"{symbol}.SZ"


def fetch_data(symbol: str, start: str, end: Optional[str] = None, source: str = "auto") -> pd.DataFrame:
    errors = []

    def _try_akshare() -> pd.DataFrame:
        import akshare as ak

        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start.replace('-', ''), end_date=(end or "").replace('-', ''), adjust="qfq")
        # expected Chinese columns from akshare
        rename_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        df = df.rename(columns=rename_map)
        cols = ["date", "open", "high", "low", "close", "volume"]
        miss = [c for c in cols if c not in df.columns]
        if miss:
            raise ValueError(f"akshare columns missing: {miss}")
        out = df[cols].copy()
        out["date"] = pd.to_datetime(out["date"])
        out = out.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        return out

    def _try_yf() -> pd.DataFrame:
        import yfinance as yf

        yf_symbol = _to_yf_symbol(symbol)
        hist = yf.Ticker(yf_symbol).history(start=start, end=end, auto_adjust=False)
        if hist is None or hist.empty:
            raise ValueError(f"yfinance empty for {yf_symbol}")
        hist = hist.reset_index()
        out = pd.DataFrame({
            "date": pd.to_datetime(hist["Date"]),
            "open": hist["Open"].astype(float),
            "high": hist["High"].astype(float),
            "low": hist["Low"].astype(float),
            "close": hist["Close"].astype(float),
            "volume": hist["Volume"].astype(float),
        })
        out = out.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        return out

    order = [source] if source in {"akshare", "yfinance"} else ["akshare", "yfinance"]
    for s in order:
        try:
            if s == "akshare":
                return _try_akshare()
            if s == "yfinance":
                return _try_yf()
        except Exception as e:
            errors.append(f"{s}: {e}")

    raise RuntimeError("Failed to fetch data. " + " | ".join(errors))


def _load_predictor(model_name: str, tokenizer_name: str):
    import torch

    # allow scripts/ under repo root
    root = Path(__file__).resolve().parents[1]
    import sys
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from model import Kronos, KronosTokenizer, KronosPredictor

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
    model = Kronos.from_pretrained(model_name)
    model = model.to("cpu")
    model.eval()
    predictor = KronosPredictor(model, tokenizer, max_context=512)
    return predictor


def make_future_dates(last_date: pd.Timestamp, pred_len: int) -> pd.DatetimeIndex:
    # A-share daily calendar fallback: business days
    return pd.bdate_range(last_date + pd.Timedelta(days=1), periods=pred_len)


def forecast(df: pd.DataFrame, cfg: ForecastConfig) -> Tuple[pd.DataFrame, str]:
    if len(df) < max(60, cfg.lookback // 2):
        raise ValueError(f"Not enough rows: {len(df)}")

    x = df.tail(cfg.lookback).copy()
    x_ts = pd.Series(pd.to_datetime(x["date"]))
    y_ts = pd.Series(make_future_dates(x_ts.iloc[-1], cfg.pred_len))

    x_df = x[["open", "high", "low", "close", "volume"]].copy()
    x_df["amount"] = 0.0

    used = "kronos"
    try:
        predictor = _load_predictor(cfg.model_name, cfg.tokenizer_name)
        pred = predictor.predict(
            df=x_df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=cfg.pred_len,
            T=1.0,
            top_p=0.9,
            sample_count=1,
        )
        pred = pred.reset_index(drop=True)
        out = pd.DataFrame({"date": y_ts, "open": pred["open"], "high": pred["high"], "low": pred["low"], "close": pred["close"]})
    except Exception:
        # deterministic fallback for continuity (keeps scripts runnable)
        used = "naive_lastbar"
        last = x.iloc[-1]
        out = pd.DataFrame({
            "date": y_ts,
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
        })

    return out, used
