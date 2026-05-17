# Windows Task Scheduler 設定步驟（雙軌制版）

## 1) 先在專案資料夾建立虛擬環境並安裝套件

```powershell
cd C:\tsmc-agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2) 設定 `.env`
至少先填：
- `GEMINI_API_KEY`
- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `EMAIL_TO`

若要每日直接推 LINE，再填：
- `LINE_PUSH_ENABLED=true`
- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_TO_ID`

## 3) 手動先測一次

```powershell
.\.venv\Scripts\python.exe .\daily_tsmc_report.py
```

成功後，`reports\` 底下會出現：
- `YYYY-MM-DD_tsmc_report.txt`
- `YYYY-MM-DD_tsmc_summary.txt`
- `YYYY-MM-DD_tsmc_meta.json`

## 4) 建議的排程方式
不要只排「週一到週五」。
請直接排 **每天 14:30**，再由程式自己判斷今天是否為休市 / 補假 / 週末。

這樣即使遇到特殊交易日或補班情況，也不會因排程本身先天漏掉。

## 5) 圖形介面設定法
1. 開啟「工作排程器」。
2. 右側按「建立工作」。
3. 【一般】
   - 名稱：`TSMC Daily Report`
   - 勾選「不論使用者是否登入都執行」
   - 勾選「使用最高權限執行」
4. 【觸發程序】
   - 新增
   - 開始工作：依排程
   - 設定：每日
   - 開始時間：14:30:00
5. 【動作】
   - 新增
   - 動作：啟動程式
   - 程式或指令碼：
     `C:\tsmc-agent\.venv\Scripts\python.exe`
   - 新增引數：
     `C:\tsmc-agent\daily_tsmc_report.py`
   - 起始於：
     `C:\tsmc-agent`
6. 【條件】
   - 取消「只有使用交流電源才啟動工作」
7. 【設定】
   - 勾選「若錯過排定的開始時間，請儘快執行」
   - 勾選「如果工作失敗，每隔 30 分鐘重新啟動一次」
   - 嘗試次數：3

## 6) 命令列建立法

```powershell
schtasks /create `
  /tn "TSMC Daily Report" `
  /tr "\"C:\tsmc-agent\.venv\Scripts\python.exe\" \"C:\tsmc-agent\daily_tsmc_report.py\"" `
  /sc daily `
  /st 14:30 `
  /f
```

## 7) 立即手動執行一次排程

```powershell
schtasks /run /tn "TSMC Daily Report"
```

## 8) 查詢排程

```powershell
schtasks /query /tn "TSMC Daily Report" /v /fo list
```

## 9) 刪除排程

```powershell
schtasks /delete /tn "TSMC Daily Report" /f
```

## 10) OpenClaw 不需另外排第二個每日任務
因為現在每日主流程已內建：
- 生成完整報告
- 生成 LINE 摘要
- 視設定直接推送 LINE

OpenClaw 的角色改為：
- 你在 LINE 上臨時查狀態
- 要求讀取今日摘要
- 手動重送一次 LINE 摘要
