#!/usr/bin/env python3
"""
台指期貨三大法人多空未平倉淨額 爬蟲
每天由 GitHub Actions 執行，資料存到 data.json
"""

import json
import re
import sys
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

URL = "https://www.wantgoo.com/futures/institutional-investors/net-open-interest"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.wantgoo.com/",
}


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.rows = []
        self.current_row = []
        self.current_cell = ""
        self.table_count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table_count += 1
            if self.table_count == 1:
                self.in_table = True
        if self.in_table:
            if tag == "tr":
                self.in_tr = True
                self.current_row = []
            if tag in ("td", "th") and self.in_tr:
                self.in_td = True
                self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.in_table = False
        if self.in_table:
            if tag in ("td", "th") and self.in_td:
                self.in_td = False
                self.current_row.append(self.current_cell.strip())
            if tag == "tr" and self.in_tr:
                self.in_tr = False
                if self.current_row:
                    self.rows.append(self.current_row)

    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data


def parse_num(s: str):
    """Convert string like '-36,158' or '2,354' to int; return None if not parseable."""
    s = s.replace(",", "").replace(" ", "").replace("\xa0", "")
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def fetch_and_parse():
    req = Request(URL, headers=HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        print(f"[ERROR] 無法取得頁面: {e}", file=sys.stderr)
        sys.exit(1)

    parser = TableParser()
    parser.feed(html)

    records = []
    for row in parser.rows:
        # 每列至少要有 17 欄，且第一欄符合 YYYY/MM/DD
        if len(row) < 17:
            continue
        if not re.match(r"\d{4}/\d{2}/\d{2}", row[0]):
            continue

        date_str = row[0]
        foreign      = parse_num(row[1])   # 外資 口數
        foreign_chg  = parse_num(row[2])   # 外資 增減
        itrust       = parse_num(row[5])   # 投信 口數
        itrust_chg   = parse_num(row[6])   # 投信 增減
        dealer       = parse_num(row[7])   # 自營商 口數
        dealer_chg   = parse_num(row[8])   # 自營商 增減
        total        = parse_num(row[9])   # 總和 口數
        total_chg    = parse_num(row[10])  # 總和 增減
        futures_price= parse_num(row[11])  # 台指期 收盤
        futures_chg  = parse_num(row[12])  # 台指期 漲跌

        if foreign is None or date_str is None:
            continue

        records.append({
            "date":         date_str,
            "foreign":      foreign,
            "foreign_chg":  foreign_chg,
            "itrust":       itrust,
            "itrust_chg":   itrust_chg,
            "dealer":       dealer,
            "dealer_chg":   dealer_chg,
            "total":        total,
            "total_chg":    total_chg,
            "futures":      futures_price,
            "futures_chg":  futures_chg,
        })

    return records


def main():
    print("[INFO] 開始爬取資料...")
    records = fetch_and_parse()

    if not records:
        print("[ERROR] 沒有解析到任何資料，請確認頁面結構是否有更動", file=sys.stderr)
        sys.exit(1)

    # 嘗試合併舊資料（避免歷史消失）
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        old_map = {r["date"]: r for r in old.get("records", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        old_map = {}

    for r in records:
        old_map[r["date"]] = r

    merged = sorted(old_map.values(), key=lambda x: x["date"], reverse=True)

    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": URL,
        "records": merged,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[INFO] 完成！共 {len(merged)} 筆資料，最新：{merged[0]['date']}")


if __name__ == "__main__":
    main()
