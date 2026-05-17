# 台股台積電股價查詢分析

這是一個以 **Python + Gemini API** 製作的個人自動化專案，用來每日查詢台股台積電（2330）成交資料，判斷台灣股市當日是否有新資料，並透過 Gemini 產生台積電股價與總體／產業／個股面向的分析報告。

目前版本已調整為 **純本機排程主流程**：

- ✅ 停用 OpenClaw 作為主要執行流程，避免額外串接高級模型或增加不必要成本
- ✅ 使用 `gemini-2.5-flash` 作為主模型
- ✅ 使用 `gemini-2.5-flash-lite` 作為備用模型
- ✅ 明確開啟 Gemini 2.5 Flash-Lite 的 thinking mode
- ✅ 備用模型 thinking budget 設為 `24576`
- ✅ 每日產生完整報告、LINE 摘要與 meta 記錄
- ✅ 可寄送 Gmail
- ✅ 可選擇直接推播 LINE 摘要

> ⚠️ 本專案輸出的分析僅供個人研究與自動化練習使用，不構成投資建議。

---

## 功能特色

### 1. 每日查詢台積電成交資料

程式會從台灣證券交易所資料來源取得台積電（2330）近期成交資料，並更新本機歷史資料檔。

主要處理內容：

- 查詢台積電月成交資訊
- 整理最近成交日
- 判斷今天是否已有新成交資料
- 更新 `data/tsmc_history.csv`

### 2. 判斷台股是否開市

程式會檢查台灣股市開休市資料，避免單純以「週一到週五」判斷交易日。

因此遇到以下情況時，比較不容易誤判：

- 國定假日
- 補假
- 特殊休市日
- 週末
- 官方資料尚未更新

### 3. Gemini 自動分析

主程式會呼叫 Gemini API，並使用 Google Search grounding 查詢近期市場資訊，產生台積電分析報告。

分析框架包含：

1. 全球地緣政治與系統性風險
2. 全球總體經濟與資金面
3. 半導體產業週期與科技巨頭動態
4. 台積電個股基本面、籌碼面與技術面

報告會輸出：

- 總結
- 明日漲跌幅推估
- 未來一週漲跌幅推估
- 未來一個月漲跌幅推估
- 未來三個月漲跌幅推估
- 未來半年漲跌幅推估
- 可能買點
- 可能賣點
- 利多因素
- 利空因素
- 關鍵觀察指標
- 風險提醒
- 信心等級

### 4. 主模型與備用模型

目前模型設定採用主備援機制：

| 角色 | 預設模型 | 用途 |
|---|---|---|
| 主模型 | `gemini-2.5-flash` | 一般情況下優先使用 |
| 備用模型 | `gemini-2.5-flash-lite` | 主模型遇到 429 / 503 / 504 等可重試錯誤時切換使用 |

程式會記錄：

- 本次實際使用的模型
- 是否切換到備用模型
- 切換原因
- 嘗試模型順序
- 主模型 thinking budget
- 備用模型 thinking budget
- 本次實際 thinking budget

這些資訊會出現在：

- `reports/YYYY-MM-DD_tsmc_report.txt`
- `reports/YYYY-MM-DD_tsmc_meta.json`

### 5. Gemini 2.5 Flash-Lite thinking mode

本版本特別針對 `gemini-2.5-flash-lite` 明確設定 `thinkingBudget`。

建議設定：

```env
GEMINI_MODEL_PRIMARY=gemini-2.5-flash
GEMINI_MODEL_FALLBACK=gemini-2.5-flash-lite
GEMINI_THINKING_BUDGET_PRIMARY=-1
GEMINI_THINKING_BUDGET_FALLBACK=24576
GEMINI_INCLUDE_THOUGHTS=false
```

說明：

| 設定值 | 意義 |
|---:|---|
| `0` | 關閉 thinking |
| `-1` | dynamic thinking，由模型依問題複雜度自行調整 |
| `512` ~ `24576` | 指定 thinking token budget |
| `24576` | Gemini 2.5 Flash / Flash-Lite 的最高 thinking budget |

> Google 官方文件指出，Gemini 2.5 Flash-Lite 在未設定 thinking budget 時，預設不會思考；若要讓 Flash-Lite 使用 thinking，應明確指定 `thinkingBudget`。

---

## 專案結構

