#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from short_cost_calculator import (
    calculate_short_pnl,
    calculate_accrued_short_interest,
    calculate_oldest_open_short_days,
)

# ---- KRONOS_DONE_MARKER_GUARD_V1 ----
# Best-effort done marker for successful natural cron reports.
# Does not run in manual rehearsal. Does not fabricate reports.
def _kronos_done_marker_guard_v1():
    try:
        import os as _os
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        if _os.environ.get("KRONOS_MANUAL_REHEARSAL") == "true":
            return
        if _os.environ.get("KRONOS_NOT_NATURAL_CRON") == "true":
            return
        if _os.environ.get("KRONOS_NOT_FOR_SAMPLE_QUALITY") == "true":
            return

        out = _Path("/Users/yifliu/Kronos-603305/guard_outputs")
        if not out.exists():
            return

        now = _time.time()

        # Only mark checks generated recently by the current natural run.
        for check in out.glob("check_*.json"):
            try:
                if now - check.stat().st_mtime > 600:
                    continue

                data = _json.loads(check.read_text(encoding="utf-8"))
                slot_ts = data.get("slot_ts") or check.stem.replace("check_", "")
                if not slot_ts:
                    continue

                if data.get("report_generation_failed") is True:
                    continue
                if data.get("errors"):
                    continue

                report = out / f"report_{slot_ts}.txt"
                if not report.exists():
                    continue

                done = out / f"{slot_ts}.done"
                if done.exists():
                    continue

                done_payload = {
                    "slot_ts": slot_ts,
                    "report_file": str(report),
                    "check_file": str(check),
                    "manual_triggered": False,
                    "natural_cron_done_marker": True,
                    "created_by": "KRONOS_DONE_MARKER_GUARD_V1",
                    "created_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                done.write_text(_json.dumps(done_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                continue
    except Exception:
        return

try:
    import atexit as _kronos_atexit
    _kronos_atexit.register(_kronos_done_marker_guard_v1)
except Exception:
    pass
# ---- END KRONOS_DONE_MARKER_GUARD_V1 ----


BASE = Path('/Users/yifliu/Kronos-603305')
SIM = BASE / 'simulate_position_603305.py'
SHADOW_SIM = BASE / 'simulate_position_603305_shadow.py'
STATE = BASE / 'sim_state_603305.json'
SHADOW_STATE = BASE / 'shadow_state_603305.json'
LOG = BASE / 'sim_trades_603305.jsonl'
SHADOW_LOG = BASE / 'shadow_trades_603305.jsonl'
OUTDIR = BASE / 'guard_outputs'
OUTDIR.mkdir(parents=True, exist_ok=True)
SLOTDIR = OUTDIR / 'slots'
SLOTDIR.mkdir(parents=True, exist_ok=True)

TEMPLATE_KEYS = [
    '时间：', '标的：', '启动资金：', '即时价格：', '行情：', '信号：', '动作：', '模拟仓位：', '理由：',
    '建仓明细（主策略，沿用既有持仓）：', '建仓均价（加权）：', '毛浮盈（未扣成本）：', '净浮盈（含累计成本）：',
    '主策略持仓口径（已体现交易成本）', '• 持仓市值：', '• 持仓成本（含累计交易成本）：', '• 持仓净值差额：',
    '成本明细（累计）：', '【影子策略 v1.1-shadow（触发即模拟成交）】', '建仓明细（影子策略，沿用既有持仓）：',
    '影子策略持仓口径（已体现交易成本）', '• 持仓仓位：', '• 持仓市值：', '• 持仓成本（含累计交易成本）：',
    '• 持仓净值差额：', '• 主策略本时点是否新增触发：', '• 影子策略本时点是否新增触发：'
]


def run_sim() -> str:
    # 同一触发时点：主策略 + 影子策略同时执行
    p_main = subprocess.run(['python3', str(SIM)], capture_output=True, text=True)
    p_shadow = subprocess.run(['python3', str(SHADOW_SIM)], capture_output=True, text=True)

    out_main = (p_main.stdout or '').strip() or (p_main.stderr or '').strip()
    out_shadow = (p_shadow.stdout or '').strip() or (p_shadow.stderr or '').strip()

    # 主输出继续沿用主策略文本，影子执行结果用于诊断时附加
    if p_main.returncode != 0 or p_shadow.returncode != 0:
        return f"MAIN_RC={p_main.returncode} SHADOW_RC={p_shadow.returncode}\nMAIN_OUT:\n{out_main}\n\nSHADOW_OUT:\n{out_shadow}"
    return out_main


def latest_trade(path=LOG):
    if not path.exists():
        return None
    lines = path.read_text(encoding='utf-8').strip().splitlines()
    if not lines:
        return None
    return json.loads(lines[-1])

def latest_effective_trade_text(path=SHADOW_LOG):
    if not path.exists():
        return None
    lines = path.read_text(encoding='utf-8').strip().splitlines()
    for line in reversed(lines):
        try:
            r = json.loads(line)
        except Exception:
            continue
        action = str(r.get('action','')).strip()
        if action and action != '持仓不变':
            ts = r.get('ts','未知时间')
            pf = r.get('position_from','?')
            pt = r.get('position_to','?')
            px = r.get('price','?')
            return f"{ts}：{pf}% → {pt}%（{px}）"
    return None



# ---- KRONOS_REPORT_SHORT_INTEREST_V2 ----
def _kronos_weighted_short_avg_v2(lots) -> float:
    """按空头 lot 名义本金加权计算开仓均价，仅用于 MTM 展示。"""

    total_notional = 0.0
    weighted_sum = 0.0

    for lot in lots or []:
        notional = float(lot.get("notional") or 0.0)
        price = float(lot.get("price") or 0.0)

        if notional <= 0 or price <= 0:
            continue

        total_notional += notional
        weighted_sum += notional * price

    if total_notional <= 0:
        return 0.0

    return weighted_sum / total_notional


def _kronos_short_interest_snapshot_v2(state, as_of_ts: str) -> dict:
    """读取 state 中的逐 lot 融券利息快照。

    - accrued_interest：未平仓应计利息，不写入累计成本；
    - settled_interest_total：已结算利息累计，已在平仓时写入成本；
    - oldest_open_short_days：最早未平仓 lot 的自然日持有天数。
    """

    lots = state.get("lot_book_short") or []
    rate = float(state.get("short_interest_rate", 0.10) or 0.10)

    try:
        accrued = calculate_accrued_short_interest(
            lots=lots,
            as_of_ts=as_of_ts,
            interest_rate=rate,
        )

        days_display = calculate_oldest_open_short_days(
            lots=lots,
            as_of_ts=as_of_ts,
        )

        return {
            "metric_status": "OK",
            "error": "",
            "accrued_interest": float(
                accrued.get("accrued_interest", 0.0) or 0.0
            ),
            "accrued_breakdown": accrued.get("breakdown", []),
            "open_lot_count": int(
                accrued.get("open_lot_count", 0) or 0
            ),
            "settled_interest_total": float(
                state.get("settled_short_interest_total", 0.0)
                or 0.0
            ),
            "oldest_open_short_days": int(days_display),
            "history_status": str(
                state.get(
                    "short_interest_history_status",
                    "UNBACKFILLED_PRE_V2",
                )
            ),
            "accounting_version": str(
                state.get(
                    "short_interest_accounting_version",
                    "lot_v2",
                )
            ),
            "as_of_ts": as_of_ts,
        }

    except Exception as e:
        return {
            "metric_status": "INVALID",
            "error": f"{e.__class__.__name__}: {e}",
            "accrued_interest": 0.0,
            "accrued_breakdown": [],
            "open_lot_count": len(lots),
            "settled_interest_total": float(
                state.get("settled_short_interest_total", 0.0)
                or 0.0
            ),
            "oldest_open_short_days": 0,
            "history_status": str(
                state.get(
                    "short_interest_history_status",
                    "UNBACKFILLED_PRE_V2",
                )
            ),
            "accounting_version": str(
                state.get(
                    "short_interest_accounting_version",
                    "lot_v2",
                )
            ),
            "as_of_ts": as_of_ts,
        }
# ---- END KRONOS_REPORT_SHORT_INTEREST_V2 ----

def format_full(out: str) -> str:
    # 从状态与最近交易补全，禁止“暂无”泛滥
    now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    st = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    tr = latest_trade() or {}

    px = st.get('last_price')
    pos = int(st.get('position_pct', 0) or 0)
    avg_raw = st.get('avg_entry_price')
    cum_cost = float(st.get('cumulative_cost', 0.0) or 0.0)
    entry_t = st.get('entry_time', '未知')
    entry_p = st.get('entry_price', px)

    base = float(st.get('base_capital_cny', 100000) or 100000)
    px = float(px or 0.0)

    main_as_of_ts = str(
        tr.get('ts')
        or st.get('updated_at')
        or now
    )

    avg_source = 'state.avg_entry_price'
    avg = float(avg_raw or 0.0)

    if pos < 0 and avg <= 0:
        avg = _kronos_weighted_short_avg_v2(
            st.get('lot_book_short') or []
        )
        avg_source = 'lot_book_short_weighted'

    main_short_interest = _kronos_short_interest_snapshot_v2(
        state=st,
        as_of_ts=main_as_of_ts,
    )

    main_accrued_short_interest = float(
        main_short_interest.get('accrued_interest', 0.0)
        or 0.0
    )

    main_settled_short_interest_total = float(
        main_short_interest.get('settled_interest_total', 0.0)
        or 0.0
    )

    main_total_cost_including_accrued = (
        cum_cost + main_accrued_short_interest
    )

    if pos < 0:
        short_pnl_pct, short_pnl_amt = calculate_short_pnl(
            avg,
            px,
            pos,
            base,
        )
        gross_pct = short_pnl_pct * 100
    else:
        gross_pct = (
            ((px / avg) - 1.0) * 100
            if (avg and pos != 0)
            else 0.0
        )

    net_pct = (
        gross_pct
        - main_total_cost_including_accrued / base * 100
    )

    market_value = (
        base
        * abs(pos)
        / 100
        * (px / avg if (avg and pos != 0) else 0.0)
    )

    cost_basis = (
        base * abs(pos) / 100
        + main_total_cost_including_accrued
    )

    net_delta = market_value - cost_basis

    reason = tr.get('reason', '按规则执行')
    action = tr.get('action', '持仓不变')
    signal = tr.get('signal', '未知')

    # ========== P0: 满仓锁定一致性修复（报表层兜底） ==========
    # 如果仓位已经满仓（多/空）且 action 仍表达为加仓/增暴露，则强制降级为“满仓锁定拦截”。
    full_lock = abs(pos) >= 100
    if full_lock and any(k in str(action) for k in ['加仓', '开多', '回补', '增加']) and ('IDEMPOTENT_SKIP_FULLY_INVESTED' not in str(action)):
        action = 'IDEMPOTENT_SKIP_FULLY_INVESTED'
        reason = '触发加仓信号，但因满仓锁定规则被拦截，仓位保持不变'

    if action == '持仓不变' and any(k in str(reason) for k in ['加仓', '减仓']):
        reason = '已达仓位上限或无交易触发，本时点持仓不变'

    ts = tr.get('ts', now)

    # 仅使用真实流水作为建仓明细（最多最近3条）：
    # 1) 仅交易时段 09:30-11:30 / 13:00-15:00
    # 2) 必须仓位发生变化（from != to）
    records = []
    if LOG.exists():
        for ln in LOG.read_text(encoding='utf-8').strip().splitlines()[-500:]:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            ts_raw = str(r.get('ts', ''))
            try:
                ts_dt = dt.datetime.strptime(ts_raw, '%Y-%m-%d %H:%M:%S')
                t = ts_dt.time()
            except Exception:
                continue
            # 仅当日记录
            if ts_dt.date() != dt.datetime.now().date():
                continue
            in_am = dt.time(9, 30) <= t <= dt.time(11, 30)
            in_pm = dt.time(13, 0) <= t <= dt.time(15, 0)
            if not (in_am or in_pm):
                continue
            frm = int(r.get('position_from', 0) or 0)
            to = int(r.get('position_to', 0) or 0)
            if frm == to:
                continue
            records.append(r)
    latest3 = records[-3:] if records else []
    if latest3:
        detail_lines = []
        for i, r in enumerate(latest3, 1):
            t = str(r.get('ts', ts))
            frm = int(r.get('position_from', pos))
            to = int(r.get('position_to', pos))
            pxx = float(r.get('price', px) or px)
            detail_lines.append(f"{i}. {t}：{frm}% → {to}%（{pxx:.2f}）")
        details = "\n".join(detail_lines)
    else:
        et = entry_t if isinstance(entry_t, str) and entry_t else now
        details = f"1. {et}：{pos}% → {pos}%（{float(entry_p or px):.2f}）"

    # 从最新交易记录提取行情字段；涨跌幅统一实时重算
    yclose = float(tr.get('prev_close') or tr.get('yclose') or 0.0)
    openp = float(tr.get('open') or tr.get('today_open') or 0.0)
    high = float(tr.get('high') or tr.get('today_high') or 0.0)
    low = float(tr.get('low') or tr.get('today_low') or 0.0)
    avgp = float(tr.get('avg_price') or tr.get('avg') or 0.0)
    chg_pct = ((px - yclose) / yclose * 100.0) if yclose > 0 else 0.0

    shadow = json.loads(SHADOW_STATE.read_text(encoding='utf-8')) if SHADOW_STATE.exists() else {}
    shadow_pos = int(shadow.get('position_pct', 0) or 0)
    shadow_latest = latest_trade(SHADOW_LOG) or {}

    shadow_as_of_ts = str(
        shadow_latest.get('ts')
        or shadow.get('updated_at')
        or now
    )

    shadow_avg_source = 'state.avg_entry_price'
    shadow_avg = float(shadow.get('avg_entry_price') or 0.0)

    if shadow_pos < 0 and shadow_avg <= 0:
        shadow_avg = _kronos_weighted_short_avg_v2(
            shadow.get('lot_book_short') or []
        )
        shadow_avg_source = 'lot_book_short_weighted'

    shadow_short_interest = _kronos_short_interest_snapshot_v2(
        state=shadow,
        as_of_ts=shadow_as_of_ts,
    )

    shadow_accrued_short_interest = float(
        shadow_short_interest.get('accrued_interest', 0.0)
        or 0.0
    )

    shadow_settled_short_interest_total = float(
        shadow_short_interest.get('settled_interest_total', 0.0)
        or 0.0
    )

    shadow_total_cost_including_accrued = (
        float(shadow.get('cumulative_cost', 0.0) or 0.0)
        + shadow_accrued_short_interest
    )

    shadow_last_trade_txt = (
        latest_effective_trade_text(SHADOW_LOG)
        or shadow.get('last_trade')
    )

    main_from = int(tr.get('position_from', pos) or pos)
    main_to = int(tr.get('position_to', pos) or pos)
    main_trigger_flag = '是' if main_from != main_to else '否'

    shadow_from = int(
        shadow_latest.get('position_from', shadow_pos)
        or shadow_pos
    )

    shadow_to = int(
        shadow_latest.get('position_to', shadow_pos)
        or shadow_pos
    )

    shadow_trigger_flag = (
        '是' if shadow_from != shadow_to else '否'
    )

    shadow_base = float(
        shadow.get('base_capital_cny', 100000)
        or 100000
    )

    shadow_cum_cost = float(
        shadow.get('cumulative_cost', 0.0)
        or 0.0
    )

    shadow_cost_basis = (
        shadow_base * abs(shadow_pos) / 100.0
        + shadow_total_cost_including_accrued
    )

    shadow_market_value = (
        shadow_base
        * abs(shadow_pos)
        / 100.0
        * (
            px / shadow_avg
            if (shadow_avg and shadow_pos != 0)
            else 0.0
        )
    )

    shadow_net_delta = (
        shadow_market_value - shadow_cost_basis
    )

    if shadow_pos < 0:
        shadow_short_pnl_pct, _shadow_short_pnl_amt = (
            calculate_short_pnl(
                shadow_avg,
                px,
                shadow_pos,
                shadow_base,
            )
        )
        shadow_gross_pct = shadow_short_pnl_pct * 100
    else:
        shadow_gross_pct = (
            ((px / shadow_avg) - 1.0) * 100
            if (shadow_avg and shadow_pos != 0)
            else 0.0
        )

    shadow_net_pct = (
        shadow_gross_pct
        - shadow_total_cost_including_accrued
        / shadow_base
        * 100
    )

    # 成本明细按当前日志动态累计
    comm = tax = transfer = 0.0
    if LOG.exists():
        for ln in LOG.read_text(encoding='utf-8').strip().splitlines():
            try:
                r = json.loads(ln)
                c = r.get('cost') or {}
                comm += float(c.get('commission', 0.0) or 0.0)
                tax += float(c.get('stamp_tax', 0.0) or 0.0)
                transfer += float(c.get('transfer_fee', 0.0) or 0.0)
            except Exception:
                continue
    total_cost = comm + tax + transfer

    # ========== 成本明细行构建：融券利息 V2 ==========
    # 已结算融券利息仅在真实平空时写入 cumulative_cost。
    # 未平仓应计融券利息仅用于 MTM 展示，不重复写入累计成本。
    cost_line = (
        f"佣金 {comm:.2f}｜"
        f"印花税 {tax:.2f}｜"
        f"过户费 {transfer:.2f}｜"
        f"已结算融券利息累计 "
        f"{main_settled_short_interest_total:.2f}｜"
        f"合计 {cum_cost:.2f} 元"
    )
    # ========== 成本明细行构建结束 ==========

    # 执行口径统一为重算涨跌幅（禁止直用上游pct字段）
    exec_pct = chg_pct

    pos_label = f"{pos}%（多头）" if pos > 0 else ("空仓" if pos == 0 else f"{abs(pos)}%（空头）")
    shadow_pos_label = f"{shadow_pos}%（多头）" if shadow_pos > 0 else ("空仓" if shadow_pos == 0 else f"{abs(shadow_pos)}%（空头）")

    # If any consistency violation is detected, mark REPORT_INCONSISTENT and degrade to signal-only (no position change implied)
    inconsistent = False
    if full_lock and action == 'IDEMPOTENT_SKIP_FULLY_INVESTED':
        inconsistent = False
    # basic delta check
    try:
        pf_chk = int(tr.get('position_from', pos) or pos)
        pt_chk = int(tr.get('position_to', pos) or pos)
        if pf_chk == pt_chk and ('加仓' in str(action) or '减仓' in str(action)):
            inconsistent = True
    except Exception:
        pass

    if inconsistent:
        action = 'REPORT_INCONSISTENT'
        reason = '回报一致性断言失败：仅报告信号，不执行仓位变更'

    text = f'''时间：{ts}
标的：603305 旭升集团
启动资金：{base:,.2f} 元（{base/10000:.0f}万元）
即时价格：{px:.2f}

行情：昨收 {yclose:.2f}｜今开 {openp:.2f}｜最高 {high:.2f}｜最低 {low:.2f}｜均价(近似) {avgp:.2f}
信号：{signal}（现价 {px:.2f}，涨跌幅 {chg_pct:+.2f}%）
动作：{action}
模拟仓位：{pos_label}
理由：{reason}

建仓明细（主策略，沿用既有持仓）：
{details}

建仓均价（加权）：约 {avg:.2f}
毛浮盈（未扣成本）：约 {gross_pct:+.2f}%（约 {base*gross_pct/100:+,.2f} 元）
净浮盈（含累计成本）：约 {net_pct:+.2f}%（约 {base*net_pct/100:+,.2f} 元）

主策略持仓口径（已体现交易成本）
• 持仓市值：{market_value:,.2f} 元
• 持仓成本（含累计交易成本）：{cost_basis:,.2f} 元
• 持仓净值差额：{net_delta:+,.2f} 元

成本明细（累计）：{cost_line}
未平仓应计融券利息（MTM）：主策略 {main_accrued_short_interest:.2f} 元｜影子策略 {shadow_accrued_short_interest:.2f} 元
融券利息历史口径：主策略 {main_short_interest.get('history_status')}｜影子策略 {shadow_short_interest.get('history_status')}

【影子策略 v1.1-shadow（触发即模拟成交）】
建仓明细（影子策略，沿用既有持仓）：
1. {shadow_last_trade_txt or '今日尚无影子成交'}

建仓均价（加权）：约 {shadow_avg:.2f}
毛浮盈（未扣成本）：约 {shadow_gross_pct:+.2f}%（约 {shadow_base*shadow_gross_pct/100:+,.2f} 元）
净浮盈（含累计成本）：约 {shadow_net_pct:+.2f}%（约 {shadow_base*shadow_net_pct/100:+,.2f} 元）

影子策略持仓口径（已体现交易成本）
• 持仓仓位：{shadow_pos_label}
• 持仓市值：{shadow_market_value:,.2f} 元
• 持仓成本（含累计交易成本）：{shadow_cost_basis:,.2f} 元
• 持仓净值差额：{shadow_net_delta:+,.2f} 元
• 主策略本时点是否新增触发：{main_trigger_flag}
• 影子策略本时点是否新增触发：{shadow_trigger_flag}

【审计】满仓锁定: {'true' if abs(pos) >= 99 else 'false'} | 新增资金: 0'''


    # --- MTM audit block (append via replace; no strategy impact) ---
    mtm_missing_fields = []
    if pos != 0 and avg <= 0:
        mtm_missing_fields.append('main_avg_entry_price')
    if shadow_pos != 0 and shadow_avg <= 0:
        mtm_missing_fields.append('shadow_avg_entry_price')
    mtm_metric_status = 'INVALID' if mtm_missing_fields else 'OK'
    mtm_missing_fields_str = ','.join(mtm_missing_fields) if mtm_missing_fields else '-'

    mtm_block = (
        f"【MTM审计字段】\n"
        f"main_mtm_price: {px}\n"
        f"main_mtm_position_pct: {pos}\n"
        f"main_mtm_avg_entry_price: {avg}\n"
        f"main_mtm_cumulative_cost: {cum_cost}\n"
        f"main_mtm_accrued_short_interest: {main_accrued_short_interest}\n"
        f"main_mtm_total_cost_including_accrued: {main_total_cost_including_accrued}\n"
        f"main_mtm_avg_entry_price_source: {avg_source}\n"
        f"main_short_holding_days_display: {main_short_interest.get('oldest_open_short_days')}\n"
        f"main_short_interest_history_status: {main_short_interest.get('history_status')}\n"
        f"main_short_interest_metric_status: {main_short_interest.get('metric_status')}\n"
        f"main_mtm_net_pnl_pct_realtime: {net_pct}\n"
        f"main_mtm_net_delta: {net_delta}\n"
        f"shadow_mtm_price: {px}\n"
        f"shadow_mtm_position_pct: {shadow_pos}\n"
        f"shadow_mtm_avg_entry_price: {shadow_avg}\n"
        f"shadow_mtm_cumulative_cost: {shadow_cum_cost}\n"
        f"shadow_mtm_accrued_short_interest: {shadow_accrued_short_interest}\n"
        f"shadow_mtm_total_cost_including_accrued: {shadow_total_cost_including_accrued}\n"
        f"shadow_mtm_avg_entry_price_source: {shadow_avg_source}\n"
        f"shadow_short_holding_days_display: {shadow_short_interest.get('oldest_open_short_days')}\n"
        f"shadow_short_interest_history_status: {shadow_short_interest.get('history_status')}\n"
        f"shadow_short_interest_metric_status: {shadow_short_interest.get('metric_status')}\n"
        f"shadow_mtm_net_pnl_pct_realtime: {shadow_net_pct}\n"
        f"shadow_mtm_net_delta: {shadow_net_delta}\n"
        f"mtm_metric_status: {mtm_metric_status}\n"
        f"mtm_missing_fields: {mtm_missing_fields_str}\n"
        f"short_interest_accounting_version: lot_v2\n"
        f"short_interest_history_status: UNBACKFILLED_PRE_V2\n"
        f"performance_use_allowed: false\n"
        f"performance_use_block_reason: short-interest history is not backfilled and effective value series is still pending\n"
    )

    text = text.replace("【审计】满仓锁定:", mtm_block + "\n【审计】满仓锁定:")
    return text, {
        'exec_pct': exec_pct,
        'show_pct': chg_pct,
        'pos': pos,
        'avg': avg,
        'market_value': market_value,
        'cost_basis': cost_basis,
        'comm': comm,
        'tax': tax,
        'transfer': transfer,
        'total_cost': total_cost,
        'action': action,
        'reason': reason,
        'position_from': int(tr.get('position_from', pos) or pos) if isinstance(tr, dict) else pos,
        'position_to': int(tr.get('position_to', pos) or pos) if isinstance(tr, dict) else pos,
    }


def validate(text: str, ctx: dict | None = None) -> list[str]:
    errs = []
    for k in TEMPLATE_KEYS:
        if k not in text:
            errs.append(f'missing:{k}')
    if '暂无' in text:
        errs.append('contains:暂无')

    # 一致性硬闸
    if ctx:
        # 1) 执行口径=展示口径（涨跌幅）
        exec_pct = float(ctx.get('exec_pct', 0.0) or 0.0)
        show_pct = float(ctx.get('show_pct', 0.0) or 0.0)
        if abs(exec_pct - show_pct) > 0.01:
            errs.append(f'consistency:pct_mismatch exec={exec_pct:.4f} show={show_pct:.4f}')

        # 2) 仓位为0时，均价/市值/成本必须为0
        pos = int(ctx.get('pos', 0) or 0)
        avg = float(ctx.get('avg', 0.0) or 0.0)
        mv = float(ctx.get('market_value', 0.0) or 0.0)
        cb = float(ctx.get('cost_basis', 0.0) or 0.0)
        if pos == 0 and (abs(avg) > 1e-9 or abs(mv) > 1e-6 or abs(cb) > 1e-6):
            errs.append('consistency:zero_pos_nonzero_metrics')

        # 3) 成本合计一致
        comm = float(ctx.get('comm', 0.0) or 0.0)
        tax = float(ctx.get('tax', 0.0) or 0.0)
        transfer = float(ctx.get('transfer', 0.0) or 0.0)
        total = float(ctx.get('total_cost', 0.0) or 0.0)
        if abs((comm + tax + transfer) - total) > 1e-6:
            errs.append('consistency:cost_total_mismatch')

        # 4) 满仓锁定下不得出现“加仓”类动作
        full_lock = abs(pos) >= 100
        action = str(ctx.get('action',''))
        if full_lock and ('加仓' in action or '开多' in action or '回补' in action):
            errs.append('consistency:full_lock_action_violation')

        # 5) position_delta 与 action_delta/ reason_delta（仅做最小硬校验）
        pf = ctx.get('position_from')
        pt = ctx.get('position_to')
        if isinstance(pf,int) and isinstance(pt,int):
            if pf==pt and ('加仓' in action or '减仓' in action):
                errs.append('consistency:delta_zero_but_action_nonzero')
    return errs


def _slot_ts(now: dt.datetime | None = None):
    n = now or dt.datetime.now()
    m = (n.minute // 10) * 10
    slot = n.replace(minute=m, second=0, microsecond=0)
    return slot, slot.strftime('%Y%m%d_%H%M%S')



# ---- KRONOS_OFF_HOURS_HARD_GATE_V1 ----
# P0 safety gate:
# - auto_report_guard is intraday-only
# - missed cron jobs after Gateway restart must never modify trading state off-hours
# - skipped runs write audit-only JSON, never formal report/check/done artifacts
def _kronos_is_intraday_market_time_v1(n: dt.datetime) -> bool:
    t = n.time()
    morning = dt.time(9, 30) <= t < dt.time(11, 31)
    afternoon = dt.time(13, 0) <= t < dt.time(15, 0)
    return morning or afternoon


def _kronos_write_skip_audit_v1(
    status: str,
    reason: str,
    now: dt.datetime,
    slot_ts: str,
) -> None:
    # Prevent the atexit done-marker guard from treating this as a natural sample.
    os.environ["KRONOS_NOT_NATURAL_CRON"] = "true"
    os.environ["KRONOS_NOT_FOR_SAMPLE_QUALITY"] = "true"

    payload = {
        "status": status,
        "reason": reason,
        "actual_ts": now.strftime("%Y-%m-%d %H:%M:%S"),
        "slot_ts": slot_ts,
        "job_id": (
            os.environ.get("OPENCLAW_CRON_JOB_ID")
            or os.environ.get("JOB_ID")
            or ""
        ),
        "not_for_sample_quality": True,
        "not_for_strategy_eval": True,
        "state_modified": False,
        "formal_report_written": False,
        "formal_check_written": False,
        "done_marker_written": False,
    }

    audit_path = OUTDIR / (
        f"skipped_off_hours_"
        f"{now.strftime('%Y%m%d_%H%M%S_%f')}.json"
    )
    audit_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"status={status} "
        f"reason={reason} "
        f"actual_ts={payload['actual_ts']} "
        f"state_modified=false "
        f"formal_report_written=false "
        f"audit_file={audit_path}"
    )
# ---- END KRONOS_OFF_HOURS_HARD_GATE_V1 ----

def main():
    # P1.1: model allowlist guard
    try:
        from scripts.model_allowlist_guard import run_guard
        run_guard(task_name='auto_report_guard_603305', job_id=os.environ.get('OPENCLAW_CRON_JOB_ID','') or os.environ.get('JOB_ID',''), model=os.environ.get('OPENCLAW_MODEL') or os.environ.get('MODEL') or '', provider=os.environ.get('OPENCLAW_PROVIDER') or os.environ.get('PROVIDER') or '')
    except Exception:
        pass

    slot_dt, slot_ts = _slot_ts()

    # P0 hardened gate: fail closed before run_sim().
    # Non-trading days and off-hours write audit-only JSON.
    try:
        from scripts.trading_calendar import is_trading_day, explain_non_trading_day

        today = slot_dt.strftime('%Y-%m-%d')

        if not is_trading_day(today):
            reason = explain_non_trading_day(today)
            _kronos_write_skip_audit_v1(
                status="SKIP_NON_TRADING_DAY",
                reason=reason,
                now=dt.datetime.now(),
                slot_ts=slot_ts,
            )
            return

    except Exception as e:
        _kronos_write_skip_audit_v1(
            status="SKIP_TRADING_CALENDAR_ERROR",
            reason=f"{e.__class__.__name__}: {e}",
            now=dt.datetime.now(),
            slot_ts=slot_ts,
        )
        return

    if not _kronos_is_intraday_market_time_v1(slot_dt):
        _kronos_write_skip_audit_v1(
            status="SKIP_OFF_HOURS",
            reason="auto_report_guard_603305 is intraday-only",
            now=dt.datetime.now(),
            slot_ts=slot_ts,
        )
        return

    slot_mark = SLOTDIR / f"{slot_ts}.done"
    if slot_mark.exists():
        print(f"[IDEMPOTENT_SKIP] slot={slot_ts} already generated")
        return

    raw = run_sim()

    # P1: append audit-only fields (do not affect trading logic)
    job_id = os.environ.get('OPENCLAW_CRON_JOB_ID') or os.environ.get('JOB_ID') or ''
    session_id = os.environ.get('OPENCLAW_SESSION_ID') or os.environ.get('SESSION_ID') or ''
    model = os.environ.get('OPENCLAW_MODEL') or os.environ.get('MODEL') or ''
    provider = os.environ.get('OPENCLAW_PROVIDER') or os.environ.get('PROVIDER') or 'deepseek'
    model_guard_pass = (model.strip() in ('', 'deepseek/deepseek-v4-flash', 'deepseek-v4-flash'))

    # Best-effort provider_final / final_error_code extraction from raw text
    provider_final = 'unknown'
    final_error_code = ''
    for ln in raw.splitlines():
        if ln.startswith('provider_primary：'):
            provider_final = ln.replace('provider_primary：', '', 1).strip() or provider_final
        if ln.startswith('provider_fallback_used：') and ln.strip().endswith('true'):
            # if fallback was used, prefer fallback provider
            provider_final = 'eastmoney_push2his'
        if ln.startswith('provider_third：'):
            # if we reached third provider, it's likely the final in failure cases
            provider_final = ln.replace('provider_third：', '', 1).strip() or provider_final
        if ln.startswith('error_code：'):
            final_error_code = ln.replace('error_code：', '', 1).strip()

    audit_lines = [
        "",
        "[AUDIT] run_status=ok",  # script executed; cron-level status recorded in cron.runs
        f"[AUDIT] jobId={job_id}",
        f"[AUDIT] sessionId={session_id}",
        f"[AUDIT] delivered=unknown",
        f"[AUDIT] deliveryStatus=unknown",
        f"[AUDIT] model_guard_pass={str(model_guard_pass).lower()}",
        f"[AUDIT] original_model={model}",
        f"[AUDIT] final_model={model or 'deepseek/deepseek-v4-flash'}",
        f"[AUDIT] provider_runtime={provider or 'deepseek'}",
        f"[AUDIT] provider_final={provider_final}",
        f"[AUDIT] final_error_code={final_error_code}",
        f"[AUDIT] report_file={str(OUTDIR / f'report_{slot_ts}.txt')}",
    ]
    raw = raw.rstrip() + "\n" + "\n".join(audit_lines) + "\n"

    # 硬规则：同一时点要么成功实时数据，要么失败+错误码；禁止旧快照冒充当前
    if '行情获取失败（' in raw:
        fail_text = raw.strip()
        (OUTDIR / f'report_{slot_ts}.txt').write_text(fail_text, encoding='utf-8')
        (OUTDIR / f'check_{slot_ts}.json').write_text(json.dumps({'errors': ['realtime_fetch_failed']}, ensure_ascii=False, indent=2), encoding='utf-8')
        slot_mark.write_text(dt.datetime.now().isoformat(), encoding='utf-8')
        print(fail_text)
        return

    full = None
    ctx = None
    report_generation_failed = False
    error_reason = ""

    try:
        full, ctx = format_full(raw)
    except Exception as e:
        report_generation_failed = True
        error_reason = str(e)
        full = f"""时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n标的：603305 旭升集团\n状态：报表生成失败（策略已执行）\n错误：{error_reason}\n原始输出摘要：{raw[:500] if raw else '无'}\n建议：检查 format_full() 函数，已记录到 warnings.log\n"""
        with open(OUTDIR / 'warnings.log', 'a', encoding='utf-8') as f:
            f.write(f"{dt.datetime.now().isoformat()} | REPORT_FAILED | {error_reason}\\n")

    # Ensure AUDIT block is present in final report text (audit-only; does not affect strategy logic)
    if full and '[AUDIT]' not in full:
        try:
            full = full.rstrip() + "\n" + "\n".join(audit_lines) + "\n"
        except Exception:
            pass

    errs = []
    if not report_generation_failed:
        errs = validate(full, ctx)
        if errs:
            raw2 = run_sim()
            try:
                full, ctx = format_full(raw2)
                errs = validate(full, ctx)
            except Exception as e:
                errs.append('retry_failed:' + str(e))

    

    # ========== FACTOR_OBSERVER (intraday light sidecar, observer-only) ==========	
    try:
        feat = {}
        if ctx and isinstance(ctx, dict):
            feat.update(ctx)
        try:
            feat['action'] = (ctx or {}).get('action')
            feat['reason'] = (ctx or {}).get('reason')
            feat['position_pct'] = (ctx or {}).get('position_to')
            feat['full_lock'] = (abs(int((ctx or {}).get('pos', 0) or 0)) >= 100)
        except Exception:
            pass
        feat['provider_final'] = provider_final
        feat['final_error_code'] = final_error_code
        feat['model_guard_pass'] = model_guard_pass
        feat['is_trading_day'] = True
        feat['sample_quality_grade'] = None
        feat['rate_limit_interrupted'] = ('RATE_LIMIT' in str(final_error_code))

        import json as _json
        p1 = subprocess.run([
            'python3', str(BASE / 'scripts' / 'factor_score_observer.py'),
            '--light-from-json', '--light-weight-profile', 'neutral'
        ], input=_json.dumps(feat, ensure_ascii=False), text=True, capture_output=True)
        if p1.returncode == 0 and (p1.stdout or '').strip():
            feat2 = _json.loads((p1.stdout or '').strip())
            p2 = subprocess.run([
                'python3', str(BASE / 'scripts' / 'factor_observer_intraday_light.py')
            ], input=_json.dumps(feat2, ensure_ascii=False), text=True, capture_output=True)
            if p2.returncode == 0 and (p2.stdout or '').strip():
                full = full.rstrip() + '\n\n' + (p2.stdout.strip()) + '\n'
    except Exception:
        pass
    # ========== FACTOR_OBSERVER end ==========	



    # ========== FACTOR_OBSERVER (intraday light sidecar, observer-only) ==========
    # Hard constraints: must not change action/reason/position_pct; best-effort only.
    try:
        import json as _json

        feat = {}
        if ctx and isinstance(ctx, dict):
            feat.update(ctx)

        # Provide action/reason/position for conflict detection (read-only)
        try:
            feat['action'] = (ctx or {}).get('action')
            feat['reason'] = (ctx or {}).get('reason')
            feat['position_pct'] = (ctx or {}).get('position_to')
            feat['full_lock'] = (abs(int((ctx or {}).get('pos', 0) or 0)) >= 100)
        except Exception:
            pass

        # data quality fields best-effort
        # --- factor observer input fields (P1) ---
        try:
            # market fields (best-effort)
            feat['price'] = float((ctx or {}).get('price') or (ctx or {}).get('last') or 0) or None
            feat['prev_close'] = (ctx or {}).get('prev_close')
            feat['open_price'] = (ctx or {}).get('open')
            feat['high'] = (ctx or {}).get('high')
            feat['low'] = (ctx or {}).get('low')
            feat['pct_change'] = (ctx or {}).get('pct')
            feat['avg_price'] = (ctx or {}).get('avg_price')
            feat['vwap_proxy'] = (ctx or {}).get('avg_price')

            # strategy fields
            feat['signal'] = (ctx or {}).get('signal')
            feat['action'] = (ctx or {}).get('action')
            feat['reason'] = (ctx or {}).get('reason')
            feat['position_from'] = (ctx or {}).get('position_from')
            feat['position_to'] = (ctx or {}).get('position_to')
            feat['position_pct'] = (ctx or {}).get('position_to')
            pos = int((ctx or {}).get('pos', 0) or 0)
            feat['side'] = 'long' if pos>0 else ('short' if pos<0 else 'flat')
            feat['full_lock'] = (abs(pos) >= 100)
        except Exception:
            pass

        # audit fields
        feat['timeslot'] = slot_dt.strftime('%H%M')
        feat['report_file'] = str(OUTDIR / f'report_{slot_ts}.txt')
        feat['factor_weight_profile'] = 'conservative'
        feat['observer_only'] = True
        feat['affects_position'] = False

        feat['provider_final'] = provider_final
        feat['final_error_code'] = final_error_code
        feat['model_guard_pass'] = model_guard_pass
        feat['is_trading_day'] = True
        feat['sample_quality_grade'] = None
        feat['rate_limit_interrupted'] = ('RATE_LIMIT' in str(final_error_code))

        # Call factor_score_observer light mode (observer-only)
        p1 = subprocess.run(
            [
                'python3',
                str(BASE / 'scripts' / 'factor_score_observer.py'),
                '--light-from-json',
                '--light-weight-profile',
                'conservative',
            ],
            input=_json.dumps(feat, ensure_ascii=False),
            text=True,
            capture_output=True,
        )

        # Display-layer de-dup: ensure only ONE [FACTOR_OBSERVER] block in final report.
        # If upstream report already contains a [FACTOR_OBSERVER] text block (legacy sidecar), drop it here.
        if "[FACTOR_OBSERVER]" in full:
            full = full.split("[FACTOR_OBSERVER]", 1)[0].rstrip()

        block_lines = [
            "[FACTOR_OBSERVER]",
        ]

        if p1.returncode == 0 and (p1.stdout or '').strip():
            d = _json.loads((p1.stdout or '').strip())
            # If data insufficient, enforce hint=insufficient_data
            if str(d.get('factor_hint') or '').strip() == '':
                d['factor_hint'] = 'insufficient_data'

            block_lines += [
                f"factor_score: {d.get('factor_score')}",
                f"factor_grade: {d.get('factor_grade')}",
                f"factor_hint: {d.get('factor_hint')}",
                f"factor_conflict_with_action: {str(bool(d.get('factor_conflict_with_action'))).lower()}",
                f"factor_weight_profile: {d.get('factor_weight_profile') or 'conservative'}",
                "observer_only: true",
                "affects_position: false",
            ]
        else:
            block_lines += [
                "unavailable: true",
                f"error: factor_score_observer_light_failed rc={p1.returncode}",
                "observer_only: true",
                "affects_position: false",
            ]

        full = full.rstrip() + "\n\n" + "\n".join(block_lines) + "\n"

    except Exception:
        # Never block main report.
        try:
            full = full.rstrip() + "\n\n[FACTOR_OBSERVER]\n" \
                "unavailable: true\n" \
                "error: exception\n" \
                "observer_only: true\n" \
                "affects_position: false\n"
        except Exception:
            pass
    # ========== FACTOR_OBSERVER end ==========

    (OUTDIR / f'report_{slot_ts}.txt').write_text(full, encoding='utf-8')
    (OUTDIR / f'check_{slot_ts}.json').write_text(
        json.dumps(
            {
                'errors': errs,
                'report_generation_failed': report_generation_failed,
                'error_reason': error_reason if report_generation_failed else None,
                'slot_ts': slot_ts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding='utf-8',
    )
    slot_mark.write_text(dt.datetime.now().isoformat(), encoding='utf-8')
    print(full)


if __name__ == '__main__':
    main()
