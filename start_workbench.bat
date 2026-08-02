@echo off
REM ===================================
REM  工作台 启动脚本
REM  使用本地 .venv 中的 Python
REM ===================================
cd /d "%~dp0"
echo 正在启动工作台...
start "" ".venv\Scripts\pythonw.exe" server.py
echo 工作台已启动！
timeout /t 2 >nul
start http://127.0.0.1:8765
