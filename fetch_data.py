#!/usr/bin/env python3
"""
台指期貨三大法人多空未平倉淨額
資料來源：臺灣期貨交易所官方 OpenAPI + 備援 HTML 解析
"""

import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser

import requests

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json, text/html, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
})

# ── 資料來源（依序嘗試）────────────────────────────────────
SOURCES = [
    # 期交所官方 OpenAPI v1
    {
        "name": "TAIFEX OpenAPI v1 (整體市場)",
        "url":  "https://openapi.taifex.com.tw/v1/FuturesInstitutionalInvestorsInTheEntireMarket",
        "type": "json",
    },
    # 期交所官方 OpenAPI — 另一個可能的 endpoint
    {
        "name": "TAIFEX OpenAPI v1 (各契約)",
        "url":  "https://openapi.taifex.com.tw/v1/FuturesInstitutionalInvestors",
        "type": "json",
    },
    # 期交所 HTML（多個嘗試）
    {
        "name": "TAIFEX HTML (futContractsDate)",
        "url":  "https://www.taifex.com.tw/cht/3/futContractsDate",
        "type": "html",
    },
]

# 台指期可能的契約名稱關鍵字
TXF_KEYWORDS = ["臺股期貨", "台股期貨", "TXF", "TX ", "臺指"]


def try_fetch_json(url: str) -> list | None:
    try:
        r = SESSION.get(url, timeout=20)
        print(f"  HTTP {r.status_code}  Content-Type: {r.headers.get('content-type','')}")
        print(f"  Body preview: {r.text[:200]!r}")
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "")
        if "json" not in ct and not r.text.strip().startswith("["):
            print("  [SKIP] 不是 JSON 格式")
            return None
        return r.json()
    except Exception as e:
        print(f"  [FAIL] {e}")
        return None


# ── HTML 解析備援（期交所 HTML 頁面）──────────────────────
class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cur_row, self.cur_cell = [], [], ""
        self.in_td = False

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.in_td = True
            self.cur_cell = ""
        if tag == "tr":
            self.cur_row = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.in_td = False
            self.cur_row.append(self.cur_cell.strip())
        if tag == "tr" and self.cur_row:
            self.rows.append(self.cur_row)

    def handle_data(self, data):
        if self.in_td:
            self.cur_cell += data


def parse_taifex_html(url: str) -> list[dict] | None:
    try:
        r = SESSION.get(url, timeout=20)
        print(f"  HTTP {r.status_code}")
        if r.status_code != 200:
            return None
        p = TableParser()
        p.feed(r.text)
        rows = [row for row in p.rows if len(row) >= 10 and re.match(r"\d{4}/\d{2}/\d{2}|\d{3}/\d{2}/\d{2}", row[0])]
        if not rows:
            print("  [SKIP] 找不到日期格式列")
            return None
        print(f"  找到 {len(rows)} 列資料")
        return rows
    except Exception as e:
        print(f"  [FAIL] {e}")
        return None


def safe_int(s):
    try:
        return int(str(s).replace(",", "").strip())
    except:
        return None


