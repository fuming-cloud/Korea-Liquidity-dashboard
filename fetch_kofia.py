# -*- coding: utf-8 -*-
"""KOFIA FreeSIS 數據抓取（GitHub Actions 直連版）
抓取四大系列完整歷史 → data/kofia_kr_leverage_bulk.json
API 規格已於 2026-07-10 實測驗證（見 fetch_spec.md）。"""
import json, time, sys
from datetime import datetime, timezone, timedelta

import requests

URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Origin": "https://freesis.kofia.or.kr",
    "Referer": "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070",
}
SERIES = [  # (key, OBJ_NM, 取TMPV2..TMPV{1+n}共n欄)
    ("credit", "STATSCU0100000070BO", 8),
    ("funds",  "STATSCU0100000060BO", 6),
    ("kospi",  "STATSCU0100000020BO", 6),
    ("kosdaq", "STATSCU0100000030BO", 6),
]

def pull(sess, obj, d1, d2, tries=4):
    body = {"dmSearch": {"tmpV40": "1000000", "tmpV41": "1", "tmpV1": "D",
                         "tmpV45": d1, "tmpV46": d2, "OBJ_NM": obj}}
    for i in range(tries):
        try:
            r = sess.post(URL, json=body, headers=HEADERS, timeout=40)
            r.raise_for_status()
            rows = (r.json().get("ds1") or [])
            rows.sort(key=lambda x: x["TMPV1"])
            return rows
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))

def pack(rows, nc):
    out = []
    for r in rows:
        rec = [r["TMPV1"]]
        for i in range(2, 2 + nc):
            v = r.get(f"TMPV{i}")
            rec.append(v if v is not None else None)
        out.append(rec)
    return out

def main():
    kst_today = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y%m%d")
    sess = requests.Session()
    # 先訪問頁面建立 session（防潛在的來源檢查）
    try:
        sess.get("https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070",
                 headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    except Exception:
        pass
    bulk = {"meta": {"generated": datetime.now(timezone.utc).isoformat(),
                     "unit": "million KRW", "source": "KOFIA FreeSIS",
                     "cols": {"credit": "date,total,kospi,kosdaq,daju_t,daju_k,daju_q,ipo,pledge",
                              "funds": "date,deposit,deriv,rp,misugeum,bandae_amt,bandae_ratio",
                              "kospi": "date,index,volume,value,mcap,f_mcap,f_pct",
                              "kosdaq": "date,index,volume,value,mcap,f_mcap,f_pct"}}}
    for key, obj, nc in SERIES:
        acc = []
        # 全歷史一次拉；若失敗改逐4年
        try:
            acc = pack(pull(sess, obj, "19980101", kst_today), nc)
        except Exception:
            y = 1998
            while y <= int(kst_today[:4]):
                d2 = min(y + 3, int(kst_today[:4]))
                acc += pack(pull(sess, obj, f"{y}0101", f"{d2}1231"), nc)
                y += 4
                time.sleep(0.4)
        if not acc:
            print(f"FATAL: {key} empty", file=sys.stderr)
            sys.exit(1)
        # 依日期去重
        ded = {r[0]: r for r in acc}
        bulk[key] = [ded[d] for d in sorted(ded)]
        print(f"{key}: {len(bulk[key])} rows, {bulk[key][0][0]} → {bulk[key][-1][0]}")
        time.sleep(0.4)
    # 基本健全性檢查
    assert len(bulk["credit"]) > 6000 and len(bulk["kospi"]) > 6000, "歷史長度異常"
    import os
    os.makedirs("data", exist_ok=True)
    with open("data/kofia_kr_leverage_bulk.json", "w") as f:
        json.dump(bulk, f)
    print("bulk saved.")

if __name__ == "__main__":
    main()
