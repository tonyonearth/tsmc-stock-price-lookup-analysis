cd /d "%~dp0"

:: 常用的 python.exe，會出現指令視窗
:: .\.venv\Scripts\python .\daily_tsmc_report.py

:: pythonw.exe，不會出現指令視窗
.\.venv\Scripts\pythonw .\daily_tsmc_report.py
