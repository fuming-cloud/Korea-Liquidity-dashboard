# -*- coding: utf-8 -*-
"""組裝儀表板: indicators.json + 管線原始碼 → korea_deleverage_dashboard.html"""
import json, base64, os, sys

def main():
    ind_path = sys.argv[1] if len(sys.argv) > 1 else "out/indicators.json"
    with open(ind_path, encoding="utf-8") as f:
        ind = f.read()
    with open("dashboard_template.html", encoding="utf-8") as f:
        tpl = f.read()
    # 內嵌管線原始碼 (讓排程工作階段可從 artifact 還原系統)
    src = {}
    for fn in []:  # GitHub 版：原始碼由倉庫本身保存，不內嵌
        if os.path.exists(fn):
            with open(fn, "rb") as f:
                src[fn.split("/")[-1]] = base64.b64encode(f.read()).decode()
    out = tpl.replace("/*__DATA__*/null", ind, 1)
    out = out.replace("/*__SRC__*/null", json.dumps(src), 1)
    with open("out/korea_deleverage_dashboard.html", "w", encoding="utf-8") as f:
        f.write(out)
    print("OK", len(out), "bytes -> out/korea_deleverage_dashboard.html")

if __name__ == "__main__":
    main()
