@echo off
cd /d "%~dp0"
echo Closing any old dashboard...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8790" ^| findstr "LISTENING"') do (
  taskkill /PID %%p /F >nul 2>&1
)
echo Opening bots dashboard...
python -m web.accounts_server
pause
