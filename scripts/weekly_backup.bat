@echo off
REM weekly backup (Sunday 23:00)
set PYTHONUTF8=1
cd /d %~dp0..
for /f %%i in ('python -c "from datetime import date; print(date.today().strftime('%%Y-%%m-%%d'))"') do set BKDIR=backups/%%i
if not exist "%BKDIR%" mkdir "%BKDIR%"
python -c "import sqlite3; src=sqlite3.connect('data/monitor.db'); dst=sqlite3.connect('%BKDIR%/monitor.db'); src.backup(dst); dst.close(); src.close(); print('db backed up')"
copy METHODS.md "%BKDIR%/" >nul
copy config.json "%BKDIR%/" >nul
copy results\*.json "%BKDIR%/" >nul 2>nul
echo backup complete: %BKDIR%
