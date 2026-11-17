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
rem 2026-11-18: decouple pipeline - collect failure no longer blocks signal chain
rem (11-16 lesson: EM outage blocked signal/judge for 2 days; signal uses lake index
rem  data and degrades honestly via gap banner. rc still reflects every failure.)
set COLLECT_FAIL=0
call :step doctor >> "%LOG%" 2>&1
if errorlevel 1 goto fail
call :step collect-daily >> "%LOG%" 2>&1
if errorlevel 1 (
  set COLLECT_FAIL=1
  echo [%DATE% %TIME%] WARN collect-daily failed, continuing with lake data >> "%LOG%"
)
rem index gap backfill via capability router (EM down -^> sina fallback)
call :py scripts\backfill_index_gap.py >> "%LOG%" 2>&1
if errorlevel 1 echo [%DATE% %TIME%] WARN index-gap backfill failed, signal will degrade >> "%LOG%"
call :step collect-sentiment >> "%LOG%" 2>&1
if errorlevel 1 (
  set COLLECT_FAIL=1
  echo [%DATE% %TIME%] WARN collect-sentiment failed, continuing >> "%LOG%"
)
rem 2026-11-14: close the daily loop - signal (session-day gated) -> judge -> scoreboard -> dashboard
call :step signal --require-session >> "%LOG%" 2>&1
if errorlevel 1 goto fail
call :step forecast-judge >> "%LOG%" 2>&1
if errorlevel 1 goto fail
call :step forecast-summary --out data\state\scoreboard_daily.json >> "%LOG%" 2>&1
if errorlevel 1 goto fail
call :py scripts\build_dashboard.py >> "%LOG%" 2>&1
if errorlevel 1 goto fail
if "%COLLECT_FAIL%"=="1" goto partial
echo [%DATE% %TIME%] DONE rc=0 >> "%LOG%"
exit /b 0

:partial
echo [%DATE% %TIME%] PARTIAL rc=2 (signal chain OK, collection degraded) >> "%LOG%"
if not defined CI echo Log: %LOG%
exit /b 2

:fail
set RC=%errorlevel%
echo [%DATE% %TIME%] FAILED rc=%RC% >> "%LOG%"
if not defined CI echo Log: %LOG%
exit /b %RC%

:py
echo.
echo ==== py %~1 ====
python %~1
exit /b %errorlevel%

:step
echo.
echo ==== %* ====
python -m astock_monitor.cli %*
exit /b %errorlevel%
