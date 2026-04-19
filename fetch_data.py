#!/usr/bin/env python3
"""
台指期貨三大法人多空未平倉淨額
資料來源：臺灣期貨交易所 https://www.taifex.com.tw/cht/3/futContractsDate
每天由 GitHub Actions 執行，資料累積存到 data.json

資料結構（已確認）：
  每列包含：序號、商品名稱、身份別、多方口數、多方金額、空方口數、空方金額、多空淨額口數、多空淨額金額
  未平倉餘額也在同一列，欄位 9-14
  臺股期貨 = 序號1，包含3列：自營商、投信、外資
"""

import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser

import requests

URL = "https://www.taifex.com.tw/cht/3/futContractsDate"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://www.taifex.com.tw/cht/3/futContractsDate",
}


class TableParser(HTMLParser):
    """解析 HTML 表格，回傳 list of list[str]"""
    def __init__(self):
        super().__init__()
        self.tables = []        # 所有 table 的所有列
        self.cur_table = []     # 目前 table 的列
        self.cur_row = []       # 目前列
        self.cur_cell = ""      # 目前格
        self.in_td = False
        self.in_table = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.cur_table = []
        elif tag in ("tr",):
            self.cur_row = []
        elif tag in ("td", "th") and self.in_table:
            self.in_td = True
            self.cur_cell = ""
            # 讀取 rowspan/colspan（暫不展開，但要記錄）
        
    def handle_endtag(self, tag):
        if tag == "table":
            self.tables.append(self.cur_table)
            self.in_table = False
        elif tag in ("td", "th") and self.in_table:
            self.in_td = False
            self.cur_row.append(self.cur_cell.strip())
        elif tag == "tr" and self.in_table and self.cur_row:
            self.cur_table.append(self.cur_row)
            self.cur_row = []

    def handle_data(self, data):
        if self.in_td:
            self.cur_cell += data.strip()


def safe_int(s: str) -> int | None:
    try:
        return int(str(s).replace(",", "").replace(" ", "").strip())
    except:
        return None


def extract_date(html: str) -> str | None:
    """從 HTML 標題或表格抓日期"""
    # 格式: 日期2026/04/17 或 日期YYYY/MM/DD
    m = re.search(r"日期(\d{4}/\d{2}/\d{2})", html)
    if m:
        return m.group(1)
    return None


def parse(html: str) -> dict | None:
    """
    解析 futContractsDate 頁面，回傳台指期三大法人未平倉淨額。
    
    表格欄位（已確認）：
    col 0: 序號
    col 1: 商品名稱  (跨列 rowspan=3，但 parser 只在第一列出現)
    col 2: 身份別    (自營商/投信/外資)
    col 3: 交易多方口數
    col 4: 交易多方金額
    col 5: 交易空方口數
    col 6: 交易空方金額
    col 7: 交易多空淨額口數
    col 8: 交易多空淨額金額
    col 9: 未平倉多方口數    ← 我們要的
    col 10: 未平倉多方金額
    col 11: 未平倉空方口數   ← 我們要的
    col 12: 未平倉空方金額
    col 13: 未平倉多空淨額口數  ← 直接有！
    col 14: 未平倉多空淨額金額
    """
    date_str = extract_date(html)
    if not date_str:
        print("[WARN] 找不到日期", file=sys.stderr)
        return None

    parser = TableParser()
    parser.feed(html)

    data = {"dealer": None, "itrust": None, "foreign": None}

    # 找包含 "臺股期貨" 的表格
    for table in parser.tables:
        found_txf = False
        current_product = None

        for row in table:
            if not row:
                continue
            
            # 找到臺股期貨的列（序號=1，商品名稱含臺股期貨）
            # 因為 rowspan，第一列有商品名稱，後兩列只有身份別
            
            # 判斷是否有商品名稱（臺股期貨）
            row_str = "".join(row)
            if "臺股期貨" in row_str:
                found_txf = True
                current_product = "臺股期貨"
            
            if not found_txf:
                continue

            # 找身份別
            identity = None
            for cell in row:
                cell = cell.strip()
                if cell in ("自營商", "投信", "外資"):
                    identity = cell
                    break
            
            if identity is None:
                continue

            # 嘗試從列中取出未平倉淨額（col 13）
            # 由於 HTML parser 不展開 rowspan，列長度會不同
            # 第一列（含商品名稱）比後兩列多1欄
            # 我們要找 "多空淨額口數" 在未平倉區
            
            # 過濾掉純文字標題列
            nums = [c for c in row if re.match(r"^-?[\d,]+$", c.strip())]
            
            if len(nums) >= 6:
                # 最後一批數字是未平倉區 (多方口數, 多方金額, 空方口數, 空方金額, 淨額口數, 淨額金額)
                # 取倒數第三個（淨額口數）
                net_oi = safe_int(nums[-3])  # 未平倉多空淨額口數
                
                if identity == "自營商":
                    data["dealer"] = net_oi
                elif identity == "投信":
                    data["itrust"] = net_oi
                elif identity == "外資":
                    data["foreign"] = net_oi

            # 遇到下一個商品（序號≥2）就停止
            if "電子期貨" in row_str or "金融期貨" in row_str:
                break

        if found_txf and any(v is not None for v in data.values()):
            break  # 找到了就不用繼續找其他 table

    # 若三個都是 None，嘗試備案：用 regex 直接從 HTML 中搜尋
    if all(v is None for v in data.values()):
        print("[WARN] 表格解析失敗，嘗試 regex 備援", file=sys.stderr)
        data = parse_regex_fallback(html)

    if all(v is None for v in data.values()):
        return None

    total = None
    if all(v is not None for v in [data["dealer"], data["itrust"], data["foreign"]]):
        total = data["dealer"] + data["itrust"] + data["foreign"]

    return {
        "date":    date_str,
        "foreign": data["foreign"],
        "itrust":  data["itrust"],
        "dealer":  data["dealer"],
        "total":   total,
        "foreign_chg": None,
        "itrust_chg":  None,
        "dealer_chg":  None,
        "total_chg":   None,
        "futures":     None,
        "futures_chg": None,
    }


