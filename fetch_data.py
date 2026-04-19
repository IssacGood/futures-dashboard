#!/usr/bin/env python3
"""
台指期貨三大法人多空未平倉淨額
資料來源：臺灣期貨交易所 https://www.taifex.com.tw/cht/3/futContractsDate

表格確認欄位（每一身份別一列，共14欄）：
  col 0:  序號（只有第一列有）
  col 1:  商品名稱（只有第一列有）
  col 2:  身份別
  col 3:  交易多方口數   ← 不要
  col 4:  交易多方金額   ← 不要
  col 5:  交易空方口數   ← 不要
  col 6:  交易空方金額   ← 不要
  col 7:  交易多空淨額口數 ← 不要
  col 8:  交易多空淨額金額 ← 不要
  col 9:  未平倉多方口數  ← 需要
  col 10: 未平倉多方金額  ← 不要
  col 11: 未平倉空方口數  ← 需要
  col 12: 未平倉空方金額  ← 不要
  col 13: 未平倉多空淨額口數 ← 直接用！
  col 14: 未平倉多空淨額金額 ← 不要

問題所在：原本錯誤地取了「最後數字」，但 rowspan 合併導致列長度不一致，
導致取到了金額而不是口數。
修正：精確定位 col 13（倒數第2個數字欄位，因為最後1個是金額）。
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
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://www.taifex.com.tw/cht/3/futContractsDate",
}


def safe_int(s):
    try:
        return int(str(s).replace(",", "").strip())
    except:
        return None


class RowParser(HTMLParser):
    """精準解析 HTML table，保留每格原始文字"""
    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = []
        self._cell = ""
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_cell = False
            self._row.append(self._cell.strip())
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
                self._row = []

    def handle_data(self, data):
        if self._in_cell:
            self._cell += data


def parse(html: str):
    """
    回傳 { "date": "YYYY/MM/DD", "dealer": int, "itrust": int, "foreign": int, "total": int }
    解析臺股期貨三大法人「未平倉多空淨額口數」
    """
    # 抓日期
    m = re.search(r"日期(\d{4}/\d{2}/\d{2})", html)
    if not m:
        print("[WARN] 找不到日期，可能是非交易日")
        return None
    date_str = m.group(1)

    parser = RowParser()
    parser.feed(html)

    results = {}   # identity -> net OI

    in_txf = False
    for row in parser.rows:
        text = "".join(row)

        # 進入臺股期貨區段
        if "臺股期貨" in text:
            in_txf = True

        # 離開臺股期貨（遇到下一個契約）
        if in_txf and any(x in text for x in ["電子期貨", "金融期貨", "小型臺指"]):
            break

        if not in_txf:
            continue

        # 找身份別
        identity = None
        for cell in row:
            if cell in ("自營商", "投信", "外資"):
                identity = cell
                break
        if identity is None:
            continue

        # 取出所有數字（含負號），過濾標題
        nums = []
        for cell in row:
            c = cell.replace(",", "").strip()
            if re.fullmatch(r"-?\d+", c):
                nums.append(int(c))

        # 預期有 12 個數字欄（每個區各6欄：多方口數、多方金額、空方口數、空方金額、淨額口數、淨額金額）
        # 交易區：nums[0..5]  未平倉區：nums[6..11]
        # 未平倉多空淨額口數 = nums[10]（倒數第2）
        if len(nums) >= 11:
            net_oi = nums[-2]   # 未平倉多空淨額口數（倒數第2，最後1個是金額千元）
            results[identity] = net_oi
            print(f"  {identity}: 未平倉淨額 = {net_oi:,} 口  (raw nums={nums})")
        else:
            print(f"  [SKIP] {identity} 數字欄不足 ({len(nums)} 個): {nums}")

    if not results:
        return None

    dealer  = results.get("自營商")
    itrust  = results.get("投信")
    foreign = results.get("外資")
    total   = (dealer + itrust + foreign) if all(v is not None for v in [dealer, itrust, foreign]) else None

    return {
        "date":    date_str,
        "foreign": foreign, "foreign_chg": None,
        "itrust":  itrust,  "itrust_chg":  None,
        "dealer":  dealer,  "dealer_chg":  None,
        "total":   total,   "total_chg":   None,
        "futures": None,    "futures_chg": None,
    }


def calc_changes(records_map: dict) -> list:
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
    print(f"[INFO] 抓取期交所三大法人未平倉資料...")

    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        html = r.content.decode("utf-8", errors="replace")
        print(f"[INFO] HTTP {r.status_code}，頁面 {len(html):,} chars")
    except requests.RequestException as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    record = parse(html)

    if record is None:
        print("[WARN] 無資料（可能是非交易日），略過更新")
        sys.exit(0)

    print(f"[OK] {record['date']} | 外資={record['foreign']} | 投信={record['itrust']} | 自營商={record['dealer']} | 總={record['total']}")

    # 合併舊資料
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        old_map = {r["date"]: r for r in old.get("records", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        old_map = {}

    old_map[record["date"]] = record
    merged = list(reversed(calc_changes(old_map)))

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": URL,
            "records": merged,
        }, f, ensure_ascii=False, indent=2)

    print(f"[INFO] ✅ 共 {len(merged)} 筆，最新: {merged[0]['date']}")


if __name__ == "__main__":
    main()
