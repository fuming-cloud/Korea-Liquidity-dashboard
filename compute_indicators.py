# -*- coding: utf-8 -*-
"""
韩国股市去杠杆压力分析 — 指标计算引擎
输入: kofia_kr_leverage_bulk.json (KOFIA FreeSIS 原始数据, 单位: 百万韩元)
     krx_etf_indicators.json (选配, KRX 杠杆ETF数据)
输出: indicators.json (仪表板数据) + CSV 汇出

对齐方式: 以行情(KOSPI∩KOSDAQ)日期为主轴的「联集对齐」——
  信用/资金系列为 KOFIA T+1 公布, 尾端可比行情晚 1-2 个交易日,
  缺口以 null 呈现, 各指标取各自最后有效值, 截止日分开标示
  (asof_market / asof_credit)。

指标框架来源: 华尔街见闻〈去杠杆风暴下半场〉(2026-07-09)
"""
import json, math, sys, csv, os
from datetime import datetime

CONFIG = {
    "baseline_date": "20260430",   # 文章: 4月底 AI 硬体行情启动前的杠杆基期
    "peak_lookback_days": 400,
    "pctl_window": 1250,           # ≈5年
    "rv_window": 20,
    "bandae_ma": 5,
    "display_daily_from": "20230101",
    "weights": {
        "lvl_margin_pctl": 15.0, "lvl_mcap_pctl": 7.5, "lvl_dep_pctl": 7.5,
        "unwind_remaining": 22.0, "momentum": 8.0,
        "forced_amt_pctl": 10.0, "forced_ratio_pctl": 10.0,
        "vol_pctl": 10.0, "turnover_pctl": 10.0,
    },
    "etf_weight": 15.0,
    "signal2_manual": {"status": "watch", "note": "大型云服务商财报将至，关注AI资本开支指引"},
    "signal3_manual": {"status": "watch", "note": "韩监管已多次释放收紧讯号；关注限空/稳定基金等措施"},
}

