#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


def parse_args():
    p = argparse.ArgumentParser(description="Aggregate validation eval csv files into one decision report")
    p.add_argument("--symbol", required=True)
    p.add_argument("--input-dir", required=True)
    p.add_argument("--out-csv", required=True)
    p.add_argument("--out-md", required=True)
    return p.parse_args()


def decision(row: pd.Series) -> str:
    mae_better = row["mae"] < row["baseline_mae"]
    mape_better = row["mape"] < row["baseline_mape"]
    dir_good = row["dir_acc_pct"] >= 55
    if mae_better and mape_better and dir_good:
        return "GREEN"
    if (not mae_better) and (not mape_better) and row["dir_acc_pct"] < 50:
        return "RED"
    return "YELLOW"


def main():
    args = parse_args()
    in_dir = Path(args.input_dir)
    files = sorted(in_dir.glob(f"{args.symbol}_eval_lb*_pl*.csv"))
    if not files:
        raise FileNotFoundError(f"No eval files found in {in_dir}")

    rows = []
    for f in files:
        df = pd.read_csv(f)
        s = df[df["cut_date"] == "SUMMARY"]
        if s.empty:
            continue
        r = s.iloc[0].to_dict()
        name = f.stem
        # filename pattern: SYMBOL_eval_lb{lb}_pl{pl}
        try:
            lb = int(name.split("_lb")[1].split("_pl")[0])
            pl = int(name.split("_pl")[1])
        except Exception:
            lb, pl = None, None
        r["lookback"] = lb
        r["pred_len"] = pl
        r["file"] = f.name
        rows.append(r)

    res = pd.DataFrame(rows)
    if res.empty:
        raise ValueError("No SUMMARY rows found")

    res = res[["symbol", "lookback", "pred_len", "horizon", "mae", "mape", "dir_acc_pct", "baseline_mae", "baseline_mape", "model_used", "file"]]
    res["mae_win"] = res["mae"] < res["baseline_mae"]
    res["mape_win"] = res["mape"] < res["baseline_mape"]
    res["decision"] = res.apply(decision, axis=1)

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out_csv, index=False)

    green = int((res["decision"] == "GREEN").sum())
    yellow = int((res["decision"] == "YELLOW").sum())
    red = int((res["decision"] == "RED").sum())
    total = len(res)

    overall = "YELLOW"
    if green / total >= 0.6:
        overall = "GREEN"
    elif red / total >= 0.5:
        overall = "RED"

    best = res.sort_values(["mape", "mae"], ascending=[True, True]).iloc[0]

    md = Path(args.out_md)
    md.write_text(
        "\n".join([
            f"# {args.symbol} Validation Suite 报告",
            "",
            f"- 总组合数: {total}",
            f"- GREEN: {green}",
            f"- YELLOW: {yellow}",
            f"- RED: {red}",
            f"- 总体评级: **{overall}**",
            "",
            "## 最优参数（按 MAPE/MAE）",
            f"- lookback={int(best['lookback'])}, pred_len={int(best['pred_len'])}",
            f"- MAE={best['mae']:.6f}, baseline_MAE={best['baseline_mae']:.6f}",
            f"- MAPE={best['mape']:.6f}%, baseline_MAPE={best['baseline_mape']:.6f}%",
            f"- 方向准确率={best['dir_acc_pct']:.2f}%",
            f"- 单项评级={best['decision']}",
            "",
            "## 小白结论",
            "- GREEN：可逐步提高模型信号权重（仍需风控）。",
            "- YELLOW：维持轻仓观察，继续收集窗口数据。",
            "- RED：不建议依赖该参数组做交易决策。",
            "",
            f"明细见：`{out_csv.name}`",
        ]),
        encoding="utf-8",
    )

    print(f"[OK] summary_csv={out_csv}")
    print(f"[OK] report_md={md}")


if __name__ == "__main__":
    main()