def process_json_rows(raw: list) -> dict:
    """處理 OpenAPI JSON 格式"""
    records = {}
    if not raw:
        return records

    # 印出第一筆看欄位
    print(f"\n  [DEBUG] 第一筆資料欄位：")
    for k, v in raw[0].items():
        print(f"    {k}: {v!r}")

    # 找台指期的列
    txf_rows = []
    for row in raw:
        name_fields = [str(row.get(k, "")) for k in ["ContractName", "ContractCode", "名稱", "商品名稱", "contract_name"]]
        combined = " ".join(name_fields)
        if any(kw in combined for kw in TXF_KEYWORDS):
            txf_rows.append(row)

    print(f"\n  台指期相關列數：{len(txf_rows)}")
    if txf_rows:
        print(f"  [DEBUG] 台指期第一筆：{json.dumps(txf_rows[0], ensure_ascii=False)}")

    if not txf_rows:
        # 如果找不到台指期，試著找所有 ContractName
        all_names = sorted(set(
            str(row.get("ContractName", row.get("ContractCode", "?")))
            for row in raw
        ))
        print(f"\n  [DEBUG] 所有 ContractName：{all_names}")
        # 用全部資料試試（整體市場 API 可能本身就只有一筆）
        txf_rows = raw

    for row in txf_rows:
        # 嘗試多種日期欄位名
        date_raw = (row.get("Date") or row.get("日期") or row.get("date") or "")
        date_str = str(date_raw).replace("-", "/").strip()
        if not date_str or len(date_str) < 8:
            continue

        # 民國轉西元
        if re.match(r"^\d{3}/", date_str):
            y = int(date_str[:3]) + 1911
            date_str = f"{y}{date_str[3:]}"

        if date_str in records:
            continue

        # 嘗試多種欄位名稱組合
        def get(row, *keys):
            for k in keys:
                if k in row:
                    return safe_int(row[k])
            return None

        f_long  = get(row, "ForeignDealersLongOI",  "ForLong",  "外資多方")
        f_short = get(row, "ForeignDealersShortOI", "ForShort", "外資空方")
        i_long  = get(row, "InvestmentTrustLongOI", "ITLong",   "投信多方")
        i_short = get(row, "InvestmentTrustShortOI","ITShort",  "投信空方")
        d_long  = get(row, "DealerLongOI",          "DealerLong","自營商多方")
        d_short = get(row, "DealerShortOI",         "DealerShort","自營商空方")

        # 也嘗試直接有淨額的欄位
        foreign = get(row, "ForeignDealersNetOI", "ForNet") or (
            (f_long - f_short) if (f_long is not None and f_short is not None) else None
        )
        itrust  = get(row, "InvestmentTrustNetOI", "ITNet") or (
            (i_long - i_short) if (i_long is not None and i_short is not None) else None
        )
        dealer  = get(row, "DealerNetOI", "DealerNet") or (
            (d_long - d_short) if (d_long is not None and d_short is not None) else None
        )
        total   = (
            (foreign + itrust + dealer)
            if all(x is not None for x in [foreign, itrust, dealer])
            else None
        )

        records[date_str] = {
            "date": date_str,
            "foreign": foreign, "foreign_chg": None,
            "itrust":  itrust,  "itrust_chg":  None,
            "dealer":  dealer,  "dealer_chg":  None,
            "total":   total,   "total_chg":   None,
            "futures": None,    "futures_chg": None,
        }

    return records


def calc_changes(records_map: dict) -> list[dict]:
    sorted_dates = sorted(records_map.keys())
    result, prev = [], None
    for d in sorted_dates:
        r = records_map[d]
        if prev:
            for f in ["foreign", "itrust", "dealer", "total"]:
                r[f"{f}_chg"] = (
                    (r[f] - prev[f]) if (r[f] is not None and prev[f] is not None) else None
                )
        prev = r
        result.append(r)
    return result


def main():
    print("[INFO] 開始從期交所官方 API 取得資料...\n")

    new_records_map = {}

    for src in SOURCES:
        print(f"[TRY] {src['name']}")
        print(f"      URL: {src['url']}")

        if src["type"] == "json":
            raw = try_fetch_json(src["url"])
            if raw and isinstance(raw, list) and len(raw) > 0:
                new_records_map = process_json_rows(raw)
                if new_records_map:
                    print(f"\n[OK] 成功取得 {len(new_records_map)} 筆台指期資料")
                    break
        print()

    if not new_records_map:
        print("[ERROR] 所有來源均失敗，請查看上方 debug 輸出", file=sys.stderr)
        sys.exit(1)

    # 合併舊資料
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        old_map = {r["date"]: r for r in old.get("records", [])}
        print(f"[INFO] 合併舊資料 {len(old_map)} 筆")
    except (FileNotFoundError, json.JSONDecodeError):
        old_map = {}

    merged_map = {**old_map, **new_records_map}
    merged_list = list(reversed(calc_changes(merged_map)))

    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source":  SOURCES[0]["url"],
        "records": merged_list,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[INFO] ✅ 完成！共 {len(merged_list)} 筆，最新: {merged_list[0]['date']}")


if __name__ == "__main__":
    main()