```text
.
├─ daily_tsmc_report.py              # 每日主流程
├─ tsmc_agent_common.py              # 共用工具函式
├─ requirements.txt                  # Python 套件需求
├─ .env.example                      # 環境變數範本
├─ windows_task_scheduler.md         # Windows 工作排程器設定說明
├─ line_setup.md                     # LINE 推播設定說明
├─ data/
│  ├─ tsmc_history.csv               # 台積電歷史成交資料
│  └─ latest_news_cache.json         # Gemini grounding 來源快取
├─ reports/
│  ├─ YYYY-MM-DD_tsmc_report.txt     # 完整分析報告
│  ├─ YYYY-MM-DD_tsmc_summary.txt    # LINE 用短摘要
│  └─ YYYY-MM-DD_tsmc_meta.json      # 本次執行中繼資料
└─ openclaw_report_helper.py         # 舊版 OpenClaw 查詢輔助工具，目前非主流程
```

---

## 安裝方式

以下以 Windows 為例，建議安裝在：

```text
C:\tsmc-agent
```

### 1. 建立虛擬環境

```powershell
cd C:\tsmc-agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

若你的電腦只有 Python 3.10，也可以改用：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. 安裝套件

```powershell
pip install -r requirements.txt
```

目前主要套件：

```text
google-genai>=1.30.0
python-dotenv>=1.0.1
requests>=2.32.0
tzdata>=2025.3
```

---

## 環境變數設定

請先複製 `.env.example` 成 `.env`：

```powershell
copy .env.example .env
```

然後編輯 `.env`。

### Gemini 設定

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
GEMINI_MODEL_PRIMARY=gemini-2.5-flash
GEMINI_MODEL_FALLBACK=gemini-2.5-flash-lite

GEMINI_THINKING_BUDGET_PRIMARY=-1
GEMINI_THINKING_BUDGET_FALLBACK=24576
GEMINI_INCLUDE_THOUGHTS=false
```

建議：

- `GEMINI_THINKING_BUDGET_PRIMARY=-1`：主模型使用 dynamic thinking
- `GEMINI_THINKING_BUDGET_FALLBACK=24576`：備用模型 Flash-Lite 明確開啟 thinking，並給最高 budget
- `GEMINI_INCLUDE_THOUGHTS=false`：一般不建議輸出 thought summary，避免報告混入不必要內容

### 報告與股票設定

```env
REPORT_TIMEZONE=Asia/Taipei
STOCK_NO=2330
HTTP_TIMEOUT_SECONDS=30
```

### Gmail SMTP 設定

```env
GMAIL_USER=your_gmail@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
EMAIL_TO=receiver1@example.com,receiver2@example.com
```

注意：

- `GMAIL_APP_PASSWORD` 應使用 Google 帳號的 App Password
- 不建議使用 Gmail 帳號的正式登入密碼
- 多位收件人請用逗號分隔

### LINE 推播設定（可選）

若只想寄 Email，不想推 LINE：

```env
LINE_PUSH_ENABLED=false
```

若要每日完成後直接推播 LINE 摘要：

