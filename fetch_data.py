#!/usr/bin/env python3
"""
台指期貨三大法人多空未平倉淨額 — 資料來源：臺灣期貨交易所官方 OpenAPI
API Docs: https://openapi.taifex.com.tw/
每天由 GitHub Actions 執行，資料累積存到 data.json
"""

import json
import sys
from datetime import datetime

import requests

# ── 期交所官方 OpenAPI endpoints ─────────────────────────────
# 傳回整體市場三大法人期貨未平倉（含台指期 TXF）
INST_URL = "https://openapi.taifex.com.tw/v1/FuturesInstitutionalInvestorsInTheEntireMarket"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; taifex-dashboard/1.0)",
}

# 我們只關注台指期（契約代碼 TXF）
TARGET_CONTRACT = "臺股期貨"  # 中文名稱
TARGET_CODE     = "TXF"


def fetch_institutional() -> list[dict]:
    """
    抓取三大法人未平倉資料，回傳 list of dict（已過濾台指期）。
    API 回傳 JSON 陣列，欄位示意：
      {
        "Date": "2024/01/02",
        "ContractName": "臺股期貨",
        "ForeignDealersLongOI":  "...",
        "ForeignDealersShortOI": "...",
        ...
      }
    """
    resp = requests.get(INST_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def safe_int(s: str) -> int | None:
    """去除千分位逗號後轉 int，失敗回 None。"""
    try:
        return int(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def process(raw: list[dict]) -> list[dict]:
    """
    從 API 原始資料中過濾出台指期，計算各法人多空淨額。

    API 欄位（依期交所 Swagger 說明）：
      Date, ContractName,
      ForeignDealersLongOI, ForeignDealersShortOI,
      InvestmentTrustLongOI, InvestmentTrustShortOI,
      DealerLongOI, DealerShortOI,
      TotalLongOI, TotalShortOI
    """
    records = {}

    for row in raw:
        # 過濾台指期
        name = row.get("ContractName", "")
        if TARGET_CONTRACT not in name and TARGET_CODE not in row.get("ContractCode", ""):
            continue

        date_raw = row.get("Date", "")
        # 統一格式 YYYY/MM/DD
        date_str = date_raw.replace("-", "/")
        if not date_str or len(date_str) < 8:
            continue

        # 外資
        f_long  = safe_int(row.get("ForeignDealersLongOI",  0))
        f_short = safe_int(row.get("ForeignDealersShortOI", 0))
        # 投信
        i_long  = safe_int(row.get("InvestmentTrustLongOI",  0))
        i_short = safe_int(row.get("InvestmentTrustShortOI", 0))
        # 自營商
        d_long  = safe_int(row.get("DealerLongOI",  0))
        d_short = safe_int(row.get("DealerShortOI", 0))

        # 淨額 = 多 - 空
        foreign = (f_long - f_short) if (f_long is not None and f_short is not None) else None
        itrust  = (i_long - i_short) if (i_long is not None and i_short is not None) else None
        dealer  = (d_long - d_short) if (d_long is not None and d_short is not None) else None
        total   = (foreign + itrust + dealer) if all(x is not None for x in [foreign, itrust, dealer]) else None

        # 如果同一天已有記錄（可能有多個到期月份），只保留近月（第一筆通常是近月）
        if date_str in records:
            continue

        records[date_str] = {
            "date":    date_str,
            "foreign": foreign,
            "itrust":  itrust,
            "dealer":  dealer,
            "total":   total,
            # 增減欄位在下面計算
            "foreign_chg": None,
            "itrust_chg":  None,
            "dealer_chg":  None,
            "total_chg":   None,
            "futures":     None,  # 收盤指數另外補（若有）
            "futures_chg": None,
        }

    return records


def calc_changes(records_map: dict) -> list[dict]:
    """依日期排序後計算每日增減。"""
    sorted_dates = sorted(records_map.keys())
    result = []
    prev = None
    for d in sorted_dates:
        r = records_map[d]
        if prev:
            r["foreign_chg"] = (r["foreign"] - prev["foreign"]) if (r["foreign"] is not None and prev["foreign"] is not None) else None
            r["itrust_chg"]  = (r["itrust"]  - prev["itrust"])  if (r["itrust"]  is not None and prev["itrust"]  is not None) else None
            r["dealer_chg"]  = (r["dealer"]  - prev["dealer"])  if (r["dealer"]  is not None and prev["dealer"]  is not None) else None
            r["total_chg"]   = (r["total"]   - prev["total"])   if (r["total"]   is not None and prev["total"]   is not None) else None
        prev = r
        result.append(r)
    return result


def main():
    print("[INFO] 開始從期交所官方 API 取得資料...")

    try:
        raw = fetch_institutional()
    except requests.RequestException as e:
        print(f"[ERROR] API 請求失敗: {e}", file=sys.stderr)
        sys.exit(1)

    if not raw:
        print("[ERROR] API 回傳空資料", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] 原始資料筆數: {len(raw)}")

    new_records_map = process(raw)
    print(f"[INFO] 台指期筆數（新抓）: {len(new_records_map)}")

    if not new_records_map:
        print("[WARN] 未找到台指期資料，可能是非交易日或 API 欄位有異動")
        # 非交易日不視為錯誤，直接結束（不更新 data.json）
        sys.exit(0)

    # ── 讀取並合併舊資料 ──────────────────────────────────────
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        old_map = {r["date"]: r for r in old.get("records", [])}
        print(f"[INFO] 舊資料筆數: {len(old_map)}")
    except (FileNotFoundError, json.JSONDecodeError):
        old_map = {}

    # 新資料覆蓋舊資料（同日期以新為主）
    merged_map = {**old_map, **new_records_map}

    # 重新計算增減（合併後排序重算，確保準確）
    merged_list = calc_changes(merged_map)

    # 最終輸出（最新在前）
    merged_list_desc = list(reversed(merged_list))

    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source":  INST_URL,
        "records": merged_list_desc,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[INFO] ✅ 完成！共 {len(merged_list_desc)} 筆，最新: {merged_list_desc[0]['date']}")


if __name__ == "__main__":
    main()