def parse_regex_fallback(html: str) -> dict:
    """備援：regex 直接從 HTML 找臺股期貨的三大法人未平倉淨額"""
    data = {"dealer": None, "itrust": None, "foreign": None}
    
    # 找臺股期貨區段
    txf_match = re.search(r"臺股期貨(.*?)電子期貨", html, re.DOTALL)
    if not txf_match:
        return data
    
    segment = txf_match.group(1)
    
    # 在這個區段裡找各身份別
    for identity, key in [("自營商", "dealer"), ("投信", "itrust"), ("外資", "foreign")]:
        m = re.search(rf"{identity}(.*?)(投信|外資|</tr>)", segment, re.DOTALL)
        if m:
            nums = re.findall(r"-?[\d,]+", m.group(1))
            nums_int = [safe_int(n) for n in nums if safe_int(n) is not None]
            if len(nums_int) >= 6:
                data[key] = nums_int[-3]  # 未平倉多空淨額口數
    
    return data


def calc_changes(records_map: dict) -> list[dict]:
    sorted_dates = sorted(records_map.keys())
    result, prev = [], None
    for d in sorted_dates:
        r = records_map[d]
        if prev:
            for f in ["foreign", "itrust", "dealer", "total"]:
                r[f"{f}_chg"] = (
                    (r[f] - prev[f])
                    if (r[f] is not None and prev[f] is not None)
                    else None
                )
        prev = r
        result.append(r)
    return result


def main():
    print("[INFO] 從期交所官方頁面取得三大法人未平倉資料...")
    print(f"[INFO] URL: {URL}")

    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        html = r.content.decode("utf-8", errors="replace")
        print(f"[INFO] HTTP {r.status_code}, 頁面大小: {len(html)} chars")
    except requests.RequestException as e:
        print(f"[ERROR] 請求失敗: {e}", file=sys.stderr)
        sys.exit(1)

    record = parse(html)

    if record is None:
        print("[WARN] 解析失敗，可能是非交易日或頁面結構異動")
        print("[INFO] 列印 HTML 前 1000 字元供排查：")
        print(html[:1000])
        # 非交易日不視為錯誤
        sys.exit(0)

    print(f"[INFO] 解析成功：{record['date']} | 外資={record['foreign']} | 投信={record['itrust']} | 自營商={record['dealer']} | 總和={record['total']}")

    # 合併舊資料
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        old_map = {r["date"]: r for r in old.get("records", [])}
        print(f"[INFO] 載入舊資料 {len(old_map)} 筆")
    except (FileNotFoundError, json.JSONDecodeError):
        old_map = {}

    old_map[record["date"]] = record
    merged_list = list(reversed(calc_changes(old_map)))

    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": URL,
        "records": merged_list,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[INFO] ✅ 完成！共 {len(merged_list)} 筆，最新: {merged_list[0]['date']}")


if __name__ == "__main__":
    main()
