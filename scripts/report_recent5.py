#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from kronos_local import fetch_data


def parse_args():
    p = argparse.ArgumentParser(description="Generate recent-5-days analysis report with charts (annotated glossary version)")
    p.add_argument("--symbol", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", default=None)
    p.add_argument("--source", choices=["auto", "akshare", "yfinance"], default="auto")
    p.add_argument("--forecast-csv", required=True)
    p.add_argument("--eval-csv", required=True)
    p.add_argument("--out-dir", required=True)
    return p.parse_args()


def _safe_float(x, default=float("nan")):
    try:
        return float(x)
    except Exception:
        return default


def main():
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    hist = fetch_data(args.symbol, args.start, args.end, args.source).sort_values("date").reset_index(drop=True)
    hist["date"] = pd.to_datetime(hist["date"])

    fc = pd.read_csv(args.forecast_csv)
    fc["date"] = pd.to_datetime(fc["date"])

    ev = pd.read_csv(args.eval_csv)
    summary = ev[ev["cut_date"] == "SUMMARY"]
    summary_row = summary.iloc[0] if not summary.empty else None

    # ===== chart 1: history + forecast =====
    htail = hist.tail(60).copy()
    plt.figure(figsize=(10, 5))
    plt.plot(htail["date"], htail["close"], label="history_close (last 60)")
    plt.plot(fc["date"], fc["close"], marker="o", label="forecast_close (next 5)")
    plt.title(f"{args.symbol} Recent trend + 5-day forecast")
    plt.xlabel("date")
    plt.ylabel("price")
    plt.legend()
    plt.tight_layout()
    fig1 = out_dir / f"{args.symbol}_recent5_trend.png"
    plt.savefig(fig1, dpi=150)
    plt.close()

    # ===== chart 2: recent 5 actual daily returns =====
    last6 = hist.tail(6).copy()  # 6 points -> 5 returns
    last6 = last6[["date", "close"]].reset_index(drop=True)
    last6["ret_pct"] = last6["close"].pct_change() * 100
    ret5 = last6.dropna().tail(5)

    plt.figure(figsize=(10, 4))
    colors = ["#2ca02c" if x >= 0 else "#d62728" for x in ret5["ret_pct"]]
    plt.bar(ret5["date"].dt.strftime("%m-%d"), ret5["ret_pct"], color=colors)
    plt.axhline(0, color="black", linewidth=1)
    plt.title(f"{args.symbol} Recent 5 trading days returns (%)")
    plt.xlabel("date")
    plt.ylabel("return %")
    plt.tight_layout()
    fig2 = out_dir / f"{args.symbol}_recent5_returns.png"
    plt.savefig(fig2, dpi=150)
    plt.close()

    # ===== metrics =====
    latest_close = _safe_float(hist.iloc[-1]["close"]) if len(hist) else float("nan")
    fc_start = _safe_float(fc.iloc[0]["close"]) if len(fc) else float("nan")
    fc_end = _safe_float(fc.iloc[-1]["close"]) if len(fc) else float("nan")
    fc_delta_pct = ((fc_end - latest_close) / latest_close * 100.0) if latest_close == latest_close and latest_close != 0 else float("nan")

    mae = _safe_float(summary_row["mae"]) if summary_row is not None else float("nan")
    mape = _safe_float(summary_row["mape"]) if summary_row is not None else float("nan")
    dir_acc = _safe_float(summary_row["dir_acc_pct"]) if summary_row is not None else float("nan")
    base_mae = _safe_float(summary_row["baseline_mae"]) if summary_row is not None else float("nan")
    base_mape = _safe_float(summary_row["baseline_mape"]) if summary_row is not None else float("nan")

    perf_lines = []
    if mae == mae and base_mae == base_mae:
        perf_lines.append(f"- MAE（平均每天差多少钱）对比：Kronos={mae:.6f} vs Baseline={base_mae:.6f}（{'更优' if mae < base_mae else '偏弱'}）")
    if mape == mape and base_mape == base_mape:
        perf_lines.append(f"- MAPE（平均百分比误差）对比：Kronos={mape:.6f}% vs Baseline={base_mape:.6f}%（{'更优' if mape < base_mape else '偏弱'}）")
    if dir_acc == dir_acc:
        perf_lines.append(f"- 方向准确率（猜涨跌命中率）：{dir_acc:.2f}%（{'高于随机' if dir_acc >= 50 else '低于50%'}）")

    signal_level = "黄灯"
    if mae == mae and base_mae == base_mae and mape == mape and base_mape == base_mape and dir_acc == dir_acc:
        if (mae < base_mae) and (mape < base_mape) and (dir_acc >= 55):
            signal_level = "绿灯"
        elif (mae > base_mae) and (mape > base_mape) and (dir_acc < 50):
            signal_level = "红灯"

    # ===== markdown report (annotated) =====
    report = out_dir / f"{args.symbol}_recent5_report.md"
    report.write_text(
        "\n".join([
            f"# {args.symbol} 最近5天分析报告（术语注释版）",
            "",
            "## 1) 运行范围",
            f"- 历史数据区间：{args.start} ~ {args.end or 'latest'}",
            f"- 预测步长（pred_len）：5个交易日",
            f"- 数据源：{args.source}（auto=AkShare优先，失败回退yfinance）",
            "",
            "## 2) 关键信号（小白直读）",
            f"- 最新收盘价：{latest_close:.4f}",
            f"- 预测首日收盘价：{fc_start:.4f}",
            f"- 预测第5日收盘价：{fc_end:.4f}",
            f"- 预测5日相对最新收盘涨跌：{fc_delta_pct:.2f}%",
            "",
            "## 3) 回测评估（最近窗口）",
            *perf_lines,
            "",
            "## 4) 决策灯（自动）",
            f"- 当前信号：**{signal_level}**",
            "- 绿灯：精度优于baseline + 方向率较高，可提高参考权重",
            "- 黄灯：部分指标一般，轻仓观察",
            "- 红灯：精度弱且方向率差，保守为主",
            "",
            "## 5) 图表",
            f"- 趋势图：`{fig1.name}`",
            f"- 最近5日涨跌柱状图：`{fig2.name}`",
            "",
            "## 6) 术语注释（边读边解释）",
            "- baseline（基线）：最简单参考法，常可理解为“未来按最新收盘价不变”。",
            "- MAE：平均绝对误差，表示平均每天差多少钱（越小越好）。",
            "- MAPE：平均绝对百分比误差，表示平均偏差占比（越小越好）。",
            "- 方向准确率：只看涨跌方向是否猜对（长期持续 >55% 才更有参考价值）。",
            "- lookback：每次预测前回看多少历史数据。",
            "- pred_len：一次预测未来多少个交易日。",
            "",
            "## 7) 结论（机器生成）",
            "- 若 MAE/MAPE 持续高于 baseline，说明该标的近期更适合保守策略（降低信号权重）。",
            "- 若方向准确率持续高于 50%，可继续观察多窗口稳定性再决定是否加权使用。",
            "",
            "> 备注：完整术语表可见项目根目录 `INVEST_TERMS_ZH.md`。",
        ]),
        encoding="utf-8",
    )

    print(f"[OK] report={report}")
    print(f"[OK] figure={fig1}")
    print(f"[OK] figure={fig2}")


if __name__ == "__main__":
    main()
