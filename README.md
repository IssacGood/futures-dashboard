# 台指期貨三大法人多空未平倉淨額 Dashboard

每日自動更新的台指期貨三大法人多空淨額圖表，資料來源：[玩股網](https://www.wantgoo.com/futures/institutional-investors/net-open-interest)

## 功能

- 📈 三大法人（外資 / 投信 / 自營商）淨額折線圖
- 📊 總和淨額 vs 台指期收盤雙軸對照
- 📉 外資每日增減長條圖
- 📋 近期明細表格
- 🕒 GitHub Actions 每個交易日下午 4:30 自動更新

## 部署方式

1. **Fork 或 clone 此 repo**

2. **開啟 GitHub Pages**：
   - Settings → Pages → Source → `main` branch → `/ (root)` → Save
   - 完成後可從 `https://<你的帳號>.github.io/<repo名>` 訪問

3. **Actions 權限**：
   - Settings → Actions → General → Workflow permissions → 選 **Read and write permissions**

4. **手動觸發第一次**：
   - Actions → `每日更新台指期貨法人資料` → Run workflow

## 檔案說明

| 檔案 | 說明 |
|------|------|
| `index.html` | 圖表展示頁面 |
| `data.json` | 爬取的資料（自動更新） |
| `fetch_data.py` | 爬蟲腳本 |
| `.github/workflows/update.yml` | GitHub Actions 排程 |

## 注意事項

- 玩股網免費版只顯示近 30 日資料，爬蟲會自動與舊資料合併累積歷史
- 若玩股網更改頁面結構，`fetch_data.py` 可能需要調整