def parse_bulk(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for key in ["credit", "funds", "kospi", "kosdaq"]:
        rows = [r for r in (raw.get(key) or []) if r and r[0]]
        rows.sort(key=lambda r: r[0])
        # 去重 (保留最后一笔)
        dedup = {}
        for r in rows:
            dedup[r[0]] = r
        out[key] = [dedup[d] for d in sorted(dedup)]
    out["meta"] = raw.get("meta", {})
    return out

def to_map(rows):
    return {r[0]: r for r in rows}

def num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def last_valid(arr, dates=None):
    for i in range(len(arr) - 1, -1, -1):
        if arr[i] is not None:
            return (arr[i], dates[i] if dates else None, i)
    return (None, None, None)

def pctl_of_last(window_vals, v):
    vals = [x for x in window_vals if x is not None]
    if v is None or len(vals) < 60:
        return None
    below = sum(1 for x in vals if x <= v)
    return round(100.0 * below / len(vals), 1)

def rolling_pctl(series, window):
    out = [None] * len(series)
    for i, v in enumerate(series):
        lo = max(0, i - window + 1)
        out[i] = pctl_of_last(series[lo:i + 1], v)
    return out

def compute(bulk, etf=None, hist=None, conc=None):
    credit_m, funds_m = to_map(bulk["credit"]), to_map(bulk["funds"])
    kosdaq_m = to_map(bulk["kosdaq"])

    dates, S = [], {k: [] for k in [
        "margin_total","margin_kospi","margin_kosdaq","pledge","deposit",
        "margin_dep","margin_mcap","margin_val","misu","bandae_amt","bandae_ratio",
        "kospi_idx","kosdaq_idx","turn_val","turn_heat","kospi_ret"]}

    # 主轴 = 行情日期 (KOSPI ∩ KOSDAQ); 信用/资金缺口 = null
    for k in bulk["kospi"]:
        d = k[0]
        q = kosdaq_m.get(d)
        ki, kv, km = num(k[1]), num(k[3]), num(k[4])
        if not q or ki is None:
            continue
        qi, qv, qm = num(q[1]), num(q[3]), num(q[4])
        c, f = credit_m.get(d), funds_m.get(d)
        mt = num(c[1]) if c else None
        mk = num(c[2]) if c else None
        mq = num(c[3]) if c else None
        pledge = num(c[8]) if c and len(c) > 8 else None
        dep = num(f[1]) if f else None
        misu = num(f[4]) if f else None
        b_amt = num(f[5]) if f else None
        b_rat = num(f[6]) if f else None
        val = (kv or 0) + (qv or 0)
        mcap = (km or 0) + (qm or 0)
        dates.append(d)
        S["margin_total"].append(None if mt is None else mt / 1e6)   # 兆원
        S["margin_kospi"].append(None if mk is None else mk / 1e6)
        S["margin_kosdaq"].append(None if mq is None else mq / 1e6)
        S["pledge"].append(None if pledge is None else pledge / 1e6)
        S["deposit"].append(None if dep is None else dep / 1e6)
        S["margin_dep"].append(None if (mt is None or not dep) else round(100 * mt / dep, 2))
        S["margin_mcap"].append(None if (mt is None or mcap == 0) else round(100 * mt / mcap, 3))
        S["margin_val"].append(None if (mt is None or val == 0) else round(mt / val, 2))
        S["misu"].append(None if misu is None else misu / 1e6)
        S["bandae_amt"].append(None if b_amt is None else b_amt / 100)  # 억원
        S["bandae_ratio"].append(b_rat)
        S["kospi_idx"].append(ki)
        S["kosdaq_idx"].append(qi)
        S["turn_val"].append(val / 1e6)
        S["turn_heat"].append(None if mcap == 0 else round(100 * val / mcap, 3))
        n = len(S["kospi_idx"])
        prev = S["kospi_idx"][n - 2] if n >= 2 else None
        S["kospi_ret"].append(None if not prev else math.log(ki / prev))

    n = len(dates)
    min_days = 30 if os.environ.get("KL_ALLOW_SHORT") else 100
    if n < min_days:
        raise SystemExit(f"数据不足: 仅 {n} 个交易日")

    # 回撤(相对52周=252交易日滚动高点) / 已实现波动率 / 断头均线
    W52 = 252
    dd = []
    for i, v in enumerate(S["kospi_idx"]):
        m = max(S["kospi_idx"][max(0, i - W52 + 1):i + 1])
        dd.append(round(100 * (v / m - 1), 2))
    seg52 = S["kospi_idx"][max(0, n - W52):]
    hi52 = max(seg52)
    hi52_date = dates[max(0, n - W52) + seg52.index(hi52)]
    rv20 = [None] * n
    w = CONFIG["rv_window"]
    for i in range(n):
        if i >= w:
            rets = [x for x in S["kospi_ret"][i - w + 1:i + 1] if x is not None]
            if len(rets) >= w - 2:
                m = sum(rets) / len(rets)
                var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
                rv20[i] = round(100 * math.sqrt(var * 252), 1)
    ma = CONFIG["bandae_ma"]
    def sma(arr):
        out = [None] * n
        for i in range(n):
            win = [x for x in arr[max(0, i - ma + 1):i + 1] if x is not None]
            out[i] = round(sum(win) / len(win), 2) if win else None
        return out
    bandae_amt_ma, bandae_ratio_ma = sma(S["bandae_amt"]), sma(S["bandae_ratio"])

    # 滚动百分位
    W = CONFIG["pctl_window"]
    P = {
        "margin_total": rolling_pctl(S["margin_total"], W),
        "margin_mcap": rolling_pctl(S["margin_mcap"], W),
        "margin_dep": rolling_pctl(S["margin_dep"], W),
        "bandae_amt": rolling_pctl(bandae_amt_ma, W),
        "bandae_ratio": rolling_pctl(bandae_ratio_ma, W),
        "rv20": rolling_pctl(rv20, W),
        "turn_heat": rolling_pctl(S["turn_heat"], W),
    }
    partial = n < 600
    sketch = (hist or {}).get("q") if partial else None
    if partial:  # 部分数据时：滚动百分位序列停用；当期百分位改用5年分布骨架(若有)
        for key in P:
            P[key] = [None] * n
    KEYMAP = {"margin_total": "mt", "margin_dep": "mdep", "margin_mcap": "mmcap",
              "turn_heat": "theat", "bandae_amt": "bamt", "bandae_ratio": "brat", "rv20": "rv"}
    def sketch_pctl(qs, v):
        if v is None or not qs:
            return None
        if v <= qs[0]:
            return 0.0
        if v >= qs[-1]:
            return 100.0
        for j in range(len(qs) - 1):
            if qs[j] <= v < qs[j + 1]:
                frac = (v - qs[j]) / ((qs[j + 1] - qs[j]) or 1)
                return round((j + frac) * 100.0 / (len(qs) - 1), 1)
        return None
    def last_pctl(key):
        if sketch is not None:
            return sketch_pctl(sketch.get(KEYMAP[key]), CURV.get(key))
        v, _, _ = last_valid(P[key], dates)
        return v
    def series_peak(arr):
        pv, pd = None, None
        for i, v in enumerate(arr):
            if v is not None and (pv is None or v > pv):
                pv, pd = v, dates[i]
        return pv, pd
    bandae_pk, bandae_pk_d = series_peak(S["bandae_amt"])
    dep_pk, dep_pk_d = series_peak(S["deposit"])

    # 出清进度 U (以信用系列自身有效值计)
    mt_valid = [(i, v) for i, v in enumerate(S["margin_total"]) if v is not None]
    bdate = CONFIG["baseline_date"]
    bi = max((i for i, v in mt_valid if dates[i] <= bdate), default=mt_valid[0][0])
    lb = CONFIG["peak_lookback_days"]
    seg = [(i, v) for i, v in mt_valid if i >= n - lb]
    peak_i, peak_v = max(seg, key=lambda t: t[1])
    cur_i, cur = mt_valid[-1]
    base_v = S["margin_total"][bi]
    U = 1.0 if peak_v <= base_v else max(0.0, min(1.0, (peak_v - cur) / (peak_v - base_v)))
    tail = [v for _, v in mt_valid[-6:]]
    d5 = (tail[-1] / tail[0] - 1) if len(tail) == 6 and tail[0] else None

    asof_market = dates[-1]
    asof_credit = dates[cur_i]
    _, asof_funds, _ = last_valid(S["deposit"], dates)

    # 当期值（供分布骨架百分位）
    CURV = {"margin_total": cur,
            "margin_dep": last_valid(S["margin_dep"])[0],
            "margin_mcap": last_valid(S["margin_mcap"])[0],
            "turn_heat": last_valid(S["turn_heat"])[0],
            "bandae_amt": last_valid(bandae_amt_ma)[0],
            "bandae_ratio": last_valid(bandae_ratio_ma)[0],
            "rv20": last_valid(rv20)[0]}

    # 综合压力指数
    Wt = dict(CONFIG["weights"])
    etf_part = None
    if etf and etf.get("remaining") is not None:
        for k in Wt: Wt[k] *= 0.85
        etf_part = CONFIG["etf_weight"] * max(0.0, min(1.0, etf["remaining"]))
    def lp(key):
        v = last_pctl(key)
        return 50.0 if v is None else v
    mom_score = 1.0 if (d5 is None or d5 > 0.01) else (0.5 if d5 > -0.01 else 0.25)
    parts = {
        "杠杆水位·融资余额百分位": Wt["lvl_margin_pctl"] * lp("margin_total") / 100,
        "杠杆水位·融资/市值百分位": Wt["lvl_mcap_pctl"] * lp("margin_mcap") / 100,
        "杠杆水位·融资/预托金百分位": Wt["lvl_dep_pctl"] * lp("margin_dep") / 100,
        "出清进度·未出清比例": Wt["unwind_remaining"] * (1 - U),
        "出清进度·融资动能": Wt["momentum"] * mom_score,
        "被动卖压·断头金额百分位": Wt["forced_amt_pctl"] * lp("bandae_amt") / 100,
        "被动卖压·断头比率百分位": Wt["forced_ratio_pctl"] * lp("bandae_ratio") / 100,
        "市场应激·波动率": Wt["vol_pctl"] * lp("rv20") / 100,
        "市场应激·成交热度": Wt["turnover_pctl"] * lp("turn_heat") / 100,
    }
    if etf_part is not None:
        parts["杠杆ETF·未出清程度"] = etf_part
    score = round(sum(parts.values()), 1)
    zone = ("high", "≥70 高压：去化初中期") if score >= 70 else \
           ("mid", "45-70 中后期：去化进行中") if score >= 45 else \
           ("late", "25-45 尾声：接近出清") if score >= 25 else ("done", "<25 大致出清")

    # === 新增：逐日历史压力指数序列（HW 扩展）===
    # 对每个交易日 i，用「当天可见的滚动百分位 + 当天出清进度 U_i + 当天动能」重算综合指数。
    # 缺 ETF 分项，用不含 ETF 的九分项权重（与当前口径一致，便于连续对比）。
    def _u_at(i):
        # 出清进度：以 baseline_date 为基期、过去 peak_lookback 内的峰值为峰
        seg_i = [(j, S["margin_total"][j]) for j in range(max(0, i - lb + 1), i + 1) if S["margin_total"][j] is not None]
        if not seg_i:
            return None
        pk = max(v for _, v in seg_i)
        cur_v = None
        for j in range(i, -1, -1):
            if S["margin_total"][j] is not None:
                cur_v = S["margin_total"][j]; break
        if cur_v is None or base_v is None:
            return None
        if pk <= base_v:
            return 1.0
        return max(0.0, min(1.0, (pk - cur_v) / (pk - base_v)))

    def _d5_at(i):
        vv = [S["margin_total"][j] for j in range(max(0, i - 5), i + 1) if S["margin_total"][j] is not None]
        if len(vv) >= 2 and vv[0]:
            return vv[-1] / vv[0] - 1
        return None

    def _pv(arr, i):  # 当天百分位（无值→50 中性）
        v = arr[i] if i < len(arr) else None
        return 50.0 if v is None else v

    score_series = [None] * n
    for i in range(n):
        u_i = _u_at(i)
        if u_i is None:
            continue
        d5_i = _d5_at(i)
        mom_i = 1.0 if (d5_i is None or d5_i > 0.01) else (0.5 if d5_i > -0.01 else 0.25)
        sc = (CONFIG["weights"]["lvl_margin_pctl"] * _pv(P["margin_total"], i) / 100
              + CONFIG["weights"]["lvl_mcap_pctl"] * _pv(P["margin_mcap"], i) / 100
              + CONFIG["weights"]["lvl_dep_pctl"] * _pv(P["margin_dep"], i) / 100
              + CONFIG["weights"]["unwind_remaining"] * (1 - u_i)
              + CONFIG["weights"]["momentum"] * mom_i
              + CONFIG["weights"]["forced_amt_pctl"] * _pv(P["bandae_amt"], i) / 100
              + CONFIG["weights"]["forced_ratio_pctl"] * _pv(P["bandae_ratio"], i) / 100
              + CONFIG["weights"]["vol_pctl"] * _pv(P["rv20"], i) / 100
              + CONFIG["weights"]["turnover_pctl"] * _pv(P["turn_heat"], i) / 100)
        score_series[i] = round(sc, 1)

    # 末点对齐顶部半圆表：最后一个有效点直接用主计算的 score，
    # 避免「逐日回算对缺失信用数据填中性50」与「顶部用最后有效值」两套口径打架。
    for i in range(n - 1, -1, -1):
        if score_series[i] is not None:
            score_series[i] = score
            break

    # === ETF 净值对齐主日期轴（HW 扩展）===
    _etf_nav_aligned = [None] * n
    if etf and etf.get("nav_dates") and etf.get("nav"):
        _navm = dict(zip(etf["nav_dates"], etf["nav"]))
        for i, d in enumerate(dates):
            if d in _navm:
                _etf_nav_aligned[i] = _navm[d]

    s1_ok_bandae = (last_pctl("bandae_amt") or 50) < 50
    s1_ok_margin = d5 is not None and d5 > -0.01
    s1_ok_etf = (etf is None) or (etf.get("aum_d5") is None) or etf["aum_d5"] > -0.02
    s1 = "green" if (s1_ok_bandae and s1_ok_margin and s1_ok_etf) else ("yellow" if (s1_ok_bandae or s1_ok_margin) else "red")

    # 显示降采样
    keep, dfrom = [], CONFIG["display_daily_from"]
    for i, d in enumerate(dates):
        if d >= dfrom:
            keep.append(i)
        else:
            dt = datetime.strptime(d, "%Y%m%d")
            nxt = dates[i + 1] if i + 1 < n else None
            if dt.weekday() == 4 or (nxt and datetime.strptime(nxt, "%Y%m%d").weekday() < dt.weekday()):
                keep.append(i)
    def pick(arr): return [arr[i] for i in keep]

    def latest_of(key):
        v, dt2, _ = last_valid(S[key], dates)
        return v
    latest = {k: latest_of(k) for k in
              ["margin_total","margin_kospi","margin_kosdaq","deposit","margin_dep",
               "margin_mcap","margin_val","misu","bandae_amt","bandae_ratio",
               "kospi_idx","kosdaq_idx","turn_val","turn_heat"]}

    out = {
        "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        "sample": str(bulk.get("meta", {}).get("source", "")).startswith("SYNTHETIC"),
        "partial": partial,
        "pctl_source": ("5年分布快照@" + str((hist or {}).get("end", ""))) if sketch is not None else ("rolling" if not partial else None),
        "data_from": dates[0],
        "asof": asof_market,
        "asof_market": asof_market,
        "asof_credit": asof_credit,
        "asof_funds": asof_funds,
        "n_days_total": n,
        "config": {"baseline_date": bdate, "pctl_window_days": W, "weights": Wt,
                   "etf_enabled": etf_part is not None},
        "dates": pick(dates),
        "daily_from": dfrom,
        "series": {
            "margin_total": pick(S["margin_total"]), "margin_kospi": pick(S["margin_kospi"]),
            "margin_kosdaq": pick(S["margin_kosdaq"]), "deposit": pick(S["deposit"]),
            "margin_dep": pick(S["margin_dep"]), "margin_mcap": pick(S["margin_mcap"]),
            "margin_val": pick(S["margin_val"]), "misu": pick(S["misu"]),
            "bandae_amt": pick(S["bandae_amt"]), "bandae_ratio": pick(S["bandae_ratio"]),
            "bandae_amt_ma": pick(bandae_amt_ma), "bandae_ratio_ma": pick(bandae_ratio_ma),
            "kospi_idx": pick(S["kospi_idx"]), "kosdaq_idx": pick(S["kosdaq_idx"]),
            "kospi_dd": pick(dd), "rv20": pick(rv20),
            "turn_val": pick(S["turn_val"]), "turn_heat": pick(S["turn_heat"]),
            "pctl_margin_total": pick(P["margin_total"]),
            "composite_score": pick(score_series),
            "etf_nav": pick(_etf_nav_aligned),
        },
        "latest": latest,
        "latest_extra": {"kospi_dd": dd[-1], "kospi_hi52": round(hi52, 2), "kospi_hi52_date": hi52_date,
                         "rv20": last_valid(rv20)[0],
                         "bandae_amt_ma": last_valid(bandae_amt_ma)[0],
                         "bandae_ratio_ma": last_valid(bandae_ratio_ma)[0],
                         "margin_d5_pct": None if d5 is None else round(100 * d5, 2),
                         "bandae_peak": [bandae_pk, bandae_pk_d], "deposit_peak": [dep_pk, dep_pk_d],
                         "pctl": {k: last_pctl(k) for k in P}},
        "unwind": {"peak": round(peak_v, 2), "peak_date": dates[peak_i],
                   "baseline": round(base_v, 2), "baseline_date": dates[bi],
                   "current": round(cur, 2), "U": round(U, 3),
                   "excess_peak": round(peak_v - base_v, 2), "excess_now": round(cur - base_v, 2)},
        "composite": {"score": score, "zone": zone[0], "zone_label": zone[1],
                      "parts": {k: round(v, 2) for k, v in parts.items()}},
        "signals": {
            "s1": {"status": s1, "label": "技术性卖压衰竭",
                   "detail": ("断头金额5日均百分位 " + (str(last_pctl('bandae_amt')) if (not partial or sketch is not None) else "待完整历史")
                              + f"｜融资5日 {('' if d5 is None else f'{d5*100:+.1f}%')}")},
            "s2": {"status": CONFIG["signal2_manual"]["status"], "label": "外部催化剂落地",
                   "detail": CONFIG["signal2_manual"]["note"] + "（人工旗标）"},
            "s3": {"status": CONFIG["signal3_manual"]["status"], "label": "监管干预力度",
                   "detail": CONFIG["signal3_manual"]["note"] + "（人工旗标）"},
        },
        "concentration": conc or {"enabled": False},
        "etf": etf or {"enabled": False, "note": "待 KRX 登入后补齐：三星/SK海力士单股2倍ETF规模与价格"},
    }
    return out

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data/kofia_kr_leverage_bulk.json"
    etf_path = sys.argv[2] if len(sys.argv) > 2 else "data/krx_etf_indicators.json"
    etf = None
    if os.path.exists(etf_path):
        with open(etf_path, encoding="utf-8") as f:
            etf = json.load(f)
    conc = None
    if os.path.exists("data/stock_concentration.json"):
        with open("data/stock_concentration.json", encoding="utf-8") as f:
            conc = json.load(f)
    hist = None
    if os.path.exists("data/history_stats.json"):
        with open("data/history_stats.json", encoding="utf-8") as f:
            hist = json.load(f)
    bulk = parse_bulk(src)
    out = compute(bulk, etf, hist, conc)
    os.makedirs("out", exist_ok=True)
    with open("out/indicators.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open("out/kr_leverage_daily.csv", "w", newline="", encoding="utf-8-sig") as f:
        wcsv = csv.writer(f)
        wcsv.writerow(["date"] + list(out["series"].keys()))
        for i, d in enumerate(out["dates"]):
            wcsv.writerow([d] + [out["series"][k][i] for k in out["series"]])
    print(f"OK market={out['asof_market']} credit={out['asof_credit']} days={out['n_days_total']} "
          f"score={out['composite']['score']} zone={out['composite']['zone']} U={out['unwind']['U']}")

if __name__ == "__main__":
    main()
