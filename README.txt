這個版本已改成「雙軌制」：

A. 每日排程主流程
- daily_tsmc_report.py
- 會在同一次執行中完成：
  1) 查台積電股價
  2) 判斷是否開市 / 是否有新資料
  3) 呼叫 Gemini 做完整分析
  4) 產生完整報告 + LINE 短摘要 + meta.json
  5) 寄送 email
  6) 視 .env 設定，直接把摘要 push 到 LINE

B. OpenClaw 查詢流程
- openclaw_report_helper.py
- 給 OpenClaw / 手動查詢用，不再重跑 Gemini
- 只讀本機已建立的 report / summary / meta.json

主要新增檔案：
- tsmc_agent_common.py
- openclaw_report_helper.py

主要新增輸出：
- reports\YYYY-MM-DD_tsmc_report.txt
- reports\YYYY-MM-DD_tsmc_summary.txt
- reports\YYYY-MM-DD_tsmc_meta.json

建議安裝位置：
C:\tsmc-agent\

基本使用順序：
1. 把 `.env.example` 改名成 `.env`
2. 填入 Gemini / Gmail / LINE 參數
3. 安裝 requirements.txt
4. 手動跑一次 daily_tsmc_report.py
5. 確認 reports 底下三種檔案都有出來
6. 確認 email 正常
7. 若要每日自動推送 LINE，將 LINE_PUSH_ENABLED=true
8. 再設 Windows Task Scheduler
9. 要接 OpenClaw 時，再看 openclaw.json.example + openclaw_line_commands.md

10. LINE 設定細節可看 `line_setup.md`
11. OpenClaw 專用環境變數範本可看 `openclaw.env.example`
