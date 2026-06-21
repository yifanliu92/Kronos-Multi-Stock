#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, ssl, time, urllib.error, urllib.request
from pathlib import Path
from typing import Optional, Dict, Tuple, Any, List

SYMBOL = "603305"
RULES_PATH = Path(__file__).with_name("signal_rules_603305.json")

DEFAULT_RULES = {
    "thresholds": {"bull_pct": 1.2, "bear_pct": -1.2},
    "texts": {
        "bull": {"a": "偏多（小仓跟随）", "b": "观察回踩承接", "c": "不追高", "risk": "止损-2%，单次仓位≤30%"},
        "neutral": {"a": "中性（轻仓观察）", "b": "看量价是否放大", "c": "维持对照观察", "risk": "仓位控制在20%以内"},
        "bear": {"a": "偏空（观望）", "b": "等待企稳信号", "c": "避免抄底", "risk": "不逆势加仓，等待下一次检查"},
    },
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


def load_rules(path: Path = RULES_PATH) -> Dict:
    if not path.exists(): return DEFAULT_RULES
    try: user_rules = json.loads(path.read_text(encoding="utf-8"))
    except Exception: return DEFAULT_RULES
    rules = json.loads(json.dumps(DEFAULT_RULES))
    rules.get("thresholds", {}).update(user_rules.get("thresholds", {}))
    for k in ("bull", "neutral", "bear"): rules["texts"][k].update(user_rules.get("texts", {}).get(k, {}))
    return rules


def _http_get(url: str, timeout: int = 8, headers: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return int(getattr(e, "code", 0) or 0), (e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else "")
    except Exception as e:
        reason = str(getattr(e, "reason", e))
        if "CERTIFICATE_VERIFY_FAILED" not in reason: raise
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", errors="ignore")


def _to_price(v) -> Optional[float]:
    try:
        if v in (None, "", "-", "--"): return None
        return float(v) / 100.0
    except Exception: return None


def _extract_json_text(txt: str) -> Optional[str]:
    s = (txt or '').strip()
    if not s: return None
    if s.startswith('{') and s.endswith('}'): return s
    l, r = s.find('{'), s.rfind('}')
    if l != -1 and r != -1 and r > l: return s[l:r+1]
    return None


def _dump_raw(raw: str) -> None:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path("/Users/wxo/Desktop/Kronos/debug"); d.mkdir(parents=True, exist_ok=True)
    (d / f"eastmoney_raw_{ts}.txt").write_text(raw or "", encoding="utf-8")


def _sanity(m: Dict[str, float]) -> Tuple[bool, str, List[str]]:
    bad: List[str] = []
    if m["last"] <= 0: bad.append("last<=0")
    if m["prev_close"] <= 0: bad.append("prev_close<=0")
    if m["high"] < m["low"]: bad.append("high<low")
    if not (m["high"] >= m["last"] >= m["low"]): bad.append("last_not_in_range")
    if abs(m["pct"]) > 30: bad.append("pct_outlier")
    return (len(bad) == 0, "OK" if not bad else "EM_SANITY_CHECK", bad)


def _parse_eastmoney(txt: str) -> Tuple[Optional[Dict[str, float]], str, List[str], str]:
    jtxt = _extract_json_text(txt)
    if not jtxt: return None, "EM_FIELD_MISSING", [], "extract_json"
    try: obj = json.loads(jtxt)
    except Exception: return None, "EM_TYPE_CAST", [], "json_loads"
    data = obj.get("data") or {}
    if not data: return None, "EM_FIELD_MISSING", [], "data_node"
    req = ["f43", "f44", "f45", "f46", "f60"]
    missing = [k for k in req if k not in data]
    if missing: return None, "EM_FIELD_MISSING", missing, "field_presence"
    last, high, low, op, prev, pct = _to_price(data.get("f43")), _to_price(data.get("f44")), _to_price(data.get("f45")), _to_price(data.get("f46")), _to_price(data.get("f60")), _to_price(data.get("f169"))
    if None in (last, high, low, op, prev): return None, "EM_TYPE_CAST", [], "type_cast"
    if pct is None and prev: pct = (last - prev) / prev * 100.0
    m = {"last": last, "open": op, "high": high, "low": low, "prev_close": prev, "pct": float(pct or 0.0)}
    ok, code, _ = _sanity(m)
    return (m if ok else None), code, [], "sanity"


def _parse_tencent(txt: str) -> Tuple[Optional[Dict[str, float]], str, List[str], str]:
    s = (txt or "").strip()
    if not s or '="' not in s: return None, "EM_FIELD_MISSING", [], "raw_pattern"
    try:
        payload = s.split('="', 1)[1].rsplit('"', 1)[0]
        arr = payload.split('~')
        last = float(arr[3]); prev = float(arr[4]); op = float(arr[5]); high = float(arr[33]); low = float(arr[34])
        pct = (last - prev) / prev * 100.0 if prev > 0 else 0.0
        m = {"last": last, "open": op, "high": high, "low": low, "prev_close": prev, "pct": pct}
        ok, code, _ = _sanity(m)
        return (m if ok else None), code, [], "sanity"
    except Exception:
        return None, "EM_TYPE_CAST", [], "type_cast"


def fetch_eastmoney(symbol: str = SYMBOL, retries: int = 2) -> Tuple[Optional[Dict[str, float]], str, Dict[str, Any]]:
    secid = f"1.{symbol}"
    primary_url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f60,f169"
    fallback_url = f"https://push2his.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f60,f169"
    third_url = f"https://qt.gtimg.cn/q=sh{symbol}"

    d: Dict[str, Any] = {
        "provider_primary": "eastmoney_push2", "primary_url": primary_url, "primary_result": "not_used", "primary_error_code": "not_used", "primary_raw_length": 0,
        "provider_fallback": "eastmoney_push2his", "fallback_url": fallback_url, "fallback_result": "not_used", "fallback_error_code": "not_used", "fallback_raw_length": 0,
        "provider_third": "tencent", "third_url": third_url, "third_result": "not_used", "third_error_code": "not_used", "third_raw_length": 0,
        "provider_fallback_used": False, "provider_final": "none", "final_error_code": "EM_UNKNOWN",
        "error_code": "EM_UNKNOWN", "fetch_url": "", "retry_count": 0, "raw_length": 0, "missing_fields": [], "parse_stage": "init", "sanity_issues": []
    }

    if primary_url == fallback_url:
        d.update({"final_error_code": "FALLBACK_SAME_AS_PRIMARY", "error_code": "FALLBACK_SAME_AS_PRIMARY"})
        return None, "FALLBACK_SAME_AS_PRIMARY", d

    for i in range(retries + 1):
        d["retry_count"] = i
        for stage, url in (("primary", primary_url), ("fallback", fallback_url)):
            d["fetch_url"] = url
            if stage == "fallback": d["provider_fallback_used"] = True
            try:
                status, txt = _http_get(url, headers=BROWSER_HEADERS)
                raw_len = len(txt or ""); d["raw_length"] = raw_len
                if stage == "primary": d["primary_raw_length"] = raw_len
                else: d["fallback_raw_length"] = raw_len
                if status != 200:
                    code = "EM_HTTP_STATUS"
                elif not (txt or "").strip():
                    code = "EM_RAW_EMPTY"
                else:
                    m, code, miss, pstage = _parse_eastmoney(txt)
                    d["missing_fields"] = miss; d["parse_stage"] = pstage
                    if m is not None:
                        if stage == "primary":
                            d.update({"provider_final": "eastmoney_push2", "primary_result": "success", "fallback_result": "not_used", "third_result": "not_used", "final_error_code": "OK", "error_code": "OK", "primary_error_code": "OK", "fallback_error_code": "not_used", "third_error_code": "not_used"})
                        else:
                            d.update({"provider_final": "eastmoney_push2his", "primary_result": "failed", "fallback_result": "success", "third_result": "not_used", "final_error_code": "OK", "error_code": "OK", "fallback_error_code": "OK", "third_error_code": "not_used"})
                        return m, "OK", d
                    _dump_raw(txt)
                if stage == "primary":
                    d["primary_error_code"] = code; d["primary_result"] = "failed"
                else:
                    d["fallback_error_code"] = code; d["fallback_result"] = "failed"
                d["error_code"] = code
            except TimeoutError:
                code = "EM_TIMEOUT"; d["error_code"] = code
                if stage == "primary": d["primary_error_code"] = code; d["primary_result"] = "failed"
                else: d["fallback_error_code"] = code; d["fallback_result"] = "failed"
            except Exception:
                code = "EM_CONNECT_FAIL"; d["error_code"] = code
                if stage == "primary": d["primary_error_code"] = code; d["primary_result"] = "failed"
                else: d["fallback_error_code"] = code; d["fallback_result"] = "failed"

        # third source
        try:
            d["fetch_url"] = third_url
            status, txt = _http_get(third_url, headers={"User-Agent": BROWSER_HEADERS["User-Agent"], "Accept": "*/*", "Accept-Language": BROWSER_HEADERS["Accept-Language"], "Connection": "keep-alive"})
            d["third_raw_length"] = len(txt or "")
            if status != 200:
                d["third_error_code"] = "EM_HTTP_STATUS"
            elif not (txt or "").strip():
                d["third_error_code"] = "EM_RAW_EMPTY"
            else:
                m, code, miss, pstage = _parse_tencent(txt)
                d["missing_fields"] = miss; d["parse_stage"] = pstage
                if m is not None:
                    d.update({"provider_final": "tencent", "provider_third": "tencent", "primary_result": d.get("primary_result","failed"), "fallback_result": d.get("fallback_result","failed"), "third_result": "success", "third_error_code": "OK", "final_error_code": "OK", "error_code": "OK"})
                    return m, "OK", d
                d["third_error_code"] = code
            d["third_result"] = "failed"
        except TimeoutError:
            d["third_error_code"] = "EM_TIMEOUT"; d["third_result"] = "failed"
        except Exception:
            d["third_error_code"] = "EM_TYPE_CAST"; d["third_result"] = "failed"

        if i < retries: time.sleep(0.6)

    d["final_error_code"] = d.get("third_error_code") or d.get("fallback_error_code") or d.get("primary_error_code") or "EM_UNKNOWN"
    return None, str(d["final_error_code"]), d


def build_lines(market: Optional[Dict[str, float]], source: str, next_check: str, rules: Dict, err_code: str = "") -> list[str]:
    now = dt.datetime.now().strftime("%H:%M")
    if market is None:
        reason = f"（{err_code}）" if err_code else ""
        return [f"【603305 盘中快报 {now}】", "A主：数据暂不可用，观望", "B观察：数据暂不可用，观望", "C观察：数据暂不可用，观望", f"风控：不加仓，等待数据恢复{reason}", f"下一次检查：{next_check}"]
    last, pct, prev_close, open_price, high, low = market["last"], market["pct"], market["prev_close"], market["open"], market["high"], market["low"]
    bull_pct, bear_pct = float(rules["thresholds"].get("bull_pct", 1.2)), float(rules["thresholds"].get("bear_pct", -1.2))
    bundle = rules["texts"]["bull"] if pct >= bull_pct else (rules["texts"]["bear"] if pct <= bear_pct else rules["texts"]["neutral"])
    return [f"【603305 盘中快报 {now}】", f"A主：{bundle['a']}", f"B观察：{bundle['b']}", f"C观察：{bundle['c']}", f"风控：{bundle['risk']}（昨收 {prev_close:.2f}，今开 {open_price:.2f}，今高 {high:.2f}，今低 {low:.2f}，现价 {last:.2f}，涨跌幅 {pct:+.2f}%，源 {source}）", f"下一次检查：{next_check}"]


def main() -> None:
    p = argparse.ArgumentParser()
    # Backward compatible: older callers use --mode quote_json
    p.add_argument("--mode", default="lines", choices=["lines", "quote_json"], help="output mode")
    p.add_argument("--next-check", default="下一个时点")
    args = p.parse_args()

    rules = load_rules()
    try:
        data, err, debug = fetch_eastmoney()
    except Exception:
        data, err, debug = None, "EM_MAIN", {"provider_final": "none", "final_error_code": "EM_MAIN"}

    if args.mode == "quote_json":
        out = {
            "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": SYMBOL,
            "ok": data is not None,
            "error_code": "OK" if data is not None else err,
            "market": data,
            "provider": (debug or {}).get("provider_final", "none"),
            "debug": debug,
        }
        print(json.dumps(out, ensure_ascii=False))
        return

    lines = build_lines(None, "none", args.next_check, rules, err_code=err) if data is None else build_lines(data, "multi_source", args.next_check, rules)
    print("\n".join(lines))

if __name__ == "__main__": main()
