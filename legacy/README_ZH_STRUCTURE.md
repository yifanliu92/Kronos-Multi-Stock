# Kronos 项目阅读地图（中文注释版）

> 目的：给 Pacino 快速看懂“每个文件夹/文件是干什么的”，避免在仓库里迷路。  
> 适用：`/Users/wxo/Desktop/Kronos`

---

## 0. 一句话先看懂

这个项目可以分成 3 层：

1. **模型核心层**（Kronos 模型与Tokenizer）
2. **运行脚本层**（你直接执行的 forecast/eval/report 脚本）
3. **结果产出层**（outputs 里的 csv/png/md 报告）

你现在主要用的是 **第2层 + 第3层**。

---

## 1. 顶层常见文件/目录说明

## `README.md`
- 官方原始说明（英文）
- 介绍 Kronos 是什么、怎么加载模型、怎么做预测
- 偏“项目介绍”，不够贴合你当前 A 股落地流程

## `requirements.txt`（若存在）
- Python 依赖清单
- `pip install -r requirements.txt` 会按这个安装

## `model.py` / `model/`（按仓库版本可能是文件或目录）
- Kronos 模型定义与加载逻辑
- 我们脚本最终会调用这里

## `figures/`
- README 用的图片资源目录
- 不影响模型运行

## `examples/`
- 官方示例脚本
- 用于理解 API，不一定直接适配你当前 A 股流程

## `finetune/`（若存在）
- 微调训练相关代码
- 你当前阶段（先跑推理/评估）可以先不碰

## `data/`（若存在）
- 示例数据目录
- 你现在主要走 AkShare/yfinance 动态抓取，不依赖静态 data

## `outputs/`
- **最重要结果目录**
- 每次运行会创建一个时间戳子目录，里面包含：
  - `*_forecast.csv`（预测结果）
  - `*_eval.csv`（评估结果）
  - `*_forecast.png`（预测图）
  - `*_recent5_report.md`（分析报告）
  - `*_recent5_*.png`（报告图）

---

## 2. 你当前核心脚本（重点）

## `run_pair.sh`
- 批量跑多个股票（默认 `603305 002049`）
- 对每个股票依次执行：
  1) `scripts/run_forecast.py`
  2) `scripts/run_eval.py`
- 最后输出成功/失败汇总

## `run_603305_recent5_report.sh`
- 你当前最常用的一键入口
- 固定只跑 `603305`
- 预测步长默认 5 天（`pred_len=5`）
- 自动生成：预测 + 评估 + 报告 + 图表

## `INVEST_TERMS_ZH.md`
- 术语词典（baseline/MAE/MAPE/方向准确率等）
- 给投资小白随时查概念

---

## 3. `scripts/` 目录文件说明

## `scripts/kronos_local.py`
- 本地统一能力层（底层工具模块）
- 负责：
  - 抓数据（AkShare 优先，失败回退 yfinance）
  - 统一字段清洗（date/open/high/low/close/volume）
  - 调用 Kronos 推理
  - 推理失败时兜底（naive_lastbar），保证流程不断

## `scripts/run_forecast.py`
- 单标的预测脚本
- 输入：symbol/start/end/lookback/pred_len
- 输出：`*_forecast.csv`，可选 `*_forecast.png`

## `scripts/run_eval.py`
- 滚动评估脚本
- 计算：
  - MAE
  - MAPE
  - dir_acc_pct（方向准确率）
  - baseline 对比
- 输出：`*_eval.csv`（包含 SUMMARY）

## `scripts/report_recent5.py`
- 最近5天报告生成器
- 读取 forecast/eval + 历史数据，产出：
  - `*_recent5_report.md`
  - `*_recent5_trend.png`
  - `*_recent5_returns.png`

---

## 4. 结果文件怎么读（小白版）

## `*_forecast.csv`
- 看未来每一天的预测价格（open/high/low/close）
- 先看 close 列即可

## `*_eval.csv`
- 看模型是否靠谱
- 关键看：
  - MAE/MAPE 是否低于 baseline（低=更好）
  - dir_acc_pct 是否长期 >55%
  - `SUMMARY` 行是平均表现

## `*_recent5_report.md`
- 给人看的文字版总结
- 包含运行范围、关键信号、回测结论和图表索引

## `*_trend.png`
- 历史价格 + 未来5天预测走势

## `*_returns.png`
- 最近5天日涨跌柱状图（红跌绿涨）

---

## 5. 推荐阅读顺序（最快上手）

1. 先看 `run_603305_recent5_report.sh`（你执行入口）
2. 再看 `scripts/run_forecast.py`（怎么预测）
3. 再看 `scripts/run_eval.py`（怎么评价好坏）
4. 最后看 `scripts/report_recent5.py`（怎么生成报告）
5. 概念不懂就查 `INVEST_TERMS_ZH.md`

---

## 6. 常用命令（复制即用）

```bash
cd /Users/wxo/Desktop/Kronos
bash run_603305_recent5_report.sh
```

查看最新输出目录：

```bash
cd /Users/wxo/Desktop/Kronos
ls -lt outputs | head
```

打开某次结果：

```bash
open /Users/wxo/Desktop/Kronos/outputs/你的时间戳目录
```

---

## 7. 给未来自己的备注

- 你当前策略是“先保证稳定跑通，再逐步提高准确率”。
- 单次结果只做参考，不要重仓依赖。
- 重点看“是否持续跑赢 baseline”，而不是看某一次预测是否刚好猜中。
