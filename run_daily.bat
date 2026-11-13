@echo off
rem astock-monitor daily run (ASCII only - GBK lesson from csqaq-monitor lesson #3)
set PYTHONUTF8=1
cd /d %~dp0
echo [1/3] doctor self-check ...
python -m astock_monitor.cli doctor
echo [2/3] daily snapshot collect ...
python -m astock_monitor.cli collect-daily
echo [3/3] sentiment collect (zt pool + margin) ...
python -m astock_monitor.cli collect-sentiment
echo done.
