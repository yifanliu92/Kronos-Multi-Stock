#!/usr/bin/env python3
import os
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf

from model import Kronos, KronosTokenizer, KronosPredictor


def fetch_ohlcv(symbol: str, period: str = "5d", interval: str = "5m") -> pd.DataFrame:
    raw = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"empty data for {symbol}")

    if isinstance(raw.columns, pd.MultiIndex):
        def pick(name):
            for c in raw.columns:
                if c[0] == name:
                    return raw[c]
            raise KeyError(name)
        open_s = pick("Open")
        high_s = pick("High")
        low_s = pick("Low")
        close_s = pick("Close")
        vol_s = pick("Volume")
    else:
        open_s = raw["Open"]
        high_s = raw["High"]
        low_s = raw["Low"]
        close_s = raw["Close"]
        vol_s = raw["Volume"]

    ts = raw.index
    if getattr(ts, "tz", None) is not None:
        ts = ts.tz_convert(None)

    df = pd.DataFrame({
        "timestamps": pd.to_datetime(ts),
        "open": pd.to_numeric(open_s, errors="coerce"),
        "high": pd.to_numeric(high_s, errors="coerce"),
        "low": pd.to_numeric(low_s, errors="coerce"),
        "close": pd.to_numeric(close_s, errors="coerce"),
        "volume": pd.to_numeric(vol_s, errors="coerce").fillna(0),
    })
    df["amount"] = 0.0
    df = df.dropna(subset=["timestamps", "open", "high", "low", "close"]).reset_index(drop=True)
    return df


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    mape = float(np.mean(np.abs((y_true - y_pred) / np.clip(np.abs(y_true), 1e-8, None))) * 100)

    # direction accuracy based on first differences
    if len(y_true) > 1:
        d_true = np.sign(np.diff(y_true))
        d_pred = np.sign(np.diff(y_pred))
        dir_acc = float(np.mean(d_true == d_pred) * 100)
    else:
        dir_acc = float("nan")

    return {"mae": mae, "mape_pct": mape, "direction_acc_pct": dir_acc}


def run_one(symbol: str, predictor: KronosPredictor, out_root: Path):
    df = fetch_ohlcv(symbol)
    n = len(df)
    lookback = min(200, max(60, int(n * 0.7)))
    pred_len = min(60, n - lookback)
    if pred_len <= 1:
        raise RuntimeError(f"not enough rows for {symbol}, n={n}")

    x_df = df.loc[:lookback - 1, ["open", "high", "low", "close"]]
    x_timestamp = df.loc[:lookback - 1, "timestamps"]
    y_timestamp = df.loc[lookback:lookback + pred_len - 1, "timestamps"]

    pred_df = predictor.predict(
        df=x_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=1,
        verbose=False,
    )

    y_true = df.loc[lookback:lookback + pred_len - 1, "close"].to_numpy(dtype=float)
    y_pred = pred_df["close"].to_numpy(dtype=float)

    base_pred = np.full_like(y_true, fill_value=float(x_df["close"].iloc[-1]))

    m_model = metrics(y_true, y_pred)
    m_base = metrics(y_true, base_pred)

    out_dir = out_root / symbol.replace(".", "_")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save CSV
    save_df = pd.DataFrame({
        "timestamps": y_timestamp.values,
        "true_close": y_true,
        "pred_close": y_pred,
        "baseline_close": base_pred,
    })
    save_df.to_csv(out_dir / "pred_df.csv", index=False)

    # Save plot
    plt.figure(figsize=(10, 4))
    plt.plot(save_df["timestamps"], save_df["true_close"], label="Ground Truth", linewidth=1.5)
    plt.plot(save_df["timestamps"], save_df["pred_close"], label="Prediction", linewidth=1.5)
    plt.plot(save_df["timestamps"], save_df["baseline_close"], label="Naive Baseline", linestyle="--", linewidth=1.2)
    plt.title(f"{symbol} | lookback={lookback}, pred_len={pred_len}")
    plt.xticks(rotation=20)
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "plot.png", dpi=150)
    plt.close()

    result = {
        "symbol": symbol,
        "rows": int(n),
        "lookback": int(lookback),
        "pred_len": int(pred_len),
        "model": m_model,
        "baseline": m_base,
        "out_dir": str(out_dir),
    }
    with open(out_dir / "eval.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def main():
    symbols_env = os.getenv("SYMBOLS", "600977.SS,300418.SZ,000001.SZ")
    symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]
    out_root = Path(os.getenv("OUT_DIR", "outputs"))
    out_root.mkdir(parents=True, exist_ok=True)

    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

    all_results = []
    for s in symbols:
        try:
            r = run_one(s, predictor, out_root)
            all_results.append(r)
            print(f"[OK] {s}: MAE={r['model']['mae']:.4f}, MAPE={r['model']['mape_pct']:.2f}%, DIR={r['model']['direction_acc_pct']:.2f}%")
            print(f"     baseline: MAE={r['baseline']['mae']:.4f}, MAPE={r['baseline']['mape_pct']:.2f}%, DIR={r['baseline']['direction_acc_pct']:.2f}%")
        except Exception as e:
            print(f"[FAIL] {s}: {e}")

    with open(out_root / "summary.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\nSaved summary: {out_root / 'summary.json'}")


if __name__ == "__main__":
    main()
