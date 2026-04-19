#!/usr/bin/env python3
"""
執行這個腳本來確認 TAIFEX API 回傳的欄位名稱。
在 GitHub Actions 或本機執行：python debug_api.py
"""
import json
import requests

INST_URL = "https://openapi.taifex.com.tw/v1/FuturesInstitutionalInvestorsInTheEntireMarket"
HEADERS  = {"Accept": "application/json", "User-Agent": "taifex-debug/1.0"}

print(f"[GET] {INST_URL}")
r = requests.get(INST_URL, headers=HEADERS, timeout=30)
print(f"Status: {r.status_code}")
data = r.json()
print(f"Total rows: {len(data)}")

if data:
    print("\n=== First row (all keys) ===")
    print(json.dumps(data[0], ensure_ascii=False, indent=2))

    print("\n=== Rows containing '臺股期貨' or 'TXF' (first 5) ===")
    count = 0
    for row in data:
        name = str(row.get("ContractName", "")) + str(row.get("ContractCode", ""))
        if "臺股期貨" in name or "TXF" in name:
            print(json.dumps(row, ensure_ascii=False, indent=2))
            count += 1
            if count >= 5:
                break
    if count == 0:
        print("[!] 沒有找到台指期資料，以下是所有 ContractName：")
        names = set(r.get("ContractName", r.get("ContractCode", "?")) for r in data)
        for n in sorted(names):
            print(" -", n)
