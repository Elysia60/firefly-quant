@echo off
rem astock-monitor daily run (ASCII only - GBK lesson from csqaq-monitor lesson #3)
rem 2026-11-14: log every step and propagate the exit code.
rem Reason: Task Scheduler reported Last Result 0 on 2026-11-13 while collection
rem silently failed (no parquet, no log) - a green light on a broken pipeline.
setlocal
rem unify console+log encoding: python emits UTF-8, cmd defaults to GBK -> mojibake in one log
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0
if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%i
if "%STAMP%"=="" set STAMP=manual
set LOG=logs\daily-%STAMP%.log

echo [%DATE% %TIME%] START >> "%LOG%"
call :step doctor >> "%LOG%" 2>&1
if errorlevel 1 goto fail
call :step collect-daily >> "%LOG%" 2>&1
if errorlevel 1 goto fail
call :step collect-sentiment >> "%LOG%" 2>&1
if errorlevel 1 goto fail
echo [%DATE% %TIME%] DONE rc=0 >> "%LOG%"
exit /b 0

:fail
set RC=%errorlevel%
echo [%DATE% %TIME%] FAILED rc=%RC% >> "%LOG%"
if not defined CI echo Log: %LOG%
exit /b %RC%

:step
echo.
echo ==== %~1 ====
python -m astock_monitor.cli %~1
exit /b %errorlevel%