```env
LINE_PUSH_ENABLED=true
LINE_PUSH_ONLY_IF_NEW_DATA=true
LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_CHANNEL_ACCESS_TOKEN
LINE_TO_ID=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

說明：

| 變數 | 說明 |
|---|---|
| `LINE_PUSH_ENABLED` | 是否啟用每日 LINE 主動推播 |
| `LINE_PUSH_ONLY_IF_NEW_DATA` | 是否只有今天真的有新成交資料才推播 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API channel access token |
| `LINE_TO_ID` | LINE user / group / room ID |

---

## 執行方式

### 手動執行一次

```powershell
cd C:\tsmc-agent
.\.venv\Scripts\python.exe .\daily_tsmc_report.py
```

成功後，`reports\` 底下會產生：

```text
YYYY-MM-DD_tsmc_report.txt
YYYY-MM-DD_tsmc_summary.txt
YYYY-MM-DD_tsmc_meta.json
```

同時會更新：

```text
data\tsmc_history.csv
data\latest_news_cache.json
```

### 報告內容

完整報告會包含：

- 執行日期
- 最近成交日
- 最近收盤價
- 最近漲跌價差
- 是否取得今日新成交資料
- Gemini 模型使用資訊
- thinking budget 使用資訊
- 台積電股價分析正文
- LINE 用短摘要
- TWSE / 行政院人事行政總處 / Gemini grounding 來源

---

## Windows Task Scheduler 建議設定

建議排程方式：**每天 14:30 執行一次**。

不要只排週一到週五，因為台股可能遇到補班日、特殊交易日或臨時休市。比較穩的做法是每天執行，讓程式自己判斷當天是否有新成交資料。

### 圖形介面設定重點

| 欄位 | 建議值 |
|---|---|
| 名稱 | `TSMC Daily Report` |
| 觸發程序 | 每天 14:30 |
| 程式或指令碼 | `C:\tsmc-agent\.venv\Scripts\python.exe` |
| 新增引數 | `C:\tsmc-agent\daily_tsmc_report.py` |
| 起始於 | `C:\tsmc-agent` |

詳細設定可參考：

```text
windows_task_scheduler.md
```

---

## OpenClaw 狀態

本版本已將 OpenClaw 從主要流程中停用。

也就是說，目前不需要：

- OpenClaw gateway
- OpenClaw LINE webhook
- OpenClaw 排程
- 額外串接高級模型

目前主流程只需要：

```text
daily_tsmc_report.py
```

舊版 OpenClaw 相關檔案若仍保留，主要是歷史參考或備用查詢用途，例如：

```text
openclaw_report_helper.py
openclaw.json.example
openclaw_line_commands.md
openclaw.env.example
```

若你只想使用目前的低成本本機排程版本，可以忽略這些檔案。

---

## GitHub 上傳前注意事項

公開到 GitHub 前，務必確認不要上傳任何密鑰或個人資料。

### 絕對不要 commit

```text
.env
.venv/
__pycache__/
*.pyc
```

### 建議不要公開 commit

```text
reports/*.txt
reports/*.json
data/latest_news_cache.json
*.zip
*.7z
```

原因：

- `.env` 可能含有 Gemini API key、Gmail App Password、LINE token
- `reports/` 內含每日分析結果與 grounding 來源，通常屬於個人使用紀錄
- 壓縮檔可能誤包進舊版 `.env` 或其他敏感資料

建議 `.gitignore` 至少包含：

```gitignore
.env
.venv/
__pycache__/
*.pyc
reports/*.txt
reports/*.json
data/latest_news_cache.json
*.zip
*.7z
```

若要保留 `reports/` 資料夾結構，可只 commit：

```text
reports/.gitkeep
```

---

## 常見問題

### 1. 為什麼今天沒有新資料？

可能原因：

- 今天是週末
- 今天是國定假日或補假
- 台股臨時休市
- TWSE 尚未更新資料
- 網路請求暫時失敗

程式會在報告中寫明目前判斷結果。

### 2. 為什麼主模型會切換到 Flash-Lite？

當主模型遇到可重試錯誤時，程式會嘗試改用備用模型。

常見可重試情況包含：

- `429`：額度或速率限制
- `500`：伺服器錯誤
- `503`：服務暫時不可用或模型過載
- `504`：逾時

### 3. Flash-Lite thinking budget 設為 24576 會怎樣？

`24576` 是 Gemini 2.5 Flash / Flash-Lite thinking budget 的高上限設定。好處是複雜分析時可給模型較多推理空間；代價是可能增加延遲與 token 消耗。

若你想節省額度，可以考慮改成較低數值，例如：

```env
GEMINI_THINKING_BUDGET_FALLBACK=4096
```

若你想讓模型自行調整，可以使用：

```env
GEMINI_THINKING_BUDGET_FALLBACK=-1
```

### 4. 可以完全不使用 LINE 嗎？

可以。

只要設定：

```env
LINE_PUSH_ENABLED=false
```

程式仍會產生完整報告並寄送 Email。

### 5. 可以完全不使用 OpenClaw 嗎？

可以，而且這就是目前版本的預設方向。

本版本的核心流程是：

```text
Windows Task Scheduler
        ↓
daily_tsmc_report.py
        ↓
TWSE 股價資料 + Gemini 分析
        ↓
reports/ + Email + optional LINE push
```

---

## 參考文件

- Gemini 2.5 Flash-Lite model：<https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite>
- Gemini thinking / thinkingBudget：<https://ai.google.dev/gemini-api/docs/thinking>
- Gemini Grounding with Google Search：<https://ai.google.dev/gemini-api/docs/google-search>
- 台灣證券交易所個股日成交資訊：<https://www.twse.com.tw/zh/trading/historical/stock-day.html>
- 行政院人事行政總處辦公日曆表：<https://www.dgpa.gov.tw/information?pid=12573&uid=41>

---

## 免責聲明

本專案僅作為個人自動化、資料處理、LLM API 串接與投資資訊整理練習。

程式產生的任何股價推估、買點、賣點、利多利空分析，皆不構成投資建議，也不保證正確性或獲利。使用者應自行查證資料來源，並自行承擔投資決策風險。
