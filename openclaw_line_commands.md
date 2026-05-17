# OpenClaw + LINE 的建議用法（雙軌制版）

## 核心原則
OpenClaw 不再負責重跑 Gemini 分析。
它只負責：
- 查今天報告是否已建立
- 讀取今天摘要
- 必要時手動重送 LINE 摘要

這樣可大幅降低 free tier 的 RPM / TPM 壓力。

## 你在本機可直接測的指令

### 1. 查今天狀態
```powershell
.\.venv\Scripts\python.exe .\openclaw_report_helper.py status --date today
```

### 2. 顯示今天摘要
```powershell
.\.venv\Scripts\python.exe .\openclaw_report_helper.py summary --date today --with-header
```

### 3. 顯示最後一份可用摘要
```powershell
.\.venv\Scripts\python.exe .\openclaw_report_helper.py summary --latest-available --with-header
```

### 4. 手動重送一次 LINE 摘要
```powershell
.\.venv\Scripts\python.exe .\openclaw_report_helper.py push-line --date today
```

### 5. 先 dry run 看看要送什麼
```powershell
.\.venv\Scripts\python.exe .\openclaw_report_helper.py push-line --date today --dry-run
```

## 給 OpenClaw 的建議訊息模板

### 範例 A：查今天狀態
Use the exec tool on the gateway host.
Workdir is C:\tsmc-agent .
Run exactly this command:
C:\tsmc-agent\.venv\Scripts\python.exe C:\tsmc-agent\openclaw_report_helper.py status --date today
Then reply with the command output only.

### 範例 B：讀今天摘要
Use the exec tool on the gateway host.
Workdir is C:\tsmc-agent .
Run exactly this command:
C:\tsmc-agent\.venv\Scripts\python.exe C:\tsmc-agent\openclaw_report_helper.py summary --date today --with-header
Then reply with the command output only.

### 範例 C：若今天還沒有報告，就改抓最後一份
Use the exec tool on the gateway host.
Workdir is C:\tsmc-agent .
First run:
C:\tsmc-agent\.venv\Scripts\python.exe C:\tsmc-agent\openclaw_report_helper.py status --date today
If today's report does not exist, run:
C:\tsmc-agent\.venv\Scripts\python.exe C:\tsmc-agent\openclaw_report_helper.py summary --latest-available --with-header
Otherwise run:
C:\tsmc-agent\.venv\Scripts\python.exe C:\tsmc-agent\openclaw_report_helper.py summary --date today --with-header
Reply with the final summary only.

## 建議的 LINE 指令設計
先做固定短指令，不要放太自由：
- status
- summary
- latest
- push
- help

原因：
1. 比較不會讓 OpenClaw 自作主張去重跑 LMM
2. 比較省 token
3. 比較容易除錯
